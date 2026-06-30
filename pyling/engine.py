"""Inference engine for pyling."""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional

from .builtins import BuiltinContext, get_builtin
from .parser import Document, N3SyntaxError, parse_n3, parse_sources
from .rdf import is_rdf_message_log, parse_rdf_message_log, parse_rdf_text, iter_rdf_message_documents
from .printing import literal_as_output_string, term_to_n3, triples_to_n3
from .store import create_fact_store
from .terms import (
    LOG_IMPLIED_BY,
    LOG_IMPLIES,
    LOG_OUTPUT_STRING,
    OWL_DIFFERENT_FROM,
    OWL_SAME_AS,
    RDF_FIRST,
    RDF_NIL,
    RDF_REST,
    Blank,
    GraphTerm,
    Iri,
    ListTerm,
    Literal,
    OpenListTerm,
    PrefixEnv,
    Rule,
    Term,
    Triple,
    Var,
    bool_value,
    numeric_value,
    rule_from_primitive,
    term_from_primitive,
    term_to_primitive,
    triple_from_primitive,
    triple_to_primitive,
    XSD_NS,
)

INFERENCE_FUSE_EXIT_CODE = 65

Subst = dict[str, Term]


@dataclass(slots=True)
class _AgendaEntry:
    rule: Rule
    rule_index: int
    goal: Triple
    s_key: Term | None
    o_key: Term | None


class InferenceFuseError(RuntimeError):
    def __init__(self, message: str = "inference fuse derived false") -> None:
        super().__init__(message)
        self.code = INFERENCE_FUSE_EXIT_CODE


@dataclass(slots=True)
class ReasonStreamResult:
    prefixes: PrefixEnv
    facts: list[Triple]
    derived: list[Triple]
    query_mode: bool
    query_triples: list[Triple]
    query_derived: list[Triple]
    closure_n3: str
    store: Any = None

    # JavaScript-style aliases for convenience.
    @property
    def closureN3(self) -> str:
        return self.closure_n3

    @property
    def queryMode(self) -> bool:
        return self.query_mode

    @property
    def queryTriples(self) -> list[Triple]:
        return self.query_triples

    @property
    def queryDerived(self) -> list[Triple]:
        return self.query_derived


class Engine:
    def __init__(self, doc: Document, options: Mapping[str, Any] | None = None) -> None:
        self.doc = doc
        self.options = dict(options or {})
        self.prefixes = doc.prefixes
        self.facts: list[Triple] = list(doc.triples)
        self._fact_set: set[Triple] = set(doc.triples)
        self._facts_by_pred: dict[Term, list[Triple]] = {}
        self._facts_by_ps: dict[tuple[Term, Term], list[Triple]] = {}
        self._facts_by_po: dict[tuple[Term, Term], list[Triple]] = {}
        self._var_pred_facts: list[Triple] = []
        for _tr in self.facts:
            self._index_fact(_tr)
        self._indexed_facts_obj_id = id(self.facts)
        self._indexed_facts_len = len(self.facts)
        self.derived: list[Triple] = []
        self.forward_rules: list[Rule] = list(doc.forward_rules)
        self.backward_rules: list[Rule] = list(doc.backward_rules)
        self.query_rules: list[Rule] = list(doc.query_rules)
        self._rule_key_cache: dict[Rule, str] = {}
        self._rule_ids: set[str] = {self._rule_key(r) for r in self.forward_rules + self.backward_rules}
        self._fired_rule_bindings: set[str] = set()
        self._agenda_active = False
        self._agenda_queue: list[Triple] = []
        self._agenda_indexed_rules: set[Rule] = set()
        self._agenda_by_pred: dict[Term, list[_AgendaEntry]] = {}
        self._agenda_by_ps: dict[tuple[Term, Term], list[_AgendaEntry]] = {}
        self._agenda_by_po: dict[tuple[Term, Term], list[_AgendaEntry]] = {}
        self._agenda_all_entries: list[_AgendaEntry] = []
        self._fresh_counter = 0
        self._std_counter = 0
        self.max_depth = int(self.options.get("max_depth", self.options.get("maxDepth", 128)))
        self.max_iterations = int(self.options.get("max_iterations", self.options.get("maxIterations", 1000)))
        self.skolem_salt = str(uuid.uuid4())
        self.store = None

    def term_to_n3(self, term: Term) -> str:
        return term_to_n3(term, self.prefixes)

    def _rule_key(self, r: Rule) -> str:
        cached = getattr(self, "_rule_key_cache", {}).get(r)
        if cached is not None:
            return cached
        key = json.dumps({
            "p": [triple_to_primitive(t) for t in r.premise],
            "c": [triple_to_primitive(t) for t in r.conclusion],
            "f": r.is_forward,
            "x": r.is_fuse,
        }, sort_keys=True, default=str)
        if hasattr(self, "_rule_key_cache"):
            self._rule_key_cache[r] = key
        return key

    def _lookup_key(self, term: Term) -> Term | None:
        """Return an exact-match index key, or None when broad unification is needed."""
        term = self.deref(term, {})
        if isinstance(term, Var) or isinstance(term, OpenListTerm):
            return None
        if isinstance(term, Literal):
            # Literal unification performs datatype normalization, so an exact
            # dataclass key could miss equivalent lexical forms. Keep literals
            # on the predicate bucket unless another position is indexable.
            return None
        if isinstance(term, ListTerm):
            return term if all(self._lookup_key(e) is not None for e in term.elems) else None
        if isinstance(term, GraphTerm):
            return None
        return term

    def _index_fact(self, tr: Triple) -> None:
        if isinstance(tr.p, Var):
            self._var_pred_facts.append(tr)
            return
        self._facts_by_pred.setdefault(tr.p, []).append(tr)
        sk = self._lookup_key(tr.s)
        if sk is not None:
            self._facts_by_ps.setdefault((tr.p, sk), []).append(tr)
        ok = self._lookup_key(tr.o)
        if ok is not None:
            self._facts_by_po.setdefault((tr.p, ok), []).append(tr)

    def _rebuild_fact_indexes(self) -> None:
        self._facts_by_pred.clear()
        self._facts_by_ps.clear()
        self._facts_by_po.clear()
        self._var_pred_facts.clear()
        for tr in self.facts:
            self._index_fact(tr)
        self._indexed_facts_obj_id = id(self.facts)
        self._indexed_facts_len = len(self.facts)

    def _ensure_fact_indexes_current(self) -> None:
        # Some log:* built-ins temporarily replace engine.facts with a scoped
        # formula's triples. Rebuild the lookup tables when that happens.
        if id(self.facts) != self._indexed_facts_obj_id or len(self.facts) != self._indexed_facts_len:
            self._rebuild_fact_indexes()

    def _candidate_facts(self, goal: Triple) -> Iterable[Triple]:
        self._ensure_fact_indexes_current()
        if isinstance(goal.p, Var):
            return list(self.facts)
        candidates: list[list[Triple]] = []
        pred_bucket = self._facts_by_pred.get(goal.p)
        if pred_bucket is not None:
            candidates.append(pred_bucket)
        sk = self._lookup_key(goal.s)
        if sk is not None:
            bucket = self._facts_by_ps.get((goal.p, sk))
            if bucket is not None:
                candidates.append(bucket)
        ok = self._lookup_key(goal.o)
        if ok is not None:
            bucket = self._facts_by_po.get((goal.p, ok))
            if bucket is not None:
                candidates.append(bucket)
        if not candidates:
            base: list[Triple] = []
        else:
            base = min(candidates, key=len)
        if not self._var_pred_facts:
            return base
        return list(base) + self._var_pred_facts

    def add_fact(self, tr: Triple, inferred: bool = True) -> bool:
        # owl:differentFrom self is false in Eyeling style tests only when queried through sameAs? Keep as normal fact.
        if tr in self._fact_set:
            return False
        self._fact_set.add(tr)
        self._ensure_fact_indexes_current()
        self.facts.append(tr)
        self._index_fact(tr)
        self._indexed_facts_len = len(self.facts)
        self._indexed_facts_obj_id = id(self.facts)
        if self._agenda_active:
            self._agenda_queue.append(tr)
        if inferred:
            self.derived.append(tr)
        if isinstance(tr.p, Iri) and isinstance(tr.s, GraphTerm) and isinstance(tr.o, GraphTerm):
            if tr.p.value == LOG_IMPLIES:
                self.add_rule(Rule(tr.s.triples, tr.o.triples, True))
            elif tr.p.value == LOG_IMPLIED_BY:
                self.add_rule(Rule(tr.s.triples, tr.o.triples, False))
        elif (
            isinstance(tr.p, Iri)
            and tr.p.value == LOG_IMPLIES
            and isinstance(tr.s, GraphTerm)
            and isinstance(tr.o, Literal)
            and bool_value(tr.o) is False
        ):
            self.add_rule(Rule(tr.s.triples, (), True, True))
        return True

    def add_rule(self, rule: Rule) -> bool:
        key = self._rule_key(rule)
        if key in self._rule_ids:
            return False
        self._rule_ids.add(key)
        if rule.is_forward:
            self.forward_rules.append(rule)
        else:
            self.backward_rules.append(rule)
        return True

    def _term_contains_blank(self, term: Term) -> bool:
        if isinstance(term, Blank):
            return True
        if isinstance(term, ListTerm):
            return any(self._term_contains_blank(e) for e in term.elems)
        if isinstance(term, OpenListTerm):
            return any(self._term_contains_blank(e) for e in term.prefix)
        if isinstance(term, GraphTerm):
            return any(
                self._term_contains_blank(tr.s)
                or self._term_contains_blank(tr.p)
                or self._term_contains_blank(tr.o)
                for tr in term.triples
            )
        return False

    def _rule_has_head_blanks(self, rule: Rule) -> bool:
        return any(
            self._term_contains_blank(tr.s)
            or self._term_contains_blank(tr.p)
            or self._term_contains_blank(tr.o)
            for tr in rule.conclusion
        )

    def _is_fast_single_premise_rule(self, rule: Rule) -> bool:
        if rule.is_fuse or len(rule.premise) != 1:
            return False
        if self.backward_rules:
            # A backward rule may prove the premise without an extensional fact.
            # Keep that case on the complete, generic solver path.
            return False
        if self._rule_has_head_blanks(rule):
            # Preserve legacy blank-node allocation order for existential heads.
            return False
        goal = rule.premise[0]
        if not isinstance(goal.p, Iri):
            return False
        return get_builtin(goal.p.value) is None

    def _add_agenda_entry(self, entry: _AgendaEntry) -> None:
        p = entry.goal.p
        self._agenda_all_entries.append(entry)
        if entry.s_key is None and entry.o_key is None:
            self._agenda_by_pred.setdefault(p, []).append(entry)
        if entry.s_key is not None:
            self._agenda_by_ps.setdefault((p, entry.s_key), []).append(entry)
        if entry.o_key is not None:
            self._agenda_by_po.setdefault((p, entry.o_key), []).append(entry)

    def _build_single_premise_agenda(self) -> None:
        self._agenda_indexed_rules.clear()
        self._agenda_by_pred.clear()
        self._agenda_by_ps.clear()
        self._agenda_by_po.clear()
        self._agenda_all_entries.clear()
        for i, rule in enumerate(self.forward_rules):
            if not self._is_fast_single_premise_rule(rule):
                continue
            goal = rule.premise[0]
            entry = _AgendaEntry(rule, i, goal, self._lookup_key(goal.s), self._lookup_key(goal.o))
            self._agenda_indexed_rules.add(rule)
            self._add_agenda_entry(entry)

    def _agenda_candidates_for_fact(self, fact: Triple) -> list[_AgendaEntry]:
        if isinstance(fact.p, Var):
            # Rare: a variable-predicate fact can unify with many rule premises.
            return list(self._agenda_all_entries)
        buckets: list[list[_AgendaEntry]] = []
        broad = self._agenda_by_pred.get(fact.p)
        if broad:
            buckets.append(broad)
        sk = self._lookup_key(fact.s)
        if sk is not None:
            bucket = self._agenda_by_ps.get((fact.p, sk))
            if bucket:
                buckets.append(bucket)
        ok = self._lookup_key(fact.o)
        if ok is not None:
            bucket = self._agenda_by_po.get((fact.p, ok))
            if bucket:
                buckets.append(bucket)
        out: list[_AgendaEntry] = []
        seen_rules: set[Rule] = set()
        for bucket in buckets:
            for entry in bucket:
                if entry.rule in seen_rules:
                    continue
                seen_rules.add(entry.rule)
                out.append(entry)
        return out

    def _fire_agenda_rule(self, entry: _AgendaEntry, fact: Triple) -> bool:
        subst = self.unify_triple(entry.goal, fact, {})
        if subst is None:
            return False
        firing_key = self._firing_key(entry.rule, subst)
        if firing_key in self._fired_rule_bindings:
            return False
        self._fired_rule_bindings.add(firing_key)
        changed = False
        for head in entry.rule.conclusion:
            out = self.apply_subst_triple(head, subst, ground_blanks=False)
            if self.add_fact(out, inferred=True):
                changed = True
        return changed

    def _drain_single_premise_agenda(self) -> bool:
        changed = False
        index = 0
        while index < len(self._agenda_queue):
            fact = self._agenda_queue[index]
            index += 1
            for entry in self._agenda_candidates_for_fact(fact):
                if self._fire_agenda_rule(entry, fact):
                    changed = True
        # All queued facts have been processed against the current agenda index.
        del self._agenda_queue[:index]
        return changed

    def run(self) -> ReasonStreamResult:
        # Top-level log:implies facts are live rules immediately.
        for tr in list(self.facts):
            if isinstance(tr.p, Iri) and isinstance(tr.s, GraphTerm) and isinstance(tr.o, GraphTerm):
                if tr.p.value == LOG_IMPLIES:
                    self.add_rule(Rule(tr.s.triples, tr.o.triples, True))
                elif tr.p.value == LOG_IMPLIED_BY:
                    self.add_rule(Rule(tr.s.triples, tr.o.triples, False))
        self._build_single_premise_agenda()
        self._agenda_active = bool(self._agenda_indexed_rules)
        if self._agenda_active:
            self._agenda_queue = list(self.facts)
            self._drain_single_premise_agenda()

        # Validate immediate sameAs reflexivity facts are usable. No full OWL closure is intended.
        for iteration in range(self.max_iterations):
            changed = False
            # Rules not covered by the agenda still use the complete solver. This
            # preserves general N3 behavior while avoiding O(rules * facts * depth)
            # scans for the common single-premise Horn-chain case.
            rules_snapshot = [r for r in self.forward_rules if r not in self._agenda_indexed_rules]
            for rule in rules_snapshot:
                if rule.is_fuse:
                    if any(True for _ in self.solve(list(rule.premise), {})):
                        raise InferenceFuseError()
                    continue
                for subst in self.solve(list(rule.premise), {}):
                    firing_key = self._firing_key(rule, subst)
                    if firing_key in self._fired_rule_bindings:
                        continue
                    self._fired_rule_bindings.add(firing_key)
                    for head in rule.conclusion:
                        fact = self.apply_subst_triple(head, subst, ground_blanks=True)
                        if self.add_fact(fact, inferred=True):
                            changed = True
            if self._agenda_active and self._agenda_queue:
                changed = self._drain_single_premise_agenda() or changed
            if not changed:
                break
        else:
            raise RuntimeError(f"reasoning did not reach a fixpoint after {self.max_iterations} iterations")

        query_derived: list[Triple] = []
        if self.query_rules:
            seen: set[Triple] = set()
            for qr in self.query_rules:
                for subst in self.solve(list(qr.premise), {}):
                    for head in qr.conclusion:
                        tr = self.apply_subst_triple(head, subst, ground_blanks=True)
                        if tr not in seen:
                            seen.add(tr)
                            query_derived.append(tr)
        query_mode = bool(self.query_rules)
        selected = query_derived if query_mode else self.derived
        if self._has_output_strings(selected):
            closure = self._render_output_strings(selected)
        else:
            include_input = bool(self.options.get("include_input_facts_in_closure", self.options.get("includeInputFactsInClosure", False)))
            all_triples = selected if not include_input else self.facts
            closure = triples_to_n3(all_triples, self.prefixes)
        return ReasonStreamResult(self.prefixes, list(self.facts), list(self.derived), query_mode, selected, query_derived, closure, self.store)

    def _firing_key(self, rule: Rule, subst: Subst) -> str:
        values = {
            name: term_to_primitive(self.apply_subst(value, subst))
            for name, value in sorted(subst.items())
        }
        return self._rule_key(rule) + "|" + json.dumps(values, sort_keys=True, default=str)

    def _has_output_strings(self, triples: Iterable[Triple]) -> bool:
        return any(isinstance(t.p, Iri) and t.p.value == LOG_OUTPUT_STRING for t in triples)

    def _render_output_strings(self, triples: Iterable[Triple]) -> str:
        items = [t for t in triples if isinstance(t.p, Iri) and t.p.value == LOG_OUTPUT_STRING]
        items.sort(key=lambda t: self.term_to_n3(t.s))
        return "".join(literal_as_output_string(t.o) for t in items)

    # ------------------------------------------------------------------
    # Solving and unification
    # ------------------------------------------------------------------
    def solve(self, goals: list[Triple], subst: Subst, depth: int = 0) -> Iterator[Subst]:
        if depth > self.max_depth:
            return
        if not goals:
            yield dict(subst)
            return
        selected = min(range(len(goals)), key=lambda index: self._goal_rank(goals[index], subst))
        first = self.apply_subst_triple(goals[selected], subst)
        rest = goals[:selected] + goals[selected + 1:]
        # Builtins first when predicate is ground IRI.
        if isinstance(first.p, Iri):
            handler = get_builtin(first.p.value)
            if handler is not None:
                ctx = BuiltinContext(first, subst, self)
                for nxt in handler(ctx):
                    yield from self.solve(rest, nxt, depth + 1)
                return
            if first.p.value in {RDF_FIRST, RDF_REST}:
                seen_lists: set[ListTerm] = set()
                for fact in self.facts:
                    for term in (fact.s, fact.p, fact.o):
                        if isinstance(term, ListTerm) and term.elems:
                            seen_lists.add(term)
                for collection in seen_lists:
                    obj = collection.elems[0] if first.p.value == RDF_FIRST else ListTerm(collection.elems[1:])
                    nxt = self.unify_triple(first, Triple(collection, first.p, obj), subst)
                    if nxt is not None:
                        yield from self.solve(rest, nxt, depth + 1)
        # Facts. Use predicate/position indexes when the selected goal has
        # ground components; this is essential for large rule sets.
        for fact in list(self._candidate_facts(first)):
            nxt = self.unify_triple(first, fact, subst)
            if nxt is not None:
                yield from self.solve(rest, nxt, depth + 1)
        # Backward rules.
        for rule in list(self.backward_rules):
            std = self.standardize_apart(rule)
            if len(std.premise) != 1:
                # Eyeling backward rules can have a multi-triple head in rare quoted contexts;
                # the normal derived-predicate form has one head triple.
                continue
            nxt = self.unify_triple(first, std.premise[0], subst)
            if nxt is not None:
                yield from self.solve(list(std.conclusion) + rest, nxt, depth + 1)

    def _goal_rank(self, goal: Triple, subst: Subst) -> tuple[int, int]:
        applied = self.apply_subst_triple(goal, subst)

        def unbound(term: Term) -> int:
            term = self.deref(term, subst)
            if isinstance(term, Var):
                return 1
            if isinstance(term, ListTerm):
                return sum(unbound(item) for item in term.elems)
            if isinstance(term, GraphTerm):
                return sum(unbound(tr.s) + unbound(tr.p) + unbound(tr.o) for tr in term.triples)
            return 0

        variables = unbound(applied.s) + unbound(applied.o)
        if not isinstance(applied.p, Iri) or get_builtin(applied.p.value) is None:
            return (0, variables)
        if applied.p.value == "http://www.w3.org/2000/10/swap/list#iterate" and unbound(applied.s) == 0:
            return (-1, variables)
        comparisons = {
            "equalTo", "notEqualTo", "greaterThan", "lessThan",
            "notGreaterThan", "notLessThan", "contains", "startsWith",
            "endsWith", "matches", "notMatches",
        }
        local = applied.p.value.rsplit("#", 1)[-1]
        if local in {"collectAllIn", "forAllIn"}:
            return (3, variables)
        if local in comparisons and variables:
            return (2, variables)
        return (1, variables)

    def deref(self, t: Term, subst: Subst) -> Term:
        seen: set[str] = set()
        while isinstance(t, Var) and t.name in subst and t.name not in seen:
            seen.add(t.name)
            t = subst[t.name]
        return t

    def apply_subst(self, t: Term, subst: Subst) -> Term:
        t = self.deref(t, subst)
        if isinstance(t, ListTerm):
            return ListTerm(self.apply_subst(e, subst) for e in t.elems)
        if isinstance(t, OpenListTerm):
            return OpenListTerm((self.apply_subst(e, subst) for e in t.prefix), t.tail_var)
        if isinstance(t, GraphTerm):
            return GraphTerm(self.apply_subst_triple(tr, subst) for tr in t.triples)
        return t

    def apply_subst_triple(self, tr: Triple, subst: Subst, ground_blanks: bool = False) -> Triple:
        if ground_blanks:
            return self._instantiate_head_triple(tr, subst)
        return Triple(self.apply_subst(tr.s, subst), self.apply_subst(tr.p, subst), self.apply_subst(tr.o, subst))

    def _instantiate_head_triple(self, tr: Triple, subst: Subst) -> Triple:
        """Apply a substitution while skolemizing only existential blank nodes
        that are written in the rule head itself. Blank nodes reached through a
        variable binding are preserved; otherwise rules over blank-node facts
        would keep producing fresh duplicates forever.
        """
        mapping: dict[str, Blank] = {}

        def convert(original: Term) -> Term:
            if isinstance(original, Var):
                return self.apply_subst(original, subst)
            if isinstance(original, Blank):
                if original.label not in mapping:
                    self._fresh_counter += 1
                    mapping[original.label] = Blank(f"_:g{self._fresh_counter}")
                return mapping[original.label]
            if isinstance(original, ListTerm):
                return ListTerm(convert(e) for e in original.elems)
            if isinstance(original, GraphTerm):
                return GraphTerm(Triple(convert(x.s), convert(x.p), convert(x.o)) for x in original.triples)
            return self.apply_subst(original, subst)

        return Triple(convert(tr.s), convert(tr.p), convert(tr.o))

    def unify_triple(self, a: Triple, b: Triple, subst: Subst) -> Subst | None:
        s1 = self.unify_term(a.s, b.s, subst)
        if s1 is None:
            return None
        s2 = self.unify_term(a.p, b.p, s1)
        if s2 is None:
            return None
        return self.unify_term(a.o, b.o, s2)

    def unify_term(self, a: Term, b: Term, subst: Subst) -> Subst | None:
        a = self.deref(a, subst)
        b = self.deref(b, subst)
        if isinstance(a, Var):
            return self._bind(a, b, subst)
        if isinstance(b, Var):
            return self._bind(b, a, subst)
        if isinstance(a, Iri) and a.value == RDF_NIL and isinstance(b, ListTerm) and not b.elems:
            return dict(subst)
        if isinstance(b, Iri) and b.value == RDF_NIL and isinstance(a, ListTerm) and not a.elems:
            return dict(subst)
        if isinstance(a, Literal) and isinstance(b, Literal):
            if self.literal_equivalent(a, b):
                return dict(subst)
            return None
        if isinstance(a, ListTerm) and isinstance(b, ListTerm):
            if len(a.elems) != len(b.elems):
                return None
            cur = dict(subst)
            for x, y in zip(a.elems, b.elems):
                cur = self.unify_term(x, y, cur)
                if cur is None:
                    return None
            return cur
        if isinstance(a, ListTerm):
            recovered = self.rdf_collection_to_list(b)
            if recovered is not None:
                return self.unify_term(a, ListTerm(recovered), subst)
        if isinstance(b, ListTerm):
            recovered = self.rdf_collection_to_list(a)
            if recovered is not None:
                return self.unify_term(ListTerm(recovered), b, subst)
        if isinstance(a, OpenListTerm) and isinstance(b, ListTerm):
            if len(b.elems) < len(a.prefix):
                return None
            cur = dict(subst)
            for x, y in zip(a.prefix, b.elems):
                cur = self.unify_term(x, y, cur)
                if cur is None:
                    return None
            return self.unify_term(Var(a.tail_var), ListTerm(b.elems[len(a.prefix):]), cur)
        if isinstance(b, OpenListTerm) and isinstance(a, ListTerm):
            return self.unify_term(b, a, subst)
        if isinstance(a, GraphTerm) and isinstance(b, GraphTerm):
            # Treat graph/formula terms as unordered conjunctions.
            if len(a.triples) != len(b.triples):
                return None
            return self._unify_graphs(list(a.triples), list(b.triples), subst)
        return dict(subst) if a == b else None

    def _unify_graphs(self, left: list[Triple], right: list[Triple], subst: Subst) -> Subst | None:
        if not left:
            return dict(subst) if not right else None
        first = left[0]
        for i, candidate in enumerate(right):
            nxt = self.unify_triple(first, candidate, subst)
            if nxt is not None:
                rem = right[:i] + right[i+1:]
                out = self._unify_graphs(left[1:], rem, nxt)
                if out is not None:
                    return out
        return None

    def _bind(self, var: Var, value: Term, subst: Subst) -> Subst | None:
        if isinstance(value, Var) and value.name == var.name:
            return dict(subst)
        if self._occurs(var.name, value, subst):
            return None
        out = dict(subst)
        out[var.name] = value
        return out

    def _occurs(self, name: str, value: Term, subst: Subst) -> bool:
        value = self.deref(value, subst)
        if isinstance(value, Var):
            return value.name == name
        if isinstance(value, ListTerm):
            return any(self._occurs(name, e, subst) for e in value.elems)
        if isinstance(value, GraphTerm):
            return any(self._occurs(name, tr.s, subst) or self._occurs(name, tr.p, subst) or self._occurs(name, tr.o, subst) for tr in value.triples)
        return False

    def literal_equivalent(self, a: Literal, b: Literal) -> bool:
        # Unification is RDF-term equality, not numeric value equality. Numeric
        # promotion belongs to math built-ins. RDF 1.1 plain strings and
        # explicit xsd:string literals denote the same literal term here.
        a_dt = a.datatype or (XSD_NS + "string" if not a.lang else None)
        b_dt = b.datatype or (XSD_NS + "string" if not b.lang else None)
        if a_dt == b_dt:
            a_num, b_num = numeric_value(a), numeric_value(b)
            if a_num is not None and b_num is not None:
                if a_num.is_nan() or b_num.is_nan():
                    return a.lexical == b.lexical
                return a_num == b_num
        return a.lexical == b.lexical and a_dt == b_dt and (a.lang or "").lower() == (b.lang or "").lower()

    def terms_equivalent(self, a: Term, b: Term, subst: Subst) -> bool:
        return self.unify_term(a, b, subst) is not None

    def standardize_apart(self, rule: Rule) -> Rule:
        self._std_counter += 1
        prefix = f"_r{self._std_counter}_"
        def cv(t: Term) -> Term:
            if isinstance(t, Var):
                return Var(prefix + t.name)
            if isinstance(t, ListTerm):
                return ListTerm(cv(e) for e in t.elems)
            if isinstance(t, OpenListTerm):
                return OpenListTerm((cv(e) for e in t.prefix), prefix + t.tail_var)
            if isinstance(t, GraphTerm):
                return GraphTerm(Triple(cv(x.s), cv(x.p), cv(x.o)) for x in t.triples)
            return t
        return Rule((Triple(cv(t.s), cv(t.p), cv(t.o)) for t in rule.premise), (Triple(cv(t.s), cv(t.p), cv(t.o)) for t in rule.conclusion), rule.is_forward, rule.is_fuse)

    def rdf_collection_to_list(self, node: Term) -> list[Term] | None:
        seen: set[Term] = set()
        out: list[Term] = []
        cur = node
        while True:
            if isinstance(cur, Iri) and cur.value == RDF_NIL:
                return out
            if isinstance(cur, ListTerm):
                return out + list(cur.elems)
            if cur in seen:
                return None
            seen.add(cur)
            firsts = [t.o for t in self.facts if t.s == cur and isinstance(t.p, Iri) and t.p.value == RDF_FIRST]
            rests = [t.o for t in self.facts if t.s == cur and isinstance(t.p, Iri) and t.p.value == RDF_REST]
            if len(firsts) != 1 or len(rests) != 1:
                return None
            out.append(firsts[0])
            cur = rests[0]


def _merge_documents(docs: Iterable[Document]) -> Document:
    docs = list(docs)
    env = docs[0].prefixes.copy() if docs else PrefixEnv({})
    triples: list[Triple] = []
    frules: list[Rule] = []
    brules: list[Rule] = []
    qrules: list[Rule] = []
    for doc in docs:
        env.map.update(doc.prefixes.map)
        env.declared.update(doc.prefixes.declared)
        if doc.prefixes.base_iri:
            env.base_iri = doc.prefixes.base_iri
        triples.extend(doc.triples)
        frules.extend(doc.forward_rules)
        brules.extend(doc.backward_rules)
        qrules.extend(doc.query_rules)
    return Document(env, triples, frules, brules, qrules)


def _looks_like_n3_rules(text: str) -> bool:
    return '=>' in text or '<=' in text or 'log:query' in text or '<http://www.w3.org/2000/10/swap/log#query>' in text


def _parse_source_auto(text: str, options: Mapping[str, Any] | None = None, *, base_iri: str | None = None) -> Document:
    options = dict(options or {})
    src = str(text or "")
    fmt = options.get("input_format") or options.get("inputFormat")
    rdf_mode = bool(options.get("rdf") or options.get("rdf12") or fmt in {"rdf", "rdf12", "turtle", "ttl", "trig", "nt", "ntriples", "n-triples", "nquads", "n-quads"})
    if rdf_mode and is_rdf_message_log(src):
        return parse_rdf_message_log(src, base_iri=base_iri)
    if rdf_mode and not _looks_like_n3_rules(src):
        try:
            return parse_rdf_text(src, format=fmt or "auto", base_iri=base_iri, rdf12=bool(options.get("rdf12", True)))
        except Exception:
            # Fall back to the N3 parser for mixed rule/fact sources.
            pass
    return parse_n3(src, base_iri=base_iri)


def _input_to_document(input_data: Any, options: Mapping[str, Any] | None = None) -> Document:
    if input_data is None:
        return parse_n3("")
    if isinstance(input_data, str):
        return _parse_source_auto(input_data, options)
    if isinstance(input_data, Document):
        return input_data
    if isinstance(input_data, Mapping):
        if "sources" in input_data:
            docs = []
            for source_index, source in enumerate(input_data.get("sources") or []):
                if isinstance(source, Mapping):
                    text = source.get("n3") or source.get("text") or source.get("rdf") or ""
                    base = source.get("baseIri") or source.get("base_iri")
                else:
                    text = str(source)
                    base = None
                try:
                    docs.append(_parse_source_auto(str(text), options, base_iri=base))
                except N3SyntaxError as error:
                    error.source_index = source_index
                    raise
            return _merge_documents(docs)
        # Simplified Eyeling AST / Python mapping input.
        prefixes = PrefixEnv({})
        n3 = input_data.get("n3") or input_data.get("text") or input_data.get("factsN3") or input_data.get("n3Facts") or ""
        doc = _parse_source_auto(str(n3), options) if n3 else Document(prefixes, [], [], [], [])
        triples = list(doc.triples)
        for key in ("triples", "facts", "quads", "dataset"):
            val = input_data.get(key)
            if val is not None and not isinstance(val, str):
                triples.extend(triple_from_primitive(x) for x in val)
        frules = list(doc.forward_rules)
        brules = list(doc.backward_rules)
        for key in ("forwardRules", "frules"):
            if input_data.get(key):
                frules.extend(rule_from_primitive(x) for x in input_data[key])
        for key in ("backwardRules", "brules"):
            if input_data.get(key):
                brules.extend(rule_from_primitive(x) for x in input_data[key])
        return Document(doc.prefixes, triples, frules, brules, list(doc.query_rules))
    if isinstance(input_data, (list, tuple)) and len(input_data) >= 4:
        pref_obj, triples_obj, frules_obj, brules_obj = input_data[:4]
        env = PrefixEnv(dict(pref_obj.get("map", pref_obj) if isinstance(pref_obj, Mapping) else {}))
        triples = [triple_from_primitive(t) for t in triples_obj]
        frules = [rule_from_primitive(r) for r in frules_obj]
        brules = [rule_from_primitive(r) for r in brules_obj]
        qrules = [rule_from_primitive(r) for r in input_data[4]] if len(input_data) > 4 else []
        return Document(env, triples, frules, brules, qrules)
    raise TypeError("input must be an N3 string, source list, RDF-like mapping, or AST bundle")


def _normalize_options(opts: Mapping[str, Any] | None) -> dict[str, Any]:
    options = dict(opts or {})
    for arg in options.get("args", []) or []:
        if arg in {"--proof", "-p"}:
            options["proof"] = True
        if arg in {"--rdf", "-r"}:
            options["rdf"] = True
        if arg == "--ast":
            options["ast"] = True
        if arg in {"--include-input", "--include-input-facts"}:
            options["include_input_facts_in_closure"] = True
    return options


def reason_stream(input_data: Any = "", options: Mapping[str, Any] | None = None) -> ReasonStreamResult:
    options = _normalize_options(options)
    doc = _input_to_document(input_data, options)
    engine = Engine(doc, options)
    store_opt = options.get("store")
    if store_opt:
        # For sync API, store support is in-memory during the run; run_async persists.
        engine.store = create_fact_store(store_opt)
    return engine.run()


def reason(options: Mapping[str, Any] | None = None, input_data: Any = "") -> str:
    options = _normalize_options(options)
    if options.get("ast"):
        doc = _input_to_document(input_data, options)
        value = [
            {"_type": "PrefixEnv", "map": doc.prefixes.map, "baseIri": doc.prefixes.base_iri},
            [triple_to_primitive(t) for t in doc.triples],
            [{"premise": [triple_to_primitive(t) for t in r.premise], "conclusion": [triple_to_primitive(t) for t in r.conclusion], "isForward": r.is_forward} for r in doc.forward_rules],
            [{"premise": [triple_to_primitive(t) for t in r.premise], "conclusion": [triple_to_primitive(t) for t in r.conclusion], "isForward": r.is_forward} for r in doc.backward_rules],
        ]
        return json.dumps(value, indent=2, sort_keys=True)
    return reason_stream(input_data, options).closure_n3


async def run_async(input_data: Any = "", options: Mapping[str, Any] | None = None) -> ReasonStreamResult:
    options = _normalize_options(options)
    doc = _input_to_document(input_data, options)
    engine = Engine(doc, options)
    store_opt = options.get("store") or (options.get("storePath") and {"name": "default", "path": options.get("storePath"), "clear": options.get("storeClear", False)})
    if store_opt:
        store = create_fact_store(store_opt)
        # Load previous store facts.
        if hasattr(store, "triples"):
            for tr in store.triples:
                engine.add_fact(tr, inferred=False)
        result = engine.run()
        for tr in doc.triples:
            await store.add(tr, "explicit")
        for tr in result.derived:
            await store.add(tr, "inferred")
        result.store = store
        return result
    return engine.run()


def _input_to_sources(input_data: Any) -> list[tuple[str, str | None]]:
    if input_data is None:
        return [("", None)]
    if isinstance(input_data, str):
        return [(input_data, None)]
    if isinstance(input_data, Mapping) and "sources" in input_data:
        out: list[tuple[str, str | None]] = []
        for source in input_data.get("sources") or []:
            if isinstance(source, Mapping):
                out.append((str(source.get("n3") or source.get("text") or source.get("rdf") or ""), source.get("baseIri") or source.get("base_iri")))
            else:
                out.append((str(source), None))
        return out
    if isinstance(input_data, Mapping):
        return [(str(input_data.get("n3") or input_data.get("text") or input_data.get("factsN3") or input_data.get("n3Facts") or ""), None)]
    return [(str(input_data), None)]


def reason_message_stream(input_data: Any = "", options: Mapping[str, Any] | None = None) -> Iterator[ReasonStreamResult]:
    """Run rules against an RDF Message Log one replay message at a time.

    Non-message sources are parsed once as rules/facts. Each yielded result is
    equivalent to running the reasoner over those base sources plus one replay
    envelope document.
    """
    options = _normalize_options(options)
    options["rdf"] = True
    sources = _input_to_sources(input_data)
    base_docs: list[Document] = []
    message_sources: list[tuple[str, str | None]] = []
    for text, base in sources:
        if is_rdf_message_log(text):
            message_sources.append((text, base))
        elif text.strip():
            base_docs.append(_parse_source_auto(text, options, base_iri=base))
    if not message_sources:
        raise ValueError("no RDF Message Log source found")
    for text, base in message_sources:
        for message_doc in iter_rdf_message_documents(text, base_iri=base):
            doc = _merge_documents([*base_docs, message_doc])
            engine = Engine(doc, options)
            yield engine.run()
