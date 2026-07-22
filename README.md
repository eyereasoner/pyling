# pyling

A Python port of the Eyeling Notation3 reasoner.

RDF/Turtle/TriG compatibility through `rdflib`, RDF 1.2 surface-syntax checks, and RDF Message Log parsing/streaming.

The [Eyeling](https://github.com/eyereasoner/eyeling) repositories remains the main implementation. 

## Requirements

- Python 3.10 or newer
- `pip`
- `rdflib` is installed automatically from `pyproject.toml`
- `pytest` is needed only for the test suite

## Install in your project

After pyling is published to PyPI as `pyling-n3`, install it with Python's
standard package installer:

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

Until the package is published on PyPI, install directly from GitHub:

```bash
python -m pip install "pyling-n3 @ git+https://github.com/eyereasoner/pyling.git"
uv add "pyling-n3 @ git+https://github.com/eyereasoner/pyling.git"
```

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

- `01-rdflib-reasoning.ipynb` shows RDFLib graph input and RDFLib graph output.
- `02-owl-style-rules.ipynb` shows runtime-loaded OWL-style N3 rules.
- `03-neuro-symbolic-validation.ipynb` shows symbolic validation over facts
  extracted by a neural model.

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

The comparison harness in `tools/compare_reasoners.py` benchmarks pyling and
optional FuXi installations over shared N3 fixtures. FuXi is not installed in
the main project environment. When the `fuxi` reasoner is selected for a
benchmark run, the harness lazily creates `.cache/fuxi-venv` with Python 3.13
and installs the `fuxi` package there. The default benchmark suite discovers
selected `.n3` files from this repo's `examples/` directory. `--list` never
installs dependencies.

```bash
npm run perf -- --list
npm run perf -- --case=socrates --reasoner=pyling --iterations=5 --warmup=2
npm run perf -- --case=socrates --reasoner=pyling,fuxi --json
npm run perf -- --csv > perf-results.csv
```

OWL 2 RL support can be benchmarked with the MobiBench OWL2RL archive. pyling
loads the RDFJS inference engine's OWL2RL N3 rules from
`https://raw.githubusercontent.com/pietercolpaert/rdfjs-inference-engine/refs/heads/main/rules/owl2rl/owl2rl-eyeling.n3`.
For the same MobiBench cases, FuXi uses its built-in OWL/DLP setup instead of
that Eyeling-specific N3 ruleset. This keeps each reasoner on its intended OWL
path: pyling exercises runtime-loaded N3 rules, while FuXi exercises the OWL
rule generation shipped with FuXi.

```bash
npm run perf -- --suite=owl-mobibench --mobibench-limit=5 --reasoner=pyling
npm run perf:mobibench
```

Latest local MobiBench OWL2RL run, measured with one iteration and no warmup on
2026-07-22:

| Reasoner | Cases | Failures | Median ms/case | Cases deriving facts | Total derived facts |
|---|---:|---:|---:|---:|---:|
| pyling | 273 | 0 | 85.88 | 273 | 33,402 |
| FuXi | 273 | 0 | 95.93 | 43 | 221 |

Interpret these numbers as a profile of each configured reasoning path, not as
a strict semantic equivalence result. pyling materializes with the runtime-loaded
OWL2RL N3 rules, which include broad datatype and RDF-based entailment rules.
FuXi runs its built-in OWL/DLP translation, which is fast and useful for many
structural OWL cases but derives no facts for many datatype-heavy MobiBench
cases. For example, `rdfbased-sem-rdfs-subclass-trans` derives facts in both
engines, while the early `rdfbased-dat-*` cases mostly derive only in pyling.

The GitHub Actions performance workflow runs both `pyling` and `fuxi` for the
examples suite only. Full MobiBench is intentionally local-only through
`npm run perf:mobibench`, because it is larger and less suitable for normal pull
request feedback. Both paths write JSON, CSV, and Markdown reports to
`performance-reports`.

The slowest pyling cases in the latest completed full run were concentrated in
a small set of RDF-based OWL patterns:

| Case | pyling median ms | Derived facts |
|---|---:|---:|
| `mobibench-rdfbased-xtr-reflection-subclasses` | 133,292.61 | 290 |
| `mobibench-rdfbased-sem-bool-intersection-inst-comp` | 31,885.76 | 105 |
| `mobibench-rdfbased-sem-bool-intersection-inst-expr` | 31,301.35 | 106 |
| `mobibench-rdfbased-sem-bool-intersection-term` | 30,417.15 | 104 |
| `mobibench-rdfbased-sem-key-def` | 3,042.21 | 116 |

An interrupted full rerun stopped inside `pyling.engine.Engine.solve`, after
recursive goal solving had already entered a deep multi-premise OWL rule. That
matches the profile from the completed report: pyling is not uniformly slow,
but the current generic N3 fixpoint solver can spend disproportionate time on
rules with broad joins over RDF lists, subclass reflection, intersections, and
keys. The next performance work should focus on predicate indexing for rule
bodies, join ordering based on bound variables and candidate counts, and
deduplication of equivalent substitutions before recursive goal expansion.

The examples suite is useful for implementation regressions. After the
memoized Fibonacci fix, pyling completes `examples/fibonacci.n3` and derives
the expected query formula containing `F(0)`, `F(1)`, `F(10)`, `F(100)`,
`F(1000)`, and `F(10000)`. FuXi's generic N3 rule loader does not currently run
that file because it rejects the literal-subject rule shape used by the example.

Disable lazy installation, or supply a dedicated Python executable or checkout
path:

```bash
npm run perf -- --reasoner=fuxi --no-install-fuxi
FUXI_PYTHON=/path/to/venv/bin/python npm run perf -- --reasoner=fuxi
FUXI_PYTHONPATH=/path/to/FuXi-reincarnate/lib npm run perf -- --reasoner=fuxi
```

FuXi currently requires Python 3.13 or newer. If your system `python3` is older,
install a 3.13 interpreter and let the benchmark harness create
`.cache/fuxi-venv` from it. Two practical options:

```bash
# uv-managed Python, no system Python upgrade needed
uv python install 3.13
FUXI_PYTHON="$(uv python find 3.13)" npm run perf -- --reasoner=fuxi --case=socrates

# pyenv-managed Python
pyenv install 3.13
FUXI_PYTHON="$(pyenv prefix 3.13)/bin/python" npm run perf -- --reasoner=fuxi --case=socrates
```

After Python 3.13 is available, `npm run perf -- --reasoner=fuxi ...` installs
the `fuxi` package lazily into `.cache/fuxi-venv` and reuses that environment on
later benchmark runs.

Additional fixtures can be added without editing the script:

```bash
npm run perf -- --fixture=my-case=../eyeling/examples/deep-taxonomy-100.n3
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

## Packaging and release

The package metadata lives in `pyproject.toml`; releases are tracked in
`CHANGELOG.md`. PyPI is the Python package index, `pip` is the default installer
users will normally run, and `build` plus `twine` are the local maintainer tools
used to create and upload distributions. The `Package build` GitHub Actions
workflow builds the wheel and sdist, runs `twine check`, and uploads the
generated distributions as an artifact.

Build and inspect a release locally:

```bash
python -m pip install -e ".[build,test]"
python -m pytest -q
python -m build
twine check dist/pyling_n3-*
```

Publish first to TestPyPI:

```bash
twine upload --repository testpypi dist/pyling_n3-*
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  pyling-n3
```

If that install works in a fresh environment, publish the same checked
distributions to PyPI:

```bash
twine upload dist/pyling_n3-*
python -m pip install pyling-n3
```

For GitHub Actions releases, prefer PyPI Trusted Publishing over storing a
long-lived API token in repository secrets. Configure a PyPI trusted publisher
for the `eyereasoner/pyling` repository and the release workflow file, then use
`pypa/gh-action-pypi-publish` with `id-token: write` permissions.

Release checklist:

1. Update `CHANGELOG.md` and move the relevant entries from `Unreleased` to the
   new version.
2. Update `version` in `pyproject.toml`.
3. Run tests, conformance checks, notebook build, and package build locally or
   in GitHub Actions.
4. Confirm the published package name, ownership, license metadata, and long
   README rendering on TestPyPI.
5. Create a signed git tag, for example `v0.1.0`.
6. Upload to TestPyPI and install from TestPyPI in a fresh environment.
7. Upload the same checked distributions to PyPI.
8. Create a GitHub release from the tag and include the changelog notes.

## Development notes

- `rdflib` is used only for RDF/Turtle/TriG/N-Triples/N-Quads parsing. N3 rules and formulas are parsed by the local parser.
- RDF Message Logs are split and replayed before reasoning so message boundaries, empty heartbeat messages, and per-message blank-node scope are preserved.
