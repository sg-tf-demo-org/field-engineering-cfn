#!/usr/bin/env python3
"""PR-head Aiden governance gate for CDK / CloudFormation (GitHub).

Same architecture as Terraform pr_aiden_gate.py:
  pending status → webhook (watch) → mcp-cdk-governance.validate_cdk_governance
  → real success|failure|error status + session watch URL.

No terraform plan. CDK synthesizes in-MCP; CFN scans templates directly.
Set GATE_KIND=cdk|cfn (informational) and AIDEN_CDK_GOV_MCP_*.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    from resolve_aiden_watch import resolve_execution, watch_url as _guild_watch_url
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from resolve_aiden_watch import resolve_execution, watch_url as _guild_watch_url


def env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


GUILD_TOKEN = env("AIDEN_GUILD_TOKEN")
WEBHOOK_URL = env("AIDEN_PR_GOVERNANCE_WEBHOOK_URL")
MCP_URL = env("AIDEN_CDK_GOV_MCP_URL", default="https://mcp-cdk-governance.stackgen.run/mcp")
MCP_TOKEN = env("AIDEN_CDK_GOV_MCP_TOKEN")
MCP_TIMEOUT = int(env("GATE_MCP_TIMEOUT", default="900"))

PROJECT = env("GATE_PROJECT")
REF = env("GATE_REF")
BASE_REF = env("GATE_BASE_REF", default="main")
COMMIT_SHA = env("GATE_COMMIT_SHA")
PR_NUMBER = env("GATE_PR_NUMBER")
PR_URL = env("GATE_PR_URL")
SOURCE_BRANCH = env("GATE_SOURCE_BRANCH")
TARGET_BRANCH = env("GATE_TARGET_BRANCH")
RUN_URL = env("GATE_RUN_URL")
CHANGED_FILES_RAW = env("GATE_CHANGED_FILES", default="[]")
KIND = env("GATE_KIND", default="cdk").lower()  # cdk | cfn
GH_TOKEN = env("GH_TOKEN", "GITHUB_TOKEN")
REPO = env("GATE_REPO", default=PROJECT)

WATCH_RESOLVE_TIMEOUT = int(env("AIDEN_WATCH_RESOLVE_TIMEOUT", default="90"))
STATUS_CONTEXT = "aiden/governance"


def summary(md: str) -> None:
    print(md)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a") as f:
                f.write(md + "\n")
        except Exception:  # noqa: BLE001
            pass


def _changed_files() -> list:
    try:
        data = json.loads(CHANGED_FILES_RAW or "[]")
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def post_commit_status(state: str, description: str, target_url: str = "") -> None:
    if not GH_TOKEN or not REPO or not COMMIT_SHA:
        summary(f"- commit status skipped · wanted `{state}`")
        return
    body: dict = {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": (description or "")[:140],
    }
    if target_url:
        body["target_url"] = target_url
    url = f"https://api.github.com/repos/{REPO}/statuses/{COMMIT_SHA}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            summary(f"- commit status `{STATUS_CONTEXT}` → `{state}` (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        summary(f"- commit status HTTP {e.code}: {e.read().decode()[:300]}")
    except Exception as e:  # noqa: BLE001
        summary(f"- commit status error: `{e}`")


def fire_pr_webhook() -> tuple[str, str]:
    if not WEBHOOK_URL:
        summary("- Aiden reporter: `AIDEN_PR_GOVERNANCE_WEBHOOK_URL` unset — no watch run.")
        return "", ""
    payload = {
        "source": "github-actions",
        "event": "pr_governance_scan",
        "kind": KIND,
        "project": PROJECT,
        "pr_number": PR_NUMBER,
        "pr_url": PR_URL,
        "source_branch": SOURCE_BRANCH or REF,
        "target_branch": TARGET_BRANCH or BASE_REF,
        "commit_sha": COMMIT_SHA,
        "run_url": RUN_URL,
        "changed_files": _changed_files(),
        "instruction": (
            f"{KIND.upper()} PR — run mcp-cdk-governance.validate_cdk_governance on this "
            "commit/branch, report PASS/FAIL/ERROR, never deploy. "
            "CI also calls the same tool for the authoritative merge check."
        ),
    }
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
            resp.read()
    except urllib.error.HTTPError as e:
        code = e.code
        e.read()
    except Exception as e:  # noqa: BLE001
        summary(f"- Aiden reporter: webhook error (non-fatal): `{e}`")
        return "", ""

    summary(f"- Aiden reporter: webhook HTTP `{code}`")
    if not RUN_URL or not GUILD_TOKEN:
        return "", ""
    summary("- Resolving Aiden watch URL (correlate on run_url)...")
    ex = resolve_execution(RUN_URL, timeout_s=WATCH_RESOLVE_TIMEOUT)
    return ex.get("trace_id") or "", ex.get("session_id") or ""


_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse(raw: str) -> dict:
    last: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        if line.startswith("{"):
            try:
                last = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return last


def _mcp_post(body: dict, session_id: str = "") -> tuple[int, dict, str]:
    headers = dict(_MCP_HEADERS)
    if MCP_TOKEN:
        headers["Authorization"] = f"Bearer {MCP_TOKEN}"
    if session_id:
        headers["mcp-session-id"] = session_id
    req = urllib.request.Request(
        MCP_URL, data=json.dumps(body).encode(), method="POST", headers=headers,
    )
    with urllib.request.urlopen(req, timeout=MCP_TIMEOUT) as resp:
        raw = resp.read().decode()
        sid = resp.headers.get("mcp-session-id", "")
        return resp.status, _parse_sse(raw), sid


def call_validate_cdk() -> dict:
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aiden-pr-gate", "version": "1.0"},
        },
    }
    _code, _resp, sid = _mcp_post(init)
    if not sid:
        raise RuntimeError("MCP initialize returned no mcp-session-id")
    try:
        _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception:  # noqa: BLE001
        pass
    call = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "validate_cdk_governance",
            "arguments": {"project": PROJECT, "ref": REF},
        },
    }
    _code, resp, _sid = _mcp_post(call, sid)
    if "error" in resp:
        raise RuntimeError(f"MCP tool error: {resp['error']}")
    result = resp.get("result", {})
    content = result.get("content", [])
    text = ""
    for c in content:
        if c.get("type") == "text":
            text = c.get("text", "")
            break
    if not text:
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            return sc
        raise RuntimeError(f"MCP tool returned no text content: {json.dumps(result)[:500]}")
    return json.loads(text)


def _status_for_verdict(verdict: str) -> tuple[str, str]:
    v = (verdict or "ERROR").upper()
    if v == "PASS":
        return "success", "Governance PASS — open Aiden scan"
    if v == "FAIL":
        return "failure", "Governance FAIL — open Aiden scan"
    return "error", f"Governance {v} — open Aiden scan"


def main() -> int:
    if not PROJECT or not REF:
        summary("**PR governance ERROR** — GATE_PROJECT / GATE_REF not set.")
        post_commit_status("error", "Governance ERROR — misconfigured gate")
        return 1
    if not MCP_TOKEN:
        summary("**PR governance ERROR** — `AIDEN_CDK_GOV_MCP_TOKEN` secret not set.")
        post_commit_status("error", "Governance ERROR — MCP token missing")
        return 1
    if not COMMIT_SHA:
        summary("**PR governance ERROR** — GATE_COMMIT_SHA not set.")
        return 1

    summary(f"## Aiden PR governance ({KIND})")
    summary(f"- Project: `{PROJECT}` · ref: `{REF}` · sha: `{COMMIT_SHA[:7]}`")

    post_commit_status("pending", "Aiden governance scan running…")

    trace_id, session_id = fire_pr_webhook()
    link = _guild_watch_url(session_id=session_id, trace_id=trace_id)
    if link:
        summary(f"- Aiden watch: {link}")
        post_commit_status(
            "pending",
            "Aiden governance scan running — open to watch",
            target_url=link,
        )

    summary("- Verdict source: `mcp-cdk-governance.validate_cdk_governance`.")
    t0 = time.time()
    try:
        verdict = call_validate_cdk()
    except Exception as e:  # noqa: BLE001
        summary(f"\n**Result: ERROR (fail-closed)** — `{e}`")
        post_commit_status("error", "Governance ERROR — scan unreachable", target_url=link)
        return 1
    dt = int(time.time() - t0)

    v = (verdict.get("verdict") or "ERROR").upper()
    gates = verdict.get("gates", {}) or {}
    gate_line = " · ".join(f"{k}={val}" for k, val in gates.items()) if gates else "n/a"
    templates = verdict.get("templates") or []
    findings = (verdict.get("findings") or "").strip()
    kind = verdict.get("kind") or KIND

    summary(f"- Kind: `{kind}` · Gates: `{gate_line}` · templates: `{templates[:8]}` · {dt}s")
    state, desc = _status_for_verdict(v)
    post_commit_status(state, desc, target_url=link)

    if v == "PASS":
        summary("\n**Result: PASS** — PR head cleared governance.")
        if link:
            summary(f"- [Open Aiden governance execution]({link})")
        return 0

    summary(f"\n**Result: {v}** — merge should stay blocked until fixed.")
    if findings:
        summary(
            "\n<details><summary>findings</summary>\n\n```\n"
            + findings[:4000]
            + "\n```\n</details>"
        )
    if link:
        summary(f"- [Open Aiden governance execution]({link})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
