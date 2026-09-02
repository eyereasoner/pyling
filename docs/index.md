# pyling

**Python-native Notation3 reasoning, powered by Eyeling.**

`pyling` runs N3 rules over RDF data from Python, notebooks, or the command
line. It supports RDFLib graphs, RDF 1.2 surface syntax, RDF Message Logs,
extensible built-ins, and in-memory or persistent fact stores.

<div class="grid cards" markdown>

-   :material-download: **Install**

    ---

    Install the published package from PyPI.

    ```console
    python -m pip install pyling-n3
    ```

-   :material-language-python: **Python API**

    ---

    Run a rule program with one function call.

    [Open the API reference](reference/index.md)

-   :material-notebook: **Executable tutorials**

    ---

    Work through practical RDFLib, OWL, QUDT, and ODRL examples.

    [Browse the tutorials](notebooks/index.md)

-   :material-console: **Command line**

    ---

    Reason over one or more local sources.

    ```console
    pyling facts.n3 rules.n3
    ```

</div>

## Quick start

```python
from pyling import reason

program = """
@prefix : <http://example.org/> .

:Socrates a :Man .
{ ?x a :Man } => { ?x a :Mortal } .
"""

print(reason(program))
```

The derived result is:

```n3
@prefix : <http://example.org/> .

:Socrates a :Mortal .
```

The distribution is named `pyling-n3`; the import package and CLI command are
both named `pyling`.

## RDFLib integration

Use `reason_graph()` when an application already works with RDFLib:

```python
from rdflib import Graph, Namespace
from pyling import reason_graph

ex = Namespace("http://example.org/")
graph = Graph()
graph.bind("", ex)
graph.add((ex.a, ex.p, ex.b))

closure = reason_graph(graph, include_input_facts_in_closure=True)
print(closure.serialize(format="turtle"))
```

See the [RDFLib tutorial](notebooks/01-rdflib-reasoning.ipynb) for an
end-to-end example.

## Requirements

- Python 3.10 or newer
- RDFLib 7.0 or newer, installed automatically
- `pytest` only when running the test suite

For an unreleased development snapshot:

```console
python -m pip install "pyling-n3 @ git+https://github.com/eyereasoner/pyling.git"
```
