# Changelog

All notable changes to pyling will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning while the public package API is still stabilizing.

## [Unreleased]

### Added

- RDFLib graph input/output support for the Python API.
- RDF 1.2 syntax compatibility checks for N-Triples, N-Quads, Turtle, and TriG.
- Performance comparison harness for pyling and optional FuXi runs.
- Notebook documentation examples for RDFLib integration, OWL-style rules, and
  neuro-symbolic validation.
- GitHub Actions workflows for conformance tests, performance comparisons,
  notebook HTML builds, and package build checks.

### Changed

- `log:memoize` supports scalable integer-subject recursive predicates such as
  the Fibonacci example.
- `math:sum` and `math:product` preserve exact integer arithmetic for very large
  values.

### Fixed

- Eyeling-style backward base rules written as `{ ... } <= true.` are accepted.

## [0.1.0]

- Initial Python package scaffold for the Eyeling Notation3 reasoner port.
