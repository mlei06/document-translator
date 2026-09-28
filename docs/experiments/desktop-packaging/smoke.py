"""Run the frozen CLI with real local MT, outside the checkout. Not a model benchmark."""

# Standalone acceptance script, outside the core: environment isolation/assertions are intentional.
# ruff: noqa: TID251, S101

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("bundle", type=Path)
parser.add_argument("model", type=Path)
parser.add_argument("pptx", type=Path)
args = parser.parse_args()
bundle = args.bundle.resolve()
model = args.model.resolve()
work = Path(tempfile.mkdtemp(prefix="translation probe \u6d4b\u8bd5 "))
exe = bundle / "doctranslator-runtime.exe"
env = {
    key: value
    for key, value in os.environ.items()
    if not key.upper().startswith(("PYTHON", "DOCTRANSLATOR_", "VIRTUAL_ENV"))
}
env.update(
    PATH=str(Path(os.environ["SYSTEMROOT"]) / "System32"),
    DOCTRANSLATOR_MT_MODEL_DIR=str(model),
    DOCTRANSLATOR_MT_DEVICE="cpu",
    DOCTRANSLATOR_MT_COMPUTE_TYPE="int8",
    DOCTRANSLATOR_MT_CPU_THREADS="2",
)
results = {"work_directory": str(work), "runs": []}


def run(name, *command):
    start = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - explicit local build under test; no shell
        [str(exe), *map(str, command)],
        cwd=work,
        env=env,
        capture_output=True,
        timeout=600,
    )
    (work / f"{name}.stdout").write_bytes(completed.stdout)
    (work / f"{name}.stderr").write_bytes(completed.stderr)
    record = {
        "name": name,
        "exit_code": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - start, 3),
    }
    results["runs"].append(record)
    (work / "evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(record), flush=True)
    completed.check_returncode()


print(str(work), flush=True)
run("probe", "--packaging-probe")
run("help", "--help")
source = work / "source.txt"
source.write_text(
    "\u8fd9\u662f\u4e00\u4e2a\u6d4b\u8bd5\u3002\u8bf7\u4fdd\u5b58\u6587\u4ef6\u3002\n",
    encoding="utf-8",
)
slide = work / "source.pptx"
slide.write_bytes(args.pptx.read_bytes())
before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, slide)}
for name, path, source_lang, target_lang in (
    ("txt", source, "zh", "en"),
    ("pptx", slide, "zh", "en"),
):
    output = work / f"translated{path.suffix}"
    run(
        name,
        "translate",
        path,
        "--from",
        source_lang,
        "--to",
        target_lang,
        "--mode",
        "mt",
        "-o",
        output,
        "--json",
    )
    assert before[path.name] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert output.is_file() and output.read_bytes() != path.read_bytes()
    report = json.loads(output.with_name(output.name + ".report.json").read_text(encoding="utf-8"))
    assert report["counts"]["unique_inputs"] > 0, "Fixture must exercise real translation"
    results[name] = {
        "source_sha256": before[path.name],
        "fit_status": report["fit_report"]["status"],
    }
    if name == "pptx":
        with zipfile.ZipFile(output) as package:
            assert package.testzip() is None
results["bundle_bytes"] = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
results["model_bytes"] = sum(path.stat().st_size for path in model.rglob("*") if path.is_file())
(work / "evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2), flush=True)
