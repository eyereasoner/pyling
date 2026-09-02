# Tutorials

These executable notebooks form a guided path from local inference to richer,
real-world reasoning workflows.

<div class="grid cards" markdown>

-   **1. RDFLib graphs with pyling**

    ---

    Establish the RDFLib-in, RDFLib-out integration pattern.

    [Start the tutorial](01-rdflib-reasoning.ipynb)

-   **2. OWL 2 RL materialization**

    ---

    Replace a toy rule with a maintained semantic profile.

    [Materialize OWL rules](02-owl-style-rules.ipynb)

-   **3. Neuro-symbolic validation**

    ---

    Turn uncertain extracted facts into an auditable review queue.

    [Validate extracted facts](03-neuro-symbolic-validation.ipynb)

-   **4. QUDT message logs**

    ---

    Reason over independently scoped streaming measurements.

    [Process message logs](04-qudt-message-log.ipynb)

-   **5. ODRL FORCE compliance**

    ---

    Combine policy, request, and world state into a linked compliance report.

    [Evaluate a policy](05-odrl-force-compliance.ipynb)

</div>

The documentation build executes every notebook before Material for MkDocs
renders it. This keeps the displayed outputs tested and makes each example
copyable as Python API documentation.

## Run locally

Install the documentation dependencies and open the notebooks:

```console
python -m pip install -e ".[docs]"
jupyter lab docs/notebooks
```

Or execute all notebooks in place:

```console
jupyter nbconvert --to notebook --execute --inplace docs/notebooks/*.ipynb
```

!!! note "Network access"

    Tutorials 2 and 4 load maintained rule profiles and fixtures from the
    `pietercolpaert/rdfjs-inference-engine` repository on GitHub. Executing the
    complete set therefore requires network access; the source URLs are visible
    in the notebooks.
