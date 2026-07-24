#!/usr/bin/env python3
"""Performance comparison harness for pyling, Eyeling, FuXi, and owlrl.

The harness keeps competitors optional: pyling is run in-process, while
Eyeling, FuXi, and owlrl run in subprocesses so callers can point them at
existing installations or checkouts without mutating this project.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_FUXI_VENV = ROOT / ".cache/fuxi-venv"
DEFAULT_FUXI_PACKAGE = "fuxi"
DEFAULT_EYELING_PATH = ROOT.parent / "eyeling"
DEFAULT_MOBIBENCH_URL = "https://william-vw.github.io/mobibench/web/res/owl/conf/testsuite-owl2-rdfbased.zip"
DEFAULT_OWL2RL_RULES_URL = "https://raw.githubusercontent.com/pietercolpaert/rdfjs-inference-engine/refs/heads/main/rules/owl2rl/owl2rl-eyeling.n3"
OWL2RL_SUBSUITE_PREFIX = "testsuite-owl2-rdfbased/subsuites/owl2rl/"


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    label: str
    sources: tuple[str, ...]
    source_paths: tuple[Path, ...] = ()
    fuxi_sources: tuple[str, ...] | None = None
    fuxi_mode: str = "n3"
    owlrl_sources: tuple[str, ...] | None = None
    owlrl_format: str = "turtle"
    rdf: bool = False
    input_format: str | None = None
    suite: str = "examples"
    eyeling_builtin_path: Path | None = None
    pyling_builtin_path: Path | None = None


@dataclass(frozen=True)
class Sample:
    total_ms: float
    facts: int | None = None
    derived: int | None = None
    closure_chars: int | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    case_label: str
    reasoner: str
    status: str
    samples: list[Sample]
    error: str | None = None


@dataclass(frozen=True)
class Reasoner:
    id: str
    label: str
    available: Callable[[], tuple[bool, str | None]]
    run_once: Callable[[BenchmarkCase, argparse.Namespace], Sample]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = discover_cases(args)
    reasoners = discover_reasoners(args)

    if args.list:
        print_inventory(cases, reasoners)
        return 0

    selected_cases = select_cases(cases, args.case)
    selected_reasoners = select_reasoners(reasoners, args.reasoner)
    if not selected_cases:
        raise SystemExit("No benchmark cases selected. Use --list to inspect case ids.")
    if not selected_reasoners:
        raise SystemExit("No reasoners selected. Use --list to inspect reasoner ids.")

    results = run_benchmarks(selected_cases, selected_reasoners, args)
    if args.report_dir:
        write_report_dir(results, args)
    if args.json:
        print_json(results, args)
    elif args.csv:
        print_csv(results)
    elif args.markdown:
        print_markdown(results, args)
    else:
        print_table(results, args)
    if missing_required_reasoners(results, args.require_reasoner):
        return 1
    if args.allow_failures:
        return 0
    return 1 if any(result.status == "failed" for result in results) else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list discovered cases and reasoners")
    parser.add_argument("--suite", action="append", default=[], help="suite to include: examples, eyeling-examples, owl-mobibench, or all")
    parser.add_argument("--case", action="append", default=[], help="case id to run; repeat or comma-separate")
    parser.add_argument("--fixture", action="append", default=[], help="extra fixture path or id=path")
    parser.add_argument("--mobibench-limit", type=int, default=int(os.environ.get("MOBIBENCH_LIMIT", "5")), help="maximum MobiBench OWL2RL cases to load; 0 means all")
    parser.add_argument("--mobibench-cache", default=os.environ.get("MOBIBENCH_OWL2RL_CACHE", str(ROOT / ".cache/mobibench/testsuite-owl2-rdfbased.zip")), help="cached MobiBench OWL2RL archive path")
    parser.add_argument("--mobibench-url", default=os.environ.get("MOBIBENCH_OWL2RL_ARCHIVE_URL", DEFAULT_MOBIBENCH_URL), help="MobiBench OWL2RL archive URL")
    parser.add_argument("--owl2rl-rules", default=os.environ.get("OWL2RL_RULES_PATH"), help="local OWL2RL N3 rules file for pyling")
    parser.add_argument("--owl2rl-rules-url", default=os.environ.get("OWL2RL_RULES_URL", DEFAULT_OWL2RL_RULES_URL), help="OWL2RL N3 rules URL for lazy cache")
    parser.add_argument("--reasoner", action="append", default=[], help="reasoner id to run; repeat or comma-separate")
    parser.add_argument("--iterations", type=int, default=3, help="measured iterations per case/reasoner")
    parser.add_argument("--warmup", type=int, default=1, help="warmup iterations per case/reasoner")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="competitor subprocess timeout in seconds")
    parser.add_argument("--max-iterations", type=int, default=1000, help="pyling max fixpoint iterations")
    parser.add_argument("--include-input-facts", action="store_true", help="include explicit facts in pyling closure output")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--csv", action="store_true", help="print CSV")
    parser.add_argument("--markdown", action="store_true", help="print Markdown report")
    parser.add_argument("--report-dir", help="write report.json, report.csv, and report.md into this directory")
    parser.add_argument("--allow-failures", action="store_true", help="exit 0 even when individual benchmark cases fail")
    parser.add_argument("--require-reasoner", action="append", default=[], help="fail if a reasoner has no non-skipped benchmark result")
    parser.add_argument("--fuxi-python", default=os.environ.get("FUXI_PYTHON", "python3"), help="Python executable with FuXi installed")
    parser.add_argument("--fuxi-pythonpath", default=os.environ.get("FUXI_PYTHONPATH"), help="optional PYTHONPATH for a FuXi checkout")
    parser.add_argument("--fuxi-venv", default=os.environ.get("FUXI_VENV", str(DEFAULT_FUXI_VENV)), help="venv path used for lazy FuXi installation")
    parser.add_argument("--fuxi-package", default=os.environ.get("FUXI_PACKAGE", DEFAULT_FUXI_PACKAGE), help="pip requirement installed into the lazy FuXi venv")
    parser.add_argument("--no-install-fuxi", action="store_true", help="skip lazy FuXi installation and report it as unavailable")
    parser.add_argument("--owlrl-python", default=os.environ.get("OWLRL_PYTHON", sys.executable), help="Python executable with owlrl installed")
    parser.add_argument("--eyeling-node", default=os.environ.get("EYELING_NODE", "node"), help="Node.js executable used for Eyeling")
    parser.add_argument("--eyeling-path", default=os.environ.get("EYELING_PATH", str(DEFAULT_EYELING_PATH)), help="Eyeling package checkout or installation path")
    return parser.parse_args(argv)


def discover_cases(args: argparse.Namespace) -> list[BenchmarkCase]:
    suites = split_requested(args.suite) or {"examples"}
    if "all" in suites:
        suites = {"examples", "eyeling-examples", "owl-mobibench"}

    cases: list[BenchmarkCase] = []
    if "examples" in suites:
        cases.extend(discover_example_cases())
    if "eyeling-examples" in suites:
        cases.extend(discover_eyeling_example_cases(args))
    if "owl-mobibench" in suites:
        cases.extend(discover_mobibench_cases(args))
    for raw in args.fixture:
        case_id, path = parse_fixture_arg(raw)
        cases.append(BenchmarkCase(case_id, case_id, (path.read_text(encoding="utf8"),), (path,)))
    seen: set[str] = set()
    unique: list[BenchmarkCase] = []
    for case in cases:
        if case.id in seen:
            continue
        seen.add(case.id)
        unique.append(case)
    return unique


def discover_example_cases() -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for path in sorted((ROOT / "examples").glob("*.n3")):
        cases.append(BenchmarkCase(path.stem, path.stem.replace("-", " "), (path.read_text(encoding="utf8"),), (path,)))
    return cases


def discover_eyeling_example_cases(args: argparse.Namespace) -> list[BenchmarkCase]:
    examples_dir = Path(args.eyeling_path).resolve() / "examples"
    if not examples_dir.is_dir():
        raise SystemExit(f"Eyeling examples directory does not exist: {examples_dir}")
    cases: list[BenchmarkCase] = []
    for path in sorted(examples_dir.glob("*.n3")):
        trig_path = examples_dir / "input" / f"{path.stem}.trig"
        builtin_path = examples_dir / "builtin" / f"{path.stem}.js"
        pyling_builtin_path = ROOT / "examples" / "builtin" / f"{path.stem}.py"
        source_paths = [path]
        sources = [path.read_text(encoding="utf8")]
        if trig_path.exists():
            source_paths.append(trig_path)
            sources.append(trig_path.read_text(encoding="utf8"))
        cases.append(
            BenchmarkCase(
                f"eyeling-{path.stem}",
                path.stem.replace("-", " "),
                tuple(sources),
                tuple(source_paths),
                rdf=trig_path.exists(),
                suite="eyeling-examples",
                eyeling_builtin_path=builtin_path if builtin_path.exists() else None,
                pyling_builtin_path=pyling_builtin_path if pyling_builtin_path.exists() else None,
            )
        )
    return cases


def discover_mobibench_cases(args: argparse.Namespace) -> list[BenchmarkCase]:
    rules = load_owl2rl_rules(args)
    archive_path = ensure_mobibench_archive(args)
    cases: list[BenchmarkCase] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        metadata_names = sorted(
            name
            for name in names
            if name.startswith(OWL2RL_SUBSUITE_PREFIX) and name.endswith(".metadata.properties")
        )
        for name in metadata_names:
            directory = name[: name.rfind("/")]
            case_id = directory[directory.rfind("/") + 1 :]
            metadata = parse_metadata(archive.read(name).decode("utf8"))
            kind = test_kind(metadata.get("testcase.type"))
            premise_name = f"{directory}/{case_id}.premisegraph.ttl"
            graph_name = f"{directory}/{case_id}.graph.ttl"
            if kind == "positive" and premise_name in names:
                premise = archive.read(premise_name).decode("utf8")
            elif kind == "inconsistency" and graph_name in names:
                premise = archive.read(graph_name).decode("utf8")
            else:
                continue
            label = one_line(metadata.get("testcase.description", case_id))[:80] or case_id
            cases.append(
                BenchmarkCase(
                    f"mobibench-{case_id}",
                    label,
                    (rules, premise),
                    fuxi_sources=(premise,),
                    fuxi_mode="owl",
                    owlrl_sources=(premise,),
                    suite="owl-mobibench",
                )
            )
            if args.mobibench_limit and len(cases) >= args.mobibench_limit:
                break
    return cases


def parse_fixture_arg(raw: str) -> tuple[str, Path]:
    if "=" in raw:
        case_id, value = raw.split("=", 1)
        path = Path(value)
    else:
        path = Path(raw)
        case_id = path.stem
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise SystemExit(f"Fixture does not exist: {path}")
    return case_id, path


def load_owl2rl_rules(args: argparse.Namespace) -> str:
    candidates: list[Path] = []
    if args.owl2rl_rules:
        candidates.append(Path(args.owl2rl_rules))
    candidates.extend(
        [
            ROOT / ".cache/perf/owl2rl-eyeling.n3",
            ROOT.parent / "rdfjs-inference-engine/rules/owl2rl/owl2rl-eyeling.n3",
        ]
    )
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf8")

    cache_path = ROOT / ".cache/perf/owl2rl-eyeling.n3"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    download(args.owl2rl_rules_url, cache_path)
    return cache_path.read_text(encoding="utf8")


def ensure_mobibench_archive(args: argparse.Namespace) -> Path:
    cache_path = Path(args.mobibench_cache)
    if not cache_path.is_absolute():
        cache_path = (ROOT / cache_path).resolve()
    sibling_cache = ROOT.parent / "rdfjs-inference-engine/.cache/mobibench/testsuite-owl2-rdfbased.zip"
    if cache_path.exists():
        return cache_path
    if sibling_cache.exists():
        return sibling_cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    download(args.mobibench_url, cache_path)
    return cache_path


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "pyling-benchmark"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def test_kind(value: str | None) -> str | None:
    if value == "POSITIVE_ENTAILMENT":
        return "positive"
    if value == "INCONSISTENCY":
        return "inconsistency"
    return None


def parse_metadata(source: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in re_find_entries(source):
        metadata[key] = decode_xml(value)
    return metadata


def re_find_entries(source: str) -> Iterable[tuple[str, str]]:
    import re

    for match in re.finditer(r'<entry key="([^"]+)">([\s\S]*?)</entry>', source):
        yield match.group(1), match.group(2)


def decode_xml(value: str) -> str:
    return (
        value.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def discover_reasoners(args: argparse.Namespace) -> list[Reasoner]:
    return [
        Reasoner("pyling", "pyling in-process", pyling_available, run_pyling_once),
        Reasoner("eyeling", "Eyeling subprocess", lambda: eyeling_available(args), run_eyeling_once),
        Reasoner("fuxi", "FuXi subprocess", lambda: fuxi_available(args), run_fuxi_once),
        Reasoner("owlrl", "owlrl subprocess", lambda: owlrl_available(args), run_owlrl_once),
    ]


def pyling_available() -> tuple[bool, str | None]:
    try:
        import pyling  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


def fuxi_available(args: argparse.Namespace) -> tuple[bool, str | None]:
    code = "import fuxi; print(getattr(fuxi, '__version__', 'unknown'))"
    env = fuxi_env(args)
    try:
        proc = subprocess.run(
            [args.fuxi_python, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=min(args.timeout, 10.0),
        )
    except FileNotFoundError:
        return False, f"Python executable not found: {args.fuxi_python}"
    if proc.returncode != 0:
        return False, one_line(proc.stderr or proc.stdout or "FuXi import failed")
    return True, None


def owlrl_available(args: argparse.Namespace) -> tuple[bool, str | None]:
    code = "import owlrl; print(getattr(owlrl, '__version__', 'unknown'))"
    try:
        proc = subprocess.run(
            [args.owlrl_python, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(args.timeout, 10.0),
        )
    except FileNotFoundError:
        return False, f"Python executable not found: {args.owlrl_python}"
    if proc.returncode != 0:
        return False, one_line(proc.stderr or proc.stdout or "owlrl import failed")
    return True, None


def eyeling_available(args: argparse.Namespace) -> tuple[bool, str | None]:
    package_path = Path(args.eyeling_path).resolve()
    code = "const e=require(process.argv[1]); if(typeof e.reasonStream!=='function') process.exit(2)"
    try:
        proc = subprocess.run(
            [args.eyeling_node, "-e", code, str(package_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(args.timeout, 10.0),
        )
    except FileNotFoundError:
        return False, f"Node.js executable not found: {args.eyeling_node}"
    if proc.returncode != 0:
        return False, one_line(proc.stderr or proc.stdout or f"Cannot load Eyeling from {package_path}")
    return True, None


def fuxi_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    if args.fuxi_pythonpath:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = args.fuxi_pythonpath if not existing else args.fuxi_pythonpath + os.pathsep + existing
    return env


def run_benchmarks(cases: list[BenchmarkCase], reasoners: list[Reasoner], args: argparse.Namespace) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []
    for case in cases:
        for reasoner in reasoners:
            if reasoner.id == "owlrl" and case.owlrl_sources is None:
                results.append(
                    BenchmarkResult(
                        case.id,
                        case.label,
                        reasoner.id,
                        "skipped",
                        [],
                        "case does not provide an RDF graph for the OWL 2 RL profile",
                    )
                )
                continue
            if reasoner.id == "fuxi":
                try:
                    ensure = ensure_fuxi_for_run(args)
                except Exception as exc:
                    results.append(BenchmarkResult(case.id, case.label, reasoner.id, "failed", [], str(exc)))
                    continue
                if ensure is not None:
                    results.append(BenchmarkResult(case.id, case.label, reasoner.id, "skipped", [], ensure))
                    continue
            ok, reason = reasoner.available()
            if not ok:
                results.append(BenchmarkResult(case.id, case.label, reasoner.id, "skipped", [], reason))
                continue
            samples: list[Sample] = []
            try:
                for index in range(args.warmup + args.iterations):
                    sample = reasoner.run_once(case, args)
                    if index >= args.warmup:
                        samples.append(sample)
                results.append(BenchmarkResult(case.id, case.label, reasoner.id, "ok", samples))
            except Exception as exc:
                results.append(BenchmarkResult(case.id, case.label, reasoner.id, "failed", samples, str(exc)))
    return results


def ensure_fuxi_for_run(args: argparse.Namespace) -> str | None:
    ok, _reason = fuxi_available(args)
    if ok:
        return None
    if args.no_install_fuxi:
        return _reason or "FuXi unavailable and --no-install-fuxi was set"
    if args.fuxi_pythonpath:
        return _reason or "FuXi unavailable from FUXI_PYTHONPATH"
    explicit_python = os.environ.get("FUXI_PYTHON") or args.fuxi_python != "python3"
    if explicit_python:
        return _reason or f"FuXi unavailable in {args.fuxi_python}"

    venv = Path(args.fuxi_venv).resolve()
    python = fuxi_venv_python(venv)
    bootstrap = find_python_313()
    if not python.exists() or not python_module_available(str(python), "pip"):
        if bootstrap is None:
            return "FuXi requires Python >=3.13; no python3.13 executable was found"
        has_ensurepip = python_module_available(bootstrap, "ensurepip")
        has_pip = python_module_available(bootstrap, "pip")
        if not has_ensurepip and not has_pip:
            return (
                f"{bootstrap} does not provide ensurepip or pip. Install the Python 3.13 venv package "
                "(for example: sudo apt install python3.13-venv) or provide FUXI_PYTHON."
            )
        venv.parent.mkdir(parents=True, exist_ok=True)
        print(f"Installing FuXi benchmark environment in {venv}", file=sys.stderr)
        command = [bootstrap, "-m", "venv"]
        if python.exists():
            command.append("--clear")
        if not has_ensurepip:
            command.extend(["--without-pip", "--system-site-packages"])
        command.append(str(venv))
        run_install_command(command, args.timeout)

    run_install_command([str(python), "-m", "pip", "install", "--upgrade", "pip"], args.timeout)
    run_install_command([str(python), "-m", "pip", "install", args.fuxi_package], args.timeout)

    args.fuxi_python = str(python)
    ok, reason = fuxi_available(args)
    return None if ok else reason or f"FuXi unavailable after installing {args.fuxi_package}"


def fuxi_venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def find_python_313() -> str | None:
    for name in ("python3.13", "python3"):
        candidate = shutil.which(name)
        if not candidate:
            continue
        proc = subprocess.run(
            [candidate, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            return candidate
    return None


def python_module_available(python: str, module: str) -> bool:
    proc = subprocess.run(
        [python, "-c", f"import {module}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def run_install_command(command: list[str], timeout: float) -> None:
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(one_line(proc.stderr or proc.stdout or f"{command[0]} exited {proc.returncode}"))


def run_pyling_once(case: BenchmarkCase, args: argparse.Namespace) -> Sample:
    if case.suite == "eyeling-examples":
        return run_pyling_subprocess_once(case, args)

    from pyling import reason_stream

    input_data: Any = {"sources": list(case.sources)} if len(case.sources) > 1 else case.sources[0]
    start = time.perf_counter()
    result = reason_stream(
        input_data,
        rdf=case.rdf,
        rdf12=case.rdf,
        input_format=case.input_format,
        include_input_facts_in_closure=args.include_input_facts,
        max_iterations=args.max_iterations,
    )
    elapsed = (time.perf_counter() - start) * 1000
    facts, derived = pyling_reported_counts(result)
    return Sample(
        total_ms=elapsed,
        facts=facts,
        derived=derived,
        closure_chars=len(result.closure_n3),
    )


def pyling_reported_counts(result: Any) -> tuple[int, int]:
    if not getattr(result, "query_mode", False):
        return len(result.facts), len(result.derived)
    query_triples = list(result.query_triples)
    output_triples = [
        tr for tr in query_triples
        if getattr(getattr(tr, "p", None), "value", None) == "http://www.w3.org/2000/10/swap/log#outputString"
    ]
    selected = output_triples if output_triples else query_triples
    return len(selected), len(selected)


def run_pyling_subprocess_once(case: BenchmarkCase, args: argparse.Namespace) -> Sample:
    payload = {
        "sources": list(case.sources),
        "rdf": case.rdf,
        "rdf12": case.rdf,
        "input_format": case.input_format,
        "include_input_facts": args.include_input_facts,
        "max_iterations": args.max_iterations,
        "builtin_path": str(case.pyling_builtin_path) if case.pyling_builtin_path else None,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf8", delete=False) as temp:
        json.dump(payload, temp)
        temp_path = temp.name
    try:
        proc = subprocess.run(
            [sys.executable, "-c", PYLING_RUNNER, temp_path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            cwd=ROOT,
        )
    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(one_line(proc.stderr or proc.stdout or f"pyling exited {proc.returncode}"))
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"pyling returned non-JSON output: {one_line(proc.stdout)}") from exc
    return Sample(
        total_ms=float(result["total_ms"]),
        facts=result.get("facts"),
        derived=result.get("derived"),
        closure_chars=result.get("closure_chars"),
    )


PYLING_RUNNER = r"""
import importlib.util
import json
import sys
import time
from pathlib import Path

from pyling import reason_stream, register_builtin_module


def load_builtin_module(path):
    if not path:
        return
    module_path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"pyling_perf_builtin_{module_path.stem}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load builtin module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    register_builtin_module(module, origin=str(module_path))

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
load_builtin_module(payload.get("builtin_path"))
input_data = {"sources": payload["sources"]} if len(payload["sources"]) > 1 else payload["sources"][0]
start = time.perf_counter()
result = reason_stream(
    input_data,
    rdf=payload["rdf"],
    rdf12=payload["rdf12"],
    input_format=payload["input_format"],
    include_input_facts_in_closure=payload["include_input_facts"],
    max_iterations=payload["max_iterations"],
)
elapsed = (time.perf_counter() - start) * 1000
query_triples = list(result.query_triples) if result.query_mode else []
output_triples = [
    tr for tr in query_triples
    if getattr(getattr(tr, "p", None), "value", None) == "http://www.w3.org/2000/10/swap/log#outputString"
]
if result.query_mode:
    selected_count = len(output_triples if output_triples else query_triples)
    facts = selected_count
    derived = selected_count
else:
    facts = len(result.facts)
    derived = len(result.derived)
print(json.dumps({
    "total_ms": elapsed,
    "facts": facts,
    "derived": derived,
    "closure_chars": len(result.closure_n3),
}))
"""


def run_fuxi_once(case: BenchmarkCase, args: argparse.Namespace) -> Sample:
    code = FUXI_RUNNER
    env = fuxi_env(args)
    sources = case.fuxi_sources if case.fuxi_sources is not None else case.sources
    with tempfile.NamedTemporaryFile("w", suffix=".n3", encoding="utf8", delete=False) as temp:
        temp.write("\n\n".join(sources))
        temp_path = temp.name
    try:
        proc = subprocess.run(
            [args.fuxi_python, "-c", code, temp_path, case.fuxi_mode],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=args.timeout,
        )
    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(one_line(proc.stderr or proc.stdout or f"FuXi exited {proc.returncode}"))
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"FuXi returned non-JSON output: {one_line(proc.stdout)}") from exc
    return Sample(
        total_ms=float(payload["total_ms"]),
        facts=payload.get("facts"),
        derived=payload.get("derived"),
        closure_chars=payload.get("closure_chars"),
    )


def run_eyeling_once(case: BenchmarkCase, args: argparse.Namespace) -> Sample:
    package_path = Path(args.eyeling_path).resolve()
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf8", delete=False) as temp:
        json.dump(
            {
                "sources": list(case.sources),
                "rdf": case.rdf,
                "builtin_path": str(case.eyeling_builtin_path) if case.eyeling_builtin_path else None,
            },
            temp,
        )
        temp_path = temp.name
    try:
        proc = subprocess.run(
            [args.eyeling_node, "-e", EYELING_RUNNER, str(package_path), temp_path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
        )
    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(one_line(proc.stderr or proc.stdout or f"Eyeling exited {proc.returncode}"))
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Eyeling returned non-JSON output: {one_line(proc.stdout)}") from exc
    return Sample(
        total_ms=float(payload["total_ms"]),
        facts=payload.get("facts"),
        derived=payload.get("derived"),
        closure_chars=payload.get("closure_chars"),
    )


EYELING_RUNNER = r"""
const fs = require("node:fs");
const { performance } = require("node:perf_hooks");

const eyeling = require(process.argv[1]);
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const source = input.sources.length === 1 ? input.sources[0] : input;
const start = performance.now();
const result = eyeling.reasonStream(source, {
  rdf: input.rdf,
  builtinModules: input.builtin_path ? [input.builtin_path] : null,
});
const elapsed = performance.now() - start;
function predicateValue(triple) {
  return triple && triple.p && triple.p.value;
}
let facts = result.facts.length;
let derived = result.derived.length;
if (result.queryMode) {
  const queryTriples = Array.isArray(result.queryTriples) ? result.queryTriples : [];
  const outputTriples = queryTriples.filter((tr) => predicateValue(tr) === "http://www.w3.org/2000/10/swap/log#outputString");
  const selected = outputTriples.length ? outputTriples : queryTriples;
  facts = selected.length;
  derived = selected.length;
}
process.stdout.write(JSON.stringify({
  total_ms: elapsed,
  facts,
  derived,
  closure_chars: result.closureN3.length,
}));
"""


FUXI_RUNNER = r"""
import json
import sys
import time
from pathlib import Path

from rdflib import Graph
from fuxi.Rete.Util import generate_token_set

path = Path(sys.argv[1])
mode = sys.argv[2]
source = path.read_text(encoding="utf8")
graph = Graph()
start = time.perf_counter()
graph.parse(data=source, format="n3", publicID=str(path.resolve()))
if mode == "owl":
    from fuxi.Rete.RuleStore import setup_rule_store

    _store, _rule_graph, network = setup_rule_store(make_network=True)
    setup_dlp = getattr(network, "setup_description_logic_programming", None)
    if setup_dlp is None:
        setup_dlp = getattr(network, "setupDescriptionLogicProgramming")
    setup_dlp(graph, add_pd_semantics=True, construct_network=True)
else:
    from fuxi.Horn.HornRules import network_from_n3

    network = network_from_n3(graph)
network.feed_facts_to_add(generate_token_set(graph))
elapsed = (time.perf_counter() - start) * 1000
inferred = getattr(network, "inferred_facts", None)
if inferred is None:
    inferred = getattr(network, "inferredFacts", None)
print(json.dumps({
    "total_ms": elapsed,
    "facts": len(graph),
    "derived": len(inferred) if inferred is not None else None,
    "closure_chars": len(inferred.serialize(format="nt")) if inferred is not None else None,
}))
"""


def run_owlrl_once(case: BenchmarkCase, args: argparse.Namespace) -> Sample:
    sources = case.owlrl_sources if case.owlrl_sources is not None else case.sources
    with tempfile.NamedTemporaryFile("w", suffix=".ttl", encoding="utf8", delete=False) as temp:
        temp.write("\n\n".join(sources))
        temp_path = temp.name
    try:
        proc = subprocess.run(
            [args.owlrl_python, "-c", OWLRL_RUNNER, temp_path, case.owlrl_format],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
        )
    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(one_line(proc.stderr or proc.stdout or f"owlrl exited {proc.returncode}"))
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"owlrl returned non-JSON output: {one_line(proc.stdout)}") from exc
    return Sample(
        total_ms=float(payload["total_ms"]),
        facts=payload.get("facts"),
        derived=payload.get("derived"),
        closure_chars=payload.get("closure_chars"),
    )


OWLRL_RUNNER = r"""
import json
import sys
import time
from pathlib import Path

from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Graph

path = Path(sys.argv[1])
input_format = sys.argv[2]
source = path.read_text(encoding="utf8")
start = time.perf_counter()
graph = Graph()
graph.parse(data=source, format=input_format, publicID=str(path.resolve()))
initial = len(graph)
DeductiveClosure(OWLRL_Semantics).expand(graph)
elapsed = (time.perf_counter() - start) * 1000
print(json.dumps({
    "total_ms": elapsed,
    "facts": len(graph),
    "derived": len(graph) - initial,
    "closure_chars": len(graph.serialize(format="nt")),
}))
"""


def print_inventory(cases: list[BenchmarkCase], reasoners: list[Reasoner]) -> None:
    print("Cases:")
    for case in cases:
        if case.source_paths:
            paths: list[str] = []
            for path in case.source_paths:
                try:
                    paths.append(str(path.relative_to(ROOT)))
                except ValueError:
                    paths.append(str(path))
            location = ", ".join(paths)
        else:
            location = case.suite
        print(f"  {case.id:32} {case.label:32} {location}")
    print("\nReasoners:")
    for reasoner in reasoners:
        ok, reason = reasoner.available()
        status = "available" if ok else f"skipped: {reason}"
        print(f"  {reasoner.id:28} {reasoner.label:32} {status}")


def print_table(results: list[BenchmarkResult], args: argparse.Namespace) -> None:
    print(f"iterations={args.iterations} warmup={args.warmup}")
    print(f"{'case':28} {'reasoner':10} {'status':8} {'median ms':>10} {'min ms':>10} {'max ms':>10} {'derived':>10} error")
    for result in results:
        if result.status == "ok":
            totals = [sample.total_ms for sample in result.samples]
            derived = first_not_none(sample.derived for sample in result.samples)
            print(
                f"{result.case_id:28} {result.reasoner:10} {result.status:8} "
                f"{median(totals):10.2f} {min(totals):10.2f} {max(totals):10.2f} "
                f"{str(derived):>10} "
            )
        else:
            print(f"{result.case_id:28} {result.reasoner:10} {result.status:8} {'':>10} {'':>10} {'':>10} {'':>10} {result.error or ''}")


def print_json(results: list[BenchmarkResult], args: argparse.Namespace) -> None:
    payload = {
        "iterations": args.iterations,
        "warmup": args.warmup,
        "results": [
            {
                "caseId": result.case_id,
                "caseLabel": result.case_label,
                "reasoner": result.reasoner,
                "status": result.status,
                "error": result.error,
                "samples": [sample.__dict__ for sample in result.samples],
                "summary": summarize(result.samples),
            }
            for result in results
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_csv(results: list[BenchmarkResult]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(["case", "reasoner", "status", "sample", "total_ms", "facts", "derived", "closure_chars", "error"])
    for result in results:
        if not result.samples:
            writer.writerow([result.case_id, result.reasoner, result.status, "", "", "", "", "", result.error or ""])
            continue
        for index, sample in enumerate(result.samples, start=1):
            writer.writerow([
                result.case_id,
                result.reasoner,
                result.status,
                index,
                f"{sample.total_ms:.6f}",
                none_as_empty(sample.facts),
                none_as_empty(sample.derived),
                none_as_empty(sample.closure_chars),
                result.error or "",
            ])


def write_report_dir(results: list[BenchmarkResult], args: argparse.Namespace) -> None:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    writers = {
        "report.json": print_json,
        "report.csv": lambda current_results, _args: print_csv(current_results),
        "report.md": print_markdown,
    }
    for name, writer in writers.items():
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            writer(results, args)
        (report_dir / name).write_text(buffer.getvalue(), encoding="utf8")


def print_markdown(results: list[BenchmarkResult], args: argparse.Namespace) -> None:
    print("# Reasoner Performance Report")
    print()
    print(f"- Iterations: `{args.iterations}`")
    print(f"- Warmup: `{args.warmup}`")
    print(f"- Cases: `{len({result.case_id for result in results})}`")
    print(f"- Reasoners: `{', '.join(sorted({result.reasoner for result in results}))}`")
    print()
    print("| Case | Reasoner | Status | Median ms | Min ms | Max ms | Facts | Derived | Error |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for result in sorted(results, key=lambda item: (item.case_id, item.reasoner)):
        summary = summarize(result.samples)
        total = (summary or {}).get("totalMs") or {}
        print(
            "| "
            + " | ".join(
                [
                    md_cell(result.case_id),
                    md_cell(result.reasoner),
                    md_cell(result.status),
                    fmt_number(total.get("median")),
                    fmt_number(total.get("min")),
                    fmt_number(total.get("max")),
                    md_cell(none_as_empty((summary or {}).get("facts"))),
                    md_cell(none_as_empty((summary or {}).get("derived"))),
                    md_cell(result.error or ""),
                ]
            )
            + " |"
        )


def summarize(samples: list[Sample]) -> dict[str, Any] | None:
    if not samples:
        return None
    totals = [sample.total_ms for sample in samples]
    return {
        "totalMs": {
            "min": min(totals),
            "median": median(totals),
            "max": max(totals),
        },
        "facts": first_not_none(sample.facts for sample in samples),
        "derived": first_not_none(sample.derived for sample in samples),
        "closureChars": first_not_none(sample.closure_chars for sample in samples),
    }


def missing_required_reasoners(results: list[BenchmarkResult], requested: list[str]) -> bool:
    required = split_requested(requested)
    missing = []
    for reasoner in sorted(required):
        if not any(result.reasoner == reasoner and result.status == "ok" for result in results):
            missing.append(reasoner)
    if missing:
        print(f"Missing required successful reasoner execution: {', '.join(missing)}", file=sys.stderr)
    return bool(missing)


def fmt_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return md_cell(value)


def md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def select_cases(cases: list[BenchmarkCase], requested: list[str]) -> list[BenchmarkCase]:
    ids = split_requested(requested)
    return cases if not ids else [case for case in cases if case.id in ids]


def select_reasoners(reasoners: list[Reasoner], requested: list[str]) -> list[Reasoner]:
    ids = split_requested(requested)
    return reasoners if not ids else [reasoner for reasoner in reasoners if reasoner.id in ids]


def split_requested(values: list[str]) -> set[str]:
    return {part for value in values for part in value.split(",") if part}


def first_not_none(values: Iterable[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def none_as_empty(value: Any) -> Any:
    return "" if value is None else value


def one_line(text: str) -> str:
    return " ".join(str(text).split())


if __name__ == "__main__":
    raise SystemExit(main())
