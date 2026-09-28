import json
from pathlib import Path

import pytest

from doctranslator_core.types import Language
from doctranslator_eval.datasets import (
    ALL_DIRECTIONS,
    FLORES_FILES,
    Dataset,
    DatasetError,
    Direction,
    flores_dir,
    load_flores,
    load_parallel_jsonl,
)

ZH_EN = Direction(source=Language.ZH, target=Language.EN)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_flores(data_dir: Path, language: Language, texts: dict[int, str]) -> None:
    rows: list[dict[str, object]] = [{"id": key, "text": text} for key, text in texts.items()]
    write_jsonl(flores_dir(data_dir) / f"{FLORES_FILES[language]}.jsonl", rows)


def test_directions() -> None:
    assert len(ALL_DIRECTIONS) == 12
    assert len(set(ALL_DIRECTIONS)) == 12
    assert str(ALL_DIRECTIONS[0]) == "zh-en"
    assert Direction.parse(" ja-es ") == Direction(source=Language.JA, target=Language.ES)
    for bad in ["zh-zh", "zh", "fr-en", "zh-en-ja"]:
        with pytest.raises(ValueError, match=r"direction|same"):
            Direction.parse(bad)


def test_flores_joins_by_id_in_numeric_order(tmp_path: Path) -> None:
    write_flores(tmp_path, Language.ZH, {10: "十", 2: "二"})
    write_flores(tmp_path, Language.EN, {2: "two", 10: "ten"})
    segments = load_flores(tmp_path, ZH_EN)
    assert [(s.id, s.source, s.reference) for s in segments] == [
        ("2", "二", "two"),
        ("10", "十", "ten"),
    ]


def test_flores_id_mismatch_fails(tmp_path: Path) -> None:
    write_flores(tmp_path, Language.ZH, {1: "一", 2: "二"})
    write_flores(tmp_path, Language.EN, {1: "one"})
    with pytest.raises(DatasetError, match="different segment ids"):
        load_flores(tmp_path, ZH_EN)


def test_flores_missing_file_points_to_download(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="download-flores"):
        load_flores(tmp_path, ZH_EN)


def test_parallel_jsonl_filters_by_direction(tmp_path: Path) -> None:
    path = tmp_path / "domain.jsonl"
    write_jsonl(
        path,
        [
            {"id": "a", "source_lang": "zh", "target_lang": "en", "source": "甲", "reference": "A"},
            {"id": "b", "source_lang": "en", "target_lang": "zh", "source": "B", "reference": "乙"},
            {"id": 3, "source_lang": "zh", "target_lang": "en", "source": "丙", "reference": "C"},
        ],
    )
    segments = load_parallel_jsonl(path, ZH_EN)
    assert [(s.id, s.source) for s in segments] == [("a", "甲"), ("3", "丙")]


def test_parallel_jsonl_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "domain.jsonl"
    row: dict[str, object] = {
        "id": "a",
        "source_lang": "zh",
        "target_lang": "en",
        "source": "甲",
        "reference": "A",
    }
    write_jsonl(path, [row, row])
    with pytest.raises(DatasetError, match="duplicate"):
        load_parallel_jsonl(path, ZH_EN)


def test_dataset_specs(tmp_path: Path) -> None:
    assert Dataset("flores").info.name == "flores_plus"
    path = tmp_path / "set.jsonl"
    path.write_text("", encoding="utf-8")
    info = Dataset(f"domain:{path}").info
    assert info.name == "domain:set.jsonl"
    assert info.revision.startswith("sha256:")
    with pytest.raises(DatasetError, match="not found"):
        Dataset(f"domain:{tmp_path / 'missing.jsonl'}")
    with pytest.raises(DatasetError, match="unknown dataset"):
        Dataset("wmt")
