#!/usr/bin/env python3
"""
k8s_manifest_gui.py - entry point.

    python3 k8s_manifest_gui.py            # launch the GUI
    python3 k8s_manifest_gui.py --check    # only run dependency checks
    python3 k8s_manifest_gui.py --no-install   # don't auto pip-install PyYAML

First run: verifies tkinter is available (prints install hints if not) and
pip-installs PyYAML if missing (see bootstrap.py for the strategy).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bootstrap  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kubernetes manifest generator GUI")
    ap.add_argument("--check", action="store_true", help="check dependencies and exit")
    ap.add_argument("--no-install", action="store_true", help="do not auto-install PyYAML")
    args = ap.parse_args(argv)

    if sys.version_info < (3, 8):
        print("Python 3.8+ is required.", file=sys.stderr)
        return 1
    tk_ok = bootstrap.check_tkinter()
    yaml = bootstrap.ensure_pyyaml(auto_install=not args.no_install)
    if args.check:
        print(bootstrap.summary())
        print(f"tkinter: {'OK' if tk_ok else 'MISSING'}   PyYAML: {yaml.__version__}")
        return 0 if tk_ok else 1
    if not tk_ok:
        return 1
    import gui_app
    gui_app.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
