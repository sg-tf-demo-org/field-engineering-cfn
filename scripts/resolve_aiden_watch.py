#!/usr/bin/env python3
"""Resolve the Aiden UI watch URL for a governance webhook fire.

The webhook trigger returns a `run_id`, but that id is NOT watchable
(`…/executions/{run_id}/watch` → "execution not found").

The watch page SSE endpoint is `/guild/api/v1/executions/{id}/subscribe`.
That lookup is flaky for bare list `trace_id` values (GET/flight-record may
still 200 while subscribe 404s with "execution not found"). The UI itself
canonicalizes to `session:{session_id}` and streams via
`/guild/api/v1/sessions/{session_id}/subscribe`, which is reliable.

We correlate by finding a recent execution whose prompt embeds our payload
marker (typically `run_url`), then build the watch URL from list `session_id`.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any


def env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


GUILD_BASE = env("AIDEN_GUILD_BASE", default="https://stage.dev.stackgen.com").rstrip("/")
ORG_ID = env("AIDEN_ORG_ID", default="aee77bee-6885-4b4b-b9c0-e0c7ae81be96")
GUILD_TOKEN = env("AIDEN_GUILD_TOKEN")
WORKSPACE = env("AIDEN_WORKSPACE", default="devops-copilot")


def watch_url(session_id: str = "", trace_id: str = "") -> str:
    """Build the UI watch URL.

    Prefer `session:{session_id}` (UI-canonical, subscribe-safe). Fall back to
    undashed `trace_id` only when session_id is missing.
    """
    sid = (session_id or "").strip()
    if sid:
        # Match the SPA: encodeURIComponent(`session:${sessionId}`)
        rid = urllib.parse.quote(f"session:{sid}", safe="")
        return (
            f"{GUILD_BASE}/app/settings/workspace/{WORKSPACE}/executions/{rid}/watch"
        )
    tid = (trace_id or "").replace("-", "").strip()
    if not tid:
        return ""
    return f"{GUILD_BASE}/app/settings/workspace/{WORKSPACE}/executions/{tid}/watch"


def _list_executions(limit: int = 40) -> list[dict[str, Any]]:
    if not GUILD_TOKEN:
        return []
    url = f"{GUILD_BASE}/guild/api/v1/executions?limit={limit}&orgId={ORG_ID}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GUILD_TOKEN}",
            "x-org-id": ORG_ID,
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode() or "[]")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("executions", "items", "data", "results"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def resolve_execution(
    marker: str, timeout_s: int = 90, interval_s: float = 3.0
) -> dict[str, str]:
    """Return {trace_id, session_id} for the list item whose prompt contains marker."""
    if not marker or not GUILD_TOKEN:
        return {"trace_id": "", "session_id": ""}
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            for it in _list_executions():
                prompt = it.get("prompt") or ""
                if marker in prompt:
                    return {
                        "trace_id": (it.get("trace_id") or "").strip(),
                        "session_id": (it.get("session_id") or "").strip(),
                    }
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(interval_s)
    if last_err:
        print(f"resolve_execution: last error: {last_err}", file=sys.stderr)
    return {"trace_id": "", "session_id": ""}


def resolve_trace_id(marker: str, timeout_s: int = 90, interval_s: float = 3.0) -> str:
    """Backward-compatible: return list `trace_id` (prefer resolve_execution)."""
    return resolve_execution(marker, timeout_s=timeout_s, interval_s=interval_s)[
        "trace_id"
    ]


def resolve_session_id(marker: str, timeout_s: int = 90, interval_s: float = 3.0) -> str:
    """Return list `session_id` whose prompt contains `marker`, or \"\"."""
    return resolve_execution(marker, timeout_s=timeout_s, interval_s=interval_s)[
        "session_id"
    ]


def main() -> int:
    """CLI: resolve_aiden_watch.py <marker>  → prints watch URL (or empty)."""
    marker = sys.argv[1] if len(sys.argv) > 1 else env("AIDEN_WATCH_MARKER")
    if not marker:
        print("usage: resolve_aiden_watch.py <marker>", file=sys.stderr)
        return 2
    timeout = int(env("AIDEN_WATCH_RESOLVE_TIMEOUT", default="90"))
    ex = resolve_execution(marker, timeout_s=timeout)
    url = watch_url(session_id=ex["session_id"], trace_id=ex["trace_id"])
    if not url:
        return 1
    # Helpful for CI logs without breaking stdout contract (URL only on stdout).
    if ex["session_id"]:
        print(
            f"resolved session_id={ex['session_id']} trace_id={ex['trace_id']}",
            file=sys.stderr,
        )
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
