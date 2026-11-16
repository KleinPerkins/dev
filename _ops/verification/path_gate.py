#!/usr/bin/env python3
"""Run attributable staged checks, or one full fail-safe check."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

MAPPING_PATH = Path("_ops/verification/path-checks.json")
SELF_PROTECTED_EXACT = {"Makefile"}
SELF_PROTECTED_PREFIXES = (
    "_ops/checks/",
    "_ops/hooks/",
    "_ops/verification/",
)
FULL_CHECK = {
    "id": "full.repo",
    "argv": ["bash", "_ops/checks/verify-operating-model.sh", "--ci"],
    "cwd": ".",
    "coverage": "All repository-only operating-model checks.",
    "rationale": "Fail-safe proof for changes that cannot be isolated safely.",
}


class RouteError(ValueError):
    pass


def _text(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RouteError("non-UTF-8 path") from exc
    if not value or value.startswith("/") or "\x00" in value:
        raise RouteError("invalid repository path")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise RouteError("non-canonical repository path")
    return value


def parse_name_status_z(raw: bytes) -> list[dict[str, str]]:
    """Parse `git diff --name-status -z`, retaining both rename/copy paths."""
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise RouteError("change list is not NUL terminated")
    fields = raw[:-1].split(b"\0")
    changes: set[tuple[str, str]] = set()
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise RouteError("invalid Git status") from exc
        index += 1
        if not status or status[0] not in "ACDMRTUXB":
            raise RouteError(f"unsupported Git status: {status!r}")
        path_count = 2 if status[0] in "RC" else 1
        if index + path_count > len(fields):
            raise RouteError("truncated change list")
        for raw_path in fields[index : index + path_count]:
            changes.add((status, _text(raw_path)))
        index += path_count
    return [
        {"status": status, "path": path}
        for status, path in sorted(changes, key=lambda item: (item[1], item[0]))
    ]


def _matches(rule: dict[str, str], path: str) -> bool:
    kind, value = rule["kind"], rule["path"]
    if kind == "exact":
        return path == value
    if kind == "prefix":
        return path.startswith(value)
    raise RouteError(f"unsupported matcher kind: {kind!r}")


def load_mapping(repo: Path) -> dict[str, Any]:
    """Read the path-check mapping from the active Git index.

    Uses ``git cat-file blob :<path>`` so the same index snapshot that drives
    ``staged_changes()`` also drives routing, making unstaged working-tree edits
    invisible to check selection.  ``GIT_INDEX_FILE`` is inherited from the
    caller environment so hook-provided index context is respected automatically.
    Any read or parse failure raises ``RouteError``; callers fall back to
    fail-safe full escalation (``mapping_invalid``) rather than working-tree bytes.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f":{MAPPING_PATH}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RouteError(
            "path-check mapping not in index: "
            + result.stderr.decode("utf-8", "replace").strip()
        )
    try:
        mapping = json.loads(result.stdout.decode("utf-8"))
        if mapping["version"] != 1 or not isinstance(mapping["areas"], list):
            raise RouteError("unsupported path-check mapping")
        if not isinstance(mapping["high_risk"], list):
            raise RouteError("invalid high-risk mapping")
        return mapping
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RouteError("path-check mapping is unreadable") from exc


def _full(
    changes: list[dict[str, str]],
    areas: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "changed_paths": changes,
        "areas": areas,
        "checks": [FULL_CHECK],
        "escalation_reason": reason,
    }


def select(
    mapping: dict[str, Any], changes: list[dict[str, str]]
) -> dict[str, Any]:
    changes = [
        {"status": status, "path": path}
        for status, path in sorted(
            {(item["status"], item["path"]) for item in changes},
            key=lambda item: (item[1], item[0]),
        )
    ]
    if not changes:
        return _full(changes, [], "no_staged_paths")

    paths = [change["path"] for change in changes]
    if any(
        path in SELF_PROTECTED_EXACT
        or path.startswith(SELF_PROTECTED_PREFIXES)
        for path in paths
    ):
        return _full(changes, [], "verifier_or_self_modifying")

    if any(
        _matches(rule, path)
        for path in paths
        for rule in mapping["high_risk"]
    ):
        return _full(changes, [], "explicitly_high_risk")

    matched: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    for path in paths:
        path_areas = [
            area
            for area in mapping["areas"]
            if any(_matches(rule, path) for rule in area["paths"])
        ]
        if len(path_areas) != 1:
            unknown.append(path)
            continue
        area = path_areas[0]
        matched[area["id"]] = area

    areas = [matched[key] for key in sorted(matched)]
    if unknown:
        return _full(changes, areas, "unmapped_or_ambiguous_path")
    if len(areas) != 1:
        return _full(changes, areas, "mixed_or_cross_cutting")

    area = areas[0]
    checks = []
    for check in sorted(area["checks"], key=lambda item: item["id"]):
        checks.append(
            {
                **check,
                "coverage": area["coverage"],
                "rationale": area["rationale"],
            }
        )
    if not checks:
        return _full(changes, areas, "mapping_has_no_checks")
    return {
        "changed_paths": changes,
        "areas": areas,
        "checks": checks,
        "escalation_reason": None,
    }


def receipt(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "changed_paths": selection["changed_paths"],
        "matched_areas": [area["id"] for area in selection["areas"]],
        "selected_checks": [
            {
                "id": check["id"],
                "command": shlex.join(check["argv"]),
                "cwd": check["cwd"],
                "coverage": check["coverage"],
                "rationale": check["rationale"],
            }
            for check in selection["checks"]
        ],
        "escalation_reason": selection["escalation_reason"],
    }


def staged_changes(repo: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-status", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RouteError(result.stderr.decode("utf-8", "replace").strip())
    return parse_name_status_z(result.stdout)


def execute(repo: Path, selection: dict[str, Any]) -> int:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for check in selection["checks"]:
        print(f"verification-check: {check['id']}", flush=True)
        result = subprocess.run(
            check["argv"],
            cwd=repo / check["cwd"],
            env=env,
            check=False,
        )
        if result.returncode:
            return result.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--explain-only",
        action="store_true",
        help="print the deterministic receipt without running checks",
    )
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()

    try:
        changes = staged_changes(repo)
    except RouteError as exc:
        changes = []
        selection = _full(changes, [], "invalid_change_set")
        print(f"path-gate warning: {exc}", file=sys.stderr)
    else:
        try:
            selection = select(load_mapping(repo), changes)
        except (RouteError, KeyError, TypeError) as exc:
            selection = _full(changes, [], "mapping_invalid")
            print(f"path-gate warning: {exc}", file=sys.stderr)

    print(
        "verification-receipt: "
        + json.dumps(receipt(selection), sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return 0 if args.explain_only else execute(repo, selection)


if __name__ == "__main__":
    raise SystemExit(main())
