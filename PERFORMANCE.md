# Performance report

This report answers two separate questions:

1. Did each benchmark process finish?
2. Did each reasoner produce the expected result, making its timing comparable?

Those questions were previously conflated. In the benchmark harness, `ok`
means that a process returned without an exception. It does not mean that a
conformance assertion was checked.

## Result

The shared example benchmarks were rerun locally on 2026-07-23.

- Eyeling's own runner passed all 224 runnable examples against their golden
  outputs.
- In the full three-reasoner survey, pyling and Eyeling returned normally with
  matching fact counts on 125 examples; FuXi never reported a derived fact.
- pyling and Eyeling completed all four examples and reported identical fact
  and derived-fact counts.
- FuXi completed two of the three attempted examples as a process, but reported
  no derived facts for either. It failed to load the Fibonacci example.
- The saved 273-case MobiBench run completed every pyling and FuXi invocation,
  but it did not check each expected OWL conclusion. It is an execution and
  workload profile, not a conformance result.

Therefore, the answer to "did the test run successfully?" is:

- **Yes for pyling versus Eyeling on the shared examples:** both execution and
  the reported output counts agree.
- **No for a like-for-like FuXi comparison on those examples:** FuXi either did
  different work or rejected the input.
- **Yes for process completion on the recorded MobiBench run, but not proven
  for semantic correctness:** no expected entailments were asserted.

## Full Eyeling example suite

Eyeling 2.35.1 contains 224 runnable files directly under `examples/`. The
additional `.n3` files under `examples/output/` and `examples/proof/` are golden
results, not additional programs, and were not benchmarked as inputs. The run
included all 20 matching TriG sidecars and loaded both JavaScript custom
built-ins for Eyeling. pyling and FuXi have no adapter for those JavaScript
modules.

First, Eyeling's own golden-output test was run:

```bash
cd ../eyeling
npm run test:examples
```

All 224 examples passed in 25.70 seconds. That is the semantic baseline and
includes the expected inference-fuse exits from `fuse.n3` and `liar.n3`.

The three-reasoner survey then ran one measured iteration per case, with no
warmup and a 10-second timeout:

| Reasoner | Normal returns | Other outcomes | Cases reporting derived facts |
|---|---:|---|---:|
| Eyeling | 222 | 2 expected inference-fuse exits | 209 |
| pyling | 192 | 20 syntax errors, 7 fuse exits, 5 timeouts | 153 |
| FuXi | 165 | 35 loader errors, 22 syntax errors, 2 timeouts | 0 |

Only `fuse.n3` explicitly expected one of pyling's seven fuse exits. Conversely,
pyling returned normally for `liar.n3`, where the Eyeling golden test expects a
fuse. A normal return should therefore not be read as a passed example.

FuXi reported zero derived facts in every normally returning case. Its timings
do not represent the same work as Eyeling and pyling, so there is no valid
three-way speed ranking from this suite.

pyling and Eyeling both returned normally with matching fact and derived-fact
counts in 125 cases. After excluding `queens.n3`, which uses an Eyeling-only
JavaScript built-in but happens to have matching top-level counts, 124 cases
remain as the most defensible timing cohort:

| Comparison over 124 cases | Result |
|---|---:|
| Cases where pyling was faster | 94 |
| Cases where Eyeling was faster | 30 |
| Median pyling time | 6.27 ms |
| Median Eyeling time | 17.64 ms |
| Median per-case pyling/Eyeling ratio | 0.446 |

The median per-case ratio means pyling was about 2.24 times faster for the
typical case in this cohort. Most examples are small, however. Several larger
or recursive examples favor Eyeling:

| Example | pyling | Eyeling | Faster engine |
|---|---:|---:|---|
| Socrates | 0.53 ms | 4.80 ms | pyling, 9.1x |
| Fibonacci | 2,597.37 ms | 1,451.61 ms | Eyeling, 1.79x |
| Deep taxonomy, 10,000 levels | 1,318.27 ms | 301.37 ms | Eyeling, 4.37x |
| Transitive closure | 3,871.33 ms | 413.03 ms | Eyeling, 9.37x |
| EV roundtrip planner | 2,183.09 ms | 56.93 ms | Eyeling, 38.35x |
| Deep taxonomy, 100,000 levels | timeout | 2,436.58 ms | not directly comparable |

Matching counts are weaker than comparing normalized complete output. These
124 rows are useful performance evidence, not a claim that pyling passed 124
of Eyeling's golden tests.

## pyling versus Eyeling

The earlier focused run below uses three measured iterations after one warmup,
making it less broad but less sensitive to a single sample. Lower is better.

| Example | pyling | Eyeling | pyling relative to Eyeling | Output check |
|---|---:|---:|---:|---|
| Socrates | 0.26 ms | 5.40 ms | 20.8x faster | 3 facts, 1 derived |
| Fibonacci | 2,306.78 ms | 1,210.57 ms | 1.91x slower | 1 fact, 1 derived |
| Deep taxonomy, 10,000 levels | 1,240.17 ms | 265.78 ms | 4.67x slower | 30,011 facts, 30,009 derived |
| Deep taxonomy, 100,000 levels | 14,548.05 ms | 2,959.19 ms | 4.92x slower | 300,011 facts, 300,009 derived |

The practical conclusion is that pyling has lower fixed overhead on the tiny
Socrates input, but Eyeling scales substantially better on the recursive and
deep-taxonomy examples. On the 100,000-level taxonomy, Eyeling is about five
times faster while producing the same counts.

Matching counts are a useful regression check, but they do not prove that
every emitted term is identical. A future correctness benchmark should
canonicalize and compare complete outputs.

## FuXi

FuXi 2.0.1 was tested through its generic N3 rule loader on the same source
files.

| Example | FuXi time | FuXi result | Comparable timing? |
|---|---:|---|---|
| Socrates | 2.61 ms | Process completed; 0 derived facts instead of 1 | No |
| Fibonacci | n/a | Loader failed on a literal-subject rule | No |
| Deep taxonomy, 10,000 levels | 3,091.65 ms | Process completed; 0 derived facts instead of 30,009 | No |

It would be misleading to call FuXi faster or slower from these rows: it did
not complete the same reasoning task. `ok` in the generated report only records
a clean process exit.

## MobiBench OWL 2 RL profile

The saved run from 2026-07-22 contains 273 MobiBench inputs, one measured
iteration per input, and no warmup.

| Reasoner | Invocations completed | Median ms/case | Cases reporting derived facts | Total reported derived facts |
|---|---:|---:|---:|---:|
| pyling | 273/273 | 85.88 | 273 | 33,402 |
| FuXi | 273/273 | 95.93 | 43 | 221 |

This is not a direct speed comparison. pyling loads an Eyeling-oriented OWL 2
RL N3 ruleset, while FuXi uses its built-in OWL/DLP setup. The very different
derived-fact counts show that the engines are not performing equivalent work.
The harness also does not compare the result with each MobiBench expected
conclusion.

The run does identify pyling performance hotspots. The slowest recorded cases
were:

| Case | pyling time | Derived facts |
|---|---:|---:|
| `rdfbased-xtr-reflection-subclasses` | 133,292.61 ms | 290 |
| `rdfbased-sem-bool-intersection-inst-comp` | 31,885.76 ms | 105 |
| `rdfbased-sem-bool-intersection-inst-expr` | 31,301.35 ms | 106 |
| `rdfbased-sem-bool-intersection-term` | 30,417.15 ms | 104 |
| `rdfbased-sem-key-def` | 3,042.21 ms | 116 |

These cases point to broad joins over RDF lists, subclass reflection,
intersections, and keys as the most useful optimization targets.

## Method

The local comparison used:

- pyling commit `e5affe7`
- Eyeling 2.35.1, commit `cb29f46`, loaded from `../eyeling`
- FuXi 2.0.1 on Python 3.13.14
- Python 3.12.3, Node.js 25.9.0
- 12th Gen Intel Core i7-1265U, 30 GiB RAM, Linux 6.8

The timer covers parsing, reasoning, and closure construction. Runtime process
startup and initial module loading occur before the timed region. Eyeling and
FuXi run in fresh subprocesses for each sample. pyling runs in-process for the
focused and MobiBench suites, but in a timed subprocess for the full Eyeling
suite so individual cases cannot stall the survey. These measurements are
suitable for project regression tracking, not as universal cross-language
performance claims.

Reproduce the shared examples with sibling checkouts:

```bash
FUXI_PYTHON=.cache/fuxi-venv/bin/python \
python3 tools/compare_reasoners.py \
  --case=socrates \
  --case=fibonacci \
  --case=deep-taxonomy-10000 \
  --reasoner=pyling,eyeling,fuxi \
  --eyeling-path=../eyeling \
  --iterations=3 \
  --warmup=1 \
  --max-iterations=100000 \
  --timeout=600 \
  --report-dir=performance-reports/examples
```

The 100,000-level case was measured separately without FuXi:

```bash
python3 tools/compare_reasoners.py \
  --case=deep-taxonomy-100000 \
  --reasoner=pyling,eyeling \
  --eyeling-path=../eyeling \
  --iterations=3 \
  --warmup=1 \
  --max-iterations=100000 \
  --timeout=600 \
  --report-dir=performance-reports/deep-100000
```

FuXi can be installed lazily when Python 3.13 is available by omitting
`FUXI_PYTHON`. Use `--list` to inspect discovered reasoners and cases without
installing anything.

Run the OWL profile separately:

```bash
npm run perf:mobibench
```

Reproduce the full Eyeling example survey:

```bash
EYELING_PATH=../eyeling npm run perf:eyeling-examples
```

Generated JSON, CSV, and Markdown reports are written under
`performance-reports/` and are intentionally ignored by Git.
