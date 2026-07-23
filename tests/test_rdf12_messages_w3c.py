"""RDF 1.2 message parsing tests extracted from the W3C RSP test catalog.

Source: https://w3c-cg.github.io/rsp/spec/messages-tests
NDJSON-LD, discovery adapters, and serializer tests are intentionally omitted.
"""

import pytest

from pyling import Blank, GraphTerm, Iri, RdfSyntaxError, parse_rdf_message_log, parse_rdf_text
from pyling.terms import EYMSG_MESSAGE_COUNT, LOG_NAME_OF


EX = "http://example.org/"


def _message_payloads(text):
    """Return payload formulas in envelope order, including empty messages."""
    replay = parse_rdf_message_log(text)
    count = next(
        int(tr.o.lexical)
        for tr in replay.triples
        if isinstance(tr.p, Iri) and tr.p.value == EYMSG_MESSAGE_COUNT
    )
    formulas = {
        tr.s.value.removesuffix("/payload"): tr.o
        for tr in replay.triples
        if isinstance(tr.s, Iri)
        and tr.s.value.endswith("/payload")
        and isinstance(tr.p, Iri)
        and tr.p.value == LOG_NAME_OF
        and isinstance(tr.o, GraphTerm)
    }
    stream = next(
        tr.s.value
        for tr in replay.triples
        if isinstance(tr.p, Iri) and tr.p.value == EYMSG_MESSAGE_COUNT
    )
    base = stream.removesuffix("#stream")
    return [formulas.get(f"{base}#m{i:03d}", GraphTerm([])) for i in range(1, count + 1)]


def _ordinary_triples(payload):
    return [tr for tr in payload.triples if not (isinstance(tr.p, Iri) and tr.p.value == LOG_NAME_OF)]


def _named_graphs(payload):
    return {
        tr.s.value: tr.o.triples
        for tr in payload.triples
        if isinstance(tr.s, Iri)
        and isinstance(tr.p, Iri)
        and tr.p.value == LOG_NAME_OF
        and isinstance(tr.o, GraphTerm)
    }


def test_1_2_1_single_message_without_delimiter():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"<{EX}s1> <{EX}p> <{EX}o1> .\n"
    )
    assert len(payloads) == 1
    assert len(payloads[0].triples) == 1


@pytest.mark.parametrize("delimiter", ["MESSAGE", "@message ."])
def test_1_2_2_and_1_2_3_two_messages_with_supported_delimiters(delimiter):
    prefix = (
        '@version "1.2-messages" .\n@prefix ex: <http://example.org/> .\n'
        if delimiter.startswith("@")
        else 'VERSION "1.2-messages"\nPREFIX ex: <http://example.org/>\n'
    )
    payloads = _message_payloads(
        f"{prefix}ex:s1 ex:p ex:o1 .\n{delimiter}\nex:s2 ex:p ex:o2 .\n"
    )
    assert [[tr.s.value for tr in payload.triples] for payload in payloads] == [
        [EX + "s1"],
        [EX + "s2"],
    ]


def test_1_2_4_empty_first_message():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        "MESSAGE\n"
        f"<{EX}s1> <{EX}p> <{EX}o1> .\n"
    )
    assert [len(payload.triples) for payload in payloads] == [0, 1]


def test_1_2_5_empty_message_between_non_empty_messages():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"<{EX}s1> <{EX}p> <{EX}o1> .\n"
        "MESSAGE\nMESSAGE\n"
        f"<{EX}s2> <{EX}p> <{EX}o2> .\n"
    )
    assert [len(payload.triples) for payload in payloads] == [1, 0, 1]


def test_1_2_6_final_delimiter_does_not_create_extra_empty_message():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"<{EX}s1> <{EX}p> <{EX}o1> .\n"
        "MESSAGE\n"
    )
    assert len(payloads) == 1
    assert len(payloads[0].triples) == 1


def test_1_2_7_nquads_messages_preserve_graph_names():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"<{EX}s1> <{EX}p> <{EX}o1> <{EX}g1> .\n"
        "MESSAGE\n"
        f"<{EX}s2> <{EX}p> <{EX}o2> <{EX}g2> .\n"
    )
    assert [set(_named_graphs(payload)) for payload in payloads] == [
        {EX + "g1"},
        {EX + "g2"},
    ]


def test_1_2_8_message_with_default_and_named_graph_quads():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        "PREFIX ex: <http://example.org/>\n"
        "ex:s1 ex:p ex:o1 .\n"
        "ex:g {\n"
        "  ex:s2 ex:p ex:o2 .\n"
        "  ex:s3 ex:p ex:o3 .\n"
        "}\n"
        "MESSAGE\n"
        "ex:s4 ex:p ex:o4 .\n"
    )
    assert len(_ordinary_triples(payloads[0])) == 1
    assert len(_named_graphs(payloads[0])[EX + "g"]) == 2
    assert len(_ordinary_triples(payloads[1])) == 1


def test_1_2_9_blank_node_labels_are_scoped_per_message():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"_:b0 <{EX}p> <{EX}o1> .\n"
        "MESSAGE\n"
        f"_:b0 <{EX}p> <{EX}o2> .\n"
    )
    subjects = [payload.triples[0].s for payload in payloads]
    assert all(isinstance(subject, Blank) for subject in subjects)
    assert subjects[0] != subjects[1]


def test_1_2_10_repeated_prefixes_only_affect_subsequent_messages():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        "PREFIX ex: <http://example.org/one/>\n"
        "ex:s ex:p ex:o .\n"
        "MESSAGE\n"
        "PREFIX ex: <http://example.org/two/>\n"
        "ex:s ex:p ex:o .\n"
    )
    assert [payload.triples[0].s.value for payload in payloads] == [
        EX + "one/s",
        EX + "two/s",
    ]


def test_1_2_11_message_boundary_after_graph_block():
    payloads = _message_payloads(
        'VERSION "1.2-messages"\n'
        f"<{EX}g> {{\n"
        f"  <{EX}a> <{EX}b> <{EX}c> .\n"
        "}\n"
        "MESSAGE\n"
        f"<{EX}d> <{EX}e> <{EX}f> .\n"
    )
    assert len(_named_graphs(payloads[0])[EX + "g"]) == 1
    assert len(_ordinary_triples(payloads[1])) == 1


def test_1_5_1_message_delimiter_without_message_support_is_an_error():
    with pytest.raises(SyntaxError):
        parse_rdf_text(
            f"<{EX}s> <{EX}p> <{EX}o> .\nMESSAGE\n",
            format="turtle",
        )


def test_1_5_2_invalid_at_message_directive_is_an_error():
    with pytest.raises(RdfSyntaxError):
        parse_rdf_message_log(
            'VERSION "1.2-messages"\n'
            f"<{EX}s> <{EX}p> <{EX}o> .\n"
            f"@message <{EX}invalid>\n"
        )


def test_1_5_3_message_delimiter_inside_open_graph_block_is_an_error():
    with pytest.raises(RdfSyntaxError):
        parse_rdf_message_log(
            'VERSION "1.2-messages"\n'
            f"<{EX}g> {{\n"
            f"  <{EX}a> <{EX}b> <{EX}c> .\n"
            "MESSAGE\n"
            f"  <{EX}d> <{EX}e> <{EX}f> .\n"
            "}\n"
        )
