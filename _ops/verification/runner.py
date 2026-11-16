#!/usr/bin/env python3
"""Sequential local-shadow execution, receipt storage, and closed import."""

from __future__ import annotations

import argparse
import copy
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from . import contracts, selector
except ImportError:  # pragma: no cover - direct-script interface
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _ops.verification import contracts, selector


ROOT = Path(__file__).resolve().parents[2]
VERIFICATION_DIR = ROOT / "_ops" / "verification"
MANIFEST_PATH = VERIFICATION_DIR / "verification-manifest.json"
MANIFEST_SCHEMA_PATH = VERIFICATION_DIR / "verification-manifest.schema.json"
RECEIPT_SCHEMA_PATH = VERIFICATION_DIR / "verification-receipt.schema.json"
LEDGER_SCHEMA_PATH = VERIFICATION_DIR / "verification-rollout-ledger.schema.json"
LEDGER_PATH = VERIFICATION_DIR / "verification-rollout-ledger.json"

PRESERVED_FULL_OBLIGATION_ID = "dev.structure"
RECEIPT_NAMESPACE = Path("verification-selector") / "receipts" / "sha256"
TEMP_PREFIX = "manifest-verification-"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_TEMP_NAME = re.compile(r"^\.receipt-[a-z0-9_]{8}$")
IPV4_COMPONENT = re.compile(br"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$")
NETWORK_NAME_COMPONENT = re.compile(
    br"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\."
    br"(?:com|dev|internal|io|local|net|org)$",
    re.IGNORECASE,
)

# Operational bounds only; they do not alter the frozen receipt wire contract.
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
TERMINATE_GRACE_SECONDS = 0.25
KILL_GRACE_SECONDS = 2.0
MAX_RETAINED_FAILED_EVENTS = 32

RUNNER_ENVIRONMENT = frozenset(
    {
        "HOME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPATH",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
    }
)

RECEIPT_DIAGNOSTIC_CODES = frozenset(
    {
        "cleanup.complete",
        "fallback.full",
        "focused.authoritative",
        "focused.passed",
        "full.authoritative",
        "shadow.unobserved",
    }
)
INVALIDATION_REASONS = frozenset(
    {
        "cleanup_failed",
        "control_drift",
        "ledger_invalid",
        "receipt_invalid",
        "safety_mismatch",
        "surveillance_invalid",
        "surveillance_missed",
    }
)
SELECTOR_DIAGNOSTIC_CODES = frozenset(
    {
        "selector.capability-blocked",
        "selector.classification-failed",
        "selector.control-failed",
        "selector.empty-change-set",
        "selector.empty-change-tags",
        "selector.lane-shadow",
        "selector.relationship-ineligible",
        "selector.self-protection",
        "selector.tags-ungraduated",
        "source.capture-failed",
        "source.diff-ambiguous",
        "source.diff-malformed",
        "source.git-missing",
        "source.git-refused",
        "source.gitlink-unsupported",
        "source.head-ambiguous",
        "source.head-drift",
        "source.head-malformed",
        "source.index-ambiguous",
        "source.index-drift",
        "source.index-invalid",
        "source.index-malformed",
        "source.index-unmerged",
        "source.intent-to-add",
        "source.manifest-invalid",
        "source.manifest-missing",
        "source.object-path-invalid",
        "source.object-store-drift",
        "source.path-invalid",
        "source.repo-invalid",
        "source.tree-malformed",
    }
)

# This is presentation data, not schema data. Tests lock it to the closed v1
# selector, receipt, and import vocabularies so explanations cannot invent state.
EXPLANATIONS: dict[str, str] = {
    "cleanup.complete": "Cleanup succeeded; no owned process or path remains; no repair is needed.",
    "fallback.full": "Focused proof was unavailable; full remains required; inspect the recorded causes.",
    "focused.authoritative": "Graduated focus supplied authority; full was not substituted; inspect any red row.",
    "focused.passed": "Selected obligations passed; only graduated policy may use that result; retain the receipt.",
    "full.authoritative": "The preserved broad verifier supplied authority; focus cannot override it; follow its result.",
    "shadow.unobserved": "Focus was predicted but not run; no pass was claimed; use the linked full result.",
    "cleanup_failed": "Cleanup could not be proven; the run is red; remove residue before retrying.",
    "control_drift": "A frozen control binding changed; focus is unsafe; restore or review the authority.",
    "ledger_invalid": "Ledger continuity or credit validation failed; evidence is blocked; repair the ledger.",
    "receipt_invalid": "Receipt identity, schema, storage, or privacy validation failed; reject it; rerun safely.",
    "safety_mismatch": "Source or proof safety did not match; focus is blocked; run the preserved full verifier.",
    "selector.capability-blocked": "A required local capability is absent; focus is blocked; use full or restore the capability.",
    "selector.classification-failed": "The change could not be classified exactly; full remains required; repair the manifest mapping.",
    "selector.control-failed": "Selector control validation failed; focus is blocked; repair the candidate controls.",
    "selector.empty-change-set": "No exact change was available to classify; full remains required; supply an explicit source.",
    "selector.empty-change-tags": "The change produced no safe rollout tag; full remains required; classify the changed inputs.",
    "selector.lane-shadow": "This lane is shadow-only; focus was not executed; use the authoritative full result.",
    "selector.relationship-ineligible": "A selected dependency is inapplicable; focus is blocked; repair the obligation graph.",
    "selector.self-protection": "Verification controls changed; full is mandatory; review the control change under full proof.",
    "selector.tags-ungraduated": "At least one change tag is ungraduated; full remains required; complete governed graduation.",
    "source.capture-failed": "Exact source capture failed; focus is blocked; retry with a stable explicit source.",
    "source.diff-ambiguous": "The Git delta was ambiguous; focus is blocked; repair the index or use full.",
    "source.diff-malformed": "Git returned a malformed delta; focus is blocked; repair the repository before retrying.",
    "source.git-missing": "Git is unavailable; source identity cannot be proven; restore Git before retrying.",
    "source.git-refused": "Required Git plumbing failed; source identity is unproven; repair the repository.",
    "source.gitlink-unsupported": "The candidate contains a gitlink; exact bytes are unsupported; use full after removing it.",
    "source.head-ambiguous": "HEAD could not be resolved exactly; focus is blocked; select an explicit valid source.",
    "source.head-drift": "HEAD changed during capture; focus is blocked; retry against a stable source.",
    "source.head-malformed": "HEAD identity was malformed; focus is blocked; repair the repository reference.",
    "source.index-ambiguous": "The index contains ambiguous entries; focus is blocked; repair the index.",
    "source.index-drift": "The index changed during capture; focus is blocked; retry after writes stop.",
    "source.index-invalid": "The supplied index is invalid; focus is blocked; provide one exact regular index file.",
    "source.index-malformed": "The index could not be parsed exactly; focus is blocked; rebuild the index.",
    "source.index-unmerged": "The index contains unmerged stages; focus is blocked; resolve the merge first.",
    "source.intent-to-add": "Intent-to-add lacks exact candidate bytes; focus is blocked; stage the complete content.",
    "source.manifest-invalid": "The candidate manifest is invalid; focus is blocked; restore a valid governed manifest.",
    "source.manifest-missing": "The candidate manifest or schema is missing; focus is blocked; restore both controls.",
    "source.object-path-invalid": "The Git object path is unsafe; focus is blocked; restore the expected object store.",
    "source.object-store-drift": "Git objects changed during capture; focus is blocked; retry after repository writes stop.",
    "source.path-invalid": "A source path is unsafe or malformed; focus is blocked; repair the candidate path.",
    "source.repo-invalid": "The repository root is invalid or ambiguous; focus is blocked; use the exact worktree root.",
    "source.tree-malformed": "The candidate tree could not be parsed exactly; focus is blocked; repair the Git tree.",
    "surveillance_invalid": "Required surveillance evidence is invalid; focus is blocked; replace it with valid proof.",
    "surveillance_missed": "Required surveillance evidence is missing or late; focus is blocked; run the owed proof.",
}


class RunnerError(contracts.ContractError):
    """Closed failure whose text is safe to expose."""

    def __init__(self, reason: str) -> None:
        if reason not in INVALIDATION_REASONS:
            raise ValueError("unknown runner invalidation reason")
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ResourceLimits:
    timeout_ms: int
    cpu_seconds: int
    memory_bytes: int
    file_size_bytes: int
    open_files: int
    processes: int
    output_bytes: int = MAX_PROCESS_OUTPUT_BYTES
    terminate_grace_seconds: float = TERMINATE_GRACE_SECONDS
    kill_grace_seconds: float = KILL_GRACE_SECONDS


@dataclass(frozen=True)
class ProcessResult:
    outcome: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool
    interrupted: bool
    output_limited: bool
    memory_limited: bool
    processes_limited: bool
    sentinel_seen: bool
    children_reaped: bool
    bytecode_absent: bool
    temp_removed: bool


@dataclass(frozen=True)
class StoredReceipt:
    receipt_id: str
    path: Path
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProcessSpec:
    argv: tuple[str, ...]
    cwd: Path
    environment_allowlist: tuple[str, ...]
    limits: ResourceLimits
    stdout_sentinel: str | None = None
    success_exit_codes: tuple[int, ...] = (0,)


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _closed_codes() -> frozenset[str]:
    return (
        RECEIPT_DIAGNOSTIC_CODES
        | INVALIDATION_REASONS
        | SELECTOR_DIAGNOSTIC_CODES
    )


if set(EXPLANATIONS) != set(_closed_codes()):  # pragma: no cover - import invariant
    raise RuntimeError("explanation catalog does not match the closed v1 codes")


def render_explanations(codes: Iterable[str]) -> str:
    """Render deterministic safe explanations for closed v1 codes."""

    unique = sorted(set(codes))
    unknown = [code for code in unique if code not in EXPLANATIONS]
    if unknown:
        raise ValueError("unknown diagnostic or invalidation code")
    return "\n".join(f"{code}: {EXPLANATIONS[code]}" for code in unique)


def _safe_lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise RunnerError("receipt_invalid") from exc


def _require_mode(path: Path, expected: int, *, regular: bool = False) -> None:
    info = _safe_lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise RunnerError("receipt_invalid")
    if regular and not stat.S_ISREG(info.st_mode):
        raise RunnerError("receipt_invalid")
    if not regular and not stat.S_ISDIR(info.st_mode):
        raise RunnerError("receipt_invalid")
    if stat.S_IMODE(info.st_mode) != expected:
        raise RunnerError("receipt_invalid")


def _ensure_private_directory(path: Path) -> None:
    if path.exists():
        _require_mode(path, 0o700)
        return
    parent = path.parent
    if parent != path and not parent.exists():
        _ensure_private_directory(parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _require_mode(path, 0o700)


def _git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    environment_root = Path(tempfile.mkdtemp(prefix="manifest-git-env-"))
    try:
        env = selector._base_environment(environment_root)
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo,
                env=env,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            raise RunnerError("safety_mismatch") from exc
    finally:
        if not _remove_owned_tree(environment_root):
            raise RunnerError("cleanup_failed")
    if check and completed.returncode != 0:
        raise RunnerError("safety_mismatch")
    return completed


def _repository_root(repo: Path) -> Path:
    completed = _git(repo, "rev-parse", "--show-toplevel")
    try:
        raw = completed.stdout.rstrip(b"\n")
        if b"\n" in raw or b"\0" in raw:
            raise ValueError
        root = Path(os.fsdecode(raw)).resolve(strict=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RunnerError("safety_mismatch") from exc
    if not root.is_dir():
        raise RunnerError("safety_mismatch")
    return root


def receipt_store_root(repo: Path = ROOT, *, create: bool = False) -> Path:
    """Return the exact Git-local receipt directory for this worktree."""

    root = _repository_root(repo)
    completed = _git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "verification-selector",
    )
    try:
        raw = completed.stdout.rstrip(b"\n")
        if b"\n" in raw or b"\0" in raw:
            raise ValueError
        state_root = Path(os.fsdecode(raw))
        if not state_root.is_absolute():
            raise ValueError
        store = state_root / "receipts" / "sha256"
    except (UnicodeError, ValueError) as exc:
        raise RunnerError("receipt_invalid") from exc

    if create:
        for directory in (state_root, state_root / "receipts", store):
            if not directory.exists():
                try:
                    directory.mkdir(mode=0o700)
                except OSError as exc:
                    raise RunnerError("receipt_invalid") from exc
            _require_mode(directory, 0o700)
    elif store.exists():
        _require_mode(store, 0o700)
    return store


def _candidate_paths(source: selector.SourceBinding) -> tuple[bytes, ...]:
    return tuple(entry.path.raw for entry in source._candidate_entries or ())


def _validate_exact_source(source: selector.SourceBinding, manifest: selector.Manifest) -> None:
    try:
        selector._validate_source_binding(source)
    except (contracts.ContractError, selector.SelectorError) as exc:
        raise RunnerError("safety_mismatch") from exc
    if source.manifest_id != manifest.manifest_id:
        raise RunnerError("control_drift")
    entries = source._candidate_entries or ()
    raw_paths = _candidate_paths(source)
    if raw_paths != tuple(sorted(raw_paths)) or len(raw_paths) != len(set(raw_paths)):
        raise RunnerError("safety_mismatch")
    if set(source._candidate_blobs) != set(raw_paths):
        raise RunnerError("safety_mismatch")
    for entry in entries:
        blob = source._candidate_blobs[entry.path.raw]
        if str(contracts.sha256_id(blob)) != entry.blob_sha256:
            raise RunnerError("safety_mismatch")
    expected_digest = selector._candidate_digest(entries)
    if source.candidate_tree_sha256 != expected_digest:
        raise RunnerError("safety_mismatch")

    manifest_blob = source._candidate_blobs.get(selector.MANIFEST_RELATIVE_PATH)
    schema_blob = source._candidate_blobs.get(selector.MANIFEST_SCHEMA_RELATIVE_PATH)
    if manifest_blob is None or schema_blob is None:
        raise RunnerError("control_drift")
    try:
        loaded = selector.load_manifest_bytes(manifest_blob, schema_bytes=schema_blob)
    except (contracts.ContractError, selector.SelectorError) as exc:
        raise RunnerError("control_drift") from exc
    if loaded.manifest_id != manifest.manifest_id or loaded.canonical_bytes != manifest.canonical_bytes:
        raise RunnerError("control_drift")


def _open_regular_file(path: bytes, mode: int) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags, mode)


def _create_parents(root: bytes, raw_path: bytes) -> None:
    current = root
    for part in raw_path.split(b"/")[:-1]:
        current = os.path.join(current, part)
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            info = os.lstat(current)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RunnerError("safety_mismatch")


def _validate_symlink_target(raw_path: bytes, target: bytes) -> None:
    if not target or target.startswith(b"/") or b"\0" in target:
        raise RunnerError("safety_mismatch")
    resolved = list(raw_path.split(b"/")[:-1])
    for component in target.split(b"/"):
        if component in (b"", b"."):
            continue
        if component == b"..":
            if not resolved:
                raise RunnerError("safety_mismatch")
            resolved.pop()
            continue
        resolved.append(component)
    if resolved and resolved[0].lower() == b".git":
        raise RunnerError("safety_mismatch")


def materialize_candidate_snapshot(
    source: selector.SourceBinding,
    manifest: selector.Manifest,
    destination: Path,
) -> None:
    """Materialize the exact candidate tree without consulting the live worktree."""

    _validate_exact_source(source, manifest)
    created = False
    try:
        destination.mkdir(mode=0o700)
        created = True
        _require_mode(destination, 0o700)
        root = os.fsencode(destination)
        for entry in source._candidate_entries or ():
            raw_path = entry.path.raw
            _create_parents(root, raw_path)
            output_path = os.path.join(root, raw_path)
            blob = source._candidate_blobs[raw_path]
            if entry.mode == "120000":
                _validate_symlink_target(raw_path, blob)
                os.symlink(blob, output_path)
                continue
            file_mode = 0o700 if entry.mode == "100755" else 0o600
            descriptor = _open_regular_file(output_path, file_mode)
            try:
                view = memoryview(blob)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.chmod(output_path, file_mode, follow_symlinks=False)
    except BaseException as exc:
        if created and not _remove_owned_tree(destination):
            raise RunnerError("cleanup_failed") from exc
        if isinstance(exc, RunnerError):
            raise
        if isinstance(exc, (OSError, ValueError)):
            raise RunnerError("safety_mismatch") from exc
        raise


def _initialize_snapshot_git(source: selector.SourceBinding, snapshot: Path) -> None:
    _git(snapshot, "init", "--quiet")
    index_records: list[bytes] = []
    for entry in source._candidate_entries or ():
        blob = source._candidate_blobs[entry.path.raw]
        completed = _git(snapshot, "hash-object", "-w", "--stdin", input_bytes=blob)
        oid = completed.stdout.rstrip(b"\n")
        if not re.fullmatch(br"[0-9a-f]{40}", oid):
            raise RunnerError("safety_mismatch")
        if entry._oid is not None and oid.decode("ascii") != entry._oid:
            raise RunnerError("safety_mismatch")
        index_records.append(
            entry.mode.encode("ascii")
            + b" "
            + oid
            + b"\t"
            + entry.path.raw
            + b"\0"
        )
    _git(
        snapshot,
        "update-index",
        "-z",
        "--index-info",
        input_bytes=b"".join(index_records),
    )
    tree = _git(snapshot, "write-tree").stdout.rstrip(b"\n")
    if source.index_tree_sha is not None and tree.decode("ascii") != source.index_tree_sha:
        raise RunnerError("safety_mismatch")
    git_dir = snapshot / ".git"
    for directory, directories, files in os.walk(git_dir, followlinks=False):
        os.chmod(directory, 0o700)
        for name in directories:
            os.chmod(Path(directory) / name, 0o700)
        for name in files:
            os.chmod(Path(directory) / name, 0o600)


def _remove_owned_tree(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return True

    def repair_permissions(_function: Callable[..., Any], name: str, _exc: Any) -> None:
        try:
            os.chmod(name, 0o700, follow_symlinks=False)
        except OSError:
            pass
        try:
            if os.path.isdir(name) and not os.path.islink(name):
                shutil.rmtree(name, onerror=repair_permissions)
            else:
                os.unlink(name)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onerror=repair_permissions)
    except OSError:
        pass
    return not path.exists() and not path.is_symlink()


def _contains_forbidden_residue(path: Path) -> bool:
    if not path.exists():
        return False
    for directory, directories, files in os.walk(path, followlinks=False):
        names = directories + files
        if "__pycache__" in names:
            return True
        if any(name.endswith((".pyc", ".pyo")) for name in files):
            return True
    return False


def _execution_environment(allowlist: Sequence[str], process_root: Path) -> dict[str, str]:
    if list(allowlist) != sorted(set(allowlist)):
        raise RunnerError("receipt_invalid")
    allowed = set(allowlist)
    if not allowed <= RUNNER_ENVIRONMENT:
        raise RunnerError("receipt_invalid")
    if "PYTHONDONTWRITEBYTECODE" not in allowed:
        raise RunnerError("receipt_invalid")

    home = process_root / "home"
    config = process_root / "xdg-config"
    cache = process_root / "xdg-cache"
    data = process_root / "xdg-data"
    state = process_root / "xdg-state"
    temp = process_root / "tmp"
    for path in (home, config, cache, data, state, temp):
        _ensure_private_directory(path)

    values = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(cache),
        "XDG_DATA_HOME": str(data),
        "XDG_STATE_HOME": str(state),
        "PYTHONPATH": str(process_root.parent / "snapshot" / "_ops"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", os.defpath),
        "TMPDIR": str(temp),
    }
    return {name: values[name] for name in sorted(allowed)}


def _bounded_resource_limit(kind: int, requested: int) -> tuple[int, int]:
    current_soft, current_hard = resource.getrlimit(kind)
    if current_hard == resource.RLIM_INFINITY:
        return requested, current_hard
    return min(requested, current_hard), current_hard


def _resource_preexec(limits: ResourceLimits) -> Callable[[], None]:
    def apply() -> None:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            _bounded_resource_limit(resource.RLIMIT_CPU, limits.cpu_seconds),
        )
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            _bounded_resource_limit(resource.RLIMIT_FSIZE, limits.file_size_bytes),
        )
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            _bounded_resource_limit(resource.RLIMIT_NOFILE, limits.open_files),
        )
        os.umask(0o077)

    return apply


def _process_group_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_process_group(process_group: int, sent_signal: signal.Signals) -> bool:
    try:
        os.killpg(process_group, sent_signal)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


def _wait_for_group_exit(
    process_group: int,
    timeout_seconds: float,
    process: subprocess.Popen[bytes] | None = None,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while _process_group_alive(process_group) and time.monotonic() < deadline:
        if process is not None:
            process.poll()
        time.sleep(0.01)
    return not _process_group_alive(process_group)


def _process_group_usage(process_group: int) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pgid=,rss="],
            env={"PATH": os.defpath},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    count = 0
    rss_kib = 0
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pgid, rss = (int(field) for field in fields)
        except ValueError:
            continue
        if pgid == process_group:
            count += 1
            rss_kib += rss
    return count, rss_kib * 1024


def _quiesce_process_group(
    process: subprocess.Popen[bytes],
    limits: ResourceLimits,
) -> bool:
    group = process.pid
    if _process_group_alive(group):
        _signal_process_group(group, signal.SIGTERM)
        if not _wait_for_group_exit(
            group,
            limits.terminate_grace_seconds,
            process,
        ):
            _signal_process_group(group, signal.SIGKILL)
            _wait_for_group_exit(group, limits.kill_grace_seconds, process)
    try:
        process.wait(timeout=limits.kill_grace_seconds)
    except subprocess.TimeoutExpired:
        _signal_process_group(group, signal.SIGKILL)
        try:
            process.wait(timeout=limits.kill_grace_seconds)
        except subprocess.TimeoutExpired:
            return False
    return not _process_group_alive(group)


def _run_one_process(
    argv: Sequence[str],
    cwd: Path,
    allowlist: Sequence[str],
    limits: ResourceLimits,
    process_root: Path,
    stdout_sentinel: str | None,
    success_exit_codes: Sequence[int] = (0,),
) -> ProcessResult:
    if not argv or any(
        not isinstance(item, str) or not item or "\0" in item for item in argv
    ):
        raise RunnerError("receipt_invalid")
    if (
        limits.timeout_ms <= 0
        or limits.cpu_seconds <= 0
        or limits.memory_bytes <= 0
        or limits.file_size_bytes <= 0
        or limits.open_files <= 0
        or limits.processes <= 0
        or limits.output_bytes <= 0
        or limits.terminate_grace_seconds < 0
        or limits.kill_grace_seconds <= 0
    ):
        raise RunnerError("receipt_invalid")
    if (
        not success_exit_codes
        or tuple(success_exit_codes) != tuple(sorted(set(success_exit_codes)))
        or any(not isinstance(code, int) for code in success_exit_codes)
    ):
        raise RunnerError("receipt_invalid")
    if cwd.is_absolute() or ".." in PurePosixPath(cwd.as_posix()).parts:
        raise RunnerError("receipt_invalid")
    execution_cwd = process_root.parent / "snapshot" / cwd
    if not execution_cwd.is_dir():
        raise RunnerError("safety_mismatch")

    environment = _execution_environment(allowlist, process_root)
    sentinel = stdout_sentinel.encode("utf-8") if stdout_sentinel else None
    output_count = 0
    output_limited = threading.Event()
    memory_limited = threading.Event()
    processes_limited = threading.Event()
    sentinel_seen = threading.Event()
    output_lock = threading.Lock()
    interrupted = threading.Event()
    process: subprocess.Popen[bytes] | None = None

    previous_handlers: dict[signal.Signals, Any] = {}

    def handle_interrupt(_number: int, _frame: Any) -> None:
        interrupted.set()

    if threading.current_thread() is threading.main_thread():
        for handled in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            previous_handlers[handled] = signal.getsignal(handled)
            signal.signal(handled, handle_interrupt)

    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=execution_cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            preexec_fn=_resource_preexec(limits),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        for handled, previous in previous_handlers.items():
            signal.signal(handled, previous)
        raise RunnerError("safety_mismatch") from exc

    assert process.stdout is not None

    def drain_output() -> None:
        nonlocal output_count
        overlap = b""
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            with output_lock:
                output_count += len(chunk)
                if output_count > limits.output_bytes:
                    output_limited.set()
            if sentinel is not None and not sentinel_seen.is_set():
                combined = overlap + chunk
                if sentinel in combined:
                    sentinel_seen.set()
                overlap = combined[-max(0, len(sentinel) - 1) :]

    reader = threading.Thread(target=drain_output, name="receipt-output-drain", daemon=True)
    reader.start()

    deadline = started + (limits.timeout_ms / 1000)
    next_resource_check = started + 0.1
    timed_out = False
    try:
        while process.poll() is None:
            if (
                interrupted.is_set()
                or output_limited.is_set()
                or memory_limited.is_set()
                or processes_limited.is_set()
            ):
                break
            now = time.monotonic()
            if now >= next_resource_check:
                usage = _process_group_usage(process.pid)
                if usage is None:
                    processes_limited.set()
                    break
                process_count, resident_bytes = usage
                if process_count > limits.processes:
                    processes_limited.set()
                    break
                if resident_bytes > limits.memory_bytes:
                    memory_limited.set()
                    break
                next_resource_check = now + 0.1
            if now >= deadline:
                timed_out = True
                break
            time.sleep(0.01)
    finally:
        try:
            children_reaped = _quiesce_process_group(process, limits)
            reader.join(timeout=limits.kill_grace_seconds)
            children_reaped = children_reaped and not reader.is_alive()
            process.stdout.close()
        finally:
            for handled, previous in previous_handlers.items():
                signal.signal(handled, previous)

    if process.returncode is None:
        children_reaped = False
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    code = process.returncode
    seen = sentinel is None or sentinel_seen.is_set()

    if not children_reaped:
        outcome = "cleanup_failed"
    elif timed_out:
        outcome = "timed_out"
    elif interrupted.is_set():
        outcome = "interrupted"
    elif output_limited.is_set() or memory_limited.is_set() or processes_limited.is_set():
        outcome = "resource_limited"
    elif code in success_exit_codes and seen:
        outcome = "passed"
    else:
        outcome = "failed"

    bytecode_absent = not _contains_forbidden_residue(process_root.parent)
    temp_removed = _remove_owned_tree(process_root)
    return ProcessResult(
        outcome=outcome,
        exit_code=code if outcome != "timed_out" else None,
        duration_ms=duration_ms,
        timed_out=timed_out,
        interrupted=interrupted.is_set(),
        output_limited=output_limited.is_set(),
        memory_limited=memory_limited.is_set(),
        processes_limited=processes_limited.is_set(),
        sentinel_seen=seen,
        children_reaped=children_reaped,
        bytecode_absent=bytecode_absent,
        temp_removed=temp_removed,
    )


def run_sequential_processes(
    run_root: Path,
    specifications: Sequence[ProcessSpec],
) -> tuple[ProcessResult, ...]:
    """Run fixed process specifications one at a time in isolated groups."""

    if not specifications or not (run_root / "snapshot").is_dir():
        raise RunnerError("safety_mismatch")
    results: list[ProcessResult] = []
    for index, specification in enumerate(specifications):
        process_root = run_root / f"process-{index:03d}"
        try:
            process_root.mkdir(mode=0o700)
        except OSError as exc:
            raise RunnerError("cleanup_failed") from exc
        try:
            result = _run_one_process(
                specification.argv,
                specification.cwd,
                specification.environment_allowlist,
                specification.limits,
                process_root,
                specification.stdout_sentinel,
                specification.success_exit_codes,
            )
        except BaseException as exc:
            if not _remove_owned_tree(process_root):
                raise RunnerError("cleanup_failed") from exc
            raise
        if not result.children_reaped or not result.temp_removed:
            raise RunnerError("cleanup_failed")
        results.append(result)
    return tuple(results)


def _manifest_obligation(manifest: selector.Manifest, obligation_id: str) -> Mapping[str, Any]:
    for obligation in manifest.value["obligations"]:
        if obligation["id"] == obligation_id:
            return obligation
    raise RunnerError("control_drift")


def _limits_for_obligation(
    manifest: selector.Manifest,
    obligation: Mapping[str, Any],
) -> ResourceLimits:
    cost_id = obligation["cost_class"]
    cost = next(
        (item for item in manifest.value["cost_classes"] if item["id"] == cost_id),
        None,
    )
    if cost is None:
        raise RunnerError("control_drift")
    timeout_seconds = cost["timeout_seconds"]
    output_bytes = cost["output_bytes"]
    processes = cost["pids"]
    return ResourceLimits(
        timeout_ms=timeout_seconds * 1000,
        cpu_seconds=timeout_seconds,
        memory_bytes=cost["memory_mib"] * 1024 * 1024,
        file_size_bytes=output_bytes,
        open_files=max(32, min(256, processes * 2)),
        processes=processes,
        output_bytes=output_bytes,
    )


def _execution_from_result(
    result: ProcessResult,
    obligation: Mapping[str, Any],
) -> dict[str, Any]:
    if result.outcome == "passed":
        outcome = "passed"
    elif result.outcome == "timed_out":
        outcome = "timed_out"
    elif result.outcome == "cleanup_failed":
        outcome = "cleanup_failed"
    else:
        outcome = "failed"
    return {
        "executor_id": "preserved.full",
        "execution_disposition": "run",
        "selection_causes": ["full_mode"],
        "outcome": outcome,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "command_digest": str(
            contracts.command_digest(
                obligation["argv"],
                obligation["cwd_b64"],
                obligation["environment_allowlist"],
            )
        ),
        "diagnostic_code": "full.authoritative",
    }


def _receipt_source(source: selector.SourceBinding) -> dict[str, Any]:
    return copy.deepcopy(source.to_object())


def focused_decision(
    causes: Iterable[str],
    *,
    blocked: bool = False,
) -> tuple[str, tuple[str, ...]]:
    """Reduce a union of closed causes with Appendix-A scalar precedence."""

    canonical = tuple(sorted(set(causes)))
    if not set(canonical) <= set(contracts.CAUSE_CODES):
        raise RunnerError("receipt_invalid")
    if blocked:
        return "blocked", canonical
    return contracts._expected_focused_disposition(canonical), canonical


def _changes_from_source(source: selector.SourceBinding) -> list[dict[str, Any]]:
    base = {entry.path.raw: entry for entry in source._base_entries or ()}
    candidate = {
        entry.path.raw: entry for entry in source._candidate_entries or ()
    }
    changes: list[selector.Change] = []
    for raw_path in sorted(set(base) | set(candidate)):
        old = base.get(raw_path)
        new = candidate.get(raw_path)
        if old is None:
            status = "add"
        elif new is None:
            status = "delete"
        elif old.mode == new.mode and old.blob_sha256 == new.blob_sha256:
            continue
        elif old.mode[:3] != new.mode[:3]:
            status = "type_change"
        else:
            status = "modify"
        changes.append(
            selector.Change(
                status=status,
                old_path=old.path if old else None,
                new_path=new.path if new else None,
                old_mode=old.mode if old else None,
                new_mode=new.mode if new else None,
                old_blob_sha256=old.blob_sha256 if old else None,
                new_blob_sha256=new.blob_sha256 if new else None,
                _old_blob=source._base_blobs.get(raw_path) if old else None,
                _new_blob=source._candidate_blobs.get(raw_path) if new else None,
            )
        )
    ordered = tuple(sorted(changes, key=lambda item: item.sort_key))
    try:
        selector._validate_changes(source, ordered)
    except (contracts.ContractError, selector.SelectorError) as exc:
        raise RunnerError("safety_mismatch") from exc
    return [change.to_object() for change in ordered]


def _focused_rows(
    selection: selector.Selection,
    manifest: selector.Manifest,
) -> list[dict[str, Any]]:
    obligations = {
        item["id"]: item for item in manifest.value["obligations"]
    }
    rows: list[dict[str, Any]] = []
    for decision in selection.decisions:
        obligation = obligations.get(decision.obligation_id)
        if obligation is None:
            raise RunnerError("control_drift")
        expected_disposition, canonical_causes = focused_decision(
            decision.selection_causes,
            blocked=decision.focused_disposition == "blocked",
        )
        if (
            canonical_causes != decision.selection_causes
            or expected_disposition != decision.focused_disposition
        ):
            raise RunnerError("receipt_invalid")
        rows.append(
            {
                "obligation_id": decision.obligation_id,
                "selection_causes": list(canonical_causes),
                "focused_disposition": decision.focused_disposition,
                "execution_disposition": "not_applicable",
                "outcome": "not_observed",
                "exit_code": None,
                "duration_ms": None,
                "command_digest": str(
                    contracts.command_digest(
                        obligation["argv"],
                        obligation["cwd_b64"],
                        obligation["environment_allowlist"],
                    )
                ),
                "diagnostic_code": "shadow.unobserved",
            }
        )
    return rows


def _receipt_base(
    *,
    mode: str,
    source: selector.SourceBinding,
    manifest: selector.Manifest,
    aggregate_execution: Mapping[str, Any],
    changes: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    cleanup: Mapping[str, Any],
    authoritative_receipt_id: str | None,
    lane: str,
    requested_mode: str,
    timing: Mapping[str, int],
    created_at: str,
) -> dict[str, Any]:
    receipt = {
        "schema": "dev-verification-receipt",
        "schema_version": 1,
        "receipt_id": "sha256:" + ("0" * 64),
        "created_at": created_at,
        "repository_id": contracts.REPOSITORY_ID,
        "selector_version": selector.SELECTOR_VERSION,
        "manifest_id": manifest.manifest_id,
        "lane": lane,
        "mode": mode,
        "requested_mode": requested_mode,
        "effective_mode": "full",
        "activation_generation": manifest.value["activation"]["generation"],
        "source": _receipt_source(source),
        "changes": copy.deepcopy(changes),
        "aggregate_execution": copy.deepcopy(aggregate_execution),
        "rows": rows,
        "authoritative_receipt_id": authoritative_receipt_id,
        "timing": copy.deepcopy(dict(timing)),
        "cleanup": copy.deepcopy(cleanup),
    }
    return contracts.with_derived_identity(receipt, "receipt_id")


def _load_json_file(path: Path, *, maximum: int | None = None) -> tuple[dict[str, Any], bytes]:
    try:
        if stat.S_ISLNK(path.lstat().st_mode) or not path.is_file():
            raise RunnerError("receipt_invalid")
        size = path.stat().st_size
        if maximum is not None and size > maximum:
            raise RunnerError("receipt_invalid")
        raw = path.read_bytes()
        parsed = contracts.parse_json_document(raw)
    except RunnerError:
        raise
    except (OSError, contracts.ContractError) as exc:
        raise RunnerError("receipt_invalid") from exc
    if not isinstance(parsed, dict):
        raise RunnerError("receipt_invalid")
    return parsed, raw


def _validate_privacy(payload: Mapping[str, Any]) -> None:
    raw = contracts.canonical_json(payload)
    forbidden = (
        b"/Users/",
        b"/home/",
        b"/private/",
        b"/tmp/",
        b"file://",
        b"http://",
        b"https://",
        b"BEGIN PRIVATE KEY",
    )
    if any(marker in raw for marker in forbidden):
        raise RunnerError("receipt_invalid")

    host_users = {
        value.encode("utf-8", errors="ignore")
        for value in (
            os.environ.get("USER", ""),
            os.environ.get("LOGNAME", ""),
            Path.home().name,
        )
        if value
    }

    def inspect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, dict):
            if (
                "diagnostic_code" in value
                and value["diagnostic_code"] not in RECEIPT_DIAGNOSTIC_CODES
            ):
                raise RunnerError("receipt_invalid")
            if "path_b64" in value:
                try:
                    path = contracts.PathValue.from_object(value).raw
                except contracts.ContractError as exc:
                    raise RunnerError("receipt_invalid") from exc
                components = path.split(b"/")
                forbidden_components = {b"Users", b"home", b"private", b"tmp"}
                forbidden_components.update(host_users)
                if any(component in forbidden_components for component in components):
                    raise RunnerError("receipt_invalid")
                if any(
                    IPV4_COMPONENT.fullmatch(component)
                    or NETWORK_NAME_COMPONENT.fullmatch(component)
                    or b"@" in component
                    for component in components
                ):
                    raise RunnerError("receipt_invalid")
                lowered = path.lower()
                if any(
                    marker in lowered
                    for marker in (b"http:", b"https:", b"file:", b"begin private key")
                ):
                    raise RunnerError("receipt_invalid")
            for item in value.values():
                inspect(item)

    inspect(payload)


def _validate_receipt_safety(payload: Mapping[str, Any]) -> None:
    _validate_privacy(payload)
    cleanup = payload.get("cleanup")
    if not isinstance(cleanup, Mapping):
        raise RunnerError("receipt_invalid")
    proof_flags = (
        "children_reaped",
        "temp_removed",
        "index_removed",
        "objects_unchanged",
        "bytecode_absent",
    )
    if (
        cleanup.get("diagnostic_code") != "cleanup.complete"
        or any(cleanup.get(flag) is not True for flag in proof_flags)
    ):
        raise RunnerError("cleanup_failed")


def _stored_receipts(store: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    if not store.exists():
        return receipts
    _require_mode(store, 0o700)
    entries = sorted(store.iterdir(), key=lambda item: item.name)
    recoverable: list[tuple[Path, os.stat_result]] = []
    for path in entries:
        if path.name.startswith(".receipt-"):
            try:
                info = path.lstat()
            except OSError as exc:
                raise RunnerError("receipt_invalid") from exc
            if (
                RECEIPT_TEMP_NAME.fullmatch(path.name) is None
                or not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_size > MAX_RECEIPT_BYTES
            ):
                raise RunnerError("receipt_invalid")
            recoverable.append((path, info))
            continue
        if not path.name.endswith(".json"):
            raise RunnerError("receipt_invalid")
        receipt_hex = path.name[:-5]
        if not HEX64.fullmatch(receipt_hex):
            raise RunnerError("receipt_invalid")
        receipt_id = f"sha256:{receipt_hex}"
        _require_mode(path, 0o600, regular=True)
        payload, raw = _load_json_file(path, maximum=MAX_RECEIPT_BYTES)
        if raw != contracts.canonical_json(payload):
            raise RunnerError("receipt_invalid")
        if payload.get("receipt_id") != receipt_id:
            raise RunnerError("receipt_invalid")
        _validate_receipt_safety(payload)
        receipts[receipt_id] = payload
    if recoverable:
        for path, original in recoverable:
            try:
                current = path.lstat()
            except OSError as exc:
                raise RunnerError("receipt_invalid") from exc
            if (
                current.st_dev != original.st_dev
                or current.st_ino != original.st_ino
                or current.st_mode != original.st_mode
                or current.st_uid != original.st_uid
                or current.st_nlink != original.st_nlink
                or current.st_size != original.st_size
            ):
                raise RunnerError("receipt_invalid")
        try:
            for path, _info in recoverable:
                path.unlink()
            directory = os.open(store, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            raise RunnerError("receipt_invalid") from exc
    return receipts


def store_receipt(
    receipt: Mapping[str, Any],
    *,
    repo: Path = ROOT,
    manifest: Mapping[str, Any],
) -> StoredReceipt:
    """Validate and atomically store one canonical content-addressed receipt."""

    root = receipt_store_root(repo, create=True)
    existing = _stored_receipts(root)
    candidate = copy.deepcopy(dict(receipt))
    try:
        receipt_schema = contracts.parse_json_document(RECEIPT_SCHEMA_PATH.read_bytes())
        contracts.validate_against_schema(candidate, receipt_schema)
        contracts.validate_receipt(
            candidate,
            manifests={manifest["manifest_id"]: dict(manifest)},
            receipt_store=existing,
        )
    except (OSError, contracts.ContractError) as exc:
        raise RunnerError("receipt_invalid") from exc
    _validate_receipt_safety(candidate)
    receipt_id = candidate["receipt_id"]
    raw = contracts.canonical_json(candidate)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise RunnerError("receipt_invalid")
    destination = root / f"{receipt_id.removeprefix('sha256:')}.json"
    if destination.exists():
        _require_mode(destination, 0o600, regular=True)
        try:
            existing_raw = destination.read_bytes()
        except OSError as exc:
            raise RunnerError("receipt_invalid") from exc
        if existing_raw != raw:
            raise RunnerError("receipt_invalid")
        return StoredReceipt(receipt_id, destination, candidate)

    descriptor: int | None = None
    temporary: Path | None = None
    installed = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=root)
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, destination)
        temporary = None
        installed = True
        os.chmod(destination, 0o600, follow_symlinks=False)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        if installed:
            try:
                destination.unlink()
            except OSError:
                pass
        raise RunnerError("receipt_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    _require_mode(destination, 0o600, regular=True)
    try:
        stored_raw = destination.read_bytes()
    except OSError as exc:
        raise RunnerError("receipt_invalid") from exc
    if stored_raw != raw:
        try:
            destination.unlink()
        except OSError:
            pass
        raise RunnerError("receipt_invalid")
    return StoredReceipt(receipt_id, destination, candidate)


def _full_and_shadow_receipts(
    source: selector.SourceBinding,
    manifest: selector.Manifest,
    selection: selector.Selection,
    result: ProcessResult,
    *,
    temp_removed: bool,
    timing: Mapping[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    obligation = _manifest_obligation(manifest, PRESERVED_FULL_OBLIGATION_ID)
    aggregate = _execution_from_result(result, obligation)
    if selection.lane == "local" and selection.requested_mode in {
        "focused_local",
        "pre_commit",
    }:
        lane = selection.requested_mode
    elif selection.lane == "runnerless_pr" and selection.requested_mode == "focused_pr":
        lane = "runnerless_pr"
    else:
        raise RunnerError("receipt_invalid")
    changes = _changes_from_source(source)
    created_at = _now_utc()
    cleanup = {
        "children_reaped": result.children_reaped,
        "index_removed": True,
        "objects_unchanged": True,
        "temp_removed": temp_removed and result.temp_removed,
        "bytecode_absent": result.bytecode_absent,
        "diagnostic_code": "cleanup.complete",
    }
    full = _receipt_base(
        mode="full",
        source=source,
        manifest=manifest,
        aggregate_execution=aggregate,
        changes=changes,
        rows=[],
        cleanup=cleanup,
        authoritative_receipt_id=None,
        lane=lane,
        requested_mode="full",
        timing=timing,
        created_at=created_at,
    )
    shadow = _receipt_base(
        mode="shadow",
        source=source,
        manifest=manifest,
        aggregate_execution=aggregate,
        changes=changes,
        rows=_focused_rows(selection, manifest),
        cleanup=cleanup,
        authoritative_receipt_id=full["receipt_id"],
        lane=lane,
        requested_mode=selection.requested_mode,
        timing=timing,
        created_at=created_at,
    )
    return full, shadow


def receipt_is_graduation_eligible(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bool:
    """Apply the v1 rows-empty rule without changing the frozen schema."""

    if not receipt.get("rows"):
        return False
    known = {item["id"] for item in manifest["obligations"]}
    rows = receipt["rows"]
    return (
        {row["obligation_id"] for row in rows} == known
        and all(row["outcome"] == "passed" for row in rows)
    )


def execute_local_shadow(
    source: selector.SourceBinding,
    manifest: selector.Manifest,
    selection: selector.Selection,
    *,
    repo: Path = ROOT,
) -> tuple[StoredReceipt, StoredReceipt]:
    """Run the preserved full verifier once, then store full before shadow."""

    _validate_exact_source(source, manifest)
    if (
        selection.source.to_object() != source.to_object()
        or selection.source.manifest_id != manifest.manifest_id
    ):
        raise RunnerError("control_drift")
    allowed_request = (
        selection.lane == "local"
        and selection.requested_mode in {"pre_commit", "focused_local"}
    ) or (
        selection.lane == "runnerless_pr"
        and selection.requested_mode == "focused_pr"
    )
    if (
        not allowed_request
        or selection.effective_mode != "full"
        or selection.fallback_executor != "preserved.full"
        or selection.focus_eligible
        or tuple(selection.diagnostic_codes)
        != tuple(sorted(set(selection.diagnostic_codes)))
        or not set(selection.diagnostic_codes) <= SELECTOR_DIAGNOSTIC_CODES
    ):
        raise RunnerError("receipt_invalid")
    _focused_rows(selection, manifest)
    obligation = _manifest_obligation(manifest, PRESERVED_FULL_OBLIGATION_ID)
    expected = selector.HARNESS_INVENTORY_V1[PRESERVED_FULL_OBLIGATION_ID]
    if (
        tuple(obligation["argv"]) != expected.argv
        or contracts._decode_base64(obligation["cwd_b64"], "cwd_b64") != expected.cwd
    ):
        raise RunnerError("control_drift")

    total_started = time.monotonic()
    outer = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    os.chmod(outer, 0o700)
    snapshot = outer / "snapshot"
    result: ProcessResult | None = None
    snapshot_started = time.monotonic()
    try:
        materialize_candidate_snapshot(source, manifest, snapshot)
        _initialize_snapshot_git(source, snapshot)
        snapshot_ms = max(0, int((time.monotonic() - snapshot_started) * 1000))
        result = run_sequential_processes(
            outer,
            (
                ProcessSpec(
                    argv=tuple(obligation["argv"]),
                    cwd=Path(os.fsdecode(expected.cwd)),
                    environment_allowlist=tuple(
                        obligation["environment_allowlist"]
                    ),
                    limits=_limits_for_obligation(manifest, obligation),
                    stdout_sentinel=obligation.get("stdout_sentinel"),
                    success_exit_codes=tuple(obligation["success_exit_codes"]),
                ),
            ),
        )[0]
        residue_absent = not _contains_forbidden_residue(outer)
        if not residue_absent:
            result = ProcessResult(
                **{
                    **result.__dict__,
                    "bytecode_absent": False,
                }
            )
    finally:
        cleanup_started = time.monotonic()
        outer_removed = _remove_owned_tree(outer)
        cleanup_ms = max(0, int((time.monotonic() - cleanup_started) * 1000))
    if result is None:
        raise RunnerError("safety_mismatch")
    if (
        not outer_removed
        or not result.children_reaped
        or not result.temp_removed
        or not result.bytecode_absent
    ):
        raise RunnerError("cleanup_failed")
    timing = {
        "snapshot_ms": snapshot_ms,
        "selection_ms": 0,
        "execution_ms": result.duration_ms,
        "cleanup_ms": cleanup_ms,
        "total_ms": max(0, int((time.monotonic() - total_started) * 1000)),
    }

    full, shadow = _full_and_shadow_receipts(
        source,
        manifest,
        selection,
        result,
        temp_removed=outer_removed,
        timing=timing,
    )
    manifest_payload = copy.deepcopy(dict(manifest.value))
    full_stored = store_receipt(full, repo=repo, manifest=manifest_payload)
    # The authoritative full receipt is durably present before linkage is accepted.
    shadow_stored = store_receipt(shadow, repo=repo, manifest=manifest_payload)
    return full_stored, shadow_stored


def _git_blob(repo: Path, revision: str, path: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", path) or path.startswith("/"):
        raise RunnerError("control_drift")
    completed = _git(repo, "show", f"{revision}:{path}")
    return completed.stdout


def _commit_candidate_digest(repo: Path, revision: str) -> str:
    environment_root = Path(
        tempfile.mkdtemp(prefix="manifest-commit-source-")
    )
    try:
        env = selector._base_environment(environment_root)
        try:
            entries, _blobs = selector._parse_tree(repo, revision, env)
        except (contracts.ContractError, selector.SelectorError) as exc:
            raise RunnerError("safety_mismatch") from exc
    finally:
        if not _remove_owned_tree(environment_root):
            raise RunnerError("cleanup_failed")
    return selector._candidate_digest(entries)


def _source_commit_candidate(
    repo: Path,
    source: Mapping[str, Any],
) -> tuple[str | None, bool]:
    kind = source["source_kind"]
    if kind == "commit":
        revision = source["commit_sha"]
    elif kind == "pull_request":
        revision = source["head_commit_sha"]
    else:
        revision = "HEAD"
    completed = _git(repo, "cat-file", "-e", f"{revision}^{{commit}}", check=False)
    if completed.returncode != 0:
        return None, False
    if kind == "pull_request":
        base = source["base_commit_sha"]
        head = source["head_commit_sha"]
        merge_base = _git(
            repo,
            "merge-base",
            "--all",
            base,
            head,
            check=False,
        )
        if (
            merge_base.returncode != 0
            or merge_base.stdout.splitlines()
            != [source["merge_base_sha"].encode("ascii")]
        ):
            return None, False
    if kind == "staged_index":
        tree = _git(
            repo,
            "rev-parse",
            f"{revision}^{{tree}}",
            check=False,
        )
        if (
            tree.returncode != 0
            or tree.stdout.rstrip(b"\n").decode("ascii", errors="ignore")
            != source["index_tree_sha"]
        ):
            return None, False
    try:
        manifest_bytes = _git_blob(
            repo,
            revision,
            "_ops/verification/verification-manifest.json",
        )
        manifest_schema_bytes = _git_blob(
            repo,
            revision,
            "_ops/verification/verification-manifest.schema.json",
        )
        bound_manifest = selector.load_manifest_bytes(
            manifest_bytes,
            schema_bytes=manifest_schema_bytes,
        )
        candidate_digest = _commit_candidate_digest(repo, revision)
    except (contracts.ContractError, selector.SelectorError, RunnerError):
        return None, False
    if bound_manifest.manifest_id != source["manifest_id"]:
        return None, False
    return candidate_digest, True


def _load_committed_authorities(
    repo: Path,
    revision: str = "HEAD",
) -> tuple[
    dict[str, Any],
    bytes,
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, dict[str, Any]],
]:
    files = {
        "manifest": "_ops/verification/verification-manifest.json",
        "manifest_schema": "_ops/verification/verification-manifest.schema.json",
        "receipt_schema": "_ops/verification/verification-receipt.schema.json",
        "ledger_schema": "_ops/verification/verification-rollout-ledger.schema.json",
        "ledger": "_ops/verification/verification-rollout-ledger.json",
    }
    raw = {name: _git_blob(repo, revision, path) for name, path in files.items()}
    parsed: dict[str, dict[str, Any]] = {}
    try:
        for name, value in raw.items():
            parsed_value = contracts.parse_json_document(value)
            if not isinstance(parsed_value, dict):
                raise contracts.ContractError("authority root must be an object")
            parsed[name] = parsed_value
        for name in ("manifest_schema", "receipt_schema", "ledger_schema"):
            contracts.validate_schema_document(parsed[name])
        if contracts.validate_canonical_input(raw["manifest"]) != parsed["manifest"]:
            raise contracts.ContractError("manifest is noncanonical")
        if contracts.validate_canonical_input(raw["ledger"]) != parsed["ledger"]:
            raise contracts.ContractError("ledger is noncanonical")
    except contracts.ContractError as exc:
        raise RunnerError("control_drift") from exc
    manifest = copy.deepcopy(parsed["manifest"])
    try:
        contracts.validate_against_schema(manifest, parsed["manifest_schema"])
        contracts.validate_manifest(manifest)
    except contracts.ContractError as exc:
        raise RunnerError("control_drift") from exc
    schemas = {
        "manifest": str(contracts.schema_digest(parsed["manifest_schema"])),
        "receipt": str(contracts.schema_digest(parsed["receipt_schema"])),
        "ledger": str(contracts.schema_digest(parsed["ledger_schema"])),
    }
    manifests = {manifest["manifest_id"]: manifest}
    try:
        contracts.validate_against_schema(parsed["ledger"], parsed["ledger_schema"])
        contracts.validate_ledger(
            parsed["ledger"],
            schema_digests=schemas,
            manifests=manifests,
        )
    except contracts.ContractError as exc:
        raise RunnerError("ledger_invalid") from exc
    return parsed["ledger"], raw["ledger"], parsed, schemas, manifests


def _event_lane(receipt_lane: str) -> str:
    return "runnerless_pr" if receipt_lane == "runnerless_pr" else "local"


def _schema_links(schema_digests: Mapping[str, str]) -> dict[str, Any]:
    return {
        "manifest": {
            "schema": "dev-verification-manifest",
            "schema_version": 1,
            "sha256": schema_digests["manifest"],
        },
        "receipt": {
            "schema": "dev-verification-receipt",
            "schema_version": 1,
            "sha256": schema_digests["receipt"],
        },
        "ledger": {
            "schema": "dev-verification-rollout-ledger",
            "schema_version": 1,
            "sha256": schema_digests["ledger"],
        },
    }


def _import_command_digest() -> str:
    return str(
        contracts.command_digest(
            ["verify-changes", "rollout-import"],
            "X29wcw==",
            ["PYTHONDONTWRITEBYTECODE"],
        )
    )


def _observation_payload(
    receipt: Mapping[str, Any],
    candidate_matches_commit: bool,
) -> dict[str, Any]:
    aggregate_outcome = receipt["aggregate_execution"]["outcome"]
    if not candidate_matches_commit:
        outcome = "blocked"
    elif aggregate_outcome == "passed":
        outcome = "passed"
    else:
        outcome = "failed"
    return {
        "observation_kind": "real_change",
        "lane": _event_lane(receipt["lane"]),
        "category": None,
        "schedule": None,
        "schedule_activated_at": None,
        "period_id": None,
        "period_end_at": None,
        "grace_seconds": None,
        "deadline_at": None,
        "bootstrap": False,
        "completed_at": None,
        "outcome": outcome,
        "current_ms": None,
        "full_ms": None,
        "focused_ms": None,
        "ratio_millionths": None,
    }


def _observation_receipt_ids(receipt: Mapping[str, Any]) -> list[str]:
    receipt_ids = [receipt["receipt_id"]]
    linked = receipt.get("authoritative_receipt_id")
    if linked is not None:
        receipt_ids.append(linked)
    return sorted(receipt_ids)


def _observation_event(
    receipt: Mapping[str, Any],
    candidate_matches_commit: bool,
    *,
    previous_event_id: str,
    acceptance_commit_sha: str,
    schema_digests: Mapping[str, str],
    occurred_at: str,
) -> dict[str, Any]:
    import_digest = _import_command_digest()
    event = {
        "event_id": "sha256:" + ("0" * 64),
        "event_type": "observation",
        "event_version": 1,
        "previous_event_id": previous_event_id,
        "occurred_at": occurred_at,
        "repository_id": contracts.REPOSITORY_ID,
        "acceptance_commit_sha": acceptance_commit_sha,
        "manifest_id": receipt["manifest_id"],
        "source": copy.deepcopy(receipt["source"]),
        "receipt_ids": _observation_receipt_ids(receipt),
        "schema_links": _schema_links(schema_digests),
        "provenance": {
            "kind": "local_command",
            "reference": import_digest,
            "reference_sha256": import_digest,
        },
        "payload": _observation_payload(receipt, candidate_matches_commit),
    }
    return contracts.with_derived_identity(event, "event_id")


def _existing_import_event(
    events: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> dict[str, Any] | None:
    import_digest = _import_command_digest()
    expected_provenance = {
        "kind": "local_command",
        "reference": import_digest,
        "reference_sha256": import_digest,
    }
    expected_ids = _observation_receipt_ids(receipt)
    for event in events:
        payload = event.get("payload", {})
        if (
            event.get("event_type") == "observation"
            and event.get("manifest_id") == receipt["manifest_id"]
            and event.get("source") == receipt["source"]
            and event.get("receipt_ids") == expected_ids
            and event.get("provenance") == expected_provenance
            and payload.get("observation_kind") == "real_change"
            and payload.get("lane") == _event_lane(receipt["lane"])
        ):
            return copy.deepcopy(dict(event))
    return None


def _ledger_anchor_matches(
    disk: Mapping[str, Any],
    committed: Mapping[str, Any],
) -> bool:
    disk_events = disk.get("events")
    committed_events = committed.get("events")
    if not isinstance(disk_events, list) or not isinstance(committed_events, list):
        return False
    if len(disk_events) < len(committed_events):
        return False
    return disk_events[: len(committed_events)] == committed_events


def _write_canonical(path: Path, payload: Mapping[str, Any], mode: int) -> None:
    raw = contracts.canonical_json(payload)
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, mode)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, mode, follow_symlinks=False)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError as exc:
        raise RunnerError("ledger_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _prune_imported_receipts(
    store: Path,
    events: Sequence[Mapping[str, Any]],
) -> None:
    local_events = [
        event
        for event in events
        if (
            event.get("event_type") == "observation"
            and event.get("payload", {}).get("lane") == "local"
        )
    ]
    passing = [
        event
        for event in local_events
        if event.get("payload", {}).get("outcome") == "passed"
    ]
    unsuccessful = [
        event
        for event in local_events
        if event.get("payload", {}).get("outcome") != "passed"
    ]
    retained_events = (
        passing[-1:]
        + unsuccessful[-MAX_RETAINED_FAILED_EVENTS:]
    )
    keep = {
        receipt_id
        for event in retained_events
        for receipt_id in event.get("receipt_ids", [])
    }
    removable = {
        receipt_id
        for event in local_events
        for receipt_id in event.get("receipt_ids", [])
    }
    for receipt_id in sorted(removable - keep):
        if not isinstance(receipt_id, str) or not receipt_id.startswith("sha256:"):
            continue
        receipt_hex = receipt_id.removeprefix("sha256:")
        if not HEX64.fullmatch(receipt_hex):
            continue
        path = store / f"{receipt_hex}.json"
        if path.exists():
            _require_mode(path, 0o600, regular=True)
            try:
                path.unlink()
            except OSError as exc:
                raise RunnerError("receipt_invalid") from exc
    try:
        directory = os.open(store, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise RunnerError("receipt_invalid") from exc


def import_receipt(
    receipt_path: Path,
    *,
    repo: Path = ROOT,
    ledger_path: Path = LEDGER_PATH,
    now: str | None = None,
) -> dict[str, Any]:
    """Import one canonical receipt against the committed ledger prefix."""

    root = _repository_root(repo)
    expected_ledger = root / "_ops" / "verification" / "verification-rollout-ledger.json"
    try:
        if ledger_path.resolve(strict=True) != expected_ledger.resolve(strict=True):
            raise RunnerError("ledger_invalid")
    except OSError as exc:
        raise RunnerError("ledger_invalid") from exc
    _require_mode(ledger_path, 0o644, regular=True)
    store = receipt_store_root(root, create=False)
    if not store.exists():
        raise RunnerError("receipt_invalid")
    _require_mode(receipt_path, 0o600, regular=True)
    try:
        supplied = receipt_path.resolve(strict=True)
        expected_parent = store.resolve(strict=True)
    except OSError as exc:
        raise RunnerError("receipt_invalid") from exc
    if supplied.parent != expected_parent:
        raise RunnerError("receipt_invalid")

    receipt, receipt_raw = _load_json_file(supplied, maximum=MAX_RECEIPT_BYTES)
    if receipt_raw != contracts.canonical_json(receipt):
        raise RunnerError("receipt_invalid")
    receipt_id = receipt.get("receipt_id")
    if (
        not isinstance(receipt_id, str)
        or supplied.name != f"{receipt_id.removeprefix('sha256:')}.json"
    ):
        raise RunnerError("receipt_invalid")
    if str(contracts.derive_identity(receipt, "receipt_id")) != receipt_id:
        raise RunnerError("receipt_invalid")
    _validate_receipt_safety(receipt)

    (
        committed_ledger,
        committed_ledger_raw,
        authorities,
        schema_digests,
        manifests,
    ) = _load_committed_authorities(root)
    if receipt.get("manifest_id") not in manifests:
        raise RunnerError("control_drift")
    all_receipts = _stored_receipts(store)
    try:
        contracts.validate_against_schema(receipt, authorities["receipt_schema"])
        contracts.validate_receipt(
            receipt,
            manifests=manifests,
            receipt_store=all_receipts,
        )
    except contracts.ContractError as exc:
        raise RunnerError("receipt_invalid") from exc

    candidate_digest, committed = _source_commit_candidate(root, receipt["source"])
    candidate_matches = (
        committed
        and candidate_digest == receipt["source"]["candidate_tree_sha256"]
    )
    if (
        receipt["source"]["source_kind"] in {"commit", "pull_request"}
        and not candidate_matches
    ):
        raise RunnerError("safety_mismatch")

    disk_ledger, disk_raw = _load_json_file(ledger_path)
    if disk_raw != contracts.canonical_json(disk_ledger):
        raise RunnerError("ledger_invalid")
    if not _ledger_anchor_matches(disk_ledger, committed_ledger):
        raise RunnerError("ledger_invalid")
    try:
        contracts.validate_against_schema(disk_ledger, authorities["ledger_schema"])
        contracts.validate_ledger(
            disk_ledger,
            schema_digests=schema_digests,
            manifests=manifests,
        )
    except contracts.ContractError as exc:
        raise RunnerError("ledger_invalid") from exc

    existing_event = _existing_import_event(
        disk_ledger["events"],
        receipt,
    )
    if existing_event is not None:
        try:
            _prune_imported_receipts(store, disk_ledger["events"])
        except RunnerError:
            pass
        return existing_event

    occurred_at = now or _now_utc()
    try:
        contracts.parse_utc_timestamp(occurred_at)
    except contracts.ContractError as exc:
        raise RunnerError("ledger_invalid") from exc
    event = _observation_event(
        receipt,
        candidate_matches,
        previous_event_id=disk_ledger["events"][-1]["event_id"],
        acceptance_commit_sha=disk_ledger["acceptance_commit_sha"],
        schema_digests=schema_digests,
        occurred_at=occurred_at,
    )
    candidate_ledger = copy.deepcopy(disk_ledger)
    candidate_ledger["events"].append(event)
    _validate_privacy(candidate_ledger)
    try:
        candidate_raw = contracts.canonical_json(candidate_ledger)
        contracts.validate_against_schema(candidate_ledger, authorities["ledger_schema"])
        contracts.validate_anchored_append(
            committed_ledger_raw,
            candidate_raw,
            str(contracts.sha256_id(committed_ledger_raw)),
            committed_ledger["events"][-1]["event_id"],
            schema_digests=schema_digests,
            manifests=manifests,
        )
    except contracts.ContractError as exc:
        raise RunnerError("ledger_invalid") from exc

    _write_canonical(ledger_path, candidate_ledger, 0o644)
    try:
        _prune_imported_receipts(store, candidate_ledger["events"])
    except RunnerError:
        # The canonical append is the commit boundary. Retention is recoverable
        # maintenance and an exact retry returns this event while retrying prune.
        pass
    return event


def validate_current_ledger(
    *,
    repo: Path = ROOT,
    ledger_path: Path = LEDGER_PATH,
) -> int:
    root = _repository_root(repo)
    committed, committed_raw, authorities, schema_digests, manifests = (
        _load_committed_authorities(root)
    )
    ledger, raw = _load_json_file(ledger_path)
    if raw != contracts.canonical_json(ledger):
        raise RunnerError("ledger_invalid")
    try:
        contracts.validate_against_schema(ledger, authorities["ledger_schema"])
        contracts.validate_ledger(
            ledger,
            schema_digests=schema_digests,
            manifests=manifests,
        )
        if raw != committed_raw:
            contracts.validate_anchored_append(
                committed_raw,
                raw,
                str(contracts.sha256_id(committed_raw)),
                committed["events"][-1]["event_id"],
                schema_digests=schema_digests,
                manifests=manifests,
            )
    except contracts.ContractError as exc:
        raise RunnerError("ledger_invalid") from exc
    return len(ledger["events"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    explain = subcommands.add_parser("explain", help="render closed diagnostic codes")
    explain.add_argument("codes", nargs="+")
    import_command = subcommands.add_parser(
        "rollout-import",
        help="import one Git-local receipt into the rollout ledger",
    )
    import_command.add_argument("--receipt", type=Path, required=True)
    validate = subcommands.add_parser(
        "validate-ledger",
        help="validate the canonical rollout ledger",
    )
    validate.add_argument("ledger", nargs="?", type=Path, default=LEDGER_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "explain":
            print(render_explanations(args.codes))
            return 0
        if args.command == "rollout-import":
            event = import_receipt(args.receipt)
            print(f"imported observation {event['event_id']}")
            return 0
        if args.command == "validate-ledger":
            count = validate_current_ledger(ledger_path=args.ledger)
            print(f"ledger valid: {count} events")
            return 0
    except (RunnerError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
