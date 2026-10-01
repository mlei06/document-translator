# /// script
# requires-python = "==3.13.*"
# dependencies = [
#     "openvino==2026.4.0",
#     "openvino-tokenizers==2026.4.0.0",
#     "optimum-intel==2.2.0",
#     "optimum==2.3.0",
#     "transformers==5.5.4",
#     "torch==2.14.0",
#     "nncf==3.4.0",
#     "sentencepiece==0.2.2",
#     "huggingface-hub",
# ]
# ///
"""Export SMALL-100 to OpenVINO IR for the OpenVINO experiment, not production code.

Run from the repository root:

    uv run --no-project docs/experiments/openvino-small100/export.py

Python 3.13 on purpose: under 3.14 ``functools.partial`` is a method descriptor, and Optimum's
class-level ``NormalizedSeq2SeqConfig.with_args(...)`` then receives ``self`` as an extra positional
argument (``TypeError: got multiple values for argument 'allow_new'``). Inference runs on 3.14.

Uses the same pinned inputs as ``scripts/convert_mt_model.py``: SMALL-100's weights and config plus
M2M100's byte-identical tokenizer files, so SMALL-100's custom tokenizer code is never loaded.
Writes FP32 weights (the checkpoint's own precision) and ``export.json`` under
data/experiments/openvino-small100/models/.
"""

import hashlib
import importlib.metadata
import json
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import hf_hub_download

MODEL_REPO = "alirezamsh/small100"
MODEL_REVISION = "8ab680e26a596d2e3d2d2d17ae0f68df1037328c"
TOKENIZER_REPO = "facebook/m2m100_418M"
TOKENIZER_REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
SOURCES = [
    (MODEL_REPO, MODEL_REVISION, ["config.json", "model.safetensors"]),
    (
        TOKENIZER_REPO,
        TOKENIZER_REVISION,
        [
            "sentencepiece.bpe.model",
            "vocab.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
        ],
    ),
]
OUT = Path("data/experiments/openvino-small100/models/small100-ov-fp32")


def main() -> int:
    from optimum.exporters.openvino import main_export

    if OUT.exists():
        shutil.rmtree(OUT)
    with tempfile.TemporaryDirectory(prefix="small100-ov-") as tmp:
        source = Path(tmp)
        for repo, revision, files in SOURCES:
            for name in files:
                shutil.copyfile(hf_hub_download(repo, name, revision=revision), source / name)
        started = time.perf_counter()
        main_export(
            model_name_or_path=str(source),
            output=str(OUT),
            task="text2text-generation-with-past",
            convert_tokenizer=False,
        )
        export_s = time.perf_counter() - started

    # Without sentencepiece installed, Optimum skips saving the tokenizer without an error.
    for required in ("sentencepiece.bpe.model", "vocab.json", "added_tokens.json"):
        if not (OUT / required).is_file():
            raise SystemExit(f"export did not write {required}")

    files = {
        p.name: {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(OUT.iterdir())
        if p.is_file()
    }
    record = {
        "model": {"repo": MODEL_REPO, "revision": MODEL_REVISION},
        "tokenizer": {"repo": TOKENIZER_REPO, "revision": TOKENIZER_REVISION},
        "task": "text2text-generation-with-past",
        "weight_format": "fp32 (no --weight-format; models under 1B parameters are not compressed)",
        "export_s": round(export_s, 2),
        "python": sys.version.split()[0],
        "versions": {
            p: importlib.metadata.version(p)
            for p in ("openvino", "optimum-intel", "optimum", "transformers", "torch", "nncf")
        },
        "files": files,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (OUT / "export.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("export_s", "python", "versions")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
