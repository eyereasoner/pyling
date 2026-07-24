# Performance comparison

Benchmarks were run on 2026-07-24 for pyling 0.1.3. The focus is practical: did the examples complete, did the result counts match, and where is Pyling faster or slower than Eyeling?

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

Timers include parsing, reasoning, and closure construction. Process and module startup happen before the timed region. Each row below is one measured iteration with no warmup, so small timing differences should not be overinterpreted.

## Eyeling example suite

All 224 top-level N3 examples from Eyeling were run once. Matching TriG inputs were included where present. Example-specific builtins are loaded explicitly for both engines: Eyeling uses `../eyeling/examples/builtin/*.js`, and Pyling uses `examples/builtin/*.py` for the matching example name.

### Completion and counts

| Outcome | Cases |
|---|---:|
| Same normal or inference-fuse outcome | 224/224 |
| Both reasoners returned normally | 222 |
| Both raised the expected inference fuse | 2 |
| Exact selected-output count after HTTP reruns | 222 |
| Remaining explained count differences | 0 |

The two inference-fuse cases are `fuse.n3` and `liar.n3`; their nonzero exits are expected results. The two HTTP-dependent examples, `reaching-out.n3` and `shacl-conforms.n3`, match when rerun with network access. In the sandboxed broad run Pyling returned zero facts for those two cases because it could not fetch the remote documents.

For examples that use `log:query`, the comparison counts selected query output rather than the engines' internal saturated fact stores. This avoids treating implementation details as semantic differences: `collection.n3` uses different internal RDF list storage, and `builtin-coverage.n3` lets Pyling derive intermediate `:assurance` facts that are not part of the rendered `log:outputString` output.

### Runtime summary

| Metric over 222 normally returning cases | Pyling | Eyeling |
|---|---:|---:|
| Median per case | 10.47 ms | 17.47 ms |
| Arithmetic mean | 334.14 ms | 71.25 ms |
| Total measured time | 74.18 s | 15.82 s |
| Slowest case | 17.24 s | 2.51 s |

Among the 222 exact-output normal cases, Pyling was faster on 145 cases and Eyeling was faster on 77. The median Pyling/Eyeling ratio was 0.632, so Pyling is about 1.58x faster on the typical exact-count example. The total runtime still favors Eyeling because a small number of large recursive programs dominate the aggregate.

| Representative exact-count example | Pyling | Eyeling | Interpretation |
|---|---:|---:|---|
| Socrates | 1.30 ms | 5.10 ms | Pyling 3.9x faster |
| Sudoku | 15.46 ms | 18.50 ms | Pyling 1.2x faster |
| Queens | 2,394.01 ms | 260.81 ms | Pyling 9.2x slower |
| Fibonacci | 3,203.28 ms | 1,218.51 ms | Pyling 2.6x slower |
| Deep taxonomy, 100,000 | 13,928.66 ms | 2,512.63 ms | Pyling 5.5x slower |
| Goldbach through 1,000 | 3,509.58 ms | 1,403.38 ms | Pyling 2.5x slower |
| Path discovery | 3,222.56 ms | 802.35 ms | Pyling 4.0x slower |
| Takeuchi | 10,741.42 ms | 846.97 ms | Pyling 12.7x slower |
| Collatz through 1,000 | 1,854.13 ms | 561.16 ms | Pyling 3.3x slower |
| Kaprekar 6174 | 17,241.59 ms | 2,094.92 ms | Pyling 8.2x slower |

### Slow-case rerun after latest optimizations

After studying the latest Eyeling engine, Pyling adopted the same builtin-delta hot path for ordinary builtins, reduced substitution object churn, replaced JSON-based visited-goal keys, added reusable scoped fact-index states, and moved the Queens example to a separately loaded Python builtin that parallelizes independent search branches on Linux. The following focused rerun used the latest local Eyeling checkout at commit `0a9270e`.

| Case | Pyling | Eyeling | Pyling/Eyeling | Change from earlier Pyling run |
|---|---:|---:|---:|---:|
| `deep-taxonomy-100000.n3` | 15,109.72 ms | 2,364.27 ms | 6.39x | slower/no clear gain |
| `dining-philosophers.n3` | 900.31 ms | 114.77 ms | 7.84x | faster than 1,390.58 ms |
| `kaprekar-6174.n3` | 10,883.28 ms | 2,088.19 ms | 5.21x | faster than 17,241.59 ms |
| `queens.n3` | 697.95 ms | 265.25 ms | 2.63x | faster than 2,394.01 ms |
| `rdf-message-cold-chain-recall.n3` | 964.85 ms | 73.34 ms | 13.16x | about unchanged |
| `rdf-message-ldes-incremental.n3` | 466.28 ms | 68.40 ms | 6.82x | about unchanged |
| `takeuchi.n3` | 9,281.46 ms | 871.96 ms | 10.64x | faster than 10,741.42 ms |
| `transitive-closure.n3` | 2,402.11 ms | 400.50 ms | 6.00x | about unchanged |
| `zebra.n3` | 218.42 ms | 86.67 ms | 2.52x | faster than 837.23 ms |

The remaining substantial gaps are now most visible in broad data closure (`deep-taxonomy-100000.n3`), scoped RDF Message reasoning, and recursive arithmetic/search (`takeuchi.n3`, `kaprekar-6174.n3`). The optimizations improve Python interpreter overhead in those paths, but Eyeling still benefits from JavaScript term ids, array-attached indexes, and a lower-cost object model.

### Clearly slow cases

| Case | Pyling | Eyeling | Pyling/Eyeling |
|---|---:|---:|---:|
| `reaching-out.n3` | 134.51 ms | 6.91 ms | 19.5x |
| `shacl-conforms.n3` | 692.90 ms | 38.70 ms | 17.9x |
| `rdf-message-cold-chain-recall.n3` | 971.91 ms | 69.86 ms | 13.9x |
| `takeuchi.n3` | 10,741.42 ms | 846.97 ms | 12.7x |
| `dining-philosophers.n3` | 1,390.58 ms | 126.06 ms | 11.0x |
| `zebra.n3` | 837.23 ms | 77.55 ms | 10.8x |
| `queens.n3` | 2,394.01 ms | 260.81 ms | 9.2x |
| `doctor-advice-work-conflict.n3` | 206.94 ms | 22.78 ms | 9.1x |
| `kaprekar-6174.n3` | 17,241.59 ms | 2,094.92 ms | 8.2x |
| `odrl-policy-evaluation-snaf.n3` | 159.13 ms | 21.13 ms | 7.5x |
| `rdf-message-ldes-incremental.n3` | 463.86 ms | 63.17 ms | 7.3x |
| `eventual-interoperability-interaction-patterns.n3` | 139.48 ms | 20.99 ms | 6.6x |

The largest remaining gaps are concentrated in deep recursive search, recursive arithmetic, broad constructive joins, and RDF Message workloads. Pyling now uses Eyeling-inspired indexing, goal selection, memoization, and trail-backed substitutions, but still pays Python object-allocation and interpreter-recursion costs in cases such as `takeuchi.n3`, `kaprekar-6174.n3`, `zebra.n3`, and the scoped Python `queens.n3` builtin. The Sudoku issue is fixed differently: it is no longer a missing builtin, and the scoped Python solver is slightly faster than Eyeling on this run.

## Focused comparison with FuXi

These examples were measured three times after one warmup in the previous 0.1.3 release run. FuXi is included as a reference, but it does not perform the same work on several general N3 programs.

| Example | Pyling | Eyeling | FuXi | Output |
|---|---:|---:|---:|---|
| Socrates | 0.45 ms | 5.74 ms | 2.69 ms | Pyling/Eyeling derive 1; FuXi derives 0 |
| Fibonacci | 3,171.95 ms | 1,511.62 ms | failed | FuXi rejects the literal-subject rule |
| Deep taxonomy, 10,000 | 1,658.37 ms | 429.15 ms | 4,013.14 ms | Pyling/Eyeling derive 30,009; FuXi derives 0 |

## Relational cube lookup

`relational-cube-lookup.n3` performs 2,000 two-key lookups over 3,375 facts represented as three-element lists. The original issue reported Pyling at 86.913 seconds versus Eyeling at 0.455 seconds. The 0.1.3 list-component index closes that algorithmic gap.

| Reasoner | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Pyling 0.1.3 | 0.387 s | 0.383 s | 0.407 s |
| Eyeling 2.35.1 | 1.322 s | 1.267 s | 1.342 s |

## MobiBench OWL 2 RL

The 273 positive-entailment and inconsistency inputs in the MobiBench OWL 2 RL archive were run once with Pyling plus the Eyeling OWL 2 RL N3 rules, FuXi with its built-in OWL/DLP setup, and `owlrl` with its built-in `OWLRL_Semantics`.

| Reasoner | Completed | Median per case | Mean per case | Total |
|---|---:|---:|---:|---:|
| `owlrl` | 273/273 | 19.14 ms | 20.79 ms | 5.68 s |
| FuXi | 273/273 | 110.71 ms | 114.58 ms | 31.28 s |
| Pyling | 273/273 | 202.71 ms | 237.08 ms | 64.72 s |

`owlrl` is the clear performance choice when an application only needs its fixed OWL 2 RL closure. Pyling is slower here because it executes an external, inspectable N3 ruleset through a general N3 engine. That flexibility is useful when OWL rules need to be mixed with broader N3 logic, but it is not free.

## Full Eyeling Example Results

`Py/Ey ratio` is lower-is-better for Pyling. The `facts/derived` columns show final fact and derived counts for ordinary closure mode, and selected query-output counts for examples that use `log:query`. HTTP rows use the network-enabled rerun; all other rows come from `performance-reports/eyeling-examples-scoped-builtins-2026-07-24`, with `log:query` rows normalized to selected output counts.

| Case | Pyling status | Eyeling status | Pyling ms | Eyeling ms | Py/Ey ratio | Py facts/derived | Ey facts/derived |
|---|---|---|---:|---:|---:|---:|---:|
| `ackermann.n3` | ok | ok | 38.70 | 22.43 | 1.73x | 1/1 | 1/1 |
| `act-alarm-bit-interoperability.n3` | ok | ok | 5.79 | 10.66 | 0.54x | 70/53 | 70/53 |
| `act-barley-seed-lineage.n3` | ok | ok | 17.51 | 16.98 | 1.03x | 234/60 | 234/60 |
| `act-docking-abort.n3` | ok | ok | 207.17 | 61.01 | 3.40x | 1024/1003 | 1024/1003 |
| `act-gravity-mediator-witness.n3` | ok | ok | 6.87 | 10.06 | 0.68x | 62/31 | 62/31 |
| `act-isolation-breach.n3` | ok | ok | 269.92 | 61.65 | 4.38x | 1132/1108 | 1132/1108 |
| `act-photosynthetic-exciton-transfer.n3` | ok | ok | 5.77 | 9.89 | 0.58x | 46/21 | 46/21 |
| `act-sensor-memory-reset.n3` | ok | ok | 5.02 | 9.55 | 0.53x | 38/22 | 38/22 |
| `act-tunnel-junction-wake-switch.n3` | ok | ok | 5.63 | 9.94 | 0.57x | 45/23 | 45/23 |
| `act-yeast-self-reproduction.n3` | ok | ok | 7.28 | 10.42 | 0.70x | 63/33 | 63/33 |
| `age.n3` | ok | ok | 1.54 | 7.55 | 0.20x | 2/1 | 2/1 |
| `alignment-demo.n3` | ok | ok | 4.20 | 7.87 | 0.53x | 46/32 | 46/32 |
| `allen-interval-calculus.n3` | ok | ok | 208.65 | 72.10 | 2.89x | 176/154 | 176/154 |
| `alma-rdf-messages.n3` | ok | ok | 4.37 | 6.45 | 0.68x | 0/0 | 0/0 |
| `annotation.n3` | ok | ok | 5.00 | 7.84 | 0.64x | 10/0 | 10/0 |
| `auroracare.n3` | ok | ok | 11.69 | 15.43 | 0.76x | 227/114 | 227/114 |
| `backward.n3` | ok | ok | 1.16 | 6.86 | 0.17x | 1/1 | 1/1 |
| `backward-recursion.n3` | ok | ok | 5.03 | 8.56 | 0.59x | 6/2 | 6/2 |
| `barley-seed-becoming.n3` | ok | ok | 18.33 | 15.71 | 1.17x | 233/60 | 233/60 |
| `basic-monadic.n3` | ok | ok | 197.28 | 69.51 | 2.84x | 10005/5 | 10005/5 |
| `bayes-diagnosis.n3` | ok | ok | 15.20 | 23.29 | 0.65x | 99/18 | 99/18 |
| `bayes-therapy.n3` | ok | ok | 37.09 | 28.95 | 1.28x | 122/23 | 122/23 |
| `bmi.n3` | ok | ok | 9.39 | 16.52 | 0.57x | 34/30 | 34/30 |
| `builtin-coverage.n3` | ok | ok | 9.32 | 12.03 | 0.77x | 1/1 | 1/1 |
| `calidor.n3` | ok | ok | 16.64 | 27.06 | 0.61x | 149/45 | 149/45 |
| `cat-koko.n3` | ok | ok | 1.77 | 8.04 | 0.22x | 6/5 | 6/5 |
| `cobalt-kepler-kitchen.n3` | ok | ok | 21.47 | 23.64 | 0.91x | 63/46 | 63/46 |
| `collatz-1000.n3` | ok | ok | 1,854.13 | 561.16 | 3.30x | 1000/1000 | 1000/1000 |
| `collection.n3` | ok | ok | 4.52 | 8.48 | 0.53x | 1/1 | 1/1 |
| `complex.n3` | ok | ok | 9.20 | 19.42 | 0.47x | 1/1 | 1/1 |
| `complex-matrix-stability.n3` | ok | ok | 47.35 | 45.56 | 1.04x | 48/7 | 48/7 |
| `composition-of-injective-functions-is-injective.n3` | ok | ok | 7.60 | 16.53 | 0.46x | 27/15 | 27/15 |
| `constructor-theory-becoming.n3` | ok | ok | 3.93 | 8.02 | 0.49x | 59/16 | 59/16 |
| `context-association.n3` | ok | ok | 10.49 | 19.65 | 0.53x | 11/8 | 11/8 |
| `context-schema-audit.n3` | ok | ok | 6.06 | 12.45 | 0.49x | 20/13 | 20/13 |
| `control-system.n3` | ok | ok | 8.25 | 25.69 | 0.32x | 35/24 | 35/24 |
| `control-system-becoming.n3` | ok | ok | 4.42 | 8.62 | 0.51x | 70/33 | 70/33 |
| `cranberry-calculus.n3` | ok | ok | 9.35 | 16.37 | 0.57x | 29/19 | 29/19 |
| `crypto-builtins-tests.n3` | ok | ok | 1.51 | 6.39 | 0.24x | 4/4 | 4/4 |
| `decimal-ebike-motor-thermal-envelope.n3` | ok | ok | 75.66 | 34.66 | 2.18x | 90/59 | 90/59 |
| `decimal-transcendental-servo-envelope.n3` | ok | ok | 32.05 | 27.18 | 1.18x | 41/32 | 41/32 |
| `deep-taxonomy-10.n3` | ok | ok | 3.80 | 11.75 | 0.32x | 41/39 | 41/39 |
| `deep-taxonomy-100.n3` | ok | ok | 14.27 | 14.76 | 0.97x | 311/309 | 311/309 |
| `deep-taxonomy-1000.n3` | ok | ok | 126.07 | 44.59 | 2.83x | 3011/3009 | 3011/3009 |
| `deep-taxonomy-10000.n3` | ok | ok | 1,310.67 | 270.48 | 4.85x | 30011/30009 | 30011/30009 |
| `deep-taxonomy-100000.n3` | ok | ok | 13,928.66 | 2,512.63 | 5.54x | 300011/300009 | 300011/300009 |
| `delfour.n3` | ok | ok | 23.82 | 22.90 | 1.04x | 127/36 | 127/36 |
| `derived-backward-rule.n3` | ok | ok | 1.63 | 5.56 | 0.29x | 4/2 | 4/2 |
| `derived-backward-rule-2.n3` | ok | ok | 1.72 | 5.94 | 0.29x | 4/4 | 4/4 |
| `derived-rule.n3` | ok | ok | 1.46 | 4.47 | 0.33x | 4/2 | 4/2 |
| `developmental-genetics-becoming.n3` | ok | ok | 5.00 | 9.01 | 0.55x | 65/30 | 65/30 |
| `digital-product-passport.n3` | ok | ok | 8.43 | 22.95 | 0.37x | 120/7 | 120/7 |
| `dijkstra.n3` | ok | ok | 35.13 | 34.41 | 1.02x | 25/16 | 25/16 |
| `dijkstra-risk-path.n3` | ok | ok | 8.33 | 14.11 | 0.59x | 27/5 | 27/5 |
| `dining-philosophers.n3` | ok | ok | 1,390.58 | 126.06 | 11.03x | 1103/806 | 1103/806 |
| `doctor-advice-work-conflict.n3` | ok | ok | 206.94 | 22.78 | 9.08x | 12/11 | 12/11 |
| `dog.n3` | ok | ok | 3.44 | 8.79 | 0.39x | 8/1 | 8/1 |
| `dpv-odrl-purpose-mapping.n3` | ok | ok | 3.15 | 6.64 | 0.47x | 29/18 | 29/18 |
| `drone-corridor-planner.n3` | ok | ok | 98.99 | 53.61 | 1.85x | 21/17 | 21/17 |
| `e-computable-real.n3` | ok | ok | 127.79 | 59.96 | 2.13x | 121/112 | 121/112 |
| `easter.n3` | ok | ok | 62.97 | 69.19 | 0.91x | 473/325 | 473/325 |
| `eco-route-insight.n3` | ok | ok | 11.67 | 15.16 | 0.77x | 40/6 | 40/6 |
| `engineering-becoming.n3` | ok | ok | 3.55 | 7.90 | 0.45x | 55/24 | 55/24 |
| `equals.n3` | ok | ok | 0.48 | 6.03 | 0.08x | 2/1 | 2/1 |
| `equivalence-classes-overlap-implies-same-class.n3` | ok | ok | 7.03 | 21.03 | 0.33x | 57/52 | 57/52 |
| `ershov-mixed-computation.n3` | ok | ok | 3.66 | 10.18 | 0.36x | 5/2 | 5/2 |
| `euler-identity.n3` | ok | ok | 3.52 | 23.08 | 0.15x | 16/6 | 16/6 |
| `ev-roundtrip-planner.n3` | ok | ok | 86.87 | 67.68 | 1.28x | 12/8 | 12/8 |
| `eventual-interoperability-interaction-patterns.n3` | ok | ok | 139.48 | 20.99 | 6.64x | 128/41 | 128/41 |
| `existential-rule.n3` | ok | ok | 1.25 | 4.89 | 0.26x | 4/2 | 4/2 |
| `expression-eval.n3` | ok | ok | 3.58 | 12.45 | 0.29x | 18/1 | 18/1 |
| `faltings-genus2-finiteness.n3` | ok | ok | 2.06 | 7.86 | 0.26x | 33/3 | 33/3 |
| `family-cousins.n3` | ok | ok | 7.53 | 13.93 | 0.54x | 40/25 | 40/25 |
| `fastpow.n3` | ok | ok | 21.24 | 14.02 | 1.52x | 1/1 | 1/1 |
| `fft32-numeric.n3` | ok | ok | 218.11 | 96.61 | 2.26x | 38/0 | 38/0 |
| `fft8-numeric.n3` | ok | ok | 49.90 | 25.38 | 1.97x | 8/0 | 8/0 |
| `fft8-symbolic.n3` | ok | ok | 41.05 | 37.31 | 1.10x | 0/0 | 0/0 |
| `fibonacci.n3` | ok | ok | 3,203.28 | 1,218.51 | 2.63x | 1/1 | 1/1 |
| `flandor.n3` | ok | ok | 15.59 | 22.74 | 0.69x | 171/45 | 171/45 |
| `floating-point-first-ema-tracker.n3` | ok | ok | 100.30 | 44.81 | 2.24x | 66/57 | 66/57 |
| `floating-point-first-rc-discharge.n3` | ok | ok | 67.57 | 35.07 | 1.93x | 56/47 | 56/47 |
| `floating-point-first-servo-envelope.n3` | ok | ok | 35.55 | 29.33 | 1.21x | 41/32 | 41/32 |
| `floating-point-first-thermal-cooling.n3` | ok | ok | 68.09 | 35.37 | 1.92x | 54/45 | 54/45 |
| `french-cities.n3` | ok | ok | 8.14 | 15.58 | 0.52x | 57/39 | 57/39 |
| `fundamental-theorem-arithmetic.n3` | ok | ok | 1,042.04 | 258.17 | 4.04x | 24/18 | 24/18 |
| `fuse.n3` | failed | failed |  |  |  |  |  |
| `gd-step-certified.n3` | ok | ok | 86.49 | 47.66 | 1.81x | 104/99 | 104/99 |
| `genetic-algorithm.n3` | ok | ok | 1,327.60 | 251.16 | 5.29x | 3/0 | 3/0 |
| `genetic-algorithm-knapsack.n3` | ok | ok | 959.04 | 204.08 | 4.70x | 3/0 | 3/0 |
| `genetic-knapsack-selection.n3` | ok | ok | 7.00 | 15.67 | 0.45x | 18/3 | 18/3 |
| `get-uuid.n3` | ok | ok | 3.80 | 10.51 | 0.36x | 4/2 | 4/2 |
| `godel-incompleteness.n3` | ok | ok | 2.58 | 7.88 | 0.33x | 50/4 | 50/4 |
| `godel-template.n3` | ok | ok | 7.52 | 15.36 | 0.49x | 38/6 | 38/6 |
| `goldbach-1000.n3` | ok | ok | 3,509.58 | 1,403.38 | 2.50x | 668/667 | 668/667 |
| `good-cobbler.n3` | ok | ok | 0.49 | 4.28 | 0.11x | 2/1 | 2/1 |
| `gps.n3` | ok | ok | 9.95 | 21.07 | 0.47x | 18/13 | 18/13 |
| `gray-code-counter.n3` | ok | ok | 11.07 | 15.55 | 0.71x | 11/1 | 11/1 |
| `greatest-lower-bound-uniqueness.n3` | ok | ok | 4.59 | 15.86 | 0.29x | 28/22 | 28/22 |
| `group-inverse-uniqueness.n3` | ok | ok | 7.42 | 17.36 | 0.43x | 27/21 | 27/21 |
| `hadamard-approx.n3` | ok | ok | 351.11 | 103.09 | 3.41x | 511/503 | 511/503 |
| `hanoi.n3` | ok | ok | 2.76 | 8.90 | 0.31x | 1/1 | 1/1 |
| `harborsmr.n3` | ok | ok | 7.26 | 13.74 | 0.53x | 68/14 | 68/14 |
| `high-trust-rdf-bloom-envelope.n3` | ok | ok | 5.78 | 18.14 | 0.32x | 25/11 | 25/11 |
| `high-trust-rdf-bloom-tamper-contrast.n3` | ok | ok | 11.12 | 23.01 | 0.48x | 60/32 | 60/32 |
| `ill-formed-literals.n3` | ok | ok | 56.25 | 76.28 | 0.74x | 48/32 | 48/32 |
| `integer-first-control-tank-level.n3` | ok | ok | 95.12 | 39.39 | 2.41x | 156/146 | 156/146 |
| `integer-first-sqrt2-mediants.n3` | ok | ok | 53.42 | 37.53 | 1.42x | 49/44 | 49/44 |
| `interop-demo.n3` | ok | ok | 5.56 | 11.60 | 0.48x | 41/27 | 41/27 |
| `jade-eigen-loom.n3` | ok | ok | 29.14 | 24.99 | 1.17x | 79/57 | 79/57 |
| `jsonterm.n3` | ok | ok | 1.50 | 5.46 | 0.28x | 6/1 | 6/1 |
| `jsonterm-advanced.n3` | ok | ok | 3.28 | 7.53 | 0.44x | 27/6 | 27/6 |
| `kaprekar-6174.n3` | ok | ok | 17,241.59 | 2,094.92 | 8.23x | 19991/19989 | 19991/19989 |
| `knowledge-engineering-alignment-flow.n3` | ok | ok | 4.70 | 8.97 | 0.52x | 33/19 | 33/19 |
| `kronecker.n3` | ok | ok | 6.94 | 22.06 | 0.31x | 69/49 | 69/49 |
| `liar.n3` | failed | failed |  |  |  |  |  |
| `light-eaters.n3` | ok | ok | 3.39 | 10.59 | 0.32x | 30/13 | 30/13 |
| `list-builtins-tests.n3` | ok | ok | 3.47 | 8.47 | 0.41x | 11/11 | 11/11 |
| `list-iterate.n3` | ok | ok | 2.16 | 7.94 | 0.27x | 6/5 | 6/5 |
| `list-map.n3` | ok | ok | 1.76 | 7.39 | 0.24x | 8/4 | 8/4 |
| `lldm.n3` | ok | ok | 20.73 | 22.22 | 0.93x | 166/38 | 166/38 |
| `log-collect-all-in.n3` | ok | ok | 2.17 | 7.87 | 0.28x | 6/3 | 6/3 |
| `log-conclusion.n3` | ok | ok | 1.60 | 8.26 | 0.19x | 2/1 | 2/1 |
| `log-for-all-in.n3` | ok | ok | 1.30 | 7.49 | 0.17x | 8/1 | 8/1 |
| `log-not-includes.n3` | ok | ok | 1.61 | 7.82 | 0.21x | 3/3 | 3/3 |
| `log-pan-rt-soe.n3` | ok | ok | 14.57 | 37.75 | 0.39x | 5/4 | 5/4 |
| `log-skolem.n3` | ok | ok | 0.55 | 6.33 | 0.09x | 1/1 | 1/1 |
| `log-uri.n3` | ok | ok | 1.19 | 6.30 | 0.19x | 2/2 | 2/2 |
| `math-builtins-tests.n3` | ok | ok | 12.82 | 14.50 | 0.88x | 200/192 | 200/192 |
| `matiyasevich-pi-fib.n3` | ok | ok | 141.06 | 51.66 | 2.73x | 69/68 | 69/68 |
| `matrix-mechanics.n3` | ok | ok | 14.62 | 14.40 | 1.02x | 43/35 | 43/35 |
| `medior.n3` | ok | ok | 17.44 | 25.24 | 0.69x | 165/45 | 165/45 |
| `meta-rule-audit.n3` | ok | ok | 14.84 | 12.82 | 1.16x | 11/10 | 11/10 |
| `minimal-skos-alignment.n3` | ok | ok | 1.50 | 5.41 | 0.28x | 7/2 | 7/2 |
| `modexp.n3` | ok | ok | 29.58 | 26.37 | 1.12x | 6/6 | 6/6 |
| `monkey.n3` | ok | ok | 1.19 | 4.78 | 0.25x | 4/2 | 4/2 |
| `monoid-identity-uniqueness.n3` | ok | ok | 1.86 | 7.40 | 0.25x | 0/0 | 0/0 |
| `n3-delegation-access.n3` | ok | ok | 10.56 | 24.45 | 0.43x | 22/16 | 22/16 |
| `n3-speaks-for-itself.n3` | ok | ok | 4.70 | 28.79 | 0.16x | 21/13 | 21/13 |
| `odrl-benefits.n3` | ok | ok | 6.65 | 11.74 | 0.57x | 72/11 | 72/11 |
| `odrl-dpv-campaign-audit.n3` | ok | ok | 7.90 | 17.85 | 0.44x | 5/4 | 5/4 |
| `odrl-dpv-conflict-audit.n3` | ok | ok | 13.69 | 20.24 | 0.68x | 5/4 | 5/4 |
| `odrl-dpv-ehds-risk-ranked.n3` | ok | ok | 29.39 | 27.03 | 1.09x | 152/95 | 152/95 |
| `odrl-dpv-fpv-trust-flow.n3` | ok | ok | 6.50 | 10.75 | 0.60x | 56/9 | 56/9 |
| `odrl-dpv-healthcare-risk-ranked.n3` | ok | ok | 42.41 | 33.29 | 1.27x | 140/82 | 140/82 |
| `odrl-dpv-risk-ranked.n3` | ok | ok | 29.70 | 26.33 | 1.13x | 145/107 | 145/107 |
| `odrl-policy-audit.n3` | ok | ok | 5.35 | 17.59 | 0.30x | 5/4 | 5/4 |
| `odrl-policy-evaluation-snaf.n3` | ok | ok | 159.13 | 21.13 | 7.53x | 20/19 | 20/19 |
| `odrl-risk.n3` | ok | ok | 31.68 | 22.65 | 1.40x | 78/60 | 78/60 |
| `odrl-risk-mitigation.n3` | ok | ok | 114.58 | 37.79 | 3.03x | 186/149 | 186/149 |
| `odrl-trust.n3` | ok | ok | 5.11 | 10.88 | 0.47x | 42/2 | 42/2 |
| `ontology-question-generation.n3` | ok | ok | 28.61 | 30.24 | 0.95x | 293/240 | 293/240 |
| `oslo-steps-library-scholarly.n3` | ok | ok | 266.53 | 102.08 | 2.61x | 123/28 | 123/28 |
| `oslo-steps-workflow-composition.n3` | ok | ok | 96.94 | 42.92 | 2.26x | 83/4 | 83/4 |
| `paraconsistent-animals.n3` | ok | ok | 46.38 | 15.62 | 2.97x | 37/36 | 37/36 |
| `parcellocker.n3` | ok | ok | 5.14 | 10.58 | 0.49x | 39/12 | 39/12 |
| `patch.n3` | ok | ok | 3.22 | 8.90 | 0.36x | 4/1 | 4/1 |
| `path-discovery.n3` | ok | ok | 3,222.56 | 802.35 | 4.02x | 96423/3 | 96423/3 |
| `peano.n3` | ok | ok | 51.95 | 23.11 | 2.25x | 1/1 | 1/1 |
| `pi.n3` | ok | ok | 56.45 | 29.19 | 1.93x | 1/1 | 1/1 |
| `pi-computable-real.n3` | ok | ok | 250.54 | 65.36 | 3.83x | 219/209 | 219/209 |
| `pillar.n3` | ok | ok | 1.79 | 6.09 | 0.29x | 3/2 | 3/2 |
| `pn-junction-tunneling.n3` | ok | ok | 14.41 | 18.65 | 0.77x | 106/94 | 106/94 |
| `polygon.n3` | ok | ok | 8.94 | 9.95 | 0.90x | 1/1 | 1/1 |
| `polynomial.n3` | ok | ok | 136.18 | 87.29 | 1.56x | 12/8 | 12/8 |
| `queens.n3` | ok | ok | 2,394.01 | 260.81 | 9.18x | 2/0 | 2/0 |
| `quoted-head-unquote.n3` | ok | ok | 1.56 | 6.09 | 0.26x | 5/3 | 5/3 |
| `quoted-head-unquote-select.n3` | ok | ok | 1.86 | 6.10 | 0.30x | 8/3 | 8/3 |
| `rc-discharge-envelope.n3` | ok | ok | 8.66 | 14.10 | 0.61x | 20/7 | 20/7 |
| `rdf-dataset.n3` | ok | ok | 6.08 | 9.30 | 0.65x | 8/2 | 8/2 |
| `rdf-list.n3` | ok | ok | 1.47 | 7.53 | 0.19x | 2/1 | 2/1 |
| `rdf-message-cold-chain-recall.n3` | ok | ok | 971.91 | 69.86 | 13.91x | 1018/671 | 1018/671 |
| `rdf-message-flow.n3` | ok | ok | 40.14 | 27.24 | 1.47x | 94/57 | 94/57 |
| `rdf-message-ldes-incremental.n3` | ok | ok | 463.86 | 63.17 | 7.34x | 821/530 | 821/530 |
| `rdf-message-microgrid.n3` | ok | ok | 15.50 | 24.25 | 0.64x | 56/26 | 56/26 |
| `rdf-message-window-repair.n3` | ok | ok | 24.73 | 26.33 | 0.94x | 102/63 | 102/63 |
| `rdf-messages.n3` | ok | ok | 11.26 | 21.65 | 0.52x | 43/20 | 43/20 |
| `reaching-out.n3` | ok | ok | 134.51 | 6.91 | 19.46x | 2/2 | 2/2 |
| `reordering.n3` | ok | ok | 1.48 | 7.59 | 0.20x | 3/1 | 3/1 |
| `resto.n3` | ok | ok | 11.28 | 16.69 | 0.68x | 71/66 | 71/66 |
| `ruby-runge-workshop.n3` | ok | ok | 55.23 | 34.05 | 1.62x | 33/13 | 33/13 |
| `rule-matching.n3` | ok | ok | 1.22 | 7.86 | 0.15x | 1/1 | 1/1 |
| `saffron-slopeworks.n3` | ok | ok | 31.28 | 28.14 | 1.11x | 39/21 | 39/21 |
| `schema-foaf-mapping.n3` | ok | ok | 1.65 | 4.59 | 0.36x | 8/4 | 8/4 |
| `school-placement-audit.n3` | ok | ok | 9.07 | 14.76 | 0.61x | 39/12 | 39/12 |
| `self-referential.n3` | ok | ok | 2.10 | 7.05 | 0.30x | 4/4 | 4/4 |
| `shacl-conforms.n3` | ok | ok | 692.90 | 38.70 | 17.91x | 2/2 | 2/2 |
| `similar.n3` | ok | ok | 1.22 | 4.91 | 0.25x | 3/1 | 3/1 |
| `smoke-arithmetic.n3` | ok | ok | 5.31 | 10.57 | 0.50x | 5/2 | 5/2 |
| `snaf.n3` | ok | ok | 1.31 | 6.73 | 0.19x | 3/1 | 3/1 |
| `socrates.n3` | ok | ok | 1.30 | 5.10 | 0.25x | 3/1 | 3/1 |
| `spectral-week.n3` | ok | ok | 4.08 | 10.84 | 0.38x | 32/14 | 32/14 |
| `sqrt2-cauchy.n3` | ok | ok | 57.50 | 37.43 | 1.54x | 61/53 | 61/53 |
| `sqrt2-computable-real.n3` | ok | ok | 75.58 | 41.05 | 1.84x | 120/115 | 120/115 |
| `sqrt2-dedekind.n3` | ok | ok | 22.18 | 35.44 | 0.63x | 110/104 | 110/104 |
| `string-builtins-tests.n3` | ok | ok | 4.22 | 9.32 | 0.45x | 21/21 | 21/21 |
| `sudoku.n3` | ok | ok | 15.46 | 18.50 | 0.84x | 46/43 | 46/43 |
| `superdense-coding.n3` | ok | ok | 41.87 | 18.25 | 2.29x | 21/4 | 21/4 |
| `tabling-query-cache-stress.n3` | ok | ok | 22.80 | 25.92 | 0.88x | 120/0 | 120/0 |
| `takeuchi.n3` | ok | ok | 10,741.42 | 846.97 | 12.68x | 1004/1003 | 1004/1003 |
| `tgate-approx.n3` | ok | ok | 258.36 | 78.31 | 3.30x | 385/377 | 385/377 |
| `theory-diff.n3` | ok | ok | 9.58 | 11.26 | 0.85x | 6/4 | 6/4 |
| `time.n3` | ok | ok | 1.63 | 7.10 | 0.23x | 7/6 | 7/6 |
| `topaz-markov-mill.n3` | ok | ok | 25.01 | 18.28 | 1.37x | 71/51 | 71/51 |
| `traffic-skos-aggregate.n3` | ok | ok | 18.13 | 21.64 | 0.84x | 249/137 | 249/137 |
| `transcendental-families.n3` | ok | ok | 16.01 | 29.05 | 0.55x | 213/91 | 213/91 |
| `transcendental-lab.n3` | ok | ok | 8.62 | 21.43 | 0.40x | 131/50 | 131/50 |
| `transcendental-names-and-families.n3` | ok | ok | 10.46 | 21.38 | 0.49x | 152/30 | 152/30 |
| `transcendental-numbers.n3` | ok | ok | 6.44 | 16.27 | 0.40x | 107/21 | 107/21 |
| `transcendental-numbers-stretched.n3` | ok | ok | 15.87 | 30.54 | 0.52x | 250/122 | 250/122 |
| `transistor-switch.n3` | ok | ok | 12.87 | 18.82 | 0.68x | 75/48 | 75/48 |
| `transitive-closure.n3` | ok | ok | 2,449.33 | 383.70 | 6.38x | 2701/2697 | 2701/2697 |
| `triple-terms.n3` | ok | ok | 5.70 | 8.93 | 0.64x | 5/1 | 5/1 |
| `trust-flow-provenance-threshold.n3` | ok | ok | 2.98 | 8.67 | 0.34x | 23/6 | 23/6 |
| `tunnel-junction-wake-switch-becoming.n3` | ok | ok | 5.90 | 9.67 | 0.61x | 45/23 | 45/23 |
| `turing.n3` | ok | ok | 19.61 | 21.59 | 0.91x | 7/0 | 7/0 |
| `two-two-four.n3` | ok | ok | 73.82 | 30.96 | 2.38x | 87/84 | 87/84 |
| `ultramarine-simpson-forge.n3` | ok | ok | 15.62 | 22.31 | 0.70x | 78/61 | 78/61 |
| `vieta-expand.n3` | ok | ok | 13.63 | 18.59 | 0.73x | 6/2 | 6/2 |
| `void.n3` | ok | ok | 3.48 | 9.41 | 0.37x | 81/6 | 81/6 |
| `vulnerability-impact.n3` | ok | ok | 3.89 | 9.85 | 0.39x | 38/20 | 38/20 |
| `whitehead-becoming.n3` | ok | ok | 4.70 | 8.24 | 0.57x | 64/40 | 64/40 |
| `wind-turbine.n3` | ok | ok | 6.03 | 11.52 | 0.52x | 25/16 | 25/16 |
| `witch.n3` | ok | ok | 1.83 | 5.32 | 0.34x | 9/6 | 9/6 |
| `zebra.n3` | ok | ok | 837.23 | 77.55 | 10.80x | 1/1 | 1/1 |

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

Run a specific scoped-builtin example manually:

```bash
pyling --builtin examples/builtin/sudoku.py ../eyeling/examples/sudoku.n3
pyling --builtin examples/builtin/queens.py ../eyeling/examples/queens.n3
```

Use `--report-dir=performance-reports/<name>` to save JSON, CSV, and Markdown reports. The `performance-reports/` directory is ignored by Git.
