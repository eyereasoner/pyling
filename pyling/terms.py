"""Core term model for pyling."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence, Tuple

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
XSD_NS = "http://www.w3.org/2001/XMLSchema#"
MATH_NS = "http://www.w3.org/2000/10/swap/math#"
TIME_NS = "http://www.w3.org/2000/10/swap/time#"
LIST_NS = "http://www.w3.org/2000/10/swap/list#"
LOG_NS = "http://www.w3.org/2000/10/swap/log#"
STRING_NS = "http://www.w3.org/2000/10/swap/string#"
CRYPTO_NS = "http://www.w3.org/2000/10/swap/crypto#"
DT_NS = "https://eyereasoner.github.io/eyeling/datatype#"
SKOLEM_NS = "https://eyereasoner.github.io/.well-known/genid/"

RDF_TYPE = RDF_NS + "type"
RDF_FIRST = RDF_NS + "first"
RDF_REST = RDF_NS + "rest"
RDF_NIL = RDF_NS + "nil"
OWL_SAME_AS = OWL_NS + "sameAs"
OWL_DIFFERENT_FROM = OWL_NS + "differentFrom"
LOG_IMPLIES = LOG_NS + "implies"
LOG_IMPLIED_BY = LOG_NS + "impliedBy"
LOG_QUERY = LOG_NS + "query"
LOG_OUTPUT_STRING = LOG_NS + "outputString"
LOG_NAME_OF = LOG_NS + "nameOf"

EYMSG_NS = "https://eyereasoner.github.io/eyeling/vocab/message#"
EYMSG_RDF_MESSAGE_STREAM = EYMSG_NS + "RDFMessageStream"
EYMSG_MESSAGE_ENVELOPE = EYMSG_NS + "MessageEnvelope"
EYMSG_ENVELOPE = EYMSG_NS + "envelope"
EYMSG_FIRST_ENVELOPE = EYMSG_NS + "firstEnvelope"
EYMSG_LAST_ENVELOPE = EYMSG_NS + "lastEnvelope"
EYMSG_ORDERED_ENVELOPES = EYMSG_NS + "orderedEnvelopes"
EYMSG_MESSAGE_COUNT = EYMSG_NS + "messageCount"
EYMSG_OFFSET = EYMSG_NS + "offset"
EYMSG_NEXT_ENVELOPE = EYMSG_NS + "nextEnvelope"
EYMSG_PAYLOAD_GRAPH = EYMSG_NS + "payloadGraph"
EYMSG_PAYLOAD_KIND = EYMSG_NS + "payloadKind"
EYMSG_EMPTY = EYMSG_NS + "empty"
EYMSG_NON_EMPTY = EYMSG_NS + "nonEmpty"

STD_PREFIXES = {
    "rdf": RDF_NS,
    "rdfs": RDFS_NS,
    "owl": OWL_NS,
    "xsd": XSD_NS,
    "math": MATH_NS,
    "time": TIME_NS,
    "list": LIST_NS,
    "log": LOG_NS,
    "string": STRING_NS,
    "crypto": CRYPTO_NS,
    "dt": DT_NS,
    "eymsg": EYMSG_NS,
}

_NUMERIC_DT = {
    XSD_NS + "integer",
    XSD_NS + "int",
    XSD_NS + "long",
    XSD_NS + "short",
    XSD_NS + "byte",
    XSD_NS + "nonNegativeInteger",
    XSD_NS + "positiveInteger",
    XSD_NS + "nonPositiveInteger",
    XSD_NS + "negativeInteger",
    XSD_NS + "unsignedLong",
    XSD_NS + "unsignedInt",
    XSD_NS + "unsignedShort",
    XSD_NS + "unsignedByte",
    XSD_NS + "decimal",
    XSD_NS + "double",
    XSD_NS + "float",
}


class Term:
    """Marker base class."""


@dataclass(frozen=True, slots=True)
class Iri(Term):
    value: str


@dataclass(frozen=True, slots=True)
class Var(Term):
    name: str


@dataclass(frozen=True, slots=True)
class Blank(Term):
    label: str


@dataclass(frozen=True, slots=True)
class Literal(Term):
    lexical: str
    datatype: Optional[str] = None
    lang: Optional[str] = None
    raw: Optional[str] = None
    bare: bool = False

    def normalized_lang(self) -> Optional[str]:
        return self.lang.lower() if self.lang else None


@dataclass(frozen=True, slots=True)
class ListTerm(Term):
    elems: Tuple[Term, ...] = field(default_factory=tuple)

    def __init__(self, elems: Iterable[Term] = ()):  # type: ignore[override]
        object.__setattr__(self, "elems", tuple(elems))


@dataclass(frozen=True, slots=True)
class OpenListTerm(Term):
    prefix: Tuple[Term, ...]
    tail_var: str

    def __init__(self, prefix: Iterable[Term], tail_var: str):  # type: ignore[override]
        object.__setattr__(self, "prefix", tuple(prefix))
        object.__setattr__(self, "tail_var", tail_var)


@dataclass(frozen=True, slots=True)
class GraphTerm(Term):
    triples: Tuple["Triple", ...] = field(default_factory=tuple)

    def __init__(self, triples: Iterable["Triple"] = ()):  # type: ignore[override]
        object.__setattr__(self, "triples", tuple(triples))


@dataclass(frozen=True, slots=True)
class Triple:
    s: Term
    p: Term
    o: Term


@dataclass(frozen=True, slots=True)
class Rule:
    premise: Tuple[Triple, ...]
    conclusion: Tuple[Triple, ...]
    is_forward: bool = True
    is_fuse: bool = False

    def __init__(self, premise: Iterable[Triple], conclusion: Iterable[Triple] = (), is_forward: bool = True, is_fuse: bool = False):  # type: ignore[override]
        object.__setattr__(self, "premise", tuple(premise))
        object.__setattr__(self, "conclusion", tuple(conclusion))
        object.__setattr__(self, "is_forward", bool(is_forward))
        object.__setattr__(self, "is_fuse", bool(is_fuse))


@dataclass(slots=True)
class PrefixEnv:
    map: dict[str, str] = field(default_factory=dict)
    base_iri: Optional[str] = None
    declared: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        merged = dict(STD_PREFIXES)
        merged.update(self.map)
        self.map = merged

    def copy(self) -> "PrefixEnv":
        env = PrefixEnv(dict(self.map), self.base_iri)
        env.declared = set(self.declared)
        return env

    def set_prefix(self, name: str, iri: str, declared: bool = True) -> None:
        self.map[name] = iri
        if declared:
            self.declared.add(name)

    def expand(self, qname: str) -> str:
        if ":" not in qname:
            raise ValueError(f"not a prefixed name: {qname}")
        pfx, local = qname.split(":", 1)
        if pfx not in self.map:
            raise ValueError(f"unknown prefix {pfx!r} in {qname!r}")
        return self.map[pfx] + local

    def shrink_iri(self, iri: str) -> Optional[str]:
        # Prefer declared prefixes and the default prefix, then standards.
        keys = list(self.declared)
        if "" in self.map and "" not in keys:
            keys.insert(0, "")
        keys += [k for k in STD_PREFIXES if k not in keys]
        # Longest namespace first prevents rdf: and custom overlaps.
        keys = sorted(set(keys), key=lambda k: len(self.map.get(k, "")), reverse=True)
        for pfx in keys:
            ns = self.map.get(pfx)
            if not ns or not iri.startswith(ns):
                continue
            local = iri[len(ns):]
            if local and _looks_like_local(local):
                return f"{pfx}:{local}" if pfx else f":{local}"
        return None


def _looks_like_local(local: str) -> bool:
    if not local:
        return False
    # Conservative Turtle-ish local name check used for printing.
    bad = set(" <>\"{}|^`\\#/?")
    return not any(ch in bad or ord(ch) < 0x20 for ch in local)


def literal_from_python(value: Any) -> Literal:
    if isinstance(value, Literal):
        return value
    if isinstance(value, bool):
        return Literal("true" if value else "false", XSD_NS + "boolean", bare=True)
    if isinstance(value, int):
        return Literal(str(value), XSD_NS + "integer", bare=True)
    if isinstance(value, float):
        return Literal(repr(value), XSD_NS + "double", bare=True)
    if isinstance(value, Decimal):
        return Literal(format(value, "f"), XSD_NS + "decimal", bare=True)
    return Literal(str(value), XSD_NS + "string")


def quote_string(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def unescape_string(raw: str) -> str:
    # Accept the common N3/Turtle escapes. Invalid escapes are preserved rather than hidden.
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\" or i + 1 >= len(raw):
            out.append(ch)
            i += 1
            continue
        esc = raw[i + 1]
        table = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}
        if esc in table:
            out.append(table[esc])
            i += 2
        elif esc == "u" and i + 5 < len(raw):
            try:
                out.append(chr(int(raw[i + 2:i + 6], 16)))
                i += 6
            except ValueError:
                out.append(esc)
                i += 2
        elif esc == "U" and i + 9 < len(raw):
            try:
                out.append(chr(int(raw[i + 2:i + 10], 16)))
                i += 10
            except ValueError:
                out.append(esc)
                i += 2
        else:
            out.append(esc)
            i += 2
    return "".join(out)


def lexical_value(lit: Literal) -> str:
    return lit.lexical


def literal_language(lit: Literal) -> Optional[str]:
    return lit.lang.lower() if lit.lang else None


def literal_datatype(lit: Literal) -> str:
    if lit.datatype:
        return lit.datatype
    if lit.lang:
        return RDF_NS + "langString"
    return XSD_NS + "string"


def numeric_value(term: Term) -> Optional[Decimal]:
    if not isinstance(term, Literal):
        return None
    dt = literal_datatype(term)
    if dt not in _NUMERIC_DT:
        return None
    try:
        return Decimal(str(term.lexical))
    except (InvalidOperation, ValueError):
        return None


def bool_value(term: Term) -> Optional[bool]:
    if not isinstance(term, Literal):
        return None
    if literal_datatype(term) != XSD_NS + "boolean":
        return None
    v = term.lexical.strip().lower()
    if v in {"true", "1"}:
        return True
    if v in {"false", "0"}:
        return False
    return None


def term_has_vars(t: Term) -> bool:
    if isinstance(t, Var):
        return True
    if isinstance(t, ListTerm):
        return any(term_has_vars(e) for e in t.elems)
    if isinstance(t, OpenListTerm):
        return True
    if isinstance(t, GraphTerm):
        return any(triple_has_vars(tr) for tr in t.triples)
    return False


def triple_has_vars(tr: Triple) -> bool:
    return term_has_vars(tr.s) or term_has_vars(tr.p) or term_has_vars(tr.o)


def vars_in_term(t: Term) -> set[str]:
    if isinstance(t, Var):
        return {t.name}
    if isinstance(t, ListTerm):
        out: set[str] = set()
        for e in t.elems:
            out |= vars_in_term(e)
        return out
    if isinstance(t, OpenListTerm):
        out = {t.tail_var}
        for e in t.prefix:
            out |= vars_in_term(e)
        return out
    if isinstance(t, GraphTerm):
        out: set[str] = set()
        for tr in t.triples:
            out |= vars_in_triple(tr)
        return out
    return set()


def vars_in_triple(tr: Triple) -> set[str]:
    return vars_in_term(tr.s) | vars_in_term(tr.p) | vars_in_term(tr.o)


def term_to_primitive(t: Term) -> Any:
    if isinstance(t, Iri):
        return {"_type": "Iri", "value": t.value}
    if isinstance(t, Literal):
        d: dict[str, Any] = {"_type": "Literal", "value": t.lexical}
        if t.datatype:
            d["datatype"] = t.datatype
        if t.lang:
            d["language"] = t.lang
        if t.bare:
            d["bare"] = True
        return d
    if isinstance(t, Var):
        return {"_type": "Var", "name": t.name}
    if isinstance(t, Blank):
        return {"_type": "Blank", "label": t.label}
    if isinstance(t, ListTerm):
        return {"_type": "ListTerm", "elems": [term_to_primitive(e) for e in t.elems]}
    if isinstance(t, OpenListTerm):
        return {"_type": "OpenListTerm", "prefix": [term_to_primitive(e) for e in t.prefix], "tailVar": t.tail_var}
    if isinstance(t, GraphTerm):
        return {"_type": "GraphTerm", "triples": [triple_to_primitive(tr) for tr in t.triples]}
    return repr(t)


def triple_to_primitive(tr: Triple) -> dict[str, Any]:
    return {"_type": "Triple", "s": term_to_primitive(tr.s), "p": term_to_primitive(tr.p), "o": term_to_primitive(tr.o)}


def rule_to_primitive(rule: Rule) -> dict[str, Any]:
    return {
        "_type": "Rule",
        "premise": [triple_to_primitive(t) for t in rule.premise],
        "conclusion": [triple_to_primitive(t) for t in rule.conclusion],
        "isForward": rule.is_forward,
        "isFuse": rule.is_fuse,
    }


def term_from_primitive(obj: Any) -> Term:
    if isinstance(obj, Term):
        return obj
    if isinstance(obj, Mapping):
        typ = obj.get("_type") or obj.get("termType")
        if typ in {"Iri", "NamedNode"}:
            return Iri(str(obj.get("value", "")))
        if typ == "Literal":
            if "datatype" in obj and isinstance(obj["datatype"], Mapping):
                dt = obj["datatype"].get("value")
            else:
                dt = obj.get("datatype")
            return Literal(str(obj.get("value", "")), str(dt) if dt else None, obj.get("language") or obj.get("lang"), bare=bool(obj.get("bare")))
        if typ == "Variable" or typ == "Var":
            return Var(str(obj.get("name", obj.get("value", ""))).lstrip("?"))
        if typ == "BlankNode" or typ == "Blank":
            lab = str(obj.get("label", obj.get("value", "")))
            if not lab.startswith("_:"):
                lab = "_:" + lab
            return Blank(lab)
        if typ == "ListTerm":
            return ListTerm(term_from_primitive(e) for e in obj.get("elems", []))
        if typ == "OpenListTerm":
            return OpenListTerm((term_from_primitive(e) for e in obj.get("prefix", [])), str(obj.get("tailVar") or obj.get("tail_var") or "tail"))
        if typ == "GraphTerm":
            return GraphTerm(triple_from_primitive(t) for t in obj.get("triples", []))
        if typ == "Quad" or {"subject", "predicate", "object"}.issubset(obj.keys()):
            return GraphTerm([Triple(term_from_primitive(obj["subject"]), term_from_primitive(obj["predicate"]), term_from_primitive(obj["object"]))])
    if isinstance(obj, str):
        return Literal(obj, XSD_NS + "string")
    if isinstance(obj, bool):
        return literal_from_python(obj)
    if isinstance(obj, int):
        return literal_from_python(obj)
    if isinstance(obj, float):
        return literal_from_python(obj)
    raise TypeError(f"cannot convert object to Eyeling term: {obj!r}")


def triple_from_primitive(obj: Any) -> Triple:
    if isinstance(obj, Triple):
        return obj
    if isinstance(obj, Mapping):
        if {"s", "p", "o"}.issubset(obj.keys()):
            return Triple(term_from_primitive(obj["s"]), term_from_primitive(obj["p"]), term_from_primitive(obj["o"]))
        if {"subject", "predicate", "object"}.issubset(obj.keys()):
            return Triple(term_from_primitive(obj["subject"]), term_from_primitive(obj["predicate"]), term_from_primitive(obj["object"]))
    raise TypeError(f"cannot convert object to Eyeling triple: {obj!r}")


def rule_from_primitive(obj: Any) -> Rule:
    if isinstance(obj, Rule):
        return obj
    if isinstance(obj, Mapping):
        premise = obj.get("premise") or obj.get("body") or []
        conclusion = obj.get("conclusion") or obj.get("head") or []
        is_forward = obj.get("isForward", obj.get("is_forward", True))
        return Rule((triple_from_primitive(t) for t in premise), (triple_from_primitive(t) for t in conclusion), bool(is_forward), bool(obj.get("isFuse", obj.get("is_fuse", False))))
    raise TypeError(f"cannot convert object to Eyeling rule: {obj!r}")
