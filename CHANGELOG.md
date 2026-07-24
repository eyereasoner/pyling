# Changelog

All notable changes to pyling will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning while the public package API is still stabilizing.

## [0.1.3]

### Added

- RDF Message parser coverage for RDF 1.2 Turtle, TriG, N-Triples, and
  N-Quads message streams.
- A narrative notebook series covering RDFLib integration, the complete
  Eyeling OWL 2 RL ruleset, neuro-symbolic validation, automatic QUDT
  normalization over RDF Message logs, and an ODRL FORCE compliance case.
- `owlrl` support in the MobiBench performance harness and CI workflow.

### Changed

- Pyling now executes every top-level Eyeling example: 222 return normally,
  while `fuse.n3` and `liar.n3` raise their expected inference fuses.
- Partially bound RDF-list patterns use component indexes. On the
  `relational-cube-lookup.n3` workload this removes repeated scans of all 3,375
  tuples for each of 2,000 lookups.
- The performance report presents the benchmark tests, measured results, and
  interpretation while distinguishing completion, output parity, and
  conformance.
- Notebook HTML and the notebook index use the Eyereasoner visual style.

### Fixed

- RDF 1.2 TriG sidecars, empty and dynamic quoted-formula rule bodies, derived
  rules, and prefixed names containing interior dots are parsed correctly.
- Quoted formulas returned by `log:parsedAsN3` and `log:semantics` retain the
  variable scope required by nested rules.
- Mutually recursive backward rules terminate through ancestor-cycle handling;
  iterative proof search also avoids Python recursion limits on deep inputs.
- Constructive `list:firstRest`, variable-predicate lookup, stable memoized
  proof snapshots, bound-input builtin prioritization, and normalized literal
  indexes restore the expected results for the Goldbach, path-discovery,
  Collatz, Kaprekar, Takeuchi, and deep-taxonomy examples.
- Inference fuses run after fixpoint completion, and proof depth counts nested
  reasoning rather than sequential conjuncts.
- Literal hashing follows Eyeling's escaped lexical representation, and
  `list:rest` no longer accepts the empty list as a non-empty decomposition.

**Full Changelog**: https://github.com/eyereasoner/pyling/compare/0.1.2...0.1.3

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
