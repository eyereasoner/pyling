"""Sphinx configuration for the pyling API documentation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

project = "pyling"
author = "Eyereasoner contributors"
copyright = "2026, Eyereasoner contributors"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path: list[str] = []
exclude_patterns: list[str] = []

autodoc_member_order = "bysource"
autodoc_typehints = "description"

html_theme = "sphinx_rtd_theme"
html_title = "pyling documentation"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
}
html_context = {
    "display_github": True,
    "github_user": "eyereasoner",
    "github_repo": "pyling",
    "github_version": "main",
    "conf_py_path": "/docs/api/",
}
