"""RDF/TriG/RDF 1.2 compatibility and RDF Message Log support.

This module deliberately keeps RDF compatibility outside the N3 rule parser.
The N3 parser remains formula/rule-oriented; RDF compatibility uses rdflib for
ordinary RDF syntaxes and a small surface-syntax adapter for RDF 1.2 constructs
that rdflib does not yet accept uniformly.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

from rdflib import BNode, Dataset, Graph, Literal as RdfLiteral, URIRef
from rdflib.namespace import RDF, XSD

from .parser import Document, N3SyntaxError, parse_n3
from .terms import (
    EYMSG_EMPTY,
    EYMSG_ENVELOPE,
    EYMSG_FIRST_ENVELOPE,
    EYMSG_LAST_ENVELOPE,
    EYMSG_MESSAGE_COUNT,
    EYMSG_MESSAGE_ENVELOPE,
    EYMSG_NEXT_ENVELOPE,
    EYMSG_NON_EMPTY,
    EYMSG_OFFSET,
    EYMSG_ORDERED_ENVELOPES,
    EYMSG_PAYLOAD_GRAPH,
    EYMSG_PAYLOAD_KIND,
    EYMSG_RDF_MESSAGE_STREAM,
    LOG_NAME_OF,
    RDF_TYPE,
    XSD_NS,
    Blank,
    GraphTerm,
    Iri,
    ListTerm,
    Literal,
    PrefixEnv,
    Rule,
    Term,
    Triple,
)

MESSAGE_VERSION_RE = re.compile(r"^\s*@?VERSION\s+['\"](?:1\.1|1\.2|1\.2-basic)-messages['\"]\s*\.?\s*(?:#.*)?$", re.I | re.M)
MESSAGE_LINE_RE = re.compile(r"^\s*@?MESSAGE\s*(?:#.*)?$", re.I)
PREFIX_LINE_RE = re.compile(r"^\s*(?:@prefix\s+([^\s]+)\s+<([^>]*)>\s*\.?|PREFIX\s+([^\s]+)\s+<([^>]*)>\s*\.?|@base\s+<([^>]*)>\s*\.?|BASE\s+<([^>]*)>\s*\.?)\s*(?:#.*)?$", re.I)
VERSION_LINE_RE = re.compile(
    r"^\s*(?:VERSION\s+(['\"])([^'\"\r\n]+)\1|@version\s+(['\"])([^'\"\r\n]+)\3\s*\.)\s*(?:#.*)?$",
    re.I,
)
RDF_REIFIES = str(RDF) + "reifies"
RDF12_PLACEHOLDER_PREFIX = "urn:pyling:rdf12:"


class RdfSyntaxError(SyntaxError):
    """Raised when the RDF compatibility parser rejects input."""


@dataclass(slots=True)
class RdfMessageChunk:
    index: int
    text: str
    triples: list[Triple]


# ---------------------------------------------------------------------------
# RDF 1.2 surface syntax checks and adapters
# ---------------------------------------------------------------------------

def _read_string_at(s: str, at: int) -> int:
    quote = s[at]
    long = s.startswith(quote * 3, at)
    i = at + (3 if long else 1)
    while i < len(s):
        if long and s.startswith(quote * 3, i):
            return i + 3
        ch = s[i]
        i += 1
        if ch == "\\" and i < len(s):
            i += 1
        elif not long and ch == quote:
            return i
    return i


def _read_iri_at(s: str, at: int) -> int:
    i = at + 1
    while i < len(s):
        ch = s[i]
        i += 1
        if ch == "\\" and i < len(s):
            i += 1
        elif ch == ">":
            return i
    return i


def _is_abs_iri(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value))


def _assert_valid_lang_tag(tag: str) -> None:
    if not re.match(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*(?:--(?:ltr|rtl))?$", tag):
        raise RdfSyntaxError(f"invalid RDF 1.2 language tag @{tag}")


def assert_rdf12_surface_syntax(text: str, *, format: str = "turtle") -> None:
    """Reject common RDF 1.2 negative-suite surface forms before parsing.

    rdflib is intentionally liberal in places and not yet complete for RDF 1.2
    triple terms / directional language syntax. These checks mirror the surface
    guards Eyeling uses for the W3C RDF 1.2 syntax tests.
    """
    data = str(text or "")
    if re.search(r"\\u[dD][89a-fA-F][0-9a-fA-F]{2}", data):
        raise RdfSyntaxError("RDF 1.2 numeric escapes must not encode UTF-16 surrogate code points")

    # Line syntaxes have stricter absolute IRI and no annotation constraints.
    if format in {"nt", "ntriples", "n-triples", "nq", "nquads", "n-quads"}:
        i = 0
        while i < len(data):
            ch = data[i]
            if ch == "#":
                while i < len(data) and data[i] not in "\r\n":
                    i += 1
                continue
            if ch in {'"', "'"}:
                end = _read_string_at(data, i)
                j = end
                if data.startswith("@", j):
                    j += 1
                    start = j
                    while j < len(data) and re.match(r"[A-Za-z0-9-]", data[j]):
                        j += 1
                    _assert_valid_lang_tag(data[start:j])
                elif data.startswith("^^<", j):
                    dt_end = _read_iri_at(data, j + 2)
                    dt = data[j + 3 : dt_end - 1]
                    if dt in {str(RDF.langString), str(RDF) + "dirLangString"}:
                        raise RdfSyntaxError(f"RDF datatype {dt} requires a language tag")
                i = end
                continue
            if ch == "<":
                if data.startswith("<<", i):
                    i += 2
                    continue
                end = _read_iri_at(data, i)
                iri = data[i + 1 : end - 1]
                if not _is_abs_iri(iri):
                    raise RdfSyntaxError(f"RDF line-syntax IRIREF must be absolute: <{iri}>")
                i = end
                continue
            if data.startswith("{|", i) or data.startswith("|}", i):
                raise RdfSyntaxError("RDF line syntax does not allow Turtle annotation syntax")
            i += 1



@dataclass(slots=True)
class _Rdf12Placeholder:
    kind: str
    triple: tuple[object, object, object] | None = None
    blank_label: str | None = None


def _strip_rdf12_versions(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if re.match(r"^\s*@?version\b", line, re.I):
            if not VERSION_LINE_RE.match(line.rstrip("\r\n")):
                raise RdfSyntaxError(f"invalid RDF 1.2 version directive: {line.strip()}")
            out.append("\n" if line.endswith("\n") else "")
        else:
            out.append(line)
    return "".join(out)


def _normalize_direction_tags(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] in {'"', "'"}:
            end = _read_string_at(text, i)
            out.append(text[i:end])
            i = end
            direction = re.match(
                r"@([A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*)--(?:ltr|rtl)\b",
                text[i:],
            )
            if direction:
                out.append("@" + direction.group(1))
                i += direction.end()
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _normalize_line_syntax_spacing(text: str) -> str:
    # RDF 1.2 line syntaxes allow token boundaries such as ``<s><p>`` where
    # the closing and opening delimiters are unambiguous. RDFLib's RDF 1.1
    # parsers require whitespace at those boundaries.
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] in {'"', "'"}:
            end = _read_string_at(text, i)
            out.append(text[i:end])
            i = end
            continue
        if text[i] == "#":
            end = i
            while end < len(text) and text[end] not in "\r\n":
                end += 1
            out.append(text[i:end])
            i = end
            continue
        if text[i] == "<":
            end = _read_iri_at(text, i)
            out.append(text[i:end])
            i = end
            if i < len(text) and text[i] in "<.":
                out.append(" ")
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _find_innermost_triple_construct(text: str) -> tuple[int, int] | None:
    stack: list[int] = []
    i = 0
    while i < len(text):
        if text[i] in {'"', "'"}:
            i = _read_string_at(text, i)
            continue
        if text[i] == "#":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if text.startswith("<<", i):
            stack.append(i)
            i += 2
            continue
        if text.startswith(">>", i):
            if not stack:
                raise RdfSyntaxError("unmatched >> in RDF 1.2 triple construct")
            return stack[-1], i + 2
        if text[i] == "<":
            i = _read_iri_at(text, i)
            continue
        i += 1
    if stack:
        raise RdfSyntaxError("unterminated RDF 1.2 triple construct")
    return None


def _find_unquoted(text: str, needle: str) -> int:
    i = 0
    while i < len(text):
        if text[i] in {'"', "'"}:
            i = _read_string_at(text, i)
            continue
        if text[i] == "<":
            i = _read_iri_at(text, i)
            continue
        if text[i] == "\\":
            i += 2
            continue
        if text.startswith(needle, i):
            return i
        i += 1
    return -1


def _rdf12_prelude(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if PREFIX_LINE_RE.match(line)) + "\n"


def _parse_turtle_fragment(fragment: str, *, prelude: str, base_iri: str | None) -> Graph:
    graph = Graph()
    try:
        graph.parse(data=prelude + fragment, format="turtle", publicID=base_iri)
    except Exception as exc:
        raise RdfSyntaxError(str(exc)) from exc
    return graph


def _validate_placeholder_positions(graph, placeholders: dict[str, _Rdf12Placeholder]) -> None:
    triples = graph.quads((None, None, None, None)) if isinstance(graph, Dataset) else graph.triples((None, None, None))
    for row in triples:
        s, p, _o = row[:3]
        subject_info = placeholders.get(str(s)) if isinstance(s, URIRef) else None
        predicate_info = placeholders.get(str(p)) if isinstance(p, URIRef) else None
        if subject_info and subject_info.kind == "triple":
            raise RdfSyntaxError("RDF 1.2 triple terms are not allowed in subject position")
        if predicate_info:
            raise RdfSyntaxError("RDF 1.2 triple constructs are not allowed in predicate position")


def _validate_embedded_triple(
    body: str,
    *,
    prelude: str,
    base_iri: str | None,
    placeholders: dict[str, _Rdf12Placeholder],
) -> tuple[object, object, object]:
    graph = _parse_turtle_fragment(_normalize_direction_tags(body) + " .", prelude=prelude, base_iri=base_iri)
    if len(graph) != 1:
        raise RdfSyntaxError("an RDF 1.2 triple construct must contain exactly one simple triple")
    _validate_placeholder_positions(graph, placeholders)
    triple = next(iter(graph))
    if not isinstance(triple[0], (URIRef, BNode)):
        raise RdfSyntaxError("an RDF 1.2 triple construct requires an IRI or blank node subject")
    if not isinstance(triple[1], URIRef):
        raise RdfSyntaxError("an RDF 1.2 triple construct requires an IRI predicate")
    return triple


def _validate_reifier_identifier(identifier: str, *, prelude: str, base_iri: str | None) -> None:
    if not identifier:
        return
    graph = _parse_turtle_fragment(
        f"{identifier} <urn:pyling:rdf12:predicate> <urn:pyling:rdf12:object> .",
        prelude=prelude,
        base_iri=base_iri,
    )
    if len(graph) != 1:
        raise RdfSyntaxError("an RDF 1.2 reifier identifier must be an IRI or blank node")


def _at_statement_start(text: str, at: int) -> bool:
    i = at - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0 or text[i] in ".{":
        return True
    line_start = max(text.rfind("\n", 0, at), text.rfind("\r", 0, at)) + 1
    previous_line_end = line_start - 1
    previous_line_start = max(
        text.rfind("\n", 0, previous_line_end), text.rfind("\r", 0, previous_line_end)
    ) + 1
    return bool(PREFIX_LINE_RE.match(text[previous_line_start:previous_line_end]))


def _normalize_triple_constructs(
    text: str,
    *,
    prelude: str,
    base_iri: str | None,
    format: str,
) -> tuple[str, dict[str, _Rdf12Placeholder]]:
    placeholders: dict[str, _Rdf12Placeholder] = {}
    counter = 0
    while True:
        span = _find_innermost_triple_construct(text)
        if span is None:
            break
        start, end = span
        raw = text[start + 2 : end - 2].strip()
        is_triple_term = raw.startswith("(") and raw.endswith(")")
        if format in {"nt", "ntriples", "n-triples", "nq", "nquads", "n-quads"} and not is_triple_term:
            raise RdfSyntaxError("N-Triples and N-Quads only allow parenthesized RDF 1.2 triple terms")
        if is_triple_term:
            body = raw[1:-1].strip()
            reifier_id = None
        else:
            tilde = _find_unquoted(raw, "~")
            body = raw[:tilde].strip() if tilde >= 0 else raw
            reifier_id = raw[tilde + 1 :].strip() if tilde >= 0 else None

        triple = _validate_embedded_triple(
            body,
            prelude=prelude,
            base_iri=base_iri,
            placeholders=placeholders,
        )
        counter += 1
        triple_iri = f"{RDF12_PLACEHOLDER_PREFIX}triple:{counter}"
        placeholders[triple_iri] = _Rdf12Placeholder("triple", triple=triple)

        if is_triple_term:
            replacement = f"<{triple_iri}>"
        else:
            if reifier_id is not None:
                _validate_reifier_identifier(reifier_id, prelude=prelude, base_iri=base_iri)
            if reifier_id:
                replacement = reifier_id
            else:
                reifier_iri = f"{RDF12_PLACEHOLDER_PREFIX}reifier:{counter}"
                placeholders[reifier_iri] = _Rdf12Placeholder(
                    "reifier", triple=triple, blank_label=f"_:rdf12_r{counter}"
                )
                replacement = f"<{reifier_iri}>"

            tail = text[end:]
            if _at_statement_start(text, start) and re.match(r"^\s*\.", tail):
                replacement += f" <{RDF_REIFIES}> <{triple_iri}>"

        text = text[:start] + " " + replacement + " " + text[end:]
    return text, placeholders


def _find_annotation(text: str) -> tuple[int, int] | None:
    i = 0
    start = -1
    while i < len(text):
        if text[i] in {'"', "'"}:
            i = _read_string_at(text, i)
            continue
        if text[i] == "#":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if text[i] == "<":
            i = _read_iri_at(text, i)
            continue
        if text.startswith("{|", i):
            if start >= 0:
                raise RdfSyntaxError("nested RDF 1.2 annotation blocks are not allowed")
            start = i
            i += 2
            continue
        if text.startswith("|}", i):
            if start < 0:
                raise RdfSyntaxError("unmatched RDF 1.2 annotation terminator")
            return start, i + 2
        i += 1
    if start >= 0:
        raise RdfSyntaxError("unterminated RDF 1.2 annotation block")
    return None


def _strip_and_validate_annotations(
    text: str,
    *,
    prelude: str,
    base_iri: str | None,
    placeholders: dict[str, _Rdf12Placeholder],
) -> str:
    while True:
        span = _find_annotation(text)
        if span is None:
            return text
        start, end = span
        body = text[start + 2 : end - 2].strip()
        if not body:
            raise RdfSyntaxError("RDF 1.2 annotation blocks must not be empty")
        graph = _parse_turtle_fragment(f"[] {body} .", prelude=prelude, base_iri=base_iri)
        if not graph:
            raise RdfSyntaxError("invalid RDF 1.2 annotation predicate-object list")
        _validate_placeholder_positions(graph, placeholders)
        text = text[:start] + " " + text[end:]


def _read_reifier_identifier(text: str, at: int) -> int:
    i = at
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] in ".;,}":
        return i
    if text[i] == "<":
        return _read_iri_at(text, i)
    if text[i] == "[" and text.startswith("[]", i):
        return i + 2
    while i < len(text) and not text[i].isspace() and text[i] not in ".;,}{|":
        i += 1
    return i


def _strip_reifier_suffixes(text: str, *, prelude: str, base_iri: str | None) -> str:
    i = 0
    out: list[str] = []
    while i < len(text):
        if text[i] in {'"', "'"}:
            end = _read_string_at(text, i)
            out.append(text[i:end])
            i = end
            continue
        if text[i] == "#":
            end = i
            while end < len(text) and text[end] not in "\r\n":
                end += 1
            out.append(text[i:end])
            i = end
            continue
        if text[i] == "<":
            end = _read_iri_at(text, i)
            out.append(text[i:end])
            i = end
            continue
        if text[i] == "~" and (i == 0 or text[i - 1] != "\\"):
            end = _read_reifier_identifier(text, i + 1)
            identifier = text[i + 1 : end].strip()
            _validate_reifier_identifier(identifier, prelude=prelude, base_iri=base_iri)
            out.append(" ")
            i = end
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _normalize_rdf12(
    text: str,
    *,
    base_iri: str | None,
    format: str,
) -> tuple[str, dict[str, _Rdf12Placeholder]]:
    data = _strip_rdf12_versions(text)
    prelude = _rdf12_prelude(data)
    data, placeholders = _normalize_triple_constructs(
        data,
        prelude=prelude,
        base_iri=base_iri,
        format=format,
    )
    data = _strip_and_validate_annotations(
        data,
        prelude=prelude,
        base_iri=base_iri,
        placeholders=placeholders,
    )
    data = _strip_reifier_suffixes(data, prelude=prelude, base_iri=base_iri)
    data = _normalize_direction_tags(data)
    if format in {"nt", "ntriples", "n-triples", "nq", "nquads", "n-quads"}:
        data = _normalize_line_syntax_spacing(data)
    return data, placeholders


# ---------------------------------------------------------------------------
# rdflib conversion
# ---------------------------------------------------------------------------

def _rdflib_term_to_term(
    term,
    placeholders: dict[str, _Rdf12Placeholder] | None = None,
    resolving: set[str] | None = None,
) -> Term:
    if isinstance(term, URIRef) and placeholders and str(term) in placeholders:
        key = str(term)
        info = placeholders[key]
        if info.kind == "reifier":
            return Blank(info.blank_label or "_:rdf12_reifier")
        if info.kind == "triple" and info.triple is not None:
            active = set() if resolving is None else set(resolving)
            if key in active:
                raise RdfSyntaxError("cyclic RDF 1.2 triple term")
            active.add(key)
            s, p, o = info.triple
            return GraphTerm(
                [
                    Triple(
                        _rdflib_term_to_term(s, placeholders, active),
                        _rdflib_term_to_term(p, placeholders, active),
                        _rdflib_term_to_term(o, placeholders, active),
                    )
                ]
            )
    if isinstance(term, URIRef):
        return Iri(str(term))
    if isinstance(term, BNode):
        return Blank("_:" + str(term))
    if isinstance(term, RdfLiteral):
        dt = str(term.datatype) if term.datatype else None
        lang = str(term.language).lower() if term.language else None
        return Literal(str(term), dt, lang)
    # rdflib RDF-star terms vary by version; keep a structural fallback.
    if hasattr(term, "subject") and hasattr(term, "predicate") and hasattr(term, "object"):
        return GraphTerm(
            [
                Triple(
                    _rdflib_term_to_term(term.subject, placeholders, resolving),
                    _rdflib_term_to_term(term.predicate, placeholders, resolving),
                    _rdflib_term_to_term(term.object, placeholders, resolving),
                )
            ]
        )
    return Iri(str(term))


def _format_alias(fmt: str | None) -> str:
    f = (fmt or "auto").lower().replace("_", "-")
    aliases = {
        "ttl": "turtle",
        "rdf12": "turtle",
        "rdf": "turtle",
        "ntriples": "nt",
        "n-triples": "nt",
        "nt": "nt",
        "nquads": "nquads",
        "n-quads": "nquads",
        "nq": "nquads",
        "trig": "trig",
        "turtle": "turtle",
        "xml": "xml",
        "json-ld": "json-ld",
    }
    return aliases.get(f, f)


def _guess_format(text: str, requested: str | None = None) -> str:
    if requested and requested.lower() != "auto":
        return _format_alias(requested)
    s = str(text or "")
    if re.search(r"(?m)^\s*(?:GRAPH\s+)?(?:<[^>]+>|[A-Za-z_][\w.-]*:|_:)\s*\{", s):
        return "trig"
    if re.search(r"(?m)^\s*<[^>]+>\s+<[^>]+>\s+", s):
        # Could be N-Triples/N-Quads. rdflib's turtle parser handles many NT
        # inputs, but line syntax has stricter RDF 1.2 checks.
        return "nt"
    return "turtle"


def _rdflib_parse(text: str, *, format: str, base_iri: str | None = None):
    fmt = _format_alias(format)
    data = str(text or "")
    if fmt in {"trig", "nquads"}:
        ds = Dataset(default_union=False)
        ds.parse(data=data, format=fmt, publicID=base_iri)
        return ds
    g = Graph()
    g.parse(data=data, format=fmt, publicID=base_iri)
    return g


def parse_rdf_text(text: str, *, format: str | None = None, base_iri: str | None = None, rdf12: bool = True, label: str | None = None) -> Document:
    """Parse RDF/Turtle/TriG/N-Triples/N-Quads text into an Eyeling Document."""
    source = str(text or "")
    fmt = _guess_format(source, format)
    placeholders: dict[str, _Rdf12Placeholder] = {}
    if rdf12:
        assert_rdf12_surface_syntax(source, format=fmt)
        data, placeholders = _normalize_rdf12(source, base_iri=base_iri, format=fmt)
    else:
        data = source

    env = PrefixEnv({})
    if base_iri:
        env.base_iri = base_iri

    graph = _rdflib_parse(data, format=fmt, base_iri=base_iri)
    _validate_placeholder_positions(graph, placeholders)
    triples: list[Triple] = []

    # Preserve only prefixes actually declared in the source. rdflib attaches a
    # long list of common namespaces to every graph; emitting those would make
    # Eyeling output noisy and unlike the JavaScript implementation.
    for line in source.splitlines():
        m = PREFIX_LINE_RE.match(line)
        if not m:
            continue
        if m.group(1) is not None or m.group(3) is not None:
            raw = m.group(1) or m.group(3) or ":"
            iri = m.group(2) or m.group(4) or ""
            if raw.endswith(":"):
                env.set_prefix(raw[:-1], iri, declared=True)
        elif m.group(5) or m.group(6):
            env.base_iri = m.group(5) or m.group(6)

    if isinstance(graph, Dataset):
        default_id = str(graph.default_graph.identifier)
        by_graph: dict[Term | None, list[Triple]] = {}
        for s, p, o, g in graph.quads((None, None, None, None)):
            tr = Triple(
                _rdflib_term_to_term(s, placeholders),
                _rdflib_term_to_term(p, placeholders),
                _rdflib_term_to_term(o, placeholders),
            )
            gid = (
                None
                if str(g) == default_id or str(g).endswith("default")
                else _rdflib_term_to_term(g, placeholders)
            )
            by_graph.setdefault(gid, []).append(tr)
        for gid, body in by_graph.items():
            if gid is None:
                triples.extend(body)
            else:
                triples.append(Triple(gid, Iri(LOG_NAME_OF), GraphTerm(body)))
    else:
        for s, p, o in graph:
            triples.append(
                Triple(
                    _rdflib_term_to_term(s, placeholders),
                    _rdflib_term_to_term(p, placeholders),
                    _rdflib_term_to_term(o, placeholders),
                )
            )
    return Document(env, triples, [], [], [])


# ---------------------------------------------------------------------------
# RDF Message Logs
# ---------------------------------------------------------------------------

def is_rdf_message_log(text: str) -> bool:
    return bool(MESSAGE_VERSION_RE.search(str(text or "")))


def _directive_prelude(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        if PREFIX_LINE_RE.match(line):
            lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def split_rdf_messages(text: str) -> list[str]:
    chunks = [""]
    for line in str(text or "").splitlines(True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            chunks[-1] += line
            continue
        if MESSAGE_VERSION_RE.match(line):
            continue
        if MESSAGE_LINE_RE.match(line):
            chunks.append("")
            continue
        chunks[-1] += line
    return chunks


def _parse_payload(chunk: str, prelude: str, idx: int, base_iri: str | None) -> list[Triple]:
    text = prelude + chunk
    if not text.strip():
        return []
    try:
        doc = parse_rdf_text(text, format="auto", base_iri=base_iri, rdf12=True)
    except Exception:
        # Some message logs contain simple N3 facts accepted by the core parser.
        doc = parse_n3(text, base_iri=base_iri, blank_prefix=f"_:eymsg_m{idx:03d}_")
    # Scope blank labels per message.
    def scoped(t: Term) -> Term:
        if isinstance(t, Blank):
            label = t.label[2:] if t.label.startswith("_:") else t.label
            return Blank(f"_:eymsg_m{idx:03d}_{re.sub(r'[^A-Za-z0-9_]', '_', label)}")
        if isinstance(t, ListTerm):
            return ListTerm(scoped(x) for x in t.elems)
        if isinstance(t, GraphTerm):
            return GraphTerm(Triple(scoped(x.s), scoped(x.p), scoped(x.o)) for x in t.triples)
        return t
    return [Triple(scoped(tr.s), scoped(tr.p), scoped(tr.o)) for tr in doc.triples]


def parse_rdf_message_log(text: str, *, base_iri: str | None = None, label: str | None = None) -> Document:
    """Parse a whole RDF Message Log into Eyeling's replay vocabulary."""
    source = str(text or "")
    if not is_rdf_message_log(source):
        raise RdfSyntaxError("input is not an RDF Message Log")
    prelude = _directive_prelude(source)
    chunks = split_rdf_messages(source)
    payloads = [_parse_payload(chunk, prelude, idx + 1, base_iri) for idx, chunk in enumerate(chunks)]
    return _message_replay_document(source, payloads, base_iri=base_iri)


def iter_rdf_message_documents(text: str, *, base_iri: str | None = None) -> Iterator[Document]:
    """Yield one replay document per RDF Message Log message."""
    source = str(text or "")
    if not is_rdf_message_log(source):
        raise RdfSyntaxError("input is not an RDF Message Log")
    prelude = _directive_prelude(source)
    for idx, chunk in enumerate(split_rdf_messages(source), start=1):
        payload = _parse_payload(chunk, prelude, idx, base_iri)
        yield _message_replay_document(source, [payload], base_iri=base_iri, first_index=idx)


def _message_replay_document(source: str, payloads: list[list[Triple]], *, base_iri: str | None = None, first_index: int = 1) -> Document:
    digest = hashlib.sha256(source.encode("utf8")).hexdigest()[:16]
    base = f"urn:eyeling:message-log:{digest}"
    stream = Iri(f"{base}#stream")
    envelopes = [Iri(f"{base}#m{idx:03d}") for idx in range(first_index, first_index + len(payloads))]
    payload_iris = [Iri(f"{env.value}/payload") for env in envelopes]
    triples: list[Triple] = []
    env = PrefixEnv({"eymsg": "https://eyereasoner.github.io/eyeling/vocab/message#"}, base_iri=base_iri)
    env.declared.add("eymsg")

    triples.append(Triple(stream, Iri(RDF_TYPE), Iri(EYMSG_RDF_MESSAGE_STREAM)))
    triples.append(Triple(stream, Iri(EYMSG_MESSAGE_COUNT), Literal(str(len(payloads)), XSD_NS + "integer", bare=True)))
    if envelopes:
        triples.append(Triple(stream, Iri(EYMSG_ORDERED_ENVELOPES), ListTerm(envelopes)))
        triples.append(Triple(stream, Iri(EYMSG_FIRST_ENVELOPE), envelopes[0]))
        triples.append(Triple(stream, Iri(EYMSG_LAST_ENVELOPE), envelopes[-1]))

    for i, body in enumerate(payloads):
        envelope = envelopes[i]
        payload = payload_iris[i]
        has_body = bool(body)
        offset = first_index + i
        triples.append(Triple(stream, Iri(EYMSG_ENVELOPE), envelope))
        triples.append(Triple(envelope, Iri(RDF_TYPE), Iri(EYMSG_MESSAGE_ENVELOPE)))
        triples.append(Triple(envelope, Iri(EYMSG_OFFSET), Literal(str(offset), XSD_NS + "integer", bare=True)))
        triples.append(Triple(envelope, Iri(EYMSG_PAYLOAD_KIND), Iri(EYMSG_NON_EMPTY if has_body else EYMSG_EMPTY)))
        if i + 1 < len(envelopes):
            triples.append(Triple(envelope, Iri(EYMSG_NEXT_ENVELOPE), envelopes[i + 1]))
        if has_body:
            triples.append(Triple(envelope, Iri(EYMSG_PAYLOAD_GRAPH), payload))
            triples.append(Triple(payload, Iri(LOG_NAME_OF), GraphTerm(body)))

    return Document(env, triples, [], [], [])
