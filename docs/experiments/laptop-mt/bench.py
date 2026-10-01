# ruff: noqa: RUF001
"""One isolated laptop MT measurement. Run with the OpenVINO experiment environment.

Each invocation loads exactly one model and writes CPU/GPU profiles for load,
warmup, and each repetition. Inputs and raw output/token metadata are retained.
Business-mixed-v2 excludes the protected Lenovo label captured in the v1 smoke.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from profiling import ResourceProfiler

ROOT = Path(__file__).resolve().parents[3]


def baseline_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "small100_baseline", ROOT / "docs/experiments/openvino-small100/bench.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot import existing SMALL-100 benchmark")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request(port: int, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=180) as response:
        return json.load(response)


class HyRuntime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.process: subprocess.Popen[bytes] | None = None
        self.log: Any = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        backend = "vulkan" if args.runtime == "hy-vulkan" else "cpu"
        exe = ROOT / f"data/tools/llama.cpp/{backend}/llama-server.exe"
        self.command = [
            str(exe),
            "-m",
            str(args.model.resolve()),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "-t",
            str(args.threads),
            "-tb",
            str(args.threads_batch or args.threads),
            "-ngl",
            "99" if backend == "vulkan" else "0",
            "-c",
            str(4096 * args.concurrency),
            "-np",
            str(args.concurrency),
            "--no-warmup",
            "--no-context-shift",
            "--cache-ram",
            "0",
        ]
        self.props = {"command": self.command, "model": str(args.model), "backend": backend}
        version = subprocess.run(  # noqa: S603 - fixed local executable
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.props["version"] = (version.stdout + version.stderr).strip()

    def start(self) -> None:
        self.log = self.args.out.with_suffix(".server.log").open("wb")
        self.process = subprocess.Popen(  # noqa: S603 - fixed local executable; no shell
            self.command,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited: inspect {self.args.out.with_suffix('.server.log')}"
                )
            try:
                if request(self.port, "/health").get("status") == "ok":
                    self.props["server"] = request(self.port, "/props")
                    return
            except urllib.error.URLError, TimeoutError:
                pass
            time.sleep(0.2)
        raise TimeoutError("llama-server did not become healthy in 180 seconds")

    def run(self, texts: list[str]) -> dict[str, Any]:
        outputs: list[str] = []
        meta: list[tuple[Any, Any, bool]] = []
        latencies: list[float] = []
        details: list[dict[str, Any]] = []

        def translate(text: str) -> tuple[dict[str, Any], float]:
            prompt = (
                "<｜hy_begin▁of▁sentence｜><｜hy_User｜>"
                "将以下文本翻译为英语，注意只需要输出翻译后的结果，不要额外解释：\n\n"
                + text
                + "<｜hy_Assistant｜>"
            )
            began = time.perf_counter()
            result = request(
                self.port,
                "/completion",
                {
                    "prompt": prompt,
                    "n_predict": 256,
                    "temperature": 0,
                    "top_k": 20,
                    "top_p": 0.6,
                    "repeat_penalty": 1.05,
                    "seed": 42,
                    "cache_prompt": False,
                    "stream": False,
                },
            )
            return result, time.perf_counter() - began

        with ThreadPoolExecutor(max_workers=self.args.concurrency) as executor:
            responses = list(executor.map(translate, texts))
        for result, latency in responses:
            latencies.append(latency)
            output = result["content"]
            truncated = bool(result.get("stopped_limit") or result.get("truncated"))
            outputs.append(output)
            meta.append((result.get("tokens_evaluated"), result.get("tokens_predicted"), truncated))
            details.append(result)
        return {"outputs": outputs, "meta": meta, "latencies": latencies, "responses": details}

    def close(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        if self.log is not None:
            self.log.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime", required=True, choices=["ct2-cpu", "ov-cpu", "ov-gpu", "hy-cpu", "hy-vulkan"]
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--threads-batch", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--beam", type=int, choices=[1, 4], default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument(
        "--model", type=Path, default=ROOT / "data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if min(args.threads, args.batch_size, args.reps, args.limit, args.concurrency) < 1:
        parser.error("threads, batch-size, reps, limit and concurrency must be positive")
    if args.threads_batch is not None and args.threads_batch < 1:
        parser.error("threads-batch must be positive")
    if not args.runtime.startswith("hy-") and args.concurrency != 1:
        parser.error("SMALL-100 requires concurrency 1; use batch-size to batch segments")
    if args.runtime.startswith("hy-") and (args.batch_size != 1 or args.beam != 1):
        parser.error("HY measurement currently requires batch-size 1 and beam 1")
    os.chdir(ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    baseline = baseline_module()
    power_policy = "not applicable"
    if os.name == "nt":
        baseline.no_power_throttling()
        power_policy = (
            "execution-speed throttling disabled for Python process; child policy unverified"
        )
    baseline.THREADS = args.threads
    baseline.MAX_BATCH = args.batch_size
    corpus = (
        baseline.ZH_LABELS[1:4]
        + baseline.ZH_SENTENCES[:6]
        + ["".join(baseline.ZH_SENTENCES[i : i + 3]) for i in (6, 9, 12)]
    )
    if args.limit > len(corpus):
        corpus += baseline.ZH_SENTENCES[15:]
    texts = corpus[: args.limit]
    versions = {}
    for package in ("ctranslate2", "openvino", "optimum-intel", "torch", "transformers", "psutil"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            versions[package] = importlib.metadata.version(package)
    report: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "corpus_version": "business-mixed-v2",
        "corpus_note": "Excludes protected Lenovo label; v1 retains its empty-output behavior.",
        "power_policy": power_policy,
        "settings": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "versions": versions,
        "inputs": texts,
        "direction": "zh-en",
        "phases": [],
        "decoding": {"temperature": 0, "seed": 42, "max_output_tokens": 256, "cache_prompt": False},
        "load_note": "Fresh process; operating-system filesystem cache is not flushed.",
    }
    hy = HyRuntime(args) if args.runtime.startswith("hy-") else None
    run: Callable[[list[str]], dict[str, Any]]
    phase_name = "load"
    profiler = ResourceProfiler()
    try:
        with profiler:
            if hy:
                hy.start()
                runtime = hy
                run = hy.run
            else:
                runtime = baseline.load_runtime(args.runtime)
                engine = baseline.make_engine(runtime, args.runtime, args.beam)

                def run_small100(items: list[str]) -> dict[str, Any]:
                    return baseline.run_chunks(engine, runtime, items, "zh-en", args.batch_size)

                run = run_small100

        report["phases"].append({"name": "load", "profile": profiler.result()})
        report["runtime"] = runtime.props
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        for name, items in [("warmup", baseline.ZH_SENTENCES[:1])] + [
            (f"inference_{i + 1}", texts) for i in range(args.reps)
        ]:
            phase_name = name
            print(f"{args.runtime} threads={args.threads}: {name}", flush=True)
            with ResourceProfiler() as profiler:
                began = time.perf_counter()
                result = run(items)
                wall = time.perf_counter() - began
            flags = [
                {"empty": not output.strip(), "truncated": bool(meta[2])}
                for output, meta in zip(result["outputs"], result["meta"], strict=True)
            ]
            report["phases"].append(
                {
                    "name": name,
                    "wall_s": wall,
                    "segments_per_s": len(items) / wall,
                    "profile": profiler.result(),
                    "flags": flags,
                    **result,
                }
            )
            args.out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
        report["status"] = "ok"
        report["outputs_valid"] = not any(
            flag["empty"] or flag["truncated"]
            for phase in report["phases"]
            for flag in phase.get("flags", [])
        )
    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        if not any(phase["name"] == phase_name for phase in report["phases"]):
            report["phases"].append(
                {"name": phase_name, "profile": profiler.result(), "failed": True}
            )
        raise
    finally:
        if hy:
            hy.close()
        report["finished_utc"] = datetime.now(UTC).isoformat()
        # Hash after measuring: hashing first would warm the OS model-file cache.
        if hy:
            model_files = [args.model]
        elif args.runtime == "ct2-cpu":
            model_files = [baseline.CT2_DIR / "model.bin"]
        else:
            model_files = sorted(baseline.OV_DIR.glob("*.xml")) + sorted(
                baseline.OV_DIR.glob("*.bin")
            )
        report["model_sha256"] = {}
        for model_file in model_files:
            if model_file.is_file():
                with model_file.open("rb") as stream:
                    report["model_sha256"][str(model_file)] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
