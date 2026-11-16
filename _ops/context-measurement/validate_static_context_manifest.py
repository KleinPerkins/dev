#!/usr/bin/env python3
"""Validate the E-09 static context manifest without reading network state.

This is the preparatory validator for Context Efficiency Program v2 E-09.  It
does not create or measure the denominator; it only proves that a candidate
static manifest, measurement input, and measurement receipt join exactly to
explicit local owner checkouts and to the closed v2 measurement contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import kp_context_measure as kpcm


SCHEMA = "static-context-manifest/v1"
VALIDATION_SCHEMA = "static-context-manifest-validation/v1"
STATUS = "FROZEN"
VALIDATION_STATUS = "OK"
OWNER_REPOSITORIES = frozenset({
    "KleinPerkins/awa",
    "KleinPerkins/dev",
    "KleinPerkins/skills",
})
PROJECTION_ORDER = [
    "awa-operator",
    "dev-operating-model",
    "generated-home-agents",
    "subagent-orchestration",
    "terse-output",
    "workspace-agents",
    "worktree-default",
]
PROJECTION_OWNERS = {
    "awa-operator": "KleinPerkins/awa",
    "dev-operating-model": "KleinPerkins/dev",
    "generated-home-agents": "KleinPerkins/skills",
    "subagent-orchestration": "KleinPerkins/skills",
    "terse-output": "KleinPerkins/dev",
    "workspace-agents": "KleinPerkins/dev",
    "worktree-default": "KleinPerkins/dev",
}
PROJECTION_REQUIRED_CATEGORIES = {
    "generated-home-agents": "generated-memory",
}
PROJECTION_CATEGORIES = frozenset({"rules", "generated-memory"})
HEX40 = frozenset("0123456789abcdef")
UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
MANIFEST_KEYS = {
    "schema",
    "status",
    "captured_at_utc",
    "baseline_id",
    "client_root_class",
    "algorithm",
    "tool_contract",
    "whitespace_set_version",
    "projection_order",
    "projections",
    "totals",
    "target_30pct",
    "measurement_input_sha256",
    "measurement_receipt_sha256",
    "owner_refs",
}
OWNER_REF_KEYS = {"default_branch", "commit", "tree"}
PROJECTION_KEYS = {
    "projection_id",
    "logical_path",
    "category",
    "owner_repository",
    "owner_commit",
    "source_path",
    "source_blob",
    "source_sha256",
    "installed_raw_sha256",
    "normalized_sha256",
    "bytes",
    "characters",
    "words",
    "generated_inputs",
}
GENERATED_INPUT_KEYS = {"source_count", "source_digests", "output_sha256"}
TARGET_KEYS = {
    "max_characters",
    "max_words",
    "meets_characters",
    "meets_words",
}


class ValidationError(Exception):
    """A closed validation failure.  The CLI intentionally prints no detail."""


class FixedErrorParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValidationError()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_hex40(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 40
        and all(character in HEX40 for character in value)
    )


def _is_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_scalar_string(value: Any, *, nonempty: bool = True) -> bool:
    if type(value) is not str:
        return False
    if nonempty and not value:
        return False
    if "\x00" in value:
        return False
    return not any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _load_canonical_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        value = kpcm._parse_json_text(text)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ValidationError()
    if type(value) is not dict:
        raise ValidationError()
    if raw != kpcm.emit(value).encode("ascii"):
        raise ValidationError()
    return value, raw


def _git(root: Path, *args: str, raw: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValidationError()
    if completed.returncode != 0:
        raise ValidationError()
    if raw:
        return completed.stdout
    try:
        return completed.stdout.decode("ascii", errors="strict").strip()
    except UnicodeError:
        raise ValidationError()


def _parse_owner_checkouts(values: list[str] | None) -> dict[str, Path]:
    if values is None:
        raise ValidationError()
    checkouts: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValidationError()
        repository, raw_path = value.split("=", 1)
        if repository in checkouts or repository not in OWNER_REPOSITORIES:
            raise ValidationError()
        if not raw_path:
            raise ValidationError()
        checkouts[repository] = Path(raw_path).expanduser()
    if set(checkouts) != OWNER_REPOSITORIES:
        raise ValidationError()
    return checkouts


def _owner_metadata(checkouts: dict[str, Path]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for repository, root in checkouts.items():
        commit = _git(root, "rev-parse", "HEAD")
        tree = _git(root, "rev-parse", "HEAD^{tree}")
        if not _is_hex40(commit) or not _is_hex40(tree):
            raise ValidationError()
        metadata[repository] = {"commit": commit, "tree": tree}
    return metadata


def _blob_metadata(root: Path, commit: str, source_path: str) -> tuple[str, str]:
    if not _is_scalar_string(source_path):
        raise ValidationError()
    blob = _git(root, "rev-parse", f"{commit}:{source_path}")
    if not _is_hex40(blob):
        raise ValidationError()
    raw = _git(root, "show", f"{commit}:{source_path}", raw=True)
    assert isinstance(raw, bytes)
    return blob, _sha256(raw)


def _validate_owner_refs(
    manifest: dict[str, Any],
    checkouts: dict[str, Path],
) -> dict[str, dict[str, str]]:
    owner_refs = manifest.get("owner_refs")
    if type(owner_refs) is not dict or set(owner_refs) != OWNER_REPOSITORIES:
        raise ValidationError()
    metadata = _owner_metadata(checkouts)
    for repository, owner_ref in owner_refs.items():
        if type(owner_ref) is not dict or set(owner_ref) != OWNER_REF_KEYS:
            raise ValidationError()
        if not _is_scalar_string(owner_ref["default_branch"]):
            raise ValidationError()
        if owner_ref["commit"] != metadata[repository]["commit"]:
            raise ValidationError()
        if owner_ref["tree"] != metadata[repository]["tree"]:
            raise ValidationError()
        if not _is_hex40(owner_ref["commit"]) or not _is_hex40(owner_ref["tree"]):
            raise ValidationError()
    return metadata


def _receipt_row_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["projection_id"]: row for row in receipt["projections"]}


def _input_entry_map(input_value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        _client_root_class, _baseline_id, entries = kpcm.validate_manifest(input_value)
    except kpcm.InputError:
        raise ValidationError()
    return {entry["projection_id"]: entry for entry in entries}


def _validate_generated_inputs(
    projection: dict[str, Any],
    receipt_row: dict[str, Any],
) -> None:
    generated_inputs = projection["generated_inputs"]
    if projection["category"] == "rules":
        if generated_inputs is not None:
            raise ValidationError()
        return
    if type(generated_inputs) is not dict or set(generated_inputs) != GENERATED_INPUT_KEYS:
        raise ValidationError()
    if not _is_nonnegative_int(generated_inputs["source_count"]):
        raise ValidationError()
    source_digests = generated_inputs["source_digests"]
    if type(source_digests) is not list:
        raise ValidationError()
    if not source_digests:
        raise ValidationError()
    if not all(kpcm._is_digest(item) for item in source_digests):
        raise ValidationError()
    if source_digests != sorted(set(source_digests)):
        raise ValidationError()
    if generated_inputs["source_count"] < 1:
        raise ValidationError()
    if generated_inputs["source_count"] < len(source_digests):
        raise ValidationError()
    if not kpcm._is_digest(generated_inputs["output_sha256"]):
        raise ValidationError()
    if generated_inputs["output_sha256"] != projection["installed_raw_sha256"]:
        raise ValidationError()
    if generated_inputs["output_sha256"] != receipt_row["raw_sha256"]:
        raise ValidationError()


def _validate_target(totals: dict[str, Any], target: Any) -> None:
    if type(target) is not dict or set(target) != TARGET_KEYS:
        raise ValidationError()
    for key in ("max_characters", "max_words"):
        if not _is_nonnegative_int(target[key]):
            raise ValidationError()
    for key in ("meets_characters", "meets_words"):
        if type(target[key]) is not bool:
            raise ValidationError()
    if target["max_characters"] != (totals["characters"] * 70) // 100:
        raise ValidationError()
    if target["max_words"] != (totals["words"] * 70) // 100:
        raise ValidationError()
    if target["meets_characters"] != (
        totals["characters"] <= target["max_characters"]
    ):
        raise ValidationError()
    if target["meets_words"] != (totals["words"] <= target["max_words"]):
        raise ValidationError()


def _validate_identity(
    manifest: dict[str, Any],
    input_value: dict[str, Any],
    receipt: dict[str, Any],
    input_raw: bytes,
    receipt_raw: bytes,
) -> None:
    if set(manifest) != MANIFEST_KEYS:
        raise ValidationError()
    if manifest["schema"] != SCHEMA or manifest["status"] != STATUS:
        raise ValidationError()
    if (
        type(manifest["captured_at_utc"]) is not str
        or UTC_TIMESTAMP.fullmatch(manifest["captured_at_utc"]) is None
    ):
        raise ValidationError()
    if manifest["algorithm"] != kpcm.ALGORITHM:
        raise ValidationError()
    if manifest["tool_contract"] != kpcm.TOOL_CONTRACT:
        raise ValidationError()
    if manifest["whitespace_set_version"] != kpcm.WHITESPACE_SET_VERSION:
        raise ValidationError()
    if not kpcm._is_token(manifest["baseline_id"]):
        raise ValidationError()
    if not kpcm._is_token(manifest["client_root_class"]):
        raise ValidationError()
    if manifest["measurement_input_sha256"] != _sha256(input_raw):
        raise ValidationError()
    if manifest["measurement_receipt_sha256"] != _sha256(receipt_raw):
        raise ValidationError()
    if manifest["projection_order"] != PROJECTION_ORDER:
        raise ValidationError()
    if input_value["client_root_class"] != manifest["client_root_class"]:
        raise ValidationError()
    if input_value["baseline_id"] != manifest["baseline_id"]:
        raise ValidationError()
    if receipt["client_root_class"] != manifest["client_root_class"]:
        raise ValidationError()
    if receipt["baseline_id"] != manifest["baseline_id"]:
        raise ValidationError()
    if receipt["algorithm"] != kpcm.ALGORITHM:
        raise ValidationError()
    if receipt["tool_contract"] != kpcm.TOOL_CONTRACT:
        raise ValidationError()
    if receipt["whitespace_set_version"] != kpcm.WHITESPACE_SET_VERSION:
        raise ValidationError()
    if receipt["status"] != "OK":
        raise ValidationError()
    if receipt["projection_order"] != PROJECTION_ORDER:
        raise ValidationError()
    if manifest["totals"] != receipt["totals"]:
        raise ValidationError()
    _validate_target(receipt["totals"], manifest["target_30pct"])


def validate_static_context_manifest(
    *,
    manifest_path: Path,
    input_path: Path,
    receipt_path: Path,
    owner_checkouts: dict[str, Path],
) -> dict[str, str]:
    manifest, manifest_raw = _load_canonical_json(manifest_path)
    input_value, input_raw = _load_canonical_json(input_path)
    receipt, receipt_raw = _load_canonical_json(receipt_path)
    try:
        kpcm.validate_receipt(receipt)
    except kpcm.ReceiptInvalid:
        raise ValidationError()
    input_entries = _input_entry_map(input_value)
    _validate_identity(manifest, input_value, receipt, input_raw, receipt_raw)
    _validate_owner_refs(manifest, owner_checkouts)

    projections = manifest["projections"]
    if type(projections) is not list or len(projections) != len(PROJECTION_ORDER):
        raise ValidationError()
    receipt_rows = _receipt_row_map(receipt)
    if list(input_entries) != PROJECTION_ORDER:
        raise ValidationError()
    seen_repositories = set()

    for index, projection in enumerate(projections):
        if type(projection) is not dict or set(projection) != PROJECTION_KEYS:
            raise ValidationError()
        projection_id = PROJECTION_ORDER[index]
        if projection["projection_id"] != projection_id:
            raise ValidationError()
        if projection["category"] not in PROJECTION_CATEGORIES:
            raise ValidationError()
        required_category = PROJECTION_REQUIRED_CATEGORIES.get(
            projection_id,
            "rules",
        )
        if projection["category"] != required_category:
            raise ValidationError()
        repository = projection["owner_repository"]
        if repository not in OWNER_REPOSITORIES:
            raise ValidationError()
        if repository != PROJECTION_OWNERS[projection_id]:
            raise ValidationError()
        seen_repositories.add(repository)
        owner_ref = manifest["owner_refs"][repository]
        if projection["owner_commit"] != owner_ref["commit"]:
            raise ValidationError()
        if not _is_scalar_string(projection["logical_path"]):
            raise ValidationError()
        receipt_row = receipt_rows.get(projection_id)
        input_entry = input_entries.get(projection_id)
        if receipt_row is None or input_entry is None:
            raise ValidationError()
        if projection["logical_path"] != receipt_row["path"]:
            raise ValidationError()
        if projection["logical_path"] != input_entry["path"]:
            raise ValidationError()
        if kpcm._receipt_selector(input_entry["select"]) != receipt_row["select"]:
            raise ValidationError()
        if projection["installed_raw_sha256"] != receipt_row["raw_sha256"]:
            raise ValidationError()
        if projection["normalized_sha256"] != receipt_row["normalized_sha256"]:
            raise ValidationError()
        for key in ("bytes", "characters", "words"):
            if projection[key] != receipt_row[key]:
                raise ValidationError()
        source_blob, source_sha256 = _blob_metadata(
            owner_checkouts[repository],
            projection["owner_commit"],
            projection["source_path"],
        )
        if projection["source_blob"] != source_blob:
            raise ValidationError()
        if projection["source_sha256"] != source_sha256:
            raise ValidationError()
        _validate_generated_inputs(projection, receipt_row)

    if seen_repositories != OWNER_REPOSITORIES:
        raise ValidationError()
    return {
        "schema": VALIDATION_SCHEMA,
        "status": VALIDATION_STATUS,
        "manifest_sha256": _sha256(manifest_raw),
        "input_sha256": _sha256(input_raw),
        "receipt_sha256": _sha256(receipt_raw),
    }


def _parser() -> argparse.ArgumentParser:
    parser = FixedErrorParser(prog="validate_static_context_manifest.py")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--owner-checkout",
        required=True,
        action="append",
        dest="owner_checkouts",
        metavar="REPOSITORY=PATH",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = validate_static_context_manifest(
            manifest_path=args.manifest,
            input_path=args.input,
            receipt_path=args.receipt,
            owner_checkouts=_parse_owner_checkouts(args.owner_checkouts),
        )
    except ValidationError:
        print(
            "validate_static_context_manifest: VALIDATION_ERROR",
            file=sys.stderr,
        )
        return 3
    print(kpcm.emit(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
