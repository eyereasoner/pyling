from __future__ import annotations

from email.message import Message
from urllib.error import URLError

import pyling.deref
from pyling import reason_stream
from pyling.deref import MAX_RESPONSE_BYTES, clear_http_cache, fetch_http_document


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        content_type: str = "text/n3; charset=utf-8",
    ):
        self._body = body
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def test_fetch_http_document_uses_rdflib_style_headers_redirect_base_and_cache(monkeypatch):
    calls = []

    def fake_urlopen(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            "@prefix : <#> . :café :says \"bonjour\" .".encode(),
            url="https://cdn.example/final/document.n3",
            content_type="text/n3; charset=utf-8",
        )

    clear_http_cache()
    monkeypatch.setattr(pyling.deref.urllib.request, "urlopen", fake_urlopen)

    document = fetch_http_document("https://example/source.n3#fragment")
    cached = fetch_http_document("https://example/source.n3#other")

    assert document is cached
    assert document is not None
    assert document.url == "https://cdn.example/final/document.n3"
    assert document.text.endswith('"bonjour" .')
    assert document.content_type == "text/n3"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://example/source.n3"
    assert "text/n3" in request.get_header("Accept")
    assert request.get_header("User-agent").startswith("pyling-n3/")
    assert timeout > 0


def test_log_content_and_semantics_dereference_http_iris(monkeypatch):
    documents = {
        "https://example/hello.txt": FakeResponse(
            b"Hello, world!\n",
            url="https://example/hello.txt",
            content_type="text/plain; charset=utf-8",
        ),
        "https://example/source.n3": FakeResponse(
            b"@prefix : <#> . :Hello a :World .\n",
            url="https://cdn.example/final/document.n3",
        ),
    }

    def fake_urlopen(request, *, timeout):
        return documents[request.full_url]

    clear_http_cache()
    monkeypatch.setattr(pyling.deref.urllib.request, "urlopen", fake_urlopen)
    result = reason_stream(
        """
        @prefix : <http://example/> .
        @prefix log: <http://www.w3.org/2000/10/swap/log#> .

        {
          <https://example/hello.txt> log:content "Hello, world!\\n" .
          <https://example/source.n3#ignored> log:semantics {
            <https://cdn.example/final/document.n3#Hello>
              a <https://cdn.example/final/document.n3#World> .
          } .
        } => { :test :is true . } .
        """
    )

    assert ":test :is true" in result.closure_n3


def test_log_semantics_standardizes_remote_variables_apart(monkeypatch):
    def fake_urlopen(_request, *, timeout):
        return FakeResponse(
            b"?formula <https://example/p> <https://example/o> .\n",
            url="https://example/source.n3",
        )

    clear_http_cache()
    monkeypatch.setattr(pyling.deref.urllib.request, "urlopen", fake_urlopen)
    result = reason_stream(
        """
        @prefix : <http://example/> .
        @prefix log: <http://www.w3.org/2000/10/swap/log#> .

        { <https://example/source.n3> log:semantics ?formula. } => {
          :result :formula ?formula.
          { :result :formula ?value. } => { :test :is true. }.
        }.
        """
    )

    assert ":test :is true" in result.closure_n3


def test_log_semantics_or_error_binds_a_string_on_http_failure(monkeypatch):
    def failing_urlopen(_request, *, timeout):
        raise URLError("offline")

    clear_http_cache()
    monkeypatch.setattr(pyling.deref.urllib.request, "urlopen", failing_urlopen)
    result = reason_stream(
        """
        @prefix : <http://example/> .
        @prefix log: <http://www.w3.org/2000/10/swap/log#> .

        { <https://example/missing.n3> log:semanticsOrError ?error . }
          => { :result :error ?error . } .
        """
    )

    assert "error(dereference_or_parse_failed,https://example/missing.n3)" in result.closure_n3


def test_fetch_http_document_rejects_oversized_and_non_http_redirects(monkeypatch):
    responses = iter(
        [
            FakeResponse(
                b"x" * (MAX_RESPONSE_BYTES + 1),
                url="https://example/large.n3",
            ),
            FakeResponse(b":s :p :o.", url="file:///etc/passwd"),
        ]
    )

    clear_http_cache()
    monkeypatch.setattr(
        pyling.deref.urllib.request,
        "urlopen",
        lambda _request, *, timeout: next(responses),
    )

    assert fetch_http_document("https://example/large.n3") is None
    assert fetch_http_document("https://example/redirect.n3") is None
