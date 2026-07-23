# Notebook examples

These notebooks are intended to render cleanly on GitHub Pages and to double as
copyable Python API documentation.

Run them locally from an editable checkout:

```bash
python -m pip install -e ".[docs]"
jupyter lab docs/notebooks
```

Or execute them in place:

```bash
jupyter nbconvert --to notebook --execute --inplace docs/notebooks/*.ipynb
```

Notebooks 02 and 04 load their maintained rule profiles and example fixtures
from `pietercolpaert/rdfjs-inference-engine` on GitHub, so executing the full
set requires network access. The source URLs are visible in the notebooks.
