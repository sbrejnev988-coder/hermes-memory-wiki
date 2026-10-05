"""Focused F02/F03/F04 regressions using real owned SQLite connections."""
from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

import decay


NOW = 2_000_000_000
SCHEMA = """
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    topic TEXT,
    confidence REAL,
    salience REAL,
    access_count INTEGER,
    status TEXT,
    updated_at INTEGER,
    freshness_at INTEGER,
    pinned INTEGER
);
"""


def claim(claim_id, **overrides):
    row = {
        "id": claim_id,
        "topic": "audit-fixture",
        "confidence": 0.7,
        "salience": 0.7,
        "access_count": 0,
        "status": "active",
        "updated_at": NOW - 20 * 86400,
        "freshness_at": NOW - 20 * 86400,
        "pinned": 0,
    }
    row.update(overrides)
    return tuple(row[column] for column in (
        "id", "topic", "confidence", "salience", "access_count", "status",
        "updated_at", "freshness_at", "pinned",
    ))


@pytest.fixture
def owned_sqlite(monkeypatch):
    """Retain real scanner-owned connections until assertions, then close ours."""
    original_connect = sqlite3.connect
    retained = []
    monkeypatch.setattr(decay.time, "time", lambda: NOW)

    def install(rows=(), *, create_table=True):
        def connect(database, *args, **kwargs):
            assert database == ":memory:", "Only synthetic in-memory DBs are allowed"
            connection = original_connect(database, *args, **kwargs)
            retained.append(connection)
            if create_table:
                connection.executescript(SCHEMA)
                connection.executemany(
                    "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
                )
                connection.commit()
            return connection

        monkeypatch.setattr(decay.sqlite3, "connect", connect)
        return retained

    yield install
    # Never let GC hide whether production closed its owned resource.
    for connection in retained:
        connection.close()


@pytest.mark.parametrize("field", ["confidence", "salience"])
def test_f02_preserves_real_zero_quality(owned_sqlite, field):
    owned_sqlite([
        claim("zero", **{field: 0.0}),
        claim("near-zero", **{field: 0.01}),
        claim("null-default", **{field: None}),
        claim("inactive", status="archived", **{field: 0.0}),
    ])

    stale = decay.scan_decay(":memory:", threshold=0.15)

    assert [row["id"] for row in stale] == ["zero", "near-zero"]
    assert [row["decay"] for row in stale] == [0.0, 0.0]
    assert stale[0][field] == 0.0
    assert all(row["days"] == 20.0 for row in stale)
    # NULL still uses .7; archived rows stay outside the scan.
    expanded = decay.scan_decay(":memory:", threshold=0.5)
    assert [row["id"] for row in expanded] == ["zero", "near-zero", "null-default"]
    assert expanded[-1]["decay"] == 0.3878
    assert expanded[-1][field] is None


def test_f03_builds_eligible_membership_once(owned_sqlite, monkeypatch):
    import builtins

    old = NOW - 80 * 86400
    owned_sqlite([
        claim("eligible", confidence=0.69, freshness_at=old),
        claim("at-high-confidence-boundary", confidence=0.7, freshness_at=old),
        claim("pinned", confidence=0.69, freshness_at=old, pinned=1),
    ])
    builds = []

    def counted_set(values):
        builds.append(list(values))
        return builtins.set(values)

    monkeypatch.setattr(decay, "set", counted_set, raising=False)

    result = decay.archive_stale_claims(":memory:", threshold=0.05)

    assert builds == [["eligible"]], "Rebuilding set(ids) per stale row is quadratic"
    assert result == {
        "stale": 3, "eligible": 1, "protected": 2,
        "protected_ids": ["at-high-confidence-boundary", "pinned"],
        "dry_run": True, "ids": ["eligible"],
    }


def assert_closed(connection):
    closed = False
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError as error:
        closed = "closed" in str(error).lower()
    assert closed, "The function-owned SQLite connection is still queryable"


@pytest.mark.parametrize("operation", ["scan_decay", "get_decay_stats"])
@pytest.mark.parametrize("scenario", ["normal", "empty", "missing_table", "row_error"])
def test_f04_closes_owned_sqlite_before_return_or_error(
    owned_sqlite, monkeypatch, operation, scenario,
):
    retained = owned_sqlite(
        [] if scenario == "empty" else [claim("zero", confidence=0.0, salience=0.0)],
        create_table=scenario != "missing_table",
    )
    if scenario == "row_error":
        def broken_row(cursor, values):
            raise RuntimeError("synthetic row conversion failure")
        monkeypatch.setattr(decay.sqlite3, "Row", broken_row)

    function = getattr(decay, operation)
    if scenario == "missing_table":
        with pytest.raises(sqlite3.OperationalError, match="no such table: claims"):
            function(":memory:")
    elif scenario == "row_error":
        with pytest.raises(RuntimeError, match="synthetic row conversion failure"):
            function(":memory:")
    else:
        result = function(":memory:")
        if operation == "scan_decay":
            assert [item["id"] for item in result] == ([] if scenario == "empty" else ["zero"])
        else:
            assert result["total"] == (0 if scenario == "empty" else 1)
            assert result["avg_conf"] == (None if scenario == "empty" else 0.0)
            assert result["avg_sal"] == (None if scenario == "empty" else 0.0)

    assert len(retained) == 1
    assert_closed(retained[0])


def test_f04_scanner_closes_before_post_fetch_conversion_error(owned_sqlite):
    retained = owned_sqlite([claim("bad-numeric", confidence="not-a-float")])

    with pytest.raises(ValueError, match="could not convert string to float"):
        decay.scan_decay(":memory:")

    assert_closed(retained[0])


def test_real_sqlite_transaction_context_does_not_close_connection():
    # Positive control: a Connection's transaction context is NOT its owner lifetime.
    with closing(sqlite3.connect(":memory:")) as connection:
        with connection:
            connection.execute("CREATE TABLE control(value INTEGER)")
            connection.execute("INSERT INTO control VALUES (1)")
        assert connection.execute("SELECT value FROM control").fetchone() == (1,)
    assert_closed(connection)


def test_callback_receives_all_ids_while_display_is_capped(owned_sqlite):
    old = NOW - 80 * 86400
    eligible = [f"eligible-{index:03d}" for index in range(80)]
    protected = [f"protected-{index:03d}" for index in range(55)]
    rows = [claim(identity, confidence=0.1, freshness_at=old) for identity in eligible]
    rows += [
        claim(identity, confidence=0.0, salience=0.0, pinned=1)
        if index % 2 else claim(identity, confidence=0.7, salience=0.0)
        for index, identity in enumerate(protected)
    ]
    rows.append(claim("already-archived", confidence=0.0, status="archived"))
    calls = []
    # This is callback-owned storage, not a replaced/stubbed MemoryProvider.
    with closing(sqlite3.connect(":memory:")) as callback_database:
        callback_database.executescript(SCHEMA)
        callback_database.executemany(
            "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )
        callback_database.commit()
        retained = owned_sqlite(rows)

        def archive_callback(ids, *, reason, change_type):
            assert len(retained) == 1
            assert_closed(retained[0])
            calls.append((list(ids), reason, change_type))
            with callback_database:
                callback_database.executemany(
                    "UPDATE claims SET status='archived' WHERE id=?", [(identity,) for identity in ids],
                )
            return str(len(ids))

        result = decay.archive_stale_claims(
            ":memory:", threshold=0.05, dry_run=False, archive_callback=archive_callback,
        )

        assert calls == [(eligible, "decay_score_below_0.0500", "decay_archive")]
        assert result == {
            "stale": len(eligible) + len(protected),
            "eligible": len(eligible), "protected": len(protected),
            "protected_ids": protected[:50], "dry_run": False,
            "ids": eligible[:50], "archived": len(eligible),
        }
        states = dict(callback_database.execute("SELECT id, status FROM claims"))
        assert all(states[identity] == "archived" for identity in eligible)
        assert all(states[identity] == "active" for identity in protected)
        assert states["already-archived"] == "archived"
        assert callback_database.execute("SELECT 1").fetchone() == (1,)
    assert_closed(callback_database)


def test_dry_run_never_invokes_archival_callback(owned_sqlite):
    retained = owned_sqlite([
        claim("eligible", confidence=0.0),
        claim("pinned", confidence=0.0, pinned=1),
        claim("high-confidence", confidence=0.7, salience=0.0),
    ])

    def forbidden_callback(*args, **kwargs):
        pytest.fail("dry_run must never mutate via callback")

    result = decay.archive_stale_claims(":memory:", archive_callback=forbidden_callback)

    assert result == {
        "stale": 3, "eligible": 1, "protected": 2,
        "protected_ids": ["pinned", "high-confidence"],
        "dry_run": True, "ids": ["eligible"],
    }
    assert len(retained) == 1
    assert_closed(retained[0])


@pytest.mark.parametrize("rows", [
    [],
    [claim("high-confidence", salience=0.0), claim("pinned", confidence=0.0, pinned=1)],
])
def test_no_eligible_claims_does_not_invoke_callback(owned_sqlite, rows):
    owned_sqlite(rows)

    def forbidden_callback(*args, **kwargs):
        pytest.fail("No eligible IDs must be an archival no-op")

    result = decay.archive_stale_claims(
        ":memory:", dry_run=False, archive_callback=forbidden_callback,
    )

    assert result["stale"] == len(rows)
    assert result["eligible"] == 0
    assert result["protected"] == len(rows)
    assert result["ids"] == []
    assert "archived" not in result
    assert result["dry_run"] is False


def test_mutating_mode_without_callback_still_refuses_archival(owned_sqlite):
    owned_sqlite([claim("eligible", confidence=0.0)])

    result = decay.archive_stale_claims(":memory:", dry_run=False)

    assert result == {
        "stale": 1, "eligible": 1, "protected": 0, "protected_ids": [],
        "dry_run": False, "ids": ["eligible"], "archived": 0,
        "error": "archive_callback is required to preserve FTS/Qdrant consistency",
    }


@pytest.mark.parametrize("returned, archived", [(None, 0), (0, 0), ("1", 1)])
def test_callback_result_conversion_is_unchanged(owned_sqlite, returned, archived):
    owned_sqlite([claim("eligible", confidence=0.0)])
    calls = []

    def archive_callback(ids, **metadata):
        calls.append((list(ids), metadata))
        return returned

    result = decay.archive_stale_claims(
        ":memory:", dry_run=False, archive_callback=archive_callback,
    )

    assert calls == [(["eligible"], {
        "reason": "decay_score_below_0.0500", "change_type": "decay_archive",
    })]
    assert result["archived"] == archived


def test_callback_exception_propagates_after_scanner_closes(owned_sqlite):
    retained = owned_sqlite([claim("eligible", confidence=0.0)])
    failure = RuntimeError("synthetic callback failure")

    def failing_callback(ids, **metadata):
        assert ids == ["eligible"]
        assert_closed(retained[0])
        raise failure

    with pytest.raises(RuntimeError) as caught:
        decay.archive_stale_claims(
            ":memory:", dry_run=False, archive_callback=failing_callback,
        )

    assert caught.value is failure
    assert len(retained) == 1
    assert_closed(retained[0])


@pytest.mark.parametrize("confidence, pinned, eligible", [
    (0.0, 0, True), (0.699999, 0, True), (0.7, 0, False), (0.9, 0, False),
    (0.0, 1, False), (0.699999, 1, False),
])
def test_high_confidence_and_pinned_protections_are_unchanged(
    owned_sqlite, confidence, pinned, eligible,
):
    owned_sqlite([claim("candidate", confidence=confidence, salience=0.0, pinned=pinned)])

    result = decay.archive_stale_claims(":memory:")

    assert result["stale"] == 1
    assert result["eligible"] == int(eligible)
    assert result["protected"] == int(not eligible)
    assert result["ids"] == (["candidate"] if eligible else [])
    assert result["protected_ids"] == ([] if eligible else ["candidate"])


@pytest.mark.parametrize("threshold, expected_ids", [
    (-1.0, []), (0.0, []), (0.15, ["zero"]), (2.0, ["zero", "default"]),
])
def test_scan_threshold_clamping_and_strict_comparison_stay_unchanged(
    owned_sqlite, threshold, expected_ids,
):
    owned_sqlite([
        claim("zero", confidence=0.0), claim("default"),
        claim("fresh", confidence=0.0, freshness_at=NOW),
    ])

    result = decay.scan_decay(":memory:", threshold=threshold)

    assert [row["id"] for row in result] == expected_ids


def test_stats_still_aggregate_only_active_rows_with_sql_null_semantics(owned_sqlite):
    recent = NOW - 10 * 86400
    owned_sqlite([
        claim("zero", confidence=0.0, salience=0.0, access_count=0),
        claim("normal", access_count=4, freshness_at=recent),
        claim("null", confidence=None, salience=None, access_count=2, freshness_at=None),
        claim("inactive", status="archived", access_count=100, freshness_at=NOW),
    ])

    result = decay.get_decay_stats(":memory:")

    assert result == {
        "total": 3, "avg_conf": (0.0 + 0.7) / 2,
        "avg_sal": (0.0 + 0.7) / 2, "avg_access": (0 + 4 + 2) / 3,
        "newest": recent, "oldest": NOW - 20 * 86400,
    }
