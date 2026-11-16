#!/usr/bin/env python3
"""Bounded synthetic correction proof for kp-context-measurement.

This helper owns one fixed fixture and command matrix.  It never measures
operator/client context and never writes the tracked evidence path itself.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


EVIDENCE_SCHEMA = "kp-context-measurement-correction-evidence/v1"
ALGORITHM = "kp-context-measurement/v1"
TOOL_CONTRACT = "kp-context-measurement-tool/v2"
ENVIRONMENT_CLASS = "macos-bash3-stdlib"
COMMAND_SET = "kp-context-measurement-correction-dogfood/v1"
CLASSIFICATION = "CORRECTION_PROVEN_NOT_E09"
SENTINEL = b"TOKEN_SENTINEL_SECRET"
TOOL_RELATIVE_PATH = "_ops/context-measurement/kp_context_measure.py"
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
MEASUREMENT_KEYS = {
    "schema", "algorithm", "tool", "tool_contract",
    "whitespace_set_version", "status", "client_root_class",
    "baseline_id", "projection_order", "projections", "totals",
}
PROJECTION_KEYS = {
    "projection_id", "path", "select", "status", "failure_class",
    "raw_sha256", "normalized_sha256", "bytes", "characters", "words",
}
TOTAL_KEYS = {"bytes", "characters", "words"}
COMPARISON_KEYS = {
    "schema", "algorithm", "tool", "tool_contract",
    "whitespace_set_version", "status", "baseline_id",
    "client_root_class", "projection_order", "baseline_totals",
    "candidate_totals", "delta", "target_30pct",
}

FIXTURES = {
    "full-newlines": {
        "base64": "YWxwaGEgYmV0YQ0KZ2FtbWEK",
        "select_kind": "full",
        "expected_class": "OK",
    },
    "unicode-cr": {
        "base64": "QQ1CwqBD4oCoRAo=",
        "select_kind": "full",
        "expected_class": "OK",
    },
    "region": {
        "base64": (
            "cHJlCjwhLS0gQkVHSU4geCAtLT4KbWlkIG9uZQo8IS0tIEVORCB4IC0tPgpwb3N0Cg=="
        ),
        "select_kind": "region",
        "expected_class": "OK",
    },
    "sentinel": {
        "base64": "VE9LRU5fU0VOVElORUxfU0VDUkVUIHN0dWZmCg==",
        "select_kind": "full",
        "expected_class": "OK",
    },
    "ambiguous": {
        "base64": "YWFhWgo=",
        "select_kind": "region",
        "expected_class": "REGION_AMBIGUOUS",
    },
    "overlap": {
        "base64": "YWJjZAo=",
        "select_kind": "region",
        "expected_class": "REGION_MISORDERED",
    },
}

EXPECTED_EXITS = {
    "measure_a": 0,
    "measure_b": 0,
    "compare_compatible": 0,
    "compare_incompatible": 4,
    "blocked": 2,
    "usage": 3,
}
EXPECTED_SAFETY = {
    "sentinel_absent": True,
    "source_content_present": False,
    "input_immutable": True,
    "receipts_byte_identical": True,
}
EVIDENCE_KEYS = {
    "schema", "status", "classification", "captured_at_utc",
    "implementation_commit", "implementation_tree", "algorithm",
    "tool_contract", "environment_class", "command_set",
    "fixture_manifest_sha256", "run_a_receipt_sha256",
    "run_b_receipt_sha256", "pre_stats_sha256", "post_stats_sha256",
    "observed_exits", "content_safety",
}


class DogfoodError(Exception):
    pass


class CliError(Exception):
    pass


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CliError()


def canonical_bytes(value) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition):
    if not condition:
        raise DogfoodError()


def _object_without_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DogfoodError()
        value[key] = item
    return value


def _reject_json_constant(_value):
    raise DogfoodError()


def parse_json(raw: bytes):
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise DogfoodError()


def _git_value(root: Path, argument: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", argument],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, UnicodeError, ValueError):
        raise DogfoodError()
    require(completed.returncode == 0)
    require(completed.stderr == "")
    value = completed.stdout.strip()
    require("\n" not in value)
    return value


def implementation_identity(root: Path):
    try:
        root = root.resolve()
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    top = _git_value(root, "--show-toplevel")
    try:
        top_path = Path(top).resolve()
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    require(top_path == root)
    commit = _git_value(root, "HEAD")
    tree = _git_value(root, commit + "^{tree}")
    require(HEX_40.fullmatch(commit) is not None)
    require(HEX_40.fullmatch(tree) is not None)
    return commit, tree


def _git_blob(root: Path, commit: str, relative_path: str) -> bytes:
    try:
        completed = subprocess.run(
            [
                "git", "-C", str(root), "cat-file", "blob",
                commit + ":" + relative_path,
            ],
            check=False,
            capture_output=True,
        )
    except (OSError, ValueError):
        raise DogfoodError()
    require(completed.returncode == 0)
    require(completed.stderr == b"")
    return completed.stdout


def _bind_tool(tool: Path, root: Path, commit: str) -> Path:
    expected = root / TOOL_RELATIVE_PATH
    require(tool.is_absolute())
    require(not tool.is_symlink())
    try:
        tool = tool.resolve(strict=True)
        expected = expected.resolve(strict=True)
        info = os.lstat(str(tool))
        raw = tool.read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    require(tool == expected)
    require(stat.S_ISREG(info.st_mode))
    require(raw == _git_blob(root, commit, TOOL_RELATIVE_PATH))
    return tool


def validate_evidence_bytes(raw: bytes, implementation_root: Path):
    value = parse_json(raw)
    require(type(value) is dict and set(value) == EVIDENCE_KEYS)
    require(value["schema"] == EVIDENCE_SCHEMA)
    require(value["status"] == "PASS")
    require(value["classification"] == CLASSIFICATION)
    require(value["algorithm"] == ALGORITHM)
    require(value["tool_contract"] == TOOL_CONTRACT)
    require(value["environment_class"] == ENVIRONMENT_CLASS)
    require(value["command_set"] == COMMAND_SET)
    require(type(value["captured_at_utc"]) is str)
    try:
        parsed_timestamp = datetime.datetime.strptime(
            value["captured_at_utc"], "%Y-%m-%dT%H:%M:%SZ"
        )
    except ValueError:
        raise DogfoodError()
    require(
        parsed_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        == value["captured_at_utc"]
    )

    for key in ("implementation_commit", "implementation_tree"):
        require(type(value[key]) is str)
        require(HEX_40.fullmatch(value[key]) is not None)
    digest_keys = (
        "fixture_manifest_sha256",
        "run_a_receipt_sha256",
        "run_b_receipt_sha256",
        "pre_stats_sha256",
        "post_stats_sha256",
    )
    for key in digest_keys:
        require(type(value[key]) is str)
        require(HEX_64.fullmatch(value[key]) is not None)

    require(type(value["observed_exits"]) is dict)
    require(set(value["observed_exits"]) == set(EXPECTED_EXITS))
    require(all(
        type(item) is int for item in value["observed_exits"].values()
    ))
    require(value["observed_exits"] == EXPECTED_EXITS)
    require(type(value["content_safety"]) is dict)
    require(set(value["content_safety"]) == set(EXPECTED_SAFETY))
    require(all(
        type(item) is bool for item in value["content_safety"].values()
    ))
    require(value["content_safety"] == EXPECTED_SAFETY)
    require(
        value["run_a_receipt_sha256"]
        == value["run_b_receipt_sha256"]
    )
    require(value["pre_stats_sha256"] == value["post_stats_sha256"])

    try:
        root = implementation_root.resolve()
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    top = _git_value(root, "--show-toplevel")
    try:
        require(Path(top).resolve() == root)
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    tree = _git_value(
        root, value["implementation_commit"] + "^{tree}"
    )
    require(tree == value["implementation_tree"])
    require(raw == canonical_bytes(value))
    return value


def validate_evidence(path: Path, implementation_root: Path):
    try:
        raw = path.read_bytes()
    except (OSError, ValueError):
        raise DogfoodError()
    return validate_evidence_bytes(raw, implementation_root)


def _write_canonical(path: Path, value):
    try:
        path.write_bytes(canonical_bytes(value))
    except OSError:
        raise DogfoodError()


def _run_tool(tool: Path, argv, cwd: Path):
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        return subprocess.run(
            [sys.executable, str(tool), *argv],
            cwd=str(cwd),
            env=environment,
            check=False,
            capture_output=True,
        )
    except OSError:
        raise DogfoodError()


def _canonical_json_output(completed):
    require(completed.stderr == b"")
    value = parse_json(completed.stdout)
    require(completed.stdout == canonical_bytes(value))
    return value


def _fixture_manifest(paths):
    rows = []
    for fixture_id, definition in FIXTURES.items():
        raw = paths[fixture_id].read_bytes()
        rows.append({
            "fixture_id": fixture_id,
            "raw_sha256": sha256(raw),
            "select_kind": definition["select_kind"],
            "expected_class": definition["expected_class"],
        })
    rows.sort(key=lambda item: item["fixture_id"].encode("ascii"))
    return canonical_bytes(rows)


def _fixture_stats(paths):
    rows = []
    for fixture_id, path in paths.items():
        try:
            info = path.stat()
            raw = path.read_bytes()
        except OSError:
            raise DogfoodError()
        require(stat.S_ISREG(info.st_mode))
        rows.append({
            "fixture_id": fixture_id,
            "mode": stat.S_IMODE(info.st_mode),
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "raw_sha256": sha256(raw),
        })
    rows.sort(key=lambda item: item["fixture_id"].encode("ascii"))
    return canonical_bytes(rows)


def _selector(fixture_id):
    if fixture_id == "region":
        return {
            "kind": "region",
            "begin": "<!-- BEGIN x -->",
            "end": "<!-- END x -->",
        }
    if fixture_id == "ambiguous":
        return {"kind": "region", "begin": "aa", "end": "Z"}
    if fixture_id == "overlap":
        return {"kind": "region", "begin": "abc", "end": "bcd"}
    return {"kind": "full"}


def _measurement_manifest(paths):
    projection_ids = [
        "sentinel", "region", "unicode-cr", "full-newlines",
    ]
    return {
        "schema": "kp-context-measurement-input/v2",
        "client_root_class": "correction-dogfood/macos",
        "baseline_id": "correction-dogfood-v1",
        "projections": [
            {
                "projection_id": fixture_id,
                "path": str(paths[fixture_id]),
                "select": _selector(fixture_id),
            }
            for fixture_id in projection_ids
        ],
    }


def _blocked_manifest(paths, absent_path):
    return {
        "schema": "kp-context-measurement-input/v2",
        "client_root_class": "correction-dogfood/macos",
        "baseline_id": "correction-dogfood-v1",
        "projections": [
            {
                "projection_id": "overlap",
                "path": str(paths["overlap"]),
                "select": _selector("overlap"),
            },
            {
                "projection_id": "absent-path",
                "path": str(absent_path),
                "select": {"kind": "full"},
            },
            {
                "projection_id": "ambiguous",
                "path": str(paths["ambiguous"]),
                "select": _selector("ambiguous"),
            },
        ],
    }


def _usage_manifest(paths):
    return {
        "schema": "kp-context-measurement-input/v2",
        "client_root_class": "correction-dogfood/macos",
        "baseline_id": "correction-dogfood-v1",
        "projections": [{
            "projection_id": "full-newlines",
            "path": str(paths["full-newlines"]),
            "select": {
                "kind": "full",
                "unexpected_payload": SENTINEL.decode("ascii"),
            },
        }],
    }


def _receipt_selector(selector):
    if selector["kind"] == "full":
        return {"kind": "full"}
    return {
        "kind": "region",
        "begin_sha256": sha256(selector["begin"].encode("utf-8")),
        "end_sha256": sha256(selector["end"].encode("utf-8")),
    }


def _assert_receipt_identity(value, manifest):
    require(type(value) is dict and set(value) == MEASUREMENT_KEYS)
    require(value["schema"] == "kp-context-measurement-receipt/v2")
    require(value["algorithm"] == ALGORITHM)
    require(value["tool"] == "kp_context_measure")
    require(value["tool_contract"] == TOOL_CONTRACT)
    require(value["whitespace_set_version"] == "unicode-15.0-White_Space")
    require(value["client_root_class"] == manifest["client_root_class"])
    require(value["baseline_id"] == manifest["baseline_id"])
    entries = sorted(
        manifest["projections"],
        key=lambda item: item["projection_id"].encode("ascii"),
    )
    expected_order = [item["projection_id"] for item in entries]
    require(value["projection_order"] == expected_order)
    rows = value["projections"]
    require(type(rows) is list and len(rows) == len(entries))
    for row, entry in zip(rows, entries):
        require(type(row) is dict and set(row) == PROJECTION_KEYS)
        require(row["projection_id"] == entry["projection_id"])
        require(row["path"] == entry["path"])
        require(row["select"] == _receipt_selector(entry["select"]))
    return rows


def _assert_measurement_receipt(value, manifest):
    rows = _assert_receipt_identity(value, manifest)
    require(value["status"] == "OK")
    sums = {key: 0 for key in TOTAL_KEYS}
    for row in rows:
        require(row["status"] == "OK")
        require(row["failure_class"] is None)
        require(
            type(row["raw_sha256"]) is str
            and HEX_64.fullmatch(row["raw_sha256"]) is not None
        )
        require(
            type(row["normalized_sha256"]) is str
            and HEX_64.fullmatch(row["normalized_sha256"]) is not None
        )
        for key in TOTAL_KEYS:
            require(type(row[key]) is int and row[key] >= 0)
            sums[key] += row[key]
    require(type(value["totals"]) is dict)
    require(set(value["totals"]) == TOTAL_KEYS)
    require(value["totals"] == sums)


def _assert_blocked_receipt(value, manifest):
    rows = _assert_receipt_identity(value, manifest)
    require(value["status"] == "BLOCKED_PREREQUISITE")
    require(value["totals"] is None)
    expected = {
        "absent-path": "PATH_UNREADABLE",
        "ambiguous": "REGION_AMBIGUOUS",
        "overlap": "REGION_MISORDERED",
    }
    require({row["projection_id"] for row in rows} == set(expected))
    for row in rows:
        require(row["status"] == "BLOCKED_PREREQUISITE")
        require(row["failure_class"] == expected[row["projection_id"]])
        require(all(
            row[key] is None
            for key in (
                "raw_sha256", "normalized_sha256", "bytes",
                "characters", "words",
            )
        ))


def _assert_compatible_comparison(value, baseline, candidate):
    baseline_totals = dict(baseline["totals"])
    candidate_totals = dict(candidate["totals"])
    max_characters = (baseline_totals["characters"] * 70) // 100
    max_words = (baseline_totals["words"] * 70) // 100
    expected = {
        "schema": "kp-context-measurement-comparison/v2",
        "algorithm": ALGORITHM,
        "tool": "kp_context_measure",
        "tool_contract": TOOL_CONTRACT,
        "whitespace_set_version": "unicode-15.0-White_Space",
        "status": "OK",
        "baseline_id": baseline["baseline_id"],
        "client_root_class": baseline["client_root_class"],
        "projection_order": list(baseline["projection_order"]),
        "baseline_totals": baseline_totals,
        "candidate_totals": candidate_totals,
        "delta": {
            key: candidate_totals[key] - baseline_totals[key]
            for key in TOTAL_KEYS
        },
        "target_30pct": {
            "max_characters": max_characters,
            "max_words": max_words,
            "meets_characters": (
                candidate_totals["characters"] <= max_characters
            ),
            "meets_words": candidate_totals["words"] <= max_words,
        },
    }
    require(type(value) is dict and set(value) == COMPARISON_KEYS)
    require(value == expected)


def _assert_incompatible_comparison(value):
    require(type(value) is dict)
    require(set(value) == {"schema", "status", "reasons"})
    require(value == {
        "schema": "kp-context-measurement-comparison/v2",
        "status": "COMPARISON_REFUSED",
        "reasons": ["BASELINE_ID_MISMATCH"],
    })


def _forbidden_source_fragments(paths):
    fragments = set()
    for path in paths.values():
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeError):
            raise DogfoodError()
        fragments.add(raw)
        for line in text.splitlines():
            encoded = line.encode("utf-8")
            if len(encoded) >= 4:
                fragments.add(encoded)
        escaped = json.dumps(
            text, ensure_ascii=True
        )[1:-1].encode("ascii")
        fragments.add(escaped)
    for fixture_id in ("region", "ambiguous", "overlap"):
        selector = _selector(fixture_id)
        for key in ("begin", "end"):
            marker = selector[key]
            fragments.add(marker.encode("utf-8"))
            fragments.add(
                json.dumps(marker, ensure_ascii=True)[1:-1].encode("ascii")
            )
    return {fragment for fragment in fragments if len(fragment) >= 4}


def _run_matrix(tool: Path, implementation_root: Path, fixture_root: Path):
    paths = {}
    for fixture_id, definition in FIXTURES.items():
        path = fixture_root / fixture_id
        try:
            path.write_bytes(base64.b64decode(definition["base64"]))
            path.chmod(0o600)
        except (OSError, ValueError):
            raise DogfoodError()
        paths[fixture_id] = path

    valid_manifest = fixture_root / "valid-manifest.json"
    blocked_manifest = fixture_root / "blocked-manifest.json"
    usage_manifest = fixture_root / "usage-manifest.json"
    _write_canonical(valid_manifest, _measurement_manifest(paths))
    _write_canonical(
        blocked_manifest,
        _blocked_manifest(paths, fixture_root / "absent"),
    )
    _write_canonical(usage_manifest, _usage_manifest(paths))

    fixture_manifest = _fixture_manifest(paths)
    pre_stats = _fixture_stats(paths)
    process_results = {}

    process_results["measure_a"] = _run_tool(
        tool, ["measure", "--manifest", str(valid_manifest)],
        implementation_root,
    )
    process_results["measure_b"] = _run_tool(
        tool, ["measure", "--manifest", str(valid_manifest)], Path("/")
    )
    require(process_results["measure_a"].returncode == 0)
    require(process_results["measure_b"].returncode == 0)
    receipt_a = _canonical_json_output(process_results["measure_a"])
    receipt_b = _canonical_json_output(process_results["measure_b"])
    _assert_measurement_receipt(
        receipt_a, _measurement_manifest(paths)
    )
    _assert_measurement_receipt(
        receipt_b, _measurement_manifest(paths)
    )
    receipt_a_bytes = process_results["measure_a"].stdout
    receipt_b_bytes = process_results["measure_b"].stdout
    require(receipt_a_bytes == receipt_b_bytes)

    receipt_a_path = fixture_root / "receipt-a.json"
    receipt_b_path = fixture_root / "receipt-b.json"
    try:
        receipt_a_path.write_bytes(receipt_a_bytes)
        receipt_b_path.write_bytes(receipt_b_bytes)
    except OSError:
        raise DogfoodError()
    process_results["compare_compatible"] = _run_tool(
        tool,
        [
            "compare", "--baseline", str(receipt_a_path),
            "--candidate", str(receipt_b_path),
        ],
        implementation_root,
    )
    require(process_results["compare_compatible"].returncode == 0)
    compatible = _canonical_json_output(
        process_results["compare_compatible"]
    )
    _assert_compatible_comparison(compatible, receipt_a, receipt_b)

    incompatible_value = json.loads(json.dumps(receipt_b))
    incompatible_value["baseline_id"] = "correction-dogfood-v1-other"
    incompatible_path = fixture_root / "receipt-incompatible.json"
    _write_canonical(incompatible_path, incompatible_value)
    process_results["compare_incompatible"] = _run_tool(
        tool,
        [
            "compare", "--baseline", str(receipt_a_path),
            "--candidate", str(incompatible_path),
        ],
        implementation_root,
    )
    require(process_results["compare_incompatible"].returncode == 4)
    incompatible = _canonical_json_output(
        process_results["compare_incompatible"]
    )
    _assert_incompatible_comparison(incompatible)

    process_results["blocked"] = _run_tool(
        tool, ["measure", "--manifest", str(blocked_manifest)],
        implementation_root,
    )
    require(process_results["blocked"].returncode == 2)
    blocked = _canonical_json_output(process_results["blocked"])
    _assert_blocked_receipt(
        blocked,
        _blocked_manifest(paths, fixture_root / "absent"),
    )

    process_results["usage"] = _run_tool(
        tool, ["measure", "--manifest", str(usage_manifest)],
        implementation_root,
    )
    require(process_results["usage"].returncode == 3)
    require(process_results["usage"].stdout == b"")
    require(
        process_results["usage"].stderr
        == b"kp_context_measure: USAGE_ERROR: select: MANIFEST_SCHEMA\n"
    )

    post_stats = _fixture_stats(paths)
    combined_output = b"".join(
        completed.stdout + completed.stderr
        for completed in process_results.values()
    )
    sentinel_absent = SENTINEL not in combined_output
    forbidden_fragments = _forbidden_source_fragments(paths)
    source_content_present = any(
        fragment in combined_output
        for fragment in forbidden_fragments
    )
    require(sentinel_absent)
    require(not source_content_present)
    require(pre_stats == post_stats)

    observed_exits = {
        key: process_results[key].returncode
        for key in EXPECTED_EXITS
    }
    require(observed_exits == EXPECTED_EXITS)
    return {
        "fixture_manifest_sha256": sha256(fixture_manifest),
        "run_a_receipt_sha256": sha256(receipt_a_bytes),
        "run_b_receipt_sha256": sha256(receipt_b_bytes),
        "pre_stats_sha256": sha256(pre_stats),
        "post_stats_sha256": sha256(post_stats),
        "observed_exits": observed_exits,
        "content_safety": {
            "sentinel_absent": sentinel_absent,
            "source_content_present": source_content_present,
            "input_immutable": pre_stats == post_stats,
            "receipts_byte_identical": receipt_a_bytes == receipt_b_bytes,
        },
    }


def _atomic_write_validated(
    output: Path, raw: bytes, implementation_root: Path
):
    require(not os.path.lexists(str(output)))
    parent = output.parent
    require(parent.is_dir())
    temporary_path = None
    descriptor = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=output.name + ".tmp.", dir=str(parent)
        )
        temporary_path = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        validate_evidence(temporary_path, implementation_root)
        require(not os.path.lexists(str(output)))
        os.rename(str(temporary_path), str(output))
        temporary_path = None
    except (OSError, DogfoodError):
        raise DogfoodError()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def run_dogfood(tool: Path, implementation_root: Path, output: Path):
    require(not os.path.lexists(str(output)))
    try:
        implementation_root = implementation_root.resolve(strict=True)
        output = output.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise DogfoodError()
    require(not os.path.lexists(str(output)))
    commit, tree = implementation_identity(implementation_root)
    tool = _bind_tool(tool, implementation_root, commit)
    try:
        with tempfile.TemporaryDirectory(
            prefix="kp-context-correction-"
        ) as temporary:
            matrix = _run_matrix(
                tool, implementation_root, Path(temporary)
            )
    except OSError:
        raise DogfoodError()

    value = {
        "schema": EVIDENCE_SCHEMA,
        "status": "PASS",
        "classification": CLASSIFICATION,
        "captured_at_utc": datetime.datetime.now(
            datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "implementation_commit": commit,
        "implementation_tree": tree,
        "algorithm": ALGORITHM,
        "tool_contract": TOOL_CONTRACT,
        "environment_class": ENVIRONMENT_CLASS,
        "command_set": COMMAND_SET,
        **matrix,
    }
    raw = canonical_bytes(value)
    validate_evidence_bytes(raw, implementation_root)
    require(SENTINEL not in raw)
    _atomic_write_validated(output, raw, implementation_root)


def parser():
    value = ClosedArgumentParser(prog="correction_dogfood")
    subparsers = value.add_subparsers(
        dest="verb", required=True, parser_class=ClosedArgumentParser
    )
    run = subparsers.add_parser("run")
    run.add_argument("--tool", required=True)
    run.add_argument("--implementation-root", required=True)
    run.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", required=True)
    validate.add_argument("--implementation-root", required=True)
    return value


def fail(message: str):
    print(message, file=sys.stderr)
    return 3


def main(argv):
    try:
        args = parser().parse_args(argv)
    except CliError:
        return fail("correction dogfood invalid")
    try:
        if args.verb == "run":
            run_dogfood(
                Path(args.tool),
                Path(args.implementation_root),
                Path(args.output),
            )
        else:
            validate_evidence(
                Path(args.evidence), Path(args.implementation_root)
            )
    except DogfoodError:
        if args.verb == "validate":
            return fail("correction evidence invalid")
        return fail("correction dogfood failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
