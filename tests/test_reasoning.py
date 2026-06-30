import asyncio
import subprocess
import sys
import pytest

from pyling import (
    INFERENCE_FUSE_EXIT_CODE,
    InferenceFuseError,
    Iri,
    Literal,
    Rule,
    Triple,
    Var,
    create_fact_store,
    reason,
    reason_stream,
    register_builtin,
    unregister_builtin,
    run_async,
)

EX = "http://example.org/"


def test_forward_rule_basic():
    out = reason({}, """
@prefix : <http://example.org/> .
:Socrates a :Man .
{ ?x a :Man } => { ?x a :Mortal } .
""")
    assert ":Socrates a :Mortal ." in out
    assert ":Socrates a :Man ." not in out


def test_integer_before_statement_dot_and_punctuation_literal():
    out = reason({}, '''
@prefix : <http://example.org/> .
@prefix string: <http://www.w3.org/2000/10/swap/string#> .
1 :equals 1.
{ 1 :equals 1. "hello!" string:endsWith "!". } => { :test :ok true. }.
''')
    assert ":test :ok true ." in out


def test_long_string_quote_runs_uchar_iris_and_exponent_form():
    out = reason({}, r'''
@prefix : <http://example.org/> .
<http://example.org/\u0041> :value 4.e2.
:quoted :value """"""".
{} => { :test :ok true. }.
''')
    assert ":test :ok true ." in out


def test_standalone_blank_node_property_list():
    out = reason({}, '''
@prefix : <http://example.org/> .
[ [] [] ].
{} => { :test :ok true. }.
''')
    assert ":test :ok true ." in out


def test_rule_antecedent_blanks_are_bindable_and_rdf_lists_are_preserved():
    out = reason({}, '''
@prefix : <http://example.org/> .
@prefix math: <http://www.w3.org/2000/10/swap/math#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
:test :value [ rdf:first 1; rdf:rest [ rdf:first 2; rdf:rest rdf:nil ] ].
{ (1 2) math:sum ?sum. (1 2) math:sum _:other. :test :value ?list. ?list math:sum 3. } => { :test :sum ?sum. }.
''')
    assert ":test :sum 3 ." in out


def test_fact_unification_uses_literal_term_equality():
    out = reason({}, '''
@prefix : <http://example.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
:x :value 42.
{ :x :value "42"^^xsd:double. } => { :bad :value true. }.
''')
    assert ":bad :value true ." not in out


def test_formula_local_prefix_and_iri_property_list_id():
    out = reason({}, '''
@prefix : <http://example.org/> .
:a :b :c. :c :d :e. :e :f :g.
{ @prefix local: <http://example.org/>. local:a local:b [ id local:c local:d [ id local:e local:f local:g ] ]. }
=> { :test :ok true. }.
''')
    assert ":test :ok true ." in out


def test_existential_rule_head_fires_once_per_binding():
    result = reason_stream('''
@prefix : <http://example.org/> .
:x :value 1.
{ :x :value ?v. } => { { _:b :value ?v. } => { :derived :value ?v. }. }.
''')
    assert len(result.derived) < 10


def test_dynamic_inference_fuse_is_enforced():
    with pytest.raises(InferenceFuseError):
        reason({}, '''
@prefix : <http://example.org/> .
:x :value 1.
{ :x :value ?v. } => { { :x :value ?v. } => false. }.
''')


def test_forbidden_unicode_escape_is_rejected():
    with pytest.raises(SyntaxError):
        reason({}, r'@prefix : <http://example.org/>. :x :value "\uD800".')


def test_cli_formats_syntax_error_and_accepts_legacy_n_flag(tmp_path):
    bad = tmp_path / "bad.n3"
    bad.write_text("@prefix : <http://example.org/> .\n:a :p .\n", encoding="utf8")
    proc = subprocess.run(
        [sys.executable, "-m", "pyling.cli", "-n", str(bad)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 1
    assert f"Syntax error in {bad}:2:7:" in proc.stderr
    assert ":a :p .\n      ^" in proc.stderr


def test_two_step_and_join():
    out = reason({}, """
@prefix : <http://example.org/> .
:a :p :b . :b :p :c .
{ ?x :p ?y } => { ?x :q ?y } .
{ ?x :p ?y . ?y :p ?z } => { ?x :p2 ?z } .
""")
    assert ":a :q :b ." in out
    assert ":a :p2 :c ." in out


def test_recursive_ancestor_closure():
    out = reason({}, """
@prefix : <http://example.org/> .
:a :parent :b . :b :parent :c . :c :parent :d .
{ ?x :parent ?y } => { ?x :ancestor ?y } .
{ ?x :parent ?y . ?y :ancestor ?z } => { ?x :ancestor ?z } .
""")
    assert ":a :ancestor :d ." in out


def test_backward_rule_satisfies_forward_body():
    out = reason({}, """
@prefix : <http://example.org/> .
@prefix math: <http://www.w3.org/2000/10/swap/math#> .
:alice :age 42 .
{ ?x :adult true } <= { ?x :age ?age . ?age math:greaterThan 17 } .
{ ?x :adult true } => { ?x :canVote true } .
""")
    assert ":alice :canVote true ." in out


def test_dynamic_log_implies():
    out = reason({}, """
@prefix : <http://example.org/> .
@prefix log: <http://www.w3.org/2000/10/swap/log#> .
:a :p :b .
{ :seed :present true } => { { ?s :p ?o } log:implies { ?s :q ?o } } .
:seed :present true .
""")
    assert ":a :q :b ." in out


def test_math_list_string_builtins():
    out = reason({}, """
@prefix : <http://example.org/> .
@prefix math: <http://www.w3.org/2000/10/swap/math#> .
@prefix list: <http://www.w3.org/2000/10/swap/list#> .
@prefix string: <http://www.w3.org/2000/10/swap/string#> .
{ (2 3 5) math:sum ?n . ?n math:greaterThan 9 . } => { :sum :value ?n } .
{ ("a" "b") string:concatenation ?s . } => { :str :value ?s } .
{ (1 2 3) list:first ?x . (1 2 3) list:rest ?r . ?r list:length ?len . } => { :list :first ?x . :list :restLength ?len } .
""")
    assert ":sum :value 10 ." in out
    assert ':str :value "ab" .' in out
    assert ":list :first 1 ." in out
    assert ":list :restLength 2 ." in out


def test_log_query_and_output_string():
    out = reason({}, """
@prefix : <http://example.org/> .
@prefix log: <http://www.w3.org/2000/10/swap/log#> .
:run :value "hello" .
{ :run :value ?text } log:query { :out log:outputString ?text } .
""")
    assert out == "hello"


def test_log_includes_formula_matching():
    out = reason({}, """
@prefix : <http://example.org/> .
@prefix log: <http://www.w3.org/2000/10/swap/log#> .
:scope :formula { :a :p :b . :b :p :c . } .
{ :scope :formula ?f . ?f log:includes { ?x :p :b } } => { :found :subject ?x } .
""")
    assert ":found :subject :a ." in out


def test_inference_fuse_code():
    with pytest.raises(InferenceFuseError) as exc:
        reason({}, """
@prefix : <http://example.org/> .
:bad :flag true .
{ :bad :flag true } => false .
""")
    assert exc.value.code == INFERENCE_FUSE_EXIT_CODE


def test_multisource_blank_scope_and_api_aliases():
    result = reason_stream({"sources": [
        {"n3": "@prefix : <http://example.org/> .\n_:x :p :a ."},
        {"n3": "@prefix : <http://example.org/> .\n_:x :p :b .\n{ ?s :p ?o } => { ?s :q ?o } ."},
    ]})
    assert result.closureN3.count(":q") == 2
    assert result.queryMode is False


def test_ast_and_rule_object_input():
    data = {
        "triples": [Triple(Iri(EX + "a"), Iri(EX + "p"), Iri(EX + "b"))],
        "forwardRules": [Rule([Triple(Var("s"), Iri(EX + "p"), Var("o"))], [Triple(Var("s"), Iri(EX + "q"), Var("o"))])],
    }
    result = reason_stream(data)
    assert any(t.p == Iri(EX + "q") for t in result.derived)
    ast = reason({"ast": True}, "@prefix : <http://example.org/> . :a :p :b .")
    assert '"_type": "Triple"' in ast


def test_custom_builtin():
    iri = EX + "custom#double"
    def handler(ctx):
        from pyling import Literal, XSD_NS
        s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)
        if not isinstance(s, Literal):
            return []
        return [] if (nxt := ctx.unify_term(ctx.goal.o, Literal(str(int(s.lexical) * 2), XSD_NS + "integer", bare=True), ctx.subst)) is None else [nxt]
    register_builtin(iri, handler)
    try:
        out = reason({}, f"""
@prefix : <http://example.org/> .
@prefix cb: <{EX}custom#> .
{{ 21 cb:double ?x }} => {{ :answer :is ?x }} .
""")
        assert ":answer :is 42 ." in out
    finally:
        unregister_builtin(iri)


def test_store_and_run_async(tmp_path):
    async def scenario():
        store = create_fact_store({"type": "memory"})
        a = Triple(Iri(EX + "a"), Iri(EX + "p"), Iri(EX + "b"))
        await store.add(a, "explicit")
        assert await store.has(a)
        rows = [x async for x in store.match(Iri(EX + "a"), None, None)]
        assert rows == [a]

        first = await run_async("@prefix : <http://example.org/> . :a :p :b .", {"store": {"name": "s", "path": str(tmp_path), "clear": True}})
        await first.store.close()
        second = await run_async("@prefix : <http://example.org/> . { ?s :p ?o } => { ?s :q ?o } .", {"store": {"name": "s", "path": str(tmp_path)}})
        assert ":a :q :b ." in second.closure_n3
        await second.store.close()
    asyncio.run(scenario())
