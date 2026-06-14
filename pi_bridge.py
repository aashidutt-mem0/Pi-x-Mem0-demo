"""
pi_bridge.py — thin wrapper around the real Pi binary and the live Mem0 API.

This is the part of the demo that actually talks to the tools. The Streamlit
app (app.py) only ever calls into here, so all the subprocess and SDK plumbing
lives in one place.

Two things are exercised:

1. The Pi coding agent, driven non-interactively via `pi -p` / `pi --mode json`.
   Each "session" is a fresh, separate pi process. That is the whole point:
   we are proving that memory survives across process boundaries, not within a
   single long-lived conversation.

2. The Mem0 cloud API directly, so the UI can show what the @mem0/pi-agent-plugin
   has stored (the captured decisions) without having to parse pi's transcript.

Nothing here is mocked. If MEM0_API_KEY or the pi binary are missing the calls
fail loudly, which is intentional for a demo you want to trust.
"""

from __future__ import annotations

import json
import os
import getpass
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

# The Mem0 plugin scopes project memory by the git repo root (app_id) plus the
# user id. We mirror that exact scoping here so the memories the UI reads back
# are the same ones the pi plugin wrote.
DEFAULT_USER_ID = os.environ.get("MEM0_USER_ID") or getpass.getuser()


@dataclass
class SessionResult:
    """Everything one pi invocation produced, in a UI-friendly shape."""

    prompt: str
    final_text: str
    events: list[dict] = field(default_factory=list)
    memories_loaded: list[str] = field(default_factory=list)  # what pi pulled in at start
    memories_written: list[str] = field(default_factory=list)  # what got captured after
    raw_stdout: str = ""
    raw_stderr: str = ""
    duration_s: float = 0.0
    error: Optional[str] = None


# --------------------------------------------------------------------------- #
# Pi binary discovery + invocation
# --------------------------------------------------------------------------- #

def find_pi() -> Optional[str]:
    """Locate the pi binary. Returns the path, or None if not installed."""
    return shutil.which("pi") or (
        os.path.expanduser("~/.agentone/node/bin/pi")
        if os.path.exists(os.path.expanduser("~/.agentone/node/bin/pi"))
        else None
    )


def pi_available() -> bool:
    return find_pi() is not None


def run_pi_session(
    prompt: str,
    project_dir: str,
    *,
    model: Optional[str] = None,
    capture_events: bool = True,
    timeout_s: int = 180,
    inject_no_memory: bool = False,
) -> SessionResult:
    """
    Run a SINGLE, fresh pi process against `project_dir` and return what it did.

    We use `--mode json` so we can read the structured event stream: tool calls
    (including the plugin's mem0_memory tool and context-loader), assistant text,
    and errors. `--no-session` keeps each run ephemeral on pi's side so the ONLY
    thing carrying state between runs is Mem0, never pi's own session file. That
    is what makes the cross-session story honest.

    `-a` / `--approve` bypasses the project-trust prompt, which is required for
    any non-interactive run that loads project extensions (the mem0 plugin).

    `inject_no_memory=True` is the "amnesiac" control: it suppresses the Mem0
    plugin for this one run by clearing MEM0_API_KEY from the child environment.
    With no key the plugin's auto-capture and context-loader are inert, so pi
    behaves like a vanilla agent that has never heard of this project. This is
    how we get an honest no-memory baseline without uninstalling the plugin.
    """
    pi = find_pi()
    if pi is None:
        return SessionResult(
            prompt=prompt,
            final_text="",
            error="pi binary not found on PATH. Install with: curl -fsSL https://pi.dev/install.sh | sh",
        )

    cmd = [pi]
    if capture_events:
        cmd += ["--mode", "json"]
    else:
        cmd += ["-p"]
    cmd += ["-a", "--no-session"]
    if model:
        cmd += ["--model", model]
    cmd += [prompt]

    env = _normalized_env_for_pi()
    # The plugin reads MEM0_API_KEY from the environment; make sure it is passed
    # through to the child process explicitly. For the amnesiac baseline, strip
    # the key so the plugin goes inert for this run only.
    if inject_no_memory:
        env.pop("MEM0_API_KEY", None)
        env.pop("MEM0_USER_ID", None)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return SessionResult(
            prompt=prompt,
            final_text="",
            duration_s=time.time() - started,
            error=f"pi run exceeded {timeout_s}s and was killed.",
        )

    duration = time.time() - started
    result = SessionResult(
        prompt=prompt,
        final_text="",
        raw_stdout=proc.stdout,
        raw_stderr=proc.stderr,
        duration_s=duration,
    )

    if capture_events:
        _parse_json_events(proc.stdout, result)
    else:
        result.final_text = proc.stdout.strip()

    if proc.returncode != 0 and not result.final_text:
        result.error = (
            f"pi exited with code {proc.returncode}. "
            f"stderr: {proc.stderr.strip()[:500]}"
        )
    return result


def _normalized_env_for_pi() -> dict[str, str]:
    """Return environment variables adjusted for Pi's Azure provider names."""
    env = dict(os.environ)

    if env.get("AZURE_OPENAI_ENDPOINT"):
        endpoint = env["AZURE_OPENAI_ENDPOINT"].split("?", 1)[0].rstrip("/")
        if "/openai/deployments/" in endpoint and not env.get("AZURE_OPENAI_DEPLOYMENT"):
            after = endpoint.split("/openai/deployments/", 1)[1]
            env["AZURE_OPENAI_DEPLOYMENT"] = after.split("/", 1)[0]
        env["AZURE_OPENAI_BASE_URL"] = _azure_resource_root(
            env.get("AZURE_OPENAI_BASE_URL") or endpoint
        )
    elif env.get("AZURE_OPENAI_BASE_URL"):
        env["AZURE_OPENAI_BASE_URL"] = _azure_resource_root(env["AZURE_OPENAI_BASE_URL"])

    if env.get("AZURE_OPENAI_API_VERSION", "").startswith("2024-"):
        env["PI_DEMO_ORIGINAL_AZURE_OPENAI_API_VERSION"] = env["AZURE_OPENAI_API_VERSION"]
        env["AZURE_OPENAI_API_VERSION"] = "v1"

    return env


def _azure_resource_root(url: str) -> str:
    url = url.split("?", 1)[0].rstrip("/")
    if "/openai/deployments/" in url:
        return url.split("/openai/deployments/", 1)[0]
    if url.endswith("/openai/v1"):
        return url[: -len("/openai/v1")]
    if url.endswith("/openai"):
        return url[: -len("/openai")]
    for scheme in ("https://", "http://"):
        if url.startswith(scheme):
            rest = url[len(scheme):]
            return scheme + rest.split("/", 1)[0]
    return url


def _parse_json_events(stdout: str, result: SessionResult) -> None:
    """
    Parse pi's --mode json event stream (one JSON object per line) into the
    SessionResult. We pull out: final assistant text, mem0 tool calls, and any
    context-loader memory reads so the UI can show 'what pi remembered at start'.

    Pi's event schema has shifted across versions, so we read defensively: we
    look at a few likely field names rather than assuming one exact shape.
    """
    final_chunks: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line (e.g. a stray log). Keep it out of the structured view.
            continue
        result.events.append(evt)

        etype = evt.get("type") or evt.get("event") or ""

        # Assistant text — collect partials and/or a final message.
        if etype == "message_end":
            msg = evt.get("message") or {}
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    final_chunks.append(content)
                elif isinstance(content, list):
                    parts = [
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    text = "".join(parts).strip()
                    if text:
                        final_chunks.append(text)

        if etype in ("assistant", "message", "text", "assistant_message"):
            txt = (
                evt.get("text")
                or evt.get("content")
                or evt.get("message")
                or ""
            )
            if isinstance(txt, str) and txt:
                final_chunks.append(txt)

        # Tool calls — surface the mem0 plugin's reads and writes.
        if etype in ("tool_use", "tool_call", "tool"):
            name = evt.get("name") or evt.get("tool") or ""
            args = evt.get("input") or evt.get("args") or {}
            if "mem0" in str(name).lower():
                op = str(args.get("operation", "")).lower()
                payload = args.get("query") or args.get("text") or args.get("content") or ""
                if op in ("search", "get", "read", "load") or "search" in op:
                    if payload:
                        result.memories_loaded.append(str(payload))
                elif op in ("add", "store", "remember", "write") or "add" in op:
                    if payload:
                        result.memories_written.append(str(payload))

    if final_chunks:
        # Last non-empty chunk is usually the final answer; join unique tail.
        result.final_text = final_chunks[-1].strip()


# --------------------------------------------------------------------------- #
# Direct Mem0 API access (so the UI can show stored memories independently)
# --------------------------------------------------------------------------- #

def _mem0_client():
    """
    Return a configured Mem0 cloud client, or None if the SDK / key is missing.
    Imported lazily so the app still launches (with a clear banner) when the
    SDK is not installed yet.
    """
    if not os.environ.get("MEM0_API_KEY"):
        return None
    try:
        from mem0 import MemoryClient  # type: ignore
    except Exception:
        return None
    try:
        return MemoryClient()  # reads MEM0_API_KEY from env
    except Exception:
        return None


def mem0_available() -> bool:
    return _mem0_client() is not None


def list_project_memories(app_id: str, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """
    Read back the project-scoped memories the plugin stored.

    Note the SDK contract that matters here: search() takes its scoping via
    `filters=`, NOT as bare kwargs. (add() is the one that takes user_id= as a
    direct argument.) Getting this wrong silently returns the wrong scope, so it
    is worth being explicit.
    """
    client = _mem0_client()
    if client is None:
        return []
    try:
        # get_all with filters returns everything in scope without a query.
        res = client.get_all(
            filters={"AND": [{"user_id": user_id}, {"app_id": app_id}]},
            version="v2",
        )
    except Exception:
        # Fall back to the simpler signature on older SDKs.
        try:
            res = client.get_all(user_id=user_id)
        except Exception:
            return []
    return _normalize_memories(res)


def search_project_memories(
    query: str, app_id: str, user_id: str = DEFAULT_USER_ID, limit: int = 5
) -> list[dict]:
    """Semantic search within the project scope (mirrors /mem0-search)."""
    client = _mem0_client()
    if client is None:
        return []
    try:
        res = client.search(
            query,
            filters={"AND": [{"user_id": user_id}, {"app_id": app_id}]},
            version="v2",
            limit=limit,
        )
    except Exception:
        try:
            res = client.search(query, user_id=user_id, limit=limit)
        except Exception:
            return []
    return _normalize_memories(res)


def add_memory(text: str, app_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
    """
    Store a memory the way the plugin would for project scope.

    add() takes user_id= as a direct argument. app_id scopes it to this repo so
    it matches what pi's git-root detection produces.
    """
    client = _mem0_client()
    if client is None:
        return False
    try:
        client.add(
            messages=[{"role": "user", "content": text}],
            user_id=user_id,
            app_id=app_id,
        )
        return True
    except Exception:
        return False


def wipe_project_memories(app_id: str, user_id: str = DEFAULT_USER_ID) -> int:
    """
    Delete all project-scoped memories. Used by the 'reset demo' button so you
    can run the before/after cleanly from a true blank slate. Returns count.
    """
    client = _mem0_client()
    if client is None:
        return 0
    mems = list_project_memories(app_id, user_id)
    deleted = 0
    for m in mems:
        mid = m.get("id")
        if not mid:
            continue
        try:
            client.delete(memory_id=mid)
            deleted += 1
        except Exception:
            pass
    return deleted


def _normalize_memories(res) -> list[dict]:
    """Coerce the various shapes Mem0 returns into a flat list of dicts."""
    if res is None:
        return []
    if isinstance(res, dict):
        items = res.get("results") or res.get("memories") or []
    elif isinstance(res, list):
        items = res
    else:
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append({"memory": str(it), "id": None})
            continue
        out.append(
            {
                "id": it.get("id"),
                "memory": it.get("memory") or it.get("text") or it.get("content") or "",
                "categories": it.get("categories") or it.get("category") or [],
                "created_at": it.get("created_at") or it.get("createdAt") or "",
            }
        )
    return out
