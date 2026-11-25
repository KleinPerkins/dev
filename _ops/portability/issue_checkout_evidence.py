"""Dev owner issuance from independently observed native and hosting authority."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import re
import time

from lib.contracts import INPUT_MAX, encode, json_load
from checkout_git_config import CONFIG_PROOF_FIELDS, config_proof, observe_git_config
from github_checkout_provider import GitHubRepositoryObservation, validate_branch_name
from native_checkout_project import NativeProjectBinding, selection_digest
from personal_checkout_inventory import Refused, lexical
from physical_checkout_binding import OwnerPhysicalBindings, ROLES, pin_checkout
from skills_inventory_projection import linked_relationship


SOURCE_READ_TIMES = {
    "native_observed_at": "Codex project",
    "github_identity_observed_at": "GitHub repository identity",
    "github_ref_observed_at": "GitHub default ref",
}


@dataclass(frozen=True)
class OwnerCheckoutObservation:
    checkout: str
    project_id: str
    repository_id: int
    github_name: str
    default_branch: str
    default_head: str
    native_observed_at: int
    github_identity_observed_at: int
    github_ref_observed_at: int
    native_selection_digest: str
    native_thread_id: str | None = None

    @classmethod
    def from_authorities(cls, native, hosting):
        if not isinstance(native, NativeProjectBinding):
            raise Refused("the owner needs an observed Codex project binding")
        if not isinstance(hosting, GitHubRepositoryObservation):
            raise Refused("the owner needs independently observed GitHub repository evidence")
        return cls(native.checkout, native.project_id, hosting.repository_id, hosting.full_name,
                   hosting.default_branch, hosting.default_head, native.observed_at,
                   hosting.identity_observed_at, hosting.ref_observed_at, native.selection_digest, native.thread_id)


def observe_checkout_authorities(selections, *, repository_ids, read_native, read_hosting, deadline):
    """Read explicit native selections and Dev's current repository IDs using the owner transports."""
    if not selections or selections.keys() != repository_ids.keys():
        raise Refused("the selected checkouts differ from the admitted hosting scope")
    native_bindings = {}
    for checkout, project_id in selections.items():
        native = read_native(project_id, checkout, deadline=deadline)
        if (not isinstance(native, NativeProjectBinding) or native.project_id != project_id
                or native.checkout != checkout):
            raise Refused("the native response differs from the selected project and checkout")
        native_bindings[checkout] = native
    repositories = {}
    for repository_id in sorted(set(repository_ids.values())):
        hosting = read_hosting(repository_id, deadline=deadline)
        if not isinstance(hosting, GitHubRepositoryObservation) or hosting.repository_id != repository_id:
            raise Refused("the hosting response differs from the Dev-admitted repository ID")
        repositories[repository_id] = hosting
    return {checkout: OwnerCheckoutObservation.from_authorities(native, repositories[repository_ids[checkout]])
            for checkout, native in native_bindings.items()}


def issue_checkout_evidence_reissue(inventory, expected, operation, selections, observations, *, physical, deadline):
    """Commit a reissue for explicit selections using trusted owner-adapter observations.

    The calling owner timestamps each observation at its own source read. Dev
    revalidates the admitted scope and physical Git roles
    before storing their exact relationship. This helper does not grant access.
    """
    if not selections or not isinstance(physical, OwnerPhysicalBindings):
        raise Refused("the owner reissue requires explicit checkout selections and physical evidence")
    paths = sorted(lexical(path) for path in selections)
    if set(paths) != set(observations):
        raise Refused("the owner observations differ from the explicit checkout selections")

    def verify_sources(bindings):
        if [binding.checkout for binding in bindings] != paths:
            raise Refused("the prepared owner evidence differs from the explicit checkout selections")
        now = int(time.time())
        for binding in bindings:
            observation = observations[binding.checkout]
            if (not isinstance(observation, OwnerCheckoutObservation)
                    or observation.checkout != binding.checkout or not observation.project_id
                    or observation.project_id != selections[binding.checkout]
                    or observation.native_selection_digest != selection_digest(
                        observation.project_id, binding.checkout, observation.native_thread_id)):
                raise Refused("the current native project binding differs from the selected checkout")
            if (binding.provider != "github" or type(observation.repository_id) is not int
                    or observation.repository_id != binding.repository_id
                    or not isinstance(observation.github_name, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", observation.github_name)
                    or not isinstance(observation.default_head, str)
                    or not re.fullmatch(r"[0-9a-f]{40}", observation.default_head)):
                raise Refused("the current GitHub identity differs from the admitted checkout")
            validate_branch_name(observation.default_branch)
            for field, source in SOURCE_READ_TIMES.items():
                observed_at = getattr(observation, field)
                if type(observed_at) is not int or not 0 <= now - observed_at <= 86400:
                    raise Refused(f"a fresh {source} observation is required for the selected checkout")

        return OwnerPhysicalBindings(tuple(physical.find(binding) for binding in bindings))

    def inspect(bindings):
        selected = verify_sources(bindings)
        verified = []
        for binding, proof in zip(bindings, selected.entries):
            location = tuple((role, getattr(binding, role)) for role in ROLES)
            with pin_checkout(binding, proof, location + binding.linked_metadata(), deadline) as reader:
                linked_relationship(binding, reader)
                source = observations[binding.checkout]
                git = observe_git_config(binding, reader, source.github_name, deadline)
                verified.append(asdict(source) | git.fields())
        return {binding.checkout: binding for binding in bindings}, selected.digest(), verified

    def inspect_current(version):
        return inventory.commit_bound_index(
            version, paths, inspect, deadline=deadline, linked_metadata_checkouts=frozenset(paths)
        )

    def verify_completion(version, checked_digest, prepared_rows):
        scope = inventory.current_owner_evidence(operation, deadline=deadline)
        if scope.digest != checked_digest or scope.current != tuple(version):
            raise Refused("Dev authority changed before the completed evidence was rechecked")
        _, _, current_rows = inspect_current(version)
        if any(not config_proof(before).matches(config_proof(now))
               for before, now in zip(prepared_rows, current_rows, strict=True)):
            raise Refused("the checkout Git configuration changed after the evidence was prepared")

    prepared = inventory.read_prepared_evidence_reissue(operation, deadline=deadline, allow_missing=True)
    if prepared is not None:
        if tuple(expected) not in (prepared.expected, prepared.current):
            raise Refused("Dev inventory changed; re-read current authority")
        selected = verify_sources(prepared.bindings)
        prior = json_load(prepared.record, INPUT_MAX)
        rows = prior.get("observations") if isinstance(prior, dict) else None
        required_fields = {*SOURCE_READ_TIMES, "git_config_sha256"}
        if (not isinstance(rows, list) or len(rows) != len(paths)
                or any(not isinstance(row, dict) or not required_fields.issubset(row) for row in rows)):
            raise Refused("the operation has no matching prepared issuer observations")
        prepared_rows = rows
        rechecked_fields = {*SOURCE_READ_TIMES, *CONFIG_PROOF_FIELDS}
        previous = [{key: value for key, value in row.items() if key not in rechecked_fields}
                    for row in prepared_rows]
        for row in previous:
            row.setdefault("native_thread_id", None)
        current = [{key: value for key, value in asdict(observations[path]).items() if key not in SOURCE_READ_TIMES}
                   for path in paths]
        if previous != current or prior.get("physical_binding_digest") != selected.digest():
            raise Refused("the current owner observations differ from the prepared evidence")
        checked_digest = "sha256:" + sha256(prepared.record).hexdigest()
        if prepared.completed is not None:
            verify_completion(prepared.current, checked_digest, prepared_rows)
            return prepared.completed
        completed = inventory.resume_prepared_evidence_reissue(
            operation, checked_owner_digest=checked_digest, physical_binding_digest=selected.digest(), deadline=deadline
        )
        verify_completion(completed, checked_digest, prepared_rows)
        return completed

    bindings, physical_digest, verified = inspect_current(expected)
    record = encode({"schema": "dev-checkout-owner-evidence/v1", "operation": operation,
                     "dev_policy_revision": expected[0], "physical_binding_digest": physical_digest,
                     "observations": verified})
    inventory.reserve_evidence_reissue(expected, operation, bindings, owner_record=record,
                                       physical_binding_digest=physical_digest, deadline=deadline)
    checked_digest = "sha256:" + sha256(record).hexdigest()
    completed = inventory.resume_prepared_evidence_reissue(
        operation, checked_owner_digest=checked_digest, physical_binding_digest=physical_digest, deadline=deadline
    )
    verify_completion(completed, checked_digest, verified)
    return completed
