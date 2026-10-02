from __future__ import annotations

from typing import Any

import pytest

from cogexp.domain.client_log import MAX_EVENTS, parse_submission


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "submit",
        "trial_id": "abc123",
        "choice_id": "single",
        "raw_value": None,
        "shown_ms": 1000.0,
        "sent_ms": 4000.0,
        "revision_count": 1,
        "client": {
            "browser": "chrome",
            "os": "windows",
            "pointer_types": ["mouse"],
            "viewport_w": 1280,
            "viewport_h": 720,
            "panel_w": 700,
            "panel_h": 400,
            "dpr": 1.25,
        },
        "events": [
            {"t": 1001.0, "type": "layout", "payload": {"rects": {"submit": [0, 0.8, 0.2, 0.9]}}},
            {"t": 1500.0, "type": "move", "x": 0.4, "y": 1.3},
            {"t": 3900.0, "type": "pointerdown", "x": 0.1, "y": 0.85, "target": "submit"},
        ],
    }
    return base | overrides


def test_valid_payload() -> None:
    p = parse_submission(payload())
    assert p is not None and len(p.events) == 3
    assert p.client.pointer_types == ("mouse",)


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "hack"},
        {"trial_id": "<script>"},
        {"shown_ms": float("nan")},
        {"events": [{"t": 1.0, "type": "keylogger"}]},
        {"events": [{"t": 1.0, "type": "move", "x": float("inf"), "y": 0}]},
        {"events": [{"t": 1.0, "type": "move", "x": 1e6, "y": 0}]},
        {"events": [{"t": 1.0, "type": "key", "payload": {"k": "x" * 5000}}]},
        {"events": [{"t": 1.0, "type": "move", "extra": 1}]},
        {"client": {"browser": "chrome"}},
        {"raw_value": "9" * 100},
        {"revision_count": -1},
    ],
)
def test_rejects_malformed(bad: dict[str, Any]) -> None:
    assert parse_submission(payload(**bad)) is None


def test_rejects_too_many_events() -> None:
    events = [{"t": 1.0, "type": "move", "x": 0.1, "y": 0.1}] * (MAX_EVENTS + 1)
    assert parse_submission(payload(events=events)) is None


@pytest.mark.parametrize("raw", [None, "string", [1, 2], 3])
def test_rejects_non_dict(raw: object) -> None:
    assert parse_submission(raw) is None
