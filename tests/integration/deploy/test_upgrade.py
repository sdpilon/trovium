"""Integration: upgrade, downgrade, and media safety (US3, SC-005/SC-008)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def _inventory(*roots: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                inventory[str(path)] = digest
    return inventory


def test_upgrade_preserves_a_customized_config(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    with layout.config.open("a", encoding="utf-8") as handle:
        handle.write("\n# operator note\n")
    config_before = layout.config.read_bytes()

    upgraded = report(install(layout, newer_bundle, _standard(layout)))

    assert upgraded["operation"] == "upgrade"
    assert upgraded["version"] == "0.2.0"
    assert upgraded["previous_version"] == "0.1.0"
    assert layout.config.read_bytes() == config_before
    help_result = deploy(layout, "status", "--json", "compact")
    assert json.loads(help_result.stdout)["version"] == "0.2.0"
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["version"] == "0.2.0"
    assert record["previous_version"] == "0.1.0"


def test_downgrade_by_reinstalling_an_earlier_bundle(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    report(install(layout, newer_bundle, _standard(layout)))
    config_before = layout.config.read_bytes()

    downgraded = report(install(layout, bundle, _standard(layout)))

    assert downgraded["version"] == "0.1.0"
    assert downgraded["previous_version"] == "0.2.0"
    assert layout.config.read_bytes() == config_before
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["version"] == "0.1.0"
    assert record["previous_version"] == "0.2.0"


def test_media_integrity_across_install_upgrade_downgrade_and_uninstall(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    before = _inventory(layout.library, layout.source)

    report(install(layout, bundle, _standard(layout)))
    assert _inventory(layout.library, layout.source) == before

    report(install(layout, newer_bundle, _standard(layout)))
    assert _inventory(layout.library, layout.source) == before

    report(install(layout, bundle, _standard(layout)))
    assert _inventory(layout.library, layout.source) == before

    uninstall = deploy(layout, "uninstall", "--json", "compact")
    assert uninstall.returncode == 0
    assert _inventory(layout.library, layout.source) == before
    assert layout.config.exists()

    report(install(layout, bundle, _standard(layout)))
    assert _inventory(layout.library, layout.source) == before

    purge = deploy(layout, "uninstall", "--purge", "--json", "compact")
    assert purge.returncode == 0
    assert not layout.config.exists()
    assert _inventory(layout.library, layout.source) == before
