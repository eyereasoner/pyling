"""N3 rendering helpers."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .terms import (
    LOG_IMPLIED_BY,
    LOG_IMPLIES,
    OWL_SAME_AS,
    RDF_TYPE,
    Blank,
    GraphTerm,
    Iri,
    ListTerm,
    Literal,
    OpenListTerm,
    PrefixEnv,
    Term,
    Triple,
    Var,
    literal_datatype,
    quote_string,
)


def _literal_to_n3(lit: Literal, prefixes: PrefixEnv) -> str:
    if lit.bare:
        if lit.datatype and lit.datatype.endswith("#boolean"):
            if lit.lexical in {"1", "true", "True"}:
                return "true"
            if lit.lexical in {"0", "false", "False"}:
                return "false"
        return lit.lexical
    raw_lex = quote_string(lit.lexical)
    if lit.lang:
        return f"{raw_lex}@{lit.lang}"
    dt = lit.datatype
    if not dt or dt.endswith("#string"):
        return raw_lex
    qdt = prefixes.shrink_iri(dt)
    return f"{raw_lex}^^{qdt or '<' + dt + '>'}"


def term_to_n3(term: Term, prefixes: PrefixEnv | None = None) -> str:
    prefixes = prefixes or PrefixEnv({"": "http://example.org/"})
    if isinstance(term, Iri):
        q = prefixes.shrink_iri(term.value)
        if q is not None:
            return q
        if term.value.startswith("_:"):
            return term.value
        return f"<{term.value}>"
    if isinstance(term, Literal):
        return _literal_to_n3(term, prefixes)
    if isinstance(term, Var):
        return "?" + term.name
    if isinstance(term, Blank):
        return term.label
    if isinstance(term, ListTerm):
        return "(" + " ".join(term_to_n3(e, prefixes) for e in term.elems) + ")"
    if isinstance(term, OpenListTerm):
        return "(" + " ".join([*(term_to_n3(e, prefixes) for e in term.prefix), "?" + term.tail_var]) + ")"
    if isinstance(term, GraphTerm):
        if not term.triples:
            return "{ }"
        body = "\n".join("    " + triple_to_n3(t, prefixes).rstrip() for t in term.triples)
        return "{\n" + body + "\n}"
    return repr(term)


def triple_to_n3(tr: Triple, prefixes: PrefixEnv | None = None) -> str:
    prefixes = prefixes or PrefixEnv({"": "http://example.org/"})
    if isinstance(tr.p, Iri) and tr.p.value == LOG_IMPLIES:
        return f"{term_to_n3(tr.s, prefixes)} => {term_to_n3(tr.o, prefixes)} ."
    if isinstance(tr.p, Iri) and tr.p.value == LOG_IMPLIED_BY:
        return f"{term_to_n3(tr.s, prefixes)} <= {term_to_n3(tr.o, prefixes)} ."
    pred = "a" if isinstance(tr.p, Iri) and tr.p.value == RDF_TYPE else "=" if isinstance(tr.p, Iri) and tr.p.value == OWL_SAME_AS else term_to_n3(tr.p, prefixes)
    return f"{term_to_n3(tr.s, prefixes)} {pred} {term_to_n3(tr.o, prefixes)} ."


def prefix_lines(prefixes: PrefixEnv, triples: Iterable[Triple] = ()) -> list[str]:
    # Emit declared prefixes first. If none were declared but a default prefix exists,
    # keep outputs readable by emitting it.
    names = sorted(prefixes.declared, key=lambda x: (x != "", x))
    if not names and "" in prefixes.map:
        names = [""]
    lines = []
    for name in names:
        if name in prefixes.map:
            label = f"{name}:" if name else ":"
            lines.append(f"@prefix {label} <{prefixes.map[name]}> .")
    return lines


def triples_to_n3(triples: Iterable[Triple], prefixes: PrefixEnv, include_prefixes: bool = True) -> str:
    triples_list = list(triples)
    body = [triple_to_n3(t, prefixes) for t in triples_list]
    body = sorted(dict.fromkeys(body))
    if include_prefixes:
        pfx = prefix_lines(prefixes, triples_list)
        if pfx and body:
            return "\n".join(pfx) + "\n\n" + "\n".join(body) + "\n"
        if pfx:
            return "\n".join(pfx) + "\n"
    return ("\n".join(body) + "\n") if body else ""


def literal_as_output_string(term: Term) -> str:
    if isinstance(term, Literal):
        return term.lexical
    return term_to_n3(term)
