"""trovium — unix-philosophy replacements for the *arr media-automation stack.

Each pipeline step is an independent, single-purpose command-line tool that
composes with the others over explicit streams. See the project constitution
(``.specify/memory/constitution.md``) for the principles this package is built
to satisfy.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("trovium")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
