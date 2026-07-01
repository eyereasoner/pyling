import json
import os
import subprocess
import sys
from pathlib import Path


def test_offline_rdf12_conformance_smoke_runner_passes():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, str(root / "tools" / "run_rdf12_w3c.py")], cwd=str(root), text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_notation3tests_runner_is_present():
    root = Path(__file__).resolve().parents[1]
    runner = root / "tools" / "run_notation3tests.py"
    assert runner.exists()
    if os.environ.get("NOTATION3TESTS_DIR"):
        proc = subprocess.run([sys.executable, str(runner), os.environ["NOTATION3TESTS_DIR"]], cwd=str(root), text=True, capture_output=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_rdf_test_suite_bridge_reports_syntax_success_and_failure():
    root = Path(__file__).resolve().parents[1]
    bridge = root / "spec" / "parse.py"

    valid = json.dumps({
        "data": "<http://example/s> <http://example/p> <http://example/o> .",
        "format": "n-triples",
        "baseIRI": "http://example/base",
    })
    proc = subprocess.run(
        [sys.executable, str(bridge)], cwd=str(root), input=valid, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    invalid = json.dumps({
        "data": "<relative> <http://example/p> <http://example/o> .",
        "format": "n-triples",
        "baseIRI": "http://example/base",
    })
    proc = subprocess.run(
        [sys.executable, str(bridge)], cwd=str(root), input=invalid, text=True, capture_output=True
    )
    assert proc.returncode != 0
