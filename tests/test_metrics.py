"""Activation-funnel metrics emitter."""

import json

import pytest

from markland.service import metrics


@pytest.fixture(autouse=True)
def _reset_first_time():
    metrics._reset_for_tests()
    yield
    metrics._reset_for_tests()


def test_emit_writes_json_line(capsys):
    metrics.emit("test_event", principal_id="usr_a", foo="bar", n=3)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "test_event"
    assert payload["principal_id"] == "usr_a"
    assert payload["foo"] == "bar"
    assert payload["n"] == 3
    assert "ts" in payload


def test_emit_without_principal_still_emits(capsys):
    metrics.emit("signup_started", source="web")
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "signup_started"
    assert payload["principal_id"] is None
    assert payload["source"] == "web"


def test_emit_first_time_emits_once_per_principal(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "first_publish"


def test_emit_first_time_independent_per_principal(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_b")
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 2
    assert {json.loads(line)["principal_id"] for line in lines} == {"usr_a", "usr_b"}


def test_emit_first_time_independent_per_event(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_grant", principal_id="usr_a")
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 2
    assert {json.loads(line)["event"] for line in lines} == {"first_publish", "first_grant"}


def test_emit_first_time_requires_principal_id():
    with pytest.raises(ValueError):
        metrics.emit_first_time("first_publish", principal_id=None)  # type: ignore[arg-type]
