#!/usr/bin/env python3
"""Lightweight RDF 1.2 syntax conformance smoke runner.

Run ``npm ci && npm run spec`` for the W3C RDF 1.2 manifests. This script keeps
a small offline positive/negative subset in the repository for quick checks
without Node.js or network access.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyling.rdf import RdfSyntaxError, parse_rdf_text


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    fmt: str
    positive: bool = True


CASES = [
    Case("turtle-prefix", "PREFIX : <http://example/>\n:s :p :o .", "turtle"),
    Case("trig-named-graph", "PREFIX : <http://example/>\n:g { :s :p :o . }", "trig"),
    Case("nt-absolute", "<http://example/s> <http://example/p> <http://example/o> .", "nt"),
    Case("nt-relative-bad", "<//example/s> <http://example/p> <http://example/o> .", "nt", False),
    Case("nt-long-lang-bad", "<http://example/s> <http://example/p> \"x\"@cantbethislong .", "nt", False),
    Case("turtle-annotation-stripped", "PREFIX : <http://example/>\n:s :p :o {| :source :sensor |} .", "turtle"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args(argv)
    failures = 0
    for case in CASES:
        try:
            doc = parse_rdf_text(case.text, format=case.fmt, rdf12=True)
            ok = case.positive and bool(doc.triples)
        except Exception:
            ok = not case.positive
        print(("ok" if ok else "not ok"), case.name)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
