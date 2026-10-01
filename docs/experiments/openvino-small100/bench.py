# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openvino==2026.4.0",
#     "openvino-tokenizers==2026.4.0.0",
#     "optimum-intel==2.2.0",
#     "optimum==2.3.0",
#     "transformers==5.5.4",
#     "torch==2.14.0",
#     "nncf==3.4.0",
#     "ctranslate2==4.8.2",
#     "sentencepiece==0.2.2",
#     "psutil==7.2.2",
# ]
# ///
# ruff: noqa: RUF001 - CJK punctuation in the synthetic inputs
"""SMALL-100 on OpenVINO (CPU and Intel Arc iGPU) versus the CTranslate2 CPU baseline.

Experiment code, not production. Run from the repository root after ``export.py`` (see README):

    uv run --no-project --with-editable ./packages/core `
        docs/experiments/openvino-small100/bench.py all

Every runtime is wrapped in CTranslate2's ``translate_batch`` interface and injected into the
production ``MtEngine`` through ``MtRuntime``, so tokenization, the ``__<target>__`` prefix and
output decoding are the production code for all three. ``all`` runs each (runtime, beam) text
benchmark and each document run in a fresh process, one at a time, then writes results.json.
"""

import argparse
import contextlib
import csv
import json
import os
import platform
import re
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

OUT = Path("data/experiments/openvino-small100")
CT2_DIR = Path("data/models/alirezamsh--small100-ct2-int8")
OV_DIR = OUT / "models" / "small100-ov-fp32"
WEBSITE_DB = Path("data/website/doctranslator.db")
FIXTURES = [Path("tests/fixtures/pptx/deck.pptx"), Path("tests/fixtures/docx/report.docx")]
RUNTIMES = ("ct2-cpu", "ov-cpu", "ov-gpu")
BEAMS = (1, 4)
BATCHES = (1, 8, 32)
REPS = 3
THREADS = 4  # the website's cpu_threads
MAX_BATCH = 32  # MtEngineConfig.max_batch_size default
MAX_DECODE = 256  # CTranslate2's default max_decoding_length, set explicitly for every runtime
MAX_INPUT = 1024  # SMALL-100 max_position_embeddings; longer inputs are rejected, never cut
EOS, PAD, UNK = 2, 1, 3
MONITOR_S = 5  # background monitor window
BUSY_CORES = 5.0  # other processes' CPU; this laptop idles at ~2.5-4 (endpoint protection, WMI)
ATTEMPTS = 3  # a measurement overlapping a busy window is repeated, up to this many times

# --- Synthetic inputs -----------------------------------------------------------------------

ZH_LABELS = [
    "联想",
    "营业收入",
    "净利润",
    "总计",
    "备注",
    "第三季度",
    "市场份额",
    "客户满意度",
    "研发投入",
    "下一步计划",
    "风险与挑战",
    "项目进度",
    "产品路线图",
    "供应链",
    "人力资源",
    "财务摘要",
    "年度目标",
    "关键指标",
    "销售区域",
    "同比增长",
    "毛利率",
    "库存周转",
    "服务器业务",
    "个人电脑",
    "智能设备",
    "数据中心",
    "合作伙伴",
    "会议纪要",
    "附录",
    "目录",
    "联系我们",
    "谢谢",
]
EN_LABELS = [
    "Lenovo",
    "Revenue",
    "Net income",
    "Total",
    "Notes",
    "Third quarter",
    "Market share",
    "Customer satisfaction",
    "R&D investment",
    "Next steps",
    "Risks and challenges",
    "Project status",
    "Product roadmap",
    "Supply chain",
    "Human resources",
    "Financial summary",
    "Annual goals",
    "Key metrics",
    "Sales regions",
    "Year-over-year growth",
    "Gross margin",
    "Inventory turnover",
    "Server business",
    "Personal computers",
    "Smart devices",
    "Data center",
    "Partners",
    "Meeting minutes",
    "Appendix",
    "Contents",
    "Contact us",
    "Thank you",
]
ZH_SENTENCES = [
    "本季度公司整体营业收入同比增长12%，主要得益于个人电脑业务的复苏。",
    "我们计划在明年上半年推出三款面向中小企业的新产品。",
    "供应链团队已与主要供应商签订了为期两年的合作协议。",
    "请各部门负责人在周五之前提交下一季度的预算草案。",
    "客户反馈显示，新版软件的稳定性明显优于旧版本。",
    "数据中心的能耗在过去一年中降低了约18%。",
    "由于原材料价格上涨，部分产品的毛利率有所下降。",
    "本次会议的主要目的是确定明年的研发重点。",
    "我们将在上海和深圳各增设一个客户服务中心。",
    "新员工入职培训将于10月8日正式开始。",
    "市场调研表明，消费者更加关注产品的续航能力。",
    "该项目预计在2027年第一季度完成全部测试工作。",
    "为了降低运营成本，公司决定优化物流网络。",
    "联想在全球个人电脑市场的份额继续保持领先。",
    "如有任何问题，请联系项目经理或发送邮件至支持团队。",
    "第二阶段的开发工作比原计划提前了两周。",
    "我们需要进一步加强信息安全管理，防止数据泄露。",
    "今年的员工满意度调查共收到4,215份有效问卷。",
    "服务器业务的订单量连续三个季度实现增长。",
    "管理层将在下个月召开年度战略规划会议。",
    "新的报销流程将于11月1日起在全公司推行。",
    "部分海外市场受到汇率波动的影响，收入低于预期。",
    "产品设计团队正在评估三种不同的外观方案。",
    "我们鼓励员工积极参与公司组织的技术分享活动。",
    "本报告中的所有数据均截至2026年6月30日。",
    "为提高交付效率，工厂引入了新的自动化生产线。",
    "合作伙伴大会将于明年三月在北京举行。",
    "目前库存水平处于合理区间，无需额外调整。",
    "研发投入占营业收入的比例提高到了4.5%。",
    "我们将继续推进绿色低碳的可持续发展战略。",
    "请确认附件中的合同条款，并在签字后寄回。",
    "感谢大家在过去一年中的辛勤工作和大力支持。",
]
EN_SENTENCES = [
    "Overall revenue for the quarter increased 12% year over year, driven mainly by the "
    "recovery of the PC business.",
    "We plan to launch three new products for small and medium-sized businesses in the first "
    "half of next year.",
    "The supply chain team has signed a two-year cooperation agreement with our main suppliers.",
    "Department heads should submit their draft budgets for the next quarter by Friday.",
    "Customer feedback shows that the new software release is noticeably more stable than the "
    "previous version.",
    "Energy consumption in the data center fell by about 18% over the past year.",
    "Gross margins on some products declined because of rising raw material prices.",
    "The main purpose of this meeting is to set next year's research and development priorities.",
    "We will open a new customer service center in both Shanghai and Shenzhen.",
    "Onboarding training for new employees officially begins on October 8.",
    "Market research indicates that consumers care more about battery life than before.",
    "The project is expected to complete all testing in the first quarter of 2027.",
    "To reduce operating costs, the company decided to optimize its logistics network.",
    "Lenovo continues to lead the global PC market by share.",
    "If you have any questions, please contact the project manager or email the support team.",
    "Development for the second phase is two weeks ahead of the original schedule.",
    "We need to further strengthen information security management to prevent data leaks.",
    "This year's employee satisfaction survey received 4,215 valid responses.",
    "Server orders have grown for three consecutive quarters.",
    "Management will hold the annual strategic planning meeting next month.",
    "The new expense reimbursement process will roll out company-wide on November 1.",
    "Some overseas markets were affected by exchange rate fluctuations, and revenue fell short "
    "of expectations.",
    "The product design team is evaluating three different exterior design options.",
    "We encourage employees to take part in the technical sharing sessions organized by the "
    "company.",
    "All figures in this report are as of June 30, 2026.",
    "To improve delivery efficiency, the factory introduced a new automated production line.",
    "The partner conference will be held in Beijing next March.",
    "Inventory levels are currently within a reasonable range and need no further adjustment.",
    "R&D spending rose to 4.5% of revenue.",
    "We will continue to pursue a green, low-carbon sustainable development strategy.",
    "Please review the contract terms in the attachment and return a signed copy.",
    "Thank you all for your hard work and strong support over the past year.",
]


def _paragraphs(sentences: list[str], sep: str) -> list[str]:
    """32 paragraphs of 4 consecutive sentences (wrapping), so each is ~4x a sentence."""
    return [sep.join(sentences[(i + k) % len(sentences)] for k in range(4)) for i in range(32)]


DIRECTIONS = ("zh-en", "en-zh")
POOLS: dict[str, dict[str, list[str]]] = {
    "zh-en": {
        "label": ZH_LABELS,
        "sentence": ZH_SENTENCES,
        "paragraph": _paragraphs(ZH_SENTENCES, ""),
    },
    "en-zh": {
        "label": EN_LABELS,
        "sentence": EN_SENTENCES,
        "paragraph": _paragraphs(EN_SENTENCES, " "),
    },
}
# Regression and protection cases. <gN>...</gN> and <xN/> are the pipeline's inline markers.
CHECKS: dict[str, list[tuple[str, str]]] = {
    "zh-en": [
        ("lenovo_alone", "联想"),
        ("lenovo_group", "联想集团"),
        ("lenovo_product", "联想 ThinkPad X1 Carbon 第12代笔记本电脑"),
        ("lenovo_revenue", "联想集团2025/26财年第一季度营业额为185亿美元，同比增长22%。"),
        ("date_number", "请于2026年10月15日前提交第3版预算。"),
        ("formatted_number", "销售额：1,234,567元（增长8.5%）"),
        ("markers_paired", "<g1>营业收入</g1>同比增长<g2>15%</g2>。"),
        ("marker_link", "请访问<x1/>了解更多信息。"),
        ("markers_mixed", "<g1>注意：</g1>本文件包含<x1/>和<x2/>两个附件。"),
        ("page_field", "第<x1/>页，共<x2/>页"),
        ("yes", "是"),
        ("no", "否"),
        ("total", "总计"),
    ],
    "en-zh": [
        ("lenovo_alone", "Lenovo"),
        (
            "lenovo_revenue",
            "Lenovo Group reported first-quarter revenue of US$18.5 billion for fiscal year "
            "2025/26, up 22% year over year.",
        ),
        ("date_number", "Please submit version 3 of the budget by October 15, 2026."),
        ("formatted_number", "Sales: 1,234,567 yuan (up 8.5%)"),
        ("markers_paired", "<g1>Revenue</g1> grew by <g2>15%</g2> year over year."),
        ("marker_link", "Please visit <x1/> for more information."),
        ("markers_mixed", "<g1>Note:</g1> this document has two attachments, <x1/> and <x2/>."),
        ("page_field", "Page <x1/> of <x2/>"),
        ("yes", "Yes"),
        ("no", "No"),
        ("total", "Total"),
    ],
}

# --- Runtimes behind CTranslate2's interface ------------------------------------------------


@dataclass
class _Result:
    hypotheses: list[list[str]]


class Recorder:
    """Records per-segment generated-token counts and truncation for the last call."""

    def __init__(self) -> None:
        self.last: list[tuple[int, int, bool]] = []  # (input tokens, output tokens, truncated)
        self.engine_s = 0.0

    @staticmethod
    def check_inputs(source: list[list[str]]) -> None:
        for tokens in source:
            if len(tokens) > MAX_INPUT:
                raise ValueError(f"input of {len(tokens)} tokens exceeds {MAX_INPUT}")


class Ct2Runtime(Recorder):
    def __init__(self) -> None:
        super().__init__()
        import ctranslate2

        started = time.perf_counter()
        self._t = ctranslate2.Translator(
            str(CT2_DIR), device="cpu", compute_type="int8", intra_threads=THREADS
        )
        self.timings = {"load_s": time.perf_counter() - started, "compile_s": 0.0}
        self.props = {
            "device": "cpu",
            "compute_type": "int8 (int8 weights, int8 GEMM with dynamic activation scales)",
            "intra_threads": THREADS,
            "supported_compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
        }

    def translate_batch(
        self, source: list[list[str]], *, beam_size: int, max_batch_size: int
    ) -> list[_Result]:
        self.check_inputs(source)
        started = time.perf_counter()
        results = self._t.translate_batch(
            source,
            beam_size=beam_size,
            max_batch_size=max_batch_size,
            max_decoding_length=MAX_DECODE,
            max_input_length=0,
        )
        self.engine_s += time.perf_counter() - started
        hyps = [r.hypotheses[0] for r in results]
        # Hypotheses exclude </s>; MAX_DECODE tokens means the limit stopped decoding.
        self.last = [
            (len(s), len(h), len(h) >= MAX_DECODE) for s, h in zip(source, hyps, strict=True)
        ]
        return [_Result([h]) for h in hyps]


class OvRuntime(Recorder):
    def __init__(self, device: str, cache_dir: str = "") -> None:
        super().__init__()
        import torch
        from optimum.intel import OVModelForSeq2SeqLM

        self._torch = torch
        torch.set_num_threads(THREADS)  # the generation loop's host-side tensor work
        # CTranslate2's vocabulary is the complete id table: vocab.json + added_tokens.json (the
        # __xx__ language tokens) + 8 unused "madeupword" fillers. ``environment`` verifies it.
        tokens = json.loads((CT2_DIR / "shared_vocabulary.json").read_text("utf-8"))
        self.vocab: dict[str, int] = {t: i for i, t in enumerate(tokens)}
        self.inverse = dict(enumerate(tokens))
        config: dict[str, str] = {"CACHE_DIR": cache_dir}
        if device == "CPU":
            config["INFERENCE_NUM_THREADS"] = str(THREADS)
        started = time.perf_counter()
        self.model = OVModelForSeq2SeqLM.from_pretrained(
            str(OV_DIR.resolve()), device=device, ov_config=config, compile=False
        )
        loaded = time.perf_counter()
        self.model.compile()
        self.timings = {"load_s": loaded - started, "compile_s": time.perf_counter() - loaded}
        self.props = {"device": device, "ov_config": config, "parts": self._part_props()}
        for part in self.props["parts"].values():
            if not all(d.startswith(device) for d in part["EXECUTION_DEVICES"]):
                raise RuntimeError(f"expected {device} execution, got {part}")

    def _part_props(self) -> dict[str, dict[str, Any]]:
        props: dict[str, dict[str, Any]] = {}
        for name, part in (("encoder", self.model.encoder), ("decoder", self.model.decoder)):
            compiled = part.request
            if hasattr(compiled, "get_compiled_model"):
                compiled = compiled.get_compiled_model()
            entry: dict[str, Any] = {}
            for key in (
                "EXECUTION_DEVICES",
                "INFERENCE_PRECISION_HINT",
                "PERFORMANCE_HINT",
                "NUM_STREAMS",
                "INFERENCE_NUM_THREADS",
                "EXECUTION_MODE_HINT",
            ):
                try:
                    entry[key] = compiled.get_property(key)
                except RuntimeError:
                    continue
            props[name] = {k: v if isinstance(v, list) else str(v) for k, v in entry.items()}
        return props

    def translate_batch(
        self, source: list[list[str]], *, beam_size: int, max_batch_size: int
    ) -> list[_Result]:
        """CTranslate2 semantics: sort by length, split into ``max_batch_size`` chunks, restore."""
        self.check_inputs(source)
        torch = self._torch
        started = time.perf_counter()
        order = sorted(range(len(source)), key=lambda i: len(source[i]))
        results: list[_Result | None] = [None] * len(source)
        meta: list[tuple[int, int, bool]] = [(0, 0, False)] * len(source)
        for start in range(0, len(order), max_batch_size):
            chunk = order[start : start + max_batch_size]
            ids = [[self.vocab.get(t, UNK) for t in source[i]] for i in chunk]
            width = max(len(x) for x in ids)
            input_ids = torch.tensor([x + [PAD] * (width - len(x)) for x in ids])
            mask = torch.tensor([[1] * len(x) + [0] * (width - len(x)) for x in ids])
            generated = self.model.generate(
                input_ids=input_ids,
                attention_mask=mask,
                num_beams=beam_size,
                num_return_sequences=1,
                do_sample=False,
                max_new_tokens=MAX_DECODE,
                max_length=None,
                min_new_tokens=0,
                early_stopping=beam_size > 1,  # CTranslate2 patience=1: stop at beam_size finished
                length_penalty=1.0,
                repetition_penalty=1.0,
                no_repeat_ngram_size=0,
                decoder_start_token_id=EOS,
                forced_bos_token_id=None,
                forced_eos_token_id=None,
                eos_token_id=EOS,
                pad_token_id=PAD,
            )
            for row, i in zip(generated.tolist(), chunk, strict=True):
                body = row[1:]  # drop the decoder start token
                truncated = EOS not in body
                body = [t for t in body if t != PAD] if truncated else body[: body.index(EOS)]
                results[i] = _Result([[self.inverse[t] for t in body]])
                meta[i] = (len(source[i]), len(body), truncated)
        self.engine_s += time.perf_counter() - started
        self.last = meta
        return [r for r in results if r is not None]


def load_runtime(name: str, cache_dir: str = "") -> Recorder:
    if name == "ct2-cpu":
        return Ct2Runtime()
    return OvRuntime("GPU" if name == "ov-gpu" else "CPU", cache_dir)


def make_engine(runtime: Recorder, name: str, beam: int) -> Any:
    import sentencepiece
    from doctranslator_core.config import MtEngineConfig
    from doctranslator_core.engines.mt import MtEngine, MtRuntime

    config = MtEngineConfig(
        model_dir=CT2_DIR,
        model_family="small100",
        device="cpu",
        compute_type="int8",
        beam_size=beam,
        max_batch_size=MAX_BATCH,
        cpu_threads=THREADS,
    )
    tokenizer = sentencepiece.SentencePieceProcessor(
        model_file=str(CT2_DIR / "sentencepiece.bpe.model")
    )
    return MtEngine(config, runtime=MtRuntime(translator=runtime, tokenizer=tokenizer, device=name))  # type: ignore[arg-type]


# --- Measurement helpers ---------------------------------------------------------------------


def website_active_jobs() -> int:
    if not WEBSITE_DB.exists():
        return 0
    with sqlite3.connect(f"file:{WEBSITE_DB.as_posix()}?mode=ro", uri=True, timeout=5) as db:
        (count,) = db.execute(
            "select count(*) from jobs where status in ('queued', 'running')"
        ).fetchone()
    return int(count)


def _background_windows(since: float) -> list[dict[str, Any]]:
    path = OUT / "background.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines()[-500:]:
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            if row["end"] > since:
                rows.append(row)
    return rows


def _busy(window: dict[str, Any]) -> bool:
    return window["other_cores"] > BUSY_CORES or window["website_active_jobs"] > 0


def wait_for_quiet(log: list[dict[str, Any]]) -> None:
    """Block while the website has active jobs or other processes are busy; record any wait."""
    waited = 0.0
    while website_active_jobs() > 0 or any(
        _busy(w) for w in _background_windows(time.time() - 2 * MONITOR_S)
    ):
        if waited == 0:
            print("  website job or background load; waiting", flush=True)
        time.sleep(MONITOR_S)
        waited += MONITOR_S
    if waited:
        log.append({"at": time.time(), "waited_s": waited})


def wait_for_sustained_quiet(seconds: float) -> None:
    """Block until the monitor's windows covering the last ``seconds`` are all quiet."""
    announced = False
    while True:
        now = time.time()
        windows = _background_windows(now - seconds)
        covered = any(w["start"] <= now - seconds for w in windows)
        if covered and not any(_busy(w) for w in windows) and website_active_jobs() == 0:
            return
        if not announced:
            print(f"  waiting for {seconds:.0f} s of quiet", flush=True)
            announced = True
        time.sleep(MONITOR_S)


def disturbed(start: float, end: float) -> bool:
    """Whether a busy monitor window overlapped [start, end]. For long measurements, first wait
    until the monitor has covered the end, so a disturbance at the very end is not missed."""
    if end - start >= 20:
        deadline = time.time() + 3 * MONITOR_S
        while time.time() < deadline and not any(
            w["end"] >= end for w in _background_windows(end - MONITOR_S)
        ):
            time.sleep(1)
    return website_active_jobs() > 0 or any(
        _busy(w) for w in _background_windows(start) if w["start"] < end
    )


def no_power_throttling() -> None:
    """Opt this process out of Windows execution-speed throttling (EcoQoS), which otherwise slows
    a background process whenever someone is using the foreground."""
    import ctypes
    from ctypes import wintypes

    class _State(ctypes.Structure):
        _fields_ = (
            ("Version", wintypes.ULONG),
            ("ControlMask", wintypes.ULONG),
            ("StateMask", wintypes.ULONG),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    # ProcessPowerThrottling = 4; control EXECUTION_SPEED (1) with state 0 = never throttle.
    state = _State(1, 1, 0)
    if not kernel32.SetProcessInformation(
        kernel32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state)
    ):
        raise OSError(ctypes.get_last_error(), "SetProcessInformation failed")


class CpuMeter:
    """CPU cores this process used over an interval."""

    def __init__(self) -> None:
        self._proc = psutil.Process()

    def start(self) -> None:
        self._wall = time.perf_counter()
        self._own = sum(self._proc.cpu_times()[:2])

    def stop(self) -> dict[str, float]:
        wall = time.perf_counter() - self._wall
        return {"own_cores": (sum(self._proc.cpu_times()[:2]) - self._own) / wall}


def monitor_background(parent: int) -> None:
    """Every 10 s, log other processes' CPU use (excluding the benchmark tree) until ``parent``
    exits. Runs at low priority; system-wide CPU counters over-report on this hybrid CPU."""
    me = psutil.Process()
    me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # type: ignore[attr-defined]

    def snapshot() -> dict[int, tuple[str, float]]:
        skip = {0, me.pid, parent}
        with contextlib.suppress(psutil.Error):
            skip |= {c.pid for c in psutil.Process(parent).children(recursive=True)}
        found: dict[int, tuple[str, float]] = {}
        for proc in psutil.process_iter():
            if proc.pid in skip:
                continue
            try:
                found[proc.pid] = (proc.name(), sum(proc.cpu_times()[:2]))
            except psutil.Error:
                continue
        return found

    with (OUT / "background.jsonl").open("a", encoding="utf-8") as log:
        before, at = snapshot(), time.time()
        while psutil.pid_exists(parent):
            time.sleep(MONITOR_S)
            after, now = snapshot(), time.time()
            deltas = sorted(
                (
                    (cpu - before.get(pid, (name, 0.0))[1], name)
                    for pid, (name, cpu) in after.items()
                ),
                reverse=True,
            )
            wall = now - at
            log.write(
                json.dumps(
                    {
                        "start": at,
                        "end": now,
                        "other_cores": sum(d for d, _ in deltas) / wall,
                        "top": [[n, round(d / wall, 2)] for d, n in deltas[:5]],
                        "website_active_jobs": website_active_jobs(),
                    }
                )
                + "\n"
            )
            log.flush()
            before, at = after, now


def memory() -> dict[str, float]:
    info = psutil.Process().memory_info()
    return {
        "rss_mb": info.rss / 2**20,
        "peak_wset_mb": getattr(info, "peak_wset", info.rss) / 2**20,
        "private_mb": getattr(info, "private", 0) / 2**20,
    }


class GpuSampler:
    """typeperf sampling of this process's GPU engines and GPU memory, once per second."""

    def __init__(self, path: Path) -> None:
        pid = os.getpid()
        self.path = path
        path.unlink(missing_ok=True)
        self._proc = subprocess.Popen(  # noqa: S603 - fixed system tool and arguments
            [  # noqa: S607 - typeperf is a Windows system tool
                "typeperf",
                f"\\GPU Engine(pid_{pid}_*)\\Utilization Percentage",
                f"\\GPU Process Memory(pid_{pid}_*)\\Shared Usage",
                f"\\GPU Process Memory(pid_{pid}_*)\\Dedicated Usage",
                "-si",
                "1",
                "-f",
                "CSV",
                "-o",
                str(path),
                "-y",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> list[dict[str, float]]:
        self._proc.terminate()
        self._proc.wait(timeout=30)
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
        if len(rows) < 2:
            return []
        header = rows[0]
        samples: list[dict[str, float]] = []
        for row in rows[1:]:
            if len(row) != len(header):
                continue
            try:
                at = datetime.strptime(row[0], "%m/%d/%Y %H:%M:%S.%f").timestamp()
            except ValueError:
                continue
            engines: Counter[str] = Counter()
            shared = dedicated = 0.0
            for name, value in zip(header[1:], row[1:], strict=True):
                number = float(value) if value.strip() else 0.0
                if "Utilization Percentage" in name:
                    kind = name.split("engtype_")[-1].split(")")[0] or "other"
                    engines[kind] += number
                elif "Shared Usage" in name:
                    shared += number
                elif "Dedicated Usage" in name:
                    dedicated += number
            busiest = max(engines.values()) if engines else 0.0
            samples.append(
                {
                    "at": at,
                    "busiest_engine_pct": min(100.0, busiest),
                    **{f"engine_{k}_pct": v for k, v in engines.items()},
                    "gpu_shared_mb": shared / 2**20,
                    "gpu_dedicated_mb": dedicated / 2**20,
                }
            )
        return samples


# --- Correctness flags ----------------------------------------------------------------------

TAG = re.compile(r"</?g\d+>|<x\d+/>")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
LATIN = re.compile(r"[A-Za-z]")


def _repeats(units: Sequence[str]) -> bool:
    """Any n-gram (n=1..8) repeated 3+ times back to back (4+ for single units)."""
    for n in range(1, 9):
        need = 4 if n == 1 else 3
        for start in range(len(units) - n * need + 1):
            gram = units[start : start + n]
            if all(units[start + k * n : start + (k + 1) * n] == gram for k in range(need)):
                return True
    return False


def flags(source: str, output: str, direction: str, truncated: bool) -> list[str]:
    target = direction.split("-")[1]
    found: list[str] = []
    text = output.strip()
    if not text:
        return ["empty"] + (["truncated"] if truncated else [])
    if text == source.strip():
        found.append("source_copied")
    if truncated:
        found.append("truncated")
    if Counter(TAG.findall(source)) != Counter(TAG.findall(output)):
        found.append("marker_mismatch")
    plain_src, plain_out = TAG.sub("", source), TAG.sub("", output)
    if target == "en":
        letters = len(LATIN.findall(plain_out)) + len(CJK.findall(plain_out))
        if letters and len(CJK.findall(plain_out)) / letters > 0.2:
            found.append("untranslated_cjk")
        src_units = len(CJK.findall(plain_src))
        ratio = len(LATIN.findall(plain_out)) / src_units if src_units else None
        units: Sequence[str] = plain_out.split()
        if "联想" in source and "lenovo" not in output.lower():
            found.append("lenovo_missing")
    else:
        if not CJK.search(plain_out):
            found.append("no_cjk_output")
        src_units = len(LATIN.findall(plain_src))
        ratio = len(CJK.findall(plain_out)) / src_units if src_units else None
        units = list(plain_out.replace(" ", ""))
        if "Lenovo" in source and "联想" not in output:
            found.append("lenovo_missing")
    if ratio is not None and src_units >= 12:
        low, high = (0.8, 8.0) if target == "en" else (0.12, 1.2)
        if ratio < low:
            found.append("short_output")
        elif ratio > high:
            found.append("long_output")
    if _repeats(units):
        found.append("repetition")
    missing = {n.replace(",", "") for n in NUMBER.findall(plain_src)} - {
        n.replace(",", "") for n in NUMBER.findall(plain_out)
    }
    if missing:
        found.append("number_not_verbatim")
    return found


# --- Text benchmark ---------------------------------------------------------------------------


def run_chunks(
    engine: Any, runtime: Recorder, texts: list[str], direction: str, batch: int
) -> dict[str, Any]:
    from doctranslator_core.types import Language

    source, target = (Language(x) for x in direction.split("-"))
    outputs: list[str] = []
    meta: list[tuple[int, int, bool]] = []
    latencies: list[float] = []
    for start in range(0, len(texts), batch):
        chunk = texts[start : start + batch]
        began = time.perf_counter()
        outputs += engine.translate_batch(chunk, source, target)
        latencies.append(time.perf_counter() - began)
        meta += runtime.last
    return {"outputs": outputs, "meta": meta, "latencies": latencies}


def text_benchmark(name: str, beam: int, cache_dir: str, *, cold_only: bool) -> dict[str, Any]:
    process_started = psutil.Process().create_time()
    imported_at = time.time()
    record: dict[str, Any] = {"runtime": name, "beam": beam, "gpu_cache_dir": cache_dir or None}
    quiet_log: list[dict[str, Any]] = []
    wait_for_quiet(quiet_log)
    record["memory_before_load"] = memory()
    runtime = load_runtime(name, cache_dir)
    record["props"] = runtime.props
    engine = make_engine(runtime, name, beam)
    record["memory_after_load"] = memory()

    # Cold: the first translation after load, then the same input warm.
    probe = ZH_SENTENCES[0]
    began = time.perf_counter()
    cold_output = run_chunks(engine, runtime, [probe], "zh-en", 1)
    first_s = time.perf_counter() - began
    warm_same = []
    for _ in range(REPS):
        began = time.perf_counter()
        run_chunks(engine, runtime, [probe], "zh-en", 1)
        warm_same.append(time.perf_counter() - began)
    record["cold"] = {
        "imports_s": imported_at - process_started,
        **runtime.timings,
        "first_translation_s": first_s,
        "same_input_warm_median_s": statistics.median(warm_same),
        "ready_to_first_result_s": runtime.timings["load_s"]
        + runtime.timings["compile_s"]
        + first_s,
        "first_output": cold_output["outputs"][0],
        "disturbed": disturbed(process_started, time.time()),
    }
    print(
        f"  cold: {json.dumps({k: v for k, v in record['cold'].items() if k.endswith('_s')})}",
        flush=True,
    )

    if cold_only:
        record["memory_end"] = memory()
        return record
    sampler = GpuSampler(OUT / f"gpu-{name}-b{beam}.csv") if name == "ov-gpu" else None
    meter = CpuMeter()
    # Warm-up: the first chunk of every cell, so every batch shape has run once.
    for direction in DIRECTIONS:
        for texts in POOLS[direction].values():
            for batch in BATCHES:
                run_chunks(engine, runtime, texts[:batch], direction, batch)
    cells: list[dict[str, Any]] = []
    for rep in range(1, REPS + 1):
        for direction in DIRECTIONS:
            for category, texts in POOLS[direction].items():
                for batch in BATCHES:
                    for attempt in range(1, ATTEMPTS + 1):
                        wait_for_quiet(quiet_log)
                        start_at = time.time()
                        meter.start()
                        began = time.perf_counter()
                        result = run_chunks(engine, runtime, texts, direction, batch)
                        total = time.perf_counter() - began
                        cpu = meter.stop()
                        busy = disturbed(start_at, time.time())
                        if not busy or attempt == ATTEMPTS:
                            break
                        print(f"  rep{rep} {direction} {category} b{batch}: busy, repeating")
                    cells.append(
                        {
                            "rep": rep,
                            "direction": direction,
                            "category": category,
                            "batch": batch,
                            "total_s": total,
                            "call_latency_median_s": statistics.median(result["latencies"]),
                            "input_tokens": sum(m[0] for m in result["meta"]),
                            "output_tokens": sum(m[1] for m in result["meta"]),
                            "truncated": sum(m[2] for m in result["meta"]),
                            "start_at": start_at,
                            "end_at": start_at + total,
                            "attempts": attempt,
                            "disturbed": busy,
                            **cpu,
                            "outputs": result["outputs"],
                        }
                    )
                    print(
                        f"  rep{rep} {direction} {category:9} b{batch:<2} {total:7.2f}s "
                        f"own={cpu['own_cores']:.1f} cores",
                        flush=True,
                    )
    record["cells"] = cells
    record["memory_after_matrix"] = memory()

    checks: dict[str, Any] = {}
    for direction in DIRECTIONS:
        texts = [t for _, t in CHECKS[direction]]
        single = run_chunks(engine, runtime, texts, direction, 1)
        batched = run_chunks(engine, runtime, texts, direction, len(texts))
        checks[direction] = [
            {
                "id": case_id,
                "source": text,
                "batch1": single["outputs"][i],
                "batch1_truncated": single["meta"][i][2],
                "batched": batched["outputs"][i],
                "batched_truncated": batched["meta"][i][2],
            }
            for i, (case_id, text) in enumerate(CHECKS[direction])
        ]
    record["checks"] = checks
    record["gpu_samples"] = sampler.stop() if sampler else []
    record["quiet_waits"] = quiet_log
    record["memory_end"] = memory()
    return record


# --- Document pipeline ------------------------------------------------------------------------


def document_benchmark(name: str) -> dict[str, Any]:
    from doctranslator_core import build_font_manifest
    from doctranslator_core.config import DocumentLimits
    from doctranslator_core.fit.fonts import FontLibrary
    from doctranslator_core.translator import Translator
    from doctranslator_core.types import DocumentTranslationOptions, FontManifest, Language

    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    manifest_path = OUT / "font-manifest.json"
    began = time.perf_counter()
    previous = (
        FontManifest.model_validate_json(manifest_path.read_text("utf-8"))
        if manifest_path.exists()
        else None
    )
    fonts = build_font_manifest(
        [
            Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
            local / "Microsoft" / "Windows" / "Fonts",
            local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
        ],
        previous=previous,
    )
    manifest_path.write_text(fonts.model_dump_json(), encoding="utf-8")
    manifest_s = time.perf_counter() - began

    quiet_log: list[dict[str, Any]] = []
    wait_for_quiet(quiet_log)
    load_started = time.time()
    runtime = load_runtime(name)
    record: dict[str, Any] = {
        "runtime": name,
        "load_disturbed": disturbed(load_started, time.time()),
        "font_manifest_s": manifest_s,
        "load_s": runtime.timings["load_s"] + runtime.timings["compile_s"],
        "runs": [],
    }
    out_dir = OUT / "documents"
    out_dir.mkdir(parents=True, exist_ok=True)
    options = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
    for beam in (4, 1):
        translator = object.__new__(Translator)  # the pattern Translator.with_mt_decoding uses
        translator._engine = make_engine(runtime, name, beam)
        translator._fonts = fonts
        translator._font_library = FontLibrary(fonts)
        translator._limits = DocumentLimits()
        translator._closed = False
        for fixture in FIXTURES:
            for attempt in range(REPS + 1):  # attempt 0 is the first document after load
                wait_for_quiet(quiet_log)
                phases: list[tuple[str, float]] = []

                def progress(p: Any, phases: list[tuple[str, float]] = phases) -> None:
                    if not phases or phases[-1][0] != str(p.phase):
                        phases.append((str(p.phase), time.perf_counter()))

                with tempfile.TemporaryDirectory() as tmp:
                    source = Path(tmp) / fixture.name
                    source.write_bytes(fixture.read_bytes())
                    target = out_dir / f"{fixture.stem}.{name}.b{beam}{fixture.suffix}"
                    target.unlink(missing_ok=True)
                    runtime.engine_s = 0.0
                    start_at = time.time()
                    began = time.perf_counter()
                    result = translator.translate_document(
                        source, target, options=options, on_progress=progress
                    )
                    ended = time.perf_counter()
                bounds = [*phases, ("end", ended)]
                durations = {
                    phase: bounds[i + 1][1] - at for i, (phase, at) in enumerate(bounds[:-1])
                }
                durations["before_first_progress"] = phases[0][1] - began if phases else 0.0
                dump = result.model_dump(mode="json")
                codes = Counter(d.code for d in result.diagnostics)
                record["runs"].append(
                    {
                        "fixture": str(fixture),
                        "beam": beam,
                        "attempt": attempt,
                        "total_s": ended - began,
                        "disturbed": disturbed(start_at, start_at + ended - began),
                        "engine_s": runtime.engine_s,
                        "phases_s": durations,
                        "pipeline_timings_s": result.timings_s,
                        "counts": dump["counts"],
                        "diagnostic_codes": dict(codes),
                        "empty_translation_preserved": sum(
                            d.count
                            for d in result.diagnostics
                            if d.code == "empty_translation_preserved"
                        ),
                        "fit_status": str(result.fit_status),
                    }
                )
                print(
                    f"  {fixture.name} b{beam} #{attempt} {ended - began:6.2f}s "
                    f"engine={runtime.engine_s:5.2f}s {dict(codes)}",
                    flush=True,
                )
    record["quiet_waits"] = quiet_log
    record["memory_end"] = memory()
    return record


# --- Environment, orchestration and report ---------------------------------------------------


def _powershell(command: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed system tool
        ["powershell", "-NoProfile", "-Command", command],  # noqa: S607 - resolved from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip()


def environment() -> dict[str, Any]:
    import importlib.metadata

    import ctranslate2
    import openvino as ov

    core = ov.Core()
    devices = {}
    for device in core.available_devices:
        entry = {}
        for key in (
            "FULL_DEVICE_NAME",
            "OPTIMIZATION_CAPABILITIES",
            "DEVICE_ARCHITECTURE",
            "GPU_EXECUTION_UNITS_COUNT",
            "GPU_DEVICE_TOTAL_MEM_SIZE",
            "DEVICE_ID",
        ):
            try:
                value = core.get_property(device, key)
            except RuntimeError:
                continue
            entry[key] = value if isinstance(value, (list, int, str)) else str(value)
        devices[device] = entry
    battery = psutil.sensors_battery()
    vocab = json.loads((OV_DIR / "vocab.json").read_text("utf-8"))
    vocab |= json.loads((OV_DIR / "added_tokens.json").read_text("utf-8"))
    shared = json.loads((CT2_DIR / "shared_vocabulary.json").read_text("utf-8"))
    differing = [(i, t) for i, t in enumerate(shared) if vocab.get(t) != i]
    return {
        "host": platform.node(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "cpu": _powershell("(Get-CimInstance Win32_Processor).Name"),
        "logical_cpus": psutil.cpu_count(),
        "physical_cores": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "gpu_driver": _powershell(
            "Get-CimInstance Win32_VideoController | ForEach-Object "
            '{ "$($_.Name) $($_.DriverVersion) $($_.DriverDate)" }'
        ),
        "power_scheme": _powershell("powercfg /getactivescheme"),
        "power_overlay_ac": _powershell(
            "(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\"
            "PowerSchemes').ActiveOverlayAcPowerScheme"
        )
        or "(none: Windows default 'Balanced' power mode)",
        "on_ac_power": battery.power_plugged if battery else None,
        "battery_pct": battery.percent if battery else None,
        "versions": {
            p: importlib.metadata.version(p)
            for p in (
                "openvino",
                "optimum-intel",
                "optimum",
                "transformers",
                "torch",
                "ctranslate2",
                "sentencepiece",
            )
        },
        "ctranslate2_cpu_compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
        "openvino_build": ov.get_version(),
        "openvino_devices": devices,
        "tokenizer_equivalence": {
            "sentencepiece_identical": (OV_DIR / "sentencepiece.bpe.model").read_bytes()
            == (CT2_DIR / "sentencepiece.bpe.model").read_bytes(),
            "hf_vocab_plus_added_tokens_size": len(vocab),
            "ct2_vocabulary_size": len(shared),
            "ct2_ids_absent_from_hf_tables": differing,
            "language_token_ids": {t: vocab[t] for t in ("__en__", "__zh__", "__ja__", "__es__")},
        },
    }


def _summary(values: list[float]) -> dict[str, float]:
    median = statistics.median(values)
    return {
        "median": median,
        "min": min(values),
        "max": max(values),
        "spread_pct": 100 * (max(values) - min(values)) / median if median else 0.0,
    }


def report() -> dict[str, Any]:
    env = json.loads((OUT / "env.json").read_text("utf-8"))
    export = json.loads((OV_DIR / "export.json").read_text("utf-8"))
    log = OUT / "background.jsonl"
    background = (
        [json.loads(line) for line in log.read_text("utf-8").splitlines() if line.strip()]
        if log.exists()
        else []
    )
    text_runs = []
    cold_only_runs = []
    for path in sorted(OUT.glob("text-*.json")):
        run = json.loads(path.read_text("utf-8"))
        if "cells" not in run:
            cold_only_runs.append(run)
            continue
        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
        for cell in run["cells"]:
            grouped.setdefault((cell["direction"], cell["category"], cell["batch"]), []).append(
                cell
            )
        matrix = []
        flag_counts: Counter[str] = Counter()
        flagged_examples: list[dict[str, Any]] = []
        nondeterministic = 0
        for (direction, category, batch), cells in grouped.items():
            totals = [c["total_s"] for c in cells]
            outputs = cells[0]["outputs"]
            nondeterministic += sum(
                any(c["outputs"][i] != outputs[i] for c in cells[1:]) for i in range(len(outputs))
            )
            source = POOLS[direction][category]
            for i, output in enumerate(outputs):
                found = flags(source[i], output, direction, False)
                flag_counts.update(found)
                if found and batch == 32:
                    flagged_examples.append(
                        {
                            "direction": direction,
                            "category": category,
                            "source": source[i],
                            "output": output,
                            "flags": found,
                        }
                    )
            summary = _summary(totals)
            matrix.append(
                {
                    "direction": direction,
                    "category": category,
                    "batch": batch,
                    "total_s": summary,
                    "segments_per_s": len(source) / summary["median"],
                    "output_tokens_per_s": cells[0]["output_tokens"] / summary["median"],
                    "call_latency_median_s": statistics.median(
                        c["call_latency_median_s"] for c in cells
                    ),
                    "own_cpu_cores": statistics.median(c["own_cores"] for c in cells),
                    "background_cores": _background(background, cells),
                    "truncated": max(c["truncated"] for c in cells),
                    "gpu_busiest_engine_pct": _gpu_mean(run["gpu_samples"], cells),
                }
            )
        checks = {
            direction: [
                {
                    **case,
                    "flags_batch1": flags(
                        case["source"], case["batch1"], direction, case["batch1_truncated"]
                    ),
                    "flags_batched": flags(
                        case["source"], case["batched"], direction, case["batched_truncated"]
                    ),
                }
                for case in cases
            ]
            for direction, cases in run["checks"].items()
        }
        gpu = run["gpu_samples"]
        text_runs.append(
            {
                "runtime": run["runtime"],
                "beam": run["beam"],
                "gpu_cache_dir": run["gpu_cache_dir"],
                "props": run["props"],
                "cold": run["cold"],
                "memory": {
                    k: run[k]
                    for k in ("memory_before_load", "memory_after_load", "memory_after_matrix")
                },
                "gpu_memory_max_mb": {
                    "shared": max((s["gpu_shared_mb"] for s in gpu), default=None),
                    "dedicated": max((s["gpu_dedicated_mb"] for s in gpu), default=None),
                },
                "matrix": matrix,
                "matrix_total_median_s": sum(m["total_s"]["median"] for m in matrix),
                "pool_flag_counts": dict(flag_counts),
                "pool_flagged_examples_batch32": flagged_examples,
                "nondeterministic_outputs_across_reps": nondeterministic,
                "checks": checks,
                "quiet_waits": run["quiet_waits"],
            }
        )
    documents = [json.loads(p.read_text("utf-8")) for p in sorted(OUT.glob("doc-*.json"))]
    results = {
        "experiment": "SMALL-100 OpenVINO CPU/GPU vs CTranslate2 CPU",
        "settings": {
            "threads": THREADS,
            "max_batch_size": MAX_BATCH,
            "max_decoding_length": MAX_DECODE,
            "max_input_tokens": MAX_INPUT,
            "reps": REPS,
            "batches": BATCHES,
            "pool_size": 32,
        },
        "environment": env,
        "export": export,
        "text": text_runs,
        "cold_only": cold_only_runs,
        "documents": documents,
        "background": {
            "windows": len(background),
            "other_cores_median": statistics.median(b["other_cores"] for b in background)
            if background
            else None,
            "other_cores_max": max((b["other_cores"] for b in background), default=None),
            "top_processes": Counter(
                name for b in background for name, cores in b["top"] if cores >= 0.5
            ).most_common(8),
            "website_active_job_windows": sum(1 for b in background if b["website_active_jobs"]),
        },
    }
    (OUT / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return results


def _background(background: list[dict[str, Any]], cells: list[dict[str, Any]]) -> float | None:
    """Mean other-process CPU cores over monitor windows overlapping the cells."""
    inside = [
        b["other_cores"]
        for b in background
        if any(b["start"] < c["end_at"] and c["start_at"] < b["end"] for c in cells)
    ]
    return statistics.mean(inside) if inside else None


def _gpu_mean(samples: list[dict[str, float]], cells: list[dict[str, Any]]) -> float | None:
    inside = [
        s["busiest_engine_pct"]
        for s in samples
        if any(c["start_at"] <= s["at"] <= c["end_at"] for c in cells)
    ]
    return statistics.mean(inside) if inside else None


def _done(step: list[str]) -> bool:
    """Whether a step's output already exists (``--skip-existing``)."""
    match step:
        case ["env"]:
            return (OUT / "env.json").exists()
        case ["text", runtime, beam]:
            return (OUT / f"text-{runtime}-b{beam}.json").exists()
        case ["fill-gpu-cache"] | ["text", _, _, "--gpu-cache"]:
            return (OUT / "text-ov-gpu-b1-gpucache.json").exists()
        case ["doc", runtime]:
            return (OUT / f"doc-{runtime}.json").exists()
    return False


def _cold_disturbed(step: list[str]) -> bool:
    if step[0] != "text":
        return False
    suffix = "-gpucache" if "--gpu-cache" in step else ""
    path = OUT / f"text-{step[1]}-b{step[2]}{suffix}.json"
    return bool(json.loads(path.read_text("utf-8"))["cold"].get("disturbed"))


def run_all(only: Callable[[str], bool], *, skip_existing: bool) -> None:
    """Each step in a fresh process, strictly one after another."""
    me = [sys.executable, __file__]
    steps = [["env"]]
    steps += [["text", r, str(b)] for r in RUNTIMES for b in BEAMS]
    steps += [["fill-gpu-cache"], ["text", "ov-gpu", "1", "--gpu-cache"]]  # cached cold start
    steps += [["doc", r] for r in RUNTIMES]
    monitor = subprocess.Popen([*me, "monitor", str(os.getpid())])  # noqa: S603 - this script
    try:
        for step in steps:
            if not only(" ".join(step)) or (skip_existing and _done(step)):
                continue
            for attempt in range(1, ATTEMPTS + 1):
                wait_for_sustained_quiet(60)
                print(f"== {' '.join(step)}", flush=True)
                subprocess.run([*me, *step], check=True)  # noqa: S603 - this script
                if not _cold_disturbed(step) or attempt == ATTEMPTS:
                    break
                print("  cold start overlapped background load; repeating the step", flush=True)
    finally:
        monitor.terminate()
    report()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("env")
    text = sub.add_parser("text")
    text.add_argument("runtime", choices=RUNTIMES)
    text.add_argument("beam", type=int, choices=BEAMS)
    text.add_argument(
        "--gpu-cache", action="store_true", help="cold start only, from a filled GPU model cache"
    )
    sub.add_parser("fill-gpu-cache")
    doc = sub.add_parser("doc")
    doc.add_argument("runtime", choices=RUNTIMES)
    sub.add_parser("report")
    monitor = sub.add_parser("monitor")
    monitor.add_argument("parent", type=int)
    everything = sub.add_parser("all")
    everything.add_argument("--only", default="", help="substring filter on step names")
    everything.add_argument("--skip-existing", action="store_true", help="keep finished steps")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command in ("text", "doc", "fill-gpu-cache"):
        no_power_throttling()

    if args.command == "env":
        (OUT / "env.json").write_text(json.dumps(environment(), indent=2) + "\n", encoding="utf-8")
    elif args.command == "text":
        cache = str(OUT / "gpu-cache") if args.gpu_cache else ""
        suffix = "-gpucache" if args.gpu_cache else ""
        record = text_benchmark(args.runtime, args.beam, cache, cold_only=args.gpu_cache)
        path = OUT / f"text-{args.runtime}-b{args.beam}{suffix}.json"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    elif args.command == "fill-gpu-cache":
        OvRuntime("GPU", str(OUT / "gpu-cache"))
    elif args.command == "doc":
        record = document_benchmark(args.runtime)
        path = OUT / f"doc-{args.runtime}.json"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    elif args.command == "report":
        report()
    elif args.command == "monitor":
        monitor_background(args.parent)
    else:
        run_all(lambda step: args.only in step, skip_existing=args.skip_existing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
