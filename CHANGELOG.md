# Changelog

All notable changes to pyling will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning while the public package API is still stabilizing.

## [0.1.2]

**Full Changelog**: https://github.com/eyereasoner/pyling/compare/0.1.1...0.1.2

## [0.1.1]

### Added

- HTTP(S) dereferencing for `log:content`, `log:semantics`, and
  `log:semanticsOrError`, including redirects, RDF content negotiation, and
  bounded response caching ([#2](https://github.com/eyereasoner/pyling/issues/2)).
- RDFLib graph input/output support for the Python API.
- RDF 1.2 syntax compatibility checks for N-Triples, N-Quads, Turtle, and TriG.
- Performance comparison harness for pyling and optional FuXi runs.
- Notebook documentation examples for RDFLib integration, the complete
  Eyeling OWL 2 RL ruleset, neuro-symbolic validation, and automatic QUDT
  conversion over RDF Message logs.
- GitHub Actions workflows for conformance tests, performance comparisons,
  notebook HTML builds, and package build checks.

### Changed

- `log:memoize` supports scalable integer-subject recursive predicates such as
  the Fibonacci example.
- `math:sum` and `math:product` preserve exact integer arithmetic for very large
  values.

### Fixed

- Eyeling-style backward base rules written as `{ ... } <= true.` are accepted.
- Variables inside formulas produced by `log:parsedAsN3` and `log:semantics`
  are scoped independently from variables in the calling rule.

## [0.1.0]

- Initial Python package scaffold for the Eyeling Notation3 reasoner port.
