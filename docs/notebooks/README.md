# Notebook examples

These notebooks form a guided path from one local inference to richer,
real-world reasoning workflows:

1. [RDFLib graphs with pyling](01-rdflib-reasoning.ipynb) establishes the
   RDFLib-in, RDFLib-out integration pattern.
2. [OWL 2 RL materialization](02-owl-style-rules.ipynb) replaces a toy rule
   with a maintained semantic profile.
3. [Neuro-symbolic validation](03-neuro-symbolic-validation.ipynb) turns
   uncertain extracted facts into an auditable review queue.
4. [QUDT over an RDF Message log](04-qudt-message-log.ipynb) reasons over
   independently scoped streaming measurements.
5. [ODRL FORCE compliance](05-odrl-force-compliance.ipynb) combines a policy,
   request, and state of the world into a linked compliance report.

They are intended to render cleanly on GitHub Pages and to double as copyable
Python API documentation. Each notebook explains why the next step is useful,
shows the evidence behind its result, and links to the next chapter.

Run them locally from an editable checkout:

```bash
python -m pip install -e ".[docs]"
jupyter lab docs/notebooks
```

Or execute them in place:

```bash
jupyter nbconvert --to notebook --execute --inplace docs/notebooks/*.ipynb
```

Notebooks 02 and 04 load maintained rule profiles and example fixtures from
`pietercolpaert/rdfjs-inference-engine` on GitHub, so executing the full set
requires network access. The source URLs are visible in the notebooks.
