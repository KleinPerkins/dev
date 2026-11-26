"""Prepare and expose a Personal repo-platform owner session from committed Dev state."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import secrets
import time

from checkout_git_config import owner_config_proofs
from engine import FileLock
from lib.checkout_admission import checked_digest
from lib.contracts import INPUT_MAX, Refusal, encode, json_load, timestamp
from lib.deadline import deadline
from lib.io_safe import directory, outside_repositories, private_dir, read_at
from lib.receipt_store import install_record
from personal_checkout_inventory import Inventory, Refused
from personal_core import SkillEntry, configure_entry, verify_entry_ownership
from personal_index_package import RELEASE
from personal_package_files import physical_path
from physical_checkout_binding import OwnerPhysicalBindings
from refresh_after_lifecycle import refresh_after_evidence_reissue
from skills_inventory_projection import Projection, project_inventory, with_current_checkouts


OWNER_SESSION_SCHEMA = "repo-platform/dev-owner-session/v1"
SKILLS_REVISION = RELEASE["revision"]


@dataclass(frozen=True)
class OwnerSessionPlan:
    root: Path
    codex_home: Path
    operation: str
    projection: Projection
    descriptor: bytes
    previous: bytes | None

    def claims(self):
        return {
            "schema": "dev-repo-platform/owner-session-preview/v1",
            "owner_state": str(self.root),
            "codex_home": str(self.codex_home),
            "inventory_version": self.projection.version,
            "operation": self.operation,
            "descriptor_sha256": sha256(self.descriptor).hexdigest(),
            "previous_sha256": sha256(self.previous).hexdigest() if self.previous is not None else None,
        }

    def digest(self):
        return sha256(encode(self.claims())).hexdigest()


def _private(path):
    with directory(str(path)) as fd:
        private_dir(fd)


def _read_optional(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return read_at(fd, name, INPUT_MAX, True)


def _exact_file(parent, name, expected):
    with directory(str(parent)) as fd:
        private_dir(fd)
        existing = _read_optional(fd, name)
        if existing is None:
            return False
        if existing != expected:
            raise Refused(f"the owner state file {name} differs from the verified preview")
        return True


def _publish_exact(parent, name, data):
    with directory(str(parent)) as fd:
        private_dir(fd)
        try:
            install_record(fd, name, data)
        except FileExistsError:
            if read_at(fd, name, INPUT_MAX, True) != data:
                raise Refused(f"the owner state file {name} was occupied or changed")
            os.fsync(fd)


def _descriptor_record(descriptor):
    return f"owner-session-descriptor-{sha256(descriptor).hexdigest()}.json"


def _current_descriptor(root):
    with directory(str(root)) as fd:
        private_dir(fd)
        previous = _read_optional(fd, "owner-session.json")
        if previous is not None and _read_optional(fd, _descriptor_record(previous)) != previous:
            raise Refused("the current repo-platform descriptor has no matching Dev ownership record")
        return previous


def _authorize_plan(plan, expected_digest):
    try:
        checked_digest(expected_digest)
    except Refusal as error:
        raise Refused("the owner-session preview digest is invalid") from error
    name = f"owner-session-preview-{expected_digest}.json"
    claims = plan.claims()
    if expected_digest == plan.digest():
        return name, encode(claims)
    if plan.previous == plan.descriptor:
        with directory(str(plan.root)) as fd:
            private_dir(fd)
            accepted = _read_optional(fd, name)
        if accepted is not None and sha256(accepted).hexdigest() == expected_digest:
            prior = json_load(accepted, INPUT_MAX)
            if isinstance(prior, dict):
                original_claims = claims | {"previous_sha256": prior.get("previous_sha256")}
                if accepted == encode(original_claims):
                    return name, accepted
    raise Refused("the owner-session preview changed; prepare it again from current Dev authority")


def _publish_descriptor(plan):
    if plan.previous == plan.descriptor:
        return
    _publish_exact(plan.root, _descriptor_record(plan.descriptor), plan.descriptor)
    with directory(str(plan.root)) as fd:
        private_dir(fd)
        name = "owner-session.json"
        if plan.previous is None:
            install_record(fd, name, plan.descriptor)
            return
        staged = ".owner-session-" + secrets.token_hex(16)
        install_record(fd, staged, plan.descriptor)
        try:
            if _read_optional(fd, name) != plan.previous:
                raise Refused("the owner-session descriptor changed during publication")
            os.replace(staged, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(staged, dir_fd=fd)
            except FileNotFoundError:
                pass


def _entry(root, codex_home, *, descriptor=None):
    control = physical_path(codex_home / "dev-personal-core" / "repo-platform")
    slot = physical_path(control / "runtime") / "owner-session"

    def verify():
        _private(root)
        if descriptor is not None and not _exact_file(root, "owner-session.json", descriptor):
            raise Refused("the Dev repo-platform owner descriptor has not been published")

    return SkillEntry(slot, root, control, "repo-platform owner session", verify, verify,
                      requires_ownership=True)


def _owner_root(home):
    root = physical_path(home / ".local/state/dev-repo-platform")
    outside_repositories(str(root))
    _private(root)
    return root


def _checked_plan(root, codex_home, operation, settings, physical):
    if not isinstance(physical, OwnerPhysicalBindings):
        raise Refused("the Dev owner session requires owner-supplied physical evidence")
    physical_path(codex_home)
    entry = _entry(root, codex_home)
    if os.path.lexists(entry.slot):
        verify_entry_ownership(entry)
    previous = _current_descriptor(root)

    inventory = Inventory(root / "inventory")
    scope = inventory.current_owner_evidence(operation, deadline=time.monotonic() + 2)
    if scope.record is None:
        raise Refused("the Dev owner session needs committed checkout evidence")
    record = json_load(scope.record, INPUT_MAX)
    if record["dev_policy_revision"] != scope.current[0]:
        raise Refused("the Dev owner session requires checkout evidence for the current policy")
    selected = OwnerPhysicalBindings(tuple(physical.find(binding) for binding in scope.bindings))
    if selected.digest() != record["physical_binding_digest"]:
        raise Refused("the owner-session physical bindings differ from committed Dev evidence")
    projection = project_inventory(inventory, scope.current, settings, deadline=time.monotonic() + 2)
    paths = tuple(binding.checkout for binding in scope.bindings)
    roots = json_load(projection.config_bytes, INPUT_MAX)["roots"]
    if not set(paths).issubset(root["path"] for root in roots):
        raise Refused("the Skills projection does not cover all checkouts in the owner operation")
    proofs = owner_config_proofs(record, paths)
    descriptor = encode({
        "schema": OWNER_SESSION_SCHEMA, "operation": operation, "skills_revision": SKILLS_REVISION,
        "projection_digest": projection.manifest_digest(),
        "physical_bindings": [asdict(binding) for binding in physical.entries],
    })
    if len(descriptor) > INPUT_MAX:
        raise Refused("the Dev owner session descriptor exceeds its byte limit")
    plan = OwnerSessionPlan(root, codex_home, operation, projection, descriptor, previous)
    return plan, inventory, scope, paths, proofs


def preview_owner_session(home, codex_home, operation, *, settings, physical):
    """Read the exact owner-session publication plan without installing it."""
    return _checked_plan(_owner_root(home), codex_home, operation, settings, physical)[0]


def install_owner_session(home, codex_home, operation, *, settings, physical, expected_digest):
    """Publish the exact preview and expose only the profile-owned session link."""
    root = _owner_root(home)
    with FileLock(root / "owner-session.lock"):
        plan, inventory, scope, paths, proofs = _checked_plan(root, codex_home, operation, settings, physical)
        receipt = _authorize_plan(plan, expected_digest)
        return _install(plan, inventory, scope, paths, proofs, settings, physical, receipt)


def _install(plan, inventory, scope, paths, proofs, settings, physical, receipt):
    discovery = plan.root / "discovery"
    results = plan.root / "results"
    for path in (discovery, results):
        path.mkdir(mode=0o700, exist_ok=True)
        _private(path)
    _publish_exact(discovery, "settings.json", settings)

    def confirm():
        current = inventory.current_owner_evidence(plan.operation, deadline=time.monotonic() + 2)
        if current.current != scope.current or current.digest != scope.digest:
            raise Refused("Dev owner evidence changed while preparing the repo-platform session")

    try:
        readback = refresh_after_evidence_reissue(
            inventory, plan.operation, settings, SKILLS_REVISION, discovery, str(discovery / "snapshot.json"),
            physical=physical, owner_record=scope.record, confirm_owner_evidence=confirm,
        )
        age = (datetime.now(timezone.utc) - timestamp(readback.receipt["observed_at"])).total_seconds()
        if not 0 <= age <= 86400:
            raise Refused("the repo-platform owner session requires a fresh Skills receipt")

        def expose(verify_current):
            verify_current()
            _publish_exact(plan.root, *receipt)
            _publish_descriptor(plan)
            return configure_entry(_entry(plan.root, plan.codex_home, descriptor=plan.descriptor), "install")

        with deadline(2):
            return with_current_checkouts(inventory, scope.current, paths, frozenset(paths), physical,
                                          expose, time.monotonic() + 2, owner_config_digests=proofs)
    except Refusal as error:
        raise Refused(f"the repo-platform owner-session preparation refused ({error.code})") from error


def installed_owner_root(home, codex_home):
    """Resolve the exact profile-owned entry for the installed native launcher."""
    root = _owner_root(home)
    entry = _entry(root, physical_path(codex_home))
    configure_entry(entry, "check")
    current = _current_descriptor(root)
    descriptor = json_load(current, INPUT_MAX) if current is not None else None
    if not isinstance(descriptor, dict) or descriptor.get("schema") != OWNER_SESSION_SCHEMA:
        raise Refused("the installed repo-platform owner descriptor is not recognized")
    return root


def withdraw_owner_session(home, codex_home):
    """Withdraw an owned discovery link and retain the complete owner state."""
    root = _owner_root(home)
    with FileLock(root / "owner-session.lock"):
        return configure_entry(_entry(root, physical_path(codex_home)), "withdraw")
