"""Einstiegspunkt – `python -m sampling_tool` bzw. Console-Script `sampling-tool`."""

from __future__ import annotations

import sys

from sampling_tool import __version__


def main() -> int:
    """Startet die Anwendung. Stub – UI folgt in Sprint 4."""
    print(f"BDO Audit Sampling Tool v{__version__}")
    print("UI noch nicht implementiert (geplant für Sprint 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
