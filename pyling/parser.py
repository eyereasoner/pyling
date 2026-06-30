"""Small Notation3 parser for the Eyeling Python reasoner.

It intentionally focuses on the N3 rule subset used by Eyeling's reasoner:
prefix/base directives, triples, graph terms, lists, blank-node property lists,
variables, literals, and `=>` / `<=` rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin

from .terms import (
    LOG_IMPLIED_BY,
    LOG_IMPLIES,
    LOG_QUERY,
    OWL_SAME_AS,
    RDF_TYPE,
    Blank,
    GraphTerm,
    Iri,
    ListTerm,
    Literal,
    PrefixEnv,
    Rule,
    Term,
    Triple,
    Var,
    XSD_NS,
    unescape_string,
)


class N3SyntaxError(SyntaxError):
    """N3 parse error with a character offset suitable for CLI diagnostics."""

    def __init__(self, message: str, offset: int | None = None):
        super().__init__(message)
        self.offset = offset


@dataclass(frozen=True)
class Token:
    typ: str
    value: str
    pos: int


_NUM_RE = re.compile(
    r"[+-]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)[eE][+-]?[0-9]+|[0-9]*\.[0-9]+|[0-9]+[eE][+-]?[0-9]+|[0-9]+)"
)
_LANG_RE = re.compile(r"@[A-Za-z]+(?:-[A-Za-z0-9]+)*")
_IDENT_STOP = set("{}[]();,.^!\"'<> \\\t\r\n")


def lex(text: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if text.startswith("=>", i) or text.startswith("<=", i) or text.startswith("<-", i) or text.startswith("^^", i) or text.startswith("<<", i) or text.startswith(">>", i):
            out.append(Token(text[i:i+2], text[i:i+2], i))
            i += 2
            continue
        # A decimal requires at least one digit after the decimal point. This
        # keeps the statement terminator in ``55.`` separate from the integer,
        # while still accepting decimal literals such as ``.5``.
        m = _NUM_RE.match(text, i)
        if m and (i == 0 or text[i-1].isspace() or text[i-1] in "({[,;"):
            end = m.end()
            if end < n and text[end] == "." and end + 1 < n and text[end+1].isdigit():
                raise N3SyntaxError("malformed numeric literal", i)
            out.append(Token("NUMBER", m.group(0), i))
            i = end
            continue
        if ch in "{}[]();,.()=!^|":
            out.append(Token(ch, ch, i))
            i += 1
            continue
        if ch == "<":
            j = i + 1
            buf = []
            while j < n and text[j] != ">":
                c = text[j]
                if c in " \t\r\n" or ord(c) < 0x20:
                    raise N3SyntaxError("invalid character inside IRI", j)
                if c == "\\":
                    width = 4 if text.startswith("\\u", j) else 8 if text.startswith("\\U", j) else 0
                    digits = text[j + 2:j + 2 + width]
                    if not width or len(digits) != width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                        raise N3SyntaxError("invalid escape inside IRI", j)
                    try:
                        decoded = chr(int(digits, 16))
                    except (ValueError, OverflowError):
                        raise N3SyntaxError("invalid UCHAR escape inside IRI", j) from None
                    if decoded in '<>"{}|^`\\' or decoded.isspace() or ord(decoded) < 0x20:
                        raise N3SyntaxError("invalid character inside IRI", j)
                    buf.append(decoded)
                    j += width + 2
                    continue
                buf.append(c)
                j += 1
            if j >= n:
                raise N3SyntaxError("unterminated IRI", i)
            out.append(Token("IRI", "".join(buf), i))
            i = j + 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            triple = text.startswith(quote * 3, i)
            delim = quote * (3 if triple else 1)
            j = i + len(delim)
            buf = []
            while j < n:
                if triple and text[j] == quote:
                    run_end = j
                    while run_end < n and text[run_end] == quote:
                        run_end += 1
                    run_length = run_end - j
                    if run_length >= 3:
                        # In a run of quotes, the final three close the long
                        # string and preceding quotes belong to its value.
                        buf.append(quote * (run_length - 3))
                        j = run_end
                        break
                elif not triple and text.startswith(delim, j):
                    j += len(delim)
                    break
                c = text[j]
                if not triple and c in "\r\n":
                    raise N3SyntaxError("raw newline in short string literal", j)
                if c == "\\" and j + 1 < n:
                    buf.append(text[j:j+2] if text[j+1] not in "uU" else text[j:j+(6 if text[j+1]=='u' else 10)])
                    j += len(buf[-1])
                else:
                    if ord(c) == 0:
                        raise N3SyntaxError("NUL in string literal", j)
                    buf.append(c)
                    j += 1
            else:
                raise N3SyntaxError("unterminated string", i)
            raw_content = "".join(buf)
            decoded_content = unescape_string(raw_content)
            if any(ord(c) == 0 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF} for c in decoded_content):
                raise N3SyntaxError("forbidden Unicode code point in string literal", i)
            out.append(Token("STRING", decoded_content, i))
            i = j
            continue
        if ch == "?":
            j = i + 1
            while j < n and re.match(r"[A-Za-z0-9_\-]", text[j]):
                j += 1
            if j == i + 1:
                raise N3SyntaxError("empty variable", i)
            out.append(Token("VAR", text[i+1:j], i))
            i = j
            continue
        if ch == "@":
            m = _LANG_RE.match(text, i)
            if m and not text.startswith("@prefix", i) and not text.startswith("@base", i):
                out.append(Token("LANG", m.group(0)[1:], i))
                i = m.end()
                continue
        # identifier / prefixed name / keyword / blank node label
        j = i
        while j < n and text[j] not in _IDENT_STOP:
            # stop at => <= <- starts, at comment marker after whitespace already handled
            if text.startswith("=>", j) or text.startswith("<=", j) or text.startswith("<-", j) or text.startswith("^^", j):
                break
            j += 1
        if j == i:
            raise N3SyntaxError(f"unexpected character {ch!r}", i)
        value = text[i:j]
        out.append(Token("IDENT", value, i))
        i = j
    out.append(Token("EOF", "", n))
    return out


@dataclass
class Document:
    prefixes: PrefixEnv
    triples: list[Triple]
    forward_rules: list[Rule]
    backward_rules: list[Rule]
    query_rules: list[Rule]


class Parser:
    def __init__(self, text: str, base_iri: str | None = None, prefix_env: PrefixEnv | None = None, blank_prefix: str = "_:b"):
        self.tokens = lex(text)
        self.i = 0
        self.env = prefix_env.copy() if prefix_env else PrefixEnv({})
        if base_iri:
            self.env.base_iri = base_iri
        self.blank_counter = 0
        self.blank_prefix = blank_prefix
        self.pending: list[Triple] = []

    def peek(self, off: int = 0) -> Token:
        idx = min(self.i + off, len(self.tokens) - 1)
        return self.tokens[idx]

    def pop(self, typ: str | None = None) -> Token:
        tok = self.peek()
        if typ is not None and tok.typ != typ and tok.value != typ:
            raise N3SyntaxError(f"expected {typ}, got {tok.typ} {tok.value!r}", tok.pos)
        self.i += 1
        return tok

    def match(self, typ_or_value: str) -> bool:
        tok = self.peek()
        # Punctuation token types equal their values; keyword matching is only
        # valid for identifiers. Literal values such as "!" must not be
        # mistaken for grammar punctuation/path operators.
        return tok.typ == typ_or_value or (tok.typ == "IDENT" and tok.value == typ_or_value)

    def accept(self, typ_or_value: str) -> Optional[Token]:
        if self.match(typ_or_value):
            return self.pop()
        return None

    def expect_dot(self) -> None:
        self.pop(".")

    def fresh_blank(self) -> Blank:
        self.blank_counter += 1
        return Blank(f"{self.blank_prefix}{self.blank_counter}")

    def parse(self) -> Document:
        triples: list[Triple] = []
        frules: list[Rule] = []
        brules: list[Rule] = []
        qrules: list[Rule] = []
        while not self.match("EOF"):
            if self.parse_directive():
                continue
            st_triples, rule, query = self.parse_statement(in_graph=False)
            triples.extend(st_triples)
            if rule:
                if rule.is_forward:
                    frules.append(rule)
                else:
                    brules.append(rule)
            if query:
                qrules.append(query)
        return Document(self.env.copy(), triples, frules, brules, qrules)

    def parse_directive(self) -> bool:
        tok = self.peek()
        low = tok.value.lower()
        if tok.typ == "IDENT" and low in {"@prefix", "prefix"}:
            self.pop()
            name_tok = self.pop("IDENT")
            if not name_tok.value.endswith(":"):
                raise N3SyntaxError("prefix names must end with ':'", name_tok.pos)
            name = name_tok.value[:-1]
            iri = self.pop("IRI").value if self.match("IRI") else self.pop("IDENT").value
            had_fragment_marker = iri.endswith("#")
            iri = urljoin(self.env.base_iri or "", iri)
            if had_fragment_marker and not iri.endswith("#"):
                iri += "#"
            self.env.set_prefix(name, iri)
            self.accept(".")
            return True
        if tok.typ == "IDENT" and low in {"@base", "base"}:
            self.pop()
            iri = self.pop("IRI").value if self.match("IRI") else self.pop("IDENT").value
            had_fragment_marker = iri.endswith("#")
            resolved = urljoin(self.env.base_iri or "", iri)
            self.env.base_iri = resolved + "#" if had_fragment_marker and not resolved.endswith("#") else resolved
            self.accept(".")
            return True
        # RDF 1.2 / RDF Message version directives are handled by the RDF
        # compatibility layer. In plain N3 mode we accept and ignore them so
        # mixed sources do not crash solely because a version line is present.
        if tok.typ == "IDENT" and low in {"@version", "version"}:
            self.pop()
            if self.match("STRING") or self.match("IDENT") or self.match("IRI"):
                self.pop()
            self.accept(".")
            return True
        return False

    def parse_statement(self, in_graph: bool) -> tuple[list[Triple], Optional[Rule], Optional[Rule]]:
        # Property-list expansion is local to a statement. Formulas recursively
        # parse statements, so sharing one mutable pending list loses triples
        # from nested RDF collections and can leak formula triples outward.
        outer_pending = self.pending
        self.pending = []
        try:
            return self._parse_statement(in_graph)
        finally:
            self.pending = outer_pending

    def _parse_statement(self, in_graph: bool) -> tuple[list[Triple], Optional[Rule], Optional[Rule]]:
        first = self.parse_term()
        if self.accept("=>"):
            second = self.parse_term()
            if not (in_graph and self.match("}")):
                self.expect_dot()
            if in_graph:
                return [*self.pending, Triple(first, Iri(LOG_IMPLIES), second)], None, None
            return self.pending, self._make_rule(first, second, True), None
        if self.accept("<="):
            second = self.parse_term()
            if not (in_graph and self.match("}")):
                self.expect_dot()
            if in_graph:
                return [*self.pending, Triple(first, Iri(LOG_IMPLIED_BY), second)], None, None
            return self.pending, self._make_rule(first, second, False), None
        triples: list[Triple]
        # A non-empty blank-node property list is a complete statement by
        # itself; its triples were accumulated while parsing the term.
        if self.pending and (self.match(".") or (in_graph and self.match("}"))):
            triples = list(self.pending)
        else:
            direct = self.parse_predicate_object_list(first)
            triples = [*self.pending, *direct]
        if not (in_graph and self.match("}")):
            self.expect_dot()
        qrule = None
        normal: list[Triple] = []
        for tr in triples:
            if isinstance(tr.p, Iri) and tr.p.value == LOG_QUERY and isinstance(tr.s, GraphTerm) and isinstance(tr.o, GraphTerm):
                qrule = Rule(tr.s.triples, tr.o.triples, True)
            else:
                normal.append(tr)
        return normal, None, qrule

    def _make_rule(self, first: Term, second: Term, is_forward: bool) -> Rule:
        if isinstance(second, Literal) and second.datatype == XSD_NS + "boolean" and second.lexical in {"false", "0"}:
            if not isinstance(first, GraphTerm):
                raise N3SyntaxError("rule premise must be a formula", self.peek().pos)
            return Rule(first.triples, [], is_forward, True)
        if not isinstance(first, GraphTerm) or not isinstance(second, GraphTerm):
            raise N3SyntaxError("rules require formula terms on both sides", self.peek().pos)
        # Blank nodes in an antecedent formula are existential variables. They
        # share scope by label within that antecedent, unlike top-level blank
        # nodes and existential blank nodes in a rule conclusion.
        blank_vars: dict[str, Var] = {}

        def antecedent_term(term: Term) -> Term:
            if isinstance(term, Blank):
                return blank_vars.setdefault(term.label, Var(f"_blank_{term.label}"))
            if isinstance(term, ListTerm):
                return ListTerm(antecedent_term(item) for item in term.elems)
            if isinstance(term, GraphTerm):
                return GraphTerm(
                    Triple(antecedent_term(tr.s), antecedent_term(tr.p), antecedent_term(tr.o))
                    for tr in term.triples
                )
            return term

        premise = [Triple(antecedent_term(tr.s), antecedent_term(tr.p), antecedent_term(tr.o)) for tr in first.triples]
        return Rule(premise, second.triples, is_forward)

    def parse_predicate_object_list(self, subject: Term) -> list[Triple]:
        triples: list[Triple] = []
        first = True
        while True:
            if not first:
                if not self.accept(";"):
                    break
                while self.accept(";"):
                    pass
                if self.match(".") or self.match("]") or self.match("}"):
                    break
            first = False
            if self.match("is"):
                self.pop()
                pred = self.parse_term()
                if not self.match("of"):
                    raise N3SyntaxError("expected 'of' after 'is P'", self.peek().pos)
                self.pop()
                objs = self.parse_object_list()
                triples.extend(Triple(o, pred, subject) for o in objs)
            elif self.match("has"):
                self.pop()
                pred = self.parse_term()
                objs = self.parse_object_list()
                triples.extend(Triple(subject, pred, o) for o in objs)
            elif self.accept("<-"):
                pred = self.parse_term()
                objs = self.parse_object_list()
                triples.extend(Triple(o, pred, subject) for o in objs)
            else:
                pred = self.parse_verb()
                objs = self.parse_object_list()
                triples.extend(Triple(subject, pred, o) for o in objs)
        return triples

    def parse_verb(self) -> Term:
        if self.match("IDENT") and self.peek().value == "a":
            self.pop()
            return Iri(RDF_TYPE)
        if self.accept("="):
            return Iri(OWL_SAME_AS)
        return self.parse_term()

    def parse_object_list(self) -> list[Term]:
        objs = [self.parse_term()]
        while self.accept(","):
            objs.append(self.parse_term())
        return objs

    def parse_term(self) -> Term:
        t = self.parse_atom()
        while self.match("!") or self.match("^"):
            op = self.pop().value
            pred = self.parse_atom()
            b = self.fresh_blank()
            if op == "!":
                self.pending.append(Triple(t, pred, b))
            else:
                self.pending.append(Triple(b, pred, t))
            t = b
        return t

    def parse_atom(self) -> Term:
        tok = self.peek()

        if self.accept("<<"):
            parenthesized = bool(self.accept("("))
            subj = self.parse_term()
            pred = self.parse_verb()
            obj = self.parse_term()
            if parenthesized:
                self.pop(")")
            self.pop(">>")
            return GraphTerm([Triple(subj, pred, obj)])
        if tok.typ == "IRI":
            self.pop()
            iri = tok.value
            if self.env.base_iri:
                iri = urljoin(self.env.base_iri, iri)
            return Iri(iri)
        if tok.typ == "VAR":
            self.pop()
            return Var(tok.value)
        if tok.typ == "NUMBER":
            self.pop()
            raw = tok.value
            if re.search(r"[.eE]", raw):
                dt = XSD_NS + ("double" if "e" in raw.lower() else "decimal")
            else:
                dt = XSD_NS + "integer"
            return Literal(raw, dt, bare=True)
        if tok.typ == "STRING":
            self.pop()
            dt = None
            lang = None
            if self.accept("^^"):
                dt_term = self.parse_term()
                if not isinstance(dt_term, Iri):
                    raise N3SyntaxError("datatype must be an IRI", tok.pos)
                dt = dt_term.value
            elif self.match("LANG"):
                lang = self.pop("LANG").value.lower()
            return Literal(tok.value, dt, lang)
        if tok.typ == "IDENT":
            val = tok.value
            low = val.lower()
            if low == "true" or low == "false":
                self.pop()
                return Literal(low, XSD_NS + "boolean", bare=True)
            if val.startswith("_:"):
                self.pop()
                return Blank(val)
            if ":" in val:
                self.pop()
                return Iri(self.env.expand(val))
            # As a permissive fallback, treat bare identifiers as relative IRIs.
            self.pop()
            iri = urljoin(self.env.base_iri or "", val)
            return Iri(iri)
        if self.accept("("):
            elems: list[Term] = []
            while not self.match(")"):
                if self.match("EOF"):
                    raise N3SyntaxError("unterminated list", self.peek().pos)
                elems.append(self.parse_term())
            self.pop(")")
            return ListTerm(elems)
        if self.accept("["):
            if self.match("IDENT") and self.peek().value.lower() == "id":
                self.pop()
                b = self.parse_term()
            else:
                b = self.fresh_blank()
            if not self.match("]"):
                triples = self.parse_predicate_object_list(b)
                self.pending.extend(triples)
            self.pop("]")
            return b
        if self.accept("{"):
            triples: list[Triple] = []
            outer_env = self.env
            self.env = self.env.copy()
            try:
                while not self.match("}"):
                    if self.match("EOF"):
                        raise N3SyntaxError("unterminated formula", self.peek().pos)
                    if self.parse_directive():
                        continue
                    st_triples, _rule, _query = self.parse_statement(in_graph=True)
                    triples.extend(st_triples)
                self.pop("}")
            finally:
                self.env = outer_env
            return GraphTerm(triples)
        raise N3SyntaxError(f"expected term, got {tok.typ} {tok.value!r}", tok.pos)


def parse_n3(text: str, *, base_iri: str | None = None, prefix_env: PrefixEnv | None = None, blank_prefix: str = "_:b") -> Document:
    return Parser(text, base_iri=base_iri, prefix_env=prefix_env, blank_prefix=blank_prefix).parse()


def parse_sources(sources: Iterable[str | dict]) -> Document:
    env = PrefixEnv({})
    triples: list[Triple] = []
    frules: list[Rule] = []
    brules: list[Rule] = []
    qrules: list[Rule] = []
    for idx, source in enumerate(sources, start=1):
        if isinstance(source, dict):
            text = source.get("n3") or source.get("text") or ""
            base = source.get("baseIri") or source.get("base_iri")
        else:
            text = str(source)
            base = None
        doc = parse_n3(text, base_iri=base, prefix_env=env, blank_prefix=f"_:s{idx}b")
        env = doc.prefixes
        triples.extend(doc.triples)
        frules.extend(doc.forward_rules)
        brules.extend(doc.backward_rules)
        qrules.extend(doc.query_rules)
    return Document(env, triples, frules, brules, qrules)
