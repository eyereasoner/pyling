"""HTTP dereferencing support for N3 log built-ins."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urlsplit
import urllib.request

DEFAULT_ACCEPT = (
    "text/n3, text/turtle;q=0.9, application/n-triples;q=0.8, "
    "application/trig;q=0.7, application/n-quads;q=0.6, "
    "text/plain;q=0.2, */*;q=0.1"
)
DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_CACHE_ENTRIES = 128

try:
    _VERSION = version("pyling-n3")
except PackageNotFoundError:
    _VERSION = "development"

USER_AGENT = f"pyling-n3/{_VERSION} (https://github.com/eyereasoner/pyling)"


@dataclass(frozen=True, slots=True)
class HttpDocument:
    text: str
    url: str
    content_type: str | None


_HTTP_CACHE: OrderedDict[tuple[str, str], HttpDocument] = OrderedDict()


def strip_fragment(iri: str) -> str:
    return urldefrag(iri)[0]


def clear_http_cache() -> None:
    """Clear dereferenced documents, primarily for tests and long-lived apps."""
    _HTTP_CACHE.clear()


def fetch_http_document(
    iri: str,
    *,
    accept: str = DEFAULT_ACCEPT,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpDocument | None:
    """Fetch an HTTP(S) document using RDFLib-style urllib behavior.

    Redirects, Python audit hooks, and custom openers installed with
    ``urllib.request.install_opener`` are honored by ``urlopen``.
    """
    document_iri = strip_fragment(iri)
    if urlsplit(document_iri).scheme.lower() not in {"http", "https"}:
        return None
    cache_key = (document_iri, accept)
    if cache_key in _HTTP_CACHE:
        _HTTP_CACHE.move_to_end(cache_key)
        return _HTTP_CACHE[cache_key]

    request = urllib.request.Request(
        document_iri,
        headers={
            "Accept": accept,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return None
            final_url = response.geturl()
            if urlsplit(final_url).scheme.lower() not in {"http", "https"}:
                return None
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            result = HttpDocument(body.decode(charset), final_url, content_type)
    except (HTTPError, URLError, LookupError, OSError, UnicodeError, ValueError):
        return None

    _HTTP_CACHE[cache_key] = result
    _HTTP_CACHE.move_to_end(cache_key)
    while len(_HTTP_CACHE) > MAX_CACHE_ENTRIES:
        _HTTP_CACHE.popitem(last=False)
    return result
