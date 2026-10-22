"""Thin process entry point for the layerguard CLI."""

from __future__ import annotations

from layerguard.cli import main


def main_entry() -> int:
    """Invoke the CLI and return its exit code."""
    return main()


if __name__ == "__main__":
    raise SystemExit(main())
