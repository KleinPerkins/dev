"""Reconcile a finished Dev operation with its qualified Skills publication."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
import time

from lib import engine
from lib.contracts import INPUT_MAX, Refusal, json_load
from lib.deadline import deadline as read_deadline
from lib.receipt_store import load_qualified_snapshot

from checkout_git_config import config_proof
from issue_checkout_evidence import issue_checkout_evidence_reissue
from personal_checkout_inventory import Refused
from physical_checkout_binding import OwnerPhysicalBindings
from skills_inventory_projection import (guarded_admission, project_inventory, qualify_current_snapshot,
                                         store_projection, with_current_checkouts)


@dataclass(frozen=True)
class RefreshReadback:
    finished_inventory_version: tuple[str, int, str]
    published_inventory_version: tuple[str, int, str]
    receipt: dict
    reused_publication: bool


def read_snapshot_and_receipt(cache, admission):
    with read_deadline(2):
        return load_qualified_snapshot(str(cache), admission)


def refresh_after_lifecycle(
    inventory, operation, trusted_settings, skills_revision, private_state, cache, *,
    physical, expected_inventory_version: tuple[str, int, str] | None = None, owner_config_digests=None,
    confirm_owner_evidence=None,
):
    """Publish current discovery or reuse its verified publication on recovery.

    The caller supplies the exact operation ID retained by its source journal.
    A committed Dev operation and exact Skills receipt survive independently.
    Replaying this step never repeats the source operation or changes Dev authority.
    A caller that separately validated owner evidence can pin the inventory
    version from that validation. A changed version requires fresh validation.
    """
    if not isinstance(physical, OwnerPhysicalBindings):
        raise Refused('discovery refresh requires owner-supplied physical checkout bindings')
    scope = inventory.finished_refresh_scope(operation)
    current = scope.current
    if expected_inventory_version is not None and current != expected_inventory_version:
        raise Refused('Dev authority changed after proof validation; re-read current owner evidence')
    projection = project_inventory(inventory, current, trusted_settings, deadline=time.monotonic() + 2)
    roots = {row['path'] for row in json_load(projection.config_bytes, INPUT_MAX)['roots']}
    if not scope.required_checkouts <= roots:
        raise Refused('the Skills projection does not cover the affected checkout admissions')
    if owner_config_digests:
        checkouts = tuple(sorted(owner_config_digests))
        with read_deadline(2):
            with_current_checkouts(inventory, current, checkouts, frozenset(checkouts), physical, lambda _: None,
                                   time.monotonic() + 2, owner_config_digests=owner_config_digests)
    admission = guarded_admission(inventory, projection, skills_revision, physical=physical,
                                  owner_config_digests=owner_config_digests)
    try:
        snapshot, receipt = read_snapshot_and_receipt(cache, admission)
    except Refusal as error:
        if error.code != 'unavailable':
            raise
        stored = store_projection(Path(private_state), projection)
        options = {"before_replace": confirm_owner_evidence} if confirm_owner_evidence is not None else {}
        written = engine.refresh_admitted(str(stored.config), str(cache), admission, **options)
        snapshot, receipt = read_snapshot_and_receipt(cache, admission)
        if written != receipt:
            raise Refused('a different Skills publication replaced the expected receipt; retry from current Dev authority')
        reused = False
    else:
        if confirm_owner_evidence is not None:
            confirm_owner_evidence()
        reused = True
    if inventory.snapshot()[1] != current:
        raise Refused('Dev authority advanced during refresh; retry from current inventory')
    qualify_current_snapshot(inventory, projection, physical, snapshot, owner_config_digests=owner_config_digests)
    return RefreshReadback(scope.completed, current, receipt, reused)


def refresh_after_evidence_reissue(
    inventory, operation, trusted_settings, skills_revision, private_state, cache, *, physical, owner_record=None,
    confirm_owner_evidence=None,
):
    """Bind a renewed owner record to the current Dev version before refreshing."""
    if not isinstance(physical, OwnerPhysicalBindings):
        raise Refused("discovery refresh requires owner-supplied physical checkout bindings")
    scope = inventory.current_owner_evidence(operation, deadline=time.monotonic() + 2)
    if owner_record is None:
        owner_record = scope.record
        if owner_record is None:
            raise Refused("the operation has no durable owner evidence record")
    if not isinstance(owner_record, bytes) or not 0 < len(owner_record) <= INPUT_MAX:
        raise Refused("a bounded owner evidence record is required")
    if "sha256:" + sha256(owner_record).hexdigest() != scope.digest:
        raise Refused("the owner record differs from the committed checkout evidence")
    record = json_load(owner_record, INPUT_MAX)
    selected = OwnerPhysicalBindings(tuple(physical.find(binding) for binding in scope.bindings))
    if (not isinstance(record, dict) or record.get("schema") != "dev-checkout-owner-evidence/v1"
            or record.get("operation") != operation or record.get("physical_binding_digest") != selected.digest()):
        raise Refused("the owner evidence does not bind the selected physical checkouts")
    config_digests = {}
    if "observations" in record:
        rows = record["observations"]
        if not isinstance(rows, list) or len(rows) != len(scope.bindings):
            raise Refused("the owner record does not cover the selected checkout Git configurations")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("checkout"), str):
                raise Refused("the owner record does not cover the selected checkout Git configurations")
            config_digests[row["checkout"]] = config_proof(row)
        if set(config_digests) != {binding.checkout for binding in scope.bindings}:
            raise Refused("the owner record does not cover the selected checkout Git configurations")
    return refresh_after_lifecycle(
        inventory, operation, trusted_settings, skills_revision, private_state, cache, physical=physical,
        expected_inventory_version=scope.current, owner_config_digests=config_digests,
        confirm_owner_evidence=confirm_owner_evidence,
    )


def reissue_and_refresh_from_owner(
    inventory, expected, operation, selections, trusted_settings, skills_revision, private_state, cache, *,
    physical, read_authorities, deadline,
):
    """Publish discovery only after the trusted owner adapter confirms the same selection twice.

    The adapter reads Codex and GitHub without opening checkouts. Dev controls
    the subsequent checkout access, journal replay and publication guard.
    """
    if not selections or not isinstance(physical, OwnerPhysicalBindings) or not callable(read_authorities):
        raise Refused("discovery refresh requires explicit selections and a trusted owner adapter")
    selections = MappingProxyType(dict(selections))

    def observe_and_reissue(version):
        if not time.monotonic() < deadline:
            raise Refused("owner evidence refresh deadline elapsed")
        bindings = inventory.owner_observation_scope(version, operation, selections, deadline=deadline)
        if any(binding.provider != "github" for binding in bindings):
            raise Refused("the discovery refresh cannot read the admitted checkout's hosting provider")
        repository_ids = MappingProxyType({binding.checkout: binding.repository_id for binding in bindings})
        observations = dict(read_authorities(selections, repository_ids=repository_ids, deadline=deadline))
        if not time.monotonic() < deadline:
            raise Refused("owner evidence refresh deadline elapsed")
        return issue_checkout_evidence_reissue(
            inventory, version, operation, selections, observations, physical=physical, deadline=deadline,
        )

    completed = observe_and_reissue(expected)

    def confirm():
        if observe_and_reissue(completed) != completed:
            raise Refused("Dev authority changed before the owner evidence was confirmed")
        if not time.monotonic() < deadline:
            raise Refused("owner evidence refresh deadline elapsed")

    return refresh_after_evidence_reissue(
        inventory, operation, trusted_settings, skills_revision, private_state, cache, physical=physical,
        confirm_owner_evidence=confirm,
    )
