#!/usr/bin/env python3
"""Deterministic, read-only, content-safe context measurement.

The counting primitives remain ``kp-context-measurement/v1``.  ADR 0005 owns
the closed v2 input, receipt, comparison, and process contracts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import stat
import sys

ALGORITHM = "kp-context-measurement/v1"
INPUT_SCHEMA = "kp-context-measurement-input/v2"
RECEIPT_SCHEMA = "kp-context-measurement-receipt/v2"
COMPARISON_SCHEMA = "kp-context-measurement-comparison/v2"
TOOL = "kp_context_measure"
TOOL_CONTRACT = "kp-context-measurement-tool/v2"
WHITESPACE_SET_VERSION = "unicode-15.0-White_Space"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
MEASUREMENT_STATUSES = frozenset({"OK", "BLOCKED_PREREQUISITE"})
FAILURE_CLASSES = frozenset({
    "PATH_UNREADABLE",
    "INVALID_UTF8",
    "REGION_NOT_FOUND",
    "REGION_AMBIGUOUS",
    "REGION_MISORDERED",
})
COMPARISON_REASONS = frozenset({
    "BASELINE_RECEIPT_UNREADABLE",
    "CANDIDATE_RECEIPT_UNREADABLE",
    "BASELINE_RECEIPT_INVALID",
    "CANDIDATE_RECEIPT_INVALID",
    "UNSUPPORTED_RECEIPT_SCHEMA",
    "BASELINE_ALGORITHM_UNSUPPORTED",
    "CANDIDATE_ALGORITHM_UNSUPPORTED",
    "BASELINE_TOOL_CONTRACT_UNSUPPORTED",
    "CANDIDATE_TOOL_CONTRACT_UNSUPPORTED",
    "BASELINE_WHITESPACE_SET_UNSUPPORTED",
    "CANDIDATE_WHITESPACE_SET_UNSUPPORTED",
    "ALGORITHM_MISMATCH",
    "TOOL_CONTRACT_MISMATCH",
    "WHITESPACE_SET_MISMATCH",
    "BASELINE_NOT_OK",
    "CANDIDATE_NOT_OK",
    "CLIENT_ROOT_CLASS_MISMATCH",
    "BASELINE_ID_MISMATCH",
    "PROJECTION_ORDER_MISMATCH",
    "PROJECTION_DESCRIPTOR_MISMATCH",
})
# Pinned Unicode 15.0 White_Space property (25 code points). NOT str.isspace()/str.split(),
# which also treat U+001C-U+001F as separators and would drift from the accepted contract.
WHITE_SPACE = frozenset(
    {0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
     0x2028, 0x2029, 0x202F, 0x205F, 0x3000} | set(range(0x2000, 0x200A + 1))
)


class InputError(Exception):
    def __init__(self, location: str, error_class: str):
        super().__init__(location, error_class)
        self.location = location
        self.error_class = error_class


class CliArgumentsError(Exception):
    pass


class DuplicateJsonKeyError(ValueError):
    pass


class InvalidJsonConstantError(ValueError):
    pass


class ReceiptInvalid(Exception):
    pass


def _is_token(value) -> bool:
    return type(value) is str and TOKEN_PATTERN.fullmatch(value) is not None


def _is_digest(value) -> bool:
    return type(value) is str and DIGEST_PATTERN.fullmatch(value) is not None


def _is_nonnegative_int(value) -> bool:
    return type(value) is int and value >= 0


def _is_scalar_string(value, *, nonempty: bool, allow_nul: bool) -> bool:
    if type(value) is not str:
        return False
    if nonempty and not value:
        return False
    if not allow_nul and "\x00" in value:
        return False
    return not any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _object_without_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJsonKeyError()
        value[key] = item
    return value


def _reject_json_constant(_value):
    raise InvalidJsonConstantError()


def _parse_json_text(text: str):
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_json_constant,
    )


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def count_characters(normalized: str) -> int:
    return len(normalized)


def count_words(normalized: str) -> int:
    count = 0
    in_run = False
    for ch in normalized:
        if ord(ch) in WHITE_SPACE:
            in_run = False
        elif not in_run:
            count += 1
            in_run = True
    return count


def decode_strict_utf8(raw: bytes) -> str:
    return raw.decode("utf-8", errors="strict")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RegionError(Exception):
    def __init__(self, failure_class: str):
        super().__init__(failure_class)
        self.failure_class = failure_class


def marker_occurrences(full_text: str, marker: str) -> list:
    starts = []
    offset = 0
    while True:
        found = full_text.find(marker, offset)
        if found == -1:
            return starts
        starts.append(found)
        offset = found + 1


def select_region(full_text: str, begin: str, end: str) -> str:
    begin_starts = marker_occurrences(full_text, begin)
    end_starts = marker_occurrences(full_text, end)
    if not begin_starts or not end_starts:
        raise RegionError("REGION_NOT_FOUND")
    if len(begin_starts) > 1 or len(end_starts) > 1:
        raise RegionError("REGION_AMBIGUOUS")
    begin_start = begin_starts[0]
    end_start = end_starts[0]
    if end_start < begin_start + len(begin):
        raise RegionError("REGION_MISORDERED")
    return full_text[begin_start:end_start + len(end)]


def _receipt_selector(selector: dict) -> dict:
    if selector["kind"] == "full":
        return {"kind": "full"}
    return {
        "kind": "region",
        "begin_sha256": sha256_hex(selector["begin"].encode("utf-8")),
        "end_sha256": sha256_hex(selector["end"].encode("utf-8")),
    }


def _blank_entry(entry: dict) -> dict:
    return {
        "projection_id": entry["projection_id"],
        "path": entry["path"],
        "select": _receipt_selector(entry["select"]),
        "status": "OK",
        "failure_class": None,
        "raw_sha256": None,
        "normalized_sha256": None,
        "bytes": None,
        "characters": None,
        "words": None,
    }


def _read_regular_file(path: str):
    try:
        before = os.stat(path, follow_symlinks=True)
        if not stat.S_ISREG(before.st_mode):
            return None
        with open(path, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                return None
            return handle.read()
    except OSError:
        return None


def measure_entry(entry: dict) -> dict:
    out = _blank_entry(entry)
    raw = _read_regular_file(entry["path"])
    if raw is None:
        out.update(
            status="BLOCKED_PREREQUISITE",
            failure_class="PATH_UNREADABLE",
        )
        return out
    try:
        full_text = decode_strict_utf8(raw)
    except UnicodeDecodeError:
        out.update(
            status="BLOCKED_PREREQUISITE",
            failure_class="INVALID_UTF8",
            raw_sha256=sha256_hex(raw),
            bytes=len(raw),
        )
        return out
    sel = entry["select"]
    if sel["kind"] == "region":
        try:
            selected = select_region(full_text, sel["begin"], sel["end"])
        except RegionError as err:
            out.update(
                status="BLOCKED_PREREQUISITE",
                failure_class=err.failure_class,
            )
            return out
        raw_selected = selected.encode("utf-8")
    else:
        selected, raw_selected = full_text, raw
    normalized = normalize_newlines(selected)
    norm_bytes = normalized.encode("utf-8")
    out.update(raw_sha256=sha256_hex(raw_selected), normalized_sha256=sha256_hex(norm_bytes),
               bytes=len(raw_selected), characters=count_characters(normalized),
               words=count_words(normalized))
    return out


def build_receipt(client_root_class: str, baseline_id: str, entries: list) -> tuple:
    client_root_class, baseline_id, validated = validate_manifest({
        "schema": INPUT_SCHEMA,
        "client_root_class": client_root_class,
        "baseline_id": baseline_id,
        "projections": entries,
    })
    measured = [measure_entry(entry) for entry in validated]
    ok = all(m["status"] == "OK" for m in measured)
    totals = None
    if ok:
        totals = {"bytes": sum(m["bytes"] for m in measured),
                  "characters": sum(m["characters"] for m in measured),
                  "words": sum(m["words"] for m in measured)}
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "algorithm": ALGORITHM,
        "tool": TOOL,
        "tool_contract": TOOL_CONTRACT,
        "whitespace_set_version": WHITESPACE_SET_VERSION,
        "status": "OK" if ok else "BLOCKED_PREREQUISITE",
        "client_root_class": client_root_class,
        "baseline_id": baseline_id,
        "projection_order": [row["projection_id"] for row in measured],
        "projections": measured,
        "totals": totals,
    }
    try:
        validate_receipt(receipt)
    except ReceiptInvalid as error:
        raise RuntimeError("generated receipt violated contract") from error
    return receipt, (0 if ok else 2)


def emit(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def validate_manifest(document):
    top_keys = {
        "schema", "client_root_class", "baseline_id", "projections",
    }
    if type(document) is not dict or set(document) != top_keys:
        raise InputError("manifest", "MANIFEST_SCHEMA")
    if document["schema"] != INPUT_SCHEMA:
        raise InputError("manifest", "MANIFEST_SCHEMA")
    if not _is_token(document["client_root_class"]):
        raise InputError("manifest", "MANIFEST_VALUE")
    if not _is_token(document["baseline_id"]):
        raise InputError("manifest", "MANIFEST_VALUE")
    projections = document["projections"]
    if type(projections) is not list:
        raise InputError("manifest", "MANIFEST_SCHEMA")
    if not projections:
        raise InputError("manifest", "MANIFEST_VALUE")

    seen = set()
    validated = []
    projection_keys = {"projection_id", "path", "select"}
    for projection in projections:
        if type(projection) is not dict or set(projection) != projection_keys:
            raise InputError("projection", "MANIFEST_SCHEMA")
        projection_id = projection["projection_id"]
        if not _is_token(projection_id):
            raise InputError("projection", "MANIFEST_VALUE")
        if projection_id in seen:
            raise InputError("projection", "MANIFEST_VALUE")
        seen.add(projection_id)
        path = projection["path"]
        if not _is_scalar_string(path, nonempty=True, allow_nul=False):
            raise InputError("projection", "MANIFEST_VALUE")

        selector = projection["select"]
        if type(selector) is not dict or "kind" not in selector:
            raise InputError("select", "MANIFEST_SCHEMA")
        kind = selector["kind"]
        if type(kind) is not str:
            raise InputError("select", "MANIFEST_SCHEMA")
        if kind == "full":
            if set(selector) != {"kind"}:
                raise InputError("select", "MANIFEST_SCHEMA")
            clean_selector = {"kind": "full"}
        elif kind == "region":
            if set(selector) != {"kind", "begin", "end"}:
                raise InputError("select", "MANIFEST_SCHEMA")
            begin = selector["begin"]
            end = selector["end"]
            if not _is_scalar_string(
                begin, nonempty=True, allow_nul=True
            ) or not _is_scalar_string(
                end, nonempty=True, allow_nul=True
            ):
                raise InputError("select", "MANIFEST_VALUE")
            if begin == end:
                raise InputError("select", "MANIFEST_VALUE")
            clean_selector = {"kind": "region", "begin": begin, "end": end}
        else:
            raise InputError("select", "MANIFEST_VALUE")
        validated.append({
            "projection_id": projection_id,
            "path": path,
            "select": clean_selector,
        })

    validated.sort(key=lambda item: item["projection_id"].encode("ascii"))
    return (
        document["client_root_class"],
        document["baseline_id"],
        validated,
    )


def load_manifest(path: str):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        raise InputError("manifest", "MANIFEST_UNREADABLE")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise InputError("manifest", "MANIFEST_INVALID_UTF8")
    try:
        document = _parse_json_text(text)
    except (
        ValueError,
        RecursionError,
    ):
        raise InputError("manifest", "MANIFEST_INVALID_JSON")
    return validate_manifest(document)


def _validate_receipt_selector(selector):
    if type(selector) is not dict or "kind" not in selector:
        raise ReceiptInvalid()
    if selector["kind"] == "full":
        if set(selector) != {"kind"}:
            raise ReceiptInvalid()
        return
    if selector["kind"] == "region":
        if set(selector) != {
            "kind", "begin_sha256", "end_sha256",
        }:
            raise ReceiptInvalid()
        if not _is_digest(selector["begin_sha256"]):
            raise ReceiptInvalid()
        if not _is_digest(selector["end_sha256"]):
            raise ReceiptInvalid()
        if selector["begin_sha256"] == selector["end_sha256"]:
            raise ReceiptInvalid()
        return
    raise ReceiptInvalid()


def _validate_totals(totals):
    if type(totals) is not dict or set(totals) != {
        "bytes", "characters", "words",
    }:
        raise ReceiptInvalid()
    if not all(_is_nonnegative_int(totals[key]) for key in totals):
        raise ReceiptInvalid()


def validate_receipt(receipt):
    top_keys = {
        "schema", "algorithm", "tool", "tool_contract",
        "whitespace_set_version", "status", "client_root_class",
        "baseline_id", "projection_order", "projections", "totals",
    }
    if type(receipt) is not dict or set(receipt) != top_keys:
        raise ReceiptInvalid()
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise ReceiptInvalid()
    if not _is_token(receipt["algorithm"]):
        raise ReceiptInvalid()
    if receipt["tool"] != TOOL:
        raise ReceiptInvalid()
    if not _is_token(receipt["tool_contract"]):
        raise ReceiptInvalid()
    if not _is_token(receipt["whitespace_set_version"]):
        raise ReceiptInvalid()
    if (
        type(receipt["status"]) is not str
        or receipt["status"] not in MEASUREMENT_STATUSES
    ):
        raise ReceiptInvalid()
    if not _is_token(receipt["client_root_class"]):
        raise ReceiptInvalid()
    if not _is_token(receipt["baseline_id"]):
        raise ReceiptInvalid()

    order = receipt["projection_order"]
    rows = receipt["projections"]
    if type(order) is not list or not order:
        raise ReceiptInvalid()
    if not all(_is_token(item) for item in order):
        raise ReceiptInvalid()
    if len(order) != len(set(order)):
        raise ReceiptInvalid()
    if order != sorted(order, key=lambda item: item.encode("ascii")):
        raise ReceiptInvalid()
    if type(rows) is not list or len(rows) != len(order):
        raise ReceiptInvalid()

    row_keys = {
        "projection_id", "path", "select", "status", "failure_class",
        "raw_sha256", "normalized_sha256", "bytes", "characters",
        "words",
    }
    all_ok = True
    sums = {"bytes": 0, "characters": 0, "words": 0}
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != row_keys:
            raise ReceiptInvalid()
        if row["projection_id"] != order[index]:
            raise ReceiptInvalid()
        if not _is_scalar_string(
            row["path"], nonempty=True, allow_nul=False
        ):
            raise ReceiptInvalid()
        _validate_receipt_selector(row["select"])
        if (
            type(row["status"]) is not str
            or row["status"] not in MEASUREMENT_STATUSES
        ):
            raise ReceiptInvalid()
        if row["status"] == "OK":
            if row["failure_class"] is not None:
                raise ReceiptInvalid()
            if not _is_digest(row["raw_sha256"]):
                raise ReceiptInvalid()
            if not _is_digest(row["normalized_sha256"]):
                raise ReceiptInvalid()
            for key in ("bytes", "characters", "words"):
                if not _is_nonnegative_int(row[key]):
                    raise ReceiptInvalid()
                sums[key] += row[key]
            continue

        all_ok = False
        failure_class = row["failure_class"]
        if (
            type(failure_class) is not str
            or failure_class not in FAILURE_CLASSES
        ):
            raise ReceiptInvalid()
        if (
            failure_class.startswith("REGION_")
            and row["select"]["kind"] != "region"
        ):
            raise ReceiptInvalid()
        if failure_class == "INVALID_UTF8":
            if not _is_digest(row["raw_sha256"]):
                raise ReceiptInvalid()
            if not _is_nonnegative_int(row["bytes"]):
                raise ReceiptInvalid()
            if any(
                row[key] is not None
                for key in ("normalized_sha256", "characters", "words")
            ):
                raise ReceiptInvalid()
        elif any(
            row[key] is not None
            for key in (
                "raw_sha256", "normalized_sha256", "bytes",
                "characters", "words",
            )
        ):
            raise ReceiptInvalid()

    if all_ok:
        if receipt["status"] != "OK":
            raise ReceiptInvalid()
        _validate_totals(receipt["totals"])
        if receipt["totals"] != sums:
            raise ReceiptInvalid()
    else:
        if receipt["status"] != "BLOCKED_PREREQUISITE":
            raise ReceiptInvalid()
        if receipt["totals"] is not None:
            raise ReceiptInvalid()
    return receipt


def _receipt_object_state(value):
    if type(value) is not dict or "schema" not in value:
        return "invalid"
    schema = value["schema"]
    if type(schema) is str and schema != RECEIPT_SCHEMA:
        return "unsupported"
    if schema != RECEIPT_SCHEMA:
        return "invalid"
    try:
        validate_receipt(value)
    except ReceiptInvalid:
        return "invalid"
    return "valid"


def _load_receipt(path: str):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return "unreadable", None
    try:
        text = raw.decode("utf-8", errors="strict")
        value = _parse_json_text(text)
    except (
        UnicodeDecodeError,
        ValueError,
        RecursionError,
    ):
        return "invalid", None
    state = _receipt_object_state(value)
    if state == "valid" and raw != emit(value).encode("ascii"):
        return "invalid", None
    return state, value


def _projection_descriptors(receipt):
    return [
        (row["projection_id"], row["path"], row["select"])
        for row in receipt["projections"]
    ]


def _comparison_refusal(reasons):
    value = {
        "schema": COMPARISON_SCHEMA,
        "status": "COMPARISON_REFUSED",
        "reasons": sorted(set(reasons)),
    }
    try:
        validate_comparison(value)
    except ReceiptInvalid as error:
        raise RuntimeError("generated comparison refusal violated contract") from error
    return value, 4


def _comparison_from_valid_receipts(baseline, candidate):
    reasons = []
    if baseline["algorithm"] != ALGORITHM:
        reasons.append("BASELINE_ALGORITHM_UNSUPPORTED")
    if candidate["algorithm"] != ALGORITHM:
        reasons.append("CANDIDATE_ALGORITHM_UNSUPPORTED")
    if baseline["tool_contract"] != TOOL_CONTRACT:
        reasons.append("BASELINE_TOOL_CONTRACT_UNSUPPORTED")
    if candidate["tool_contract"] != TOOL_CONTRACT:
        reasons.append("CANDIDATE_TOOL_CONTRACT_UNSUPPORTED")
    if baseline["whitespace_set_version"] != WHITESPACE_SET_VERSION:
        reasons.append("BASELINE_WHITESPACE_SET_UNSUPPORTED")
    if candidate["whitespace_set_version"] != WHITESPACE_SET_VERSION:
        reasons.append("CANDIDATE_WHITESPACE_SET_UNSUPPORTED")
    if baseline["algorithm"] != candidate["algorithm"]:
        reasons.append("ALGORITHM_MISMATCH")
    if baseline["tool_contract"] != candidate["tool_contract"]:
        reasons.append("TOOL_CONTRACT_MISMATCH")
    if (
        baseline["whitespace_set_version"]
        != candidate["whitespace_set_version"]
    ):
        reasons.append("WHITESPACE_SET_MISMATCH")
    if baseline["status"] != "OK":
        reasons.append("BASELINE_NOT_OK")
    if candidate["status"] != "OK":
        reasons.append("CANDIDATE_NOT_OK")
    if baseline["client_root_class"] != candidate["client_root_class"]:
        reasons.append("CLIENT_ROOT_CLASS_MISMATCH")
    if baseline["baseline_id"] != candidate["baseline_id"]:
        reasons.append("BASELINE_ID_MISMATCH")
    if baseline["projection_order"] != candidate["projection_order"]:
        reasons.append("PROJECTION_ORDER_MISMATCH")
    if _projection_descriptors(baseline) != _projection_descriptors(candidate):
        reasons.append("PROJECTION_DESCRIPTOR_MISMATCH")
    if reasons:
        return _comparison_refusal(reasons)

    baseline_totals = dict(baseline["totals"])
    candidate_totals = dict(candidate["totals"])
    max_characters = (baseline_totals["characters"] * 70) // 100
    max_words = (baseline_totals["words"] * 70) // 100
    value = {
        "schema": COMPARISON_SCHEMA,
        "algorithm": ALGORITHM,
        "tool": TOOL,
        "tool_contract": TOOL_CONTRACT,
        "whitespace_set_version": WHITESPACE_SET_VERSION,
        "status": "OK",
        "baseline_id": baseline["baseline_id"],
        "client_root_class": baseline["client_root_class"],
        "projection_order": list(baseline["projection_order"]),
        "baseline_totals": baseline_totals,
        "candidate_totals": candidate_totals,
        "delta": {
            key: candidate_totals[key] - baseline_totals[key]
            for key in ("bytes", "characters", "words")
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
    try:
        validate_comparison(value)
    except ReceiptInvalid as error:
        raise RuntimeError("generated comparison violated contract") from error
    return value, 0


def compare_receipts(baseline: dict, candidate: dict):
    baseline_state = _receipt_object_state(baseline)
    candidate_state = _receipt_object_state(candidate)
    reasons = []
    if baseline_state == "invalid":
        reasons.append("BASELINE_RECEIPT_INVALID")
    elif baseline_state == "unsupported":
        reasons.append("UNSUPPORTED_RECEIPT_SCHEMA")
    if candidate_state == "invalid":
        reasons.append("CANDIDATE_RECEIPT_INVALID")
    elif candidate_state == "unsupported":
        reasons.append("UNSUPPORTED_RECEIPT_SCHEMA")
    if reasons:
        return _comparison_refusal(reasons)
    return _comparison_from_valid_receipts(baseline, candidate)


def compare_receipt_paths(baseline_path: str, candidate_path: str):
    baseline_state, baseline = _load_receipt(baseline_path)
    candidate_state, candidate = _load_receipt(candidate_path)
    reasons = []
    side_states = (
        ("BASELINE", baseline_state),
        ("CANDIDATE", candidate_state),
    )
    for side, state in side_states:
        if state == "unreadable":
            reasons.append(f"{side}_RECEIPT_UNREADABLE")
        elif state == "invalid":
            reasons.append(f"{side}_RECEIPT_INVALID")
        elif state == "unsupported":
            reasons.append("UNSUPPORTED_RECEIPT_SCHEMA")
    if reasons:
        return _comparison_refusal(reasons)
    return _comparison_from_valid_receipts(baseline, candidate)


def validate_comparison(value):
    if type(value) is not dict or value.get("schema") != COMPARISON_SCHEMA:
        raise ReceiptInvalid()
    if value.get("status") == "COMPARISON_REFUSED":
        if set(value) != {"schema", "status", "reasons"}:
            raise ReceiptInvalid()
        reasons = value["reasons"]
        if type(reasons) is not list or not reasons:
            raise ReceiptInvalid()
        if not all(
            type(reason) is str and reason in COMPARISON_REASONS
            for reason in reasons
        ):
            raise ReceiptInvalid()
        if reasons != sorted(set(reasons)):
            raise ReceiptInvalid()
        return value

    success_keys = {
        "schema", "algorithm", "tool", "tool_contract",
        "whitespace_set_version", "status", "baseline_id",
        "client_root_class", "projection_order", "baseline_totals",
        "candidate_totals", "delta", "target_30pct",
    }
    if set(value) != success_keys or value["status"] != "OK":
        raise ReceiptInvalid()
    if value["algorithm"] != ALGORITHM or value["tool"] != TOOL:
        raise ReceiptInvalid()
    if value["tool_contract"] != TOOL_CONTRACT:
        raise ReceiptInvalid()
    if value["whitespace_set_version"] != WHITESPACE_SET_VERSION:
        raise ReceiptInvalid()
    if not _is_token(value["baseline_id"]):
        raise ReceiptInvalid()
    if not _is_token(value["client_root_class"]):
        raise ReceiptInvalid()
    order = value["projection_order"]
    if type(order) is not list or not order:
        raise ReceiptInvalid()
    if not all(_is_token(item) for item in order):
        raise ReceiptInvalid()
    if order != sorted(set(order), key=lambda item: item.encode("ascii")):
        raise ReceiptInvalid()
    _validate_totals(value["baseline_totals"])
    _validate_totals(value["candidate_totals"])
    delta = value["delta"]
    if type(delta) is not dict or set(delta) != {
        "bytes", "characters", "words",
    }:
        raise ReceiptInvalid()
    if not all(type(delta[key]) is int for key in delta):
        raise ReceiptInvalid()
    for key in delta:
        if delta[key] != (
            value["candidate_totals"][key] - value["baseline_totals"][key]
        ):
            raise ReceiptInvalid()
    target = value["target_30pct"]
    if type(target) is not dict or set(target) != {
        "max_characters", "max_words", "meets_characters", "meets_words",
    }:
        raise ReceiptInvalid()
    max_characters = (value["baseline_totals"]["characters"] * 70) // 100
    max_words = (value["baseline_totals"]["words"] * 70) // 100
    if type(target["max_characters"]) is not int:
        raise ReceiptInvalid()
    if type(target["max_words"]) is not int:
        raise ReceiptInvalid()
    if type(target["meets_characters"]) is not bool:
        raise ReceiptInvalid()
    if type(target["meets_words"]) is not bool:
        raise ReceiptInvalid()
    if target != {
        "max_characters": max_characters,
        "max_words": max_words,
        "meets_characters": (
            value["candidate_totals"]["characters"] <= max_characters
        ),
        "meets_words": value["candidate_totals"]["words"] <= max_words,
    }:
        raise ReceiptInvalid()
    return value


class ControlledArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CliArgumentsError()


def _parser():
    parser = ControlledArgumentParser(prog=TOOL)
    subparsers = parser.add_subparsers(
        dest="verb", required=True, parser_class=ControlledArgumentParser
    )
    measure = subparsers.add_parser("measure")
    measure.add_argument("--manifest")
    measure.add_argument("--path")
    measure.add_argument("--projection-id")
    measure.add_argument("--client-root-class")
    measure.add_argument("--baseline-id")
    measure.add_argument("--region-begin")
    measure.add_argument("--region-end")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    return parser


def _write_usage_error(location: str, error_class: str):
    sys.stderr.write(
        f"{TOOL}: USAGE_ERROR: {location}: {error_class}\n"
    )
    return 3


def _measure_arguments(args):
    has_manifest = args.manifest is not None
    has_path = args.path is not None
    if has_manifest == has_path:
        raise CliArgumentsError()
    single_path_values = (
        args.projection_id,
        args.client_root_class,
        args.baseline_id,
        args.region_begin,
        args.region_end,
    )
    if has_manifest:
        if any(value is not None for value in single_path_values):
            raise CliArgumentsError()
        return load_manifest(args.manifest)
    if any(
        value is None
        for value in (
            args.projection_id,
            args.client_root_class,
            args.baseline_id,
        )
    ):
        raise CliArgumentsError()
    if (args.region_begin is None) != (args.region_end is None):
        raise CliArgumentsError()
    selector = {"kind": "full"}
    if args.region_begin is not None:
        selector = {
            "kind": "region",
            "begin": args.region_begin,
            "end": args.region_end,
        }
    return validate_manifest({
        "schema": INPUT_SCHEMA,
        "client_root_class": args.client_root_class,
        "baseline_id": args.baseline_id,
        "projections": [{
            "projection_id": args.projection_id,
            "path": args.path,
            "select": selector,
        }],
    })


def main(argv):
    try:
        args = _parser().parse_args(argv)
    except CliArgumentsError:
        return _write_usage_error("cli", "CLI_ARGUMENTS")

    if args.verb == "measure":
        try:
            client_root_class, baseline_id, entries = _measure_arguments(args)
            receipt, code = build_receipt(
                client_root_class, baseline_id, entries
            )
        except CliArgumentsError:
            return _write_usage_error("cli", "CLI_ARGUMENTS")
        except InputError as error:
            return _write_usage_error(error.location, error.error_class)
        sys.stdout.write(emit(receipt))
        return code

    comparison, code = compare_receipt_paths(
        args.baseline, args.candidate
    )
    sys.stdout.write(emit(comparison))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
