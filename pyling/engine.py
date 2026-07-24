"""Inference engine for pyling."""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping, MutableMapping, Optional

from .builtins import BuiltinContext, get_builtin
from .parser import Document, N3SyntaxError, lex, parse_n3, parse_sources
from .rdf import is_rdf_message_log, parse_rdf_graph, parse_rdf_message_log, parse_rdf_text, iter_rdf_message_documents, triples_to_rdflib_graph
from .printing import literal_as_output_string, term_to_n3, triples_to_n3
from .store import create_fact_store
from .terms import (
    LOG_IMPLIED_BY,
    LOG_IMPLIES,
    LOG_MEMOIZE,
    LOG_NS,
    LOG_OUTPUT_STRING,
    LOG_QUERY,
    MATH_NS,
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
    literal_datatype,
    numeric_value,
    rule_from_primitive,
    rule_to_primitive,
    term_has_vars,
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
    s_key: Any | None
    o_key: Any | None
    fast_subject_var: str | None = None
    fast_object_var: str | None = None


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

    def as_rdflib_graph(self, *, include_input_facts: bool = False):
        if include_input_facts:
            triples = self.facts
        elif self.query_mode:
            triples = self.query_triples
        else:
            triples = self.derived
        return triples_to_rdflib_graph(triples, self.prefixes)


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
        self._facts_by_list_component: dict[
            tuple[Term, str, tuple[int, ...], Any], list[Triple]
        ] = {}
        self._var_pred_facts: list[Triple] = []
        for _tr in self.facts:
            self._index_fact(_tr)
        self._indexed_facts_obj_id = id(self.facts)
        self._indexed_facts_len = len(self.facts)
        self.derived: list[Triple] = []
        self.forward_rules: list[Rule] = list(doc.forward_rules)
        self.backward_rules: list[Rule] = list(doc.backward_rules)
        self._backward_rules_by_pred: dict[str, list[Rule]] = {}
        self._wild_backward_rules: list[Rule] = []
        for _rule in self.backward_rules:
            if len(_rule.premise) != 1:
                continue
            if isinstance(_rule.premise[0].p, Iri):
                self._backward_rules_by_pred.setdefault(_rule.premise[0].p.value, []).append(_rule)
            else:
                self._wild_backward_rules.append(_rule)
        self._backward_predicates: set[str] = {
            rule.premise[0].p.value
            for rule in self.backward_rules
            if len(rule.premise) == 1 and isinstance(rule.premise[0].p, Iri)
        }
        self._has_wild_backward_predicate = any(
            len(rule.premise) == 1 and not isinstance(rule.premise[0].p, Iri)
            for rule in self.backward_rules
        )
        self.query_rules: list[Rule] = list(doc.query_rules)
        self._rule_key_cache: dict[Rule, str] = {}
        self._rule_ids: set[str] = {self._rule_key(r) for r in self.forward_rules + self.backward_rules}
        self._fired_rule_bindings: set[tuple[int, tuple[Triple, ...]]] = set()
        self._rule_input_signatures: dict[Rule, tuple] = {}
        self._agenda_active = False
        self._agenda_queue: list[Triple] = []
        self._agenda_indexed_rules: set[Rule] = set()
        self._agenda_by_pred: dict[Term, list[_AgendaEntry]] = {}
        self._agenda_by_ps: dict[tuple[Term, Term], list[_AgendaEntry]] = {}
        self._agenda_by_po: dict[tuple[Term, Term], list[_AgendaEntry]] = {}
        self._agenda_all_entries: list[_AgendaEntry] = []
        self._fresh_counter = 0
        self._std_counter = 0
        self._standardized_term_cache: dict[str, Term] = {}
        self._rule_fact_view_active = True
        self.max_depth = int(self.options.get("max_depth", self.options.get("maxDepth", 100_000)))
        self.max_iterations = int(self.options.get("max_iterations", self.options.get("maxIterations", 1000)))
        self.skolem_salt = str(uuid.uuid4())
        self.store = None
        # Opt-in backward-goal memoization/tabling, declared with top-level
        # facts of the form `<predicate> log:memoize true.` (see the Eyeling
        # JS reference engine). See _extract_memoize_declarations and solve().
        self._memoized_predicates: set[str] = set()
        self._predicate_memo_tables: dict[tuple, dict[str, dict[str, Any]]] = {}
        self._bottom_up_memo_active: set[tuple[str, int]] = set()
        self._goal_memo_version: tuple | None = None
        self._goal_memo_table: dict[str, list[Subst]] = {}
        self._term_substitution_cache: dict[int, tuple[Term, bool]] = {}
        self._extract_memoize_declarations()

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
            "d": term_to_primitive(r.dynamic_conclusion) if r.dynamic_conclusion is not None else None,
        }, sort_keys=True, default=str)
        if hasattr(self, "_rule_key_cache"):
            self._rule_key_cache[r] = key
        return key

    def _lookup_key(self, term: Term) -> Any | None:
        """Return an exact-match index key, or None when broad unification is needed."""
        term = self.deref(term, {})
        if isinstance(term, Var) or isinstance(term, OpenListTerm):
            return None
        if isinstance(term, Literal):
            datatype = literal_datatype(term)
            number = numeric_value(term)
            if number is not None and not number.is_nan():
                return ("literal-number", datatype, number)
            if datatype in {XSD_NS + "date", XSD_NS + "dateTime"}:
                import datetime

                try:
                    if datatype == XSD_NS + "dateTime":
                        value = datetime.datetime.fromisoformat(term.lexical.replace("Z", "+00:00"))
                    else:
                        value = datetime.date.fromisoformat(term.lexical)
                    return ("literal-temporal", datatype, value)
                except ValueError:
                    pass
            return ("literal", datatype, (term.lang or "").lower(), term.lexical)
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
        for side, term in (("s", tr.s), ("o", tr.o)):
            for path, key in self._list_component_keys(term):
                index_key = (tr.p, side, path, key)
                self._facts_by_list_component.setdefault(index_key, []).append(tr)

    def _list_component_keys(
        self, term: Term, path: tuple[int, ...] = ()
    ) -> Iterator[tuple[tuple[int, ...], Any]]:
        if not isinstance(term, ListTerm):
            return
        for index, item in enumerate(term.elems):
            item_path = path + (index,)
            key = self._lookup_key(item)
            if key is not None:
                yield item_path, key
            if isinstance(item, ListTerm):
                yield from self._list_component_keys(item, item_path)

    def _rebuild_fact_indexes(self) -> None:
        self._facts_by_pred.clear()
        self._facts_by_ps.clear()
        self._facts_by_po.clear()
        self._facts_by_list_component.clear()
        self._var_pred_facts.clear()
        for tr in self.facts:
            self._index_fact(tr)
        self._indexed_facts_obj_id = id(self.facts)
        self._indexed_facts_len = len(self.facts)

    def _extract_memoize_declarations(self) -> None:
        """Pull out `<predicate> log:memoize true.` directives.

        These are engine hints, not data triples, so they are removed from
        the fact set (matching the Eyeling JS reference engine) and recorded
        in `self._memoized_predicates` for `solve()` to consult.
        """
        kept: list[Triple] = []
        changed = False
        for tr in self.facts:
            if (
                isinstance(tr.p, Iri) and tr.p.value == LOG_MEMOIZE
                and isinstance(tr.s, Iri)
                and isinstance(tr.o, Literal) and bool_value(tr.o) is True
            ):
                self._memoized_predicates.add(tr.s.value)
                changed = True
                continue
            kept.append(tr)
        if changed:
            self.facts = kept
            self._fact_set = set(kept)
            self._rebuild_fact_indexes()

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
            if bucket is None:
                return list(self._var_pred_facts)
            candidates.append(bucket)
        ok = self._lookup_key(goal.o)
        if ok is not None:
            bucket = self._facts_by_po.get((goal.p, ok))
            if bucket is None:
                return list(self._var_pred_facts)
            candidates.append(bucket)
        component_candidates: list[list[Triple]] = []
        for side, term in (("s", goal.s), ("o", goal.o)):
            for path, key in self._list_component_keys(term):
                index_key = (goal.p, side, path, key)
                bucket = self._facts_by_list_component.get(index_key)
                if bucket is None:
                    return list(self._var_pred_facts)
                component_candidates.append(bucket)
        if component_candidates:
            smallest = min(component_candidates, key=len)
            if len(component_candidates) == 1:
                candidates.append(smallest)
            else:
                shared = {id(fact) for fact in smallest}
                for bucket in component_candidates:
                    if bucket is not smallest:
                        shared.intersection_update(id(fact) for fact in bucket)
                candidates.append([fact for fact in smallest if id(fact) in shared])
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
        if (
            not any(term_has_vars(term) for term in (tr.s, tr.p, tr.o))
            and any(self._has_numeric_literal(term) for term in (tr.s, tr.p, tr.o))
        ):
            for existing in self._candidate_facts(tr):
                if self._fact_terms_equal(tr.s, existing.s) and self._fact_terms_equal(
                    tr.p, existing.p
                ) and self._fact_terms_equal(tr.o, existing.o):
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
        rule = self._rule_from_fact(tr)
        if rule is not None:
            self.add_rule(rule)
        return True

    def _has_numeric_literal(self, term: Term) -> bool:
        if isinstance(term, Literal):
            return numeric_value(term) is not None
        if isinstance(term, ListTerm):
            return any(self._has_numeric_literal(item) for item in term.elems)
        if isinstance(term, GraphTerm):
            return any(
                self._has_numeric_literal(item)
                for triple in term.triples
                for item in (triple.s, triple.p, triple.o)
            )
        return False

    def _fact_terms_equal(self, left: Term, right: Term) -> bool:
        if left == right:
            return True
        if isinstance(left, Literal) and isinstance(right, Literal):
            left_number = numeric_value(left)
            right_number = numeric_value(right)
            return (
                left_number is not None
                and right_number is not None
                and literal_datatype(left) == literal_datatype(right)
                and not left_number.is_nan()
                and not right_number.is_nan()
                and left_number == right_number
            )
        if isinstance(left, ListTerm) and isinstance(right, ListTerm):
            return len(left.elems) == len(right.elems) and all(
                self._fact_terms_equal(a, b) for a, b in zip(left.elems, right.elems)
            )
        return False

    def _rule_from_fact(self, tr: Triple) -> Rule | None:
        if not isinstance(tr.p, Iri):
            return None
        blank_vars: dict[str, Var] = {}

        def antecedent_term(term: Term) -> Term:
            if isinstance(term, Blank):
                return blank_vars.setdefault(term.label, Var(f"_blank_{term.label}"))
            if isinstance(term, ListTerm):
                return ListTerm(antecedent_term(item) for item in term.elems)
            if isinstance(term, OpenListTerm):
                return OpenListTerm((antecedent_term(item) for item in term.prefix), term.tail_var)
            if isinstance(term, GraphTerm):
                return GraphTerm(
                    Triple(antecedent_term(item.s), antecedent_term(item.p), antecedent_term(item.o))
                    for item in term.triples
                )
            return term

        def antecedent(triples: Iterable[Triple]) -> tuple[Triple, ...]:
            return tuple(
                Triple(antecedent_term(item.s), antecedent_term(item.p), antecedent_term(item.o))
                for item in triples
            )

        if tr.p.value == LOG_IMPLIES:
            if isinstance(tr.s, GraphTerm) and isinstance(tr.o, GraphTerm):
                return Rule(antecedent(tr.s.triples), tr.o.triples, True)
            if isinstance(tr.s, GraphTerm) and isinstance(tr.o, Literal):
                value = bool_value(tr.o)
                if value is False:
                    return Rule(antecedent(tr.s.triples), (), True, True)
                if value is True:
                    return Rule(antecedent(tr.s.triples), (), True)
            if isinstance(tr.s, Literal) and bool_value(tr.s) is True and isinstance(tr.o, GraphTerm):
                return Rule((), tr.o.triples, True)
        if tr.p.value == LOG_IMPLIED_BY and isinstance(tr.s, GraphTerm):
            if isinstance(tr.o, GraphTerm):
                return Rule(antecedent(tr.s.triples), tr.o.triples, False)
            if isinstance(tr.o, Literal) and bool_value(tr.o) is True:
                return Rule(tr.s.triples, (), False)
        return None

    def _rule_as_fact(self, rule: Rule) -> Triple:
        """Expose a live rule to meta-rules without materializing it as output."""
        if rule.is_forward:
            subject: Term = GraphTerm(rule.premise) if rule.premise else Literal("true", XSD_NS + "boolean", bare=True)
            if rule.is_fuse:
                obj: Term = Literal("false", XSD_NS + "boolean", bare=True)
            elif rule.dynamic_conclusion is not None:
                obj = rule.dynamic_conclusion
            else:
                obj = GraphTerm(rule.conclusion)
            return Triple(subject, Iri(LOG_IMPLIES), obj)
        subject = GraphTerm(rule.premise)
        obj = GraphTerm(rule.conclusion) if rule.conclusion else Literal("true", XSD_NS + "boolean", bare=True)
        return Triple(subject, Iri(LOG_IMPLIED_BY), obj)

    def _candidate_rule_facts(self, goal: Triple) -> Iterator[Triple]:
        if not self._rule_fact_view_active:
            return
        predicate = goal.p
        if isinstance(predicate, Iri):
            if predicate.value == LOG_IMPLIES:
                rules: Iterable[Rule] = self.forward_rules
            elif predicate.value == LOG_IMPLIED_BY:
                rules = self.backward_rules
            else:
                return
        elif isinstance(predicate, Var):
            rules = (*self.forward_rules, *self.backward_rules)
        else:
            return
        for rule in rules:
            # Universal variables in the exposed rule have their own scope.
            yield self._rule_as_fact(self.standardize_apart(rule))

    def add_rule(self, rule: Rule) -> bool:
        key = self._rule_key(rule)
        if key in self._rule_ids:
            return False
        self._rule_ids.add(key)
        if rule.is_forward:
            self.forward_rules.append(rule)
        else:
            self.backward_rules.append(rule)
            if len(rule.premise) == 1 and isinstance(rule.premise[0].p, Iri):
                self._backward_predicates.add(rule.premise[0].p.value)
                self._backward_rules_by_pred.setdefault(rule.premise[0].p.value, []).append(rule)
            elif len(rule.premise) == 1:
                self._has_wild_backward_predicate = True
                self._wild_backward_rules.append(rule)
            if self._agenda_active:
                # Forward rules indexed before this derived backward rule
                # existed may now be provable without an extensional fact.
                # Return them to the generic solver on the next iteration.
                self._agenda_indexed_rules.clear()
                self._agenda_active = False
                self._agenda_queue.clear()
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

    def _rule_has_strict_ground_head(self, rule: Rule) -> bool:
        return (
            rule.dynamic_conclusion is None
            and bool(rule.conclusion)
            and not self._rule_has_head_blanks(rule)
            and all(
                not term_has_vars(term)
                for triple in rule.conclusion
                for term in (triple.s, triple.p, triple.o)
            )
        )

    def _is_fast_single_premise_rule(self, rule: Rule) -> bool:
        if rule.is_fuse or rule.dynamic_conclusion is not None or len(rule.premise) != 1:
            return False
        if self._rule_has_head_blanks(rule):
            # Preserve legacy blank-node allocation order for existential heads.
            return False
        goal = rule.premise[0]
        if not isinstance(goal.p, Iri):
            return False
        if goal.p.value in {LOG_IMPLIES, LOG_IMPLIED_BY}:
            # Live rules are exposed through a virtual rule-as-data view that
            # is consulted by the generic solver, not the extensional agenda.
            return False
        if self._has_wild_backward_predicate or goal.p.value in self._backward_predicates:
            # A backward rule may prove this premise without an extensional
            # fact. Keep only that predicate on the complete solver path.
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
            s_key = self._lookup_key(goal.s)
            o_key = self._lookup_key(goal.o)
            entry = _AgendaEntry(
                rule,
                i,
                goal,
                s_key,
                o_key,
                goal.s.name if isinstance(goal.s, Var) and o_key is not None else None,
                goal.o.name if isinstance(goal.o, Var) and s_key is not None else None,
            )
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
        if entry.fast_subject_var is not None:
            subst = {entry.fast_subject_var: fact.s}
        elif entry.fast_object_var is not None:
            subst = {entry.fast_object_var: fact.o}
        else:
            subst = self.unify_triple(entry.goal, fact, {})
            if subst is None:
                return False
        changed = False
        for head in entry.rule.conclusion:
            if not self._head_template_is_bound(head, subst):
                continue
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

    def _rule_uses_scoped_builtin(self, rule: Rule) -> bool:
        scoped = {
            LOG_NS + "collectAllIn",
            LOG_NS + "forAllIn",
            LOG_NS + "includes",
            LOG_NS + "notIncludes",
        }
        return any(isinstance(goal.p, Iri) and goal.p.value in scoped for goal in rule.premise)

    def _rule_uses_aggregate_builtin(self, rule: Rule) -> bool:
        return any(
            isinstance(goal.p, Iri) and goal.p.value == LOG_NS + "collectAllIn"
            for goal in rule.premise
        )

    def _rule_input_signature(self, rule: Rule) -> tuple:
        self._ensure_fact_indexes_current()
        dependencies: set[Iri] = set()
        pending: list[Iri] = []
        broad = self._rule_uses_scoped_builtin(rule)

        def add_goal(goal: Triple) -> None:
            nonlocal broad
            if isinstance(goal.p, Var):
                broad = True
            elif isinstance(goal.p, Iri) and get_builtin(goal.p.value) is None and goal.p not in dependencies:
                dependencies.add(goal.p)
                pending.append(goal.p)

        for goal in rule.premise:
            add_goal(goal)
        seen_backward: set[str] = set()
        while pending:
            predicate = pending.pop()
            if predicate.value in seen_backward:
                continue
            seen_backward.add(predicate.value)
            for backward in self.backward_rules:
                if (
                    len(backward.premise) == 1
                    and isinstance(backward.premise[0].p, Iri)
                    and backward.premise[0].p.value == predicate.value
                ):
                    for body_goal in backward.conclusion:
                        add_goal(body_goal)

        counts = tuple(
            (predicate.value, len(self._facts_by_pred.get(predicate, ())))
            for predicate in sorted(dependencies, key=lambda item: item.value)
        )
        return (
            len(self.facts) if broad else None,
            len(self.forward_rules),
            len(self.backward_rules),
            counts,
        )

    def _evaluate_forward_rules(self, rules: Iterable[Rule]) -> bool:
        changed = False
        for rule in rules:
            if rule.is_fuse:
                continue
            strict_ground_head = self._rule_has_strict_ground_head(rule)
            if strict_ground_head and all(head in self._fact_set for head in rule.conclusion):
                continue
            input_signature = self._rule_input_signature(rule)
            if self._rule_input_signatures.get(rule) == input_signature:
                continue
            self._rule_input_signatures[rule] = input_signature
            has_head_blanks = self._rule_has_head_blanks(rule)
            solution_iter = self.solve(list(rule.premise), {})
            if strict_ground_head:
                first_solution = next(solution_iter, None)
                solutions: Iterable[Subst] = () if first_solution is None else (first_solution,)
            else:
                # Freeze the answer set before adding facts. Derived facts
                # invalidate proof tables and must not perturb this traversal.
                solutions = list(solution_iter)
            for subst in solutions:
                if has_head_blanks:
                    firing_key = self._firing_key(rule, subst)
                    if firing_key in self._fired_rule_bindings:
                        continue
                    self._fired_rule_bindings.add(firing_key)
                heads = list(rule.conclusion)
                if rule.dynamic_conclusion is not None:
                    dynamic = self.apply_subst(rule.dynamic_conclusion, subst)
                    if isinstance(dynamic, GraphTerm):
                        heads.extend(dynamic.triples)
                    elif isinstance(dynamic, Literal) and bool_value(dynamic) is False:
                        raise InferenceFuseError()
                blank_mapping: dict[str, Blank] = {}
                for head in heads:
                    if not self._head_template_is_bound(head, subst):
                        continue
                    fact = self.apply_subst_triple(
                        head,
                        subst,
                        ground_blanks=True,
                        blank_mapping=blank_mapping,
                    )
                    if self.add_fact(fact, inferred=True):
                        changed = True
        return changed

    def run(self) -> ReasonStreamResult:
        # Top-level log:implies facts are live rules immediately.
        for tr in list(self.facts):
            rule = self._rule_from_fact(tr)
            if rule is not None:
                self.add_rule(rule)
        self._build_single_premise_agenda()
        self._agenda_active = bool(self._agenda_indexed_rules)
        if self._agenda_active:
            self._agenda_queue = list(self.facts)
            self._drain_single_premise_agenda()

        # Validate immediate sameAs reflexivity facts are usable. No full OWL closure is intended.
        for iteration in range(self.max_iterations):
            # Rules not covered by the agenda still use the complete solver. This
            # preserves general N3 behavior while avoiding O(rules * facts * depth)
            # scans for the common single-premise Horn-chain case.
            rules_snapshot = [r for r in self.forward_rules if r not in self._agenda_indexed_rules]
            ordinary_rules = [rule for rule in rules_snapshot if not self._rule_uses_scoped_builtin(rule)]
            lower_scoped_rules = [
                rule
                for rule in rules_snapshot
                if self._rule_uses_scoped_builtin(rule) and not self._rule_uses_aggregate_builtin(rule)
            ]
            aggregate_rules = [rule for rule in rules_snapshot if self._rule_uses_aggregate_builtin(rule)]
            changed = self._evaluate_forward_rules(ordinary_rules)
            if self._agenda_active and self._agenda_queue:
                changed = self._drain_single_premise_agenda() or changed
            if not changed:
                changed = self._evaluate_forward_rules(lower_scoped_rules)
                if self._agenda_active and self._agenda_queue:
                    changed = self._drain_single_premise_agenda() or changed
            if not changed:
                changed = self._evaluate_forward_rules(aggregate_rules)
                if self._agenda_active and self._agenda_queue:
                    changed = self._drain_single_premise_agenda() or changed
            if not changed:
                break
        else:
            raise RuntimeError(f"reasoning did not reach a fixpoint after {self.max_iterations} iterations")

        # Fuses are closure assertions. Evaluate them only after ordinary
        # forward rules have saturated, matching Eyeling's frozen-snapshot
        # semantics for log:includes/log:notIncludes.
        for rule in self.forward_rules:
            if rule.is_fuse and any(True for _ in self.solve(list(rule.premise), {})):
                raise InferenceFuseError()

        query_derived: list[Triple] = []
        if self.query_rules:
            seen: set[Triple] = set()
            for qr in self.query_rules:
                for subst in self.solve(list(qr.premise), {}):
                    blank_mapping: dict[str, Blank] = {}
                    for head in qr.conclusion:
                        if not self._head_template_is_bound(head, subst):
                            continue
                        tr = self.apply_subst_triple(
                            head,
                            subst,
                            ground_blanks=True,
                            blank_mapping=blank_mapping,
                        )
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

    def _firing_key(self, rule: Rule, subst: Subst) -> tuple[int, tuple[Triple, ...]]:
        return (
            id(rule),
            tuple(self.apply_subst_triple(goal, subst) for goal in rule.premise),
        )

    def _has_output_strings(self, triples: Iterable[Triple]) -> bool:
        return any(isinstance(t.p, Iri) and t.p.value == LOG_OUTPUT_STRING for t in triples)

    def _render_output_strings(self, triples: Iterable[Triple]) -> str:
        items = [t for t in triples if isinstance(t.p, Iri) and t.p.value == LOG_OUTPUT_STRING]
        items.sort(key=lambda t: self.term_to_n3(t.s))
        return "".join(literal_as_output_string(t.o) for t in items)

    # ------------------------------------------------------------------
    # Backward-goal memoization (tabling)
    #
    # Opt-in, predicate-scoped answer caching for backward-chained goals,
    # ported from the Eyeling JS reference engine's `log:memoize` support.
    # Only predicates explicitly declared with `<predicate> log:memoize
    # true.` are affected, so it cannot change results for programs that
    # don't use it. A goal is only cacheable once its *entire* answer set has
    # been enumerated ("complete"), and only when at least one of its subject
    # or object is fully ground (no Var/Blank/OpenListTerm anywhere), since
    # that is what makes the cache key well-defined. The cache is scoped to
    # the current fact/rule set so it is automatically invalidated whenever
    # facts are added or `engine.facts` is swapped (e.g. by the log:includes/
    # log:notIncludes built-ins).
    # ------------------------------------------------------------------
    def _term_has_var_or_blank(self, term: Term) -> bool:
        if isinstance(term, (Var, Blank, OpenListTerm)):
            return True
        if isinstance(term, ListTerm):
            return any(self._term_has_var_or_blank(e) for e in term.elems)
        if isinstance(term, GraphTerm):
            return any(
                self._term_has_var_or_blank(tr.s) or self._term_has_var_or_blank(tr.p) or self._term_has_var_or_blank(tr.o)
                for tr in term.triples
            )
        return False

    def _term_contains_unbound_var(self, term: Term) -> bool:
        if isinstance(term, Var):
            return True
        if isinstance(term, ListTerm):
            return any(self._term_contains_unbound_var(item) for item in term.elems)
        if isinstance(term, OpenListTerm):
            return True
        if isinstance(term, GraphTerm):
            return any(
                self._term_contains_unbound_var(item.s)
                or self._term_contains_unbound_var(item.p)
                or self._term_contains_unbound_var(item.o)
                for item in term.triples
            )
        return False

    def _term_needs_substitution(self, term: Term) -> bool:
        if isinstance(term, (Iri, Literal, Blank)):
            return False
        if isinstance(term, (Var, OpenListTerm)):
            return True
        identity = id(term)
        cached = self._term_substitution_cache.get(identity)
        if cached is not None and cached[0] is term:
            return cached[1]
        if isinstance(term, ListTerm):
            result = any(self._term_needs_substitution(item) for item in term.elems)
        elif isinstance(term, GraphTerm):
            result = any(
                self._term_needs_substitution(item.s)
                or self._term_needs_substitution(item.p)
                or self._term_needs_substitution(item.o)
                for item in term.triples
            )
        else:
            result = True
        self._term_substitution_cache[identity] = (term, result)
        return result

    def _triple_contains_unbound_var(self, triple: Triple) -> bool:
        return (
            self._term_contains_unbound_var(triple.s)
            or self._term_contains_unbound_var(triple.p)
            or self._term_contains_unbound_var(triple.o)
        )

    def _head_template_is_bound(self, triple: Triple, subst: Subst) -> bool:
        def bound(term: Term) -> bool:
            if isinstance(term, Var):
                return not isinstance(self.apply_subst(term, subst), Var)
            if isinstance(term, ListTerm):
                return all(bound(item) for item in term.elems)
            if isinstance(term, OpenListTerm):
                return False
            if isinstance(term, GraphTerm):
                # Variables inside a quoted formula have formula-local scope.
                return True
            return True

        return bound(triple.s) and bound(triple.p) and bound(triple.o)

    def _can_memoize_answer_term(self, term: Term) -> bool:
        if isinstance(term, (Var, OpenListTerm)):
            return False
        if isinstance(term, ListTerm):
            return all(self._can_memoize_answer_term(e) for e in term.elems)
        if isinstance(term, GraphTerm):
            return all(
                self._can_memoize_answer_term(tr.s) and self._can_memoize_answer_term(tr.p) and self._can_memoize_answer_term(tr.o)
                for tr in term.triples
            )
        return True

    def _memo_term_key(self, term: Term) -> str:
        return json.dumps(term_to_primitive(term), sort_keys=True, default=str)

    def _predicate_memo_key(self, goal: Triple) -> str | None:
        if not isinstance(goal.p, Iri):
            return None
        s_bound = not self._term_has_var_or_blank(goal.s)
        o_bound = not self._term_has_var_or_blank(goal.o)
        if not s_bound and not o_bound:
            return None
        s_part = self._memo_term_key(goal.s) if s_bound else "_"
        o_part = self._memo_term_key(goal.o) if o_bound else "_"
        return f"{goal.p.value}|{s_part}|{o_part}"

    def _memo_scope_version(self) -> tuple:
        # The cache is only valid while the underlying fact/rule set is
        # unchanged. `engine.facts` is a different list object whenever
        # log:includes/log:notIncludes swap in a scoped formula, so this
        # naturally partitions the cache per scope.
        return (id(self.facts), len(self.facts), len(self.backward_rules))

    def _predicate_memo_lookup(self, key: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        version = self._memo_scope_version()
        table = self._predicate_memo_tables.get(version)
        if table is None:
            table = {}
            self._predicate_memo_tables[version] = table
        entry = table.get(key)
        if entry is None:
            entry = {"computing": False, "complete": False, "unsafe": False, "answers": [], "answer_keys": set()}
            table[key] = entry
        return table, entry

    def _store_predicate_memo_answer(self, entry: dict[str, Any], goal: Triple, subst: Subst) -> None:
        answer = self.apply_subst_triple(goal, subst)
        if not (
            self._can_memoize_answer_term(answer.s)
            and self._can_memoize_answer_term(answer.p)
            and self._can_memoize_answer_term(answer.o)
        ):
            entry["unsafe"] = True
            return
        key = self._memo_term_key(answer.s) + "\t" + self._memo_term_key(answer.p) + "\t" + self._memo_term_key(answer.o)
        if key in entry["answer_keys"]:
            return
        entry["answer_keys"].add(key)
        entry["answers"].append(answer)

    def _integer_literal_value(self, term: Term) -> int | None:
        term = self.deref(term, {})
        if not isinstance(term, Literal) or term.datatype != XSD_NS + "integer":
            return None
        try:
            return int(term.lexical)
        except ValueError:
            return None

    def _memo_goal_for_integer_subject(self, predicate: Iri, value: int) -> Triple:
        return Triple(Literal(str(value), XSD_NS + "integer", bare=True), predicate, Var("_memo_answer"))

    def _rules_are_bottom_up_numeric_safe(self, predicate: Iri, rules: list[Rule]) -> bool:
        has_recursive_rule = False
        difference = Iri(MATH_NS + "difference")
        for rule in rules:
            head = rule.premise[0]
            if not rule.conclusion:
                continue
            if not isinstance(head.s, Var):
                return False
            smaller_subject_vars: set[str] = set()
            for tr in rule.conclusion:
                if (
                    tr.p == difference
                    and isinstance(tr.s, ListTerm)
                    and len(tr.s.elems) == 2
                    and isinstance(tr.s.elems[0], Var)
                    and tr.s.elems[0].name == head.s.name
                    and isinstance(tr.o, Var)
                ):
                    step = self._integer_literal_value(tr.s.elems[1])
                    if step is not None and step > 0:
                        smaller_subject_vars.add(tr.o.name)
                if tr.p == predicate:
                    has_recursive_rule = True
                    if not isinstance(tr.s, Var) or tr.s.name not in smaller_subject_vars:
                        return False
        return has_recursive_rule

    def _try_bottom_up_numeric_memo(self, goal: Triple) -> dict[str, Any] | None:
        """Materialize memoized integer-subject answers bottom-up.

        This covers dynamic-programming-shaped backward predicates such as the
        Eyeling Fibonacci example. It only activates for calls like
        `N :predicate ?answer`, where `N` is a non-negative integer and the
        object is unbound. Other memoized predicates keep the normal prover
        behavior.
        """
        if not isinstance(goal.p, Iri) or not isinstance(goal.o, Var):
            return None
        target = self._integer_literal_value(goal.s)
        if target is None or target < 0:
            return None
        active_key = (goal.p.value, target)
        if active_key in self._bottom_up_memo_active:
            return None

        relevant_rules = [
            rule
            for rule in self.backward_rules
            if len(rule.premise) == 1
            and isinstance(rule.premise[0].p, Iri)
            and rule.premise[0].p.value == goal.p.value
        ]
        if not relevant_rules:
            return None
        if not self._rules_are_bottom_up_numeric_safe(goal.p, relevant_rules):
            return None

        self._bottom_up_memo_active.add(active_key)
        try:
            for value in range(target + 1):
                row_goal = self._memo_goal_for_integer_subject(goal.p, value)
                row_key = self._predicate_memo_key(row_goal)
                if row_key is None:
                    return None
                _table, row_entry = self._predicate_memo_lookup(row_key)
                if row_entry["complete"]:
                    continue
                if row_entry["computing"]:
                    return None
                row_entry["computing"] = True
                row_entry["unsafe"] = False
                row_entry["answers"] = []
                row_entry["answer_keys"] = set()
                try:
                    for rule in relevant_rules:
                        std = self.standardize_apart(rule)
                        local = self.unify_triple(row_goal, std.premise[0], {})
                        if local is None:
                            continue
                        for answer_subst in self.solve(list(std.conclusion), local, 0, False):
                            self._store_predicate_memo_answer(row_entry, row_goal, answer_subst)
                    if row_entry["unsafe"]:
                        return None
                    row_entry["complete"] = True
                finally:
                    row_entry["computing"] = False
            target_key = self._predicate_memo_key(goal)
            if target_key is None:
                return None
            _table, target_entry = self._predicate_memo_lookup(target_key)
            return target_entry if target_entry["complete"] else None
        finally:
            self._bottom_up_memo_active.discard(active_key)

    # ------------------------------------------------------------------
    # Solving and unification
    # ------------------------------------------------------------------
    def _completed_goal_memo_key(
        self,
        goals: list[Triple],
        subst: Subst,
        allow_reorder: bool,
    ) -> str:
        instantiated = [triple_to_primitive(self.apply_subst_triple(goal, subst)) for goal in goals]
        return json.dumps(
            {"reorder": allow_reorder, "goals": instantiated},
            sort_keys=True,
            default=str,
        )

    def _completed_goal_memo(self) -> dict[str, list[Subst]]:
        version = self._memo_scope_version()
        if self._goal_memo_version != version:
            self._goal_memo_version = version
            self._goal_memo_table = {}
        return self._goal_memo_table

    def solve(
        self,
        goals: list[Triple],
        subst: Subst,
        depth: int = 0,
        allow_reorder: bool = True,
        _visited: frozenset[str] | None = None,
    ) -> Iterator[Subst]:
        """Prove goals with iterative DFS and trail-backed substitutions."""
        goal_memo_key: str | None = None
        goal_memo: dict[str, list[Subst]] | None = None
        if depth == 0 and not _visited and not subst:
            goal_memo = self._completed_goal_memo()
            goal_memo_key = self._completed_goal_memo_key(goals, subst, allow_reorder)
            cached = goal_memo.get(goal_memo_key)
            if cached is not None:
                for answer in cached:
                    yield dict(answer)
                return

        subst_mut: Subst = dict(subst)
        trail: list[str] = []
        visited_counts: dict[str, int] = {key: 1 for key in (_visited or frozenset())}
        visited_trail: list[str] = []
        answer_vars = set(subst)

        def collect_vars(term: Term, target: set[str]) -> None:
            if not self._term_needs_substitution(term):
                return
            if isinstance(term, Var):
                target.add(term.name)
            elif isinstance(term, ListTerm):
                for item in term.elems:
                    collect_vars(item, target)
            elif isinstance(term, OpenListTerm):
                for item in term.prefix:
                    collect_vars(item, target)
                target.add(term.tail_var)
            elif isinstance(term, GraphTerm):
                for triple in term.triples:
                    collect_vars(triple.s, target)
                    collect_vars(triple.p, target)
                    collect_vars(triple.o, target)

        for original_goal in goals:
            collect_vars(original_goal.s, answer_vars)
            collect_vars(original_goal.p, answer_vars)
            collect_vars(original_goal.o, answer_vars)
        completed_answers: list[Subst] = []

        def goal_key(goal: Triple) -> str:
            primitive = triple_to_primitive(goal)

            def canonicalize(value: Any) -> Any:
                if isinstance(value, dict):
                    if value.get("_type") == "Var":
                        return {"_type": "Var", "name": "*"}
                    return {key: canonicalize(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [canonicalize(item) for item in value]
                return value

            # Standardized rule variables change names at every recursive
            # call, so normalize variables for cycle detection. Blank nodes
            # remain identity-bearing terms and must not be collapsed.
            return json.dumps(canonicalize(primitive), sort_keys=True, default=str)

        def undo_to(mark: int) -> None:
            for name in reversed(trail[mark:]):
                subst_mut.pop(name, None)
            del trail[mark:]

        def push_visited(key: str) -> None:
            visited_counts[key] = visited_counts.get(key, 0) + 1
            visited_trail.append(key)

        def undo_visited_to(mark: int) -> None:
            for key in reversed(visited_trail[mark:]):
                count = visited_counts.get(key, 0)
                if count <= 1:
                    visited_counts.pop(key, None)
                else:
                    visited_counts[key] = count - 1
            del visited_trail[mark:]

        def occurs(name: str, value: Term) -> bool:
            value = self.deref(value, subst_mut)
            if not self._term_needs_substitution(value):
                return False
            if isinstance(value, Var):
                return value.name == name
            if isinstance(value, ListTerm):
                return any(occurs(name, item) for item in value.elems)
            if isinstance(value, OpenListTerm):
                return (
                    value.tail_var == name
                    or any(occurs(name, item) for item in value.prefix)
                    or occurs(name, Var(value.tail_var))
                )
            if isinstance(value, GraphTerm):
                return any(
                    occurs(name, triple.s) or occurs(name, triple.p) or occurs(name, triple.o)
                    for triple in value.triples
                )
            return False

        def bind_var(var: Var, value: Term) -> bool:
            if var.name in subst_mut:
                return unify_term_trail(subst_mut[var.name], value)
            if isinstance(value, Var) and value.name == var.name:
                return True
            if occurs(var.name, value):
                return False
            subst_mut[var.name] = value
            trail.append(var.name)
            return True

        def unify_graphs_trail(left: tuple[Triple, ...], right: tuple[Triple, ...]) -> bool:
            if len(left) != len(right):
                return False
            used = [False] * len(right)

            def step(index: int) -> bool:
                if index >= len(left):
                    return True
                current = left[index]
                for candidate_index, candidate in enumerate(right):
                    if used[candidate_index]:
                        continue
                    if (
                        isinstance(current.p, Iri)
                        and isinstance(candidate.p, Iri)
                        and current.p.value != candidate.p.value
                    ):
                        continue
                    mark = len(trail)
                    if unify_triple_trail(current, candidate):
                        used[candidate_index] = True
                        if step(index + 1):
                            return True
                        used[candidate_index] = False
                    undo_to(mark)
                return False

            return step(0)

        def unify_term_trail(a: Term, b: Term) -> bool:
            a = self.apply_subst(a, subst_mut)
            b = self.apply_subst(b, subst_mut)
            if isinstance(a, Var):
                return bind_var(a, b)
            if isinstance(b, Var):
                return bind_var(b, a)
            if isinstance(a, Iri) and a.value == RDF_NIL and isinstance(b, ListTerm) and not b.elems:
                return True
            if isinstance(b, Iri) and b.value == RDF_NIL and isinstance(a, ListTerm) and not a.elems:
                return True
            if a is b or a == b:
                return True
            if isinstance(a, Literal) and isinstance(b, Literal):
                return self.literal_equivalent(a, b)
            if isinstance(a, ListTerm) and isinstance(b, ListTerm):
                if len(a.elems) != len(b.elems):
                    return False
                return all(unify_term_trail(x, y) for x, y in zip(a.elems, b.elems))
            if isinstance(a, ListTerm):
                recovered = self.rdf_collection_to_list(b)
                if recovered is not None:
                    return unify_term_trail(a, ListTerm(recovered))
            if isinstance(b, ListTerm):
                recovered = self.rdf_collection_to_list(a)
                if recovered is not None:
                    return unify_term_trail(ListTerm(recovered), b)
            if isinstance(a, OpenListTerm) and isinstance(b, ListTerm):
                if len(b.elems) < len(a.prefix):
                    return False
                for x, y in zip(a.prefix, b.elems):
                    if not unify_term_trail(x, y):
                        return False
                return bind_var(Var(a.tail_var), ListTerm(b.elems[len(a.prefix):]))
            if isinstance(b, OpenListTerm) and isinstance(a, ListTerm):
                return unify_term_trail(b, a)
            if isinstance(a, OpenListTerm) and isinstance(b, OpenListTerm):
                common = min(len(a.prefix), len(b.prefix))
                for x, y in zip(a.prefix[:common], b.prefix[:common]):
                    if not unify_term_trail(x, y):
                        return False
                if len(a.prefix) == len(b.prefix):
                    return bind_var(Var(a.tail_var), Var(b.tail_var))
                if len(a.prefix) < len(b.prefix):
                    return bind_var(Var(a.tail_var), OpenListTerm(b.prefix[common:], b.tail_var))
                return bind_var(Var(b.tail_var), OpenListTerm(a.prefix[common:], a.tail_var))
            if isinstance(a, GraphTerm) and isinstance(b, GraphTerm):
                return unify_graphs_trail(a.triples, b.triples)
            return False

        def unify_triple_trail(a: Triple, b: Triple) -> bool:
            return (
                unify_term_trail(a.p, b.p)
                and unify_term_trail(a.s, b.s)
                and unify_term_trail(a.o, b.o)
            )

        def apply_delta(delta: Subst) -> bool:
            for name, value in list(delta.items()):
                if not unify_term_trail(Var(name), value):
                    return False
            return True

        def answer_from_current() -> Subst:
            answer: Subst = {}
            for name in answer_vars:
                value = self.apply_subst(Var(name), subst_mut)
                if not (isinstance(value, Var) and value.name == name):
                    answer[name] = value
            return answer

        visited_reset = object()
        Frame = dict[str, Any]
        stack: list[Frame] = [
            {"kind": "node", "goals": list(goals), "depth": depth, "reorder": allow_reorder}
        ]
        while stack:
            frame = stack.pop()
            kind = frame["kind"]
            if kind == "undo":
                undo_to(frame["subst_mark"])
                undo_visited_to(frame["visited_mark"])
                continue
            if kind == "delta_iter":
                deltas = frame["deltas"]
                while frame["index"] < len(deltas):
                    delta = deltas[frame["index"]]
                    frame["index"] += 1
                    mark = len(trail)
                    if not apply_delta(delta):
                        undo_to(mark)
                        continue
                    if not frame["rest"]:
                        answer = answer_from_current()
                        if goal_memo_key is not None:
                            completed_answers.append(dict(answer))
                        yield answer
                        undo_to(mark)
                        continue
                    stack.append(frame)
                    stack.append({"kind": "undo", "subst_mark": mark, "visited_mark": len(visited_trail)})
                    stack.append({
                        "kind": "node",
                        "goals": frame["rest"],
                        "depth": frame["depth"] + 1,
                        "reorder": frame["reorder"],
                    })
                    break
                continue
            if kind in {"fact_iter", "rule_fact_iter", "memo_answer_iter"}:
                items = frame["items"]
                while frame["index"] < len(items):
                    item = items[frame["index"]]
                    frame["index"] += 1
                    mark = len(trail)
                    if not unify_triple_trail(frame["goal"], item):
                        undo_to(mark)
                        continue
                    if not frame["rest"]:
                        answer = answer_from_current()
                        if goal_memo_key is not None:
                            completed_answers.append(dict(answer))
                        yield answer
                        undo_to(mark)
                        continue
                    stack.append(frame)
                    stack.append({"kind": "undo", "subst_mark": mark, "visited_mark": len(visited_trail)})
                    stack.append({
                        "kind": "node",
                        "goals": frame["rest"],
                        "depth": frame["depth"] + 1,
                        "reorder": frame["reorder"],
                    })
                    break
                continue
            if kind == "rule_iter":
                rules = frame["rules"]
                while frame["index"] < len(rules):
                    rule = rules[frame["index"]]
                    frame["index"] += 1
                    if len(rule.premise) != 1:
                        continue
                    std = self.standardize_apart(rule)
                    mark = len(trail)
                    if not unify_triple_trail(frame["goal"], std.premise[0]):
                        undo_to(mark)
                        continue
                    body = list(std.conclusion)
                    if frame["goal_was_visited"] and any(
                        goal_key(self.apply_subst_triple(premise, subst_mut)) in visited_counts
                        for premise in body
                    ):
                        undo_to(mark)
                        continue
                    visited_mark = len(visited_trail)
                    push_visited(frame["goal_key"])
                    stack.append(frame)
                    stack.append({"kind": "undo", "subst_mark": mark, "visited_mark": visited_mark})
                    next_goals = body + frame["rest"]
                    if frame["rest"]:
                        next_goals = body + [(visited_reset, visited_mark)] + frame["rest"]
                    stack.append({
                        "kind": "node",
                        "goals": next_goals,
                        "depth": frame["depth"] + 1,
                        "reorder": False,
                    })
                    break
                continue

            goals_now = frame["goals"]
            depth_now = frame["depth"]
            reorder_now = frame["reorder"]
            if depth_now > self.max_depth:
                continue
            if not goals_now:
                answer = answer_from_current()
                if goal_memo_key is not None:
                    completed_answers.append(dict(answer))
                yield answer
                continue
            if isinstance(goals_now[0], tuple) and goals_now[0][0] is visited_reset:
                undo_visited_to(goals_now[0][1])
                stack.append({
                    "kind": "node",
                    "goals": goals_now[1:],
                    "depth": depth_now,
                    "reorder": reorder_now,
                })
                continue

            selected = self._select_goal_index(goals_now, subst_mut) if reorder_now else 0
            first = self.apply_subst_triple(goals_now[selected], subst_mut)
            rest = goals_now[:selected] + goals_now[selected + 1:]

            # A registered builtin owns its predicate and does not fall through
            # to ordinary facts or backward rules.
            if isinstance(first.p, Iri):
                handler = get_builtin(first.p.value)
                if handler is not None:
                    # The selected goal is already substitution-applied. Match
                    # Eyeling's hot path: builtins return only the new bindings
                    # introduced while evaluating this goal, not a full copy of
                    # the current proof state.
                    builtin_subst = (
                        subst_mut
                        if len(subst_mut) <= 64
                        or first.p.value in {
                            LOG_NS + "collectAllIn",
                            LOG_NS + "forAllIn",
                            LOG_NS + "includes",
                            LOG_NS + "notIncludes",
                        }
                        else {}
                    )
                    ctx = BuiltinContext(first, builtin_subst, self)
                    deltas = list(handler(ctx))
                    if deltas:
                        stack.append({
                            "kind": "delta_iter",
                            "deltas": deltas,
                            "index": 0,
                            "rest": rest,
                            "depth": depth_now,
                            "reorder": reorder_now,
                        })
                    continue

                if first.p.value in {RDF_FIRST, RDF_REST}:
                    seen_lists: set[ListTerm] = set()
                    for fact in self.facts:
                        for term in (fact.s, fact.p, fact.o):
                            if isinstance(term, ListTerm) and term.elems:
                                seen_lists.add(term)
                    synthetic: list[Triple] = []
                    for collection in seen_lists:
                        obj = collection.elems[0] if first.p.value == RDF_FIRST else ListTerm(collection.elems[1:])
                        synthetic.append(Triple(collection, first.p, obj))
                    if synthetic:
                        stack.append({
                            "kind": "fact_iter",
                            "items": synthetic,
                            "index": 0,
                            "goal": first,
                            "rest": rest,
                            "depth": depth_now,
                            "reorder": reorder_now,
                        })

            # Predicate-scoped memoization remains opt-in via log:memoize.
            if isinstance(first.p, Iri) and first.p.value in self._memoized_predicates:
                memo_key = self._predicate_memo_key(first)
                if memo_key is not None:
                    table, memo_entry = self._predicate_memo_lookup(memo_key)
                    if not memo_entry["complete"] and not memo_entry["computing"]:
                        bottom_up_entry = self._try_bottom_up_numeric_memo(first)
                        if bottom_up_entry is not None:
                            memo_entry = bottom_up_entry
                    if memo_entry["complete"]:
                        stack.append({
                            "kind": "memo_answer_iter",
                            "items": memo_entry["answers"],
                            "index": 0,
                            "goal": first,
                            "rest": rest,
                            "depth": depth_now,
                            "reorder": reorder_now,
                        })
                        continue
                    if not memo_entry["computing"]:
                        memo_entry["computing"] = True
                        memo_successors: list[Subst] = []
                        try:
                            for nxt in self.solve(
                                [first],
                                {},
                                depth_now + 1,
                                reorder_now,
                                frozenset(visited_counts),
                            ):
                                self._store_predicate_memo_answer(memo_entry, first, nxt)
                                memo_successors.append(nxt)
                        finally:
                            memo_entry["computing"] = False
                            if memo_entry["unsafe"]:
                                table.pop(memo_key, None)
                            else:
                                memo_entry["complete"] = True
                        if memo_successors:
                            stack.append({
                                "kind": "delta_iter",
                                "deltas": memo_successors,
                                "index": 0,
                                "rest": rest,
                                "depth": depth_now,
                                "reorder": reorder_now,
                            })
                        continue

            # On re-entering an ancestor goal, reject only rules whose body
            # immediately re-enters that ancestor chain. This is Eyeling's
            # inexpensive guard for direct and mutual recursion.
            first_key = goal_key(first)
            goal_was_visited = first_key in visited_counts
            # Eyeling only indexes/applies backward rules for a ground IRI
            # predicate. Variable-predicate goals range over facts.
            candidate_rules: list[Rule]
            if isinstance(first.p, Iri):
                candidate_rules = [
                    *self._backward_rules_by_pred.get(first.p.value, ()),
                    *self._wild_backward_rules,
                ]
            else:
                candidate_rules = []

            # Push in reverse processing order so facts are explored first, as
            # in the previous Python solver.
            if candidate_rules:
                stack.append({
                    "kind": "rule_iter",
                    "rules": candidate_rules,
                    "index": 0,
                    "goal": first,
                    "goal_key": first_key,
                    "goal_was_visited": goal_was_visited,
                    "rest": rest,
                    "depth": depth_now,
                })
            rule_facts = list(self._candidate_rule_facts(first))
            if rule_facts:
                stack.append({
                    "kind": "rule_fact_iter",
                    "items": rule_facts,
                    "index": 0,
                    "goal": first,
                    "rest": rest,
                    "depth": depth_now,
                    "reorder": reorder_now,
                })
            facts = list(self._candidate_facts(first))
            if facts:
                stack.append({
                    "kind": "fact_iter",
                    "items": facts,
                    "index": 0,
                    "goal": first,
                    "rest": rest,
                    "depth": depth_now,
                    "reorder": reorder_now,
                })

        if goal_memo is not None and goal_memo_key is not None:
            goal_memo[goal_memo_key] = completed_answers

    def _select_goal_index(self, goals: list[Any], subst: Subst) -> int:
        for index, goal in enumerate(goals):
            if not isinstance(goal, Triple):
                return index
            predicate = self.deref(goal.p, subst)
            handler = get_builtin(predicate.value) if isinstance(predicate, Iri) else None
            rank = self._goal_rank(goal, subst)
            if handler is not None:
                if rank[0] < 0:
                    return index
            elif rank[0] == 0:
                return index
        return 0

    def _goal_rank(self, goal: Triple, subst: Subst) -> tuple[int, int]:
        pred = self.deref(goal.p, subst)

        def unbound(term: Term) -> int:
            original = term
            term = self.deref(term, subst)
            if isinstance(original, Var) and isinstance(term, GraphTerm):
                # Variables inside a formula bound to an outer variable have
                # formula-local scope. They do not make the builtin's input
                # unbound and must not delay log:conclusion/includes.
                return 0
            if isinstance(term, Var):
                return 1
            if isinstance(term, ListTerm):
                return sum(unbound(item) for item in term.elems)
            if isinstance(term, GraphTerm):
                return sum(unbound(tr.s) + unbound(tr.p) + unbound(tr.o) for tr in term.triples)
            return 0

        variables = unbound(goal.s) + unbound(goal.o)
        if not isinstance(pred, Iri):
            return (0, variables)
        if get_builtin(pred.value) is None:
            self._ensure_fact_indexes_current()
            has_extensional_candidate = bool(self._facts_by_pred.get(pred))
            has_backward_rule = pred.value in self._backward_predicates
            if has_backward_rule and not has_extensional_candidate and unbound(goal.s):
                # Backward relations conventionally consume their subject and
                # construct/test their object. Do not invoke a backward-only
                # relation before preceding facts have supplied that input.
                return (1, variables)
            return (0, variables)
        if pred.value == "http://www.w3.org/2000/10/swap/list#iterate" and unbound(goal.s) == 0:
            return (-1, variables)
        if (
            pred.value in {
                "http://www.w3.org/2000/10/swap/list#append",
                "http://www.w3.org/2000/10/swap/list#firstRest",
            }
            and unbound(goal.o) == 0
        ):
            return (-1, variables)
        comparisons = {
            "equalTo", "notEqualTo", "greaterThan", "lessThan",
            "notGreaterThan", "notLessThan", "contains", "startsWith",
            "endsWith", "matches", "notMatches", "notMember",
        }
        local = pred.value.rsplit("#", 1)[-1]
        if local in {"collectAllIn", "forAllIn"}:
            # Aggregates often bind a list used by a following builtin. Rank
            # them after extensional facts and constructive backward goals,
            # but before consumers whose subject is still unbound.
            return (1, variables)
        if local in {"includes", "notIncludes"} and isinstance(self.deref(goal.o, subst), Var):
            # A variable object denotes a formula pattern supplied by another
            # goal; includes cannot enumerate an unconstrained formula.
            return (3, variables)
        if local in {"includes", "notIncludes"} and variables:
            return (1, variables)
        if pred.value == LOG_NS + "equalTo":
            left = self.deref(goal.s, subst)
            right = self.deref(goal.o, subst)
            if not (isinstance(left, Var) and isinstance(right, Var)):
                # log:equalTo is structural unification. A partially bound
                # list or formula can construct the other side even though it
                # still contains variables of its own.
                return (-1, variables)
        if local in comparisons and variables:
            return (2, variables)
        # Most N3 builtins consume their subject and bind/test their object.
        # Once that input is ground, evaluate them before predicates that
        # depend on their output.
        if unbound(goal.s) == 0:
            return (-1, variables)
        return (2, variables)

    def deref(self, t: Term, subst: Subst) -> Term:
        if not isinstance(t, Var):
            return t
        seen: set[str] = set()
        while isinstance(t, Var) and t.name in subst and t.name not in seen:
            seen.add(t.name)
            t = subst[t.name]
        return t

    def apply_subst(self, t: Term, subst: Subst) -> Term:
        if not self._term_needs_substitution(t):
            return t
        t = self.deref(t, subst)
        if isinstance(t, ListTerm):
            return ListTerm(self.apply_subst(e, subst) for e in t.elems)
        if isinstance(t, OpenListTerm):
            prefix = tuple(self.apply_subst(e, subst) for e in t.prefix)
            tail = self.apply_subst(Var(t.tail_var), subst)
            if isinstance(tail, ListTerm):
                return ListTerm((*prefix, *tail.elems))
            if isinstance(tail, OpenListTerm):
                return OpenListTerm((*prefix, *tail.prefix), tail.tail_var)
            if isinstance(tail, Var):
                return OpenListTerm(prefix, tail.name)
            return OpenListTerm(prefix, t.tail_var)
        if isinstance(t, GraphTerm):
            return GraphTerm(self.apply_subst_triple(tr, subst) for tr in t.triples)
        return t

    def apply_subst_triple(
        self,
        tr: Triple,
        subst: Subst,
        ground_blanks: bool = False,
        blank_mapping: dict[str, Blank] | None = None,
    ) -> Triple:
        if ground_blanks:
            return self._instantiate_head_triple(tr, subst, blank_mapping)
        return Triple(self.apply_subst(tr.s, subst), self.apply_subst(tr.p, subst), self.apply_subst(tr.o, subst))

    def _instantiate_head_triple(
        self,
        tr: Triple,
        subst: Subst,
        mapping: dict[str, Blank] | None = None,
    ) -> Triple:
        """Apply a substitution while skolemizing only existential blank nodes
        that are written in the rule head itself. Blank nodes reached through a
        variable binding are preserved; otherwise rules over blank-node facts
        would keep producing fresh duplicates forever.
        """
        mapping = mapping if mapping is not None else {}

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
        s1 = self.unify_term(a.p, b.p, subst)
        if s1 is None:
            return None
        s2 = self.unify_term(a.s, b.s, s1)
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
            return subst
        if isinstance(b, Iri) and b.value == RDF_NIL and isinstance(a, ListTerm) and not a.elems:
            return subst
        if isinstance(a, Literal) and isinstance(b, Literal):
            return subst if self.literal_equivalent(a, b) else None
        if isinstance(a, ListTerm) and isinstance(b, ListTerm):
            if len(a.elems) != len(b.elems):
                return None
            cur = subst
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
            cur = subst
            for x, y in zip(a.prefix, b.elems):
                cur = self.unify_term(x, y, cur)
                if cur is None:
                    return None
            return self.unify_term(Var(a.tail_var), ListTerm(b.elems[len(a.prefix):]), cur)
        if isinstance(b, OpenListTerm) and isinstance(a, ListTerm):
            return self.unify_term(b, a, subst)
        if isinstance(a, OpenListTerm) and isinstance(b, OpenListTerm):
            common = min(len(a.prefix), len(b.prefix))
            cur = subst
            for x, y in zip(a.prefix[:common], b.prefix[:common]):
                cur = self.unify_term(x, y, cur)
                if cur is None:
                    return None
            if len(a.prefix) == len(b.prefix):
                return self.unify_term(Var(a.tail_var), Var(b.tail_var), cur)
            if len(a.prefix) < len(b.prefix):
                remainder = OpenListTerm(b.prefix[common:], b.tail_var)
                return self.unify_term(Var(a.tail_var), remainder, cur)
            remainder = OpenListTerm(a.prefix[common:], a.tail_var)
            return self.unify_term(remainder, Var(b.tail_var), cur)
        if isinstance(a, GraphTerm) and isinstance(b, GraphTerm):
            # Treat graph/formula terms as unordered conjunctions.
            if len(a.triples) != len(b.triples):
                return None
            return self._unify_graphs(list(a.triples), list(b.triples), subst)
        return subst if a == b else None

    def _unify_graphs(self, left: list[Triple], right: list[Triple], subst: Subst) -> Subst | None:
        if not left:
            return subst if not right else None
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
            return subst
        if self._occurs(var.name, value, subst):
            return None
        out = dict(subst)
        out[var.name] = value
        return out

    def _occurs(self, name: str, value: Term, subst: Subst) -> bool:
        value = self.deref(value, subst)
        if not self._term_needs_substitution(value):
            return False
        if isinstance(value, Var):
            return value.name == name
        if isinstance(value, ListTerm):
            return any(self._occurs(name, e, subst) for e in value.elems)
        if isinstance(value, OpenListTerm):
            return (
                value.tail_var == name
                or any(self._occurs(name, e, subst) for e in value.prefix)
                or self._occurs(name, Var(value.tail_var), subst)
            )
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
            if a_dt in {XSD_NS + "date", XSD_NS + "dateTime"}:
                import datetime

                def temporal_value(literal: Literal) -> datetime.date | datetime.datetime | None:
                    try:
                        lexical = literal.lexical
                        if a_dt == XSD_NS + "dateTime":
                            return datetime.datetime.fromisoformat(lexical.replace("Z", "+00:00"))
                        return datetime.date.fromisoformat(lexical)
                    except ValueError:
                        return None

                a_temporal = temporal_value(a)
                b_temporal = temporal_value(b)
                if a_temporal is not None and b_temporal is not None:
                    return a_temporal == b_temporal
        return a.lexical == b.lexical and a_dt == b_dt and (a.lang or "").lower() == (b.lang or "").lower()

    def terms_equivalent(self, a: Term, b: Term, subst: Subst) -> bool:
        return self.unify_term(a, b, subst) is not None

    def _fresh_variable_renamer(self, kind: str) -> Callable[[Term], Term]:
        self._std_counter += 1
        prefix = f"_{kind}{self._std_counter}_"
        renamed: dict[str, Var] = {}

        def variable(name: str) -> Var:
            return renamed.setdefault(name, Var(prefix + name))

        def cv(t: Term) -> Term:
            if isinstance(t, Var):
                return variable(t.name)
            if isinstance(t, ListTerm):
                return ListTerm(cv(e) for e in t.elems)
            if isinstance(t, OpenListTerm):
                return OpenListTerm((cv(e) for e in t.prefix), variable(t.tail_var).name)
            if isinstance(t, GraphTerm):
                return GraphTerm(Triple(cv(x.s), cv(x.p), cv(x.o)) for x in t.triples)
            return t

        return cv

    def standardize_term_apart(self, term: Term, *, scope_key: str | None = None) -> Term:
        """Give variables in an external term an engine-local lexical scope."""
        if scope_key is not None and scope_key in self._standardized_term_cache:
            return self._standardized_term_cache[scope_key]
        standardized = self._fresh_variable_renamer("e")(term)
        if scope_key is not None:
            self._standardized_term_cache[scope_key] = standardized
        return standardized

    def standardize_apart(self, rule: Rule) -> Rule:
        cv = self._fresh_variable_renamer("r")
        return Rule(
            (Triple(cv(t.s), cv(t.p), cv(t.o)) for t in rule.premise),
            (Triple(cv(t.s), cv(t.p), cv(t.o)) for t in rule.conclusion),
            rule.is_forward,
            rule.is_fuse,
            cv(rule.dynamic_conclusion) if rule.dynamic_conclusion is not None else None,
        )

    def rdf_collection_to_list(self, node: Term) -> list[Term] | None:
        # Only RDF resources can head an explicit rdf:first/rdf:rest chain.
        # In particular, an unbound variable here means a list builtin should
        # use its constructive mode, not scan the complete fact set.
        if not isinstance(node, (Iri, Blank, ListTerm)):
            return None
        self._ensure_fact_indexes_current()
        seen: set[Term] = set()
        out: list[Term] = []
        cur = node
        first_pred = Iri(RDF_FIRST)
        rest_pred = Iri(RDF_REST)
        while True:
            if isinstance(cur, Iri) and cur.value == RDF_NIL:
                return out
            if isinstance(cur, ListTerm):
                return out + list(cur.elems)
            if cur in seen:
                return None
            seen.add(cur)
            sk = self._lookup_key(cur)
            if sk is None:
                firsts = [t.o for t in self.facts if t.s == cur and isinstance(t.p, Iri) and t.p.value == RDF_FIRST]
                rests = [t.o for t in self.facts if t.s == cur and isinstance(t.p, Iri) and t.p.value == RDF_REST]
            else:
                firsts = [t.o for t in self._facts_by_ps.get((first_pred, sk), ()) if t.s == cur]
                rests = [t.o for t in self._facts_by_ps.get((rest_pred, sk), ()) if t.s == cur]
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
    try:
        tokens = lex(str(text or ""))
    except N3SyntaxError:
        return True
    return any(
        token.typ in {"=>", "<="}
        or (token.typ == "IDENT" and token.value == "log:query")
        or (token.typ == "IRI" and token.value == LOG_QUERY)
        for token in tokens
    )


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
    if _is_rdflib_graph(input_data):
        return parse_rdf_graph(input_data)
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
    raise TypeError("input must be an N3 string, RDFLib graph, source list, RDF-like mapping, or AST bundle")


def _is_rdflib_graph(value: Any) -> bool:
    return hasattr(value, "triples") and hasattr(value, "namespace_manager") and (
        hasattr(value, "quads") or hasattr(value, "add")
    )


def _build_options(
    *,
    rdf: bool = False,
    rdf12: bool = False,
    input_format: str | None = None,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
    store: Any = None,
    store_path: str | None = None,
    store_clear: bool = False,
    ast: bool = False,
    proof: bool = False,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "rdf": rdf,
        "rdf12": rdf12,
        "include_input_facts_in_closure": include_input_facts_in_closure,
        "ast": ast,
        "proof": proof,
    }
    if input_format is not None:
        options["input_format"] = input_format
    if max_depth is not None:
        options["max_depth"] = max_depth
    if max_iterations is not None:
        options["max_iterations"] = max_iterations
    if store is not None:
        options["store"] = store
    if store_path is not None:
        options["storePath"] = store_path
        options["storeClear"] = store_clear
    return options


def reason_stream(
    input_data: Any = "",
    *,
    rdf: bool = False,
    rdf12: bool = False,
    input_format: str | None = None,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
    store: Any = None,
) -> ReasonStreamResult:
    """Parse ``input_data`` and run the reasoner to a fixed point.

    ``input_data`` is an N3/Turtle/TriG/etc. string, a source-list mapping
    (``{"sources": [...]}}``), or an already-parsed :class:`Document`/AST
    bundle. All other reasoning options are explicit keyword arguments.
    """
    options = _build_options(
        rdf=rdf,
        rdf12=rdf12,
        input_format=input_format,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
        store=store,
    )
    doc = _input_to_document(input_data, options)
    engine = Engine(doc, options)
    if store is not None:
        # For sync API, store support is in-memory during the run; run_async persists.
        engine.store = create_fact_store(store)
    return engine.run()


def reason(
    input_data: Any = "",
    *,
    rdf: bool = False,
    rdf12: bool = False,
    input_format: str | None = None,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
    store: Any = None,
    ast: bool = False,
    proof: bool = False,
) -> str:
    """Reason over ``input_data`` and return the closure rendered as N3.

    Pass ``ast=True`` to get the parsed AST as a JSON string instead.
    """
    options = _build_options(
        rdf=rdf,
        rdf12=rdf12,
        input_format=input_format,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
        store=store,
        ast=ast,
        proof=proof,
    )
    if ast:
        doc = _input_to_document(input_data, options)
        value = [
            {"_type": "PrefixEnv", "map": doc.prefixes.map, "baseIri": doc.prefixes.base_iri},
            [triple_to_primitive(t) for t in doc.triples],
            [rule_to_primitive(r) for r in doc.forward_rules],
            [rule_to_primitive(r) for r in doc.backward_rules],
        ]
        return json.dumps(value, indent=2, sort_keys=True)
    return reason_stream(
        input_data,
        rdf=rdf,
        rdf12=rdf12,
        input_format=input_format,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
        store=store,
    ).closure_n3


def reason_graph(
    input_data: Any = "",
    *,
    rdf: bool = False,
    rdf12: bool = False,
    input_format: str | None = None,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
    store: Any = None,
):
    """Reason over input and return the selected closure as an RDFLib Graph."""
    return reason_stream(
        input_data,
        rdf=rdf,
        rdf12=rdf12,
        input_format=input_format,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
        store=store,
    ).as_rdflib_graph(include_input_facts=include_input_facts_in_closure)


async def run_async(
    input_data: Any = "",
    *,
    rdf: bool = False,
    rdf12: bool = False,
    input_format: str | None = None,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
    store: Any = None,
    store_path: str | None = None,
    store_clear: bool = False,
) -> ReasonStreamResult:
    """Like :func:`reason_stream`, but awaits a persistent fact store.

    Provide either ``store`` (a fact-store spec mapping) or ``store_path``
    (with optional ``store_clear``) to persist facts across runs.
    """
    options = _build_options(
        rdf=rdf,
        rdf12=rdf12,
        input_format=input_format,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
        store=store,
        store_path=store_path,
        store_clear=store_clear,
    )
    doc = _input_to_document(input_data, options)
    engine = Engine(doc, options)
    store_opt = store or (store_path and {"name": "default", "path": store_path, "clear": store_clear})
    if store_opt:
        fact_store = create_fact_store(store_opt)
        # Load previous store facts.
        if hasattr(fact_store, "triples"):
            for tr in fact_store.triples:
                engine.add_fact(tr, inferred=False)
        result = engine.run()
        for tr in doc.triples:
            await fact_store.add(tr, "explicit")
        for tr in result.derived:
            await fact_store.add(tr, "inferred")
        result.store = fact_store
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


def reason_message_stream(
    input_data: Any = "",
    *,
    include_input_facts_in_closure: bool = False,
    max_depth: int | None = None,
    max_iterations: int | None = None,
) -> Iterator[ReasonStreamResult]:
    """Run rules against an RDF Message Log one replay message at a time.

    Non-message sources are parsed once as rules/facts. Each yielded result is
    equivalent to running the reasoner over those base sources plus one replay
    envelope document.
    """
    options = _build_options(
        rdf=True,
        include_input_facts_in_closure=include_input_facts_in_closure,
        max_depth=max_depth,
        max_iterations=max_iterations,
    )
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
