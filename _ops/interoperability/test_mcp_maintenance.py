"""Synthetic D2 coordination tests; no user config, installed packages or services."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = importlib.util.spec_from_file_location("int014_maintenance", HERE / "mcp_maintenance.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
NOW = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)
REV = "a" * 40
H = "b" * 64


def evidence(target: Path, state: Path, **updates):
    mid = str(uuid.uuid4())
    result = dict(schema=m.EVIDENCE_SCHEMA, maintenance_id=mid,
        issuer_source_revision=REV, accepted_contract_digest=m.CONTRACT_DIGEST,
        audience_digest=m.digest({"synthetic": "selected"}),
        config_target_id=m.target_id(target), state_target_id=m.target_id(state),
        config_preimage_digest="absent", state_preimage_digest="absent",
        consequence_review_digest=H, legacy_handoff_id=mid,
        acquired_at=m._stamp(NOW), expires_at=m._stamp(NOW + timedelta(seconds=600)),
        prior_guard_state="not_enrolled", prior_guard_lock="not_applicable",
        predecessor_maintenance_id=None, recovery_of=None,
        known_writers=[dict(writer_id="mirror", kind="legacy-mirror", prior_state="inactive",
            observed_state="inactive", observation_reference="synthetic:mirror", observation_digest=H,
            observed_at=m._stamp(NOW), resume_disposition="remain_suspended")])
    result.update(updates)
    return result


class SyntheticObservations:
    """Deterministic runtime observations, never registered as a live adapter."""
    def __init__(self):
        self.active = False
        self.effects = "bounded"
        self.baseline = "compatible"
        self.restored = True
        self.mutated = False
        self.eligible = {b"synthetic preimage", b"synthetic postimage"}
        self.approval = None
        self.calls = []

    def current(self, evidence, now):
        self.calls.append("current")
        if self.active or self.effects != "bounded":
            raise m.MaintenanceError()
        if {w["writer_id"] for w in evidence["known_writers"]} != {"mirror"}:
            raise m.MaintenanceError()

    def lineage(self, evidence, predecessor):
        if evidence["recovery_of"] != H:
            raise m.MaintenanceError()

    def mutation(self, request, evidence):
        self.calls.append("mutation")
        if any(blob is not None and blob not in self.eligible for blob in request.durable_material):
            raise m.MaintenanceError("durable_material_ineligible")
        if request.approval is not None and request.approval != self.approval:
            raise m.MaintenanceError("approval_invalid")

    def transition(self, evidence, before, after, child):
        self.calls.append("transition")
        if after["status"] in {"released", "cancelled"}:
            if self.baseline != "compatible" or not self.restored:
                raise m.MaintenanceError("writer_release_failed")
            if after["status"] == "cancelled" and self.mutated and child is None:
                raise m.MaintenanceError("recovery_required")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dev-maintenance-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.store = m.MaintenanceStore(self.home / ".local/state/dev/mcp-maintenance")
        self.config = self.home / ".codex/config.toml"
        self.registrar_state = self.root / "registrar-state"
        self.e = evidence(self.config, self.registrar_state)
        self.obs = SyntheticObservations()
        self.env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop(m._FD_ENV, None)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            self.env.pop(key, None)

    def acquire(self):
        return self.store.acquire(self.e, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)

    def transition(self, state, status, **kw):
        defaults = dict(registrar_result_reference=None, baseline_handoff_reference=None,
                        release_observation_digest=None, observations=self.obs, now=NOW)
        defaults.update(kw)
        return self.store.transition(self.e["maintenance_id"], m.digest(state), status=status, **defaults)

    def request(self, **updates):
        result = dict(context=SimpleNamespace(config_path=self.config, state_directory=self.registrar_state, maintenance_evidence=SimpleNamespace(to_record=lambda: deepcopy(self.e))),
                      checked_at=NOW, audience=SimpleNamespace(to_record=lambda: {"synthetic": "selected"}),
                      original_operation_reference=None, durable_material=(), approval=None,
                      phase="admission", operation_id=None, action_digest=None,
                      prepared_payload_digest=None, expected_config_digest=None, expected_state_digest=None)
        result.update(updates)
        return SimpleNamespace(**result)

    def validator(self):
        validator = m.MaintenanceValidator(self.store, REV, self.obs)
        def validate(request):
            with validator.operation():
                validator.validate(request)
        return SimpleNamespace(validate=validate)

    def run_script(self, script, *args, env=None):
        return subprocess.run(["bash", str(script), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=20)

    def test_private_atomic_roundtrip_and_reconstruction(self):
        state = self.acquire()
        loaded = m.MaintenanceStore(self.store.root).read(self.e["maintenance_id"])
        self.assertEqual(state, loaded["state"])
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)
        for path in self.store.root.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.validator().validate(self.request())
        self.assertEqual(self.obs.calls[-2:], ["current", "mutation"])

    def test_closed_evidence_refuses_unknown_mixed_mode_and_duration(self):
        for update in ({"extra": True}, {"schema": "kp-mcp/writer-window/v1"},
                       {"accepted_contract_digest": "c" * 64}, {"legacy_handoff_id": str(uuid.uuid4())},
                       {"expires_at": m._stamp(NOW + timedelta(seconds=601))},
                       {"recovery_of": H}, {"prior_guard_state": "unknown"}):
            with self.subTest(update=update), self.assertRaises(m.MaintenanceError):
                self.store.acquire({**self.e, **update}, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)
        self.assertFalse(self.store.root.exists())

    def test_unknown_or_duplicate_writer_refuses(self):
        for change in ({"observed_state": "active"}, {"extra": "unknown"}, {"kind": "fixture"}):
            e = deepcopy(self.e)
            e["known_writers"][0].update(change)
            with self.assertRaises(m.MaintenanceError):
                self.store.acquire(e, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)
        e = deepcopy(self.e)
        e["known_writers"] *= 2
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(e, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)

    def test_excluded_or_unknown_pause_effects_create_no_record(self):
        for effect in ("excluded-runtime", "unknown"):
            self.obs.effects = effect
            with self.assertRaises(m.MaintenanceError):
                self.acquire()
            self.assertFalse(self.store.root.exists())

    def test_known_writer_restart_and_expiry_refuse(self):
        self.acquire()
        self.obs.active = True
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request())
        self.obs.active = False
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request(checked_at=NOW + timedelta(seconds=601)))
        with self.assertRaises(m.MaintenanceError):
            m.refuse_legacy(self.store, [self.config])

    def test_pause_before_acquire_is_bounded_and_future_observations_refuse(self):
        self.e["known_writers"][0]["observed_at"] = m._stamp(NOW - timedelta(seconds=599))
        self.acquire()
        for age in (601, -1):
            e = evidence(self.config, self.registrar_state)
            e["known_writers"][0]["observed_at"] = m._stamp(NOW - timedelta(seconds=age))
            with self.assertRaises(m.MaintenanceError):
                self.store.acquire(e, self.obs, config_path=self.config,
                                   state_directory=self.registrar_state, now=NOW)

    def test_runtime_requires_operation_barrier_and_blocks_state_transition(self):
        state = self.acquire()
        validator = m.MaintenanceValidator(self.store, REV, self.obs)
        with self.assertRaises(m.MaintenanceError):
            validator.validate(self.request())
        with validator.operation():
            validator.validate(self.request())
            with self.assertRaisesRegex(m.MaintenanceError, "known_writer_active"):
                self.transition(state, "recovery_required")
        self.transition(state, "recovery_required")

    def test_target_alias_or_foreign_binding_refuses(self):
        wrong = evidence(self.root / "foreign", self.registrar_state)
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(wrong, self.obs, config_path=self.config,
                               state_directory=self.registrar_state, now=NOW)
        self.acquire()
        self.config.parent.mkdir(parents=True)
        (self.root / "other").write_text("fixture")
        self.config.symlink_to(self.root / "other")
        with self.assertRaises(m.MaintenanceError):
            m.refuse_legacy(self.store, [self.config])

    def test_whole_file_secret_sibling_and_unclassified_bytes_never_persist(self):
        self.acquire()
        before = {p.name: p.read_bytes() for p in self.store.root.iterdir()}
        for blob in (b'{"selected":{},"sibling":{"credential":"SYNTHETIC_SECRET"}}', b"unknown"):
            with self.assertRaises(m.MaintenanceError):
                self.validator().validate(self.request(durable_material=(b"synthetic preimage", blob)))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.root.iterdir()})
        self.assertFalse(self.config.exists())

    def test_approval_audience_source_and_original_binding(self):
        self.acquire()
        for update in ({"audience": SimpleNamespace(to_record=lambda: {"wrong": "audience"})},
                       {"original_operation_reference": H}, {"approval": "fixture-approval"}):
            with self.assertRaises(m.MaintenanceError):
                self.validator().validate(self.request(**update))
        with self.assertRaises(m.MaintenanceError):
            m.MaintenanceValidator(self.store, "c" * 40, self.obs).validate(self.request())

    def test_refuses_persisted_validated_flag_and_evidence_rewrite(self):
        self.acquire()
        path = self.store.root / (self.e["maintenance_id"] + ".json")
        row = json.loads(path.read_bytes())
        row["state"]["validated"] = True
        path.write_bytes(m.canonical(row))
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request())

    def test_release_pending_baseline_is_separate_from_registrar_success(self):
        state = self.acquire()
        pending = self.transition(state, "applied_pending_handoff", registrar_result_reference=H)
        self.obs.baseline = "conflict"
        with self.assertRaises(m.MaintenanceError):
            self.transition(pending, "released", registrar_result_reference=H,
                            baseline_handoff_reference=H, release_observation_digest=H)
        self.assertEqual(self.store.read(self.e["maintenance_id"])["state"], pending)
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request())
        self.obs.baseline = "compatible"
        released = self.transition(pending, "released", registrar_result_reference=H,
                                   baseline_handoff_reference=H, release_observation_digest=H)
        with self.assertRaises(m.MaintenanceError):
            m.refuse_legacy(self.store, [self.config])
        with self.assertRaises(m.MaintenanceError):
            self.transition(released, "acquired")

    def test_baseline_pending_unrelated_or_healing_and_lock_restore_refuse(self):
        state = self.acquire()
        for baseline, restored in (("pending-unrelated", True), ("would-heal", True), ("compatible", False)):
            self.obs.baseline, self.obs.restored = baseline, restored
            with self.assertRaises(m.MaintenanceError):
                self.transition(state, "cancelled", registrar_result_reference=H,
                                baseline_handoff_reference=H, release_observation_digest=H)

    def test_exact_zero_mutation_cancel_allows_prior_legacy_writer(self):
        state = self.acquire()
        self.transition(state, "cancelled", registrar_result_reference=H,
                        baseline_handoff_reference=H, release_observation_digest=H)
        m.refuse_legacy(self.store, [self.config])

    def test_no_blanket_cancel_after_mutation_and_no_result_discard(self):
        state = self.acquire()
        self.obs.mutated = True
        with self.assertRaises(m.MaintenanceError):
            self.transition(state, "cancelled", registrar_result_reference=H,
                            baseline_handoff_reference=H, release_observation_digest=H)
        pending = self.transition(state, "applied_pending_handoff", registrar_result_reference=H)
        with self.assertRaises(m.MaintenanceError):
            self.transition(pending, "recovery_required")

    def test_recovery_requires_child_terminal_and_no_competing_lineage(self):
        state = self.acquire()
        parent = self.transition(state, "recovery_required")
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request())
        with self.assertRaises(m.MaintenanceError):
            self.transition(parent, "released", registrar_result_reference=H,
                            baseline_handoff_reference=H, release_observation_digest=H)
        child_e = evidence(self.config, self.registrar_state,
                           predecessor_maintenance_id=self.e["maintenance_id"], recovery_of=H)
        child = self.store.acquire(child_e, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)
        other = evidence(self.config, self.registrar_state,
                         predecessor_maintenance_id=self.e["maintenance_id"], recovery_of=H)
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(other, self.obs, config_path=self.config, state_directory=self.registrar_state, now=NOW)
        with self.assertRaises(m.MaintenanceError):
            self.transition(parent, "released", registrar_result_reference=H,
                            baseline_handoff_reference=H, release_observation_digest=H,
                            child_id=child_e["maintenance_id"])
        self.store.transition(child_e["maintenance_id"], m.digest(child), status="cancelled",
                              registrar_result_reference=H, baseline_handoff_reference=H,
                              release_observation_digest=H, observations=self.obs, now=NOW)
        self.transition(parent, "cancelled", registrar_result_reference=H,
                        baseline_handoff_reference=H, release_observation_digest=H,
                        child_id=child_e["maintenance_id"])

    def test_lifecycle_compare_and_swap_and_fsync_failure(self):
        state = self.acquire()
        with self.assertRaises(m.MaintenanceError):
            self.store.transition(self.e["maintenance_id"], "c" * 64, status="recovery_required",
                registrar_result_reference=None, baseline_handoff_reference=None,
                release_observation_digest=None, observations=self.obs, now=NOW)
        with patch.object(m.os, "fsync", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.transition(state, "recovery_required")
        self.assertEqual(self.store.read(self.e["maintenance_id"])["state"], state)
        with self.assertRaises(m.MaintenanceError):
            m.refuse_legacy(self.store, [self.config])

    def test_recovery_chain_admits_grandchild_but_not_competing_sibling(self):
        parent = self.transition(self.acquire(), "recovery_required")
        child_e = evidence(self.config, self.registrar_state,
                           predecessor_maintenance_id=self.e["maintenance_id"], recovery_of=H)
        child = self.store.acquire(child_e, self.obs, config_path=self.config,
                                   state_directory=self.registrar_state, now=NOW)
        self.store.transition(child_e["maintenance_id"], m.digest(child), status="recovery_required",
                              registrar_result_reference=None, baseline_handoff_reference=None,
                              release_observation_digest=None, observations=self.obs, now=NOW)
        grandchild_e = evidence(self.config, self.registrar_state,
                                predecessor_maintenance_id=child_e["maintenance_id"], recovery_of=H)
        grandchild = self.store.acquire(grandchild_e, self.obs, config_path=self.config,
                                        state_directory=self.registrar_state, now=NOW)
        self.assertEqual(grandchild["status"], "acquired")
        self.assertEqual(self.store.read(self.e["maintenance_id"])["state"], parent)
        sibling = evidence(self.config, self.registrar_state,
                           predecessor_maintenance_id=child_e["maintenance_id"], recovery_of=H)
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(sibling, self.obs, config_path=self.config,
                               state_directory=self.registrar_state, now=NOW)

    def _chain_for_refusal(self):
        self.transition(self.acquire(), "recovery_required")
        child_e = evidence(self.config, self.registrar_state,
                           predecessor_maintenance_id=self.e["maintenance_id"], recovery_of=H)
        child = self.store.acquire(child_e, self.obs, config_path=self.config,
                                   state_directory=self.registrar_state, now=NOW)
        self.store.transition(child_e["maintenance_id"], m.digest(child), status="recovery_required",
                              registrar_result_reference=None, baseline_handoff_reference=None,
                              release_observation_digest=None, observations=self.obs, now=NOW)
        return evidence(self.config, self.registrar_state,
                        predecessor_maintenance_id=child_e["maintenance_id"], recovery_of=H)

    def test_recovery_chain_cycle_refuses_without_new_record(self):
        proposed = self._chain_for_refusal()
        root = self.store.read(self.e["maintenance_id"])
        root["evidence"].update(predecessor_maintenance_id=proposed["predecessor_maintenance_id"], recovery_of=H)
        root["state"].update(predecessor_maintenance_id=proposed["predecessor_maintenance_id"],
                             evidence_digest=m.digest(root["evidence"]))
        with self.store.barrier(exclusive=True):
            self.store._write(root)
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(proposed, self.obs, config_path=self.config,
                               state_directory=self.registrar_state, now=NOW)
        self.assertEqual(len(self.store.records()), 2)

    def test_recovery_chain_changed_ancestor_target_refuses(self):
        proposed = self._chain_for_refusal()
        root = self.store.read(self.e["maintenance_id"])
        root["evidence"]["config_target_id"] = m.target_id(self.root / "other-config")
        root["state"]["evidence_digest"] = m.digest(root["evidence"])
        with self.store.barrier(exclusive=True):
            self.store._write(root)
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(proposed, self.obs, config_path=self.config,
                               state_directory=self.registrar_state, now=NOW)
        self.assertEqual(len(self.store.records()), 2)

    def test_recovery_chain_unrelated_retained_operation_refuses(self):
        proposed = self._chain_for_refusal()
        unrelated = evidence(self.config, self.registrar_state)
        state = dict(schema=m.STATE_SCHEMA, maintenance_id=unrelated["maintenance_id"],
                     evidence_digest=m.digest(unrelated), predecessor_maintenance_id=None,
                     status="recovery_required", last_observed_at=m._stamp(NOW),
                     registrar_result_reference=None, baseline_handoff_reference=None,
                     release_observation_digest=None)
        with self.store.barrier(exclusive=True):
            self.store._write({"evidence": unrelated, "state": state})
        with self.assertRaises(m.MaintenanceError):
            self.store.acquire(proposed, self.obs, config_path=self.config,
                               state_directory=self.registrar_state, now=NOW)
        self.assertEqual(len(self.store.records()), 3)

    def test_process_death_pending_recovery_never_admits_new_writes(self):
        self.acquire()
        row = self.store.read(self.e["maintenance_id"])
        before = hashlib.sha256(m.canonical(row)).hexdigest()
        pending = self.store.root / f".pending-{self.e['maintenance_id']}.{m.digest(self.e)}.{before}.fixture"
        pending.write_bytes(b'{"partial":')
        pending.chmod(0o600)
        with self.assertRaises(m.MaintenanceError):
            self.store.records()
        preview = self.store.pending_preview(pending.name, self.e)
        pending.write_bytes(b"changed")
        with self.assertRaises(m.MaintenanceError):
            self.store.recover_pending(preview, self.e, self.obs)
        pending.write_bytes(b'{"partial":')
        # Crash after recovery_required is durable but before orphan deletion.
        with self.store.barrier(exclusive=True):
            self.store._write({"evidence": self.e, "state": preview["after"]})
        repaired = self.store.recover_pending(preview, self.e, self.obs)
        self.assertEqual(repaired["status"], "recovery_required")
        with self.assertRaises(m.MaintenanceError):
            self.validator().validate(self.request())
        with self.assertRaises(m.MaintenanceError):
            m.refuse_legacy(self.store, [self.config])

    def test_failed_first_acquire_only_repairs_with_explicit_cancellation_proofs(self):
        with self.store.barrier(exclusive=True):
            pass
        pending = self.store.root / f".pending-{self.e['maintenance_id']}.{m.digest(self.e)}.absent.fixture"
        pending.write_bytes(b'{"partial":')
        pending.chmod(0o600)
        with self.assertRaises(m.MaintenanceError):
            self.store.pending_preview(pending.name, self.e)
        cancelled = dict(schema=m.STATE_SCHEMA, maintenance_id=self.e["maintenance_id"],
                         evidence_digest=m.digest(self.e), predecessor_maintenance_id=None,
                         status="cancelled", last_observed_at=m._stamp(NOW),
                         registrar_result_reference=H, baseline_handoff_reference=H,
                         release_observation_digest=H)
        preview = self.store.pending_preview(pending.name, self.e, cancelled_state=cancelled)
        self.obs.restored = False
        with self.assertRaises(m.MaintenanceError):
            self.store.recover_pending(preview, self.e, self.obs)
        self.assertTrue(pending.exists())
        self.obs.restored = True
        repaired = self.store.recover_pending(preview, self.e, self.obs)
        self.assertEqual(repaired["status"], "cancelled")
        self.assertFalse(pending.exists())
        m.refuse_legacy(self.store, [self.config])

    def test_inflight_legacy_barrier_blocks_acquire_without_sleep(self):
        with self.store.barrier(exclusive=False):
            with self.assertRaisesRegex(m.MaintenanceError, "known_writer_active"):
                self.acquire()
        self.acquire()

    def test_foreign_symlink_mode_and_git_store_refuse(self):
        self.store.root.parent.mkdir(parents=True)
        self.store.root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(m.MaintenanceError):
            self.acquire()
        self.store.root.unlink()
        self.store.root.mkdir(mode=0o755)
        self.store.root.chmod(0o755)  # Exercise unsafe permissions under any caller umask.
        with self.assertRaises(m.MaintenanceError):
            self.acquire()
        self.store.root.chmod(0o700)
        (self.store.root / ".git").mkdir()
        with self.assertRaises(m.MaintenanceError):
            self.acquire()

    def test_mirror_force_dry_run_and_make_refuse_before_config_reads(self):
        self.acquire()
        self.config.parent.mkdir(parents=True)
        self.config.write_text("unparseable synthetic fixture")
        for args in ((), ("--dry-run",)):
            result = self.run_script(ROOT / "_ops/bin/install-mcp.sh", *args,
                                     env={**self.env, "MCP_MIRROR_FORCE": "1"})
            self.assertEqual(result.returncode, 73, result.stderr)
        result = subprocess.run(["make", "-C", str(ROOT), "install-mcp"], env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy writer refused", result.stderr)
        self.assertEqual(self.config.read_text(), "unparseable synthetic fixture")
        self.assertEqual(list(self.config.parent.iterdir()), [self.config])

    def test_snow_all_mutating_entrypoints_refuse_before_package_profile_or_auth(self):
        self.acquire()
        for args in ((), ("install", "snow-kit"), ("install", "snow-kit", "--activate"),
                     ("repin", "snow-kit"), ("repair", "snow-kit"),
                     ("rollback", "snow-kit"), ("uninstall", "snow-kit")):
            result = self.run_script(ROOT / "capabilities/mcp-bootstrap.sh", *args)
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        self.assertFalse((self.home / ".config").exists())
        self.assertFalse((self.home / ".local/share").exists())

    def test_invalid_inherited_descriptor_refuses(self):
        result = self.run_script(ROOT / "_ops/bin/install-mcp.sh",
                                 env={**self.env, m._FD_ENV: "999999"})
        self.assertEqual(result.returncode, 73)

    def test_snow_overrides_cannot_hide_default_kit_write_targets(self):
        self.acquire()
        env = {**self.env, "SNOW_KIT_CODEX_CONFIG": str(self.root / "decoy.toml")}
        for verb in ("install", "rollback", "uninstall"):
            result = self.run_script(ROOT / "capabilities/mcp-bootstrap.sh", verb, "snow-kit", env=env)
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        self.assertFalse((self.home / ".config").exists())

    def test_no_handoff_preserves_legacy_noop(self):
        result = self.run_script(ROOT / "_ops/bin/install-mcp.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to mirror", result.stdout)

    def test_bootstrap_refusal_stops_before_step_five(self):
        fixture = self.root / "bootstrap"
        (fixture / "_ops/bin").mkdir(parents=True)
        (fixture / "capabilities").mkdir()
        shutil.copy2(ROOT / "bootstrap.sh", fixture / "bootstrap.sh")
        for relative in ("capabilities/bootstrap.sh", "_ops/bin/install-dev-awa-overlay.sh", "_ops/bin/install-agent-rules.sh"):
            path = fixture / relative
            path.write_text("#!/bin/bash\nexit 0\n")
            path.chmod(0o700)
        # This fixture isolates the MCP handoff refusal after an accepted source
        # preflight; real source identity/inventory tests live in test_contracts.
        source_guard = fixture / "_ops/interoperability/original_sources.py"
        source_guard.parent.mkdir(parents=True)
        source_guard.write_text("# fixture: source preflight accepted\n")
        (fixture / "_ops/bin/install-mcp.sh").write_text("#!/bin/bash\nexit 73\n")
        (fixture / "capabilities/mcp-bootstrap.sh").write_text("#!/bin/bash\ntouch later-writer\n")
        result = self.run_script(fixture / "bootstrap.sh")
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertNotIn("5/8", result.stdout)
        self.assertFalse((fixture / "later-writer").exists())

if __name__ == "__main__":
    unittest.main()
