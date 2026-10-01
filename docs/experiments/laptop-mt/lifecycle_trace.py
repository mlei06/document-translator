"""Experiment-only timing spans around unchanged production calls."""

from __future__ import annotations

import contextlib
import copy
import functools
import threading
import time
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch


class Trace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.local = threading.local()
        self.lock = threading.Lock()
        self.rep = 0

    @contextlib.contextmanager
    def span(self, name: str, **details: Any) -> Generator[dict[str, Any]]:
        stack: list[int] = getattr(self.local, "stack", [])
        self.local.stack = stack
        with self.lock:
            event: dict[str, Any] = {
                "id": len(self.events),
                "parent": stack[-1] if stack else None,
                "name": name,
                "rep": self.rep,
                "thread_id": threading.get_ident(),
                "thread_name": threading.current_thread().name,
                "start": time.perf_counter(),
                "process_cpu_start": time.process_time(),
                "thread_cpu_start": time.thread_time(),
                **details,
            }
            self.events.append(event)
        stack.append(event["id"])
        try:
            yield event
        except BaseException as exc:
            with self.lock:
                event["error_type"] = type(exc).__name__
            raise
        finally:
            with self.lock:
                event["end"] = time.perf_counter()
                event["wall_s"] = event["end"] - event["start"]
                event["process_cpu_s"] = time.process_time() - event.pop("process_cpu_start")
                event["thread_cpu_s"] = time.thread_time() - event.pop("thread_cpu_start")
            stack.pop()

    def wrap(self, function: Callable[..., Any], name: str) -> Callable[..., Any]:
        @functools.wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            details: dict[str, Any] = {}
            if name.startswith("libreoffice"):
                details["input_name"] = str(args[0]) if args else str(kwargs.get("source", ""))
            with self.span(name, **details) as event:
                result = function(*args, **kwargs)
                if name == "document_pipeline":
                    with self.lock:
                        event["pipeline_timings_s"] = result.timings_s
                        event["counts"] = result.counts.model_dump(mode="json")
                return result

        return wrapped

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return copy.deepcopy(self.events)

    def install(self, stack: contextlib.ExitStack) -> None:
        import doctranslator_core.pipeline as pipeline
        import doctranslator_core.render as render
        import doctranslator_core.render.verify as verify
        from doctranslator_core.formats.pptx.adapter import PptxAdapter
        from doctranslator_core.translator import Translator
        from doctranslator_server.jobs import pages, worker
        from doctranslator_server.jobs.engines import EngineCatalog
        from doctranslator_server.jobs.queue import Queue

        for owner, attribute, name in [
            (pipeline, "_translate_units", "translation_and_formatting_fallback"),
            (pipeline, "_fit", "standard_fit"),
            (pipeline, "_write_verify_publish", "write_verify_publish"),
            (pipeline, "_verify", "serialized_output_verify"),
            (pipeline, "_thorough_check", "thorough_check_nested"),
            (pipeline, "publish", "atomic_file_publish"),
            (PptxAdapter, "save", "serialized_save"),
            (Translator, "__init__", "translator_model_load"),
            (Translator, "translate_document", "document_pipeline"),
            (EngineCatalog, "translator", "catalog_resolve_or_load"),
            (worker.Worker, "process", "worker_process"),
            (worker, "build_preview", "text_preview_package"),
            (Queue, "publish", "result_publication_and_page_queue"),
            (pages.PageRenderer, "_process", "postpublication_page_render"),
            (pages, "build_pages", "page_pair_render_and_package"),
            (render, "office_to_pdf", "libreoffice_preview_conversion"),
            (render, "rasterize", "preview_rasterization"),
            (verify, "office_to_pdf", "libreoffice_thorough_conversion"),
            (verify, "verify_pdfs", "thorough_geometry_check"),
        ]:
            stack.enter_context(
                patch.object(owner, attribute, self.wrap(getattr(owner, attribute), name))
            )

        original = pipeline._reporter  # pyright: ignore[reportPrivateUsage]

        def reporter(callback: Any) -> Any:
            report = original(callback)
            active: dict[str, Any] = {}

            def progress(phase: Any, done: int, total: int) -> None:
                name = str(phase)
                if done == 0 and name in ("extract", "apply") and name not in active:
                    active[name] = self.span(f"pipeline_{name}")
                    active[name].__enter__()
                report(phase, done, total)
                if done == total and name in active:
                    active.pop(name).__exit__(None, None, None)

            return progress

        stack.enter_context(patch.object(pipeline, "_reporter", reporter))

    def finish(self) -> None:
        for event in self.events:
            if "end" not in event:
                continue
            children = [
                child for child in self.events if child["parent"] == event["id"] and "end" in child
            ]
            event["exclusive_wall_s"] = max(
                0.0, event["wall_s"] - sum(c["wall_s"] for c in children)
            )
            event["exclusive_thread_cpu_s"] = max(
                0.0, event["thread_cpu_s"] - sum(c["thread_cpu_s"] for c in children)
            )

    def resources(self, origin: float, samples: list[dict[str, Any]]) -> None:
        """Proportionally apportion interval observations; never invent unsampled peaks."""
        for event in self.events:
            if "end" not in event:
                event["incomplete"] = True
                continue
            cpu_seconds = cpu_coverage = gpu_sum = gpu_coverage = 0.0
            points: list[dict[str, Any]] = []
            for sample in samples:
                end = origin + sample["elapsed_s"]
                start = end - sample["interval_s"]
                overlap = max(0.0, min(end, event["end"]) - max(start, event["start"]))
                if event["start"] <= end <= event["end"]:
                    points.append(sample)
                if sample["process_tree_cpu_percent"] is not None and overlap:
                    cpu_seconds += sample["process_tree_cpu_percent"] / 100 * overlap
                    cpu_coverage += overlap
                gpu = sample.get("gpu", {}).get("busiest_engine_pct")
                if gpu is not None and overlap:
                    gpu_sum += gpu * overlap
                    gpu_coverage += overlap
            rss = [
                p["process_tree_rss_bytes"]
                for p in points
                if p["process_tree_rss_bytes"] is not None
            ]
            shared = [
                p["gpu"]["shared_total_bytes"]
                for p in points
                if p.get("gpu", {}).get("shared_total_bytes") is not None
            ]
            event["resources"] = {
                "method": "interval overlap estimates; process tree includes concurrent work",
                "cpu_interval_estimated_seconds": cpu_seconds if cpu_coverage else None,
                "cpu_observed_window_s": cpu_coverage,
                "average_cpu_cores_estimate": cpu_seconds / cpu_coverage if cpu_coverage else None,
                "gpu_timeweighted_pct_estimate": gpu_sum / gpu_coverage if gpu_coverage else None,
                "gpu_valid_overlap_s": gpu_coverage,
                "point_sample_rss_peak_bytes": max(rss) if rss else None,
                "point_sample_shared_gpu_peak_bytes": max(shared) if shared else None,
                "point_samples": len(points),
                "short_or_unsampled": event["wall_s"] < 1 or not points,
            }
