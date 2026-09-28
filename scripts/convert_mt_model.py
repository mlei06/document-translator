"""Convert SMALL-100 to a CTranslate2 model for MT mode (ADR-006).

Runs in a throwaway environment so PyTorch never enters the lockfile. From the repository root:

    uv run --no-project --python 3.14 --with ctranslate2 --with "transformers[torch]>=5,<6" \
        --with sentencepiece --with huggingface-hub scripts/convert_mt_model.py

SMALL-100's weights and config are combined with M2M100's tokenizer files (byte-identical to
SMALL-100's), so the conversion never loads or executes the custom ``tokenization_small100.py``.
"""

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from huggingface_hub import hf_hub_download  # pyright: ignore[reportUnknownVariableType]

MODEL_REPO = "alirezamsh/small100"
MODEL_REVISION = "8ab680e26a596d2e3d2d2d17ae0f68df1037328c"
MODEL_FILES = ["config.json", "model.safetensors"]
TOKENIZER_REPO = "facebook/m2m100_418M"
TOKENIZER_REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
TOKENIZER_FILES = [
    "sentencepiece.bpe.model",
    "vocab.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]
ENGINE_FILES = ["sentencepiece.bpe.model"]
"""Tokenizer files the MT engine reads at runtime, copied next to ``model.bin``."""


class _Converter(Protocol):
    def convert(self, output_dir: str, *, quantization: str | None, force: bool) -> str: ...


class _ConverterFactory(Protocol):
    def __call__(self, model_name_or_path: str, *, copy_files: list[str]) -> _Converter: ...


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert SMALL-100 to CTranslate2 (ADR-006).")
    parser.add_argument("--quantization", default="int8", help="CTranslate2 quantization")
    parser.add_argument("--output-root", type=Path, default=Path("data/models"))
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    args = parser.parse_args()
    quantization: str = args.quantization
    output_root: Path = args.output_root
    force: bool = args.force

    output_dir = output_root / f"{MODEL_REPO.replace('/', '--')}-ct2-{quantization}"
    if output_dir.exists() and not force:
        print(f"{output_dir} exists; pass --force to replace it", file=sys.stderr)
        return 1

    from ctranslate2.converters import (  # pyright: ignore[reportMissingTypeStubs]
        TransformersConverter,
    )

    token = os.environ.get("HF_TOKEN") or None
    with tempfile.TemporaryDirectory(prefix="small100-") as tmp:
        source = Path(tmp)
        for repo, revision, files in (
            (MODEL_REPO, MODEL_REVISION, MODEL_FILES),
            (TOKENIZER_REPO, TOKENIZER_REVISION, TOKENIZER_FILES),
        ):
            for name in files:
                downloaded = hf_hub_download(repo, name, revision=revision, token=token)
                shutil.copyfile(downloaded, source / name)

        factory = cast(_ConverterFactory, TransformersConverter)
        converter = factory(str(source), copy_files=ENGINE_FILES)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        converter.convert(str(output_dir), quantization=quantization, force=True)

    record = {
        "model": {"repo": MODEL_REPO, "revision": MODEL_REVISION, "files": MODEL_FILES},
        "tokenizer": {
            "repo": TOKENIZER_REPO,
            "revision": TOKENIZER_REVISION,
            "files": TOKENIZER_FILES,
        },
        "quantization": quantization,
        "ctranslate2": importlib.metadata.version("ctranslate2"),
        "transformers": importlib.metadata.version("transformers"),
        "converted_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (output_dir / "conversion.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
