#!/usr/bin/env python3
"""INT-014 cooperative maintenance; no native exclusion or live admission.

This is a partial D2 source foundation, not completed native evidence resolution.
The registrar owns config/receipt writes. This module owns the private maintenance
state machine and the cooperative legacy-writer barrier. Runtime observations are
supplied by an explicitly reconstructed, source-qualified caller, never by persisted
callables, PID lists or a 'validated' flag. No live observation adapter is enrolled.
The legacy barrier is operational coordination, not a same-user security boundary.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterator, Protocol
from types import MappingProxyType
import uuid

VALIDATOR_ID = "dev/int014-maintenance-validator/v1"
CONTRACT_DIGEST = "bb0c2417ae274b5f60717939f9286b8c7acd3d5ff712394d80a8b920e833a7c8"
EVIDENCE_SCHEMA = "dev/mcp-maintenance-evidence/v1"
STATE_SCHEMA = "dev/mcp-maintenance-state/v1"
HANDOFF_REFUSED = 73
_FD_ENV = "DEV_MCP_MAINTENANCE_LOCK_FD"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REV = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}\Z")
EVIDENCE_FIELDS = frozenset("schema maintenance_id issuer_source_revision accepted_contract_digest audience_digest config_target_id state_target_id config_preimage_digest state_preimage_digest known_writers consequence_review_digest legacy_handoff_id acquired_at expires_at prior_guard_state prior_guard_lock predecessor_maintenance_id recovery_of".split())
WRITER_FIELDS = frozenset("writer_id kind prior_state observed_state observation_reference observation_digest observed_at resume_disposition".split())
STATE_FIELDS = frozenset("schema maintenance_id evidence_digest predecessor_maintenance_id status last_observed_at registrar_result_reference baseline_handoff_reference release_observation_digest".split())
EDGES = {
    "acquired": {"applied_pending_handoff", "recovery_required", "cancelled", "release_failed"},
    "applied_pending_handoff": {"released", "recovery_required", "release_failed"},
    "release_failed": {"released", "cancelled", "recovery_required"},
    "recovery_required": {"released", "cancelled"},
    "released": set(), "cancelled": set(),
}


class MaintenanceError(Exception):
    """Bounded errors: never print paths, observations, config or caller errors."""
    def __init__(self, code: str = "concurrency_unqualified") -> None:
        self.code = code
        super().__init__(code)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def target_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def _closed(value: Any, fields: frozenset[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise MaintenanceError("state_invalid")


def _hex(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise MaintenanceError("state_invalid")


def _uuid(value: Any) -> None:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise MaintenanceError("state_invalid") from None


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise MaintenanceError("state_invalid") from None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise MaintenanceError("state_invalid")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_evidence(evidence: dict) -> None:
    _closed(evidence, EVIDENCE_FIELDS)
    e = evidence
    if e["schema"] != EVIDENCE_SCHEMA or e["accepted_contract_digest"] != CONTRACT_DIGEST:
        raise MaintenanceError()
    _uuid(e["maintenance_id"])
    if e["legacy_handoff_id"] != e["maintenance_id"]:
        raise MaintenanceError()
    if not isinstance(e["issuer_source_revision"], str) or not _REV.fullmatch(e["issuer_source_revision"]):
        raise MaintenanceError()
    for key in ("audience_digest", "config_target_id", "state_target_id", "consequence_review_digest"):
        _hex(e[key])
    for key in ("config_preimage_digest", "state_preimage_digest"):
        if e[key] != "absent":
            _hex(e[key])
    start, end = _time(e["acquired_at"]), _time(e["expires_at"])
    if not 0 < (end - start).total_seconds() <= 600:
        raise MaintenanceError()
    if e["prior_guard_state"] not in {"enabled", "disabled", "not_enrolled"} or e["prior_guard_lock"] not in {"on", "off", "not_applicable"}:
        raise MaintenanceError()
    if (e["prior_guard_state"] == "not_enrolled") != (e["prior_guard_lock"] == "not_applicable"):
        raise MaintenanceError()
    predecessor = e["predecessor_maintenance_id"]
    if predecessor is None:
        if e["recovery_of"] is not None:
            raise MaintenanceError()
    else:
        _uuid(predecessor)
        _hex(e["recovery_of"])
        if predecessor == e["maintenance_id"]:
            raise MaintenanceError()
    writers = e["known_writers"]
    if not isinstance(writers, list) or not 1 <= len(writers) <= 64:
        raise MaintenanceError()
    seen = set()
    for w in writers:
        _closed(w, WRITER_FIELDS)
        for key in ("writer_id", "observation_reference"):
            if not isinstance(w[key], str) or not _ID.fullmatch(w[key]):
                raise MaintenanceError()
        if w["writer_id"] in seen:
            raise MaintenanceError()
        seen.add(w["writer_id"])
        if w["kind"] not in {"legacy-mirror", "kit-lifecycle", "native-client", "editor", "server-guard", "management"} or w["prior_state"] not in {"active", "inactive", "not_enrolled"} or w["observed_state"] not in {"paused", "inactive"} or w["resume_disposition"] not in {"restore_prior", "remain_suspended"}:
            raise MaintenanceError()
        _hex(w["observation_digest"])
        if not start - timedelta(seconds=600) <= _time(w["observed_at"]) <= end:
            raise MaintenanceError()


def validate_state(state: dict, evidence: dict) -> None:
    _closed(state, STATE_FIELDS)
    s, e = state, evidence
    if s["schema"] != STATE_SCHEMA or s["maintenance_id"] != e["maintenance_id"] or s["evidence_digest"] != digest(e) or s["predecessor_maintenance_id"] != e["predecessor_maintenance_id"] or s["status"] not in EDGES:
        raise MaintenanceError("state_invalid")
    if _time(s["last_observed_at"]) < _time(e["acquired_at"]):
        raise MaintenanceError("state_invalid")
    refs = [s[k] for k in ("registrar_result_reference", "baseline_handoff_reference", "release_observation_digest")]
    for ref in refs:
        _hex(ref, nullable=True)
    if s["status"] == "acquired" and any(v is not None for v in refs):
        raise MaintenanceError("state_invalid")
    if s["status"] == "applied_pending_handoff" and (refs[0] is None or refs[2] is not None):
        raise MaintenanceError("state_invalid")
    if s["status"] in {"released", "cancelled"} and any(v is None for v in refs):
        raise MaintenanceError("state_invalid")
    if s["status"] == "release_failed" and refs[2] is None:
        raise MaintenanceError("state_invalid")


class Observations(Protocol):
    """Source-qualified runtime behavior, not serialized authorities.

    Each method must resolve supported current observations and raise on failure;
    matching digests/booleans alone cannot implement these methods. D3 must qualify
    the concrete adapter, required-writer coverage, entire durable byte eligibility,
    exact approvals, effects, lineage and baseline/restoration proofs. This module
    enrolls no production adapter. Synthetic tests use deterministic observations.
    """
    def current(self, evidence: dict, now: datetime) -> None: ...
    def lineage(self, evidence: dict, predecessor: dict) -> None: ...
    def mutation(self, request: Any, evidence: dict) -> None: ...
    def transition(self, evidence: dict, before: dict, after: dict, child: dict | None) -> None: ...


def _observed(method: Any, *args: Any) -> None:
    try:
        if method(*args) is not None:
            raise MaintenanceError()
    except MaintenanceError:
        raise
    except Exception:
        raise MaintenanceError() from None


def _private(path: Path, *, directory: bool) -> os.stat_result:
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or (not directory and info.st_nlink != 1):
        raise MaintenanceError("state_invalid")
    return info


def _safe_root(root: Path, *, create: bool) -> Path:
    if not root.is_absolute() or ".." in root.parts:
        raise MaintenanceError("state_invalid")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        if current.is_symlink() or (current / ".git").exists():
            raise MaintenanceError("state_invalid")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(root, directory=True)
    return root


def _load(path: Path) -> dict:
    def pairs(items: list) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise MaintenanceError("state_invalid")
            result[key] = value
        return result
    info = _private(path, directory=False)
    if info.st_size > 131072:
        raise MaintenanceError("state_invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (info.st_dev, info.st_ino):
            raise MaintenanceError("state_invalid")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(131073)
        value = json.loads(data, object_pairs_hook=pairs)
        if canonical(value) != data:
            raise MaintenanceError("state_invalid")
        return value
    finally:
        os.close(fd)


class MaintenanceStore:
    """One atomic private evidence/state pair per UUID; cooperative barrier shared
    with legacy callers. No config bytes, raw observations or callables persisted.
    Acquisition is explicit; merely constructing this object creates nothing.
    """
    def __init__(self, root: Path):
        self.root = Path(root)

    def check_location(self, observations: Observations) -> None:
        """Bind reconstructed checked operations to the canonical state/barrier."""
        if isinstance(observations, CheckedObservations):
            checks = observations.checks
            if self.root != checks.storage_root() / checks.policy["storage"]["maintenance_name"]:
                raise MaintenanceError("durable_material_ineligible")

    @contextmanager
    def barrier(self, *, exclusive: bool, create: bool = True) -> Iterator[int]:
        _safe_root(self.root, create=create)
        lock = self.root / "writers.lock"
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            before = _private(lock, directory=False)
            actual = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino):
                raise MaintenanceError("state_invalid")
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MaintenanceError("known_writer_active") from None
            yield fd
        finally:
            os.close(fd)

    def records(self) -> list[dict]:
        _safe_root(self.root, create=False)
        paths = list(self.root.iterdir())
        if len(paths) > 1025:
            raise MaintenanceError("state_invalid")
        result = []
        for path in paths:
            if path.name == "writers.lock":
                _private(path, directory=False)
                continue
            # A leftover interrupted write remains a refusal, never silent cleanup.
            if path.suffix != ".json":
                raise MaintenanceError("recovery_required")
            _uuid(path.stem)
            value = _load(path)
            _closed(value, frozenset({"evidence", "state"}))
            validate_evidence(value["evidence"])
            validate_state(value["state"], value["evidence"])
            if value["evidence"]["maintenance_id"] != path.stem:
                raise MaintenanceError("state_invalid")
            result.append(value)
        return result

    def read(self, maintenance_id: str) -> dict:
        _uuid(maintenance_id)
        rows = [r for r in self.records() if r["state"]["maintenance_id"] == maintenance_id]
        if len(rows) != 1:
            raise MaintenanceError("state_invalid")
        return rows[0]

    def _write(self, record: dict) -> None:
        payload = canonical(record)
        mid = record["state"]["maintenance_id"]
        target = self.root / (mid + ".json")
        before = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else "absent"
        prefix = f".pending-{mid}.{digest(record['evidence'])}.{before}."
        fd, name = tempfile.mkstemp(prefix=prefix, dir=self.root)
        # The filename binds the prior durable state and evidence even if a
        # process dies midway through writing this private, redacted candidate.
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        except BaseException:
            # A caught pre-replacement failure has not changed the prior record.
            # Process-death orphans require the explicit recovery path below.
            Path(name).unlink(missing_ok=True)
            raise
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def pending_preview(self, pending_name: str, evidence: dict, *,
                        cancelled_state: dict | None = None, prior_state: dict | None = None) -> dict:
        """Read-only exact orphan disposition; no registrar recovery claim."""
        validate_evidence(evidence)
        mid = evidence["maintenance_id"]
        prefix = f".pending-{mid}.{digest(evidence)}."
        if not pending_name.startswith(prefix) or Path(pending_name).name != pending_name:
            raise MaintenanceError("state_invalid")
        suffix = pending_name[len(prefix):].split(".")
        if len(suffix) != 2 or not suffix[1]:
            raise MaintenanceError("state_invalid")
        before_digest = suffix[0]
        if before_digest != "absent":
            _hex(before_digest)
        _safe_root(self.root, create=False)
        pending = self.root / pending_name
        _private(pending, directory=False)
        if pending.stat().st_size > 131072:
            raise MaintenanceError("state_invalid")
        target = self.root / (mid + ".json")
        if before_digest == "absent":
            before = dict(schema=STATE_SCHEMA, maintenance_id=mid, evidence_digest=digest(evidence),
                          predecessor_maintenance_id=evidence["predecessor_maintenance_id"],
                          status="acquired", last_observed_at=evidence["acquired_at"],
                          registrar_result_reference=None, baseline_handoff_reference=None,
                          release_observation_digest=None)
            if cancelled_state is None:
                raise MaintenanceError("recovery_required")
            validate_state(cancelled_state, evidence)
            if cancelled_state["status"] != "cancelled":
                raise MaintenanceError("recovery_required")
            after = cancelled_state
            if target.exists() or target.is_symlink():
                # Supported retry after the cancellation became durable but
                # before the interrupted candidate was removed.
                if _load(target) != {"evidence": evidence, "state": after}:
                    raise MaintenanceError("state_invalid")
        else:
            if cancelled_state is not None:
                raise MaintenanceError("state_invalid")
            record = _load(target)
            _closed(record, frozenset({"evidence", "state"}))
            if record["evidence"] != evidence:
                raise MaintenanceError("state_invalid")
            before = record["state"]
            validate_state(before, evidence)
            if hashlib.sha256(canonical(record)).hexdigest() != before_digest:
                if prior_state is None:
                    raise MaintenanceError("state_invalid")
                validate_state(prior_state, evidence)
                if (record != {"evidence": evidence, "state": {**prior_state, "status": "recovery_required"}}
                    or hashlib.sha256(canonical({"evidence": evidence, "state": prior_state})).hexdigest() != before_digest):
                    raise MaintenanceError("state_invalid")
                before = prior_state
            if before["status"] in {"released", "cancelled"}:
                raise MaintenanceError("state_invalid")
            after = {**before, "status": "recovery_required"}
        result = {"pending_name": pending_name,
                  "pending_digest": hashlib.sha256(pending.read_bytes()).hexdigest(),
                  "evidence_digest": digest(evidence), "prior_record_digest": before_digest,
                  "before": before, "after": after}
        return {**result, "action_digest": digest(result)}

    def recover_pending(self, preview: dict, evidence: dict, observations: Observations) -> dict:
        """Resolve one exact uncommitted candidate without admitting new writes.

        A failed initial acquisition may only be explicitly cancelled after
        observed no-mutation, baseline and restoration proof. An interrupted
        transition retains its prior references in recovery_required. Its new
        child authority remains necessary. This never executes candidate bytes.
        """
        self.check_location(observations)
        _closed(preview, frozenset({"pending_name", "pending_digest", "evidence_digest",
                                   "prior_record_digest", "before", "after", "action_digest"}))
        with self.barrier(exclusive=True, create=False):
            cancelled = preview["after"] if preview["prior_record_digest"] == "absent" else None
            current = self.pending_preview(preview["pending_name"], evidence, cancelled_state=cancelled,
                                           prior_state=preview["before"])
            if current != preview:
                raise MaintenanceError("state_invalid")
            before, after = current["before"], current["after"]
            _observed(observations.transition, evidence, before, after, None)
            self._write({"evidence": evidence, "state": after})
            (self.root / current["pending_name"]).unlink()
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return after

    def acquire(self, evidence: dict, observations: Observations, *, config_path: Path,
                state_directory: Path, now: datetime | None = None) -> dict:
        validate_evidence(evidence)
        for path, key in ((config_path, "config_target_id"), (state_directory, "state_target_id")):
            if not path.is_absolute() or path != path.resolve() or target_id(path) != evidence[key]:
                raise MaintenanceError("target_changed")
        now = now or _now()
        _fresh(evidence, now)
        # Concrete observations classify their entire context/evidence before
        # even creating the private maintenance root or cooperative lock. Repeat
        # under the barrier below to re-observe current coordination conditions.
        _observed(observations.current, evidence, now)
        if isinstance(observations, CheckedObservations):
            # The separate checked registrar path also binds the actual initial
            # images and persistence location. Legacy protocol-only fixtures do
            # not constitute that path or a production enrollment.
            observations.checks.acquisition(evidence, config_path, state_directory, self.root)
        with self.barrier(exclusive=True):
            rows = self.records()
            if any(r["evidence"]["maintenance_id"] == evidence["maintenance_id"] for r in rows):
                raise MaintenanceError("state_invalid")
            predecessor = evidence["predecessor_maintenance_id"]
            conflicts = [r for r in rows if r["evidence"]["config_target_id"] == evidence["config_target_id"] and r["state"]["status"] not in {"cancelled", "released"}]
            if predecessor is None:
                if conflicts:
                    raise MaintenanceError("recovery_required")
            else:
                parent = self.read(predecessor)
                # An interrupted inverse can itself need recovery. Its retained
                # unresolved ancestors are lineage, not competing operations.
                # Admit exactly one chain; no sibling, cycle or foreign target.
                ancestors, cursor, descendant = set(), parent, None
                while cursor is not None:
                    ancestor_id = cursor["evidence"]["maintenance_id"]
                    children = [r["evidence"]["maintenance_id"] for r in rows
                                if r["evidence"]["predecessor_maintenance_id"] == ancestor_id]
                    if (ancestor_id in ancestors or cursor["state"]["status"] != "recovery_required"
                        or children != ([] if descendant is None else [descendant])):
                        raise MaintenanceError("recovery_required")
                    for key in ("config_target_id", "state_target_id"):
                        if cursor["evidence"][key] != evidence[key]:
                            raise MaintenanceError("state_invalid")
                    ancestors.add(ancestor_id)
                    descendant = ancestor_id
                    next_id = cursor["evidence"]["predecessor_maintenance_id"]
                    cursor = self.read(next_id) if next_id is not None else None
                if any(r["evidence"]["maintenance_id"] not in ancestors for r in conflicts):
                    raise MaintenanceError("recovery_required")
                _observed(observations.lineage, evidence, parent)
            _observed(observations.current, evidence, now)
            if isinstance(observations, CheckedObservations):
                observations.checks.acquisition(evidence, config_path, state_directory, self.root)
            state = dict(schema=STATE_SCHEMA, maintenance_id=evidence["maintenance_id"],
                         evidence_digest=digest(evidence), predecessor_maintenance_id=predecessor,
                         status="acquired", last_observed_at=_stamp(now),
                         registrar_result_reference=None, baseline_handoff_reference=None,
                         release_observation_digest=None)
            self._write({"evidence": evidence, "state": state})
            return state

    def transition(self, maintenance_id: str, expected_state_digest: str, *, status: str,
                   registrar_result_reference: str | None, baseline_handoff_reference: str | None,
                   release_observation_digest: str | None, observations: Observations,
                   child_id: str | None = None, now: datetime | None = None) -> dict:
        self.check_location(observations)
        now = now or _now()
        with self.barrier(exclusive=True, create=False):
            record = self.read(maintenance_id)
            before, evidence = record["state"], record["evidence"]
            if digest(before) != expected_state_digest or status not in EDGES[before["status"]] or now < _time(before["last_observed_at"]):
                raise MaintenanceError("state_invalid")
            after = {**before, "status": status, "last_observed_at": _stamp(now),
                     "registrar_result_reference": registrar_result_reference,
                     "baseline_handoff_reference": baseline_handoff_reference,
                     "release_observation_digest": release_observation_digest}
            for key in ("registrar_result_reference", "baseline_handoff_reference"):
                if before[key] is not None and after[key] != before[key]:
                    raise MaintenanceError("state_invalid")
            validate_state(after, evidence)
            child = None
            if before["status"] == "recovery_required":
                if child_id is None:
                    raise MaintenanceError("recovery_required")
                child = self.read(child_id)
                if child["evidence"]["predecessor_maintenance_id"] != maintenance_id or child["state"]["status"] not in {"released", "cancelled"}:
                    raise MaintenanceError("recovery_required")
            elif child_id is not None:
                raise MaintenanceError("state_invalid")
            _observed(observations.transition, evidence, before, after, child)
            self._write({"evidence": evidence, "state": after})
            return after


def _fresh(evidence: dict, now: datetime) -> None:
    if now.tzinfo is None or not _time(evidence["acquired_at"]) <= now <= _time(evidence["expires_at"]):
        raise MaintenanceError("concurrency_unqualified")
    if any(_time(w["observed_at"]) > now for w in evidence["known_writers"]):
        raise MaintenanceError("concurrency_unqualified")


class MaintenanceValidator:
    validator_id = VALIDATOR_ID

    def __init__(self, store: MaintenanceStore, issuer_source_revision: str, observations: Observations):
        if not _REV.fullmatch(issuer_source_revision):
            raise MaintenanceError()
        self.store = store
        self.issuer_source_revision = issuer_source_revision
        self.observations = observations
        self._operation_depth = 0

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Hold the caller barrier across a complete registrar operation.

        State transitions/acquisitions take the exclusive side. An observation
        followed by an unprotected registrar call is deliberately not sufficient.
        This context cannot turn an unqualified D1 profile into an admitted one.
        """
        self.store.check_location(self.observations)
        with self.store.barrier(exclusive=False, create=False):
            self._operation_depth += 1
            try:
                yield
            finally:
                self._operation_depth -= 1

    def validate(self, request: Any) -> None:
        """D1 MaintenanceValidationRequest protocol; no package import or install.

        D1 validates its pinned profile and phase images; the dev observer resolves
        exact approval and all-byte eligibility. Exceptions are bounded by D1.
        """
        self.store.check_location(self.observations)
        e = request.context.maintenance_evidence.to_record()
        validate_evidence(e)
        _fresh(e, request.checked_at)
        if self._operation_depth != 1:
            raise MaintenanceError("concurrency_unqualified")
        if e["issuer_source_revision"] != self.issuer_source_revision:
            raise MaintenanceError()
        for path, key in ((request.context.config_path, "config_target_id"),
                          (request.context.state_directory, "state_target_id")):
            if path != path.resolve() or target_id(path) != e[key]:
                raise MaintenanceError("target_changed")
        if request.audience is not None and digest(request.audience.to_record()) != e["audience_digest"]:
            raise MaintenanceError("approval_invalid")
        if request.original_operation_reference is not None and request.original_operation_reference != e["recovery_of"]:
            raise MaintenanceError()
        with self.store.barrier(exclusive=False, create=False):
            record = self.store.read(e["maintenance_id"])
            if record["evidence"] != e or record["state"]["status"] != "acquired":
                raise MaintenanceError("recovery_required")
            _observed(self.observations.current, e, request.checked_at)
            _observed(self.observations.mutation, request, e)


# Independent registrar safeguards, not native control qualification. Policies
# are source-owned declarations, never supplied by an operation JSON file. There
# is deliberately no production enrollment yet. Tests replace this table locally
# with an explicit synthetic schema; they do not add a runtime enrollment API.
NONSECRET_POLICIES = MappingProxyType({})
APPROVAL_ISSUER = "dev/int014-operation-approval/v1"
MUTATION_PHASES = frozenset("prepare prepare_locked journal_prepared config_replace journal_config_replaced receipt_replace journal_verified original_journal original_terminal cancel_staging_remove journal_committed terminal_commit".split())


def _json_bytes(data: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MaintenanceError("durable_material_ineligible")
            result[key] = value
        return result
    try:
        if len(data) > 1048576:
            raise ValueError
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise MaintenanceError("durable_material_ineligible") from None


def _schema_value(value: Any, rule: dict) -> None:
    """Small closed nonsecret policy language; no arbitrary-string rule.

    Every string/key is source-declared. Unknown siblings, comments, duplicate
    keys, and unclassified scalar values refuse, even if the selected entry is
    safe. JSON whitespace carries no unclassified content. TOML needs a separate
    reviewed lexical policy and is not silently parsed as equivalent JSON.
    """
    valid = False
    if set(rule) == {"enum"}:
        valid = any(type(value) is type(item) and value == item for item in rule["enum"])
    elif set(rule) == {"boolean"} and rule["boolean"] is True:
        valid = type(value) is bool
    elif set(rule) == {"integer"}:
        low, high = rule["integer"]
        valid = type(value) is int and low <= value <= high
    elif set(rule) == {"object", "required"}:
        if isinstance(value, dict) and set(rule["required"]) <= set(value) <= set(rule["object"]):
            for key, item in value.items():
                _schema_value(item, rule["object"][key])
            valid = True
    if not valid:
        raise MaintenanceError("durable_material_ineligible")


def read_image(path: Path, *, private: bool = False) -> bytes | None:
    """Read one bounded regular image without following writable aliases."""
    if not path.is_absolute() or path != path.resolve():
        raise MaintenanceError("target_changed")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise MaintenanceError("state_invalid") from None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid() or before.st_size > 1048576
            or (private and stat.S_IMODE(before.st_mode) != 0o600)):
            raise MaintenanceError("state_invalid")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(1048577)
        after = os.fstat(fd)
        current = path.lstat()
        if (len(data) > 1048576 or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size)
            != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size)
            or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
            raise MaintenanceError("target_changed")
        return data
    finally:
        os.close(fd)


def image_digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def selected_receipt_path(context: Any) -> Path:
    # Exact D1 0.4 StateStore recipe, bound by the separate package loader.
    key = hashlib.sha256("|".join((context.target_id, context.host, context.scope,
                                  context.connection_id)).encode()).hexdigest()
    return context.state_directory / ("receipt-" + key + ".json")


class RegistrarChecks:
    """Concrete payload, phase-image and lineage checks independent of controls."""
    def __init__(self, policy_id: str):
        if policy_id not in NONSECRET_POLICIES:
            raise MaintenanceError("durable_material_ineligible")
        self.policy_id = policy_id
        self.policy_digest = digest(NONSECRET_POLICIES[policy_id])
        self.context = self.definition = None

    @property
    def policy(self) -> dict:
        try:
            result = NONSECRET_POLICIES[self.policy_id]
            if digest(result) != self.policy_digest:
                raise MaintenanceError("durable_material_ineligible")
            return result
        except KeyError:
            raise MaintenanceError("durable_material_ineligible") from None

    def bind(self, context: Any, definition: Any) -> None:
        policy = self.policy
        _closed(policy, frozenset({"context", "definitions", "config", "receipt_paths", "auth_binding_ids",
                                  "storage", "issuer_source_revision", "writers", "consequence", "guard", "actions"}))
        _closed(policy["context"], frozenset({"host", "surface", "build", "scope", "mapping_version", "mapping_digest"}))
        records = [d for d in policy["definitions"] if digest(d) == context.definition_digest]
        if len(records) != 1:
            raise MaintenanceError("durable_material_ineligible")
        source = records[0]
        # An exact inverse prepared by D1 may carry definition=None. Its context
        # must still resolve exactly one reviewed source definition here.
        if ((definition is not None and definition.to_record() != source)
            or any(getattr(context, key, None) != value for key, value in policy["context"].items())
            or context.source_owner != source["source_owner"]
            or context.connection_id != source["connection_id"]
            or context.source_revision != source["source_revision"]
            or (context.auth_binding is not None and (context.auth_binding.kind.value != "none"
                or context.auth_binding.binding_id not in policy["auth_binding_ids"]))):
            raise MaintenanceError("durable_material_ineligible")
        # These are the only currently implemented metadata classes. Expansion
        # needs a reviewed policy, not an operation-time assertion of safety.
        if context.migration_evidence is not None or context.policy_validator_id is not None:
            raise MaintenanceError("durable_material_ineligible")
        for path in (context.config_path, context.state_directory):
            if not path.is_absolute() or path != path.resolve():
                raise MaintenanceError("target_changed")
        self.context, self.definition = context, definition
        self.definition_record = source
        self.metadata(context.maintenance_evidence.to_record())

    def storage_root(self) -> Path:
        """Source-owned path grammar, not a caller-approved path digest.

        A policy names the exact canonical anchor, fixed directory/file names,
        and bounded generated temporary-name segments. It cannot bless an
        arbitrary ancestor or path taken from an operation record.
        """
        rule = self.policy["storage"]
        _closed(rule, frozenset({"anchor", "operation_prefix", "fixture_prefix", "suffix_length",
                                "config_name", "state_name", "approval_name", "maintenance_name"}))
        config, state = self.context.config_path, self.context.state_directory
        anchor = Path(rule["anchor"])
        if not anchor.is_absolute() or anchor != anchor.resolve():
            raise MaintenanceError("durable_material_ineligible")
        def generated(name, prefix):
            suffix = name.removeprefix(prefix)
            return (name.startswith(prefix) and len(suffix) == rule["suffix_length"]
                    and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in suffix))
        if (config != config.resolve() or state != state.resolve()
            or config.name != rule["config_name"] or state.name != rule["state_name"]
            or config.parent != state.parent or config.parent.parent.parent != anchor
            or not generated(config.parent.name, rule["fixture_prefix"])
            or not generated(config.parent.parent.name, rule["operation_prefix"])):
            raise MaintenanceError("durable_material_ineligible")
        return config.parent.parent

    def acquisition(self, evidence: dict, config_path: Path, state_directory: Path,
                    maintenance_root: Path) -> None:
        self.metadata(evidence)
        if (config_path != self.context.config_path or state_directory != self.context.state_directory
            or maintenance_root != self.storage_root() / self.policy["storage"]["maintenance_name"]
            or image_digest(read_image(config_path)) != evidence["config_preimage_digest"]
            or image_digest(read_image(selected_receipt_path(self.context), private=True)) != evidence["state_preimage_digest"]):
            raise MaintenanceError("durable_material_ineligible")

    def metadata(self, evidence: dict) -> None:
        """Classify every serialized context/evidence field before persistence.

        Free text comes only from closed source declarations. Dynamic values
        are typed UUIDs/timestamps or recomputed bindings, never a caller's
        assertion that a matching hash makes arbitrary text nonsecret.
        """
        policy, context = self.policy, self.context
        self.storage_root()
        validate_evidence(evidence)
        if context.maintenance_evidence.to_record() != evidence:
            raise MaintenanceError("durable_material_ineligible")
        if (evidence["issuer_source_revision"] != policy["issuer_source_revision"]
            or evidence["consequence_review_digest"] != digest(policy["consequence"])
            or {k: evidence[k] for k in ("prior_guard_state", "prior_guard_lock")} != policy["guard"]):
            raise MaintenanceError("durable_material_ineligible")
        expected_writers = []
        if len(evidence["known_writers"]) != len(policy["writers"]):
            raise MaintenanceError("durable_material_ineligible")
        for row, declared in zip(evidence["known_writers"], policy["writers"]):
            _closed(declared, (WRITER_FIELDS - {"observation_digest", "observed_at"}) | {"observation"})
            expected_writers.append({**{k: v for k, v in declared.items() if k != "observation"},
                                     "observation_digest": digest(declared["observation"]),
                                     "observed_at": _stamp(_time(row["observed_at"]))})
        if evidence["known_writers"] != expected_writers:
            raise MaintenanceError("durable_material_ineligible")
        for key in ("acquired_at", "expires_at"):
            if evidence[key] != _stamp(_time(evidence[key])):
                raise MaintenanceError("durable_material_ineligible")
        audiences = [digest(dict(source_owner=context.source_owner, connection_id=context.connection_id,
                                 host=context.host, scope=context.scope, target_id=context.target_id, action=action))
                     for action in policy["actions"]]
        if (evidence["audience_digest"] not in audiences
            or evidence["config_target_id"] != context.target_id
            or evidence["state_target_id"] != target_id(context.state_directory)):
            raise MaintenanceError("durable_material_ineligible")
        qualification = "kp-mcp/coordinated-maintenance/v1"
        window = dict(schema="kp-mcp/writer-window/v2", qualification_id=qualification,
                      qualification_digest=digest(dict(id=qualification, validator_id=VALIDATOR_ID,
                          accepted_contract_digest=CONTRACT_DIGEST, mechanism="coordinated-maintenance",
                          concurrency_claim="coordinated")),
                      issuer_owner="KleinPerkins/dev", issuer_source_revision=policy["issuer_source_revision"],
                      mechanism="coordinated-maintenance", host=context.host, surface=context.surface,
                      build=context.build, mapping_digest=context.mapping_digest, config_target_id=context.target_id,
                      state_target_id=target_id(context.state_directory), acquisition_reference=evidence["maintenance_id"],
                      acquired_at=evidence["acquired_at"], expires_at=evidence["expires_at"],
                      release_method="dev-int014-explicit-handoff/v1", concurrency_claim="coordinated",
                      maintenance_evidence_digest=digest(evidence))
        auth = None
        if context.auth_binding is not None:
            auth = dict(schema="kp-mcp/auth-binding/v1", binding_id=context.auth_binding.binding_id,
                        kind="none", host=context.host, surface=context.surface, scope=context.scope,
                        target_origin_digest=self.definition.target_origin_digest if self.definition else
                            digest({"transport": self.definition_record["transport"]["kind"],
                                    "command": self.definition_record["transport"]["command"]}),
                        account_reference=None, grant_reference=None, allowed_native_fields=[], environment_variable=None)
        expected = dict(schema="kp-mcp/registration-context/v2", **policy["context"],
                        source_owner=self.definition_record["source_owner"],
                        connection_id=self.definition_record["connection_id"],
                        source_revision=self.definition_record["source_revision"],
                        definition_digest=digest(self.definition_record), config_path=str(context.config_path),
                        state_directory=str(context.state_directory), auth_binding=auth,
                        writer_window=window, migration_evidence=None, policy_validator_id=None,
                        maintenance_evidence=evidence, concurrency_claim="coordinated",
                        writer_window_digest=digest(window), maintenance_evidence_digest=digest(evidence))
        actual = context.to_record()
        # D1's in-memory window carries datetime objects; its canonical durable
        # encoding uses these exact UTC strings. Normalize only these two slots.
        if isinstance(actual.get("writer_window"), dict):
            actual["writer_window"] = dict(actual["writer_window"])
            for key in ("acquired_at", "expires_at"):
                value = actual["writer_window"].get(key)
                if isinstance(value, datetime):
                    actual["writer_window"][key] = _stamp(value)
        if actual != expected:
            raise MaintenanceError("durable_material_ineligible")

    def config(self, data: bytes | None) -> None:
        if data is not None:
            _schema_value(_json_bytes(data), self.policy["config"])

    def receipt(self, data: bytes | None) -> None:
        if data is None:
            return
        row = _json_bytes(data)
        _closed(row, frozenset("schema receipt_id adapter_version mapping_digest source_owner connection_id source_revision definition_digest native_name host scope target_id operation_id verified_postimage source_projection auth_projection previous_receipt_digest".split()))
        context = self.context
        expected = dict(schema="kp-mcp/registrar-receipt/v1", adapter_version="kp-mcp/adapter/v1",
                        mapping_digest=context.mapping_digest, source_owner=context.source_owner,
                        connection_id=context.connection_id, host=context.host, scope=context.scope,
                        target_id=context.target_id, native_name=self.definition_record["native_name"])
        if any(row[key] != value for key, value in expected.items()):
            raise MaintenanceError("durable_material_ineligible")
        # Historical receipts may name an older reviewed source definition.
        if not any(row["source_revision"] == d["source_revision"] and row["definition_digest"] == digest(d)
                   for d in self.policy["definitions"]):
            raise MaintenanceError("durable_material_ineligible")
        _uuid(row["operation_id"])
        if row["receipt_id"] != row["operation_id"]:
            raise MaintenanceError("state_invalid")
        for key in ("verified_postimage", "previous_receipt_digest"):
            if row[key] != "absent":
                _hex(row[key])
        source, auth = row["source_projection"], row["auth_projection"]
        _closed(source, frozenset({"owner", "paths"}))
        _closed(auth, frozenset({"owner", "binding_digest", "paths"}))
        if (source["owner"] != context.source_owner or not isinstance(source["paths"], dict)
            or not set(source["paths"]) <= set(self.policy["receipt_paths"])
            or auth != {"owner": context.auth_binding.binding_id if context.auth_binding else "not_applicable",
                        "binding_digest": context.auth_binding.digest if context.auth_binding else "not_applicable", "paths": {}}):
            raise MaintenanceError("durable_material_ineligible")
        for value in source["paths"].values():
            _hex(value)

    def mutation(self, request: Any, evidence: dict) -> None:
        if self.context is None or request.context != self.context:
            raise MaintenanceError("target_changed")
        self.metadata(evidence)
        if request.phase not in MUTATION_PHASES | {"admission", "inspection", "approval"}:
            raise MaintenanceError("concurrency_unqualified")
        if request.phase in MUTATION_PHASES:
            if (len(request.durable_material) != 4 or request.expected_config_digest is None
                or request.expected_state_digest is None):
                raise MaintenanceError("state_invalid")
            self.config(request.durable_material[0])
            self.config(request.durable_material[1])
            self.receipt(request.durable_material[2])
            self.receipt(request.durable_material[3])
        elif request.durable_material:
            raise MaintenanceError("state_invalid")
        # Check the phase supplied by D1, never stale acquisition preimages after
        # D1's own writes. Compare the selected receipt, not its whole directory.
        for path, expected, private in ((self.context.config_path, request.expected_config_digest, False),
                                        (selected_receipt_path(self.context), request.expected_state_digest, True)):
            if expected is not None and image_digest(read_image(path, private=private)) != expected:
                raise MaintenanceError("target_changed")

    def original_reference(self, operation_id: str) -> dict:
        """Read the pinned D1 original-authority snapshot; no guessed latest file.

        D1 subsequently validates its full journal/terminal semantics on public
        load/recover/rollback calls. This snapshot alone authorizes no mutation.
        """
        _uuid(operation_id)
        root = self.context.state_directory
        prepared = read_image(root / ("prepared-" + operation_id + ".json"), private=True)
        if prepared is None:
            raise MaintenanceError("recovery_required")
        row = _json_bytes(prepared)
        original_context = row.get("context", {})
        if (row.get("schema") != "kp-mcp/prepared-record/v2" or row.get("operation_id") != operation_id
            or row.get("payload_digest") != digest({k: v for k, v in row.items() if k != "payload_digest"})
            or canonical(row) != prepared
            or row.get("preview", {}).get("target_id") != self.context.target_id
            or original_context.get("config_path") != str(self.context.config_path)
            or original_context.get("state_directory") != str(root)
            or any(original_context.get(key) != getattr(self.context, key)
                   for key in ("source_owner", "connection_id", "source_revision", "definition_digest",
                               "host", "surface", "scope", "build", "mapping_version", "mapping_digest"))):
            raise MaintenanceError("target_changed")
        journal = read_image(root / ("journal-" + operation_id + ".json"), private=True)
        terminal = read_image(root / ("terminal-" + operation_id + ".json"), private=True)
        j = _json_bytes(journal) if journal is not None else None
        snapshot = dict(original_operation_id=operation_id, target_id=self.context.target_id,
                        prepared_digest=image_digest(prepared), journal_digest=image_digest(journal),
                        terminal_digest=image_digest(terminal), journal_phase=j["phase"] if j else None)
        return {"reference": digest(snapshot), "snapshot": snapshot,
                "evidence": original_context["maintenance_evidence"],
                "maintenance_id": original_context["maintenance_evidence"]["maintenance_id"]}

    def lineage(self, evidence: dict, parent: dict, operation_id: str) -> None:
        original = self.original_reference(operation_id)
        if (original["reference"] != evidence["recovery_of"]
            or original["maintenance_id"] != evidence["predecessor_maintenance_id"]
            or original["evidence"] != parent["evidence"]
            or parent["evidence"]["maintenance_id"] != original["maintenance_id"]
            or parent["state"]["status"] != "recovery_required"):
            raise MaintenanceError("recovery_required")


def _write_once(root: Path, name: str, record: dict) -> None:
    _safe_root(root, create=True)
    fd, temporary = tempfile.mkstemp(prefix=".approval-", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, root / name)  # Never replace another approval.
    finally:
        Path(temporary).unlink(missing_ok=True)
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class OperationApprovals:
    """Exact private approval transport, not proof of human presence.

    The calling UI must obtain the displayed proposal's explicit decision. This
    class neither asks on its behalf nor infers consent from a digest or bool.
    It stores only the closed operation-bound decision and the owner Approval.
    """
    def __init__(self, root: Path, api: Any, checks: RegistrarChecks):
        self.root, self.api, self.checks = root, api, checks

    def proposal(self, prepared: Any) -> dict:
        self.checks.bind(prepared._context, prepared._definition)
        if self.root != self.checks.storage_root() / self.checks.policy["storage"]["approval_name"]:
            raise MaintenanceError("durable_material_ineligible")
        e = prepared._context.maintenance_evidence.to_record()
        return dict(schema="dev/int014-operation-decision/v1", decision="approve-coordinated-maintenance",
                    operation_id=prepared.operation_id, action_digest=prepared.action_digest,
                    prepared_payload_digest=prepared.payload_digest, audience=prepared.audience.to_record(),
                    maintenance_id=e["maintenance_id"], maintenance_evidence_digest=digest(e),
                    consequence_review_digest=e["consequence_review_digest"],
                    expires_at=_stamp(prepared.expires_at))

    def accept(self, prepared: Any, confirmation: dict, *, now: datetime | None = None) -> Any:
        expected = self.proposal(prepared)
        if type(confirmation) is not dict or confirmation != expected:
            raise MaintenanceError("approval_invalid")
        e = prepared._context.maintenance_evidence.to_record()
        now = now or _now()
        _fresh(e, now)
        if now > prepared.expires_at:
            raise MaintenanceError("approval_invalid")
        _uuid(prepared.operation_id)
        name = prepared.operation_id + ".json"
        _safe_root(self.root, create=True)
        if (self.root / name).exists():
            return self.load(prepared)
        approval = self.api.Approval(prepared.audience, prepared.operation_id, prepared.action_digest,
                                    prepared.payload_digest, APPROVAL_ISSUER, e["maintenance_id"],
                                    now, prepared.expires_at)
        _write_once(self.root, name, {"decision": expected, "approval": approval.to_dict()})
        return approval

    def load(self, prepared: Any) -> Any:
        expected = self.proposal(prepared)
        _uuid(prepared.operation_id)
        _safe_root(self.root, create=False)
        record = _load(self.root / (prepared.operation_id + ".json"))
        _closed(record, frozenset({"decision", "approval"}))
        if record["decision"] != expected:
            raise MaintenanceError("approval_invalid")
        a = record["approval"]
        approval = self.api.Approval(prepared.audience, prepared.operation_id, prepared.action_digest,
                                    prepared.payload_digest, APPROVAL_ISSUER,
                                    prepared._context.maintenance_evidence.maintenance_id,
                                    _time(a["issued_at"]), prepared.expires_at)
        if approval.to_dict() != a:
            raise MaintenanceError("approval_invalid")
        return approval

    def validate(self, request: Any, evidence: dict) -> None:
        self.checks.metadata(evidence)
        if self.root != self.checks.storage_root() / self.checks.policy["storage"]["approval_name"]:
            raise MaintenanceError("durable_material_ineligible")
        if request.approval is None:
            return
        _uuid(request.operation_id)
        _safe_root(self.root, create=False)
        record = _load(self.root / (request.operation_id + ".json"))
        _closed(record, frozenset({"decision", "approval"}))
        a, decision = request.approval.to_dict(), record["decision"]
        expected = dict(schema="dev/int014-operation-decision/v1", decision="approve-coordinated-maintenance",
                        operation_id=request.operation_id, action_digest=request.action_digest,
                        prepared_payload_digest=request.prepared_payload_digest,
                        audience=request.audience.to_record(), maintenance_id=evidence["maintenance_id"],
                        maintenance_evidence_digest=digest(evidence),
                        consequence_review_digest=evidence["consequence_review_digest"], expires_at=a["expires_at"])
        if (record["approval"] != a or decision != expected or a["issuer_authority"] != APPROVAL_ISSUER
            or a["issuer_reference"] != evidence["maintenance_id"] or a["choice"] != "apply"
            or not _time(a["issued_at"]) <= request.checked_at <= _time(a["expires_at"])):
            raise MaintenanceError("approval_invalid")


class CheckedObservations:
    """Compose independent checks with the still-required control resolver.

    This does not implement or qualify native controls. Synthetic tests supply
    their own observations; no source-shipped control provider currently exists.
    """
    def __init__(self, checks: RegistrarChecks, approvals: OperationApprovals,
                 controls: Observations, *, original_operation_id: str | None = None):
        self.checks, self.approvals, self.controls = checks, approvals, controls
        self.original_operation_id = original_operation_id

    def current(self, evidence: dict, now: datetime) -> None:
        self.checks.metadata(evidence)
        _observed(self.controls.current, evidence, now)

    def mutation(self, request: Any, evidence: dict) -> None:
        self.checks.mutation(request, evidence)
        self.approvals.validate(request, evidence)

    def lineage(self, evidence: dict, parent: dict) -> None:
        if self.original_operation_id is None:
            raise MaintenanceError("recovery_required")
        self.checks.lineage(evidence, parent, self.original_operation_id)

    def transition(self, evidence: dict, before: dict, after: dict, child: dict | None) -> None:
        self.checks.metadata(evidence)
        _observed(self.controls.transition, evidence, before, after, child)


def default_store() -> MaintenanceStore:
    # Not an environment-selectable bypass. Synthetic subprocesses use temp HOME.
    # Canonicalize the home anchor (macOS /var -> /private/var is common in
    # disposable homes); reject symlinks below it in _safe_root.
    return MaintenanceStore(Path.home().resolve() / ".local/state/dev/mcp-maintenance")


def refuse_legacy(store: MaintenanceStore, targets: list[Path]) -> None:
    rows = store.records()
    # The initial caller profile only admits canonical targets. Ambiguous alias
    # changes cannot route an old writer around a retained handoff record.
    if rows:
        for path in targets:
            if not path.is_absolute() or path != path.resolve():
                raise MaintenanceError("target_changed")
            if path.exists() and path.stat().st_nlink != 1:
                raise MaintenanceError("target_changed")
    wanted = {target_id(p) for p in targets}
    for row in rows:
        if row["evidence"]["config_target_id"] in wanted and row["state"]["status"] != "cancelled":
            # Includes expired, recovery, failed and successfully adopted targets.
            raise MaintenanceError("legacy_writer_suspended")


def _targets(entry: str) -> list[Path]:
    home = Path.home().resolve()
    defaults = [home / ".cursor/mcp.json", home / ".codex/config.toml", home / ".claude.json"]
    if entry == "snow":
        # Kit bootstrap/unregister use default_platform_paths(); direct legacy
        # deletion/profile paths honor overrides. Guard the union of both effects.
        overrides = [Path(os.environ.get(name, str(default))) for name, default in zip(
            ("SNOW_KIT_CURSOR_CONFIG", "SNOW_KIT_CODEX_CONFIG", "SNOW_KIT_CLAUDE_CONFIG"), defaults)]
        return list(dict.fromkeys(defaults + overrides))
    return defaults


def _inherited(store: MaintenanceStore) -> int | None:
    raw = os.environ.get(_FD_ENV)
    if raw is None:
        return None
    try:
        fd = int(raw)
        actual = os.fstat(fd)
        expected = _private(store.root / "writers.lock", directory=False)
        if fd < 3 or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError
        # Reestablish the cooperative shared lock even if the inherited fd was
        # malformed; never treat an environment variable as proof of ownership.
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return fd
    except (OSError, ValueError):
        raise MaintenanceError("state_invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("legacy-enter",))
    parser.add_argument("entry", choices=("mirror", "snow"))
    parser.add_argument("script", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        store = default_store()
        inherited = _inherited(store)
        if inherited is not None:
            refuse_legacy(store, _targets(args.entry))
            # Shell's guarded second entry continues under the supervising lock.
            return 0
        with store.barrier(exclusive=False) as fd:
            refuse_legacy(store, _targets(args.entry))
            env = dict(os.environ, **{_FD_ENV: str(fd)})
            result = subprocess.run(["/bin/bash", str(args.script), *args.arguments],
                                    env=env, pass_fds=(fd,), check=False)
            return result.returncode
    except (MaintenanceError, OSError, ValueError, TypeError, KeyError):
        print("mcp-maintenance: legacy writer refused; explicit handoff/recovery required", file=sys.stderr)
        return HANDOFF_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
