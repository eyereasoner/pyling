# pyling

A Python port of the Eyeling Notation3 reasoner.

RDF/Turtle/TriG compatibility through `rdflib`, RDF 1.2 surface-syntax checks, and RDF Message Log parsing/streaming.

The [Eyeling](https://github.com/eyereasoner/eyeling) repositories remains the main implementation. 

## Requirements

- Python 3.10 or newer
- `pip`
- `rdflib` is installed automatically from `pyproject.toml`
- `pytest` is needed only for the test suite

## Install from a checkout

```bash
cd pyling
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

Verify the install:

```bash
pyling --help
python -m pytest -q
```

## Command-line usage

Run a simple N3 rule program from standard input:

```bash
cat > example.n3 <<'EOF'
@prefix : <http://example.org/> .

:Socrates a :Man .
{ ?x a :Man } => { ?x a :Mortal } .
EOF

pyling example.n3
```

Expected derived output:

```n3
@prefix : <http://example.org/> .

:Socrates a :Mortal .
```

Include explicit input facts in the rendered closure:

```bash
pyling --include-input-facts example.n3
```

Read multiple sources, such as facts plus rules:

```bash
pyling facts.n3 rules.n3
```

Enable RDF/Turtle/TriG/RDF Message compatibility mode:

```bash
pyling --rdf data.trig rules.n3
```

Force a line format:

```bash
pyling --rdf --input-format nt data.nt

pyling --rdf --input-format nquads data.nq
```

## Python API

```python
from pyling import reason, reason_stream, run_async

program = """
@prefix : <http://example.org/> .
:a :p :b .
{ ?s :p ?o } => { ?s :q ?o } .
"""

print(reason({}, program))

result = reason_stream(program, {"include_input_facts_in_closure": True})
print(result.closure_n3)
print(result.derived)
```

Multi-source input mirrors Eyeling’s source-list style:

```python
from pyling import reason

out = reason({}, {
    "sources": [
        "@prefix : <http://example.org/> .\n:Socrates a :Man .\n",
        "@prefix : <http://example.org/> .\n{ ?x a :Man } => { ?x a :Mortal } .\n",
    ]
})
```

The main exported term classes are `Iri`, `Literal`, `Var`, `Blank`, `ListTerm`, `GraphTerm`, `Triple`, `Rule`, and `PrefixEnv`.

## RDF and RDF 1.2 compatibility

RDF mode is selected with `--rdf` on the CLI or `{"rdf": True}` in the API. It routes ordinary RDF syntax through `rdflib` instead of the N3 rule parser:

```python
from pyling import reason

rdf = """
PREFIX : <http://example.org/>
:a :p :b .
"""

print(reason({"rdf": True, "include_input_facts_in_closure": True}, rdf))
```

Supported compatibility inputs include:

- Turtle / `.ttl`
- TriG / `.trig`
- N-Triples / `.nt`
- N-Quads / `.nq`
- uppercase `PREFIX`, `BASE`, and RDF 1.2 `VERSION` surface forms
- simple RDF 1.2 annotation syntax, preserving the asserted triple
- RDF Message Logs using `VERSION "1.2-messages"` and `MESSAGE`

The RDF 1.2 layer includes strict surface checks for common negative conformance cases such as surrogate numeric escapes, invalid RDF 1.2 language tags in line syntaxes, relative IRIREFs in N-Triples/N-Quads, and annotation syntax in line syntaxes.

Run the bundled offline RDF 1.2 smoke suite:

```bash
python tools/run_rdf12_w3c.py
```

Run the W3C RDF 1.2 syntax compliance manifests (requires Node.js and network
access on the first run):

```bash
npm ci
npm run spec
```

The W3C runner caches downloaded manifests and fixtures in
`.rdf-test-suite-cache/`. All RDF 1.2 syntax cases in the configured N-Triples,
N-Quads, Turtle, and TriG manifests are enabled.

## RDF Message Logs

Whole-log replay:

```bash
cat > messages.trig <<'EOF'
VERSION "1.2-messages"
PREFIX : <http://example.org/>

:a :value 21 .

MESSAGE

# Empty heartbeat message.

MESSAGE

:b :value 22 .
EOF

pyling --rdf --include-input-facts messages.trig
```

Streaming replay, one message envelope at a time:

```bash
pyling --rdf --stream-messages rules.n3 messages.trig
```

Python streaming API:

```python
from pyling import reason_message_stream

for result in reason_message_stream({"sources": [rules_n3, messages_trig]}, {"rdf": True}):
    print(result.closure_n3)
```

The replay vocabulary uses:

```n3
@prefix eymsg: <https://eyereasoner.github.io/eyeling/vocab/message#> .
```

It materializes stream/envelope metadata, `eymsg:orderedEnvelopes`, `eymsg:messageCount`, `eymsg:payloadKind`, and payload formula links through `log:nameOf`. Rules can inspect each payload graph with `log:includes`.

## Built-ins

The package includes the built-in registry API:

```python
from pyling import register_builtin, unregister_builtin, list_builtin_iris
```

Built-in coverage includes common predicates in these namespaces:

- `math:` numeric comparison and arithmetic, plus common trig functions
- `string:` contains/matches/replace/format/length/comparison helpers
- `list:` first/rest/member/append/reverse/sort and related helpers
- `log:` includes/notIncludes/semantics/conjunction/skolem/uri and equality helpers
- `dt:` datatype inspection, validation, value comparison, canonicalization
- `crypto:` md5/sha/sha256/sha512
- `time:` year/month/day/hour/minute/second/timeZone/localTime

Registering a custom built-in:

```python
from pyling import Literal, XSD_NS, register_builtin


def hello(ctx):
    return [ctx.unify_term(ctx.goal.o, Literal("world", XSD_NS + "string"), ctx.subst)]

register_builtin("http://example.org/custom#hello", hello)
```

## Stores

The synchronous API uses in-memory reasoning. `run_async(..., {"store": ...})` can persist explicit and inferred triples through the included JSON-backed persistent store.

```python
import asyncio
from pyling import run_async

async def main():
    result = await run_async(program, {"store": {"name": "demo", "path": ".eyeling-store", "clear": True}})
    await result.store.close()

asyncio.run(main())
```

## Tests

Run the package tests:

```bash
python -m pytest -q
```

Run the offline RDF 1.2 compatibility smoke suite:

```bash
python tools/run_rdf12_w3c.py
```

Run the W3C RDF 1.2 compliance tests:

```bash
npm ci
npm run spec
```

Run the external `phochste/notation3tests` suite when you have network access or an existing checkout:

```bash
# Existing checkout
python tools/run_notation3tests.py /path/to/notation3tests

# Or let the runner clone and install the public suite at https://codeberg.org/phochste/notation3tests
python tools/run_notation3tests.py --clone
```

The runner defaults to `NETWORKING=0`, because this native port does not
dereference Web resources. It removes stale `.out` files for the 19 skipped
network fixtures so the reported score covers only tests actually executed.

You can also have `pytest` run the external suite by setting:

```bash
NOTATION3TESTS_DIR=/path/to/notation3tests python -m pytest -q
```

## Development notes

- `rdflib` is used only for RDF/Turtle/TriG/N-Triples/N-Quads parsing. N3 rules and formulas are parsed by the local parser.
- RDF Message Logs are split and replayed before reasoning so message boundaries, empty heartbeat messages, and per-message blank-node scope are preserved.
