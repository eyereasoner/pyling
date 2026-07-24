# Performance comparison

Benchmarks were run on 2026-07-24 for pyling 0.1.3. This document reports:

1. whether the test programs completed;
2. whether their output counts matched;
3. how long each reasoner took; and
4. what can and cannot be concluded from those numbers.

## Test environment

| Component | Version |
|---|---|
| pyling | 0.1.3 working tree |
| Eyeling | 2.35.1, commit `cb29f46` |
| FuXi | 2.0.1 on Python 3.13 |
| owlrl | 7.6.2 |
| RDFLib | 7.6.0 |
| Python | 3.12.3 |
| Node.js | 25.9.0 |
| Host | Intel Core i7-1265U, 30.8 GiB RAM, Linux 6.8 |

The timers include parsing, reasoning, and closure construction. Process and
module startup happen before the timed region.

## Eyeling example suite

All 224 top-level N3 examples from Eyeling were run once. Matching TriG inputs
were included where present.

### Completion and output

| Outcome | Cases |
|---|---:|
| Same normal or inference-fuse outcome | 224/224 |
| Both reasoners returned normally | 222 |
| Both raised the expected inference fuse | 2 |
| Exact fact and derived count in the broad run | 217 |
| Exact count after network-enabled HTTP reruns | 219 |
| Remaining explained count differences | 3 |

The two inference-fuse cases are `fuse.n3` and `liar.n3`. Their nonzero exits
are expected results.

The three remaining count differences are:

- `collection.n3`: both derive zero facts, but the engines count the RDF list
  representation differently.
- `builtin-coverage.n3`: the comparison adapter reports 29 Pyling derivations
  and zero Eyeling derivations, so this case is not a useful parity result.
- `sudoku.n3`: Eyeling loads an example-specific JavaScript solver. JavaScript
  builtin modules are intentionally outside Pyling's scope.

Eyeling's independent golden-output test also passed all 224 examples.

### Runtime

| Metric over 222 normally returning cases | pyling | Eyeling |
|---|---:|---:|
| Median per case | 9.63 ms | 18.27 ms |
| Arithmetic mean | 381.73 ms | 75.60 ms |
| Total measured time | 84.75 s | 16.78 s |
| Slowest case | 14.45 s | 2.38 s |

Among the 217 cases with exact counts in the broad run:

- Pyling was faster on 150 cases.
- Eyeling was faster on 67 cases.
- The median Pyling/Eyeling ratio was 0.594, making Pyling about 1.68 times
  faster on the typical exact-count example.

The total runtime favors Eyeling because a small number of large recursive
programs dominate the aggregate.

| Representative exact-count example | pyling | Eyeling | Interpretation |
|---|---:|---:|---|
| Socrates | 1.33 ms | 5.32 ms | Pyling 4.0x faster |
| Fibonacci | 2.88 s | 1.30 s | Pyling 2.2x slower |
| Deep taxonomy, 100,000 | 14.45 s | 2.38 s | Pyling 6.1x slower |
| Goldbach through 1,000 | 12.67 s | 1.52 s | Pyling 8.3x slower |
| Path discovery | 3.26 s | 0.92 s | Pyling 3.6x slower |
| Takeuchi | 8.90 s | 1.08 s | Pyling 8.2x slower |
| Collatz through 1,000 | 7.28 s | 0.56 s | Pyling 13.0x slower |

**Interpretation:** Pyling has lower overhead on small programs. Eyeling scales
better on several deep, recursive, or constructive workloads.

The largest improvements came from the same implementation strategies used by
Eyeling:

- bound RDF-list components are indexed instead of rescanning every fact;
- completed top-level goals and explicitly memoized predicates reuse answers;
- backward rules are selected by head predicate;
- ordinary goals remain left-to-right while only blocked builtins are deferred;
- single-premise rules use an agenda even when unrelated backward rules exist;
- ground terms and no-op unifications are reused instead of copied.

Compared with the pre-optimization broad run, path discovery decreased from
15.19 to 3.26 seconds and Takeuchi from 20.30 to 8.90 seconds. Recursive
arithmetic still exposes the main remaining gap: Eyeling uses numeric term IDs
and one mutable substitution with a rollback trail across its complete DFS.
Pyling still standardizes Python term objects and copies branch substitutions.

## Focused comparison with FuXi

These examples were measured three times after one warmup.

| Example | pyling | Eyeling | FuXi | Output |
|---|---:|---:|---:|---|
| Socrates | 0.45 ms | 5.74 ms | 2.69 ms | Pyling/Eyeling derive 1; FuXi derives 0 |
| Fibonacci | 3,171.95 ms | 1,511.62 ms | failed | FuXi rejects the literal-subject rule |
| Deep taxonomy, 10,000 | 1,658.37 ms | 429.15 ms | 4,013.14 ms | Pyling/Eyeling derive 30,009; FuXi derives 0 |

**Interpretation:** FuXi did not perform the same work on these N3 programs.
Its timings therefore cannot be ranked directly against Pyling or Eyeling.

## Relational cube lookup

`relational-cube-lookup.n3` performs 2,000 two-key lookups over 3,375 facts
represented as three-element lists.

The original reported measurements were:

| Reasoner | Time |
|---|---:|
| Eyeling | 0.455 s |
| Pyling before 0.1.3 | 86.913 s |

The issue was reproduced locally at 90.55 seconds. Pyling used only the
predicate index for a partially bound list such as
`(:a17 ?middle :c7)`, causing every lookup to scan all 3,375 facts.

Pyling 0.1.3 indexes bound list components by predicate, subject/object side,
and list position. The optimized comparison emits the expected
`:lookupResult :passed` result.

A controlled comparison used three measured runs:

| Reasoner | Median | Minimum | Maximum |
|---|---:|---:|---:|
| pyling 0.1.3 | 0.387 s | 0.383 s | 0.407 s |
| Eyeling 2.35.1 | 1.322 s | 1.267 s | 1.342 s |

**Interpretation:** The list-component index closes the reported algorithmic
gap on this machine: Pyling is 234 times faster than its reproduced 90.55
second baseline and 3.4 times faster than Eyeling in this run. These controlled
results should not be compared directly with timings from another machine.

## HTTP-dependent examples

The broad suite initially ran without network access. The two HTTP-dependent
examples were rerun with network access:

| Example | pyling | Eyeling | Output |
|---|---:|---:|---|
| `reaching-out.n3` | 111.50 ms | 6.55 ms | 2 facts, 2 derived |
| `shacl-conforms.n3` | 1,017.02 ms | 42.82 ms | 2 facts, 2 derived |

**Interpretation:** `log:content` and `log:semantics` complete successfully and
produce matching counts. Their timing depends heavily on network latency,
remote availability, and caching.

## MobiBench OWL 2 RL

The 273 positive-entailment and inconsistency inputs in the
[MobiBench OWL 2 RL archive](https://william-vw.github.io/mobibench/web/res/owl/conf/testsuite-owl2-rdfbased.zip)
were each run once.

- Pyling uses the
  [Eyeling OWL 2 RL N3 rules](https://github.com/pietercolpaert/rdfjs-inference-engine/blob/main/rules/owl2rl/owl2rl-eyeling.n3).
- FuXi uses its built-in OWL/DLP setup.
- `owlrl` uses its built-in `OWLRL_Semantics`.

| Reasoner | Completed | Median per case | Mean per case | Total |
|---|---:|---:|---:|---:|
| `owlrl` | 273/273 | 19.14 ms | 20.79 ms | 5.68 s |
| FuXi | 273/273 | 110.71 ms | 114.58 ms | 31.28 s |
| pyling | 273/273 | 202.71 ms | 237.08 ms | 64.72 s |

The list-component index also removed the previous Pyling hotspots:

- `rdfbased-xtr-reflection-subclasses` decreased from 133.29 seconds to
  348.34 ms.
- The slowest current Pyling case is
  `rdfbased-dat-dtype-datetime-valid` at 1.21 seconds.

**Interpretation:** `owlrl` is the clear performance choice when an application
needs only its fixed OWL 2 RL closure. Pyling is slower here because it executes
an external N3 ruleset through a general N3 engine.

An `ok` MobiBench result means the process completed. The harness does not yet
verify every expected entailment or inconsistency. Because the three reasoners
apply different rule systems, this table is a workload comparison rather than
a conformance result or a strict equivalent-work ranking.

## Overall interpretation

- Pyling successfully executes the complete Eyeling example set with the same
  normal or intentional-fuse outcome.
- It has low overhead and is faster on most small exact-count examples.
- Eyeling remains substantially faster on several large recursive examples.
- The 0.1.3 list index closes the severe relational-cube gap and removes the
  previous MobiBench outliers.
- FuXi is not directly comparable on the selected general N3 examples because
  it does not produce the same results.
- `owlrl` is faster for specialized OWL 2 RL closure; Pyling is useful when
  OWL rules must remain ordinary, inspectable N3 or be combined with broader
  N3 logic.

Count equality is a regression signal, not proof that complete output graphs
are isomorphic. Future correctness comparisons should normalize and compare
the full outputs and assert the expected MobiBench conclusions.

## Reproduce

Install the benchmark dependencies:

```bash
python -m pip install -e ".[test,performance]"
```

Run the full Eyeling suite and MobiBench:

```bash
npm run perf:eyeling-examples
npm run perf:mobibench
```

Run the focused comparison:

```bash
FUXI_PYTHON=.cache/fuxi-venv/bin/python \
python tools/compare_reasoners.py \
  --case=socrates \
  --case=fibonacci \
  --case=deep-taxonomy-10000 \
  --reasoner=pyling,eyeling,fuxi \
  --iterations=3 \
  --warmup=1 \
  --max-iterations=100000 \
  --timeout=600
```

Run the relational cube comparison:

```bash
curl -L \
  https://eyereasoner.github.io/eyeling/examples/relational-cube-lookup.n3 \
  -o /tmp/relational-cube-lookup.n3

python tools/compare_reasoners.py \
  --fixture=relational-cube=/tmp/relational-cube-lookup.n3 \
  --case=relational-cube \
  --reasoner=pyling,eyeling \
  --iterations=5 \
  --warmup=1 \
  --timeout=30
```

Use `--report-dir=performance-reports/<name>` to save JSON, CSV, and Markdown
reports. The `performance-reports/` directory is ignored by Git.
