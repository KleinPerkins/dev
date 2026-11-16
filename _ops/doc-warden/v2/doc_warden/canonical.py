"""Canonical bytes and contained filesystem operations."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CanonicalError(ValueError):
    """A value or path cannot be represented safely."""


@dataclass(frozen=True)
class ParsedArtifact:
    metadata: dict[str, Any]
    body: str
    path: Path


def _reject_float(value: str) -> None:
    raise CanonicalError(f"non-canonical number: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalError(f"duplicate key: {key}")
        result[key] = value
    return result


def parse_json_object(data: str | bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise CanonicalError(str(exc)) from exc
    if not isinstance(value, dict):
        raise CanonicalError("expected one JSON object")
    return value


def canonical_json(value: object) -> bytes:
    def reject_numbers(item: object) -> None:
        if isinstance(item, float):
            raise CanonicalError("floating-point values are not canonical")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise CanonicalError("object keys must be strings")
            for child in item.values():
                reject_numbers(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                reject_numbers(child)

    reject_numbers(value)
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalError(str(exc)) from exc
    return (rendered + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_ref(value: bytes) -> str:
    return f"sha256:{sha256_bytes(value)}"


def digest_file_manifest(paths: list[Path]) -> str:
    manifest = {path.name: digest_ref(path.read_bytes()) for path in sorted(paths)}
    return digest_ref(canonical_json(manifest))


def parse_artifact(path: Path) -> ParsedArtifact:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise CanonicalError("artifact must begin with JSON front matter")
    end = raw.find("\n---\n", 4)
    if end < 0:
        raise CanonicalError("unterminated front matter")
    metadata_text = raw[4:end]
    metadata = parse_json_object(metadata_text)
    if canonical_json(metadata).decode("utf-8")[:-1] != metadata_text:
        raise CanonicalError("front matter is not canonical JSON")
    return ParsedArtifact(metadata=metadata, body=raw[end + 5 :], path=path)


def contained_path(root: Path, relative: str, *, for_write: bool = True) -> Path:
    if not relative or os.path.isabs(relative):
        raise CanonicalError("path must be non-empty and relative")
    root = root.resolve(strict=True)
    candidate = root.joinpath(relative)
    normalized = Path(os.path.normpath(candidate))
    try:
        normalized.relative_to(root)
    except ValueError as exc:
        raise CanonicalError("path escapes canonical root") from exc
    cursor = root
    for part in Path(relative).parts[:-1] if for_write else Path(relative).parts:
        if part in {"", ".", ".."}:
            raise CanonicalError("unsafe path component")
        cursor = cursor / part
        if cursor.is_symlink():
            raise CanonicalError("symlinked writable component")
        if cursor.exists() and not cursor.is_dir():
            raise CanonicalError("non-directory path component")
    if candidate.is_symlink():
        raise CanonicalError("symlink target refused")
    if candidate.exists():
        mode = candidate.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise CanonicalError("special file refused")
    return candidate


def atomic_write(root: Path, relative: str, content: bytes) -> Path:
    root_before = root.resolve(strict=True)
    destination = contained_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    root_after = root.resolve(strict=True)
    if root_after != root_before:
        raise CanonicalError("canonical root changed")
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise CanonicalError("staged output is not a regular file")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination
