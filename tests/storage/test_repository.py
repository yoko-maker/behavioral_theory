from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cogexp.storage.repository import (
    ConsentRequiredError,
    SaveResult,
    SchemaMismatchError,
    SqliteRepository,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def participant(pid: str = "p1", consent: str = "agreed") -> dict[str, object]:
    return {
        "participant_id": pid,
        "experiment_id": "pilot_v1",
        "condition_id": "standard_limit",
        "order_index": 0,
        "assignment_method": "balanced_cells",
        "assignment_seed": 42,
        "consent_status": consent,
        "consented_at": T0,
        "status": "in_progress",
        "created_at": T0,
        "completed_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "app_version": "0.1.0",
        "config_hash": "x" * 64,
    }


def trial(pid: str = "p1", trial_id: str = "t1", submission_id: str = "s1") -> dict[str, object]:
    return {
        "trial_id": trial_id,
        "submission_id": submission_id,
        "participant_id": pid,
        "experiment_id": "pilot_v1",
        "condition_id": "standard_limit",
        "task_id": "linda",
        "variant_id": "standard",
        "task_version": 1,
        "presentation_order": 3,
        "is_practice": False,
        "response_format": "choice",
        "time_limit_sec": 15.0,
        "show_countdown": True,
        "attempt": "initial",
        "initial_trial_id": None,
        "shown_at_server": T0,
        "submitted_at_server": T0,
        "shown_at_client_ms": None,
        "submitted_at_client_ms": None,
        "response_time_ms": 1234.5,
        "outcome": "answered",
        "choice_id": "single",
        "response_value": None,
        "is_correct": True,
        "confidence": None,
        "confidence_timing": None,
        "revision_count": 0,
        "duplicate_submission_count": 0,
    }


@pytest.fixture
def repo(tmp_path: Path) -> SqliteRepository:
    r = SqliteRepository(tmp_path / "data" / "test.sqlite")
    r.create_participant(participant())
    return r


def test_roundtrip_preserves_types(repo: SqliteRepository) -> None:
    assert repo.save_trial(trial()) is SaveResult.INSERTED
    [row] = repo.read_table("trials")
    assert row["is_correct"] is True
    assert row["shown_at_server"] == T0
    assert row["time_limit_sec"] == 15.0


def test_duplicate_submission_is_counted_not_inserted(repo: SqliteRepository) -> None:
    repo.save_trial(trial())
    assert repo.save_trial(trial(trial_id="t1-retry")) is SaveResult.DUPLICATE
    assert repo.save_trial(trial()) is SaveResult.DUPLICATE
    [row] = repo.read_table("trials")
    assert row["duplicate_submission_count"] == 2


def test_trial_requires_consented_participant(repo: SqliteRepository) -> None:
    with pytest.raises(ConsentRequiredError):
        repo.save_trial(trial(pid="unknown"))
    assert repo.read_table("trials") == []


def test_participant_row_only_on_agreement(tmp_path: Path) -> None:
    r = SqliteRepository(tmp_path / "x.sqlite")
    with pytest.raises(ConsentRequiredError):
        r.create_participant(participant(consent="declined"))
    assert r.read_table("participants") == []


def test_events_require_consent(repo: SqliteRepository) -> None:
    event = {
        "event_id": "e1",
        "trial_id": "t1",
        "participant_id": "nobody",
        "event_type": "click",
        "t_client_ms": 1.0,
        "x_norm": 0.5,
        "y_norm": 0.5,
        "target_id": None,
        "payload": {"k": 1},
    }
    with pytest.raises(ConsentRequiredError):
        repo.save_events([event])
    assert repo.save_events([event | {"participant_id": "p1"}]) == 1
    assert repo.read_table("events")[0]["payload"] == {"k": 1}


def test_confidence_is_set_once(repo: SqliteRepository) -> None:
    repo.save_trial(trial())
    assert repo.set_confidence("t1", 4, "after")
    assert not repo.set_confidence("t1", 1, "after")
    assert repo.read_table("trials")[0]["confidence"] == 4


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("outcome"),
        lambda r: r.update(extra_col=1),
        lambda r: r.update(task_version="1"),
        lambda r: r.update(outcome=None),
        lambda r: r.update(shown_at_server=datetime(2026, 1, 1)),  # noqa: DTZ001
    ],
)
def test_schema_validation(repo: SqliteRepository, mutate: object) -> None:
    row = trial()
    mutate(row)  # type: ignore[operator]
    with pytest.raises(SchemaMismatchError):
        repo.save_trial(row)


def test_outdated_database_is_detected(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trials (trial_id TEXT PRIMARY KEY)")
    with pytest.raises(SchemaMismatchError, match="退避"):
        SqliteRepository(path)


def test_status_update(repo: SqliteRepository) -> None:
    repo.set_participant_status("p1", "completed", T0)
    [row] = repo.read_table("participants")
    assert (row["status"], row["completed_at"]) == ("completed", T0)


def test_assigned_counts_exclude_aborted_and_abandoned(tmp_path: Path) -> None:
    from datetime import timedelta

    r = SqliteRepository(tmp_path / "a.sqlite")
    old = T0 - timedelta(hours=2)
    r.create_participant(participant("done") | {"status": "completed", "created_at": old})
    r.create_participant(participant("active"))
    r.create_participant(participant("stale") | {"created_at": old})
    r.create_participant(participant("gone") | {"status": "aborted"})
    seen: list[dict[tuple[str, int], int]] = []

    def build(counts: dict[tuple[str, int], int]) -> dict[str, object]:
        seen.append(counts)
        return participant("new")

    r.create_participant_assigned("pilot_v1", T0 - timedelta(minutes=30), build)
    assert seen == [{("standard_limit", 0): 2}]
    assert r.get_participant("new") is not None


def test_mark_aborted_only_in_progress(repo: SqliteRepository) -> None:
    assert repo.mark_aborted("p1", T0, "reload")
    assert not repo.mark_aborted("p1", T0, "reload")
    row = repo.get_participant("p1")
    assert row is not None and (row["status"], row["abort_reason"]) == ("aborted", "reload")


def test_accepting_defaults_to_closed_and_follows_latest(repo: SqliteRepository) -> None:
    from datetime import timedelta

    assert not repo.is_accepting("pilot_v1")
    for i, flag in enumerate([True, False, True]):
        repo.append_status(
            {
                "log_id": f"l{i}",
                "experiment_id": "pilot_v1",
                "accepting": flag,
                "changed_at": T0 + timedelta(minutes=i),
            }
        )
    assert repo.is_accepting("pilot_v1")
    assert not repo.is_accepting("other")
