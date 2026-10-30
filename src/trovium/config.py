"""Trovium's shared INI configuration.

The authoritative external schema is
``specs/002-server-deployment/contracts/config-schema.md``.  Secrets are never
stored here: credential keys hold environment-variable names only.
"""

from __future__ import annotations

import configparser
import contextlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from trovium.profiles import available_profiles, get_profile
from trovium.record import JsonStyle, Mode, OnFail, PostIngest

SCHEMA_VERSION = 1
CONFIG_FILE_ENV = "TROVIUM_CONFIG_FILE"
DEFAULT_CLIENT_USERNAME_ENV = "TROVIUM_CLIENT_USERNAME"
DEFAULT_CLIENT_PASSWORD_ENV = "TROVIUM_CLIENT_PASSWORD"

SOURCE_MODES = ("disk", "client")


class ConfigError(Exception):
    """A refused configuration read or write with a named cause."""


@dataclass(frozen=True)
class SourceSettings:
    """The configured download source, if any."""

    mode: str | None = None
    path: Path | None = None
    client_url: str | None = None
    client_username_env: str = DEFAULT_CLIENT_USERNAME_ENV
    client_password_env: str = DEFAULT_CLIENT_PASSWORD_ENV


@dataclass(frozen=True)
class IngestSettings:
    """Defaults passed to the ingest step."""

    profile: str = "video"
    category: str = "all"
    mode: Mode = Mode.AUTO
    post_ingest: PostIngest = PostIngest.KEEP
    on_fail: OnFail = OnFail.CONTINUE
    json: JsonStyle = JsonStyle.PRETTY


@dataclass(frozen=True)
class TroviumConfig:
    """A validated configuration file."""

    path: Path
    schema_version: int
    library_root: Path | None
    source: SourceSettings
    ingest: IngestSettings


@dataclass(frozen=True)
class LoadedConfig:
    """A loaded configuration plus non-fatal observations."""

    config: TroviumConfig
    warnings: tuple[str, ...] = ()


def config_path(explicit: str | Path | None = None) -> Path:
    """Resolve the single canonical config path.

    Precedence: an explicit path, ``TROVIUM_CONFIG_FILE``, then XDG.
    """

    if explicit is not None:
        return Path(explicit).expanduser()
    override = os.environ.get(CONFIG_FILE_ENV)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "trovium" / "config.ini"


def _read_parser(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as error:
        raise ConfigError(f"cannot read config {path}: {error}") from error
    except configparser.Error as error:
        raise ConfigError(f"invalid config syntax in {path}: {error}") from error
    return parser


def _optional(parser: configparser.ConfigParser, section: str, key: str) -> str | None:
    value = parser.get(section, key, fallback=None)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_int(value: str | None, *, name: str) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from error


def _parse_enum[EnumT: StrEnum](
    value: str | None,
    enum: type[EnumT],
    *,
    name: str,
    default: EnumT,
) -> EnumT:
    if value is None:
        return default
    try:
        return enum(value)
    except ValueError as error:
        allowed = ", ".join(item.value for item in enum)
        raise ConfigError(f"{name} must be one of: {allowed}") from error


def _validate_client_url(value: str | None) -> None:
    if value is None:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(
            "client_url must be an absolute http or https URL without userinfo"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(
            "client_url must not contain userinfo; put credentials in the named "
            "environment variables instead"
        )


def _validate_env_name(value: str, *, name: str) -> None:
    if not value or "=" in value or any(character.isspace() for character in value):
        raise ConfigError(f"{name} must be a non-empty environment-variable name")


def parse_config(path: Path) -> tuple[TroviumConfig, tuple[str, ...]]:
    """Parse and validate an existing config file without mutating it."""

    parser = _read_parser(path)
    warnings: list[str] = []
    schema_version = _parse_int(
        _optional(parser, "meta", "schema_version"), name="schema_version"
    )
    if schema_version > SCHEMA_VERSION:
        warnings.append(
            f"config schema {schema_version} is newer than supported "
            f"{SCHEMA_VERSION}; it will not be rewritten"
        )
    elif schema_version < SCHEMA_VERSION:
        warnings.append(
            "config schema is missing or older; the installer will back it up "
            "and migrate it"
        )

    library_value = _optional(parser, "library", "root")
    library_root = Path(library_value).expanduser() if library_value else None

    mode = _optional(parser, "source", "mode")
    if mode is not None and mode not in SOURCE_MODES:
        raise ConfigError("source mode must be 'disk' or 'client'")
    source_path_value = _optional(parser, "source", "path")
    source_path = Path(source_path_value).expanduser() if source_path_value else None
    client_url = _optional(parser, "source", "client_url")
    _validate_client_url(client_url)
    if mode == "disk" and source_path is None:
        raise ConfigError("source mode is 'disk' but source path is not set")
    if mode == "client" and client_url is None:
        raise ConfigError("source mode is 'client' but client_url is not set")
    if source_path is not None and client_url is not None:
        raise ConfigError("source path and client_url are mutually exclusive")
    username_env = _optional(parser, "source", "client_username_env") or (
        DEFAULT_CLIENT_USERNAME_ENV
    )
    password_env = _optional(parser, "source", "client_password_env") or (
        DEFAULT_CLIENT_PASSWORD_ENV
    )
    _validate_env_name(username_env, name="client_username_env")
    _validate_env_name(password_env, name="client_password_env")

    profile_name = _optional(parser, "ingest", "profile") or "video"
    try:
        profile = get_profile(profile_name)
    except KeyError as error:
        allowed = ", ".join(available_profiles())
        raise ConfigError(f"ingest profile must be one of: {allowed}") from error
    category = _optional(parser, "ingest", "category") or "all"
    if category not in profile.categories:
        allowed = ", ".join(profile.categories)
        raise ConfigError(
            f"ingest category for profile '{profile.name}' must be one of: {allowed}"
        )

    ingest = IngestSettings(
        profile=profile.name,
        category=category,
        mode=_parse_enum(
            _optional(parser, "ingest", "mode"),
            Mode,
            name="ingest mode",
            default=Mode.MOVE,
        ),
        post_ingest=_parse_enum(
            _optional(parser, "ingest", "post_ingest"),
            PostIngest,
            name="ingest post_ingest",
            default=PostIngest.KEEP,
        ),
        on_fail=_parse_enum(
            _optional(parser, "ingest", "on_fail"),
            OnFail,
            name="ingest on_fail",
            default=OnFail.CONTINUE,
        ),
        json=_parse_enum(
            _optional(parser, "ingest", "json"),
            JsonStyle,
            name="ingest json",
            default=JsonStyle.PRETTY,
        ),
    )
    config = TroviumConfig(
        path=path,
        schema_version=max(schema_version, 0),
        library_root=library_root,
        source=SourceSettings(
            mode=mode,
            path=source_path,
            client_url=client_url,
            client_username_env=username_env,
            client_password_env=password_env,
        ),
        ingest=ingest,
    )
    return config, tuple(warnings)


def load_config(
    explicit: str | Path | None = None, *, required: bool = False
) -> LoadedConfig | None:
    """Load the default config if present, or a required explicit config."""

    path = config_path(explicit)
    if not path.exists():
        if required or explicit is not None:
            raise ConfigError(f"config file does not exist: {path}")
        return None
    config, warnings = parse_config(path)
    return LoadedConfig(config=config, warnings=warnings)


def migrate_config(path: Path) -> Path | None:
    """Add the schema version to an older config, backing it up first.

    Returns the backup path when a rewrite happened.  A newer schema is left
    untouched.
    """

    parser = _read_parser(path)
    current = _parse_int(
        _optional(parser, "meta", "schema_version"), name="schema_version"
    )
    if current > SCHEMA_VERSION:
        return None
    if current == SCHEMA_VERSION:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    backup.chmod(0o600)
    if not parser.has_section("meta"):
        parser.add_section("meta")
    parser.set("meta", "schema_version", str(SCHEMA_VERSION))
    _write_parser(path, parser)
    return backup


def _write_parser(path: Path, parser: configparser.ConfigParser) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write("# trovium configuration. Schema 1.\n")
        parser.write(handle)
    temporary.chmod(0o600)
    temporary.replace(path)


def write_default_config(
    path: Path,
    *,
    library_root: Path,
    source_mode: str | None = None,
    source_path: Path | None = None,
    client_url: str | None = None,
    ingest: IngestSettings | None = None,
) -> None:
    """Create a new config when none exists.  Never overwrites."""

    if path.exists():
        raise ConfigError(f"refusing to overwrite existing config: {path}")
    if source_mode is not None and source_mode not in SOURCE_MODES:
        raise ConfigError("source mode must be 'disk' or 'client'")
    if source_mode == "disk" and source_path is None:
        raise ConfigError("source mode is 'disk' but no path was supplied")
    if source_mode == "client" and client_url is None:
        raise ConfigError("source mode is 'client' but no client URL was supplied")
    if source_path is not None and client_url is not None:
        raise ConfigError("source path and client_url are mutually exclusive")
    _validate_client_url(client_url)

    settings = ingest or IngestSettings()
    parser = configparser.ConfigParser(interpolation=None)
    parser["meta"] = {"schema_version": str(SCHEMA_VERSION)}
    parser["library"] = {"root": str(library_root)}
    if source_mode is not None:
        section = {"mode": source_mode}
        if source_path is not None:
            section["path"] = str(source_path)
        if client_url is not None:
            section["client_url"] = client_url
        section["client_username_env"] = DEFAULT_CLIENT_USERNAME_ENV
        section["client_password_env"] = DEFAULT_CLIENT_PASSWORD_ENV
        parser["source"] = section
    parser["ingest"] = {
        "profile": settings.profile,
        "category": settings.category,
        "mode": settings.mode.value,
        "post_ingest": settings.post_ingest.value,
        "on_fail": settings.on_fail.value,
        "json": settings.json.value,
    }
    _write_parser(path, parser)


def copy_config(source: Path, destination: Path) -> bool:
    """Copy a supplied config to the canonical path when absent.

    Returns True when a copy happened.  An existing destination wins.
    """

    if destination.exists():
        return False
    if not source.exists():
        raise ConfigError(f"supplied config does not exist: {source}")
    parse_config(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        destination.parent.chmod(0o700)
    shutil.copy2(source, destination)
    destination.chmod(0o600)
    return True


def tighten_permissions(path: Path) -> bool:
    """Set a config file to owner-only and report whether it changed."""

    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return False
    if mode == 0o600:
        return False
    path.chmod(0o600)
    return True


__all__ = [
    "CONFIG_FILE_ENV",
    "SCHEMA_VERSION",
    "ConfigError",
    "IngestSettings",
    "LoadedConfig",
    "SourceSettings",
    "TroviumConfig",
    "config_path",
    "copy_config",
    "load_config",
    "migrate_config",
    "parse_config",
    "tighten_permissions",
    "write_default_config",
]
