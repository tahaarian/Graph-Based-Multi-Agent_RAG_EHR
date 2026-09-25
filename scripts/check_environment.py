#!/usr/bin/env python3
"""Check the Python version and availability of project dependencies."""

from __future__ import annotations

import importlib
import sys

CORE_PACKAGES = ["neo4j", "qdrant_client", "pandas", "numpy", "langchain", "langgraph"]
OPTIONAL_PACKAGES = ["torch", "torch_geometric", "transformers"]
ALL_PACKAGES = CORE_PACKAGES + OPTIONAL_PACKAGES


def main() -> int:
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    if (version.major, version.minor) < (3, 11):
        print("ERROR: Python >= 3.11 is required (found "
              f"{version.major}.{version.minor}).")
        return 1
    print("Python version requirement (>= 3.11): OK\n")

    missing_core: list[str] = []
    for pkg in ALL_PACKAGES:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "unknown")
            print(f"  OK      {pkg:<18} {ver}")
        except ImportError:
            label = "MISSING (optional for Phase 0)" if pkg in OPTIONAL_PACKAGES else "MISSING"
            print(f"  {label:<24} {pkg}")
            if pkg not in OPTIONAL_PACKAGES:
                missing_core.append(pkg)

    print()
    if missing_core:
        print(f"RESULT: FAILED - missing core packages: {', '.join(missing_core)}")
        print("Install them with: pip install -r requirements.txt  (or: conda env create -f environment.yml)")
        return 1
    print("RESULT: OK - all core packages available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
