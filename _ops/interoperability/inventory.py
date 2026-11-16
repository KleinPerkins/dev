#!/usr/bin/env python3
"""Read-only observations for INT-001. Writes only an explicitly selected report directory.

Never installs, authenticates, runs discovered commands, follows repository subtrees,
or exports config values. Existing inventory paths bound repository inspection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

EXCLUDED = "kleinperkins/chaos-scheduler"
META_FIELDS = ("id", "kind", "scope", "flavor", "owner", "expose", "sync_policy",
               "provenance_source", "provenance_ref")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def git(path: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                            text=True, timeout=15, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return result.stdout.strip() if result.returncode == 0 else None


def identity(remote: str | None) -> str | None:
    if not remote:
        return None
    if remote.startswith('git@github.com:'):
        remote = 'ssh://git@github.com/' + remote.split(':', 1)[1]
    try:
        parsed = urlsplit(remote)
        if parsed.scheme not in {'ssh', 'git', 'https'} or parsed.hostname != 'github.com':
            return None
        if parsed.password or (parsed.scheme == 'https' and parsed.username):
            return None
        if parsed.port not in {None, 22, 443, 9418}:
            return None
        path = parsed.path.strip('/')
    except ValueError:
        return None
    match = re.fullmatch(r'([\w.-]+/[\w.-]+?)(?:\.git)?', path)
    return match.group(1) if match else None



def repository(path: Path) -> tuple[str | None, str | None]:
    """Check *all* remote identities before reading content, independent of basename."""
    if git(path, "rev-parse", "--show-toplevel") is None:
        return None, "no-repository"
    remotes = git(path, "config", "--get-regexp", r"remote\..*\.url") or ""
    identities = [identity(line.split(None, 1)[1]) for line in remotes.splitlines()]
    if any(name and name.lower() == EXCLUDED for name in identities):
        return None, "excluded"
    origin = identity(git(path, "remote", "get-url", "origin"))
    return origin, None if origin and all(identities) else "unresolved-identity"


def flat_metadata(path: Path) -> dict:
    """Read the existing flat scalar contract, never interpret arbitrary YAML tags."""
    fields = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([a-z_]+):\s*(.*?)\s*$", line)
        if match and match.group(1) in META_FIELDS:
            key, value = match.groups()
            if key in fields:
                raise ValueError("duplicate metadata key")
            if value.startswith('"'):
                value = json.loads(value)
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
            else:
                value = value.split(" #", 1)[0]
            fields[key] = int(value) if key == "flavor" else value
    return fields


def refresh_repositories(rows: list[dict], observed_at: str) -> list[dict]:
    result = []
    for old in rows:
        path = Path(old["path"])
        owner, reason = repository(path)
        if reason:
            result.append({"path": str(path), "owner": owner, "disposition": reason,
                           "qualification": "unsupported", "observed_at": observed_at})
            continue
        status = git(path, "status", "--porcelain")
        head = git(path, "rev-parse", "HEAD")
        result.append({"path": str(path), "origin": f"git@github.com:{owner}.git",
                       "owner": owner, "head": head,
                       "branch": git(path, "branch", "--show-current"),
                       "dirty": bool(status) if status is not None else None,
                       "scope": old["scope"], "previous_head": old.get("previous_head", old["head"]),
                       "qualification": "metadata-observed" if head and status is not None else "metadata-incomplete",
                       "disposition": "preserve; consult owner before implementation",
                       "dependencies": ["INT-001", "INT-023"], "observed_at": observed_at})
    return result


def refresh_capabilities(root: Path, task_map: list[dict], observed_at: str) -> tuple[list, list]:
    owner, reason = repository(root)
    if reason or owner != "KleinPerkins/skills":
        raise ValueError("skills owner identity unresolved or excluded")
    head = git(root, "rev-parse", "HEAD")
    old = {row["capability"]: row for row in task_map}
    capabilities, mapping = [], []
    # Explicit source shelves: no traversal of ignored product repos or installed links.
    for path in sorted(root.glob("*/*/*/meta.yml")):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise ValueError("unsupported linked source metadata")
        row = flat_metadata(path)
        cap_id = row["id"]
        tasks = old.get(cap_id, {}).get("tasks", ["INT-001", "INT-023"])
        row.update(path=str(path), sha256=digest(path), source_revision=head,
                   source_repository=owner, observed_at=observed_at, dependencies=tasks,
                   qualification="metadata-observed; native qualification pending",
                   disposition=old.get(cap_id, {}).get("proposed_action", "owner review required"))
        capabilities.append(row)
        mapping.append({"capability": cap_id, "scope": row["scope"], "kind": row["kind"],
                        "source": str(path), "owner": owner, "source_revision": head,
                        "tasks": tasks, "proposed_action": row["disposition"],
                        "qualification": row["qualification"], "observed_at": observed_at})
    return capabilities, mapping


def skill_exposures(home: Path, observed_at: str) -> list[dict]:
    config = home / ".codex/config.toml"
    settings = tomllib.loads(config.read_text()) if config.exists() else {}
    overrides = {str(Path(row["path"]).expanduser().resolve()): row.get("enabled")
                 for row in settings.get("skills", {}).get("config", []) if "path" in row}
    result = []
    for surface, root in [("codex-agents", home / ".agents/skills"),
                          ("codex", home / ".codex/skills"),
                          ("cursor", home / ".cursor/skills")]:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.name.startswith("."):
                continue  # Native system/plugin catalogs are separately observed, not hub-owned.
            resolved = entry.resolve()
            owner, reason = repository(resolved)
            if reason == "excluded":
                continue
            path = entry / "SKILL.md"
            if not path.is_file():
                continue
            canonical = path.resolve()
            file_owner, file_reason = repository(canonical.parent)
            if file_reason == "excluded":
                continue
            if file_reason == "unresolved-identity":
                reason = file_reason
            owner = file_owner or owner
            # No content is retained; digest is exposure identity, never semantic proof.
            result.append({"name": entry.name, "surface": surface, "path": str(path),
                           "canonical_source": str(canonical), "symlink": entry.is_symlink(),
                           "sha256": digest(path) if reason != "unresolved-identity" else None,
                           "owner": owner or "operator/import-owner-unresolved",
                           "source_revision": git(canonical.parent if file_owner else resolved, "rev-parse", "HEAD") if owner else None,
                           "codex_enabled_override": overrides.get(str(canonical), overrides.get(str(resolved))),
                           "qualification": "exposure-observed; native resolution unqualified",
                           "dependencies": ["INT-008", "INT-023"],
                           "disposition": "preserve until ownership and native precedence are qualified",
                           "semantic_review": "pending; name/digest is not semantic coverage",
                           "observed_at": observed_at})
    return result


def mcp_entries(home: Path, observed_at: str) -> list[dict]:
    paths = [("cursor", home / ".cursor/mcp.json", "mcpServers"),
             ("codex", home / ".codex/config.toml", "mcp_servers")]
    result = []
    for host, path, key in paths:
        if not path.exists():
            continue
        config = tomllib.loads(path.read_text()) if host == "codex" else json.loads(path.read_text())
        for name, entry in sorted(config.get(key, {}).items()):
            if name == "chaos-scheduler":
                continue
            # Exclude aliases whose local executable or argument belongs to the excluded repository.
            paths_to_check = [entry.get("command", ""), *entry.get("args", [])]
            if any(isinstance(v, str) and v.startswith("/") and Path(v).exists()
                   and repository(Path(v) if Path(v).is_dir() else Path(v).parent)[1] == "excluded"
                   for v in paths_to_check):
                continue
            enabled = entry.get("enabled")
            if enabled is None and isinstance(entry.get("disabled"), bool):
                enabled = not entry["disabled"]
            owner = {"awa": "KleinPerkins/awa + dev host overlay", "snow-kit": "KleinPerkins/kp-mcp + dev host overlay"}.get(name, "operator/registration-owner-unresolved")
            result.append({"name": name, "host": host,
                           "transport": "remote" if "url" in entry else "stdio" if "command" in entry else "unknown",
                           "owner": owner, "enabled": enabled, "registered": "observed-parsed",
                           "effective_enablement": "unknown", "authenticated": "unknown",
                           "tools_discovered": "unknown", "safe_read_succeeded": "unknown",
                           "qualification": "configuration-only",
                           "disposition": "preserve host settings; resolve field ownership before reconciliation",
                           "dependencies": ["INT-013", "INT-014", "INT-015"],
                           "observed_at": observed_at})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dev-root", type=Path, required=True)
    parser.add_argument("--operator-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output must be empty; review before replacing evidence")
    observed_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    read = lambda name: json.loads((args.baseline / f"{name}.json").read_text())
    caps, mapping = refresh_capabilities(args.dev_root / "capabilities/skills", read("capability_task_map"), observed_at)
    reports = {"repositories": refresh_repositories(read("repositories"), observed_at),
               "capabilities": caps, "capability_task_map": mapping,
               "installed-skills": skill_exposures(args.operator_home, observed_at),
               "mcp": mcp_entries(args.operator_home, observed_at)}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in reports.items():
        (args.output / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps({name: len(rows) for name, rows in reports.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
