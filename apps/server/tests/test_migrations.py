"""Migration 0002 converts 0001 storage into ADR-014 documents, current translations and results."""

import sqlite3
from pathlib import Path

from doctranslator_server.db import Database

NOW = "2026-09-28 10:00:00"
LATER = "2026-09-28 11:00:00"


def _insert(conn: sqlite3.Connection, table: str, **values: object) -> None:
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    statement = f"INSERT INTO {table} ({columns}) VALUES ({marks})"  # noqa: S608 - literal names
    conn.execute(statement, list(values.values()))


def _job(conn: sqlite3.Connection, job_id: str, blob: str, target: str, created: str) -> None:
    _insert(
        conn,
        "jobs",
        id=job_id,
        owner_id="u1",
        request_hash="r" + job_id,
        kind="translate",
        original_name="deck.pptx",
        format="pptx",
        input_blob=blob,
        input_size=10,
        options="{}",
        mode="mt",
        source_requested="auto",
        source_resolved="zh",
        target=target,
        fingerprint="fp",
        force=0,
        status="succeeded",
        attempts=1,
        max_attempts=3,
        available_at=created,
        cancel_requested=0,
        phase="done",
        progress_done=1,
        progress_total=1,
        cache_hit=0,
        created_at=created,
        fit_status="passed",
        result_id="cache1" if job_id == "j1" else None,
    )


def test_0001_data_converts_without_losing_results(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    database = Database(f"sqlite:///{path.as_posix()}")
    database.migrate("0001")
    database.dispose()
    conn = sqlite3.connect(path)
    _insert(conn, "users", id="u1", display_name="Alice", kind="person", active=1, created_at=NOW)
    for digest in ("src", "out1", "rep1", "out2", "rep2", "out3", "rep3"):
        _insert(conn, "blobs", hash=digest, size=10, state="available", created_at=NOW)
    _insert(
        conn,
        "translation_results",
        id="cache1",
        input_hash="src",
        fingerprint="fp",
        output_blob="out1",
        report_blob="rep1",
        source_resolved="zh",
        fit_status="passed",
        engine='{"model": "small100"}',
        created_at=NOW,
        last_used_at=NOW,
    )
    rows = [
        ("j1", "en", NOW, "out1", "rep1"),
        ("j2", "en", LATER, "out2", "rep2"),
        ("j3", "ja", NOW, "out3", "rep3"),
    ]
    for index, (job_id, target, created, out, rep) in enumerate(rows):
        _job(conn, job_id, "src", target, created)
        _insert(
            conn,
            "documents",
            id=f"d{index}",
            owner_id="u1",
            job_id=job_id,
            original_name="deck.pptx",
            format="pptx",
            original_blob="src",
            source_requested="auto",
            source_resolved="zh",
            target=target,
            mode="mt",
            fingerprint="fp",
            fit_status="passed",
            created_at=created,
            expires_at=LATER,
        )
        _insert(
            conn,
            "document_versions",
            id=f"v{index}",
            document_id=f"d{index}",
            version_no=0,
            output_blob=out,
            report_blob=rep,
            created_by="translation",
            created_at=created,
        )
    conn.commit()
    conn.close()

    database = Database(f"sqlite:///{path.as_posix()}")
    database.migrate()
    assert database.current_revision() == "0007"
    database.dispose()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT kind FROM users").fetchall() == [("human",)]
    assert conn.execute("SELECT count(*) FROM documents").fetchone() == (1,)  # merged by bytes
    results = dict(conn.execute("SELECT job_id, output_blob FROM job_results").fetchall())
    assert results == {"j1": "out1", "j2": "out2", "j3": "out3"}  # every result kept
    current = dict(
        conn.execute(
            "SELECT t.target, r.job_id FROM document_translations t "
            "JOIN job_results r ON r.id = t.current_result_id"
        ).fetchall()
    )
    assert current == {"en": "j2", "ja": "j3"}  # the newest result per language is current
    expiring = conn.execute(
        "SELECT job_id FROM job_results WHERE expires_at IS NOT NULL"
    ).fetchall()
    assert expiring == [("j1",)]  # the older English result is superseded
    engine = conn.execute("SELECT engine FROM job_results WHERE job_id = 'j1'").fetchone()[0]
    assert "small100" in engine
    assert conn.execute("SELECT count(*) FROM jobs WHERE phase = 'done'").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM jobs WHERE result_id IS NULL").fetchone() == (0,)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"translation_results", "document_versions", "legacy_documents"} & tables
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_password_upgrade_preserves_existing_key_sessions(tmp_path: Path) -> None:
    path = tmp_path / "accounts.db"
    database = Database(f"sqlite:///{path.as_posix()}")
    try:
        database.migrate("0003")
        with sqlite3.connect(path) as conn:
            _insert(
                conn,
                "users",
                id="u",
                display_name="Existing",
                kind="human",
                active=1,
                created_at=NOW,
            )
            _insert(
                conn,
                "api_keys",
                id="k",
                user_id="u",
                prefix="abcdefghijkl",
                digest="digest",
                label="Existing",
                created_at=NOW,
            )
            _insert(
                conn,
                "sessions",
                id="s",
                user_id="u",
                api_key_id="k",
                token_digest="token",  # noqa: S106 - inert migration fixture digest
                csrf_digest="csrf",
                created_at=NOW,
                last_seen_at=NOW,
                expires_at=LATER,
            )
        conn.close()
        database.migrate()
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT user_id, api_key_id FROM sessions").fetchall() == [
                ("u", "k")
            ]
            assert conn.execute("SELECT email, password_hash FROM users").fetchall() == [
                (None, None)
            ]
            assert conn.execute("SELECT translation_settings FROM users").fetchall() == [("{}",)]
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()
    finally:
        database.dispose()
