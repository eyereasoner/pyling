import pytest

from pyling import (
    RdfSyntaxError,
    assert_rdf12_surface_syntax,
    parse_rdf_message_log,
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
