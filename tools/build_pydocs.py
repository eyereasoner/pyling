"""Build the standard-library pydoc pages for the pyling package."""

from __future__ import annotations

import argparse
import os
import pkgutil
import pydoc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyling


def module_names() -> list[str]:
    """Return the package and all of its importable submodules."""
    names = [pyling.__name__]
    names.extend(
        module.name
        for module in pkgutil.walk_packages(pyling.__path__, prefix=f"{pyling.__name__}.")
    )
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=Path("site/api"),
        help="directory in which to write the HTML pages (default: site/api)",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_dir = Path.cwd()
    try:
        os.chdir(output_dir)
        for name in module_names():
            pydoc.writedoc(name)
    finally:
        os.chdir(previous_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
