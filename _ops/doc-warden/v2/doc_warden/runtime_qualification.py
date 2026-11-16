"""Keep the GSD Core qualification record bound to the runtime files it pins.

`check` is offline and stdlib-only so the runnerless PR sandbox can run it on
every PR. `refresh` rewrites only the lock-derived fields, after an agent has
reviewed the lock change and run tests/verify-binding.sh.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import atomic_write, digest_ref, parse_json_object
from .live_install import QUALIFICATION_DIGEST_PATHS, _validate_runtime_qualification

RUNTIME = "_ops/doc-warden/runtime/gsd-core"
RECORD = "_ops/doc-warden/state/v2/runtime/gsd-core-v1.11.0-qualification.json"
RUNBOOK = "docs/runbooks/gsd-core-lock-requalification.md"
REGISTRY = "https://registry.npmjs.org/"
LOCK_DIGEST = "package_lock_sha256"
DIGEST_PATHS = {**QUALIFICATION_DIGEST_PATHS, "verifier_sha256": "tests/verify-binding.sh"}
MAX_DELTA_LINES = 20


def derive_dependency_licenses(lock: dict[str, Any]) -> list[dict[str, Any]]:
    """Project the record's license inventory from an npm v3 lock, in lock order."""
    packages = lock.get("packages")
    if lock.get("lockfileVersion") != 3 or not isinstance(packages, dict):
        raise ValueError("package-lock.json is not an npm lockfileVersion 3 lock")
    inventory = []
    for path, entry in packages.items():
        if path == "":
            continue
        if not path.startswith("node_modules/") or not isinstance(entry, dict):
            raise ValueError(f"unexpected lock entry {path!r}")
        fields = {key: entry.get(key) for key in ("integrity", "license", "version")}
        if not all(isinstance(value, str) and value for value in fields.values()):
            raise ValueError(f"lock entry {path!r} lacks a string version, integrity, or license")
        inventory.append(
            {
                **fields,
                "name": path.removeprefix("node_modules/"),
                "optional": entry.get("optional") is True,
            }
        )
    return inventory


def render_record(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _observed_digests(runtime: Path) -> dict[str, str]:
    return {
        name: digest_ref((runtime / relative).read_bytes()).removeprefix("sha256:")
        for name, relative in DIGEST_PATHS.items()
    }


def _delta(recorded: object, derived: list[dict[str, Any]]) -> list[str]:
    items = recorded if isinstance(recorded, list) else []
    before = {item.get("name"): item for item in items if isinstance(item, dict)}
    after = {item["name"]: item for item in derived}
    lines = []
    for name in sorted(set(before) | set(after), key=str):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if old is None:
            lines.append(f"added {name}@{new['version']}")
        elif new is None:
            lines.append(f"removed {name}@{old.get('version')}")
        elif old.get("version") != new["version"]:
            lines.append(f"{name} {old.get('version')} -> {new['version']}")
        else:
            lines.append(f"{name}@{new['version']} metadata changed")
    if not lines and recorded != derived:
        lines.append("entry order differs")
    return lines


def check(repo: Path) -> list[str]:
    """Return why the record no longer qualifies the runtime files; empty when bound."""
    root = repo.resolve(strict=True)
    runtime = root / RUNTIME
    try:
        record = parse_json_object((root / RECORD).read_bytes())
        observed = _observed_digests(runtime)
        derived = derive_dependency_licenses(
            parse_json_object((runtime / "package-lock.json").read_bytes())
        )
    except (OSError, ValueError) as exc:
        return [f"cannot read the qualification inputs: {exc}"]
    recorded = record.get("digests") if isinstance(record.get("digests"), dict) else {}
    problems = [
        f"{RUNTIME}/{DIGEST_PATHS[name]} changed since qualification "
        f"({name}: recorded {recorded.get(name)}, observed {digest})"
        for name, digest in observed.items()
        if recorded.get(name) != digest
    ]
    delta = _delta(record.get("dependency_licenses"), derived)
    if delta:
        shown = delta[:MAX_DELTA_LINES]
        if len(delta) > MAX_DELTA_LINES:
            shown.append(f"... and {len(delta) - MAX_DELTA_LINES} more")
        problems.append("dependency_licenses differs from package-lock.json: " + "; ".join(shown))
    try:
        _validate_runtime_qualification(root)
    except ValueError as exc:
        problems.append(f"doc-warden rejects the record: {exc}")
    return problems


def refresh(repo: Path, *, qualified_at: str, toolchain: dict[str, str]) -> list[str]:
    """Re-bind the record to a reviewed lock change; return the package delta."""
    root = repo.resolve(strict=True)
    runtime = root / RUNTIME
    record = parse_json_object((root / RECORD).read_bytes())
    lock = parse_json_object((runtime / "package-lock.json").read_bytes())
    observed = _observed_digests(runtime)
    recorded = record["digests"]
    other_changes = [
        f"{RUNTIME}/{DIGEST_PATHS[name]}"
        for name in DIGEST_PATHS
        if name != LOCK_DIGEST and recorded.get(name) != observed[name]
    ]
    if other_changes:
        raise ValueError(
            "a lock-only re-qualification cannot cover changes to " + ", ".join(other_changes)
        )
    derived = derive_dependency_licenses(lock)
    previous = record["dependency_licenses"]
    entries = [(path, entry) for path, entry in lock["packages"].items() if path]
    for (path, entry), item in zip(entries, derived):
        if item in previous:
            continue
        if entry.get("hasInstallScript"):
            raise ValueError(f"{path} declares install scripts; it needs a full re-qualification")
        if not str(entry.get("resolved", "")).startswith(REGISTRY):
            raise ValueError(f"{path} does not resolve from {REGISTRY}")
    if recorded[LOCK_DIGEST] == observed[LOCK_DIGEST] and previous == derived:
        raise ValueError("the record already matches package-lock.json; nothing to re-qualify")
    delta = _delta(previous, derived)
    record["dependency_licenses"] = derived
    recorded[LOCK_DIGEST] = observed[LOCK_DIGEST]
    record["qualified_at"] = qualified_at
    record["toolchain"] = toolchain
    atomic_write(root, RECORD, render_record(record))
    remaining = check(root)
    if remaining:
        raise ValueError("the record is still stale after refresh: " + "; ".join(remaining))
    return delta


def _host_toolchain() -> dict[str, str]:
    versions = {}
    for tool in ("node", "npm"):
        executable = shutil.which(tool)
        if executable is None:
            raise ValueError(f"{tool} is required to run {RUNTIME}/tests/verify-binding.sh")
        versions[tool] = subprocess.run(
            [executable, "--version"], check=True, capture_output=True, text=True
        ).stdout.strip()
    return {**versions, "platform": sys.platform}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m doc_warden.runtime_qualification", description=__doc__
    )
    parser.add_argument("command", choices=("check", "refresh"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.command == "check":
        problems = check(args.repo)
        if not problems:
            return 0
        print("  gsd-core qualification record no longer matches the runtime files it pins:")
        for problem in problems:
            print(f"    - {problem}")
        print(
            "  Next: do not merge this lock change as-is. An agent re-qualifies it in this PR\n"
            f"  per {RUNBOOK}: review the lock diff, run tests/verify-binding.sh, then\n"
            "  PYTHONPATH=_ops/doc-warden/v2 python3 -m doc_warden.runtime_qualification refresh"
        )
        return 1
    try:
        delta = refresh(
            args.repo,
            qualified_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            toolchain=_host_toolchain(),
        )
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"refresh refused: {exc}", file=sys.stderr)
        return 1
    print(f"re-qualified {RECORD}:")
    for line in delta:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
