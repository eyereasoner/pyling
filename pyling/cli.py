from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import InferenceFuseError, reason, reason_message_stream
from .parser import N3SyntaxError
from .rdf import RdfSyntaxError


def format_n3_syntax_error(error: N3SyntaxError, text: str, label: str = "<input>") -> str:
    """Render syntax errors like the JavaScript Eyeling CLI."""
    offset = getattr(error, "offset", None)
    if not isinstance(offset, int):
        return f"Syntax error in {label}: {error}"
    offset = max(0, min(offset, len(text)))
    before = text[:offset]
    line = before.count("\n") + before.count("\r") - before.count("\r\n") + 1
    line_start = max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1
    line_end_candidates = [pos for pos in (text.find("\n", offset), text.find("\r", offset)) if pos >= 0]
    line_end = min(line_end_candidates) if line_end_candidates else len(text)
    column = offset - line_start + 1
    line_text = text[line_start:line_end]
    return f"Syntax error in {label}:{line}:{column}: {error}\n{line_text}\n{' ' * (column - 1)}^"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyling", description="Python Notation3/RDF reasoner compatible with Eyeling's core API")
    parser.add_argument("inputs", nargs="*", help="input files, or '-' for stdin")
    parser.add_argument("-p", "--proof", action="store_true", help="accepted for API compatibility; proof comments are not emitted")
    parser.add_argument("-d", "--derived", action="store_true", help="print derived facts (default)")
    parser.add_argument("-n", action="store_true", help=argparse.SUPPRESS)  # legacy notation3tests compatibility
    parser.add_argument("-r", "--rdf", action="store_true", help="enable RDF/Turtle/TriG/RDF Message compatibility mode")
    parser.add_argument("--rdf12", action="store_true", help="enable RDF 1.2 surface-syntax checks")
    parser.add_argument("--input-format", default="auto", help="auto, n3, turtle, trig, nt, nquads")
    parser.add_argument("--stream-messages", action="store_true", help="process RDF Message Logs one message at a time")
    parser.add_argument("--ast", action="store_true", help="print parsed AST JSON")
    parser.add_argument("--include-input-facts", action="store_true", help="include input facts in closure output")
    parser.add_argument("--max-iterations", type=int, default=1000)
    ns = parser.parse_args(argv)
    try:
        sources = []
        source_labels = []
        if not ns.inputs:
            sources.append(sys.stdin.read())
            source_labels.append("<stdin>")
        else:
            for name in ns.inputs:
                if name == "-":
                    sources.append(sys.stdin.read())
                    source_labels.append("<stdin>")
                else:
                    sources.append(Path(name).read_text(encoding="utf8"))
                    source_labels.append(name)
        input_data = {"sources": sources} if len(sources) > 1 else (sources[0] if sources else "")
        opts = {
            "proof": ns.proof,
            "ast": ns.ast,
            "rdf": ns.rdf or ns.rdf12,
            "rdf12": ns.rdf12 or ns.rdf,
            "input_format": ns.input_format,
            "include_input_facts_in_closure": ns.include_input_facts,
            "max_iterations": ns.max_iterations,
        }
        if ns.stream_messages:
            for result in reason_message_stream(input_data, opts):
                sys.stdout.write(result.closure_n3)
            return 0
        out = reason(opts, input_data)
        sys.stdout.write(out)
        return 0
    except InferenceFuseError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except N3SyntaxError as e:
        # The common CLI case has one source. For merged sources, use the
        # source index attached by the parser pipeline when available.
        index = getattr(e, "source_index", 0)
        if not isinstance(index, int) or not 0 <= index < len(sources):
            index = 0
        print(format_n3_syntax_error(e, sources[index], source_labels[index]), file=sys.stderr)
        return 1
    except (RdfSyntaxError, SyntaxError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
