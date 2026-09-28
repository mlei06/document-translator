"""Formatted-translation experiment for P2.0, not production code.

Run from the repository root with the LLM settings in the environment or .env:

    uv run python docs/experiments/formatting/spike.py [--engines llm,mt] [--mt-model-dir DIR]

Question: can inline formatting spans survive translation by SMALL-100 and Gemma when paragraphs
are sent with inline tags, and how does that compare with translating each span separately?

For every case, source language and target language (all 12 directions) it records:
- plain: the paragraph text with all formatting removed, translated as one segment;
- tagged: the paragraph with <gN>...</gN> spans and <xN/> placeholders, translated as one segment,
  then validated (same tag inventory, each tag once, same nesting, non-empty spans);
- segmented: each formatting span translated separately and concatenated in source order.

Meaning is measured separately from formatting: chrF of the tag-stripped tagged output (and of the
segmented output) against the plain output of the same engine. It is a proxy for how much the
markup or splitting disturbs the translation, not a quality score against references.

Writes data/experiments/formatting/results.json (translations included; synthetic text only).
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from sacrebleu.metrics import CHRF

from doctranslator_core import LlmEngineConfig, MtEngineConfig, Translator
from doctranslator_core.types import Language

OUT = Path("data/experiments/formatting")
TAG = re.compile(r"<(/?)g(\d+)>|<x(\d+)/>")

# Parallel synthetic cases. Each value is the tagged paragraph in that language.
CASES: dict[str, dict[str, str]] = {
    "bold-middle": {
        "zh": "请<g1>立即</g1>提交季度报告。",
        "en": "Please submit the quarterly report <g1>immediately</g1>.",
        "ja": "四半期報告書を<g1>直ちに</g1>提出してください。",
        "es": "Por favor, envíe el informe trimestral <g1>de inmediato</g1>.",
    },
    "two-spans": {
        "zh": "<g1>销售额</g1>增长了百分之十二，但<g2>利润</g2>下降了。",
        "en": "<g1>Revenue</g1> grew by twelve percent, but <g2>profit</g2> fell.",
        "ja": "<g1>売上高</g1>は12パーセント増加しましたが、<g2>利益</g2>は減少しました。",
        "es": "Los <g1>ingresos</g1> crecieron un doce por ciento, pero el <g2>beneficio</g2> cayó.",
    },
    "span-at-start": {
        "zh": "<g1>注意：</g1>系统将于周五晚上维护。",
        "en": "<g1>Note:</g1> the system will be under maintenance on Friday night.",
        "ja": "<g1>注意：</g1>システムは金曜日の夜にメンテナンスを行います。",
        "es": "<g1>Nota:</g1> el sistema estará en mantenimiento el viernes por la noche.",
    },
    "span-at-end": {
        "zh": "所有更改必须经过<g1>安全审查</g1>",
        "en": "All changes must pass a <g1>security review</g1>",
        "ja": "すべての変更は<g1>セキュリティレビュー</g1>を通過する必要があります",
        "es": "Todos los cambios deben pasar una <g1>revisión de seguridad</g1>",
    },
    "nested": {
        "zh": "<g1>重要：请在<g2>三月一日</g2>之前完成培训。</g1>",
        "en": "<g1>Important: please complete the training before <g2>March 1</g2>.</g1>",
        "ja": "<g1>重要：<g2>3月1日</g2>までに研修を完了してください。</g1>",
        "es": "<g1>Importante: complete la formación antes del <g2>1 de marzo</g2>.</g1>",
    },
    "link-placeholder": {
        "zh": "详细信息请访问<x1/>或联系支持团队。",
        "en": "For details, visit <x1/> or contact the support team.",
        "ja": "詳細は<x1/>をご覧いただくか、サポートチームにお問い合わせください。",
        "es": "Para más detalles, visite <x1/> o póngase en contacto con el equipo de soporte.",
    },
    "line-break": {
        "zh": "第一阶段：需求分析<x1/>第二阶段：系统设计",
        "en": "Phase one: requirements analysis<x1/>Phase two: system design",
        "ja": "第1段階：要件分析<x1/>第2段階：システム設計",
        "es": "Fase uno: análisis de requisitos<x1/>Fase dos: diseño del sistema",
    },
    "moved-emphasis": {
        "zh": "我们<g1>昨天</g1>在上海签署了合同。",
        "en": "We signed the contract in Shanghai <g1>yesterday</g1>.",
        "ja": "私たちは<g1>昨日</g1>上海で契約に署名しました。",
        "es": "<g1>Ayer</g1> firmamos el contrato en Shanghái.",
    },
    "link-span": {
        "zh": "请阅读<g1>员工手册</g1>中的相关章节。",
        "en": "Please read the relevant section of the <g1>employee handbook</g1>.",
        "ja": "<g1>従業員ハンドブック</g1>の該当する章をお読みください。",
        "es": "Lea la sección correspondiente del <g1>manual del empleado</g1>.",
    },
    "literal-less-than": {
        "zh": "当温度 < 5 度时，<g1>停止</g1>设备运行。",
        "en": "When the temperature is < 5 degrees, <g1>stop</g1> the equipment.",
        "ja": "温度が < 5 度の場合は、装置を<g1>停止</g1>してください。",
        "es": "Cuando la temperatura sea < 5 grados, <g1>detenga</g1> el equipo.",
    },
    "three-spans": {
        "zh": "<g1>红色</g1>表示错误，<g2>黄色</g2>表示警告，<g3>绿色</g3>表示正常。",
        "en": "<g1>Red</g1> means error, <g2>yellow</g2> means warning, <g3>green</g3> means normal.",
        "ja": "<g1>赤</g1>はエラー、<g2>黄色</g2>は警告、<g3>緑</g3>は正常を表します。",
        "es": "El <g1>rojo</g1> indica error, el <g2>amarillo</g2> advertencia y el <g3>verde</g3> normal.",
    },
    "number-span": {
        "zh": "本季度的目标是<g1>1,250</g1>台，比去年增加<g2>15%</g2>。",
        "en": "This quarter's target is <g1>1,250</g1> units, <g2>15%</g2> more than last year.",
        "ja": "今四半期の目標は<g1>1,250</g1>台で、昨年より<g2>15%</g2>増加しています。",
        "es": "El objetivo del trimestre es de <g1>1.250</g1> unidades, un <g2>15 %</g2> más que el año pasado.",
    },
}

MARKUPS = {
    "xml": lambda text: text,
    "bracket": lambda text: TAG.sub(_bracket, text),
}
BRACKET = re.compile(r"\[(/?)g(\d+)\]|\[x(\d+)\]")


def _bracket(match: re.Match[str]) -> str:
    if match.group(3):
        return f"[x{match.group(3)}]"
    return f"[{match.group(1)}g{match.group(2)}]"


def tokens(text: str, markup: str) -> list[tuple[str, str]]:
    """(kind, id) for each tag in order: ("open", n), ("close", n), ("empty", n)."""
    pattern = TAG if markup == "xml" else BRACKET
    found: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        if match.group(3):
            found.append(("empty", match.group(3)))
        elif match.group(1):
            found.append(("close", match.group(2)))
        else:
            found.append(("open", match.group(2)))
    return found


def structure(text: str, markup: str) -> tuple[Counter[tuple[str, str]], dict[str, str], bool]:
    """Tag inventory, parent of each tag, and whether the nesting is well formed."""
    stack: list[str] = []
    parents: dict[str, str] = {}
    well_formed = True
    for kind, ident in tokens(text, markup):
        if kind == "open":
            parents["g" + ident] = stack[-1] if stack else ""
            stack.append(ident)
        elif kind == "close":
            if not stack or stack[-1] != ident:
                well_formed = False
            else:
                stack.pop()
        else:
            parents["x" + ident] = stack[-1] if stack else ""
    return Counter(tokens(text, markup)), parents, well_formed and not stack


def span_texts(text: str, markup: str) -> dict[str, str]:
    """Text directly inside each paired span, tags removed."""
    pattern = TAG if markup == "xml" else BRACKET
    result: dict[str, str] = {}
    for ident in {i for k, i in tokens(text, markup) if k == "open"}:
        if markup == "xml":
            inner = re.search(rf"<g{ident}>(.*?)</g{ident}>", text, re.DOTALL)
        else:
            inner = re.search(rf"\[g{ident}\](.*?)\[/g{ident}\]", text, re.DOTALL)
        result[ident] = pattern.sub("", inner.group(1)) if inner else ""
    return result


def validate(source: str, output: str, markup: str) -> str | None:
    """None if the output's markup corresponds to the source's; otherwise the failure reason."""
    src_inventory, src_parents, _ = structure(source, markup)
    out_inventory, out_parents, well_formed = structure(output, markup)
    if src_inventory != out_inventory:
        return "inventory"
    if not well_formed:
        return "nesting"
    if src_parents != out_parents:
        return "parent"
    if any(not text.strip() for text in span_texts(output, markup).values()):
        return "empty-span"
    return None


def strip(text: str) -> str:
    return BRACKET.sub(" ", TAG.sub(" ", text)).replace("  ", " ").strip()


def pieces(text: str) -> list[str]:
    """Split a tagged paragraph into its formatting pieces (text between any two tags)."""
    return [p for p in TAG.split(text) if p and not p.isdigit() and p != "/"]


def load_env() -> None:
    env = Path(".env")
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def engine(name: str, mt_model_dir: str) -> Translator:
    if name == "llm":
        return Translator(
            LlmEngineConfig.model_validate(
                {
                    "base_url": os.environ["DOCTRANSLATOR_LLM_BASE_URL"],
                    "api_key": os.environ["DOCTRANSLATOR_LLM_API_KEY"],
                    "model": os.environ["DOCTRANSLATOR_LLM_MODEL"],
                }
            )
        )
    return Translator(
        MtEngineConfig(model_dir=Path(mt_model_dir), model_family="small100", compute_type="int8")
    )


def run(name: str, translator: Translator) -> list[dict[str, object]]:
    chrf = CHRF()
    rows: list[dict[str, object]] = []
    markups = ["xml", "bracket"]
    for source in Language:
        for target in Language:
            if source == target:
                continue
            cases = list(CASES.items())
            srcs = [c[source.value] for _, c in cases]
            plain = translator.translate_texts(
                [strip(s) for s in srcs], source=source, target=target
            )
            tagged = {
                m: translator.translate_texts(
                    [MARKUPS[m](s) for s in srcs], source=source, target=target
                )
                for m in markups
            }
            all_pieces = [p for s in srcs for p in pieces(s)]
            translated_pieces = dict(
                zip(
                    all_pieces,
                    translator.translate_texts(all_pieces, source=source, target=target),
                    strict=True,
                )
            )
            for index, (case, _) in enumerate(cases):
                segmented = " ".join(translated_pieces[p].strip() for p in pieces(srcs[index]))
                row: dict[str, object] = {
                    "engine": name,
                    "case": case,
                    "direction": f"{source.value}-{target.value}",
                    "source": srcs[index],
                    "plain": plain[index],
                    "segmented": segmented,
                    "segmented_chrf_vs_plain": round(
                        chrf.sentence_score(segmented, [plain[index]]).score, 1
                    ),
                }
                for m in markups:
                    out = tagged[m][index]
                    failure = validate(MARKUPS[m](srcs[index]), out, m)
                    row[f"{m}_output"] = out
                    row[f"{m}_failure"] = failure
                    row[f"{m}_chrf_vs_plain"] = round(
                        chrf.sentence_score(strip(out), [plain[index]]).score, 1
                    )
                rows.append(row)
    return rows


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for name in sorted({str(r["engine"]) for r in rows}):
        mine = [r for r in rows if r["engine"] == name]
        entry: dict[str, object] = {"cases": len(mine)}
        for m in ("xml", "bracket"):
            valid = [r for r in mine if r[f"{m}_failure"] is None]
            entry[f"{m}_valid"] = len(valid)
            entry[f"{m}_failures"] = dict(
                Counter(str(r[f"{m}_failure"]) for r in mine if r[f"{m}_failure"])
            )
            entry[f"{m}_mean_chrf_vs_plain_valid"] = (
                round(sum(float(str(r[f"{m}_chrf_vs_plain"])) for r in valid) / len(valid), 1)
                if valid
                else None
            )
            entry[f"{m}_valid_by_direction"] = dict(
                Counter(str(r["direction"]) for r in valid)
            )
        entry["segmented_mean_chrf_vs_plain"] = round(
            sum(float(str(r["segmented_chrf_vs_plain"])) for r in mine) / len(mine), 1
        )
        summary[name] = entry
    return summary


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", default="llm,mt")
    parser.add_argument("--mt-model-dir", default="data/models/alirezamsh--small100-ct2-int8")
    args = parser.parse_args()
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    timings: dict[str, float] = {}
    for name in args.engines.split(","):
        started = time.perf_counter()
        with engine(name, args.mt_model_dir) as translator:
            rows.extend(run(name, translator))
        timings[name] = round(time.perf_counter() - started, 1)
    summary = summarize(rows)
    result = {"summary": summary, "timings_s": timings, "rows": rows}
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"summary": summary, "timings_s": timings}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
