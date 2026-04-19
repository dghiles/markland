"""Activation-funnel metrics — JSON-line events to stdout.

Intentionally minimal: stdout is captured by Fly's log pipeline; downstream
(Axiom, Grafana, whatever) can parse JSON lines. No Prometheus, no StatsD.

emit()            — always emits
emit_first_time() — emits only the first time a (event, principal_id) pair
                    is seen in this process. Survives only until restart; use
                    it for funnel *firsts*, not for persistent cohort tracking.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from typing import Any

_seen: set[tuple[str, str]] = set()


def _reset_for_tests() -> None:
    _seen.clear()


def emit(event: str, *, principal_id: str | None = None, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "event": event,
        "principal_id": principal_id,
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    for k, v in fields.items():
        payload[k] = v
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    sys.stdout.flush()


def emit_first_time(event: str, *, principal_id: str) -> None:
    if not principal_id:
        raise ValueError("emit_first_time requires a non-empty principal_id")
    key = (event, principal_id)
    if key in _seen:
        return
    _seen.add(key)
    emit(event, principal_id=principal_id, first_time=True)
