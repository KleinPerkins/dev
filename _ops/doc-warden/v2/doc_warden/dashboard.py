"""Deterministic repo/fleet snapshots for the tracked Cursor Canvas seed."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .canonical import canonical_json
from .dependencies import build_graph
from .inventory import LogicalRepository
from .render import render_logical_repository
from .roadmap import roadmap_view
from .validators import read_repository_config


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _source_observed_at(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", "-s", "--format=%cI", "HEAD"],
        text=True,
    ).strip()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_repo_snapshot(
    repo: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    source_observed_at = _source_observed_at(repo)
    reasons = []
    try:
        config = read_repository_config(repo)
    except ValueError as exc:
        config = None
        reasons.append(str(exc))
    try:
        graph = build_graph(repo)
    except ValueError as exc:
        graph = None
        reasons.append(str(exc))
    items = (
        list(roadmap_view(repo, config["repository_key"]).items)
        if config is not None and graph is not None
        else []
    )
    value = {
        "schema": "doc-warden/canvas-data/v2",
        "mode": "repo",
        "source_revision": _head(repo),
        "source_observed_at": source_observed_at,
        "generated_at": generated_at or source_observed_at,
        "repository_key": config["repository_key"] if config else None,
        "items": items,
        "dependencies": [list(edge) for edge in graph.edges] if graph else [],
        "cycles": [list(cycle) for cycle in graph.cycles] if graph else [],
        "read_only": True,
        "repository_writes": [],
        "refresh_action": (
            "bash _ops/bin/doc-warden.sh view repo "
            "--canvas <managed-canvas-path>"
        ),
        "manage_action": "Manage doc-warden governance in chat.",
    }
    if reasons:
        value["migration_status"] = "blocked"
        value["reason"] = ";".join(reasons)
    return value


def render_fleet_snapshot(
    repos: Iterable[LogicalRepository],
    *,
    source_revision: str,
    generated_at: str | None = None,
    source_observed_at: str | None = None,
) -> dict[str, Any]:
    observed = source_observed_at or "1970-01-01T00:00:00Z"
    return {
        "schema": "doc-warden/canvas-data/v2",
        "mode": "fleet",
        "source_revision": source_revision,
        "source_observed_at": observed,
        "generated_at": generated_at or observed,
        "repositories": [render_logical_repository(repo) for repo in repos],
        "read_only": True,
        "repository_writes": [],
        "refresh_action": (
            "bash _ops/bin/doc-warden.sh view fleet "
            "--canvas <managed-canvas-path>"
        ),
        "manage_action": "Manage doc-warden governance in chat.",
    }


def canvas_refresh_contract(
    scope: str,
    *,
    bridge_available: bool,
) -> dict[str, Any]:
    if scope not in {"repo", "fleet"}:
        raise ValueError("canvas_scope_invalid")
    prompt = (
        "Refresh the read-only doc-warden repository roadmap view."
        if scope == "repo"
        else "Refresh the read-only doc-warden fleet roadmap view."
    )
    return {
        "schema": "doc-warden/canvas-refresh/v1",
        "scope": scope,
        "mode": "read_only_bridge" if bridge_available else "chat_fallback",
        "read_only": True,
        "repository_writes": [],
        "command": (
            f"bash _ops/bin/doc-warden.sh view {scope} "
            "--canvas <managed-canvas-path>"
        ),
        "chat_action": {
            "type": "newComposerChat",
            "userPrompt": prompt,
        },
    }


CanvasBridge = Callable[[str, Path, str], dict[str, Any]]


_CANVAS_COMMON_FIELDS = {
    "schema",
    "mode",
    "source_revision",
    "source_observed_at",
    "generated_at",
    "read_only",
    "repository_writes",
    "refresh_action",
    "manage_action",
}
_CANVAS_SCOPE_FIELDS = {
    "repo": {
        "repository_key",
        "items",
        "dependencies",
        "cycles",
        "migration_status",
        "reason",
    },
    "fleet": {"repositories"},
}


def _validate_bridge_snapshot(
    snapshot: object,
    *,
    scope: str,
    generated_at: str,
) -> dict[str, Any]:
    allowed = _CANVAS_COMMON_FIELDS | _CANVAS_SCOPE_FIELDS[scope]
    if (
        not isinstance(snapshot, dict)
        or set(snapshot) - allowed
        or not _CANVAS_COMMON_FIELDS.issubset(snapshot)
        or snapshot.get("schema") != "doc-warden/canvas-data/v2"
        or snapshot.get("mode") != scope
        or snapshot.get("read_only") is not True
        or snapshot.get("repository_writes") != []
        or snapshot.get("generated_at") != generated_at
        or re.fullmatch(
            r"[0-9a-f]{40}",
            str(snapshot.get("source_revision", "")),
        )
        is None
        or not isinstance(snapshot.get("source_observed_at"), str)
    ):
        raise ValueError("canvas_bridge_result_invalid")
    return snapshot


def refresh_canvas(
    seed: Path,
    target: Path,
    *,
    scope: str,
    repo: Path,
    generated_at: str,
    bridge: CanvasBridge | None,
) -> dict[str, Any]:
    contract = canvas_refresh_contract(
        scope,
        bridge_available=bridge is not None,
    )
    if bridge is None:
        return {
            **contract,
            "status": "chat_fallback",
        }
    snapshot = _validate_bridge_snapshot(
        bridge(scope, repo, generated_at),
        scope=scope,
        generated_at=generated_at,
    )
    output = generate_canvas(seed, target, snapshot)
    return {
        **contract,
        "status": "refreshed",
        "source_revision": snapshot["source_revision"],
        "generated_at": snapshot["generated_at"],
        "content_size": len(output),
    }


def generate_canvas(seed: Path, target: Path, snapshot: dict[str, Any]) -> bytes:
    source = seed.read_text(encoding="utf-8")
    begin = "// DOC_WARDEN_DATA_BEGIN\n"
    end = "// DOC_WARDEN_DATA_END"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError("canvas_data_marker_invalid")
    prefix, remainder = source.split(begin, 1)
    _, suffix = remainder.split(end, 1)
    payload = canonical_json(snapshot).decode("utf-8").strip()
    output = (
        prefix
        + begin
        + f"const SNAPSHOT: Snapshot | null = {payload};\n"
        + end
        + suffix
    ).encode("utf-8")
    if target.is_symlink() or not target.parent.is_dir():
        raise ValueError("canvas_target_invalid")
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, target)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    return output
