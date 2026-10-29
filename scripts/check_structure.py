"""Structural sanity check: required files exist and every .py file compiles.

Run from anywhere: `python scripts/check_structure.py`. Exit code 1 on failure.
"""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "app.py", "requirements.txt", ".gitignore", ".env.example", "README.md",
    "config/settings.py", "modules/contracts.py",
    "docs/project_requirements.md", "docs/system_architecture.md",
    "docs/dataset_specification.md", "docs/module_interfaces.md", "docs/development_plan.md",
]


def main() -> int:
    missing = [f for f in REQUIRED if not (ROOT / f).exists()]
    errors: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in {".venv", "venv"} for part in path.parts):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))
    for f in missing:
        print(f"MISSING  {f}")
    for e in errors:
        print(f"SYNTAX   {e}")
    print("OK" if not (missing or errors) else "FAILED")
    return 1 if (missing or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
