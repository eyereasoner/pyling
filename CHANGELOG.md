# Changelog

All notable changes to pyling will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning while the public package API is still stabilizing.

## [0.1.4]

### Added

- Example-scoped Python builtin modules for the Eyeling `sudoku.n3` and
  `queens.n3` examples.

### Changed

- Example-specific builtins are no longer part of Pyling's default builtin
  registry. The CLI and performance harness can load Python builtin modules
  explicitly with `--builtin`, matching Eyeling's example module pattern.
- Hot proof paths now avoid full substitution deltas for ordinary builtins,
  reuse unchanged term/triple objects after substitution, use cheaper
  visited-goal keys, and keep reusable fact indexes for repeated scoped
  formula searches.
- The engine now stores lazy internal integer lookup keys and cached numeric,
  substitution, and visited-key metadata on slotted term objects, reducing
  Python object-model overhead while preserving the public term API.
- Recursive proof search now uses trail-local dereference, substitution, and
  goal-ranking paths, with small-list fast paths and arithmetic builtin
  shortcuts to avoid redundant Python recursion in hot examples such as
  `takeuchi.n3` and `kaprekar-6174.n3`.
- The example-scoped Queens builtin now parallelizes independent first-row
  branches on platforms with cheap `fork` support, while remaining outside the
  default builtin registry.
- The performance harness now counts selected `log:query` output for query-mode
  examples instead of internal saturated fact stores, matching the examples'
  rendered output and avoiding implementation-specific count differences.
- `PERFORMANCE.md` now includes a full per-case table for all Eyeling examples,
  with network-enabled reruns for the HTTP-dependent cases.

### Fixed

- Broad variable-predicate queries no longer enumerate ambient live rules as
  ordinary facts. Explicit `log:implies` and `log:impliedBy` meta-rule matching
  still works, while `kronecker.n3` now matches Eyeling's selected output count.

**Full Changelog**: https://github.com/eyereasoner/pyling/compare/0.1.3...0.1.4

## [0.1.3]

### Added

- RDF Message parser coverage for RDF 1.2 Turtle, TriG, N-Triples, and
  N-Quads message streams.
- A narrative notebook series covering RDFLib integration, the complete
  Eyeling OWL 2 RL ruleset, neuro-symbolic validation, automatic QUDT
  normalization over RDF Message logs, and an ODRL FORCE compliance case.
- `owlrl` support in the MobiBench performance harness and CI workflow.
- Public RDFLib boundary helpers for converting terms, triples, documents, and
  graphs in both directions without exposing the internal N3 solver model.

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
- Backward proof search now uses a mutable substitution with rollback trails,
  following Eyeling's DFS strategy while preserving Pyling's public term model.
- RDFLib graph import/export reuses repeated term conversions within each
  conversion run, reducing boundary overhead without changing solver internals.

### Fixed

- RDF 1.2 TriG sidecars, empty and dynamic quoted-formula rule bodies, derived
  rules, and prefixed names containing interior dots are parsed correctly.
- Quoted formulas returned by `log:parsedAsN3` and `log:semantics` retain the
  variable scope required by nested rules.
- Mutually recursive backward rules terminate through ancestor-cycle handling;
  iterative proof search also avoids Python recursion limits on deep inputs.
- Backward loop-check state is restored before sibling goals, so conjunctions
  can prove multiple goals through the same recursive helper relation.
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
