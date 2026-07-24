import pytest
from rdflib import BNode, Graph, Literal as RdfLiteral, Namespace, URIRef

from pyling import (
    Blank,
    GraphTerm,
    Iri,
    Literal,
    RdfSyntaxError,
    assert_rdf12_surface_syntax,
    document_from_rdflib,
    document_to_rdflib,
    parse_rdf_message_log,
    parse_rdf_graph,
    parse_rdf_text,
    reason,
    reason_graph,
    reason_message_stream,
    reason_stream,
    term_from_rdflib,
    term_to_rdflib,
    triple_from_rdflib,
    triple_to_rdflib,
)


def test_rdf_turtle_mode_does_not_emit_rdflib_default_prefix_noise():
    out = reason(
        "PREFIX : <http://example.org/>\n:a :p :b .",
        rdf=True,
        include_input_facts_in_closure=True,
    )
    assert "@prefix : <http://example.org/> ." in out
    assert ":a :p :b ." in out
    assert "@prefix foaf:" not in out


def test_rdflib_graph_input_is_accepted_directly():
    ex = Namespace("http://example.org/")
    graph = Graph()
    graph.bind("", ex)
    graph.add((ex.a, ex.p, ex.b))

    doc = parse_rdf_graph(graph)
    assert doc.prefixes.map[""] == str(ex)
    assert any(getattr(tr.s, "value", None) == str(ex.a) for tr in doc.triples)

    out = reason(graph, include_input_facts_in_closure=True)
    assert ":a :p :b ." in out
    assert "@prefix foaf:" not in out


def test_rdflib_conversion_helpers_are_public_and_round_trip_basic_terms():
    ex = Namespace("http://example.org/")
    assert term_from_rdflib(URIRef(ex.a)) == Iri(str(ex.a))
    assert term_from_rdflib(BNode("b1")) == Blank("_:b1")
    assert term_from_rdflib(RdfLiteral("chat", lang="NL")) == Literal("chat", lang="nl")
    assert term_to_rdflib(Iri(str(ex.a))) == URIRef(ex.a)

    triple = triple_from_rdflib((URIRef(ex.a), URIRef(ex.p), RdfLiteral("1")))
    assert triple.s == Iri(str(ex.a))
    assert triple.p == Iri(str(ex.p))
    assert triple.o == Literal("1")
    assert triple_to_rdflib(triple) == (
        URIRef(ex.a),
        URIRef(ex.p),
        RdfLiteral("1", datatype=URIRef("http://www.w3.org/2001/XMLSchema#string")),
    )


def test_rdflib_graph_conversion_reuses_repeated_terms_per_run():
    ex = Namespace("http://example.org/")
    graph = Graph()
    graph.bind("", ex)
    graph.add((ex.a, ex.p, ex.shared))
    graph.add((ex.b, ex.p, ex.shared))

    doc = document_from_rdflib(graph)
    assert len(doc.triples) == 2
    assert doc.triples[0].p is doc.triples[1].p
    assert doc.triples[0].o is doc.triples[1].o

    back = document_to_rdflib(doc)
    assert (ex.a, ex.p, ex.shared) in back
    assert (ex.b, ex.p, ex.shared) in back


def test_rdflib_conversion_cache_keeps_literal_forms_distinct():
    ex = Namespace("http://example.org/")
    graph = Graph()
    graph.add((ex.plain, ex.p, RdfLiteral("same")))
    graph.add((
        ex.typed,
        ex.p,
        RdfLiteral("same", datatype=URIRef("http://www.w3.org/2001/XMLSchema#string")),
    ))

    doc = document_from_rdflib(graph)
    values = {tr.s.value.rsplit("/", 1)[-1]: tr.o for tr in doc.triples}
    assert values["plain"] == Literal("same")
    assert values["typed"] == Literal("same", "http://www.w3.org/2001/XMLSchema#string")


def test_reason_result_can_return_rdflib_graph():
    result = reason_stream(
        """
@prefix : <http://example.org/> .
{ :a :p :b } => { :a :q :b } .
:a :p :b .
"""
    )

    ex = Namespace("http://example.org/")
    closure = result.as_rdflib_graph()
    assert (ex.a, ex.q, ex.b) in closure
    assert (ex.a, ex.p, ex.b) not in closure


def test_reason_graph_returns_rdflib_graph_with_selected_closure():
    ex = Namespace("http://example.org/")
    graph = reason_graph(
        """
@prefix : <http://example.org/> .
{ :a :p :b } => { :a :q :b } .
:a :p :b .
""",
    )

    assert (URIRef(ex.a), URIRef(ex.q), URIRef(ex.b)) in graph


def test_rdf_message_log_replay_exposes_payload_formula():
    log = '''VERSION "1.2-messages"
PREFIX : <http://example.org/>
:a :p 1 .
MESSAGE
# heartbeat
MESSAGE
:b :p 2 .
'''
    doc = parse_rdf_message_log(log)
    rendered = reason(doc, include_input_facts_in_closure=True)
    assert "eymsg:RDFMessageStream" in rendered
    assert "eymsg:messageCount 3" in rendered
    assert "log:nameOf" in rendered
    assert "eymsg:empty" in rendered


def test_rules_can_inspect_rdf_message_payload_with_log_includes():
    rules = '''@prefix : <http://example.org/> .
@prefix log: <http://www.w3.org/2000/10/swap/log#> .
@prefix eymsg: <https://eyereasoner.github.io/eyeling/vocab/message#> .
{ ?env eymsg:payloadGraph ?payload .
  ?payload log:nameOf ?g .
  ?g log:includes { ?s :p ?o . } .
} => { ?env :seen ?o . } .
'''
    log = '''VERSION "1.2-messages"
PREFIX : <http://example.org/>
:a :p 1 .
MESSAGE
:b :p 2 .
'''
    out = reason({"sources": [rules, log]}, rdf=True)
    assert ":seen \"1\"^^xsd:integer" in out
    assert ":seen \"2\"^^xsd:integer" in out


def test_stream_messages_yields_one_result_per_message():
    log = '''VERSION "1.2-messages"
PREFIX : <http://example.org/>
:a :p 1 .
MESSAGE
MESSAGE
:b :p 2 .
'''
    results = list(reason_message_stream(log, include_input_facts_in_closure=True))
    assert len(results) == 3
    assert "eymsg:payloadKind eymsg:empty" in results[1].closure_n3
    assert "eymsg:offset 3" in results[2].closure_n3


def test_stream_messages_accepts_directive_markers_without_a_trailing_heartbeat():
    log = '''@version "1.2-messages" .
@prefix : <http://example.org/> .
:a :p 1 .
@message .
:b :p 2 .
@message .
'''
    results = list(reason_message_stream(log, include_input_facts_in_closure=True))
    assert len(results) == 2
    assert "<http://example.org/a> <http://example.org/p>" in results[0].closure_n3
    assert "<http://example.org/b> <http://example.org/p>" in results[1].closure_n3


def test_rdf12_surface_checks_reject_bad_line_syntax():
    with pytest.raises(RdfSyntaxError):
        assert_rdf12_surface_syntax('<//example/s> <http://example/p> <http://example/o> .', format="nt")
    with pytest.raises(RdfSyntaxError):
        assert_rdf12_surface_syntax('<http://example/s> <http://example/p> "x"@cantbethislong .', format="nt")


def test_rdf12_versions_annotations_and_reifiers_parse():
    doc = parse_rdf_text(
        '''VERSION "1.2"
PREFIX : <http://example/>
:s :p :o ~:statement {| :source :sensor |} .
:x :p << :s :p :o ~ :statement >> .
''',
        format="turtle",
    )
    assert any(getattr(tr.s, "value", None) == "http://example/s" for tr in doc.triples)
    assert any(getattr(tr.s, "value", None) == "http://example/x" for tr in doc.triples)


def test_rdf12_nested_triple_terms_and_direction_tags_parse_in_line_syntaxes():
    doc = parse_rdf_text(
        '<http://example/s><http://example/p><<(<http://example/a><http://example/b>'
        '<<( <http://example/c> <http://example/d> "Hello"@en--ltr )>>)>>.',
        format="n-triples",
    )
    outer = doc.triples[0].o
    assert isinstance(outer, GraphTerm)
    assert isinstance(outer.triples[0].o, GraphTerm)
    nested_literal = outer.triples[0].o.triples[0].o
    assert isinstance(nested_literal, Literal)
    assert nested_literal.lang == "en"


def test_rdf12_trig_triple_constructs_parse_inside_named_graphs():
    doc = parse_rdf_text(
        '''PREFIX : <http://example/>
:G {
  :s :p :o .
  << :s :p :o >> :q <<( :a :b :c )>> .
  :x :p :o ~ {| :source :sensor |} .
}
''',
        format="trig",
    )
    assert doc.triples


@pytest.mark.parametrize(
    "text,fmt",
    [
        ('<http://example/s> <http://example/p> << <http://a> <http://b> <http://c> >> .', "n-triples"),
        ('PREFIX : <http://example/>\n<< "literal" :p :o >> :q :z .', "turtle"),
        ('PREFIX : <http://example/>\n:s :p :o {| :a :b :c |} .', "turtle"),
        ('@version "1.2"', "turtle"),
    ],
)
def test_rdf12_rejects_invalid_new_syntax(text, fmt):
    with pytest.raises(RdfSyntaxError):
        parse_rdf_text(text, format=fmt)


def test_rdf12_normalization_does_not_change_literal_content():
    doc = parse_rdf_text(
        '<http://example/s><http://example/p> ">< @en--ltr" .',
        format="n-triples",
    )
    assert doc.triples[0].o == Literal(">< @en--ltr")
