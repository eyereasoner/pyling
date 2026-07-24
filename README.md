# pyling

[![PyPI version](https://img.shields.io/pypi/v/pyling-n3.svg)](https://pypi.org/project/pyling-n3/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyling-n3.svg)](https://pypi.org/project/pyling-n3/)
[![License](https://img.shields.io/pypi/l/pyling-n3.svg)](LICENSE)

`pyling` is a Python port of the [Eyeling](https://github.com/eyereasoner/eyeling)
Notation3 reasoner. Install it from PyPI as `pyling-n3`, import it as
`pyling`, and use it to run N3 rules over RDF data from Python code, notebooks,
or the command line.

It is useful when you want a small Python dependency for:

- deriving facts with Notation3 rules
- mixing N3 reasoning with RDFLib graphs
- reading Turtle, TriG, N-Triples, and N-Quads through RDFLib
- checking RDF 1.2 surface syntax in Python tooling
- replaying RDF Message Logs as whole logs or as message streams

The Eyeling repositories remain the main implementation; `pyling` gives Python
projects a native package interface to the same style of N3 reasoning.

## Install in your project

Install the published package from [PyPI](https://pypi.org/project/pyling-n3/):

```bash
python -m pip install pyling-n3
```

With project-oriented package managers:

```bash
uv add pyling-n3
poetry add pyling-n3
pdm add pyling-n3
```

The distribution package is named `pyling-n3`; the Python import package and
CLI command remain `pyling`.

```python
from pyling import reason

program = """
@prefix : <http://example.org/> .

:Socrates a :Man .
{ ?x a :Man } => { ?x a :Mortal } .
"""

print(reason(program))
```

```bash
pyling rules-and-facts.n3
```

For an unreleased development snapshot, install directly from GitHub:

```bash
python -m pip install "pyling-n3 @ git+https://github.com/eyereasoner/pyling.git"
uv add "pyling-n3 @ git+https://github.com/eyereasoner/pyling.git"
```

## Requirements

- Python 3.10 or newer
- `rdflib`, installed automatically with `pyling-n3`
- `pytest`, needed only for the test suite

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

print(reason(program))

result = reason_stream(program, include_input_facts_in_closure=True)
print(result.closure_n3)
print(result.derived)
```

Multi-source input mirrors Eyeling’s source-list style:

```python
from pyling import reason

out = reason({
    "sources": [
        "@prefix : <http://example.org/> .\n:Socrates a :Man .\n",
        "@prefix : <http://example.org/> .\n{ ?x a :Man } => { ?x a :Mortal } .\n",
    ]
})
```

The main exported term classes are `Iri`, `Literal`, `Var`, `Blank`, `ListTerm`, `GraphTerm`, `Triple`, `Rule`, and `PrefixEnv`.

## Notebook examples

Publishable notebooks live in `docs/notebooks/`:

- [RDFLib graphs with pyling](docs/notebooks/01-rdflib-reasoning.ipynb) shows
  RDFLib graph input and RDFLib graph output.
- [OWL 2 RL materialization](docs/notebooks/02-owl-style-rules.ipynb) loads and
  runs the complete OWL 2 RL/RDF N3 profile maintained for Eyeling.
- [Neuro-symbolic validation](docs/notebooks/03-neuro-symbolic-validation.ipynb)
  applies symbolic review policy to facts extracted by a neural model.
- [QUDT over an RDF Message log](docs/notebooks/04-qudt-message-log.ipynb)
  automatically normalizes logarithmic measurements in independently scoped
  messages.
- [ODRL FORCE compliance](docs/notebooks/05-odrl-force-compliance.ipynb)
  evaluates the ODRL Test Suite's complex weekday office-hours policy and
  produces an auditable compliance report.

Run them locally with:

```bash
python -m pip install -e ".[docs]"
jupyter lab docs/notebooks
```

GitHub Actions executes the notebooks and converts them to HTML in the
`Notebook docs` workflow. Pull requests upload the generated `notebook-site`
artifact; pushes to `main` also publish the same `site/` output through GitHub
Pages when Pages is enabled for GitHub Actions.

## RDF and RDF 1.2 compatibility

RDF mode is selected with `--rdf` on the CLI or `{"rdf": True}` in the API. It routes ordinary RDF syntax through `rdflib` instead of the N3 rule parser:

```python
from pyling import reason

rdf = """
PREFIX : <http://example.org/>
:a :p :b .
"""

print(reason(rdf, rdf=True, include_input_facts_in_closure=True))
```

RDFLib graphs can also be passed directly:

```python
from rdflib import Graph, Namespace
from pyling import reason_graph

ex = Namespace("http://example.org/")
g = Graph()
g.bind("", ex)
g.add((ex.a, ex.p, ex.b))

closure = reason_graph(g, include_input_facts_in_closure=True)
print(closure.serialize(format="turtle"))
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

## Performance comparisons

See the
[performance report](https://github.com/eyereasoner/pyling/blob/main/PERFORMANCE.md)
for measured comparisons with
[Eyeling](https://github.com/eyereasoner/eyeling), FuXi, and
[`owlrl`](https://pypi.org/project/owlrl/), including which runs completed,
whether their outputs were comparable, the benchmark method, and reproduction
commands.

```bash
npm run perf -- --list
npm run perf -- --case=socrates --reasoner=pyling,eyeling,fuxi
EYELING_PATH=../eyeling npm run perf:eyeling-examples
```

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

for result in reason_message_stream({"sources": [rules_n3, messages_trig]}):
    print(result.closure_n3)
```

The [QUDT notebook](docs/notebooks/04-qudt-message-log.ipynb) shows this API
applying automatic unit-normalization rules independently to each message.

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
- `log:` includes/notIncludes/content/semantics/semanticsOrError/conjunction,
  plus skolem/URI and equality helpers
- `dt:` datatype inspection, validation, value comparison, canonicalization
- `crypto:` md5/sha/sha256/sha512
- `time:` year/month/day/hour/minute/second/timeZone/localTime

`log:content` retrieves an HTTP(S) resource as a string. `log:semantics`
retrieves and parses an N3 document as a formula, resolving relative IRIs
against the final URL after redirects. Requests send N3/RDF `Accept` headers
and a versioned `User-Agent`, use a 30-second timeout, and reject responses
larger than 32 MiB. `log:semanticsOrError` binds an error string when retrieval
or parsing fails.

HTTP dereferencing can access any network location reachable by the process.
Applications handling untrusted N3 should restrict access with Python
`urllib` audit hooks or a custom installed opener, following
[RDFLib's security guidance](https://rdflib.readthedocs.io/en/latest/security_considerations/).

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

The runner defaults to `NETWORKING=1` so the networking fixtures for
`log:content`, `log:semantics`, and `log:semanticsOrError` are included. Set
`NETWORKING=0` explicitly for an offline conformance run.

You can also have `pytest` run the external suite by setting:

```bash
NOTATION3TESTS_DIR=/path/to/notation3tests python -m pytest -q
```

## Notes

- `rdflib` is used only for RDF/Turtle/TriG/N-Triples/N-Quads parsing. N3 rules and formulas are parsed by the local parser.
- RDF Message Logs are split and replayed before reasoning so message boundaries, empty heartbeat messages, and per-message blank-node scope are preserved.
- Packaging and publishing it on Pypi happens via a github action: create a new tag and release. Make sure the `pyproject.toml` is correct.
