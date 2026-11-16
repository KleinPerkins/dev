"""Frozen v1 wire contracts for manifest-driven verification.

This module is dependency-free, deterministic, and offline.  It contains no
selector, execution, rollout, or persistence behavior.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
DOT_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
MODE_RE = re.compile(r"^[0-9]{6}$")
BASE64_RE = re.compile(
    r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
)
RUNNERLESS_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PR_REFERENCE_RE = re.compile(r"^pr/[0-9]+$")
WEEK_RE = re.compile(r"^([0-9]{4})-W([0-9]{2})$")
MONTH_RE = re.compile(r"^([0-9]{4})-([0-9]{2})$")

REPOSITORY_ID = "KleinPerkins/dev"
MANIFEST_SCHEMA = "dev-verification-manifest"
RECEIPT_SCHEMA = "dev-verification-receipt"
LEDGER_SCHEMA = "dev-verification-rollout-ledger"
ACCEPTANCE_COMMIT_SHA = "a99abb4fde94836e6e3f697cda8c520f3c2ae6b7"
GENESIS_AT = "2026-09-02T17:51:34Z"
OPERATOR_RECORD_SHA256 = (
    "sha256:2a73500812202c56c7071f5e640c43096d6093c86530fe219fa73c134b72a651"
)
CLASSIFICATION_TOOL_SHA256 = (
    "sha256:4535a29289775cf6dfe8491ed5d920f03af05b67592678c6eeaaaa4ebab292f4"
)

MANIFEST_MODES = (
    "deep_periodic",
    "focused_local",
    "focused_pr",
    "full",
    "full_release",
    "pre_commit",
)
CAUSE_CODES = (
    "deep_mode",
    "dependency",
    "direct",
    "fallback",
    "full_mode",
    "inert",
    "not_applicable",
    "reverse_impact",
    "self_protection",
    "universal",
)
DISPOSITIONS = ("blocked", "not_applicable", "run", "skip")
OUTCOMES = ("cleanup_failed", "failed", "not_observed", "passed", "timed_out")
EVENT_TYPES = (
    "acceptance",
    "authority_genesis",
    "graduation",
    "invalidation",
    "observation",
    "restoration",
    "rollback",
)
AUTHORITY_PATHS = (
    "_ops/adr/0011-manifest-driven-verification-selector.md",
    "_ops/plans/manifest-driven-verification-execution-v1.md",
    "_ops/plans/manifest-driven-verification-target-design-v1.md",
)
AUTHORITY_ARTIFACTS = {
    "_ops/adr/0011-manifest-driven-verification-selector.md": (
        "sha256:76d6039acb5eb604de010a090f2e5128e19874296bf838423237ddf835c08883",
        18500,
    ),
    "_ops/plans/manifest-driven-verification-execution-v1.md": (
        "sha256:8454a1bbfe2c59cb9b5f59dda836514c315cf92154034f25f70f46082a602850",
        67647,
    ),
    "_ops/plans/manifest-driven-verification-target-design-v1.md": (
        "sha256:cc3e3470fe759729716969da3690d95179b643c611f43051a5f9e7e85debf2ed",
        73217,
    ),
}
LIMITS = {
    "max_blob_bytes": 1048576,
    "max_changed_pointers": 10000,
    "max_depth": 64,
    "max_nodes": 100000,
    "max_number_chars": 128,
}


class ContractError(ValueError):
    """A value is outside the frozen v1 contract."""


class Sha256Id(str):
    """A content identity in the v1 sha256 wire form."""

    def __new__(cls, value: str) -> "Sha256Id":
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise ContractError("expected sha256:<64 lowercase hex>")
        return str.__new__(cls, value)


class CommitSha(str):
    """A 40-character lowercase Git object identity."""

    def __new__(cls, value: str) -> "CommitSha":
        if not isinstance(value, str) or not COMMIT_SHA_RE.fullmatch(value):
            raise ContractError("expected 40 lowercase hexadecimal characters")
        return str.__new__(cls, value)


def _check_scalar_text(value: str, where: str = "string") -> None:
    if not isinstance(value, str):
        raise ContractError(f"{where}: expected string")
    for char in value:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise ContractError(f"{where}: unpaired Unicode surrogate")


def _escape_string(value: str) -> str:
    _check_scalar_text(value)
    short = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }
    pieces: list[str] = ['"']
    for char in value:
        if char in short:
            pieces.append(short[char])
        elif ord(char) < 0x20:
            pieces.append(f"\\u{ord(char):04x}")
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)


def canonical_json(value: Any) -> bytes:
    """Encode one value with Appendix A.1's restricted canonical profile."""

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int) and not isinstance(item, bool):
            if item < INT64_MIN or item > INT64_MAX:
                raise ContractError("integer outside signed 64-bit range")
            return str(item)
        if isinstance(item, float) or isinstance(item, Decimal):
            raise ContractError("non-integer numbers are forbidden")
        if isinstance(item, str):
            return _escape_string(item)
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            for key in item:
                _check_scalar_text(key, "object key")
            keys = sorted(item, key=lambda key: key.encode("utf-8"))
            return "{" + ",".join(
                f"{_escape_string(key)}:{encode(item[key])}" for key in keys
            ) + "}"
        raise ContractError(f"unsupported canonical JSON type: {type(item).__name__}")

    return encode(value).encode("utf-8")


def _parse_int_token(token: str) -> int:
    if not re.fullmatch(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)", token) or token == "-0":
        raise ContractError(f"non-minimal integer: {token}")
    value = int(token)
    if value < INT64_MIN or value > INT64_MAX:
        raise ContractError("integer outside signed 64-bit range")
    return value


def _reject_non_integer(token: str) -> None:
    raise ContractError(f"non-integer number is forbidden: {token}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _check_scalar_text(key, "object key")
        if key in result:
            raise ContractError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _check_tree_scalars(value: Any) -> None:
    if isinstance(value, str):
        _check_scalar_text(value)
    elif isinstance(value, list):
        for child in value:
            _check_tree_scalars(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_scalar_text(key, "object key")
            _check_tree_scalars(child)


def parse_json_document(data: bytes | str) -> Any:
    """Parse strict JSON while permitting non-canonical document whitespace."""

    if isinstance(data, bytes):
        if data.startswith(b"\xef\xbb\xbf"):
            raise ContractError("UTF-8 BOM is forbidden")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ContractError("invalid UTF-8") from exc
    elif isinstance(data, str):
        text = data
    else:
        raise ContractError("JSON input must be bytes or text")
    if text.startswith("\ufeff"):
        raise ContractError("UTF-8 BOM is forbidden")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_int=_parse_int_token,
            parse_float=_reject_non_integer,
            parse_constant=_reject_non_integer,
            strict=True,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc
    _check_tree_scalars(value)
    return value


def validate_canonical_input(data: bytes) -> Any:
    """Parse and reject every byte sequence that is not canonical A.1 input."""

    if not isinstance(data, bytes):
        raise ContractError("canonical input must be bytes")
    value = parse_json_document(data)
    expected = canonical_json(value)
    if data != expected:
        raise ContractError("input is not canonical JSON")
    return value


def sha256_id(data: bytes) -> Sha256Id:
    if not isinstance(data, bytes):
        raise ContractError("SHA-256 input must be bytes")
    return Sha256Id("sha256:" + hashlib.sha256(data).hexdigest())


def derive_identity(value: Mapping[str, Any], field: str) -> Sha256Id:
    if not isinstance(value, Mapping):
        raise ContractError("identity input must be an object")
    if field not in value:
        raise ContractError(f"identity field omitted from stored object: {field}")
    preimage = dict(value)
    del preimage[field]
    return sha256_id(canonical_json(preimage))


def with_derived_identity(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = ""
    result[field] = str(derive_identity(result, field))
    return result


def _decode_base64(value: str, where: str) -> bytes:
    if not isinstance(value, str) or not value or not BASE64_RE.fullmatch(value):
        raise ContractError(f"{where}: malformed padded RFC 4648 base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ContractError(f"{where}: malformed padded RFC 4648 base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ContractError(f"{where}: non-canonical base64")
    return decoded


def _validate_path_bytes(raw: bytes, where: str = "path") -> None:
    if not raw:
        raise ContractError(f"{where}: empty path")
    if b"\x00" in raw:
        raise ContractError(f"{where}: NUL is forbidden")
    if raw.startswith(b"/"):
        raise ContractError(f"{where}: absolute path is forbidden")
    if raw.endswith(b"/"):
        raise ContractError(f"{where}: trailing slash is forbidden")
    components = raw.split(b"/")
    if any(component in (b"", b".", b"..") for component in components):
        raise ContractError(f"{where}: forbidden path component")


@dataclass(frozen=True)
class PathValue:
    """A reversible, repository-relative Git path value."""

    path_b64: str
    path_utf8: str | None = None

    @classmethod
    def from_object(cls, value: Any, where: str = "path") -> "PathValue":
        obj = _expect_object(value, {"path_b64"}, {"path_utf8"}, where)
        raw = _decode_base64(obj["path_b64"], f"{where}.path_b64")
        _validate_path_bytes(raw, where)
        try:
            decoded = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            decoded = None
        display = obj.get("path_utf8")
        if "path_utf8" in obj:
            _check_scalar_text(display, f"{where}.path_utf8")
            if decoded is None or display != decoded:
                raise ContractError(f"{where}: path_utf8 is not the exact byte decoding")
        return cls(path_b64=obj["path_b64"], path_utf8=display)

    @classmethod
    def from_bytes(cls, raw: bytes, include_utf8: bool = True) -> "PathValue":
        _validate_path_bytes(raw)
        display: str | None = None
        if include_utf8:
            try:
                display = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                display = None
        return cls(base64.b64encode(raw).decode("ascii"), display)

    @property
    def raw(self) -> bytes:
        return _decode_base64(self.path_b64, "path_b64")

    def to_object(self) -> dict[str, str]:
        result = {"path_b64": self.path_b64}
        if self.path_utf8 is not None:
            result["path_utf8"] = self.path_utf8
        return result


def parse_utc_timestamp(value: Any, where: str = "timestamp") -> datetime:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ContractError(f"{where}: expected RFC3339 UTC whole seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ContractError(f"{where}: invalid calendar timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _expect_object(
    value: Any,
    required: set[str],
    optional: set[str] | None = None,
    where: str = "object",
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{where}: expected object")
    optional = optional or set()
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise ContractError(f"{where}: missing fields {sorted(missing)}")
    if unknown:
        raise ContractError(f"{where}: unknown fields {sorted(unknown)}")
    return value


def _expect_literal(value: Any, expected: Any, where: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ContractError(f"{where}: expected literal {expected!r}")


def _expect_int(
    value: Any,
    where: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(f"{where}: expected integer")
    if value < INT64_MIN or value > INT64_MAX:
        raise ContractError(f"{where}: integer outside signed 64-bit range")
    if minimum is not None and value < minimum:
        raise ContractError(f"{where}: must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{where}: must be at most {maximum}")
    return value


def _expect_enum(value: Any, values: Iterable[str], where: str) -> str:
    choices = tuple(values)
    if not isinstance(value, str) or value not in choices:
        raise ContractError(f"{where}: unknown enum {value!r}")
    return value


def _expect_token(value: Any, where: str) -> str:
    if not isinstance(value, str) or not DOT_TOKEN_RE.fullmatch(value):
        raise ContractError(f"{where}: expected lowercase dot token")
    return value


def _canonical_text_key(value: str) -> bytes:
    return value.encode("utf-8")


def _validate_string_set(
    value: Any,
    where: str,
    *,
    allowed: Iterable[str] | None = None,
    nonempty: bool = False,
    validator: Callable[[Any, str], Any] | None = None,
) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{where}: expected set array")
    if nonempty and not value:
        raise ContractError(f"{where}: set must be nonempty")
    if not all(isinstance(item, str) for item in value):
        raise ContractError(f"{where}: set members must be strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{where}: duplicate set member")
    if value != sorted(value, key=_canonical_text_key):
        raise ContractError(f"{where}: set is not canonical-byte sorted")
    allowed_set = set(allowed) if allowed is not None else None
    for index, item in enumerate(value):
        if allowed_set is not None and item not in allowed_set:
            raise ContractError(f"{where}[{index}]: unknown enum {item!r}")
        if validator is not None:
            validator(item, f"{where}[{index}]")
    return value


def _validate_object_set_by_key(
    value: Any,
    where: str,
    key: Callable[[dict[str, Any]], Any],
    validator: Callable[[Any, str], Any],
    *,
    nonempty: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(f"{where}: expected set array")
    if nonempty and not value:
        raise ContractError(f"{where}: set must be nonempty")
    checked: list[dict[str, Any]] = []
    keys: list[Any] = []
    for index, item in enumerate(value):
        validator(item, f"{where}[{index}]")
        checked.append(item)
        keys.append(key(item))
    if len(set(keys)) != len(keys):
        raise ContractError(f"{where}: duplicate set key")
    if keys != sorted(keys):
        raise ContractError(f"{where}: set is not contract-sorted")
    return checked


def command_digest(
    argv: Sequence[str], cwd_b64: str, environment_allowlist: Sequence[str]
) -> Sha256Id:
    if not isinstance(argv, (list, tuple)) or not argv or not all(
        isinstance(item, str) for item in argv
    ):
        raise ContractError("command argv must be a nonempty ordered string array")
    cwd = _decode_base64(cwd_b64, "cwd_b64")
    _validate_path_bytes(cwd, "cwd_b64")
    env = list(environment_allowlist)
    _validate_string_set(env, "environment_allowlist", validator=_validate_environment_name)
    return sha256_id(
        canonical_json(
            {
                "argv": list(argv),
                "cwd_b64": cwd_b64,
                "environment_allowlist": env,
            }
        )
    )


def _validate_environment_name(value: Any, where: str) -> None:
    if not isinstance(value, str) or not ENV_NAME_RE.fullmatch(value):
        raise ContractError(f"{where}: invalid environment name")
    secret_parts = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "PRIVATE_KEY")
    if any(part in value for part in secret_parts) or value.endswith("_KEY"):
        raise ContractError(f"{where}: secret-like environment name")


def candidate_tree_digest(entries: Any) -> Sha256Id:
    if not isinstance(entries, list):
        raise ContractError("candidate entries must be an ordered array")
    decoded_paths: list[bytes] = []
    for index, entry in enumerate(entries):
        obj = _expect_object(
            entry,
            {"path_b64", "mode", "blob_sha256"},
            where=f"candidate_entries[{index}]",
        )
        raw = _decode_base64(obj["path_b64"], f"candidate_entries[{index}].path_b64")
        _validate_path_bytes(raw, f"candidate_entries[{index}].path_b64")
        if not isinstance(obj["mode"], str) or not MODE_RE.fullmatch(obj["mode"]):
            raise ContractError(f"candidate_entries[{index}].mode: expected six digits")
        Sha256Id(obj["blob_sha256"])
        decoded_paths.append(raw)
    if len(set(decoded_paths)) != len(decoded_paths):
        raise ContractError("candidate entries contain duplicate paths")
    if decoded_paths != sorted(decoded_paths):
        raise ContractError("candidate entries are not decoded-path sorted")
    return sha256_id(canonical_json(entries))


def schema_digest(data: bytes | str | Mapping[str, Any]) -> Sha256Id:
    value = parse_json_document(data) if isinstance(data, (bytes, str)) else data
    if not isinstance(value, Mapping):
        raise ContractError("schema must be a JSON object")
    return sha256_id(canonical_json(dict(value)))


def _validate_matcher(value: Any, where: str) -> bytes:
    obj = _expect_object(value, {"kind", "value_b64"}, where=where)
    kind = _expect_enum(obj["kind"], ("exact", "prefix", "suffix"), f"{where}.kind")
    raw = _decode_base64(obj["value_b64"], f"{where}.value_b64")
    if kind == "exact":
        _validate_path_bytes(raw, where)
    elif kind == "prefix":
        if not raw.endswith(b"/") or len(raw) == 1:
            raise ContractError(f"{where}: prefix must be nonempty and end in slash")
        _validate_path_bytes(raw[:-1], where)
    else:
        if not raw.startswith(b".") or b"/" in raw:
            raise ContractError(f"{where}: suffix must begin with dot and contain no slash")
    return raw


def matcher_matches(matcher: Mapping[str, Any], raw_path: bytes) -> bool:
    raw = _validate_matcher(dict(matcher), "matcher")
    _validate_path_bytes(raw_path)
    if matcher["kind"] == "exact":
        return raw_path == raw
    if matcher["kind"] == "prefix":
        return raw_path.startswith(raw)
    return raw_path.endswith(raw)


def validate_json_pointer(value: Any, where: str = "pointer") -> str:
    if not isinstance(value, str):
        raise ContractError(f"{where}: expected string")
    _check_scalar_text(value, where)
    if value == "":
        return value
    if not value.startswith("/"):
        raise ContractError(f"{where}: invalid RFC 6901 pointer")
    for token in value.split("/")[1:]:
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in "01":
                    raise ContractError(f"{where}: invalid RFC 6901 escape")
                index += 2
            else:
                index += 1
    return value


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def pointer_rule_matches(rule_pointer: str, match: str, changed_pointer: str) -> bool:
    validate_json_pointer(rule_pointer, "rule pointer")
    validate_json_pointer(changed_pointer, "changed pointer")
    _expect_enum(match, ("descendant_prefix", "exact"), "pointer match")
    if match == "exact":
        return changed_pointer == rule_pointer
    if rule_pointer == "":
        return True
    return changed_pointer == rule_pointer or changed_pointer.startswith(rule_pointer + "/")


def _blob_parse(data: bytes, limits: Mapping[str, int], where: str) -> Any:
    if len(data) > limits["max_blob_bytes"]:
        raise ContractError(f"{where}: max_blob_bytes exceeded")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ContractError(f"{where}: BOM is forbidden")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{where}: invalid UTF-8") from exc

    def number(token: str) -> Decimal:
        if len(token.encode("utf-8")) > limits["max_number_chars"]:
            raise ContractError(f"{where}: max_number_chars exceeded")
        try:
            result = Decimal(token)
        except InvalidOperation as exc:
            raise ContractError(f"{where}: invalid number") from exc
        if not result.is_finite():
            raise ContractError(f"{where}: non-finite number")
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_int=number,
            parse_float=number,
            parse_constant=_reject_non_integer,
            strict=True,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError(f"{where}: invalid JSON") from exc
    _check_tree_scalars(value)
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > limits["max_nodes"]:
            raise ContractError(f"{where}: max_nodes exceeded")
        if depth > limits["max_depth"]:
            raise ContractError(f"{where}: max_depth exceeded")
        if isinstance(item, dict):
            for child in item.values():
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)

    walk(value, 0)
    return value


def _json_blob_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return isinstance(left, Decimal) and isinstance(right, Decimal) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_blob_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_blob_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def classify_json_pointer_changes(
    old_blob: bytes | None,
    new_blob: bytes | None,
    limits: Mapping[str, int] | None = None,
) -> list[str]:
    """Return strict additive JSON-pointer changes with ancestor closure."""

    active_limits = dict(LIMITS if limits is None else limits)
    if active_limits != LIMITS:
        raise ContractError("semantic parser limits differ from frozen v1 literals")
    old = _blob_parse(old_blob, active_limits, "old blob") if old_blob is not None else None
    new = _blob_parse(new_blob, active_limits, "new blob") if new_blob is not None else None
    emitted: set[str] = set()

    def add(pointer: str) -> None:
        validate_json_pointer(pointer)
        if pointer == "":
            emitted.add("")
            return
        parts = pointer.split("/")[1:]
        emitted.add("")
        for index in range(1, len(parts) + 1):
            emitted.add("/" + "/".join(parts[:index]))

    def compare(left: Any, right: Any, pointer: str, left_missing: bool = False, right_missing: bool = False) -> None:
        if left_missing or right_missing:
            add(pointer)
            return
        if isinstance(left, list) or isinstance(right, list):
            if not _json_blob_equal(left, right):
                add(pointer)
            return
        if isinstance(left, dict) and isinstance(right, dict):
            keys = sorted(set(left) | set(right), key=lambda item: item.encode("utf-8"))
            for key in keys:
                child = pointer + "/" + _pointer_token(key)
                compare(
                    left.get(key),
                    right.get(key),
                    child,
                    key not in left,
                    key not in right,
                )
            return
        if not _json_blob_equal(left, right):
            add(pointer)

    if old_blob is None:
        add("")
    elif new_blob is None:
        add("")
    else:
        compare(old, new, "")
    result = sorted(emitted, key=lambda item: item.encode("utf-8"))
    if len(result) > active_limits["max_changed_pointers"]:
        raise ContractError("max_changed_pointers exceeded")
    return result


def _validate_source(value: Any, where: str = "source") -> dict[str, Any]:
    fields = {
        "repository_id",
        "source_kind",
        "candidate_tree_sha256",
        "manifest_id",
        "selector_version",
        "base_commit_sha",
        "head_commit_sha",
        "merge_base_sha",
        "index_tree_sha",
        "commit_sha",
    }
    obj = _expect_object(value, fields, where=where)
    _expect_literal(obj["repository_id"], REPOSITORY_ID, f"{where}.repository_id")
    kind = _expect_enum(
        obj["source_kind"], ("commit", "pull_request", "staged_index"), f"{where}.source_kind"
    )
    Sha256Id(obj["candidate_tree_sha256"])
    Sha256Id(obj["manifest_id"])
    _expect_literal(obj["selector_version"], "1", f"{where}.selector_version")
    sha_fields = (
        "base_commit_sha",
        "head_commit_sha",
        "merge_base_sha",
        "index_tree_sha",
        "commit_sha",
    )
    for field in sha_fields:
        if obj[field] is not None:
            CommitSha(obj[field])
    if kind == "staged_index":
        if obj["index_tree_sha"] is None:
            raise ContractError(f"{where}: staged_index requires index_tree_sha")
        if any(obj[field] is not None for field in ("head_commit_sha", "merge_base_sha", "commit_sha")):
            raise ContractError(f"{where}: invalid staged_index nullability")
    elif kind == "pull_request":
        if any(obj[field] is None for field in ("base_commit_sha", "head_commit_sha", "merge_base_sha")):
            raise ContractError(f"{where}: pull_request requires base/head/merge-base")
        if obj["index_tree_sha"] is not None or obj["commit_sha"] is not None:
            raise ContractError(f"{where}: invalid pull_request nullability")
    else:
        if obj["commit_sha"] is None:
            raise ContractError(f"{where}: commit source requires commit_sha")
        if any(
            obj[field] is not None
            for field in ("base_commit_sha", "head_commit_sha", "merge_base_sha", "index_tree_sha")
        ):
            raise ContractError(f"{where}: invalid commit nullability")
    return obj


def _validate_change(value: Any, where: str) -> tuple[bytes, bytes, str]:
    fields = {
        "status",
        "old_path",
        "new_path",
        "old_mode",
        "new_mode",
        "old_blob_sha256",
        "new_blob_sha256",
    }
    obj = _expect_object(value, fields, where=where)
    status = _expect_enum(
        obj["status"], ("add", "delete", "modify", "type_change"), f"{where}.status"
    )
    old_path = PathValue.from_object(obj["old_path"], f"{where}.old_path") if obj["old_path"] is not None else None
    new_path = PathValue.from_object(obj["new_path"], f"{where}.new_path") if obj["new_path"] is not None else None
    for field in ("old_mode", "new_mode"):
        if obj[field] is not None and (
            not isinstance(obj[field], str) or not MODE_RE.fullmatch(obj[field])
        ):
            raise ContractError(f"{where}.{field}: expected six-digit mode")
    for field in ("old_blob_sha256", "new_blob_sha256"):
        if obj[field] is not None:
            Sha256Id(obj[field])
    old_fields = (old_path, obj["old_mode"], obj["old_blob_sha256"])
    new_fields = (new_path, obj["new_mode"], obj["new_blob_sha256"])
    if status == "add" and (any(item is not None for item in old_fields) or any(item is None for item in new_fields)):
        raise ContractError(f"{where}: invalid add shape")
    if status == "delete" and (any(item is None for item in old_fields) or any(item is not None for item in new_fields)):
        raise ContractError(f"{where}: invalid delete shape")
    if status in ("modify", "type_change") and (
        any(item is None for item in old_fields) or any(item is None for item in new_fields)
    ):
        raise ContractError(f"{where}: invalid {status} shape")
    if status in ("modify", "type_change") and old_path.raw != new_path.raw:
        raise ContractError(f"{where}: movement must be represented as delete plus add")
    return (
        new_path.raw if new_path is not None else b"",
        old_path.raw if old_path is not None else b"",
        status,
    )


def _validate_applicability(value: Any, where: str) -> None:
    obj = _expect_object(
        value,
        {"lanes", "platforms", "source_kinds", "required_capabilities"},
        where=where,
    )
    _validate_string_set(obj["lanes"], f"{where}.lanes", allowed=("local", "runnerless_pr"))
    _validate_string_set(obj["platforms"], f"{where}.platforms", allowed=("darwin", "linux"))
    _validate_string_set(
        obj["source_kinds"],
        f"{where}.source_kinds",
        allowed=("commit", "pull_request", "staged_index"),
    )
    _validate_string_set(
        obj["required_capabilities"],
        f"{where}.required_capabilities",
        validator=_expect_token,
    )


def _validate_cost_class(value: Any, where: str) -> None:
    obj = _expect_object(
        value, {"id", "timeout_seconds", "memory_mib", "pids", "output_bytes"}, where=where
    )
    _expect_token(obj["id"], f"{where}.id")
    for field in ("timeout_seconds", "memory_mib", "pids", "output_bytes"):
        _expect_int(obj[field], f"{where}.{field}", minimum=1)


def _validate_input_rule(value: Any, where: str) -> None:
    obj = _expect_object(
        value, {"id", "matcher", "owner_obligation_ids", "classification_tags"}, where=where
    )
    _expect_token(obj["id"], f"{where}.id")
    _validate_matcher(obj["matcher"], f"{where}.matcher")
    _validate_string_set(
        obj["owner_obligation_ids"],
        f"{where}.owner_obligation_ids",
        nonempty=True,
        validator=_expect_token,
    )
    _validate_string_set(
        obj["classification_tags"], f"{where}.classification_tags", validator=_expect_token
    )


def _validate_inert_rule(value: Any, where: str) -> None:
    obj = _expect_object(value, {"id", "matcher", "reason_code"}, where=where)
    _expect_token(obj["id"], f"{where}.id")
    _validate_matcher(obj["matcher"], f"{where}.matcher")
    _expect_literal(obj["reason_code"], "inert", f"{where}.reason_code")


def _validate_semantic_selector(value: Any, where: str) -> None:
    obj = _expect_object(
        value, {"id", "baseline_input_rule_ids", "parser", "limits", "pointer_rules"}, where=where
    )
    _expect_token(obj["id"], f"{where}.id")
    _validate_string_set(
        obj["baseline_input_rule_ids"],
        f"{where}.baseline_input_rule_ids",
        nonempty=True,
        validator=_expect_token,
    )
    _expect_literal(obj["parser"], "json_pointer_changes_v1", f"{where}.parser")
    limits = _expect_object(
        obj["limits"],
        {
            "max_blob_bytes",
            "max_depth",
            "max_nodes",
            "max_changed_pointers",
            "max_number_chars",
        },
        where=f"{where}.limits",
    )
    if limits != LIMITS:
        raise ContractError(f"{where}.limits: values differ from frozen v1 literals")

    def pointer_key(rule: dict[str, Any]) -> tuple[bytes, str, bytes]:
        return (
            rule["pointer"].encode("utf-8"),
            rule["match"],
            canonical_json(rule["add_obligation_ids"]),
        )

    def validate_rule(rule: Any, rule_where: str) -> None:
        item = _expect_object(
            rule, {"pointer", "match", "add_obligation_ids"}, where=rule_where
        )
        validate_json_pointer(item["pointer"], f"{rule_where}.pointer")
        _expect_enum(
            item["match"], ("descendant_prefix", "exact"), f"{rule_where}.match"
        )
        _validate_string_set(
            item["add_obligation_ids"],
            f"{rule_where}.add_obligation_ids",
            nonempty=True,
            validator=_expect_token,
        )

    _validate_object_set_by_key(
        obj["pointer_rules"],
        f"{where}.pointer_rules",
        pointer_key,
        validate_rule,
    )


def _validate_obligation(value: Any, where: str) -> None:
    fields = {
        "id",
        "description",
        "argv",
        "cwd_b64",
        "depends_on",
        "universal_in",
        "eligible_in",
        "deep_only",
        "applicability",
        "cost_class",
        "execution_scope",
        "hermeticity",
        "exclusive_group",
        "network",
        "environment_allowlist",
        "success_exit_codes",
        "stdout_sentinel",
    }
    obj = _expect_object(value, fields, where=where)
    _expect_token(obj["id"], f"{where}.id")
    _check_scalar_text(obj["description"], f"{where}.description")
    if not isinstance(obj["argv"], list) or not obj["argv"] or not all(
        isinstance(item, str) for item in obj["argv"]
    ):
        raise ContractError(f"{where}.argv: expected nonempty ordered string array")
    for index, item in enumerate(obj["argv"]):
        _check_scalar_text(item, f"{where}.argv[{index}]")
    cwd = _decode_base64(obj["cwd_b64"], f"{where}.cwd_b64")
    _validate_path_bytes(cwd, f"{where}.cwd_b64")
    _validate_string_set(
        obj["depends_on"], f"{where}.depends_on", validator=_expect_token
    )
    _validate_string_set(
        obj["universal_in"], f"{where}.universal_in", allowed=MANIFEST_MODES
    )
    _validate_string_set(
        obj["eligible_in"], f"{where}.eligible_in", allowed=MANIFEST_MODES
    )
    if not isinstance(obj["deep_only"], bool):
        raise ContractError(f"{where}.deep_only: expected boolean")
    _validate_applicability(obj["applicability"], f"{where}.applicability")
    _expect_token(obj["cost_class"], f"{where}.cost_class")
    _expect_enum(
        obj["execution_scope"],
        ("commit_snapshot", "host_read", "index_snapshot"),
        f"{where}.execution_scope",
    )
    _expect_enum(
        obj["hermeticity"],
        ("host_runtime", "pure", "temp_files", "temp_git"),
        f"{where}.hermeticity",
    )
    if obj["exclusive_group"] is not None:
        _expect_token(obj["exclusive_group"], f"{where}.exclusive_group")
    _expect_enum(obj["network"], ("forbidden", "not_required"), f"{where}.network")
    _validate_string_set(
        obj["environment_allowlist"],
        f"{where}.environment_allowlist",
        validator=_validate_environment_name,
    )
    exits = obj["success_exit_codes"]
    if not isinstance(exits, list) or not exits:
        raise ContractError(f"{where}.success_exit_codes: expected nonempty set")
    for index, exit_code in enumerate(exits):
        _expect_int(exit_code, f"{where}.success_exit_codes[{index}]")
    if len(set(exits)) != len(exits) or exits != sorted(exits, key=canonical_json):
        raise ContractError(f"{where}.success_exit_codes: duplicate or unsorted")
    if obj["stdout_sentinel"] is not None:
        _check_scalar_text(obj["stdout_sentinel"], f"{where}.stdout_sentinel")


def _validate_activation(value: Any, where: str) -> None:
    obj = _expect_object(value, {"generation", "full_profile", "lanes"}, where=where)
    _expect_int(obj["generation"], f"{where}.generation", minimum=1)
    _expect_enum(
        obj["full_profile"], ("decomposed", "preserved_aggregate"), f"{where}.full_profile"
    )
    lanes = obj["lanes"]
    if not isinstance(lanes, list) or len(lanes) != 2:
        raise ContractError(f"{where}.lanes: expected ordered two-item array")
    expected_lanes = ("local", "runnerless_pr")
    for index, expected_lane in enumerate(expected_lanes):
        lane = _expect_object(
            lanes[index], {"lane", "policy", "graduated_tags"}, where=f"{where}.lanes[{index}]"
        )
        _expect_literal(lane["lane"], expected_lane, f"{where}.lanes[{index}].lane")
        policy = _expect_enum(
            lane["policy"], ("enforce", "shadow"), f"{where}.lanes[{index}].policy"
        )
        _validate_string_set(
            lane["graduated_tags"],
            f"{where}.lanes[{index}].graduated_tags",
            validator=_expect_token,
        )
        if policy == "shadow" and lane["graduated_tags"]:
            raise ContractError(f"{where}.lanes[{index}]: shadow tags must be empty")


def validate_manifest(value: Any) -> dict[str, Any]:
    fields = {
        "schema",
        "schema_version",
        "manifest_id",
        "manifest_version",
        "repository_id",
        "selector_api_version",
        "receipt_contract",
        "ledger_contract",
        "modes",
        "cause_codes",
        "cost_classes",
        "exclusive_groups",
        "input_rules",
        "inert_rules",
        "semantic_selectors",
        "control_rule_ids",
        "obligations",
        "activation",
    }
    obj = _expect_object(value, fields, where="manifest")
    _expect_literal(obj["schema"], MANIFEST_SCHEMA, "manifest.schema")
    _expect_literal(obj["schema_version"], 1, "manifest.schema_version")
    Sha256Id(obj["manifest_id"])
    _expect_int(obj["manifest_version"], "manifest.manifest_version", minimum=1)
    _expect_literal(obj["repository_id"], REPOSITORY_ID, "manifest.repository_id")
    _expect_literal(obj["selector_api_version"], "1", "manifest.selector_api_version")
    receipt_contract = _expect_object(
        obj["receipt_contract"], {"schema", "schema_version"}, where="manifest.receipt_contract"
    )
    _expect_literal(receipt_contract["schema"], RECEIPT_SCHEMA, "manifest.receipt_contract.schema")
    _expect_literal(receipt_contract["schema_version"], 1, "manifest.receipt_contract.schema_version")
    ledger_contract = _expect_object(
        obj["ledger_contract"], {"schema", "schema_version"}, where="manifest.ledger_contract"
    )
    _expect_literal(ledger_contract["schema"], LEDGER_SCHEMA, "manifest.ledger_contract.schema")
    _expect_literal(ledger_contract["schema_version"], 1, "manifest.ledger_contract.schema_version")
    _validate_string_set(obj["modes"], "manifest.modes", allowed=MANIFEST_MODES)
    if tuple(obj["modes"]) != MANIFEST_MODES:
        raise ContractError("manifest.modes: expected the exact frozen mode set")
    _validate_string_set(obj["cause_codes"], "manifest.cause_codes", allowed=CAUSE_CODES)
    if tuple(obj["cause_codes"]) != CAUSE_CODES:
        raise ContractError("manifest.cause_codes: expected the exact frozen cause set")
    _validate_object_set_by_key(
        obj["cost_classes"], "manifest.cost_classes", lambda item: item["id"], _validate_cost_class
    )
    _validate_string_set(
        obj["exclusive_groups"], "manifest.exclusive_groups", validator=_expect_token
    )
    _validate_object_set_by_key(
        obj["input_rules"], "manifest.input_rules", lambda item: item["id"], _validate_input_rule
    )
    _validate_object_set_by_key(
        obj["inert_rules"], "manifest.inert_rules", lambda item: item["id"], _validate_inert_rule
    )
    _validate_object_set_by_key(
        obj["semantic_selectors"],
        "manifest.semantic_selectors",
        lambda item: item["id"],
        _validate_semantic_selector,
    )
    _validate_string_set(
        obj["control_rule_ids"], "manifest.control_rule_ids", validator=_expect_token
    )
    _validate_object_set_by_key(
        obj["obligations"], "manifest.obligations", lambda item: item["id"], _validate_obligation
    )
    _validate_activation(obj["activation"], "manifest.activation")

    input_ids = {item["id"] for item in obj["input_rules"]}
    obligation_ids = {item["id"] for item in obj["obligations"]}
    cost_ids = {item["id"] for item in obj["cost_classes"]}
    exclusive_ids = set(obj["exclusive_groups"])
    for rule in obj["input_rules"]:
        if not set(rule["owner_obligation_ids"]) <= obligation_ids:
            raise ContractError(f"manifest input rule {rule['id']}: unknown obligation")
    if not set(obj["control_rule_ids"]) <= input_ids:
        raise ContractError("manifest.control_rule_ids: unknown input rule")
    for selector in obj["semantic_selectors"]:
        if not set(selector["baseline_input_rule_ids"]) <= input_ids:
            raise ContractError(
                f"semantic selector {selector['id']}: unknown baseline_input_rule_ids"
            )
        for rule in selector["pointer_rules"]:
            if not set(rule["add_obligation_ids"]) <= obligation_ids:
                raise ContractError(f"semantic selector {selector['id']}: unknown obligation")
    graph: dict[str, set[str]] = {}
    eligible: dict[str, set[str]] = {}
    for obligation in obj["obligations"]:
        oid = obligation["id"]
        deps = set(obligation["depends_on"])
        if not deps <= obligation_ids or oid in deps:
            raise ContractError(f"obligation {oid}: invalid dependency reference")
        if obligation["cost_class"] not in cost_ids:
            raise ContractError(f"obligation {oid}: unknown cost class")
        group = obligation["exclusive_group"]
        if group is not None and group not in exclusive_ids:
            raise ContractError(f"obligation {oid}: unknown exclusive group")
        if not set(obligation["universal_in"]) <= set(obligation["eligible_in"]):
            raise ContractError(f"obligation {oid}: universal mode is ineligible")
        graph[oid] = deps
        eligible[oid] = set(obligation["eligible_in"])
    for oid, deps in graph.items():
        for dep in deps:
            if not eligible[oid] <= eligible[dep]:
                raise ContractError(f"obligation {oid}: dependency {dep} is ineligible")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractError("manifest obligation dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    if derive_identity(obj, "manifest_id") != obj["manifest_id"]:
        raise ContractError("manifest.manifest_id: identity mismatch")
    return obj


def _validate_execution_values(
    disposition: Any,
    outcome: Any,
    exit_code: Any,
    duration_ms: Any,
    where: str,
    *,
    shadow_tuple: bool = False,
) -> None:
    disposition = _expect_enum(disposition, DISPOSITIONS, f"{where}.execution_disposition")
    if shadow_tuple:
        if (
            disposition != "not_applicable"
            or outcome != "not_observed"
            or exit_code is not None
            or duration_ms is not None
        ):
            raise ContractError(f"{where}: invalid shadow tuple")
        return
    if disposition != "run":
        if outcome is not None or exit_code is not None or duration_ms is not None:
            raise ContractError(f"{where}: non-run execution must be unobserved nulls")
        return
    _expect_enum(outcome, ("cleanup_failed", "failed", "passed", "timed_out"), f"{where}.outcome")
    _expect_int(duration_ms, f"{where}.duration_ms", minimum=0)
    if outcome in ("passed", "failed"):
        _expect_int(exit_code, f"{where}.exit_code")
    elif exit_code is not None:
        _expect_int(exit_code, f"{where}.exit_code")


def _expected_focused_disposition(causes: Sequence[str]) -> str:
    if "not_applicable" in causes:
        return "not_applicable"
    run_causes = {
        "deep_mode",
        "dependency",
        "direct",
        "fallback",
        "full_mode",
        "reverse_impact",
        "self_protection",
        "universal",
    }
    return "run" if set(causes) & run_causes else "skip"


def _validate_receipt_row(value: Any, where: str, shadow: bool) -> None:
    fields = {
        "obligation_id",
        "focused_disposition",
        "execution_disposition",
        "selection_causes",
        "outcome",
        "command_digest",
        "exit_code",
        "duration_ms",
        "diagnostic_code",
    }
    obj = _expect_object(value, fields, where=where)
    _expect_token(obj["obligation_id"], f"{where}.obligation_id")
    focused = _expect_enum(obj["focused_disposition"], DISPOSITIONS, f"{where}.focused_disposition")
    causes = _validate_string_set(
        obj["selection_causes"], f"{where}.selection_causes", allowed=CAUSE_CODES
    )
    if focused != "blocked" and focused != _expected_focused_disposition(causes):
        raise ContractError(f"{where}: focused disposition violates cause precedence")
    Sha256Id(obj["command_digest"])
    _expect_token(obj["diagnostic_code"], f"{where}.diagnostic_code")
    if shadow:
        _validate_execution_values(
            obj["execution_disposition"],
            obj["outcome"],
            obj["exit_code"],
            obj["duration_ms"],
            where,
            shadow_tuple=True,
        )
        _expect_literal(obj["diagnostic_code"], "shadow.unobserved", f"{where}.diagnostic_code")
    else:
        _validate_execution_values(
            obj["execution_disposition"],
            obj["outcome"],
            obj["exit_code"],
            obj["duration_ms"],
            where,
        )


def _validate_aggregate(value: Any, where: str) -> None:
    fields = {
        "executor_id",
        "execution_disposition",
        "selection_causes",
        "outcome",
        "command_digest",
        "exit_code",
        "duration_ms",
        "diagnostic_code",
    }
    obj = _expect_object(value, fields, where=where)
    _expect_token(obj["executor_id"], f"{where}.executor_id")
    _validate_string_set(obj["selection_causes"], f"{where}.selection_causes", allowed=CAUSE_CODES)
    Sha256Id(obj["command_digest"])
    _expect_token(obj["diagnostic_code"], f"{where}.diagnostic_code")
    _validate_execution_values(
        obj["execution_disposition"],
        obj["outcome"],
        obj["exit_code"],
        obj["duration_ms"],
        where,
    )


def validate_receipt(
    value: Any,
    *,
    manifests: Mapping[str, Mapping[str, Any]] | None = None,
    receipt_store: Mapping[str, Mapping[str, Any]] | None = None,
    validate_link: bool = True,
) -> dict[str, Any]:
    fields = {
        "schema",
        "schema_version",
        "receipt_id",
        "created_at",
        "repository_id",
        "selector_version",
        "manifest_id",
        "lane",
        "mode",
        "requested_mode",
        "effective_mode",
        "activation_generation",
        "source",
        "changes",
        "rows",
        "authoritative_receipt_id",
        "aggregate_execution",
        "timing",
        "cleanup",
    }
    obj = _expect_object(value, fields, where="receipt")
    _expect_literal(obj["schema"], RECEIPT_SCHEMA, "receipt.schema")
    _expect_literal(obj["schema_version"], 1, "receipt.schema_version")
    Sha256Id(obj["receipt_id"])
    parse_utc_timestamp(obj["created_at"], "receipt.created_at")
    _expect_literal(obj["repository_id"], REPOSITORY_ID, "receipt.repository_id")
    _expect_literal(obj["selector_version"], "1", "receipt.selector_version")
    Sha256Id(obj["manifest_id"])
    _expect_enum(
        obj["lane"],
        ("focused_local", "local_full", "periodic", "pre_commit", "release", "runnerless_pr"),
        "receipt.lane",
    )
    mode = _expect_enum(
        obj["mode"], ("deep_periodic", "enforce", "full", "full_release", "shadow"), "receipt.mode"
    )
    requested = _expect_enum(obj["requested_mode"], MANIFEST_MODES, "receipt.requested_mode")
    effective = _expect_enum(obj["effective_mode"], MANIFEST_MODES, "receipt.effective_mode")
    _expect_int(obj["activation_generation"], "receipt.activation_generation", minimum=1)
    source = _validate_source(obj["source"], "receipt.source")
    if source["manifest_id"] != obj["manifest_id"]:
        raise ContractError("receipt.source.manifest_id does not match receipt")
    allowed_sources = {
        "pre_commit": {"staged_index"},
        "focused_local": {"staged_index"},
        "runnerless_pr": {"pull_request"},
        "local_full": {"commit", "staged_index"},
        "release": {"commit"},
        "periodic": {"commit"},
    }
    if source["source_kind"] not in allowed_sources[obj["lane"]]:
        raise ContractError("receipt: lane/source variant mismatch")

    changes = obj["changes"]
    if not isinstance(changes, list):
        raise ContractError("receipt.changes: expected ordered array")
    change_keys = [_validate_change(item, f"receipt.changes[{index}]") for index, item in enumerate(changes)]
    if len(set(change_keys)) != len(change_keys) or change_keys != sorted(change_keys):
        raise ContractError("receipt.changes: duplicate or contract-unsorted")

    rows = obj["rows"]
    if not isinstance(rows, list):
        raise ContractError("receipt.rows: expected ordered array")
    for index, row in enumerate(rows):
        _validate_receipt_row(row, f"receipt.rows[{index}]", mode == "shadow")
    row_ids = [row["obligation_id"] for row in rows]
    if len(set(row_ids)) != len(row_ids) or row_ids != sorted(row_ids):
        raise ContractError("receipt.rows: duplicate or obligation_id-unsorted")
    _validate_aggregate(obj["aggregate_execution"], "receipt.aggregate_execution")
    aggregate = obj["aggregate_execution"]

    if mode == "shadow":
        if requested not in ("pre_commit", "focused_local", "focused_pr") or effective != "full":
            raise ContractError("receipt: invalid shadow requested/effective mode")
        lane_requested = {
            "pre_commit": "pre_commit",
            "focused_local": "focused_local",
            "runnerless_pr": "focused_pr",
        }
        if obj["lane"] not in lane_requested or lane_requested[obj["lane"]] != requested:
            raise ContractError("receipt: shadow lane does not match requested mode")
        if obj["authoritative_receipt_id"] is None:
            raise ContractError("receipt: shadow requires authoritative_receipt_id")
        Sha256Id(obj["authoritative_receipt_id"])
        if (
            aggregate["execution_disposition"] != "run"
            or aggregate["selection_causes"] != ["full_mode"]
            or aggregate["outcome"] not in ("passed", "failed", "timed_out", "cleanup_failed")
            or aggregate["duration_ms"] is None
            or aggregate["diagnostic_code"] != "full.authoritative"
        ):
            raise ContractError("receipt: invalid shadow authoritative aggregate")
    else:
        if obj["authoritative_receipt_id"] is not None:
            raise ContractError("receipt: non-shadow authoritative_receipt_id must be null")
        if mode == "enforce":
            lane_requested = {
                "pre_commit": "pre_commit",
                "focused_local": "focused_local",
                "runnerless_pr": "focused_pr",
            }
            if (
                obj["lane"] not in lane_requested
                or lane_requested[obj["lane"]] != requested
            ):
                raise ContractError("receipt: enforce lane does not match requested mode")
            if requested == effective:
                if requested not in ("pre_commit", "focused_local", "focused_pr"):
                    raise ContractError("receipt: invalid enforce focus mode")
            else:
                if requested not in ("focused_local", "focused_pr") or effective != "full":
                    raise ContractError("receipt: invalid enforce fallback modes")
                if not any(
                    set(row["selection_causes"]) & {"fallback", "self_protection"} for row in rows
                ):
                    raise ContractError("receipt: enforce fallback lacks fallback cause")
                if (
                    aggregate["execution_disposition"] != "run"
                    or aggregate["selection_causes"] != ["full_mode"]
                    or aggregate["diagnostic_code"] != "full.authoritative"
                ):
                    raise ContractError("receipt: invalid enforce fallback aggregate")
        elif mode == "full":
            if requested != "full" or effective != "full":
                raise ContractError("receipt: full requires requested/effective full")
        elif mode == "full_release":
            if requested != "full_release" or effective != "full_release":
                raise ContractError("receipt: full-release mode mismatch")
            if obj["lane"] != "release":
                raise ContractError("receipt: full-release requires release lane")
        elif mode == "deep_periodic":
            if requested != "deep_periodic" or effective != "deep_periodic":
                raise ContractError("receipt: deep-periodic mode mismatch")
            if obj["lane"] != "periodic":
                raise ContractError("receipt: deep-periodic requires periodic lane")
        if mode in ("full", "full_release") and aggregate["selection_causes"] != ["full_mode"]:
            raise ContractError("receipt: full aggregate cause must be full_mode")
        if mode == "deep_periodic" and aggregate["selection_causes"] != ["deep_mode"]:
            raise ContractError("receipt: deep aggregate cause must be deep_mode")
        if mode in ("full", "full_release", "deep_periodic") and (
            aggregate["execution_disposition"] != "run"
            or aggregate["outcome"] not in ("passed", "failed", "timed_out", "cleanup_failed")
            or aggregate["duration_ms"] is None
        ):
            raise ContractError("receipt: full/deep aggregate must be observed")

    timing = _expect_object(
        obj["timing"],
        {"snapshot_ms", "selection_ms", "execution_ms", "cleanup_ms", "total_ms"},
        where="receipt.timing",
    )
    for field, value_ms in timing.items():
        _expect_int(value_ms, f"receipt.timing.{field}", minimum=0)
    cleanup = _expect_object(
        obj["cleanup"],
        {
            "children_reaped",
            "temp_removed",
            "index_removed",
            "objects_unchanged",
            "bytecode_absent",
            "diagnostic_code",
        },
        where="receipt.cleanup",
    )
    for field in (
        "children_reaped",
        "temp_removed",
        "index_removed",
        "objects_unchanged",
        "bytecode_absent",
    ):
        if not isinstance(cleanup[field], bool):
            raise ContractError(f"receipt.cleanup.{field}: expected boolean")
    _expect_token(cleanup["diagnostic_code"], "receipt.cleanup.diagnostic_code")

    manifest: Mapping[str, Any] | None = None
    if manifests is not None:
        manifest = manifests.get(obj["manifest_id"])
        if manifest is None:
            raise ContractError("receipt: unresolved manifest_id")
        validate_manifest(dict(manifest))
        if manifest["activation"]["generation"] != obj["activation_generation"]:
            raise ContractError("receipt: activation generation mismatch")
        obligations = {item["id"]: item for item in manifest["obligations"]}
        for row in rows:
            obligation = obligations.get(row["obligation_id"])
            if obligation is None:
                raise ContractError("receipt: unknown obligation row")
            expected_digest = command_digest(
                obligation["argv"],
                obligation["cwd_b64"],
                obligation["environment_allowlist"],
            )
            if row["command_digest"] != expected_digest:
                raise ContractError("receipt: obligation command digest mismatch")
        if not rows and mode in ("full", "full_release", "deep_periodic"):
            if (
                manifest["activation"]["full_profile"] != "preserved_aggregate"
                or aggregate["executor_id"] != "preserved.full"
            ):
                raise ContractError("receipt: empty full rows outside preserved_aggregate")

    if mode == "shadow" and validate_link:
        if receipt_store is None:
            raise ContractError("receipt: shadow link store is required")
        linked = receipt_store.get(obj["authoritative_receipt_id"])
        if linked is None:
            raise ContractError("receipt: authoritative full receipt missing")
        validate_receipt(
            dict(linked), manifests=manifests, receipt_store=receipt_store, validate_link=False
        )
        if linked["receipt_id"] != obj["authoritative_receipt_id"] or linked["mode"] != "full":
            raise ContractError("receipt: invalid authoritative full link")
        if canonical_json(linked["source"]) != canonical_json(obj["source"]):
            raise ContractError("receipt: shadow/full source mismatch")
        if canonical_json(linked["aggregate_execution"]) != canonical_json(aggregate):
            raise ContractError("receipt: shadow/full aggregate mismatch")
    if derive_identity(obj, "receipt_id") != obj["receipt_id"]:
        raise ContractError("receipt.receipt_id: identity mismatch")
    return obj


def _schema_link_names() -> dict[str, str]:
    return {"manifest": MANIFEST_SCHEMA, "receipt": RECEIPT_SCHEMA, "ledger": LEDGER_SCHEMA}


def _validate_schema_links(
    value: Any,
    where: str,
    expected_digests: Mapping[str, str] | None,
) -> None:
    obj = _expect_object(value, {"manifest", "receipt", "ledger"}, where=where)
    for key, schema_name in _schema_link_names().items():
        link = _expect_object(
            obj[key], {"schema", "schema_version", "sha256"}, where=f"{where}.{key}"
        )
        _expect_literal(link["schema"], schema_name, f"{where}.{key}.schema")
        _expect_literal(link["schema_version"], 1, f"{where}.{key}.schema_version")
        Sha256Id(link["sha256"])
        if expected_digests is not None and link["sha256"] != expected_digests[key]:
            raise ContractError(f"{where}.{key}: stale schema digest")


def _validate_provenance(value: Any, where: str) -> None:
    obj = _expect_object(value, {"kind", "reference", "reference_sha256"}, where=where)
    kind = _expect_enum(
        obj["kind"],
        ("local_command", "operator_record", "pull_request", "runnerless_check"),
        f"{where}.kind",
    )
    Sha256Id(obj["reference_sha256"])
    reference = obj["reference"]
    if kind in ("operator_record", "local_command"):
        Sha256Id(reference)
        if reference != obj["reference_sha256"]:
            raise ContractError(f"{where}: digest reference must equal reference_sha256")
    elif kind == "runnerless_check":
        if not isinstance(reference, str) or not RUNNERLESS_REFERENCE_RE.fullmatch(reference):
            raise ContractError(f"{where}: invalid runnerless check reference")
    elif not isinstance(reference, str) or not PR_REFERENCE_RE.fullmatch(reference):
        raise ContractError(f"{where}: invalid pull-request reference")


def _validate_event_common(
    event: Any,
    index: int,
    root: Mapping[str, Any],
    schema_digests: Mapping[str, str] | None,
) -> dict[str, Any]:
    fields = {
        "event_id",
        "event_type",
        "event_version",
        "previous_event_id",
        "occurred_at",
        "repository_id",
        "acceptance_commit_sha",
        "manifest_id",
        "source",
        "receipt_ids",
        "schema_links",
        "provenance",
        "payload",
    }
    obj = _expect_object(event, fields, where=f"ledger.events[{index}]")
    Sha256Id(obj["event_id"])
    _expect_enum(obj["event_type"], EVENT_TYPES, f"ledger.events[{index}].event_type")
    _expect_literal(obj["event_version"], 1, f"ledger.events[{index}].event_version")
    if obj["previous_event_id"] is not None:
        Sha256Id(obj["previous_event_id"])
    parse_utc_timestamp(obj["occurred_at"], f"ledger.events[{index}].occurred_at")
    _expect_literal(obj["repository_id"], root["repository_id"], f"ledger.events[{index}].repository_id")
    _expect_literal(
        obj["acceptance_commit_sha"],
        root["acceptance_commit_sha"],
        f"ledger.events[{index}].acceptance_commit_sha",
    )
    if obj["manifest_id"] is not None:
        Sha256Id(obj["manifest_id"])
    if obj["source"] is not None:
        source = _validate_source(obj["source"], f"ledger.events[{index}].source")
        if obj["manifest_id"] is None or source["manifest_id"] != obj["manifest_id"]:
            raise ContractError(f"ledger.events[{index}]: source/manifest mismatch")
    _validate_string_set(
        obj["receipt_ids"], f"ledger.events[{index}].receipt_ids", validator=lambda item, _: Sha256Id(item)
    )
    _validate_schema_links(
        obj["schema_links"], f"ledger.events[{index}].schema_links", schema_digests
    )
    _validate_provenance(obj["provenance"], f"ledger.events[{index}].provenance")
    if derive_identity(obj, "event_id") != obj["event_id"]:
        raise ContractError(f"ledger.events[{index}].event_id: identity mismatch")
    return obj


def _validate_genesis_payload(value: Any, where: str) -> None:
    obj = _expect_object(
        value,
        {"artifact_digests", "d2_d5_decisions", "direct_classifications"},
        where=where,
    )

    def artifact(entry: Any, entry_where: str) -> None:
        item = _expect_object(entry, {"path", "sha256", "byte_length"}, where=entry_where)
        if item["path"] not in AUTHORITY_PATHS:
            raise ContractError(f"{entry_where}.path: unknown authority artifact")
        Sha256Id(item["sha256"])
        _expect_int(item["byte_length"], f"{entry_where}.byte_length", minimum=0)

    artifacts = _validate_object_set_by_key(
        obj["artifact_digests"], f"{where}.artifact_digests", lambda item: item["path"], artifact
    )
    if tuple(item["path"] for item in artifacts) != AUTHORITY_PATHS:
        raise ContractError(f"{where}.artifact_digests: expected exact three authority paths")
    for item in artifacts:
        expected_sha, expected_length = AUTHORITY_ARTIFACTS[item["path"]]
        if item["sha256"] != expected_sha or item["byte_length"] != expected_length:
            raise ContractError(f"{where}.artifact_digests: immutable artifact mismatch")
    decisions = obj["d2_d5_decisions"]
    if not isinstance(decisions, list) or len(decisions) != 4:
        raise ContractError(f"{where}.d2_d5_decisions: expected D2,D3,D4,D5")
    for index, expected in enumerate(("D2", "D3", "D4", "D5")):
        item = _expect_object(
            decisions[index],
            {"id", "disposition", "replacement_sha256"},
            where=f"{where}.d2_d5_decisions[{index}]",
        )
        _expect_literal(item["id"], expected, f"{where}.d2_d5_decisions[{index}].id")
        disposition = _expect_enum(
            item["disposition"], ("accept", "reject", "replace"), f"{where}.d2_d5_decisions[{index}].disposition"
        )
        if disposition == "replace":
            Sha256Id(item["replacement_sha256"])
        elif item["replacement_sha256"] is not None:
            raise ContractError(f"{where}.d2_d5_decisions[{index}]: unexpected replacement")
        if disposition != "accept" or item["replacement_sha256"] is not None:
            raise ContractError(f"{where}.d2_d5_decisions[{index}]: operator record mismatch")

    def classification(entry: Any, entry_where: str) -> None:
        item = _expect_object(entry, {"path", "result", "tool_sha256"}, where=entry_where)
        if item["path"] not in AUTHORITY_PATHS:
            raise ContractError(f"{entry_where}.path: unknown authority artifact")
        _expect_enum(item["result"], ("conformant", "nonconformant"), f"{entry_where}.result")
        Sha256Id(item["tool_sha256"])

    classifications = _validate_object_set_by_key(
        obj["direct_classifications"],
        f"{where}.direct_classifications",
        lambda item: item["path"],
        classification,
    )
    if tuple(item["path"] for item in classifications) != AUTHORITY_PATHS:
        raise ContractError(f"{where}.direct_classifications: expected exact authority paths")
    if any(
        item["result"] != "conformant"
        or item["tool_sha256"] != CLASSIFICATION_TOOL_SHA256
        for item in classifications
    ):
        raise ContractError(f"{where}.direct_classifications: operator record mismatch")


def _validate_acceptance_payload(value: Any, where: str) -> None:
    obj = _expect_object(value, {"bundle_scope", "milestone", "criteria"}, where=where)
    for field in ("bundle_scope", "milestone"):
        if not isinstance(obj[field], str) or not obj[field]:
            raise ContractError(f"{where}.{field}: expected nonempty string")

    def criterion(entry: Any, entry_where: str) -> None:
        item = _expect_object(entry, {"ac_id", "status", "evidence_ids"}, where=entry_where)
        if not isinstance(item["ac_id"], str) or not item["ac_id"]:
            raise ContractError(f"{entry_where}.ac_id: expected nonempty string")
        _expect_enum(
            item["status"], ("blocked", "failed", "passed", "superseded"), f"{entry_where}.status"
        )
        _validate_string_set(
            item["evidence_ids"],
            f"{entry_where}.evidence_ids",
            validator=lambda member, _: Sha256Id(member),
        )

    _validate_object_set_by_key(
        obj["criteria"],
        f"{where}.criteria",
        lambda item: item["ac_id"],
        criterion,
        nonempty=True,
    )


def _period_bounds(schedule: str, period_id: str) -> tuple[datetime, datetime, int]:
    if schedule == "weekly_full":
        match = WEEK_RE.fullmatch(period_id) if isinstance(period_id, str) else None
        if not match:
            raise ContractError("invalid ISO weekly period_id")
        year, week = map(int, match.groups())
        try:
            start = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ContractError("invalid ISO weekly period_id") from exc
        if start.strftime("%G-W%V") != period_id:
            raise ContractError("non-canonical ISO weekly period_id")
        return start, start + timedelta(days=7), 86400
    if schedule == "monthly_deep":
        match = MONTH_RE.fullmatch(period_id) if isinstance(period_id, str) else None
        if not match:
            raise ContractError("invalid monthly period_id")
        year, month = map(int, match.groups())
        if not 1 <= month <= 12:
            raise ContractError("invalid monthly period_id")
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=timezone.utc)
        )
        return start, end, 172800
    raise ContractError("unknown surveillance schedule")


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _period_containing(schedule: str, moment: datetime) -> str:
    if schedule == "weekly_full":
        year, week, _ = moment.isocalendar()
        return f"{year:04d}-W{week:02d}"
    return f"{moment.year:04d}-{moment.month:02d}"


def latest_required_surveillance_period(
    schedule: str,
    schedule_activated_at: str,
    now: str,
) -> str | None:
    """Return the latest fixed period whose non-sliding deadline has elapsed."""

    activated = parse_utc_timestamp(
        schedule_activated_at, "schedule_activated_at"
    )
    current = parse_utc_timestamp(now, "now")
    first_id = _period_containing(schedule, activated)
    period_id = first_id
    latest: str | None = None
    while True:
        start, end, grace = _period_bounds(schedule, period_id)
        if end + timedelta(seconds=grace) > current:
            return latest
        latest = period_id
        if schedule == "weekly_full":
            next_start = start + timedelta(days=7)
            year, week, _ = next_start.isocalendar()
            period_id = f"{year:04d}-W{week:02d}"
        else:
            next_start = end
            period_id = f"{next_start.year:04d}-{next_start.month:02d}"


def validate_surveillance_authority(
    events: Sequence[Mapping[str, Any]],
    *,
    schedule: str,
    lane: str,
    manifest_id: str,
    activation_generation: int,
    schema_links: Mapping[str, Any],
    source: Mapping[str, Any],
    now: str,
    manifests: Mapping[str, Mapping[str, Any]],
) -> str:
    """Resolve one schedule's bootstrap-or-latest-period authority at ``now``."""

    _expect_enum(schedule, ("monthly_deep", "weekly_full"), "schedule")
    _expect_enum(lane, ("local", "runnerless_pr"), "lane")
    Sha256Id(manifest_id)
    _expect_int(activation_generation, "activation_generation", minimum=1)
    _validate_source(dict(source), "source")
    if source["source_kind"] != "commit":
        raise ContractError("surveillance authority requires an exact commit source")
    if _manifest_generation(manifest_id, manifests) != activation_generation:
        raise ContractError("surveillance authority generation mismatch")
    matching = [
        event
        for event in events
        if event.get("event_type") == "observation"
        and event.get("payload", {}).get("schedule") == schedule
        and event.get("payload", {}).get("lane") == lane
    ]
    if not matching:
        raise ContractError("missing surveillance evidence")
    activations = {event["payload"]["schedule_activated_at"] for event in matching}
    if len(activations) != 1:
        raise ContractError("surveillance schedule activation drift")
    activated_at = next(iter(activations))
    required = latest_required_surveillance_period(schedule, activated_at, now)
    first_period = _period_containing(
        schedule, parse_utc_timestamp(activated_at, "schedule_activated_at")
    )
    target_period = first_period if required is None else required
    bootstrap = required is None
    candidates = []
    for event in matching:
        payload = event["payload"]
        completed = parse_utc_timestamp(payload["completed_at"], "completed_at")
        deadline = parse_utc_timestamp(payload["deadline_at"], "deadline_at")
        if (
            payload["period_id"] == target_period
            and payload["bootstrap"] is bootstrap
            and payload["outcome"] == "passed"
            and completed <= deadline
            and event["manifest_id"] == manifest_id
            and canonical_json(event["schema_links"]) == canonical_json(schema_links)
            and canonical_json(event["source"]) == canonical_json(source)
            and _manifest_generation(event["manifest_id"], manifests)
            == activation_generation
        ):
            candidates.append(event)
    if len(candidates) != 1:
        raise ContractError("missing or conflicting current surveillance authority")
    if bootstrap:
        deadline = parse_utc_timestamp(
            candidates[0]["payload"]["deadline_at"], "deadline_at"
        )
        if parse_utc_timestamp(now, "now") >= deadline:
            raise ContractError("bootstrap authority expired")
    return candidates[0]["event_id"]


def _validate_observation_payload(
    value: Any, where: str, event: Mapping[str, Any]
) -> None:
    fields = {
        "observation_kind",
        "lane",
        "category",
        "schedule",
        "schedule_activated_at",
        "period_id",
        "period_end_at",
        "grace_seconds",
        "deadline_at",
        "bootstrap",
        "completed_at",
        "outcome",
        "current_ms",
        "full_ms",
        "focused_ms",
        "ratio_millionths",
    }
    obj = _expect_object(value, fields, where=where)
    kind = _expect_enum(
        obj["observation_kind"],
        ("deep_periodic_monthly", "full_release_weekly", "paired_speed", "real_change"),
        f"{where}.observation_kind",
    )
    _expect_enum(obj["lane"], ("local", "runnerless_pr"), f"{where}.lane")
    _expect_enum(obj["outcome"], ("blocked", "failed", "passed"), f"{where}.outcome")
    if obj["category"] is not None:
        _expect_token(obj["category"], f"{where}.category")
    surveillance = kind in ("full_release_weekly", "deep_periodic_monthly")
    period_fields = (
        "schedule",
        "schedule_activated_at",
        "period_id",
        "period_end_at",
        "grace_seconds",
        "deadline_at",
        "completed_at",
    )
    if surveillance:
        if any(obj[field] is None for field in period_fields):
            raise ContractError(f"{where}: surveillance period fields are required")
        expected_schedule = (
            "weekly_full" if kind == "full_release_weekly" else "monthly_deep"
        )
        _expect_literal(obj["schedule"], expected_schedule, f"{where}.schedule")
        activated = parse_utc_timestamp(obj["schedule_activated_at"], f"{where}.schedule_activated_at")
        completed = parse_utc_timestamp(obj["completed_at"], f"{where}.completed_at")
        _, end, grace = _period_bounds(expected_schedule, obj["period_id"])
        _expect_literal(obj["period_end_at"], _format_utc(end), f"{where}.period_end_at")
        _expect_literal(obj["grace_seconds"], grace, f"{where}.grace_seconds")
        deadline = end + timedelta(seconds=grace)
        _expect_literal(obj["deadline_at"], _format_utc(deadline), f"{where}.deadline_at")
        first_period = _period_containing(expected_schedule, activated)
        first_start, _, _ = _period_bounds(expected_schedule, first_period)
        period_start, _, _ = _period_bounds(expected_schedule, obj["period_id"])
        if period_start < first_start:
            raise ContractError(f"{where}: period predates schedule activation")
        if obj["bootstrap"] and obj["period_id"] != first_period:
            raise ContractError(f"{where}: bootstrap must identify first required period")
        if not obj["bootstrap"] and obj["outcome"] == "passed" and completed < end:
            raise ContractError(f"{where}: period proof completed before period end")
        if obj["outcome"] == "passed" and completed > deadline:
            raise ContractError(f"{where}: late surveillance cannot pass")
        if (
            event["manifest_id"] is None
            or event["source"] is None
            or event["source"]["source_kind"] != "commit"
            or not event["receipt_ids"]
        ):
            raise ContractError(f"{where}: surveillance lacks consumer-bound commit evidence")
        for field in ("current_ms", "full_ms", "focused_ms", "ratio_millionths"):
            if obj[field] is not None:
                raise ContractError(f"{where}.{field}: must be null outside paired speed")
    else:
        if any(obj[field] is not None for field in period_fields):
            raise ContractError(f"{where}: non-surveillance period fields must be null")
        if obj["bootstrap"] is not False:
            raise ContractError(f"{where}: non-surveillance bootstrap must be false")
        if kind == "paired_speed":
            if obj["category"] is None:
                raise ContractError(f"{where}: paired speed requires category")
            current = _expect_int(obj["current_ms"], f"{where}.current_ms", minimum=1)
            full = _expect_int(obj["full_ms"], f"{where}.full_ms", minimum=1)
            focused = _expect_int(obj["focused_ms"], f"{where}.focused_ms", minimum=1)
            ratio = _expect_int(obj["ratio_millionths"], f"{where}.ratio_millionths", minimum=0)
            if ratio != (min(current, full) * 1_000_000) // focused:
                raise ContractError(f"{where}.ratio_millionths: exact ratio mismatch")
        else:
            for field in ("current_ms", "full_ms", "focused_ms", "ratio_millionths"):
                if obj[field] is not None:
                    raise ContractError(f"{where}.{field}: must be null outside paired speed")


def _validate_graduation_payload(value: Any, where: str) -> None:
    fields = {
        "lane",
        "tags",
        "activation_generation",
        "corpus_digest",
        "edge_digest",
        "streak_digest",
        "budget_digest",
        "speed_digest",
        "required_surveillance_event_ids",
        "invalidation_drill_event_ids",
    }
    obj = _expect_object(value, fields, where=where)
    _expect_enum(obj["lane"], ("local", "runnerless_pr"), f"{where}.lane")
    _validate_string_set(obj["tags"], f"{where}.tags", validator=_expect_token)
    _expect_int(obj["activation_generation"], f"{where}.activation_generation", minimum=1)
    for field in ("corpus_digest", "edge_digest", "streak_digest", "budget_digest", "speed_digest"):
        Sha256Id(obj[field])
    for field in ("required_surveillance_event_ids", "invalidation_drill_event_ids"):
        _validate_string_set(
            obj[field], f"{where}.{field}", validator=lambda member, _: Sha256Id(member)
        )


def _validate_invalidation_payload(value: Any, where: str) -> None:
    obj = _expect_object(
        value,
        {"lane", "activation_generation", "reason", "detected_at", "detection_evidence_id"},
        where=where,
    )
    _expect_enum(obj["lane"], ("local", "runnerless_pr"), f"{where}.lane")
    _expect_int(obj["activation_generation"], f"{where}.activation_generation", minimum=1)
    _expect_enum(
        obj["reason"],
        (
            "cleanup_failed",
            "control_drift",
            "ledger_invalid",
            "receipt_invalid",
            "safety_mismatch",
            "surveillance_invalid",
            "surveillance_missed",
        ),
        f"{where}.reason",
    )
    parse_utc_timestamp(obj["detected_at"], f"{where}.detected_at")
    Sha256Id(obj["detection_evidence_id"])


def _validate_rollback_payload(value: Any, where: str) -> None:
    obj = _expect_object(
        value, {"lane", "from_generation", "to_generation", "invalidation_event_id"}, where=where
    )
    _expect_enum(obj["lane"], ("local", "runnerless_pr"), f"{where}.lane")
    _expect_int(obj["from_generation"], f"{where}.from_generation", minimum=1)
    _expect_int(obj["to_generation"], f"{where}.to_generation", minimum=1)
    Sha256Id(obj["invalidation_event_id"])


def _validate_restoration_payload(value: Any, where: str) -> None:
    obj = _expect_object(
        value,
        {
            "lane",
            "invalidation_event_id",
            "required_period_event_ids",
            "restored_generation",
            "graduation_event_id",
        },
        where=where,
    )
    _expect_enum(obj["lane"], ("local", "runnerless_pr"), f"{where}.lane")
    Sha256Id(obj["invalidation_event_id"])
    _validate_string_set(
        obj["required_period_event_ids"],
        f"{where}.required_period_event_ids",
        validator=lambda member, _: Sha256Id(member),
    )
    _expect_int(obj["restored_generation"], f"{where}.restored_generation", minimum=1)
    Sha256Id(obj["graduation_event_id"])


def _manifest_generation(
    manifest_id: str,
    manifests: Mapping[str, Mapping[str, Any]] | None,
) -> int:
    if manifests is None or manifest_id not in manifests:
        raise ContractError("consumer-bound event requires its manifest")
    manifest = validate_manifest(dict(manifests[manifest_id]))
    return manifest["activation"]["generation"]


def _same_event_binding(consumer: Mapping[str, Any], evidence: Mapping[str, Any]) -> bool:
    return (
        evidence["manifest_id"] == consumer["manifest_id"]
        and evidence["source"] is not None
        and consumer["source"] is not None
        and canonical_json(evidence["source"]) == canonical_json(consumer["source"])
        and canonical_json(evidence["schema_links"]) == canonical_json(consumer["schema_links"])
    )


def _validate_consumer_bindings(
    event: Mapping[str, Any],
    prior: Mapping[str, Mapping[str, Any]],
    manifests: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    payload = event["payload"]
    event_type = event["event_type"]
    if event_type == "graduation":
        if event["manifest_id"] is None or event["source"] is None:
            raise ContractError("graduation: manifest and source are required")
        if event["source"]["source_kind"] != "commit":
            raise ContractError("graduation: exact commit source is required")
        generation = _manifest_generation(event["manifest_id"], manifests)
        if generation != payload["activation_generation"]:
            raise ContractError("graduation: target generation mismatch")
        schedules: set[str] = set()
        for event_id in payload["required_surveillance_event_ids"]:
            evidence = prior.get(event_id)
            if (
                evidence is None
                or evidence["event_type"] != "observation"
                or evidence["payload"]["schedule"] not in ("weekly_full", "monthly_deep")
                or evidence["payload"]["lane"] != payload["lane"]
                or evidence["payload"]["outcome"] != "passed"
                or evidence["payload"]["bootstrap"] is not False
                or not _same_event_binding(event, evidence)
            ):
                raise ContractError("graduation: non-consumer-bound surveillance reference")
            if _manifest_generation(evidence["manifest_id"], manifests) != generation:
                raise ContractError("graduation: surveillance generation mismatch")
            schedule = evidence["payload"]["schedule"]
            if schedule in schedules:
                raise ContractError("graduation: duplicate surveillance schedule")
            schedules.add(schedule)
        if schedules != {"weekly_full", "monthly_deep"}:
            raise ContractError("graduation: each surveillance schedule requires evidence")
        for schedule in ("weekly_full", "monthly_deep"):
            expected_event_id = validate_surveillance_authority(
                list(prior.values()),
                schedule=schedule,
                lane=payload["lane"],
                manifest_id=event["manifest_id"],
                activation_generation=generation,
                schema_links=event["schema_links"],
                source=event["source"],
                now=event["occurred_at"],
                manifests=manifests,
            )
            if expected_event_id not in payload["required_surveillance_event_ids"]:
                raise ContractError("graduation: surveillance proof is not current")
        for event_id in payload["invalidation_drill_event_ids"]:
            evidence = prior.get(event_id)
            if (
                evidence is None
                or evidence["event_type"] != "observation"
                or evidence["payload"]["observation_kind"] != "real_change"
                or evidence["payload"]["schedule"] is not None
                or evidence["payload"]["lane"] != payload["lane"]
                or evidence["payload"]["outcome"] != "passed"
                or not _same_event_binding(event, evidence)
                or _manifest_generation(evidence["manifest_id"], manifests) != generation
            ):
                raise ContractError("graduation: non-consumer-bound drill reference")
    elif event_type == "rollback":
        invalidation = prior.get(payload["invalidation_event_id"])
        if (
            invalidation is None
            or invalidation["event_type"] != "invalidation"
            or invalidation["payload"]["lane"] != payload["lane"]
            or invalidation["payload"]["activation_generation"] != payload["from_generation"]
        ):
            raise ContractError("rollback: invalid invalidation reference")
        if event["manifest_id"] is None:
            raise ContractError("rollback: target manifest_id is required")
    elif event_type == "restoration":
        invalidation = prior.get(payload["invalidation_event_id"])
        graduation = prior.get(payload["graduation_event_id"])
        if (
            invalidation is None
            or invalidation["event_type"] != "invalidation"
            or invalidation["payload"]["lane"] != payload["lane"]
        ):
            raise ContractError("restoration: invalid invalidation reference")
        if (
            graduation is None
            or graduation["event_type"] != "graduation"
            or graduation["payload"]["lane"] != payload["lane"]
            or graduation["payload"]["activation_generation"] != payload["restored_generation"]
            or not _same_event_binding(event, graduation)
        ):
            raise ContractError("restoration: invalid graduation reference")
        generation = _manifest_generation(event["manifest_id"], manifests)
        if generation != payload["restored_generation"]:
            raise ContractError("restoration: target generation mismatch")
        for event_id in payload["required_period_event_ids"]:
            evidence = prior.get(event_id)
            if (
                evidence is None
                or evidence["event_type"] != "observation"
                or evidence["payload"]["schedule"] not in ("weekly_full", "monthly_deep")
                or evidence["payload"]["lane"] != payload["lane"]
                or evidence["payload"]["outcome"] != "passed"
                or not _same_event_binding(event, evidence)
            ):
                raise ContractError("restoration: non-consumer-bound period reference")
        expected_period_ids = {
            validate_surveillance_authority(
                list(prior.values()),
                schedule=schedule,
                lane=payload["lane"],
                manifest_id=event["manifest_id"],
                activation_generation=generation,
                schema_links=event["schema_links"],
                source=event["source"],
                now=event["occurred_at"],
                manifests=manifests,
            )
            for schedule in ("weekly_full", "monthly_deep")
        }
        if set(payload["required_period_event_ids"]) != expected_period_ids:
            raise ContractError("restoration: period evidence is not current")


def event_logical_credit_keys(event: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    payload = event["payload"]
    kind = event["event_type"]
    if kind == "authority_genesis":
        return []
    if kind == "acceptance":
        return [("acceptance", item["ac_id"]) for item in payload["criteria"]]
    if kind == "observation":
        if payload["schedule"] is not None:
            return ([
                ("schedule", payload["period_id"], payload["lane"])
            ])
        source = event["source"]
        if source is None:
            raise ContractError("observation logical key requires source")
        return [
            (
                payload["observation_kind"],
                payload["lane"],
                payload["category"],
                source["candidate_tree_sha256"],
            )
        ]
    if kind == "graduation":
        return [("graduation", payload["lane"], payload["activation_generation"])]
    if kind == "invalidation":
        return [
            (
                "invalidation",
                payload["lane"],
                payload["activation_generation"],
                payload["reason"],
                payload["detection_evidence_id"],
            )
        ]
    if kind == "rollback":
        return [
            ("rollback", payload["lane"], payload["from_generation"], payload["to_generation"])
        ]
    return [("restoration", payload["lane"], payload["invalidation_event_id"])]


def _passing_credit(event: Mapping[str, Any], key: tuple[Any, ...]) -> bool:
    if event["event_type"] == "acceptance":
        ac_id = key[1]
        return next(item for item in event["payload"]["criteria"] if item["ac_id"] == ac_id)[
            "status"
        ] == "passed"
    if event["event_type"] == "observation":
        if event["payload"]["bootstrap"]:
            return False
        return event["payload"]["outcome"] == "passed"
    return event["event_type"] != "authority_genesis"


def reduce_logical_credits(
    events: Sequence[Mapping[str, Any]],
) -> dict[tuple[Any, ...], str]:
    credits: dict[tuple[Any, ...], str] = {}
    for event in events:
        keys = event_logical_credit_keys(event)
        if len(set(keys)) != len(keys):
            raise ContractError("duplicate logical credit key within event")
        for key in keys:
            if not _passing_credit(event, key):
                continue
            if key in credits:
                raise ContractError("conflicting second passing logical credit")
            credits[key] = event["event_id"]
    return credits


def validate_ledger(
    value: Any,
    *,
    schema_digests: Mapping[str, str] | None = None,
    manifests: Mapping[str, Mapping[str, Any]] | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    fields = {
        "schema",
        "schema_version",
        "repository_id",
        "acceptance_commit_sha",
        "created_at",
        "events",
    }
    obj = _expect_object(value, fields, where="ledger")
    _expect_literal(obj["schema"], LEDGER_SCHEMA, "ledger.schema")
    _expect_literal(obj["schema_version"], 1, "ledger.schema_version")
    _expect_literal(obj["repository_id"], REPOSITORY_ID, "ledger.repository_id")
    _expect_literal(
        obj["acceptance_commit_sha"],
        ACCEPTANCE_COMMIT_SHA,
        "ledger.acceptance_commit_sha",
    )
    _expect_literal(obj["created_at"], GENESIS_AT, "ledger.created_at")
    events = obj["events"]
    if not isinstance(events, list) or not events:
        raise ContractError("ledger.events: genesis is required")
    previous: str | None = None
    prior: dict[str, Mapping[str, Any]] = {}
    activations: dict[tuple[str, str], str] = {}
    acceptance_ids: set[str] = set()
    for index, raw_event in enumerate(events):
        event = _validate_event_common(raw_event, index, obj, schema_digests)
        if index == 0:
            if event["event_type"] != "authority_genesis" or event["previous_event_id"] is not None:
                raise ContractError("ledger: first event must be predecessor-free genesis")
            if (
                event["occurred_at"] != GENESIS_AT
                or event["provenance"]["reference"] != OPERATOR_RECORD_SHA256
                or event["provenance"]["reference_sha256"] != OPERATOR_RECORD_SHA256
            ):
                raise ContractError("ledger: genesis does not mirror the operator record")
        else:
            if event["event_type"] == "authority_genesis":
                raise ContractError("ledger: genesis may occur only once")
            if event["previous_event_id"] != previous:
                raise ContractError("ledger: broken or forked previous_event_id chain")
        where = f"ledger.events[{index}].payload"
        event_type = event["event_type"]
        if event_type == "authority_genesis":
            if (
                event["manifest_id"] is not None
                or event["source"] is not None
                or event["receipt_ids"]
                or event["provenance"]["kind"] != "operator_record"
            ):
                raise ContractError("genesis: invalid common-field binding")
            _validate_genesis_payload(event["payload"], where)
        elif event_type == "acceptance":
            _validate_acceptance_payload(event["payload"], where)
            for criterion in event["payload"]["criteria"]:
                if criterion["ac_id"] in acceptance_ids:
                    raise ContractError("ledger: acceptance criterion appears more than once")
                acceptance_ids.add(criterion["ac_id"])
        elif event_type == "observation":
            _validate_observation_payload(event["payload"], where, event)
            schedule = event["payload"]["schedule"]
            if schedule is not None:
                key = (event["payload"]["lane"], schedule)
                activated = event["payload"]["schedule_activated_at"]
                if key not in activations and event["payload"]["bootstrap"] is not True:
                    raise ContractError(
                        "ledger: first surveillance event must be the bootstrap canary"
                    )
                if key in activations and activations[key] != activated:
                    raise ContractError("ledger: surveillance schedule activation drift")
                activations.setdefault(key, activated)
        elif event_type == "graduation":
            _validate_graduation_payload(event["payload"], where)
        elif event_type == "invalidation":
            _validate_invalidation_payload(event["payload"], where)
        elif event_type == "rollback":
            _validate_rollback_payload(event["payload"], where)
        elif event_type == "restoration":
            _validate_restoration_payload(event["payload"], where)
        else:
            raise ContractError("ledger: unknown event type")

        if receipts is not None:
            for receipt_id in event["receipt_ids"]:
                receipt = receipts.get(receipt_id)
                if receipt is None:
                    raise ContractError("ledger event: unresolved receipt_id")
                validate_receipt(
                    dict(receipt), manifests=manifests, receipt_store=receipts
                )
                if event["source"] is not None and canonical_json(receipt["source"]) != canonical_json(
                    event["source"]
                ):
                    raise ContractError("ledger event: receipt source mismatch")
        if event_type in ("graduation", "rollback", "restoration"):
            _validate_consumer_bindings(event, prior, manifests)
        prior[event["event_id"]] = event
        previous = event["event_id"]
    reduce_logical_credits(events)
    return obj


def validate_anchored_append(
    base_bytes: bytes,
    candidate_bytes: bytes,
    anchored_base_sha256: str,
    anchored_tip_event_id: str,
    *,
    schema_digests: Mapping[str, str] | None = None,
    manifests: Mapping[str, Mapping[str, Any]] | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    Sha256Id(anchored_base_sha256)
    Sha256Id(anchored_tip_event_id)
    if sha256_id(base_bytes) != anchored_base_sha256:
        raise ContractError("anchored append: base blob digest mismatch")
    base = validate_canonical_input(base_bytes)
    candidate = validate_canonical_input(candidate_bytes)
    validate_ledger(
        base, schema_digests=schema_digests, manifests=manifests, receipts=receipts
    )
    validate_ledger(
        candidate, schema_digests=schema_digests, manifests=manifests, receipts=receipts
    )
    if base["events"][-1]["event_id"] != anchored_tip_event_id:
        raise ContractError("anchored append: base tip mismatch")
    root_fields = (
        "schema",
        "schema_version",
        "repository_id",
        "acceptance_commit_sha",
        "created_at",
    )
    if any(base[field] != candidate[field] for field in root_fields):
        raise ContractError("anchored append: ledger root changed")
    if len(candidate["events"]) <= len(base["events"]):
        raise ContractError("anchored append: candidate did not append")
    for index, event in enumerate(base["events"]):
        if canonical_json(event) != canonical_json(candidate["events"][index]):
            raise ContractError("anchored append: prior-event prefix changed")
    if candidate["events"][len(base["events"])]["previous_event_id"] != anchored_tip_event_id:
        raise ContractError("anchored append: first appended event misses anchored tip")
    return candidate


def _resolve_schema_ref(root: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ContractError("only local JSON Schema references are permitted")
    value: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or part not in value:
            raise ContractError(f"unresolved JSON Schema reference: {reference}")
        value = value[part]
    return value


def validate_schema_document(schema: Any) -> dict[str, Any]:
    """Dependency-free structural self-check for the three frozen schemas."""

    if not isinstance(schema, dict):
        raise ContractError("schema document must be an object")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ContractError("schema document must declare draft 2020-12")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ContractError("schema root must be a closed object")

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and node.get("additionalProperties") is not False:
            raise ContractError(f"{path}: object schema is not closed")
        if "$ref" in node:
            if len(node) != 1:
                raise ContractError(f"{path}: sibling keywords beside $ref are forbidden here")
            _resolve_schema_ref(schema, node["$ref"])
        for key, child in node.items():
            if key == "properties" and not isinstance(child, dict):
                raise ContractError(f"{path}/properties: expected object")
            if key == "required" and (
                not isinstance(child, list)
                or len(set(child)) != len(child)
                or not all(isinstance(item, str) for item in child)
            ):
                raise ContractError(f"{path}/required: invalid")
            walk(child, f"{path}/{key}")

    walk(schema, "#")
    return schema


def _schema_type_matches(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    raise ContractError(f"unsupported schema type: {expected}")


def validate_against_schema(
    instance: Any,
    schema: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any] | None = None,
    where: str = "$",
) -> None:
    """Evaluate the dependency-free JSON Schema subset used by the v1 files."""

    if schema is True:
        return
    if schema is False:
        raise ContractError(f"{where}: false schema")
    root = root_schema or schema
    if "$ref" in schema:
        validate_against_schema(
            instance, _resolve_schema_ref(root, schema["$ref"]), root_schema=root, where=where
        )
        return
    if "allOf" in schema:
        for child in schema["allOf"]:
            validate_against_schema(instance, child, root_schema=root, where=where)
    if "anyOf" in schema:
        successes = 0
        for child in schema["anyOf"]:
            try:
                validate_against_schema(instance, child, root_schema=root, where=where)
                successes += 1
            except ContractError:
                pass
        if successes == 0:
            raise ContractError(f"{where}: no anyOf schema matched")
    if "oneOf" in schema:
        successes = 0
        for child in schema["oneOf"]:
            try:
                validate_against_schema(instance, child, root_schema=root, where=where)
                successes += 1
            except ContractError:
                pass
        if successes != 1:
            raise ContractError(f"{where}: expected exactly one oneOf match, got {successes}")
    if "if" in schema:
        try:
            validate_against_schema(instance, schema["if"], root_schema=root, where=where)
            branch = schema.get("then")
        except ContractError:
            branch = schema.get("else")
        if branch is not None:
            validate_against_schema(instance, branch, root_schema=root, where=where)
    if "const" in schema and instance != schema["const"]:
        raise ContractError(f"{where}: const mismatch")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractError(f"{where}: enum mismatch")
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else expected_type
        if not any(_schema_type_matches(instance, candidate) for candidate in expected_types):
            raise ContractError(f"{where}: type mismatch")
    if isinstance(instance, str):
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            raise ContractError(f"{where}: pattern mismatch")
        if len(instance) < schema.get("minLength", 0):
            raise ContractError(f"{where}: minLength mismatch")
    if isinstance(instance, int) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise ContractError(f"{where}: minimum mismatch")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ContractError(f"{where}: maximum mismatch")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            raise ContractError(f"{where}: minItems mismatch")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise ContractError(f"{where}: maxItems mismatch")
        if schema.get("uniqueItems") and len({canonical_json(item) for item in instance}) != len(instance):
            raise ContractError(f"{where}: uniqueItems mismatch")
        for index, child in enumerate(schema.get("prefixItems", [])):
            if index < len(instance):
                validate_against_schema(
                    instance[index], child, root_schema=root, where=f"{where}/{index}"
                )
        if "items" in schema:
            start = len(schema.get("prefixItems", []))
            for index, item in enumerate(instance[start:], start=start):
                validate_against_schema(
                    item, schema["items"], root_schema=root, where=f"{where}/{index}"
                )
    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = set(required) - set(instance)
        if missing:
            raise ContractError(f"{where}: missing required properties {sorted(missing)}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                validate_against_schema(
                    value, properties[key], root_schema=root, where=f"{where}/{key}"
                )
            elif schema.get("additionalProperties") is False:
                raise ContractError(f"{where}: unknown property {key}")


def _load_file(path: str) -> bytes:
    return Path(path).read_bytes()


def _check_schema_files(paths: Sequence[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = parse_json_document(_load_file(path))
        result[path] = validate_schema_document(value)
    return result


def _default_schema_paths(directory: Path) -> tuple[Path, Path, Path]:
    return (
        directory / "verification-manifest.schema.json",
        directory / "verification-receipt.schema.json",
        directory / "verification-rollout-ledger.schema.json",
    )


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    schemas_parser = subparsers.add_parser("check-schemas")
    schemas_parser.add_argument("paths", nargs="+")
    ledger_parser = subparsers.add_parser("check-ledger")
    ledger_parser.add_argument("ledger")
    ledger_parser.add_argument("schemas", nargs="*")
    args = parser.parse_args(argv)
    if args.command == "check-schemas":
        _check_schema_files(args.paths)
        return 0
    ledger_path = Path(args.ledger)
    schema_paths = [Path(path) for path in args.schemas]
    if not schema_paths:
        schema_paths = list(_default_schema_paths(ledger_path.parent))
    if len(schema_paths) != 3:
        raise ContractError("check-ledger requires exactly three schemas")
    schemas = _check_schema_files([str(path) for path in schema_paths])
    by_contract: dict[str, tuple[dict[str, Any], str]] = {}
    for path in schema_paths:
        schema = schemas[str(path)]
        contract = schema.get("properties", {}).get("schema", {}).get("const")
        if contract not in (MANIFEST_SCHEMA, RECEIPT_SCHEMA, LEDGER_SCHEMA):
            raise ContractError(f"unrecognized schema contract: {path}")
        by_contract[contract] = (schema, str(schema_digest(_load_file(str(path)))))
    ledger_bytes = _load_file(str(ledger_path))
    ledger = validate_canonical_input(ledger_bytes)
    ledger_schema = by_contract[LEDGER_SCHEMA][0]
    validate_against_schema(ledger, ledger_schema)
    validate_ledger(
        ledger,
        schema_digests={
            "manifest": by_contract[MANIFEST_SCHEMA][1],
            "receipt": by_contract[RECEIPT_SCHEMA][1],
            "ledger": by_contract[LEDGER_SCHEMA][1],
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except ContractError as exc:
        print(f"verification contract error: {exc}")
        raise SystemExit(1)
