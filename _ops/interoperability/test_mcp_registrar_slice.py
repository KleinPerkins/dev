"""Partial D2 safeguards against the exact retained D1 wheel.

Opt in with INT014_D1_WHEEL and INT014_D1_REPOSITORY. No package install, native
control, auth, config discovery or qualification. Synthetic control observations
exist only in this test file and make no claim about server-guard drain.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
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
sys.path.insert(0, str(HERE))
import mcp_maintenance as dev
import mcp_migration as migration

WHEEL, REPOSITORY = os.environ.get("INT014_D1_WHEEL"), os.environ.get("INT014_D1_REPOSITORY")
REVISION = "c" * 40
POLICY = "synthetic/closed-json/v1"


def definition(api):
    return api.RegistrationDefinition.stdio(
        api.SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:partial-test", "d" * 40, "partial-test"),
        command="/opt/fixtures/partial-test", args=("mcp",))


def policy(api):
    # All permitted strings are explicitly source-declared here. This policy is
    # never copied into production or loaded from the operation's persisted data.
    return {"context": {"host": "fixture", "surface": "cursor", "build": "cursor-fixture-v1",
                        "scope": "user", "mapping_version": "cursor-mcp-json/v1",
                        "mapping_digest": migration.ADAPTER_BINDINGS["cursor"]["mapping_digest"]},
            "definitions": [definition(api).to_record()], "auth_binding_ids": [],
            "issuer_source_revision": REVISION,
            "storage": {"anchor": "/private/tmp", "operation_prefix": "int014-registrar-slice-",
                        "fixture_prefix": "kp-mcp-registrar-", "suffix_length": 8,
                        "config_name": "mcp.json", "state_name": "state", "approval_name": "approvals",
                        "maintenance_name": "maintenance"},
            "writers": [{"writer_id": "synthetic-transaction", "kind": "legacy-mirror",
                         "prior_state": "inactive", "observed_state": "inactive",
                         "observation_reference": "synthetic-test-only", "resume_disposition": "remain_suspended",
                         "observation": {"schema": "synthetic-transaction-observation/v1",
                                         "classification": "disposable-test-files-only"}}],
            "consequence": {"schema": "synthetic-consequence/v1", "scope": "disposable-test-files-only",
                            "claim": "coordinated", "native_controls": "none"},
            "guard": {"prior_guard_state": "not_enrolled", "prior_guard_lock": "not_applicable"},
            "actions": ["register", "recover", "rollback", "cancel"],
            "receipt_paths": ["/command", "/args"],
            "config": {"object": {
                "safe_setting": {"boolean": True},
                "mcpServers": {"object": {
                    "partial-test": {"object": {
                        "command": {"enum": ["/opt/fixtures/partial-test"]},
                        "args": {"enum": [["mcp"]]},
                        "disabled": {"boolean": True}}, "required": ["command", "args"]},
                    "safe-sibling": {"object": {"disabled": {"boolean": True}}, "required": ["disabled"]}
                }, "required": []}}, "required": []}}


class IsolatedControls:
    """Synthetic transaction conditions only; never a supported native profile."""
    active = False
    effects = "isolated-test"

    def current(self, evidence, now):
        if (self.active or self.effects != "isolated-test"
            or [w["writer_id"] for w in evidence["known_writers"]] != ["synthetic-transaction"]):
            raise dev.MaintenanceError("concurrency_unqualified")

    def transition(self, evidence, before, after, child):
        # Only permit bookkeeping required to test fresh child recovery. No
        # synthetic terminal handoff is substituted for the missing owner proof.
        if after["status"] != "recovery_required":
            raise dev.MaintenanceError("writer_release_failed")


def bind(api, context, action=None, *, predecessor=None, recovery_of=None):
    from kp_mcp_bootstrap.registrars import maintenance
    from kp_mcp_bootstrap.registrars.contracts import ApprovalAudience, utc_now
    now = utc_now()
    mid = str(uuid.uuid4())
    audience = ApprovalAudience(context.source_owner, context.connection_id, context.host,
                               context.scope, context.target_id, action or api.Action.REGISTER)
    declared = policy(api)
    writer = declared["writers"][0]
    evidence = api.MaintenanceEvidence(
        mid, REVISION, maintenance.ACCEPTED_CONTRACT_DIGEST, dev.digest(audience.to_record()),
        context.target_id, dev.target_id(context.state_directory),
        dev.image_digest(dev.read_image(context.config_path)),
        dev.image_digest(dev.read_image(dev.selected_receipt_path(context), private=True)),
        (api.KnownWriterEvidence(**{k: v for k, v in writer.items() if k != "observation"},
                                 observation_digest=dev.digest(writer["observation"]), observed_at=now),),
        dev.digest(declared["consequence"]), mid, now, now + timedelta(minutes=9), "not_enrolled", "not_applicable",
        predecessor, recovery_of)
    window = replace(context.writer_window, schema="kp-mcp/writer-window/v2",
                     mechanism="coordinated-maintenance", concurrency_claim="coordinated",
                     maintenance_evidence_digest=evidence.digest,
                     qualification_id=maintenance.QUALIFICATION_ID, qualification_digest=maintenance.QUALIFICATION_DIGEST,
                     issuer_owner="KleinPerkins/dev", issuer_source_revision=REVISION,
                     acquisition_reference=mid, acquired_at=now, expires_at=evidence.expires_at,
                     release_method="dev-int014-explicit-handoff/v1")
    return replace(context, schema="kp-mcp/registration-context/v2", writer_window=window,
                   maintenance_evidence=evidence)


def components(bound, root, context, *, original=None):
    checks = dev.RegistrarChecks(POLICY)
    checks.bind(context, definition(bound.registrars))
    approvals = dev.OperationApprovals(root / "approvals", bound.registrars, checks)
    controls = IsolatedControls()
    observed = dev.CheckedObservations(checks, approvals, controls, original_operation_id=original)
    store = dev.MaintenanceStore(root / "maintenance")
    validator = dev.MaintenanceValidator(store, REVISION, observed)
    ops = migration.MaintenanceOperations(bound, validator, checks, host="cursor", approvals=approvals)
    return SimpleNamespace(checks=checks, approvals=approvals, controls=controls, observed=observed,
                           store=store, validator=validator, ops=ops, context=context, root=root)


def acquire(case):
    case.store.acquire(case.context.maintenance_evidence.to_record(), case.observed,
                       config_path=case.context.config_path, state_directory=case.context.state_directory)


def approve(case, prepared):
    # Explicit synthetic decision transport; production code never calls this.
    return case.approvals.accept(prepared, case.approvals.proposal(prepared))


def recovery_required(case):
    mid = case.context.maintenance_evidence.maintenance_id
    state = case.store.read(mid)["state"]
    case.store.transition(mid, dev.digest(state), status="recovery_required",
                          registrar_result_reference=None, baseline_handoff_reference=None,
                          release_observation_digest=None, observations=case.observed)


def fresh_process(spec_path):
    bound = migration.load_maintenance_api(Path(WHEEL), Path(REPOSITORY))
    api = bound.registrars
    from kp_mcp_bootstrap.registrars import maintenance
    from kp_mcp_bootstrap.registrars.contracts import context_from_record
    spec = json.loads(Path(spec_path).read_bytes())
    with patch.object(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION})), \
         patch.object(dev, "NONSECRET_POLICIES", {POLICY: policy(api)}):
        context = context_from_record(spec["context"])
        case = components(bound, Path(spec["root"]), context, original=spec.get("original"))
        source = definition(api) if spec["definition_present"] else None
        prepared = case.ops.load(spec["record_id"], context=context, definition=source)
        if spec["action"] == "apply":
            result = case.ops.apply(prepared, case.approvals.load(prepared))
        elif spec["action"] == "recover":
            secondary = case.ops.prepare_recovery(prepared, api.RecoveryDisposition.COMPLETE, context=context)
            result = case.ops.recover(secondary, api.RecoveryDisposition.COMPLETE, approve(case, secondary))
        elif spec["action"] == "cancel":
            secondary = case.ops.prepare_cancel(prepared, context=context)
            result = case.ops.apply(secondary, approve(case, secondary))
        else:
            reference = api.OperationRef(api.OperationRefKind.COMMITTED_RECEIPT,
                                         prepared.operation_id, context.target_id, context.state_directory)
            secondary = case.ops.prepare(case.ops.rollback(reference, context=context, definition=definition(api)))
            result = case.ops.apply(secondary, approve(case, secondary))
        print(result.outcome.value)


@unittest.skipUnless(WHEEL and REPOSITORY, "explicit retained D1 wheel and owner Git source required")
class RegistrarSlice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bound = migration.load_maintenance_api(Path(WHEEL), Path(REPOSITORY))
        cls.api = cls.bound.registrars

    @contextmanager
    def example(self, seed=None, *, acquired=True):
        from kp_mcp_bootstrap.registrars import maintenance
        with tempfile.TemporaryDirectory(prefix="int014-registrar-slice-", dir="/private/tmp") as name, \
             patch.object(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION})), \
             patch.object(dev, "NONSECRET_POLICIES", {POLICY: policy(self.api)}):
            root = Path(name).resolve()
            root.chmod(0o700)
            with self.api.fixture_context(self.api.CursorRegistrar(), definition(self.api), fixture_root=root) as fixture:
                if seed is not None:
                    fixture.config_path.write_bytes(seed)
                context = bind(self.api, fixture.context)
                case = components(self.bound, root, context)
                if acquired:
                    acquire(case)
                yield case

    def prepared(self, case):
        return case.ops.prepare(case.ops.preview(case.context, definition(self.api)))

    def child(self, case, prepared, action):
        ref = case.checks.original_reference(prepared.record_id)
        recovery_required(case)
        context = bind(self.api, case.context, action,
                       predecessor=case.context.maintenance_evidence.maintenance_id, recovery_of=ref["reference"])
        child = components(self.bound, case.root, context, original=prepared.record_id)
        acquire(child)
        return child

    def run_fresh(self, case, prepared, action):
        from kp_mcp_bootstrap.registrars.contracts import canonical_json_bytes
        path = case.root / "fresh-process.json"
        path.write_bytes(canonical_json_bytes(dict(root=str(case.root), context=case.context.to_record(),
                         record_id=prepared.record_id, action=action, original=case.observed.original_operation_id,
                         definition_present=prepared._definition is not None)))
        path.chmod(0o600)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--fresh", str(path)],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_real_prepare_apply_fresh_reload_and_phase_images(self):
        seed = b'{"safe_setting":false,"mcpServers":{"safe-sibling":{"disabled":true}}}'
        with self.example(seed) as c:
            prepared = self.prepared(c)
            approval = approve(c, prepared)
            result = c.ops.apply(prepared, approval)
            self.assertEqual(result.outcome, self.api.Outcome.APPLIED)
            self.assertEqual(json.loads(c.context.config_path.read_bytes())["safe_setting"], False)
            self.assertEqual(self.run_fresh(c, prepared, "apply"), "no_change")
            self.assertEqual(result.concurrency_claim, "coordinated")
            self.assertEqual(c.store.read(c.context.maintenance_evidence.maintenance_id)["state"]["status"], "acquired")

    def test_copied_maintenance_store_cannot_replay_acquired_state(self):
        with self.example() as c:
            preview = c.ops.preview(c.context, definition(self.api))
            copied = dev.MaintenanceStore(c.root / "unapproved-maintenance-path")
            shutil.copytree(c.store.root, copied.root)
            recovery_required(c)
            with self.assertRaises((self.api.RegistrarError, dev.MaintenanceError)):
                self.prepared(c)
            validator = dev.MaintenanceValidator(copied, REVISION, c.observed)
            ops = migration.MaintenanceOperations(self.bound, validator, c.checks,
                                                  host="cursor", approvals=c.approvals)
            mid = c.context.maintenance_evidence.maintenance_id
            record = copied.read(mid)
            # A genuine interrupted-transition envelope can be previewed without
            # authority; applying it must still bind the canonical state root.
            pending = (f".pending-{mid}.{dev.digest(record['evidence'])}."
                       f"{dev.digest(record)}.synthetic")
            (copied.root / pending).write_bytes(b"synthetic-interrupted-write")
            (copied.root / pending).chmod(0o600)
            repair = copied.pending_preview(pending, record["evidence"])
            before = {p.name: p.read_bytes() for p in copied.root.iterdir()}
            for call in (
                lambda: ops.preview(c.context, definition(self.api)),
                lambda: ops.prepare(preview),
                lambda: copied.transition(mid, dev.digest(record["state"]), status="recovery_required",
                    registrar_result_reference=None, baseline_handoff_reference=None,
                    release_observation_digest=None, observations=c.observed),
                lambda: copied.recover_pending(repair, record["evidence"], c.observed),
            ):
                with self.assertRaises(dev.MaintenanceError):
                    call()
                self.assertEqual({p.name: p.read_bytes() for p in copied.root.iterdir()}, before)
            self.assertEqual(c.store.read(mid)["state"]["status"], "recovery_required")
            self.assertFalse(list(c.context.state_directory.glob("*.json")))

    def test_validator_rechecks_store_location_inside_an_existing_operation(self):
        with self.example() as c:
            copied = dev.MaintenanceStore(c.root / "unapproved-maintenance-path")
            shutil.copytree(c.store.root, copied.root)
            recovery_required(c)
            with c.validator.operation():
                c.validator.store = copied
                try:
                    with self.assertRaises(self.api.RegistrarError):
                        c.ops.registrar.preview(c.context.config_path, definition(self.api), context=c.context)
                finally:
                    c.validator.store = c.store
            self.assertFalse(list(c.context.state_directory.glob("*.json")))

    def test_whole_file_unclassified_and_secret_siblings_refuse_before_prepare(self):
        for seed in (b'{"sibling":{"token":"synthetic-secret"}}', b'{"unknown":true}',
                     b'{"safe_setting":"synthetic-secret"}', b'{"safe_setting":true,"safe_setting":false}',
                     b'{"safe_setting":true} /* synthetic secret comment */'):
            with self.subTest(seed=seed), self.example(seed) as c:
                with self.assertRaises((self.api.RegistrarError, dev.MaintenanceError)):
                    self.prepared(c)
                self.assertFalse(list(c.context.state_directory.glob("*.json")))
                self.assertEqual(c.context.config_path.read_bytes(), seed)

    def test_exact_approval_rejects_wrong_fields_and_replay(self):
        with self.example() as c:
            prepared = self.prepared(c)
            proposal = c.approvals.proposal(prepared)
            for key in ("operation_id", "action_digest", "prepared_payload_digest", "maintenance_id",
                        "maintenance_evidence_digest", "consequence_review_digest", "audience", "decision"):
                wrong = {**proposal, key: "wrong"}
                with self.subTest(key=key), self.assertRaises(dev.MaintenanceError):
                    c.approvals.accept(prepared, wrong)
            with self.assertRaises(dev.MaintenanceError):
                c.approvals.accept(prepared, True)
            approval = approve(c, prepared)
            self.assertEqual(c.approvals.load(prepared), approval)
            with self.assertRaises(self.api.RegistrarError):
                c.ops.apply(prepared, replace(approval, issuer_reference=str(uuid.uuid4())))
            self.assertFalse(c.context.config_path.exists())

    def test_phase_images_refuse_actual_changed_config_and_selected_receipt(self):
        with self.example() as c:
            prepared = self.prepared(c)
            approval = approve(c, prepared)
            c.context.config_path.write_text('{"safe_setting":true}')
            with self.assertRaises(self.api.RegistrarError):
                c.ops.apply(prepared, approval)
            self.assertEqual(c.context.config_path.read_text(), '{"safe_setting":true}')
        with self.example() as c:
            prepared = self.prepared(c)
            self.assertEqual(c.ops.apply(prepared, approve(c, prepared)).outcome, self.api.Outcome.APPLIED)
            receipt = dev.selected_receipt_path(c.context)
            receipt.write_bytes(b'{}\n')
            with self.assertRaises(self.api.RegistrarError):
                c.ops.apply(prepared, c.approvals.load(prepared))

    def test_source_mismatch_and_unknown_policy_refuse(self):
        with self.example() as c:
            with self.assertRaises(dev.MaintenanceError):
                c.ops.preview(replace(c.context, source_revision="e" * 40), definition(self.api))
            with self.assertRaises(dev.MaintenanceError):
                dev.RegistrarChecks("operator-supplied-digest")
            with self.assertRaises(migration.MigrationError):
                migration.open_maintenance_operation(control_profile="synthetic-transaction")
            self.assertFalse(list(c.context.state_directory.glob("*.json")))

    def test_writer_restart_and_unbounded_effects_still_refuse(self):
        for attribute, value in (("active", True), ("effects", "unknown"), ("effects", "excluded")):
            with self.example() as c:
                prepared = self.prepared(c)
                approval = approve(c, prepared)
                setattr(c.controls, attribute, value)
                with self.assertRaises(self.api.RegistrarError):
                    c.ops.apply(prepared, approval)
                self.assertFalse(c.context.config_path.exists())

    def test_fresh_process_recovery_after_partial_failure(self):
        for phase in ("journal_prepared", "config_replaced", "receipt_verified"):
            with self.subTest(phase=phase), self.example() as c:
                prepared = self.prepared(c)
                def interrupt(step):
                    if step == phase:
                        raise RuntimeError("synthetic interruption")
                with patch.object(c.ops.registrar, "_fault", interrupt):
                    self.assertEqual(c.ops.apply(prepared, approve(c, prepared)).outcome, self.api.Outcome.RECOVERY_REQUIRED)
                child = self.child(c, prepared, self.api.Action.RECOVER)
                self.assertEqual(self.run_fresh(child, prepared, "recover"), "recovered")
                self.assertTrue(c.context.config_path.exists())

    def test_fresh_process_cancel_and_exact_inverse(self):
        for action in ("cancel", "rollback"):
            with self.subTest(action=action), self.example() as c:
                prepared = self.prepared(c)
                if action == "rollback":
                    c.ops.apply(prepared, approve(c, prepared))
                child = self.child(c, prepared, self.api.Action.CANCEL if action == "cancel" else self.api.Action.ROLLBACK)
                self.assertEqual(self.run_fresh(child, prepared, action), "cancelled" if action == "cancel" else "rolled_back")
                self.assertFalse(c.context.config_path.exists())
                self.assertEqual(c.store.read(c.context.maintenance_evidence.maintenance_id)["state"]["status"], "recovery_required")

    def test_lineage_wrong_original_or_competing_child_refuses(self):
        with self.example() as c:
            prepared = self.prepared(c)
            c.ops.apply(prepared, approve(c, prepared))
            child = self.child(c, prepared, self.api.Action.ROLLBACK)
            wrong = bind(self.api, child.context, self.api.Action.ROLLBACK,
                         predecessor=c.context.maintenance_evidence.maintenance_id, recovery_of="f" * 64)
            other = components(self.bound, c.root, wrong, original=prepared.record_id)
            with self.assertRaises(dev.MaintenanceError):
                acquire(other)
            with self.assertRaises(dev.MaintenanceError):
                c.checks.lineage(wrong.maintenance_evidence.to_record(), c.store.read(c.context.maintenance_evidence.maintenance_id), prepared.record_id)

    def test_interrupted_inverse_recovers_in_fresh_process(self):
        with self.example() as c:
            forward = self.prepared(c)
            c.ops.apply(forward, approve(c, forward))
            reference = c.ops.operation_ref(forward)
            child = self.child(c, forward, self.api.Action.ROLLBACK)
            inverse = child.ops.prepare(child.ops.rollback(reference, context=child.context, definition=definition(self.api)))
            def interrupt(step):
                if step == "config_replaced":
                    raise RuntimeError("synthetic inverse interruption")
            with patch.object(child.ops.registrar, "_fault", interrupt):
                self.assertEqual(child.ops.apply(inverse, approve(child, inverse)).outcome, self.api.Outcome.RECOVERY_REQUIRED)
            grandchild = self.child(child, inverse, self.api.Action.RECOVER)
            self.assertEqual(self.run_fresh(grandchild, inverse, "recover"), "recovered")
            self.assertFalse(c.context.config_path.exists())

    def test_exact_inverse_refuses_unrelated_later_edit(self):
        with self.example() as c:
            prepared = self.prepared(c)
            c.ops.apply(prepared, approve(c, prepared))
            reference = c.ops.operation_ref(prepared)
            contents = json.loads(c.context.config_path.read_bytes())
            contents["safe_setting"] = True
            c.context.config_path.write_bytes(dev.canonical(contents))
            child = self.child(c, prepared, self.api.Action.ROLLBACK)
            with self.assertRaises(self.api.RegistrarError):
                child.ops.prepare(child.ops.rollback(reference, context=child.context, definition=definition(self.api)))
            self.assertTrue(json.loads(c.context.config_path.read_bytes())["safe_setting"])

    def test_loader_wrong_bytes_and_changed_policy_refuse(self):
        with self.example() as c:
            wrong = c.root / "wrong.whl"
            wrong.write_bytes(b"not the retained owner artifact")
            with self.assertRaises(migration.MigrationError):
                migration.load_maintenance_api(wrong, Path(REPOSITORY))
            preview = c.ops.preview(c.context, definition(self.api))
            changed = deepcopy(policy(self.api))
            changed["config"]["object"]["unreviewed"] = {"boolean": True}
            with patch.object(dev, "NONSECRET_POLICIES", {POLICY: changed}), self.assertRaises(dev.MaintenanceError):
                c.ops.prepare(preview)
            self.assertFalse(list(c.context.state_directory.glob("*.json")))

    def forged_context(self, context, edit):
        from kp_mcp_bootstrap.registrars.contracts import canonical_json_bytes, context_from_record
        row = json.loads(canonical_json_bytes(context.to_record()))
        edit(row)
        e, w = row["maintenance_evidence"], row["writer_window"]
        e["config_target_id"] = dev.target_id(Path(row["config_path"]))
        e["state_target_id"] = dev.target_id(Path(row["state_directory"]))
        e["audience_digest"] = dev.digest({k: row[k] for k in ("source_owner", "connection_id", "host", "scope")} |
                                          {"target_id": e["config_target_id"], "action": "register"})
        w.update({k: row[k] for k in ("host", "surface", "build", "mapping_digest")})
        w.update(config_target_id=e["config_target_id"], state_target_id=e["state_target_id"],
                 maintenance_evidence_digest=dev.digest(e))
        row.update(maintenance_evidence_digest=dev.digest(e), writer_window_digest=dev.digest(w))
        return context_from_record(row)

    def assert_no_operation_persistence(self, c):
        self.assertFalse(c.store.root.exists())
        self.assertFalse(c.approvals.root.exists())
        self.assertEqual(list(c.context.state_directory.iterdir()), [])
        self.assertFalse(list(c.root.rglob("*.json")))

    def test_all_free_text_metadata_rejects_markers_before_any_persistence(self):
        marker = "synthetic-secret-observation-reference"
        edits = []
        for key in ("writer_id", "observation_reference"):
            edits.append(("writer." + key, lambda r, key=key: r["maintenance_evidence"]["known_writers"][0].__setitem__(key, marker)))
        for key in ("source_owner", "connection_id", "source_revision", "host", "surface", "build", "scope", "mapping_version", "policy_validator_id"):
            edits.append(("context." + key, lambda r, key=key: r.__setitem__(key, marker)))
        for key in ("qualification_id", "issuer_owner", "release_method"):
            edits.append(("window." + key, lambda r, key=key: r["writer_window"].__setitem__(key, marker)))
        for label, edit in edits:
            with self.subTest(field=label), self.example(acquired=False) as c:
                # Classification must stand independently of the test control's
                # writer-name check. No native observation is being simulated.
                with patch.object(c.controls, "current", lambda *_: None), \
                     self.assertRaises((dev.MaintenanceError, self.api.RegistrarError, ValueError)):
                    forged = self.forged_context(c.context, edit)
                    c.checks.bind(forged, definition(self.api))
                    c.context = forged
                    acquire(c)
                    self.prepared(c)
                self.assert_no_operation_persistence(c)

    def test_acquire_revalidates_evidence_before_creating_maintenance_root(self):
        for key in ("writer_id", "observation_reference"):
            with self.subTest(field=key), self.example(acquired=False) as c:
                e = deepcopy(c.context.maintenance_evidence.to_record())
                e["known_writers"][0][key] = "synthetic-secret-metadata"
                with patch.object(c.controls, "current", lambda *_: None), self.assertRaises(dev.MaintenanceError):
                    c.store.acquire(e, c.observed, config_path=c.context.config_path,
                                    state_directory=c.context.state_directory)
                self.assert_no_operation_persistence(c)

    def test_unapproved_canonical_target_paths_refuse_without_writes(self):
        edits = [
            lambda r: r.__setitem__("config_path", str(Path(r["config_path"]).with_name("synthetic-secret-config.json"))),
            lambda r: r.__setitem__("state_directory", str(Path(r["state_directory"]).with_name("synthetic-secret-state"))),
            lambda r: r.update(config_path="/private/tmp/unapproved/mcp.json", state_directory="/private/tmp/unapproved/state"),
        ]
        for edit in edits:
            with self.subTest(edit=edit), self.example(acquired=False) as c:
                with self.assertRaises((dev.MaintenanceError, self.api.RegistrarError, ValueError)):
                    forged = self.forged_context(c.context, edit)
                    c.checks.bind(forged, definition(self.api))
                    c.context = forged
                    acquire(c)
                    self.prepared(c)
                self.assert_no_operation_persistence(c)

    def test_unapproved_digest_bindings_and_maintenance_storage_refuse(self):
        for key in ("observation_digest", "consequence_review_digest", "config_preimage_digest", "state_preimage_digest"):
            with self.subTest(field=key), self.example(acquired=False) as c:
                def edit(row):
                    target = row["maintenance_evidence"]
                    if key == "observation_digest":
                        target = target["known_writers"][0]
                    target[key] = "f" * 64
                with self.assertRaises((dev.MaintenanceError, self.api.RegistrarError)):
                    forged = self.forged_context(c.context, edit)
                    c.checks.bind(forged, definition(self.api))
                    c.context = forged
                    acquire(c)
                self.assert_no_operation_persistence(c)
        with self.example(acquired=False) as c:
            wrong = dev.MaintenanceStore(c.root / "synthetic-secret-maintenance-path")
            with self.assertRaises(dev.MaintenanceError):
                wrong.acquire(c.context.maintenance_evidence.to_record(), c.observed,
                              config_path=c.context.config_path, state_directory=c.context.state_directory)
            self.assertFalse(wrong.root.exists())
            self.assert_no_operation_persistence(c)

    def test_prepare_and_approval_recheck_metadata_after_acquisition(self):
        with self.example() as c:
            preview = c.ops.preview(c.context, definition(self.api))
            forged = self.forged_context(c.context, lambda r: r["maintenance_evidence"]["known_writers"][0].__setitem__(
                "observation_reference", "synthetic-secret-after-acquisition"))
            poisoned = replace(preview, _private=replace(preview._private, context=forged))
            before = {p: p.read_bytes() for p in c.root.rglob("*.json")}
            with self.assertRaises(dev.MaintenanceError):
                c.ops.prepare(poisoned)
            self.assertEqual(before, {p: p.read_bytes() for p in c.root.rglob("*.json")})
            prepared = self.prepared(c)
            poisoned = replace(prepared, _context=forged)
            with self.assertRaises(dev.MaintenanceError):
                c.approvals.accept(poisoned, {})
            self.assertFalse(c.approvals.root.exists())
            wrong_store = dev.OperationApprovals(c.root / "synthetic-secret-approval-path", self.api, c.checks)
            with self.assertRaises(dev.MaintenanceError):
                wrong_store.accept(prepared, c.approvals.proposal(prepared))
            self.assertFalse(wrong_store.root.exists())


class IndependentSafety(unittest.TestCase):
    def test_production_tables_remain_empty(self):
        self.assertEqual(dict(dev.NONSECRET_POLICIES), {})
        self.assertEqual(migration.SUPPORTED_CONTROL_PROFILES, ())
        with self.assertRaises(migration.MigrationError):
            migration.open_maintenance_operation(control_profile="native")

    def test_closed_policy_has_no_arbitrary_string_or_unknown_field_escape(self):
        rule = {"object": {"mode": {"enum": ["read-only"]}, "enabled": {"boolean": True}}, "required": ["mode"]}
        dev._schema_value({"mode": "read-only", "enabled": False}, rule)
        for value in ({"mode": "synthetic-secret"}, {"mode": "read-only", "unknown": "synthetic-secret"},
                      {"mode": "read-only", "enabled": 1}, {"enabled": True}):
            with self.subTest(value=value), self.assertRaises(dev.MaintenanceError):
                dev._schema_value(value, rule)
        with self.assertRaises(dev.MaintenanceError):
            dev._schema_value("synthetic-secret", {"string": True})

    def test_nonregular_image_and_alias_refuse(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            target = root / "config"
            target.write_bytes(b"{}")
            alias = root / "alias"
            alias.symlink_to(target)
            with self.assertRaises(dev.MaintenanceError):
                dev.read_image(alias)
            with self.assertRaises(dev.MaintenanceError):
                dev.read_image(root)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fresh":
        fresh_process(sys.argv[2])
    else:
        unittest.main()
