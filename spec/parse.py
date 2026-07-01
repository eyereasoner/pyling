#!/usr/bin/env python3
"""Bridge rdf-test-suite syntax cases to pyling's RDF parser."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyling.rdf import parse_rdf_text


def main() -> int:
    request = json.load(sys.stdin)
    parse_rdf_text(
        request["data"],
        format=request["format"],
        base_iri=request.get("baseIRI"),
        rdf12=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
