"""Checked personal automatic launcher; no capture before the UI Start action."""
from __future__ import annotations

import argparse
import sys

from lvc.platform.windows.installed_launcher import preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--check-ui", action="store_true")
    action.add_argument("--version", action="store_true")
    args = parser.parse_args()
    build_id, errors, warnings = preflight()
    if args.version:
        print(f"Mithril Automatic {build_id}")
        return 0 if build_id != "unknown" else 2
    if errors:
        print(f"Mithril Automatic {build_id}: BLOCKED {','.join(errors)}")
        return 2
    for warning in warnings:
        print(f"Optional: {warning}")
    from lvc.platform.windows.lotro_auto_ui import main as auto_main

    if args.check:
        sys.argv = [sys.argv[0], "--check"]
    elif args.check_ui:
        sys.argv = [sys.argv[0], "--check-ui"]
    else:
        sys.argv = [sys.argv[0]]
    return auto_main()


if __name__ == "__main__":
    raise SystemExit(main())
