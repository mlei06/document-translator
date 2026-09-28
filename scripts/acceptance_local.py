"""Local-CLI acceptance run with real engines: every fixture format through ``doctranslator translate``.

Usage (from the repository root, with LLM settings in the environment or .env and
DOCTRANSLATOR_MT_MODEL_DIR set):

    uv run python scripts/acceptance_local.py --out data/acceptance/p2 [--modes llm,mt] [--to en]

For each fixture and mode, copies the fixture into ``--out``, runs the real CLI in a subprocess,
and records: exit code, input SHA-256 before/after, output SHA-256, source-script characters left
in the output's text (per part), formatting fallbacks, diagnostics and fit status. Writes
``summary.json`` in ``--out``. Native-application opens are a separate step
(scripts/native_office_check.ps1) because they need Office.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

FIXTURES = {
    "txt": None,
    "pptx": Path("tests/fixtures/pptx/deck.pptx"),
    "docx": Path("tests/fixtures/docx/report.docx"),
    "xlsx": Path("tests/fixtures/xlsx/features-shared.xlsx"),
}
TXT_SAMPLE = (
    "季度业务回顾\r\n\r\n销售额增长了百分之十二，利润率保持稳定。\r\n"
    "  详情请访问 https://intranet.example.com/q3 或联系支持团队。\r\n12,345\r\n"
)
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
TEXT_TAG = re.compile(rb"<(?:a|w|s):t(?: [^>]*)?>([^<]*)</(?:a|w|s):t>")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leftover(path: Path) -> dict[str, int]:
    """Source-script characters remaining in each part's text nodes (or the whole TXT)."""
    if path.suffix == ".txt":
        count = len(CJK.findall(path.read_text(encoding="utf-8")))
        return {"text": count} if count else {}
    found: dict[str, int] = {}
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if not name.endswith(".xml"):
                continue
            text = b"".join(TEXT_TAG.findall(package.read(name))).decode("utf-8", "replace")
            count = len(CJK.findall(text))
            if count:
                found[name] = count
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--modes", default="llm,mt")
    parser.add_argument("--to", default="en")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for mode in args.modes.split(","):
        for fmt, fixture in FIXTURES.items():
            source = args.out / f"{fmt}-{mode}.{fmt}"
            output = args.out / f"{fmt}-{mode}.{args.to}.{fmt}"
            for stale in (output, output.with_name(output.name + ".report.json")):
                stale.unlink(missing_ok=True)
            if fixture is None:
                source.write_bytes(TXT_SAMPLE.encode("utf-8"))
            else:
                shutil.copyfile(fixture, source)
            before = sha(source)
            command = [sys.executable, "-c", "from doctranslator_cli.main import main; main()",
                       "translate", str(source), "--to", args.to, "--from", "zh",
                       "--mode", mode, "--json"]
            completed = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
                command, capture_output=True, text=True, encoding="utf-8", check=False
            )
            row: dict[str, object] = {
                "format": fmt, "mode": mode, "exit": completed.returncode,
                "input_unchanged": sha(source) == before,
            }
            if completed.returncode == 0:
                result = json.loads(completed.stdout)
                row |= {
                    "output": str(output),
                    "output_sha256": sha(output),
                    "engine": result["engine"],
                    "segments": result["counts"]["segments"],
                    "unique_inputs": result["counts"]["unique_inputs"],
                    "formatting_fallbacks": result["counts"]["formatting_fallbacks"],
                    "fit_status": result["fit_report"]["status"],
                    "diagnostics": sorted({d["code"] for d in result["diagnostics"]}),
                    "source_script_left": leftover(output),
                }
            else:
                row["stderr"] = completed.stderr[-2000:]
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("format", "mode", "exit")}), flush=True)
    (args.out / "summary.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
