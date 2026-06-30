#!/usr/bin/env python3
"""Run phochste/notation3tests against the local Python package.

Usage:
  python tools/run_notation3tests.py /path/to/notation3tests
  python tools/run_notation3tests.py --clone

The script intentionally does not depend on RDF-JS, browser bundles, or Node
packaging. It creates a tiny reasoner command shim that calls this package's
`pyling` CLI and then runs the notation3tests target that is present in the
checked-out suite.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://codeberg.org/phochste/notation3tests.git"


def run(cmd: list[str], cwd: Path | None = None) -> int:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return p.returncode


def make_shim(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pyling.cli import main\n"
        "raise SystemExit(main(sys.argv[1:]))\n",
        encoding="utf8",
    )
    path.chmod(0o755)


def remove_skipped_network_outputs(suite: Path) -> None:
    """Prevent stale results from being counted for NETWORKING=0 fixtures."""
    tests = suite / "tests"
    if not tests.exists():
        return
    for source in tests.rglob("*.n3"):
        try:
            is_network_test = "@pragma networking" in source.read_text(encoding="utf8")
        except (OSError, UnicodeError):
            continue
        if is_network_test:
            Path(str(source) + ".out").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", nargs="?", help="path to a notation3tests checkout")
    ap.add_argument("--clone", action="store_true", help="clone the Codeberg suite into a temporary directory")
    ap.add_argument("--keep", action="store_true", help="keep a temporary clone")
    ns = ap.parse_args(argv)

    tmp = None
    if ns.clone:
        tmp = Path(tempfile.mkdtemp(prefix="notation3tests-"))
        suite = tmp / "notation3tests"
        code = run(["git", "clone", "--depth", "1", REPO, str(suite)])
        if code:
            return code
    elif ns.suite:
        suite = Path(ns.suite).resolve()
    else:
        ap.error("provide a suite path or --clone")

    if not suite.exists():
        print(f"suite not found: {suite}", file=sys.stderr)
        return 2

    shim_dir = Path(tempfile.mkdtemp(prefix="pyling-shim-"))
    try:
        make_shim(shim_dir / "eyeling")
        env = os.environ.copy()
        env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        # The Python port intentionally does not perform Web dereferencing.
        # Callers can explicitly set NETWORKING=1 when testing an extension
        # that adds it; otherwise report only the locally executable corpus.
        env.setdefault("NETWORKING", "0")
        if env["NETWORKING"] == "0":
            remove_skipped_network_outputs(suite)
        # The suite has varied over time. Prefer a Python/pytest target when
        # present, otherwise use the published npm target for Eyeling adapters.
        # A directory named tests is not evidence of a pytest project: the
        # npm-based notation3tests repository stores its N3 fixtures there.
        if (suite / "pytest.ini").exists() or (suite / "pyproject.toml").exists():
            code = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(suite), env=env).returncode
        elif (suite / "package.json").exists():
            target = "test:eyeling" if "test:eyeling" in (suite / "package.json").read_text(encoding="utf8") else "test"
            code = subprocess.run(["npm", "run", target], cwd=str(suite), env=env).returncode
        else:
            print("Could not identify how to run notation3tests in this checkout", file=sys.stderr)
            code = 2
        return code
    finally:
        shutil.rmtree(shim_dir, ignore_errors=True)
        if tmp and not ns.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        elif tmp:
            print(f"kept temporary clone: {tmp}")


if __name__ == "__main__":
    raise SystemExit(main())
