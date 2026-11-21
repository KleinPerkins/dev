"""Pinned Save-Game observations and closed authoring continuity pointers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .artifact_authority import resolve_approved_artifact
from .artifact_discovery import artifact_paths
from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .dependencies import assert_plan_assumptions_current
from .validators import parse_validated_artifact, read_repository_config, require_valid


POINTER_FIELDS = {
    "schema",
    "checkpoint_id",
    "checkpoint_digest",
    "status",
    "artifact_ids",
    "next_action_code",
    "blocker_ids",
    "authority_pointers",
}
NEXT_ACTIONS = {
    "author",
    "review",
    "validate",
    "reconcile",
    "wait",
    "complete",
}
EVENT_FIELDS = {
    "operation_id",
    "artifact_ids",
    "next_action_code",
    "blocker_ids",
    "authority_pointers",
}
SAVE_GAME_PIN = Path(__file__).resolve().parents[2] / "runtime/save-game-pin.json"
HEX_DIGEST = re.compile(r"[a-f0-9]{64}")
SHA256 = re.compile(r"sha256:[a-f0-9]{64}")
CHECKPOINT_ID = re.compile(r"chk-[a-zA-Z0-9_.-]{1,100}")
UUID = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
ARTIFACT_ID = re.compile(rf"(?:PROJECT|PRD|SPEC|UXR|DESIGN|ASSET|PROTO|SKETCH|SPIKE|ADR|PLAN|VER|UAT|REL|DEF)-{UUID}-{UUID}")
BLOCKER_ID = re.compile(rf"(?:BLK-{UUID}|DEF-{UUID}-{UUID})")
AUTHORITY_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.md")
OBSERVATION_SCHEMA = "save-game-reconcile-observation/v1"
OBSERVATION_SCOPE = ("repo_key", "clone_key", "workstream_key")
OBSERVATION_FAILURES = {
    "UNADOPTED": "save_game_unadopted", "ADOPTION_DISABLED": "save_game_adoption_disabled",
    "WORKSTREAM_UNAVAILABLE": "save_game_workstream_unavailable", "LOCK_BUSY": "save_game_workstream_busy",
    "INCOMPLETE_TRANSACTION": "save_game_owner_recovery_required", "INVALID_EVIDENCE": "save_game_invalid_evidence",
    "IDENTITY_MISMATCH": "save_game_identity_mismatch", "LIVE_STATE_CHANGED": "save_game_live_state_changed",
    "GIT_CONFLICT": "save_game_live_conflict", "CHECKPOINT_AMBIGUOUS": "save_game_checkpoint_ambiguous",
    "CHECKPOINT_STALE": "save_game_checkpoint_stale", "CHECKPOINT_UNADOPTED": "save_game_checkpoint_unadopted",
}
FLUSH_FAILURES = {
    "SAVED_PRIVATE_UNADOPTED": "save_game_saved_private_unadopted",
    "PRIVACY_BLOCK": "save_game_privacy_blocked", "AUTHORITY_CONFLICT": "save_game_live_conflict",
    "LOCK_BUSY": "save_game_workstream_busy", "RECOVERY_REQUIRED": "save_game_owner_recovery_required",
    "RECOVERY_CONFLICT": "save_game_owner_recovery_conflict", "RECOVERY_BLOCKED": "save_game_owner_recovery_blocked",
    "UNSUPPORTED_ENVIRONMENT": "save_game_unavailable",
}
FLUSH_FIELDS = {"schema", "receipt_id", "workstream_key", "created_at", "status", "saved", "omitted", "refused",
                "stale", "reconciliation_required", "negative_claims"}


def _owner_files(skill: Path) -> dict[str, str]:
    names = ["scripts/save-game.sh"]
    for folder, pattern in (("engine", "*.py"), ("engine/schemas", "*.schema.json")):
        directory = contained_path(skill, f"{folder}/.probe").parent
        names.extend(path.relative_to(skill).as_posix() for path in directory.glob(pattern))
    return {name: digest_ref(contained_path(skill, name).read_bytes()) for name in sorted(names)}


def owner_checkpoint_digest(checkpoint: dict[str, Any]) -> str:
    """The owner hashes compact, ASCII-escaped JSON without a trailing newline."""
    return digest_ref(json.dumps(checkpoint, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))


@dataclass(frozen=True)
class CheckpointEvent:
    operation_id: str
    artifact_ids: tuple[str, ...]
    next_action_code: str
    blocker_ids: tuple[str, ...] = ()
    authority_pointers: tuple[str, ...] = ()


class SaveGameAdapter:
    def __init__(
        self,
        *,
        home: Path | None = None,
        root: Path | None = None,
        runner: Callable[[str, CheckpointEvent], dict[str, Any]] | None = None,
    ):
        self.home = (home or Path.home()).resolve()
        self.root = (root or Path.cwd()).resolve()
        self.runner = runner

    def executable(self) -> Path | None:
        if not SAVE_GAME_PIN.is_file():
            return None
        raw = SAVE_GAME_PIN.read_bytes()
        pin = parse_json_object(raw)
        if (raw != canonical_json(pin)
                or set(pin) != {"schema", "repository_id", "revision", "files"}
                or pin["schema"] != "doc-warden/save-game-source-pin/v1"
                or pin["repository_id"] != 1461925043
                or re.fullmatch(r"[0-9a-f]{40}", str(pin["revision"])) is None
                or not isinstance(pin["files"], dict)):
            raise ValueError("save_game_unqualified")
        candidates = (
            self.home / ".codex/skills/save-game/scripts/save-game.sh",
            self.home / ".cursor/skills/save-game/scripts/save-game.sh",
            self.home / ".claude/skills/save-game/scripts/save-game.sh",
        )
        for candidate in candidates:
            if candidate.is_file():
                skill = candidate.parent.parent.resolve(strict=True)
                if _owner_files(skill) == pin["files"]:
                    return contained_path(skill, "scripts/save-game.sh")
        if any(path.is_file() for path in candidates):
            raise ValueError("save_game_unqualified")
        return None

    def available(self) -> bool:
        return self.runner is not None or self.executable() is not None

    @staticmethod
    def _command(prefix: list[str], *args: str) -> tuple[int, dict[str, Any]]:
        try:
            completed = subprocess.run([*prefix, *args], capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("save_game_timeout") from exc
        except OSError as exc:
            raise ValueError("save_game_invocation_failed") from exc
        if len(completed.stdout) > 65536:
            raise ValueError("save_game_invalid_evidence")
        try:
            return completed.returncode, parse_json_object(completed.stdout)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("save_game_invalid_evidence") from exc

    def _observe(self, prefix: list[str], task_id: str, registration: dict[str, Any], *, allow_empty=False):
        code, reply = self._command(prefix, "reconcile", "--task-id", task_id, "--observe")
        if reply.get("schema") != OBSERVATION_SCHEMA:
            raise ValueError("save_game_observation_unavailable")
        status = reply.get("status")
        scope_fields = {"schema", "status", *OBSERVATION_SCOPE}
        if (not isinstance(status, str) or set(reply) != scope_fields | ({"checkpoint"} if status == "MATCH" else set())
                or any(not isinstance(reply[key], str) or HEX_DIGEST.fullmatch(reply[key]) is None
                       for key in OBSERVATION_SCOPE)):
            raise ValueError("save_game_invalid_evidence")
        if any(reply[key] != registration[key] for key in ("repo_key", "clone_key")):
            raise ValueError("save_game_identity_mismatch")
        if status != "MATCH":
            if code != 1:
                raise ValueError("save_game_invalid_evidence")
            if allow_empty and status == "WORKSTREAM_UNAVAILABLE":
                return reply
            raise ValueError(OBSERVATION_FAILURES.get(status, "save_game_invalid_evidence"))
        checkpoint = reply["checkpoint"]
        if (code != 0 or not isinstance(checkpoint, dict) or set(checkpoint) != {"id", "digest", "generation"}
                or not isinstance(checkpoint["id"], str) or CHECKPOINT_ID.fullmatch(checkpoint["id"]) is None
                or not isinstance(checkpoint["digest"], str) or SHA256.fullmatch(checkpoint["digest"]) is None
                or type(checkpoint["generation"]) is not int or checkpoint["generation"] < 1):
            raise ValueError("save_game_invalid_evidence")
        return reply

    def _registration(self, prefix: list[str]) -> dict[str, Any]:
        code, status = self._command(prefix, "adopt", "--preview")
        if (code != 0 or set(status) != {"repo_key", "clone_key", "adopted", "case", "registration"}
                or any(not isinstance(status[key], str) or HEX_DIGEST.fullmatch(status[key]) is None
                       for key in ("repo_key", "clone_key"))):
            raise ValueError("save_game_invalid_evidence")
        if status["adopted"] is False and status["case"] == "unconfigured" and status["registration"] is None:
            raise ValueError("save_game_unadopted")
        record = status["registration"]
        if (status["adopted"] is not True or status["case"] != "configured" or not isinstance(record, dict)
                or record.get("schema") != "save-game-registration/v1" or type(record.get("enabled")) is not bool
                or any(record.get(key) != status[key] for key in ("repo_key", "clone_key"))):
            raise ValueError("save_game_invalid_evidence")
        if not record["enabled"]:
            raise ValueError("save_game_adoption_disabled")
        return status

    def _index(self, prefix: list[str], task_id: str, observation: dict[str, Any]):
        code, indexed = self._command(prefix, "index", "--task-id", task_id)
        pointer = observation.get("checkpoint")
        if pointer is None and code == 1 and indexed == {"status": "NO_CHECKPOINT"}:
            return None
        if code == 1 and indexed.get("status") == "CHECKPOINT_AMBIGUOUS":
            raise ValueError("save_game_checkpoint_ambiguous")
        if (code != 0 or pointer is None or indexed.get("schema") != "save-game-checkpoint/v1"
                or not isinstance(indexed.get("active_state_digest"), str)
                or HEX_DIGEST.fullmatch(indexed["active_state_digest"]) is None):
            raise ValueError("save_game_checkpoint_unavailable")
        if indexed.get("workstream_key") != observation["workstream_key"]:
            raise ValueError("save_game_identity_mismatch")
        if (indexed.get("checkpoint_id") != pointer["id"]
                or indexed.get("active_state_generation") != pointer["generation"]
                or owner_checkpoint_digest(indexed) != pointer["digest"]):
            raise ValueError("save_game_checkpoint_stale")
        return indexed

    @staticmethod
    def _pointer(event: CheckpointEvent, checkpoint: dict[str, Any], status: str) -> dict[str, Any]:
        return {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": checkpoint["id"],
            "checkpoint_digest": checkpoint["digest"],
            "status": status,
            "artifact_ids": list(event.artifact_ids),
            "next_action_code": event.next_action_code,
            "blocker_ids": list(event.blocker_ids),
            "authority_pointers": list(event.authority_pointers),
        }

    def _invoke(self, verb: str, event: CheckpointEvent, request_digest: str) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            raise ValueError("save_game_unavailable")
        task_seed = canonical_json({"authoring_operation": event.operation_id, "checkpoint_request": request_digest})
        task_id = "doc-warden-" + hashlib.sha256(task_seed).hexdigest()
        prefix = [str(executable), "--root", str(self.root)]
        registration = self._registration(prefix)
        initial = self._observe(prefix, task_id, registration, allow_empty=(verb == "checkpoint"))
        initial_index = self._index(prefix, task_id, initial)
        if verb == "reconcile":
            if self._observe(prefix, task_id, registration) != initial or self._registration(prefix) != registration:
                raise ValueError("save_game_live_state_changed")
            return self._pointer(event, initial["checkpoint"], "reconciled")
        code, receipt = self._command(
            prefix, "flush", "--task-id", task_id, "--client-id", "unknown",
            "--objective", "Doc-Warden authoring continuity", "--next-action", event.next_action_code,
            "--expected-digest", initial_index["active_state_digest"] if initial_index is not None else "none",
        )
        status = receipt.get("status")
        if (set(receipt) not in (FLUSH_FIELDS, FLUSH_FIELDS | {"checkpoint_id"})
                or receipt.get("schema") != "save-game-flush-receipt/v1" or not isinstance(status, str)
                or not isinstance(receipt.get("receipt_id"), str)
                or re.fullmatch(r"rcpt-[a-zA-Z0-9_.-]{1,100}", receipt["receipt_id"]) is None
                or type(receipt.get("reconciliation_required")) is not bool):
            raise ValueError("save_game_invalid_evidence")
        if receipt.get("workstream_key") != initial["workstream_key"]:
            raise ValueError("save_game_identity_mismatch")
        if status not in {"SAVED", "NO_DURABLE_DELTA"}:
            raise ValueError(FLUSH_FAILURES.get(status, "save_game_invocation_failed"))
        if code != 0 or receipt["reconciliation_required"]:
            raise ValueError("save_game_live_state_changed")
        observed = self._observe(prefix, task_id, registration)
        self._index(prefix, task_id, observed)
        if any(initial[key] != observed[key] for key in OBSERVATION_SCOPE):
            raise ValueError("save_game_identity_mismatch")
        pointer = observed["checkpoint"]
        if ((status == "SAVED" and receipt.get("checkpoint_id") != pointer["id"])
                or (status == "NO_DURABLE_DELTA" and initial.get("checkpoint") != pointer)):
            raise ValueError("save_game_checkpoint_stale")
        if (self._observe(prefix, task_id, registration) != observed
                or self._registration(prefix) != registration or self.executable() != executable):
            raise ValueError("save_game_live_state_changed")
        return self._pointer(event, pointer, "created")

    def _run(self, verb: str, event: CheckpointEvent, request_digest: str) -> dict[str, Any]:
        validate_event(event)
        if self.runner is not None:
            pointer = self.runner(verb, event)
        else:
            pointer = self._invoke(verb, event, request_digest)
        pointer = validate_pointer(pointer)
        expected = self._pointer(event, {"id": pointer["checkpoint_id"], "digest": pointer["checkpoint_digest"]},
                                 pointer["status"])
        if pointer != expected:
            raise ValueError("save_game_pointer_identity_mismatch")
        if pointer["status"] not in ({"created", "updated"} if verb == "checkpoint" else {"reconciled"}):
            raise ValueError("save_game_unavailable")
        return pointer

    def checkpoint(self, event: CheckpointEvent, *, request_digest: str) -> dict[str, Any]:
        if not isinstance(request_digest, str) or SHA256.fullmatch(request_digest) is None:
            raise ValueError("save_game_request_digest")
        return self._run("checkpoint", event, request_digest)

    def reconcile(self, event: CheckpointEvent, *, request_digest: str) -> dict[str, Any]:
        if not isinstance(request_digest, str) or SHA256.fullmatch(request_digest) is None:
            raise ValueError("save_game_request_digest")
        return self._run("reconcile", event, request_digest)


def validate_pointer(pointer: object) -> dict[str, Any]:
    if not isinstance(pointer, dict) or set(pointer) != POINTER_FIELDS:
        raise ValueError("save_game_pointer_not_closed")
    if pointer.get("schema") != "doc-warden/save-game-pointer/v1":
        raise ValueError("save_game_pointer_schema")
    if pointer.get("status") not in {"created", "updated", "reconciled", "unavailable"}:
        raise ValueError("save_game_pointer_status")
    if pointer.get("next_action_code") not in NEXT_ACTIONS:
        raise ValueError("save_game_pointer_next_action")
    if not isinstance(pointer["checkpoint_id"], str) or (
        CHECKPOINT_ID.fullmatch(pointer["checkpoint_id"]) is None
        and not (pointer["checkpoint_id"] == "unavailable" and pointer["status"] == "unavailable")
    ):
        raise ValueError("save_game_pointer_id")
    if not isinstance(pointer["checkpoint_digest"], str) or SHA256.fullmatch(pointer["checkpoint_digest"]) is None:
        raise ValueError("save_game_pointer_digest")
    if (pointer["checkpoint_digest"] == "sha256:" + "0" * 64) != (pointer["status"] == "unavailable"):
        raise ValueError("save_game_pointer_digest")
    _validate_references(pointer)
    return pointer


def _validate_references(fields: dict[str, Any]) -> None:
    patterns = {"artifact_ids": ARTIFACT_ID, "blocker_ids": BLOCKER_ID, "authority_pointers": AUTHORITY_PATH}
    for field in ("artifact_ids", "blocker_ids", "authority_pointers"):
        values = fields[field]
        if not isinstance(values, (list, tuple)) or len(values) > 100:
            raise ValueError("save_game_pointer_list")
        if any(not isinstance(value, str) or len(value) > 256 or patterns[field].fullmatch(value) is None
               for value in values) or len(set(values)) != len(values):
            raise ValueError("save_game_pointer_value")
        if field == "authority_pointers" and any(part in {".", ".."} for value in values for part in value.split("/")):
            raise ValueError("authoring_authority_path_invalid")


def validate_event(event: CheckpointEvent) -> None:
    try:
        if str(uuid.UUID(event.operation_id)) != event.operation_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("save_game_event_operation") from exc
    if event.next_action_code not in NEXT_ACTIONS:
        raise ValueError("save_game_pointer_next_action")
    _validate_references({"artifact_ids": event.artifact_ids, "blocker_ids": event.blocker_ids,
                          "authority_pointers": event.authority_pointers})


def event_from_envelope(raw: dict[str, Any]) -> CheckpointEvent:
    if set(raw) != EVENT_FIELDS or any(
        not isinstance(raw[field], list)
        for field in ("artifact_ids", "blocker_ids", "authority_pointers")
    ):
        raise ValueError("save_game_event_contract_invalid")
    event = CheckpointEvent(
        operation_id=raw["operation_id"],
        artifact_ids=tuple(raw["artifact_ids"]),
        next_action_code=raw["next_action_code"],
        blocker_ids=tuple(raw["blocker_ids"]),
        authority_pointers=tuple(raw["authority_pointers"]),
    )
    validate_event(event)
    return event


def _git_read(repo: Path, *arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "--no-optional-locks", "-C", str(repo), *arguments],
            stderr=subprocess.DEVNULL, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("authoring_git_unavailable") from exc


def _working_inputs(repo: Path) -> dict[str, str]:
    untracked = {}
    for raw in _git_read(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        candidate = repo / relative
        if candidate.is_symlink():
            contained_path(repo, str(Path(relative).with_name(".symlink-probe")))
            untracked[relative] = digest_ref(str(candidate.readlink()).encode())
        else:
            with contained_path(repo, relative).open("rb") as stream:
                untracked[relative] = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    return untracked


def live_binding(repo: Path, authoring_state: dict[str, Any], event: CheckpointEvent) -> str:
    """Observe local authority before invoking the independently owned adapter."""
    require_valid("authoring-state", authoring_state)
    validate_event(event)
    if authoring_state["save_game_pointer"] is not None:
        validate_pointer(authoring_state["save_game_pointer"])
    _validate_references({"artifact_ids": (), "blocker_ids": authoring_state["blocker_ids"],
                          "authority_pointers": ()})
    root = repo.resolve(strict=True)
    config = read_repository_config(root)
    if (config is None or not config["enabled"] or config["repository_key"] != authoring_state["repository_key"]
            or Path(_git_read(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root):
        raise ValueError("authoring_repository_mismatch")
    if event.operation_id != authoring_state["operation_id"]:
        raise ValueError("save_game_event_operation")
    git_dir = Path(_git_read(root, "rev-parse", "--absolute-git-dir").decode().strip())
    if any((git_dir / marker).exists() for marker in (
        "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply", "sequencer",
    )) or _git_read(root, "ls-files", "--unmerged"):
        raise ValueError("authoring_git_conflict")
    head = _git_read(root, "rev-parse", "HEAD").decode().strip()
    if authoring_state["source_revision"] != head:
        raise ValueError("authoring_source_revision_changed")
    paths = {
        ".planning/doc-warden.json": contained_path(root, ".planning/doc-warden.json"),
    }
    policy_paths = {"AGENTS.md", "OPERATING-MANUAL.md", "_ops/POLICY.md", "_ops/doc-warden/POLICY.md", "README.md"}
    authority_paths = set(event.authority_pointers)
    for relative in sorted({"_ops/doc-warden/POLICY.md", ".doc-warden.yml"} | (authority_paths & policy_paths)):
        path = contained_path(root, relative)
        if path.is_file():
            paths[relative] = path
        elif relative in event.authority_pointers:
            raise ValueError("authoring_authority_missing")
    identifiers = set(event.artifact_ids)
    identifiers.update(authoring_state[key] for key in ("active_plan_id", "active_artifact_id")
                       if authoring_state[key] is not None)
    artifacts = {}
    for path in artifact_paths(root):
        relative = path.relative_to(root).as_posix()
        metadata = parse_validated_artifact(path, repo=root)
        identifier = metadata["id"]
        if identifier not in identifiers and relative not in event.authority_pointers:
            continue
        authority_paths.discard(relative)
        if (identifier in artifacts or metadata["repository_key"] != config["repository_key"]
                or metadata["github_repository_id"] != config["github_repository_id"]):
            raise ValueError("authoring_authority_mismatch")
        if metadata["lifecycle"] == "approved":
            authority = resolve_approved_artifact(root, metadata["type"], identifier)
            artifacts[identifier] = authority.digest
        elif identifier == authoring_state["active_plan_id"] or relative in event.authority_pointers:
            raise ValueError("authoring_authority_unapproved")
        else:
            artifacts[identifier] = digest_ref(path.read_bytes())
    if identifiers - artifacts.keys() or authority_paths - policy_paths:
        raise ValueError("authoring_authority_missing")
    assert_plan_assumptions_current(root, authoring_state["active_plan_id"])
    return digest_ref(canonical_json({
        "head": head,
        "root": str(root),
        "git_dir": str(git_dir.resolve()),
        "git_common_dir": _git_read(root, "rev-parse", "--git-common-dir").decode().strip(),
        "branch": _git_read(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
        "remotes": digest_ref(_git_read(root, "remote", "-v")),
        "status": digest_ref(_git_read(root, "status", "--porcelain=v2", "-z", "--untracked-files=normal")),
        "tracked_changes": digest_ref(_git_read(root, "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD")),
        "untracked_changes": _working_inputs(root),
        "policy": digest_ref((Path(__file__).resolve().parents[2] / "POLICY.md").read_bytes()),
        "inputs": {name: digest_ref(path.read_bytes()) for name, path in paths.items()},
        "artifacts": artifacts,
    }))


def prepare_checkpoint(
    repo: Path,
    authoring_state: dict[str, Any],
    event: CheckpointEvent,
    adapter: SaveGameAdapter,
    *, request_digest: str, intent: str = "checkpoint",
) -> dict[str, Any]:
    before = live_binding(repo, authoring_state, event)
    if adapter.root != repo.resolve(strict=True):
        raise ValueError("authoring_repository_mismatch")
    if intent not in {"checkpoint", "handoff", "pause-with-continuity"}:
        raise ValueError("authoring_continuity_intent_invalid")
    pointer = adapter.checkpoint(event, request_digest=request_digest)
    if live_binding(repo, authoring_state, event) != before:
        raise ValueError("authoring_live_state_changed")
    prior = authoring_state["save_game_pointer"]
    if prior is not None and prior.get("status") != "unavailable":
        pointer = {**pointer, "status": "updated"}
    updated = authoring_state | {"save_game_pointer": pointer, "next_action_code": event.next_action_code,
                                 "continuity_binding": before, "checkpoint_request_digest": request_digest}
    if intent != "checkpoint":
        updated["lifecycle"] = "paused" if intent == "pause-with-continuity" else "waiting"
    require_valid("authoring-state", updated)
    return updated


def prepare_authoring_resume(
    repo: Path,
    authoring_state: dict[str, Any],
    event: CheckpointEvent,
    adapter: SaveGameAdapter,
) -> dict[str, Any]:
    before = live_binding(repo, authoring_state, event)
    if adapter.root != repo.resolve(strict=True):
        raise ValueError("authoring_repository_mismatch")
    if (authoring_state["save_game_pointer"] is None or authoring_state.get("continuity_binding") is None
            or authoring_state.get("checkpoint_request_digest") is None):
        raise ValueError("save_game_checkpoint_required")
    if authoring_state["continuity_binding"] != before:
        raise ValueError("authoring_live_state_changed")
    prior = validate_pointer(authoring_state["save_game_pointer"])
    if prior["status"] == "unavailable":
        raise ValueError("save_game_checkpoint_required")
    if any(prior[field] != list(getattr(event, field))
           for field in ("artifact_ids", "blocker_ids", "authority_pointers")):
        raise ValueError("save_game_pointer_identity_mismatch")
    pointer = adapter.reconcile(event, request_digest=authoring_state["checkpoint_request_digest"])
    if (pointer["checkpoint_id"], pointer["checkpoint_digest"]) != (prior["checkpoint_id"], prior["checkpoint_digest"]):
        raise ValueError("save_game_checkpoint_stale")
    if live_binding(repo, authoring_state, event) != before:
        raise ValueError("authoring_live_state_changed")
    updated = authoring_state | {"save_game_pointer": pointer, "lifecycle": "planned",
                                 "next_action_code": event.next_action_code}
    require_valid("authoring-state", updated)
    return updated
