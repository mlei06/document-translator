"""Benchmark datasets: FLORES+ and domain sets of parallel sentences."""

import hashlib
import itertools
import json
from pathlib import Path
from typing import cast

from huggingface_hub import hf_hub_download  # pyright: ignore[reportUnknownVariableType]
from huggingface_hub.errors import GatedRepoError
from pydantic import BaseModel, ConfigDict

from doctranslator_core.types import Language

FLORES_REPO = "openlanguagedata/flores_plus"
FLORES_REVISION = "5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06"
FLORES_SPLIT = "devtest"
FLORES_FILES: dict[Language, str] = {
    Language.ZH: "cmn_Hans",
    Language.EN: "eng_Latn",
    Language.JA: "jpn_Jpan",
    Language.ES: "spa_Latn",
}
FLORES_PAGE = f"https://huggingface.co/datasets/{FLORES_REPO}"


class DatasetError(Exception):
    """A dataset is missing, inaccessible, or malformed."""


class Segment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: str
    reference: str


class Direction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Language
    target: Language

    def __str__(self) -> str:
        return f"{self.source.value}-{self.target.value}"

    @classmethod
    def parse(cls, text: str) -> Direction:
        source, _, target = text.strip().partition("-")
        try:
            direction = cls(source=Language(source), target=Language(target))
        except ValueError as exc:
            raise ValueError(f"not a language direction: {text!r}") from exc
        if direction.source == direction.target:
            raise ValueError(f"source and target are the same: {text!r}")
        return direction


ALL_DIRECTIONS: tuple[Direction, ...] = tuple(
    Direction(source=source, target=target)
    for source, target in itertools.permutations(Language, 2)
)
"""The 12 directions, ``zh-en`` first."""


class DatasetInfo(BaseModel):
    """Identifies a dataset version for run manifests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    revision: str
    """FLORES+ revision, or the sha256 of a domain set file."""


class Dataset:
    """A dataset addressed by name on the command line: ``flores`` or ``domain:<path>``."""

    def __init__(self, spec: str) -> None:
        if spec == "flores":
            self._path: Path | None = None
            self.info = DatasetInfo(name="flores_plus", revision=FLORES_REVISION)
        elif spec.startswith("domain:"):
            path = Path(spec.removeprefix("domain:"))
            if not path.is_file():
                raise DatasetError(f"domain set not found: {path}")
            self._path = path
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.info = DatasetInfo(name=f"domain:{path.name}", revision=f"sha256:{digest}")
        else:
            raise DatasetError(f"unknown dataset {spec!r}; use 'flores' or 'domain:<path>'")

    def load(self, data_dir: Path, direction: Direction) -> list[Segment]:
        if self._path is None:
            return load_flores(data_dir, direction)
        return load_parallel_jsonl(self._path, direction)


def flores_dir(data_dir: Path) -> Path:
    return data_dir / "benchmarks" / "flores_plus" / FLORES_REVISION / FLORES_SPLIT


def download_flores(data_dir: Path, token: str | None) -> list[Path]:
    """Download the FLORES+ devtest files for the four languages; skip files already present."""
    root = data_dir / "benchmarks" / "flores_plus" / FLORES_REVISION
    paths: list[Path] = []
    for code in FLORES_FILES.values():
        path = flores_dir(data_dir) / f"{code}.jsonl"
        if not path.is_file():
            try:
                hf_hub_download(
                    FLORES_REPO,
                    f"{FLORES_SPLIT}/{code}.jsonl",
                    repo_type="dataset",
                    revision=FLORES_REVISION,
                    local_dir=root,
                    token=token,
                )
            except GatedRepoError as exc:
                raise DatasetError(
                    f"FLORES+ is gated: accept its terms at {FLORES_PAGE} with the account "
                    "behind HF_TOKEN"
                ) from exc
        paths.append(path)
    return paths


def load_flores(data_dir: Path, direction: Direction) -> list[Segment]:
    sources = _read_flores_file(data_dir, direction.source)
    references = _read_flores_file(data_dir, direction.target)
    if sources.keys() != references.keys():
        raise DatasetError(f"FLORES+ files for {direction} have different segment ids")
    return [
        Segment(id=str(key), source=sources[key], reference=references[key])
        for key in sorted(sources)
    ]


def _read_flores_file(data_dir: Path, language: Language) -> dict[int, str]:
    path = flores_dir(data_dir) / f"{FLORES_FILES[language]}.jsonl"
    if not path.is_file():
        raise DatasetError(f"missing {path}; run 'doctranslator-eval download-flores'")
    rows: dict[int, str] = {}
    for record in _read_jsonl(path):
        key, text = record.get("id"), record.get("text")
        if not isinstance(key, int) or not isinstance(text, str):
            raise DatasetError(f"malformed FLORES+ row in {path}")
        rows[key] = text
    return rows


def load_parallel_jsonl(path: Path, direction: Direction) -> list[Segment]:
    """Rows ``{"id", "source_lang", "target_lang", "source", "reference"}`` for ``direction``."""
    segments: list[Segment] = []
    seen: set[str] = set()
    for record in _read_jsonl(path):
        key = record.get("id")
        if not isinstance(key, str | int):
            raise DatasetError(f"row without an id in {path}")
        key = str(key)
        if key in seen:
            raise DatasetError(f"duplicate id {key!r} in {path}")
        seen.add(key)
        if (
            record.get("source_lang") != direction.source.value
            or record.get("target_lang") != direction.target.value
        ):
            continue
        source, reference = record.get("source"), record.get("reference")
        if not isinstance(source, str) or not isinstance(reference, str):
            raise DatasetError(f"row {key!r} in {path} lacks source or reference text")
        segments.append(Segment(id=key, source=source, reference=reference))
    return segments


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record: object = json.loads(line)
            except ValueError as exc:
                raise DatasetError(f"invalid JSON on line {number} of {path}") from exc
            if not isinstance(record, dict):
                raise DatasetError(f"line {number} of {path} is not an object")
            records.append(cast(dict[str, object], record))
    return records
