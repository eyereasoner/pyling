import pytest

from pyling import (
    GraphTerm,
    Literal,
    RdfSyntaxError,
    assert_rdf12_surface_syntax,
    parse_rdf_message_log,
    parse_rdf_text,
    reason,
    reason_message_stream,
)


def test_rdf_turtle_mode_does_not_emit_rdflib_default_prefix_noise():
    out = reason(
        {"rdf": True, "include_input_facts_in_closure": True},
        "PREFIX : <http://example.org/>\n:a :p :b .",
    )
    assert "@prefix : <http://example.org/> ." in out
    assert ":a :p :b ." in out
    assert "@prefix foaf:" not in out


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
    rendered = reason({"include_input_facts_in_closure": True}, doc)
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
    out = reason({"rdf": True}, {"sources": [rules, log]})
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
    results = list(reason_message_stream(log, {"rdf": True, "include_input_facts_in_closure": True}))
    assert len(results) == 3
    assert "eymsg:payloadKind eymsg:empty" in results[1].closure_n3
    assert "eymsg:offset 3" in results[2].closure_n3


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
