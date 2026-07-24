# Performance comparison

Benchmarks were regenerated on 2026-07-24 from the current Pyling working tree. The report is intentionally practical: which cases completed, whether selected output counts matched, and where Pyling is faster or slower than Eyeling and other Python reasoners.

## Test environment

| Component | Version |
|---|---|
| pyling | 0.1.4 working tree |
| Eyeling | 2.35.3, commit `0a9270e` |
| FuXi | 2.0.1 in `.cache/fuxi-venv` |
| owlrl | 7.6.2 |
| RDFLib | 7.6.0 |
| Python | 3.12.3 |
| Node.js | 25.9.0 |
| Host | 12th Gen Intel Core i7-1265U, 12 logical CPUs, Linux 6.8 |

Timers include parsing, reasoning, and closure construction. Process and module startup happen before the timed region. Unless noted otherwise, each Eyeling example row is one measured iteration with no warmup, so small timing differences should not be overinterpreted.

## Eyeling example suite

All 225 top-level N3 examples from the local Eyeling checkout were run once. Matching TriG inputs were included where present. Example-specific builtins are loaded explicitly for both engines: Eyeling uses `../eyeling/examples/builtin/*.js`, and Pyling uses `examples/builtin/*.py` for the matching example name. The HTTP-dependent cases were rerun with network access and override the sandboxed broad-sweep rows.

### Completion and counts

| Outcome | Cases |
|---|---:|
| Same normal or inference-fuse outcome | 225/225 |
| Both reasoners returned normally | 223 |
| Both raised the expected inference fuse | 2 |
| Exact selected-output count after HTTP reruns | 222 |
| Remaining count differences | 1 |

The inference-fuse cases are `fuse.n3`, `liar.n3`; their nonzero exits are expected results.
The remaining count difference is `kronecker.n3`. It derives `77/77` in Pyling and `69/69` in Eyeling on this run, so it should be treated as an open semantic-parity item rather than a performance-only difference.

For examples that use `log:query`, the comparison counts selected query output rather than implementation-internal saturated stores.

### Runtime summary

| Metric over 222 exact-count normal cases | Pyling | Eyeling |
|---|---:|---:|
| Median per case | 9.84 ms | 18.41 ms |
| Arithmetic mean | 268.97 ms | 75.03 ms |
| Total measured time | 59.712 s | 16.657 s |
| Slowest normal case | `deep-taxonomy-100000.n3` (15.191 s) | `deep-taxonomy-100000.n3` (2.473 s) |

Among the 222 exact-count normal cases, Pyling was faster on 158 cases and Eyeling was faster on 64. The median Pyling/Eyeling ratio was 0.572, so Pyling is about 1.75x faster on the typical exact-count example. The total runtime still favors Eyeling because large recursive/search programs dominate the aggregate.

| Representative exact-count example | Pyling | Eyeling | Interpretation |
|---|---:|---:|---|
| Socrates | 1.16 ms | 6.85 ms | Pyling 5.9x faster |
| Sudoku | 16.97 ms | 21.73 ms | Pyling 1.3x faster |
| Queens | 759.05 ms | 291.80 ms | Pyling 2.6x slower |
| Fibonacci | 3,068.98 ms | 1,352.96 ms | Pyling 2.3x slower |
| Deep Taxonomy 100000 | 15,191.30 ms | 2,472.82 ms | Pyling 6.1x slower |
| Goldbach 1000 | 2,876.05 ms | 1,462.88 ms | Pyling 2.0x slower |
| Path Discovery | 3,176.62 ms | 854.72 ms | Pyling 3.7x slower |
| Takeuchi | 7,312.45 ms | 957.46 ms | Pyling 7.6x slower |
| Collatz 1000 | 1,523.55 ms | 539.86 ms | Pyling 2.8x slower |
| Kaprekar 6174 | 8,451.44 ms | 2,059.77 ms | Pyling 4.1x slower |
| Relational Cube Lookup | 3,052.80 ms | 90.30 ms | Pyling 33.8x slower |

### Clearly slow cases

| Case | Pyling | Eyeling | Pyling/Eyeling |
|---|---:|---:|---:|
| `relational-cube-lookup.n3` | 3,052.80 ms | 90.30 ms | 33.8x |
| `shacl-conforms.n3` | 791.23 ms | 36.17 ms | 21.9x |
| `reaching-out.n3` | 121.03 ms | 6.75 ms | 17.9x |
| `rdf-message-cold-chain-recall.n3` | 787.50 ms | 75.12 ms | 10.5x |
| `takeuchi.n3` | 7,312.45 ms | 957.46 ms | 7.6x |
| `deep-taxonomy-100000.n3` | 15,191.30 ms | 2,472.82 ms | 6.1x |
| `dining-philosophers.n3` | 793.33 ms | 130.33 ms | 6.1x |
| `doctor-advice-work-conflict.n3` | 180.74 ms | 30.86 ms | 5.9x |
| `transitive-closure.n3` | 2,100.03 ms | 394.63 ms | 5.3x |
| `rdf-message-ldes-incremental.n3` | 351.77 ms | 72.45 ms | 4.9x |
| `deep-taxonomy-10000.n3` | 1,312.03 ms | 271.23 ms | 4.8x |
| `odrl-policy-evaluation-snaf.n3` | 121.30 ms | 26.62 ms | 4.6x |
| `kaprekar-6174.n3` | 8,451.44 ms | 2,059.77 ms | 4.1x |
| `path-discovery.n3` | 3,176.62 ms | 854.72 ms | 3.7x |
| `genetic-algorithm.n3` | 1,143.64 ms | 315.55 ms | 3.6x |

The largest remaining gaps are concentrated in broad data closure, relational list lookups, RDF Message scope handling, and recursive arithmetic/search. The newest trail-local substitutions and builtin fast paths reduce Python interpreter recursion overhead, but Eyeling still benefits from a deeper all-internal integer term representation and array-backed solver state. The regenerated relational-cube row shows a clear regression that should be investigated separately because that workload previously benefited from the list-component index.

## Focused comparison with FuXi

These three examples were measured three times after one warmup. FuXi is included as a Python reference point, but it does not perform the same work on several general N3 programs.

| Example | Pyling | Eyeling | FuXi | Output |
|---|---:|---:|---:|---|
| Socrates | 1.35 ms | 4.95 ms | 2.36 ms | Pyling/Eyeling derive 1; FuXi derives 0 |
| Fibonacci | 2,803.99 ms | 1,221.88 ms | failed | FuXi rejects the literal-subject rule |
| Deep taxonomy, 10,000 | 1,479.63 ms | 321.93 ms | 3,229.27 ms | Pyling/Eyeling derive 30,009; FuXi derives 0 |

## Relational cube lookup

`relational-cube-lookup.n3` performs 2,000 two-key lookups over 3,375 facts represented as three-element lists. This regenerated run shows Pyling is again much slower than Eyeling here, so the list-component indexing path needs follow-up profiling.

| Reasoner | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Pyling | 2.869 s | 2.832 s | 2.953 s |
| Eyeling | 0.084 s | 0.080 s | 0.089 s |

## MobiBench OWL 2 RL

The 273 positive-entailment and inconsistency inputs in the MobiBench OWL 2 RL archive were run once with Pyling plus the Eyeling OWL 2 RL N3 rules, FuXi with its built-in OWL/DLP setup, and `owlrl` with its built-in `OWLRL_Semantics`.

| Reasoner | Completed | Median per case | Mean per case | Total |
|---|---:|---:|---:|---:|
| `owlrl` | 273/273 | 16.38 ms | 16.71 ms | 4.563 s |
| FuXi | 273/273 | 94.83 ms | 94.69 ms | 25.851 s |
| Pyling | 273/273 | 246.37 ms | 256.54 ms | 70.035 s |

`owlrl` remains the clear performance choice when an application only needs its fixed OWL 2 RL closure. Pyling is slower here because it executes an external, inspectable N3 ruleset through a general N3 engine. That flexibility is useful when OWL rules need to be mixed with broader N3 logic, but it is not free.

## Full Eyeling Example Results

`Py/Ey ratio` is lower-is-better for Pyling. The `facts/derived` columns show final fact and derived counts for ordinary closure mode, and selected query-output counts for examples that use `log:query`. HTTP rows use the network-enabled rerun.

| Case | Pyling status | Eyeling status | Pyling ms | Eyeling ms | Py/Ey ratio | Py facts/derived | Ey facts/derived |
|---|---|---|---:|---:|---:|---:|---:|
| `ackermann.n3` | ok | ok | 39.89 | 20.87 | 1.91x | 1/1 | 1/1 |
| `act-alarm-bit-interoperability.n3` | ok | ok | 5.70 | 13.43 | 0.42x | 70/53 | 70/53 |
| `act-barley-seed-lineage.n3` | ok | ok | 14.65 | 15.64 | 0.94x | 234/60 | 234/60 |
| `act-docking-abort.n3` | ok | ok | 119.14 | 52.21 | 2.28x | 1024/1003 | 1024/1003 |
| `act-gravity-mediator-witness.n3` | ok | ok | 6.90 | 13.44 | 0.51x | 62/31 | 62/31 |
| `act-isolation-breach.n3` | ok | ok | 159.11 | 66.98 | 2.38x | 1132/1108 | 1132/1108 |
| `act-photosynthetic-exciton-transfer.n3` | ok | ok | 5.63 | 9.57 | 0.59x | 46/21 | 46/21 |
| `act-sensor-memory-reset.n3` | ok | ok | 4.87 | 13.71 | 0.36x | 38/22 | 38/22 |
| `act-tunnel-junction-wake-switch.n3` | ok | ok | 5.61 | 9.46 | 0.59x | 45/23 | 45/23 |
| `act-yeast-self-reproduction.n3` | ok | ok | 6.80 | 10.17 | 0.67x | 63/33 | 63/33 |
| `age.n3` | ok | ok | 1.42 | 7.40 | 0.19x | 2/1 | 2/1 |
| `alignment-demo.n3` | ok | ok | 3.36 | 8.11 | 0.41x | 46/32 | 46/32 |
| `allen-interval-calculus.n3` | ok | ok | 126.55 | 83.00 | 1.52x | 176/154 | 176/154 |
| `alma-rdf-messages.n3` | ok | ok | 4.19 | 6.28 | 0.67x | 0/0 | 0/0 |
| `annotation.n3` | ok | ok | 5.00 | 8.64 | 0.58x | 1/1 | 1/1 |
| `auroracare.n3` | ok | ok | 11.28 | 14.36 | 0.79x | 227/114 | 227/114 |
| `backward.n3` | ok | ok | 1.15 | 6.79 | 0.17x | 1/1 | 1/1 |
| `backward-recursion.n3` | ok | ok | 5.56 | 8.69 | 0.64x | 1/1 | 1/1 |
| `barley-seed-becoming.n3` | ok | ok | 14.51 | 16.63 | 0.87x | 233/60 | 233/60 |
| `basic-monadic.n3` | ok | ok | 210.69 | 87.48 | 2.41x | 10005/5 | 10005/5 |
| `bayes-diagnosis.n3` | ok | ok | 11.27 | 24.02 | 0.47x | 99/18 | 99/18 |
| `bayes-therapy.n3` | ok | ok | 19.66 | 28.18 | 0.70x | 122/23 | 122/23 |
| `bmi.n3` | ok | ok | 9.42 | 19.74 | 0.48x | 34/30 | 34/30 |
| `builtin-coverage.n3` | ok | ok | 8.57 | 11.05 | 0.78x | 1/1 | 1/1 |
| `calidor.n3` | ok | ok | 15.57 | 23.10 | 0.67x | 149/45 | 149/45 |
| `cat-koko.n3` | ok | ok | 1.80 | 7.72 | 0.23x | 6/5 | 6/5 |
| `cobalt-kepler-kitchen.n3` | ok | ok | 12.24 | 24.42 | 0.50x | 63/46 | 63/46 |
| `collatz-1000.n3` | ok | ok | 1,523.55 | 539.86 | 2.82x | 1000/1000 | 1000/1000 |
| `collection.n3` | ok | ok | 4.70 | 7.66 | 0.61x | 1/1 | 1/1 |
| `complex.n3` | ok | ok | 7.16 | 18.60 | 0.38x | 1/1 | 1/1 |
| `complex-matrix-stability.n3` | ok | ok | 32.20 | 37.10 | 0.87x | 48/7 | 48/7 |
| `composition-of-injective-functions-is-injective.n3` | ok | ok | 6.98 | 16.19 | 0.43x | 2/2 | 2/2 |
| `constructor-theory-becoming.n3` | ok | ok | 3.72 | 7.89 | 0.47x | 59/16 | 59/16 |
| `context-association.n3` | ok | ok | 8.73 | 20.36 | 0.43x | 11/8 | 11/8 |
| `context-schema-audit.n3` | ok | ok | 5.18 | 12.65 | 0.41x | 20/13 | 20/13 |
| `control-system.n3` | ok | ok | 8.13 | 13.91 | 0.58x | 35/24 | 35/24 |
| `control-system-becoming.n3` | ok | ok | 4.24 | 8.63 | 0.49x | 70/33 | 70/33 |
| `cranberry-calculus.n3` | ok | ok | 7.62 | 24.47 | 0.31x | 29/19 | 29/19 |
| `crypto-builtins-tests.n3` | ok | ok | 1.49 | 6.62 | 0.22x | 4/4 | 4/4 |
| `decimal-ebike-motor-thermal-envelope.n3` | ok | ok | 50.14 | 34.10 | 1.47x | 22/22 | 22/22 |
| `decimal-transcendental-servo-envelope.n3` | ok | ok | 23.71 | 27.21 | 0.87x | 26/26 | 26/26 |
| `deep-taxonomy-10.n3` | ok | ok | 3.74 | 8.53 | 0.44x | 41/39 | 41/39 |
| `deep-taxonomy-100.n3` | ok | ok | 14.82 | 14.12 | 1.05x | 311/309 | 311/309 |
| `deep-taxonomy-1000.n3` | ok | ok | 129.86 | 47.04 | 2.76x | 3011/3009 | 3011/3009 |
| `deep-taxonomy-10000.n3` | ok | ok | 1,312.03 | 271.23 | 4.84x | 30011/30009 | 30011/30009 |
| `deep-taxonomy-100000.n3` | ok | ok | 15,191.30 | 2,472.82 | 6.14x | 300011/300009 | 300011/300009 |
| `delfour.n3` | ok | ok | 15.49 | 23.03 | 0.67x | 127/36 | 127/36 |
| `derived-backward-rule.n3` | ok | ok | 1.51 | 10.75 | 0.14x | 4/2 | 4/2 |
| `derived-backward-rule-2.n3` | ok | ok | 1.83 | 6.78 | 0.27x | 4/4 | 4/4 |
| `derived-rule.n3` | ok | ok | 1.28 | 5.11 | 0.25x | 4/2 | 4/2 |
| `developmental-genetics-becoming.n3` | ok | ok | 5.19 | 10.27 | 0.51x | 65/30 | 65/30 |
| `digital-product-passport.n3` | ok | ok | 8.07 | 18.64 | 0.43x | 120/7 | 120/7 |
| `dijkstra.n3` | ok | ok | 24.68 | 34.63 | 0.71x | 25/16 | 25/16 |
| `dijkstra-risk-path.n3` | ok | ok | 8.23 | 14.05 | 0.59x | 27/5 | 27/5 |
| `dining-philosophers.n3` | ok | ok | 793.33 | 130.33 | 6.09x | 1103/806 | 1103/806 |
| `doctor-advice-work-conflict.n3` | ok | ok | 180.74 | 30.86 | 5.86x | 12/11 | 12/11 |
| `dog.n3` | ok | ok | 3.43 | 12.87 | 0.27x | 8/1 | 8/1 |
| `dpv-odrl-purpose-mapping.n3` | ok | ok | 3.92 | 7.57 | 0.52x | 29/18 | 29/18 |
| `drone-corridor-planner.n3` | ok | ok | 73.28 | 55.53 | 1.32x | 21/17 | 21/17 |
| `e-computable-real.n3` | ok | ok | 107.18 | 96.70 | 1.11x | 90/90 | 90/90 |
| `easter.n3` | ok | ok | 37.15 | 74.97 | 0.50x | 473/325 | 473/325 |
| `eco-route-insight.n3` | ok | ok | 17.02 | 21.55 | 0.79x | 40/6 | 40/6 |
| `engineering-becoming.n3` | ok | ok | 7.98 | 18.46 | 0.43x | 55/24 | 55/24 |
| `equals.n3` | ok | ok | 0.35 | 6.85 | 0.05x | 2/1 | 2/1 |
| `equivalence-classes-overlap-implies-same-class.n3` | ok | ok | 11.44 | 23.89 | 0.48x | 18/18 | 18/18 |
| `ershov-mixed-computation.n3` | ok | ok | 4.23 | 11.27 | 0.37x | 5/2 | 5/2 |
| `euler-identity.n3` | ok | ok | 3.88 | 16.21 | 0.24x | 6/6 | 6/6 |
| `ev-roundtrip-planner.n3` | ok | ok | 74.54 | 61.85 | 1.21x | 12/8 | 12/8 |
| `eventual-interoperability-interaction-patterns.n3` | ok | ok | 97.17 | 29.45 | 3.30x | 128/41 | 128/41 |
| `existential-rule.n3` | ok | ok | 1.36 | 6.00 | 0.23x | 4/2 | 4/2 |
| `expression-eval.n3` | ok | ok | 3.15 | 10.18 | 0.31x | 18/1 | 18/1 |
| `faltings-genus2-finiteness.n3` | ok | ok | 2.76 | 9.05 | 0.30x | 33/3 | 33/3 |
| `family-cousins.n3` | ok | ok | 6.07 | 11.65 | 0.52x | 40/25 | 40/25 |
| `fastpow.n3` | ok | ok | 22.77 | 16.22 | 1.40x | 1/1 | 1/1 |
| `fft32-numeric.n3` | ok | ok | 223.71 | 138.04 | 1.62x | 6/6 | 6/6 |
| `fft8-numeric.n3` | ok | ok | 41.85 | 24.50 | 1.71x | 1/1 | 1/1 |
| `fft8-symbolic.n3` | ok | ok | 28.19 | 21.15 | 1.33x | 1/1 | 1/1 |
| `fibonacci.n3` | ok | ok | 3,068.98 | 1,352.96 | 2.27x | 1/1 | 1/1 |
| `flandor.n3` | ok | ok | 19.91 | 30.88 | 0.64x | 171/45 | 171/45 |
| `floating-point-first-ema-tracker.n3` | ok | ok | 79.56 | 47.91 | 1.66x | 50/50 | 50/50 |
| `floating-point-first-rc-discharge.n3` | ok | ok | 52.80 | 37.30 | 1.42x | 38/38 | 38/38 |
| `floating-point-first-servo-envelope.n3` | ok | ok | 28.99 | 31.31 | 0.93x | 26/26 | 26/26 |
| `floating-point-first-thermal-cooling.n3` | ok | ok | 49.27 | 37.54 | 1.31x | 38/38 | 38/38 |
| `french-cities.n3` | ok | ok | 8.26 | 13.45 | 0.61x | 57/39 | 57/39 |
| `fundamental-theorem-arithmetic.n3` | ok | ok | 1,040.64 | 290.72 | 3.58x | 24/18 | 24/18 |
| `fuse.n3` | failed | failed |  |  |  |  |  |
| `gd-step-certified.n3` | ok | ok | 70.29 | 46.72 | 1.50x | 79/79 | 79/79 |
| `genetic-algorithm.n3` | ok | ok | 1,143.64 | 315.55 | 3.62x | 2/2 | 2/2 |
| `genetic-algorithm-knapsack.n3` | ok | ok | 655.17 | 275.46 | 2.38x | 2/2 | 2/2 |
| `genetic-knapsack-selection.n3` | ok | ok | 9.03 | 16.99 | 0.53x | 18/3 | 18/3 |
| `get-uuid.n3` | ok | ok | 3.79 | 12.48 | 0.30x | 4/2 | 4/2 |
| `godel-incompleteness.n3` | ok | ok | 3.03 | 9.08 | 0.33x | 50/4 | 50/4 |
| `godel-template.n3` | ok | ok | 7.51 | 19.81 | 0.38x | 38/6 | 38/6 |
| `goldbach-1000.n3` | ok | ok | 2,876.05 | 1,462.88 | 1.97x | 668/667 | 668/667 |
| `good-cobbler.n3` | ok | ok | 0.55 | 4.23 | 0.13x | 2/1 | 2/1 |
| `gps.n3` | ok | ok | 9.39 | 17.90 | 0.52x | 18/13 | 18/13 |
| `gray-code-counter.n3` | ok | ok | 8.56 | 15.74 | 0.54x | 11/1 | 11/1 |
| `greatest-lower-bound-uniqueness.n3` | ok | ok | 4.83 | 16.62 | 0.29x | 2/2 | 2/2 |
| `group-inverse-uniqueness.n3` | ok | ok | 6.81 | 18.26 | 0.37x | 2/2 | 2/2 |
| `hadamard-approx.n3` | ok | ok | 236.88 | 111.38 | 2.13x | 441/441 | 441/441 |
| `hanoi.n3` | ok | ok | 2.42 | 9.04 | 0.27x | 1/1 | 1/1 |
| `harborsmr.n3` | ok | ok | 7.45 | 17.79 | 0.42x | 68/14 | 68/14 |
| `high-trust-rdf-bloom-envelope.n3` | ok | ok | 6.19 | 18.19 | 0.34x | 4/4 | 4/4 |
| `high-trust-rdf-bloom-tamper-contrast.n3` | ok | ok | 11.04 | 22.67 | 0.49x | 19/19 | 19/19 |
| `ill-formed-literals.n3` | ok | ok | 44.43 | 43.71 | 1.02x | 24/24 | 24/24 |
| `integer-first-control-tank-level.n3` | ok | ok | 71.46 | 52.30 | 1.37x | 68/68 | 68/68 |
| `integer-first-sqrt2-mediants.n3` | ok | ok | 36.74 | 39.70 | 0.93x | 54/54 | 54/54 |
| `interop-demo.n3` | ok | ok | 5.58 | 14.74 | 0.38x | 41/27 | 41/27 |
| `jade-eigen-loom.n3` | ok | ok | 22.37 | 23.65 | 0.95x | 79/57 | 79/57 |
| `jsonterm.n3` | ok | ok | 1.57 | 6.02 | 0.26x | 6/1 | 6/1 |
| `jsonterm-advanced.n3` | ok | ok | 3.31 | 7.61 | 0.43x | 27/6 | 27/6 |
| `kaprekar-6174.n3` | ok | ok | 8,451.44 | 2,059.77 | 4.10x | 9990/9990 | 9990/9990 |
| `knowledge-engineering-alignment-flow.n3` | ok | ok | 4.24 | 8.04 | 0.53x | 33/19 | 33/19 |
| `kronecker.n3` | ok | ok | 6.55 | 19.69 | 0.33x | 77/77 | 69/69 |
| `liar.n3` | failed | failed |  |  |  |  |  |
| `light-eaters.n3` | ok | ok | 3.52 | 10.42 | 0.34x | 30/13 | 30/13 |
| `list-builtins-tests.n3` | ok | ok | 3.20 | 7.97 | 0.40x | 11/11 | 11/11 |
| `list-iterate.n3` | ok | ok | 1.98 | 7.74 | 0.26x | 6/5 | 6/5 |
| `list-map.n3` | ok | ok | 1.94 | 7.07 | 0.27x | 8/4 | 8/4 |
| `lldm.n3` | ok | ok | 20.80 | 21.74 | 0.96x | 166/38 | 166/38 |
| `log-collect-all-in.n3` | ok | ok | 2.35 | 8.85 | 0.27x | 6/3 | 6/3 |
| `log-conclusion.n3` | ok | ok | 1.49 | 7.34 | 0.20x | 2/1 | 2/1 |
| `log-for-all-in.n3` | ok | ok | 1.58 | 7.28 | 0.22x | 8/1 | 8/1 |
| `log-not-includes.n3` | ok | ok | 1.62 | 8.19 | 0.20x | 3/3 | 3/3 |
| `log-pan-rt-soe.n3` | ok | ok | 14.87 | 38.96 | 0.38x | 5/4 | 5/4 |
| `log-skolem.n3` | ok | ok | 0.56 | 6.36 | 0.09x | 1/1 | 1/1 |
| `log-uri.n3` | ok | ok | 1.40 | 6.60 | 0.21x | 2/2 | 2/2 |
| `math-builtins-tests.n3` | ok | ok | 14.64 | 14.15 | 1.03x | 200/192 | 200/192 |
| `matiyasevich-pi-fib.n3` | ok | ok | 102.96 | 56.36 | 1.83x | 69/68 | 69/68 |
| `matrix-mechanics.n3` | ok | ok | 12.44 | 14.50 | 0.86x | 43/35 | 43/35 |
| `medior.n3` | ok | ok | 17.15 | 39.58 | 0.43x | 165/45 | 165/45 |
| `meta-rule-audit.n3` | ok | ok | 11.49 | 15.69 | 0.73x | 11/10 | 11/10 |
| `minimal-skos-alignment.n3` | ok | ok | 1.48 | 5.83 | 0.25x | 7/2 | 7/2 |
| `modexp.n3` | ok | ok | 23.51 | 40.54 | 0.58x | 6/6 | 6/6 |
| `monkey.n3` | ok | ok | 1.31 | 4.85 | 0.27x | 4/2 | 4/2 |
| `monoid-identity-uniqueness.n3` | ok | ok | 1.97 | 7.31 | 0.27x | 1/1 | 1/1 |
| `n3-delegation-access.n3` | ok | ok | 9.17 | 19.27 | 0.48x | 12/12 | 12/12 |
| `n3-speaks-for-itself.n3` | ok | ok | 4.45 | 20.55 | 0.22x | 1/1 | 1/1 |
| `odrl-benefits.n3` | ok | ok | 6.29 | 12.21 | 0.52x | 72/11 | 72/11 |
| `odrl-dpv-campaign-audit.n3` | ok | ok | 7.42 | 18.56 | 0.40x | 2/2 | 2/2 |
| `odrl-dpv-conflict-audit.n3` | ok | ok | 11.40 | 24.32 | 0.47x | 2/2 | 2/2 |
| `odrl-dpv-ehds-risk-ranked.n3` | ok | ok | 26.11 | 28.19 | 0.93x | 9/9 | 9/9 |
| `odrl-dpv-fpv-trust-flow.n3` | ok | ok | 5.44 | 11.38 | 0.48x | 56/9 | 56/9 |
| `odrl-dpv-healthcare-risk-ranked.n3` | ok | ok | 32.05 | 28.35 | 1.13x | 140/82 | 140/82 |
| `odrl-dpv-risk-ranked.n3` | ok | ok | 26.19 | 28.36 | 0.92x | 10/10 | 10/10 |
| `odrl-policy-audit.n3` | ok | ok | 5.20 | 17.52 | 0.30x | 2/2 | 2/2 |
| `odrl-policy-evaluation-snaf.n3` | ok | ok | 121.30 | 26.62 | 4.56x | 20/19 | 20/19 |
| `odrl-risk.n3` | ok | ok | 27.03 | 23.36 | 1.16x | 78/60 | 78/60 |
| `odrl-risk-mitigation.n3` | ok | ok | 79.40 | 47.13 | 1.68x | 186/149 | 186/149 |
| `odrl-trust.n3` | ok | ok | 4.40 | 10.85 | 0.41x | 42/2 | 42/2 |
| `ontology-question-generation.n3` | ok | ok | 29.36 | 25.95 | 1.13x | 293/240 | 293/240 |
| `oslo-steps-library-scholarly.n3` | ok | ok | 136.79 | 79.89 | 1.71x | 123/28 | 123/28 |
| `oslo-steps-workflow-composition.n3` | ok | ok | 54.29 | 45.31 | 1.20x | 83/4 | 83/4 |
| `paraconsistent-animals.n3` | ok | ok | 43.96 | 16.03 | 2.74x | 37/36 | 37/36 |
| `parcellocker.n3` | ok | ok | 5.50 | 13.05 | 0.42x | 39/12 | 39/12 |
| `patch.n3` | ok | ok | 3.11 | 9.26 | 0.34x | 4/1 | 4/1 |
| `path-discovery.n3` | ok | ok | 3,176.62 | 854.72 | 3.72x | 96423/3 | 96423/3 |
| `peano.n3` | ok | ok | 14.45 | 27.16 | 0.53x | 1/1 | 1/1 |
| `pi.n3` | ok | ok | 52.11 | 32.28 | 1.61x | 1/1 | 1/1 |
| `pi-computable-real.n3` | ok | ok | 167.29 | 64.40 | 2.60x | 91/91 | 91/91 |
| `pillar.n3` | ok | ok | 1.66 | 5.74 | 0.29x | 3/2 | 3/2 |
| `pn-junction-tunneling.n3` | ok | ok | 13.90 | 22.23 | 0.63x | 106/94 | 106/94 |
| `polygon.n3` | ok | ok | 4.47 | 10.11 | 0.44x | 1/1 | 1/1 |
| `polynomial.n3` | ok | ok | 100.26 | 84.06 | 1.19x | 12/8 | 12/8 |
| `queens.n3` | ok | ok | 759.05 | 291.80 | 2.60x | 2/2 | 2/2 |
| `quoted-head-unquote.n3` | ok | ok | 1.54 | 5.90 | 0.26x | 5/3 | 5/3 |
| `quoted-head-unquote-select.n3` | ok | ok | 1.81 | 6.36 | 0.28x | 8/3 | 8/3 |
| `rc-discharge-envelope.n3` | ok | ok | 8.62 | 16.87 | 0.51x | 20/7 | 20/7 |
| `rdf-dataset.n3` | ok | ok | 6.43 | 9.62 | 0.67x | 1/1 | 1/1 |
| `rdf-list.n3` | ok | ok | 1.52 | 7.63 | 0.20x | 2/1 | 2/1 |
| `rdf-message-cold-chain-recall.n3` | ok | ok | 787.50 | 75.12 | 10.48x | 1018/671 | 1018/671 |
| `rdf-message-flow.n3` | ok | ok | 44.04 | 33.46 | 1.32x | 94/57 | 94/57 |
| `rdf-message-ldes-incremental.n3` | ok | ok | 351.77 | 72.45 | 4.86x | 821/530 | 821/530 |
| `rdf-message-microgrid.n3` | ok | ok | 18.65 | 22.58 | 0.83x | 56/26 | 56/26 |
| `rdf-message-window-repair.n3` | ok | ok | 21.32 | 29.65 | 0.72x | 102/63 | 102/63 |
| `rdf-messages.n3` | ok | ok | 16.31 | 25.92 | 0.63x | 43/20 | 43/20 |
| `reaching-out.n3` | ok | ok | 121.03 | 6.75 | 17.92x | 2/2 | 2/2 |
| `relational-cube-lookup.n3` | ok | ok | 3,052.80 | 90.30 | 33.81x | 2/2 | 2/2 |
| `reordering.n3` | ok | ok | 1.75 | 9.68 | 0.18x | 3/1 | 3/1 |
| `resto.n3` | ok | ok | 13.03 | 34.72 | 0.38x | 71/66 | 71/66 |
| `ruby-runge-workshop.n3` | ok | ok | 44.80 | 31.15 | 1.44x | 33/13 | 33/13 |
| `rule-matching.n3` | ok | ok | 1.16 | 7.83 | 0.15x | 1/1 | 1/1 |
| `saffron-slopeworks.n3` | ok | ok | 27.15 | 22.91 | 1.19x | 39/21 | 39/21 |
| `schema-foaf-mapping.n3` | ok | ok | 1.64 | 5.31 | 0.31x | 8/4 | 8/4 |
| `school-placement-audit.n3` | ok | ok | 10.27 | 15.32 | 0.67x | 39/12 | 39/12 |
| `self-referential.n3` | ok | ok | 1.87 | 7.47 | 0.25x | 4/4 | 4/4 |
| `shacl-conforms.n3` | ok | ok | 791.23 | 36.17 | 21.88x | 2/2 | 2/2 |
| `similar.n3` | ok | ok | 1.13 | 5.30 | 0.21x | 3/1 | 3/1 |
| `smoke-arithmetic.n3` | ok | ok | 5.39 | 11.31 | 0.48x | 5/2 | 5/2 |
| `snaf.n3` | ok | ok | 1.12 | 7.22 | 0.16x | 3/1 | 3/1 |
| `socrates.n3` | ok | ok | 1.16 | 6.85 | 0.17x | 3/1 | 3/1 |
| `spectral-week.n3` | ok | ok | 3.75 | 10.92 | 0.34x | 32/14 | 32/14 |
| `sqrt2-cauchy.n3` | ok | ok | 46.49 | 42.53 | 1.09x | 61/53 | 61/53 |
| `sqrt2-computable-real.n3` | ok | ok | 57.27 | 49.62 | 1.15x | 65/65 | 65/65 |
| `sqrt2-dedekind.n3` | ok | ok | 18.35 | 39.01 | 0.47x | 110/104 | 110/104 |
| `string-builtins-tests.n3` | ok | ok | 4.32 | 9.45 | 0.46x | 21/21 | 21/21 |
| `sudoku.n3` | ok | ok | 16.97 | 21.73 | 0.78x | 46/43 | 46/43 |
| `superdense-coding.n3` | ok | ok | 37.81 | 35.78 | 1.06x | 21/4 | 21/4 |
| `tabling-query-cache-stress.n3` | ok | ok | 21.99 | 30.09 | 0.73x | 24/24 | 24/24 |
| `takeuchi.n3` | ok | ok | 7,312.45 | 957.46 | 7.64x | 1004/1003 | 1004/1003 |
| `tgate-approx.n3` | ok | ok | 165.06 | 83.39 | 1.98x | 336/336 | 336/336 |
| `theory-diff.n3` | ok | ok | 8.28 | 11.41 | 0.73x | 6/4 | 6/4 |
| `time.n3` | ok | ok | 1.74 | 7.62 | 0.23x | 7/6 | 7/6 |
| `topaz-markov-mill.n3` | ok | ok | 17.73 | 22.84 | 0.78x | 71/51 | 71/51 |
| `traffic-skos-aggregate.n3` | ok | ok | 16.24 | 23.62 | 0.69x | 249/137 | 249/137 |
| `transcendental-families.n3` | ok | ok | 15.55 | 27.78 | 0.56x | 136/136 | 136/136 |
| `transcendental-lab.n3` | ok | ok | 8.91 | 29.24 | 0.30x | 57/57 | 57/57 |
| `transcendental-names-and-families.n3` | ok | ok | 10.26 | 22.15 | 0.46x | 116/116 | 116/116 |
| `transcendental-numbers.n3` | ok | ok | 6.72 | 18.36 | 0.37x | 24/24 | 24/24 |
| `transcendental-numbers-stretched.n3` | ok | ok | 14.20 | 31.86 | 0.45x | 1/1 | 1/1 |
| `transistor-switch.n3` | ok | ok | 12.92 | 28.91 | 0.45x | 75/48 | 75/48 |
| `transitive-closure.n3` | ok | ok | 2,100.03 | 394.63 | 5.32x | 2701/2697 | 2701/2697 |
| `triple-terms.n3` | ok | ok | 5.61 | 9.93 | 0.57x | 1/1 | 1/1 |
| `trust-flow-provenance-threshold.n3` | ok | ok | 2.88 | 9.48 | 0.30x | 23/6 | 23/6 |
| `tunnel-junction-wake-switch-becoming.n3` | ok | ok | 6.12 | 9.57 | 0.64x | 45/23 | 45/23 |
| `turing.n3` | ok | ok | 15.82 | 23.93 | 0.66x | 4/4 | 4/4 |
| `two-two-four.n3` | ok | ok | 27.15 | 27.38 | 0.99x | 87/84 | 87/84 |
| `ultramarine-simpson-forge.n3` | ok | ok | 12.87 | 19.17 | 0.67x | 78/61 | 78/61 |
| `vieta-expand.n3` | ok | ok | 9.13 | 15.33 | 0.60x | 6/2 | 6/2 |
| `void.n3` | ok | ok | 3.67 | 8.57 | 0.43x | 81/6 | 81/6 |
| `vulnerability-impact.n3` | ok | ok | 3.30 | 10.68 | 0.31x | 38/20 | 38/20 |
| `whitehead-becoming.n3` | ok | ok | 4.74 | 8.62 | 0.55x | 64/40 | 64/40 |
| `wind-turbine.n3` | ok | ok | 5.85 | 16.73 | 0.35x | 25/16 | 25/16 |
| `witch.n3` | ok | ok | 1.89 | 6.02 | 0.31x | 9/6 | 9/6 |
| `zebra.n3` | ok | ok | 175.79 | 86.16 | 2.04x | 1/1 | 1/1 |
