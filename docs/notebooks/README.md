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

The notebooks avoid network access and embed their small rule/data fixtures so
they remain useful as published documentation.

