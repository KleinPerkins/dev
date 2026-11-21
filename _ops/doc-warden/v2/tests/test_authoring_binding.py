"""Offline authoring preview/runtime drift and central-authority regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

from doc_warden.adrs import preview_adr_draft
from doc_warden.artifacts import apply_preview, consent_for, draft_artifact, repository_profile
from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.cli import main, _authoring_preview_json, _load_authoring_preview
from doc_warden.gsd_adapter import (
    CENTRAL_REPOSITORY_ID, CENTRAL_REPOSITORY_KEY, CENTRAL_SELECTOR,
    AuthoringScope, AuthoringResult, prepare_authoring_import, validate_authoring_result,
)
from doc_warden.operation_store import load_preview
from fixture_factory import FixtureFactory

ROOT = Path(__file__).resolve().parents[4]


class AuthoringBindingTests(unittest.TestCase):
    def setUp(self):
        self.private = tempfile.TemporaryDirectory(prefix='authoring-binding-')
        self.addCleanup(self.private.cleanup)
        self.state = Path(self.private.name)
        template = self.state / 'empty-template';template.mkdir()
        self.environment = patch.dict(os.environ, {
            'XDG_STATE_HOME': str(self.state / 'state'),
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_COUNT': '3',
            'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': os.devnull,
            'GIT_CONFIG_KEY_1': 'init.templateDir', 'GIT_CONFIG_VALUE_1': str(template),
            'GIT_CONFIG_KEY_2': 'commit.gpgsign', 'GIT_CONFIG_VALUE_2': 'false',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': '',
        })
        self.environment.start();self.addCleanup(self.environment.stop)
        self.fixture = FixtureFactory.create();self.addCleanup(self.fixture.cleanup)
        self.repo = self.fixture.repo.resolve()
        owner = FixtureFactory.create('central-authority')
        self.addCleanup(owner.cleanup)
        self.authority = owner.repo.resolve()
        relatives = ['_ops/doc-warden/POLICY.md', '_ops/doc-warden/triggers.v2.json',
                     '_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json',
                     '_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json']
        relatives += [str(p.relative_to(ROOT)) for p in (ROOT / '_ops/doc-warden/schemas/v2').glob('*.schema.json')]
        for relative in relatives:
            path = self.authority / relative;path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        (self.authority / '.planning/doc-warden.json').write_bytes(canonical_json(repository_profile(
            self.authority, CENTRAL_REPOSITORY_KEY, github_repository_id=CENTRAL_REPOSITORY_ID,
        )))
        owner.approve_prd('REQ-001')
        plan = draft_artifact('plan', {
            'title': 'Current owner plan', 'lifecycle': 'approved',
            'approval': {'actor': 'fixture', 'date': '2026-01-01'},
        }, repo=self.authority)
        apply_preview(plan, consent_for(plan.transaction))
        self.central_plan = self.authority / plan.artifact_path
        self.central_plan_digest = digest_ref(self.central_plan.read_bytes())
        body = '# Select fixture plan\n\nUse the approved current fixture plan.\n'
        decision = preview_adr_draft({
            'title': 'Select fixture plan', 'body': body,
            'approval': {'actor': 'fixture', 'date': '2026-01-01', 'review_sha256': digest_ref(body.encode())[7:]},
            'parents': {
                'observed_at': '2026-01-01T00:10:00Z',
                'parents': [{'kind': 'plan', 'id': plan.artifact_id, 'version': 1,
                             'digest': self.central_plan_digest}],
            },
        }, repo=self.authority)
        apply_preview(decision, consent_for(decision.transaction))
        self.selector = self.authority / CENTRAL_SELECTOR
        self.selector.write_bytes(canonical_json({
            'schema': 'doc-warden/current-plan-authority/v1', 'repository_key': CENTRAL_REPOSITORY_KEY,
            'github_repository_id': CENTRAL_REPOSITORY_ID, 'plan_id': plan.artifact_id, 'plan_version': 1,
            'plan_receipt_id': plan.transaction.operation_id, 'decision_id': decision.artifact_id,
        }))
        self.profile = self.repo / '.planning/doc-warden.json'
        self.profile.write_bytes(canonical_json(repository_profile(self.repo, self.fixture.repository_key,
                                                                   binding_root=self.authority)))
        self.pin = self.authority / '_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json'
        self.interface = self.pin.with_name('runtime-interface.v1.json')

    def prepare(self, central=True, **kwargs):
        return prepare_authoring_import(AuthoringScope(repo=self.repo, operation_id=str(uuid.uuid4()),
            binding_root=self.authority if central else None, **kwargs))

    def result(self, preview, outputs=None):
        return AuthoringResult(preview.source_revision, preview.pin_digest,
                               outputs or {'.planning/STATE.md': b'synthetic authoring state\n'}, True)

    def test_central_prepare_needs_no_repository_local_runtime_copy(self):
        shutil.rmtree(self.repo / '_ops/doc-warden/runtime')
        before = self.profile.read_bytes()
        preview = self.prepare()
        self.assertEqual(preview.binding_root, str(self.authority.resolve()))
        self.assertEqual(preview.profile_digest, digest_ref(before))
        self.assertEqual(preview.authority_bindings['gsd_pin_digest'], preview.pin_digest)
        self.assertEqual(preview.authority_bindings['approved_plan_digest'], self.central_plan_digest)
        self.assertNotEqual(preview.authority_bindings['policy_digest'], 'sha256:' + '0'*64)
        self.assertEqual(self.profile.read_bytes(), before)

    def test_central_result_binds_receipt_and_preserves_exact_replay(self):
        index = (self.repo / '.git/index').read_bytes()
        preview = self.prepare();plan = validate_authoring_result(preview, self.result(preview))
        consent = consent_for(plan.transaction)
        first = apply_preview(plan.transaction, consent)
        self.assertEqual(first['bindings'], preview.authority_bindings)
        self.assertEqual(apply_preview(plan.transaction, consent), first)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)

    def test_legacy_v1_preview_and_missing_optional_active_plan_roundtrip(self):
        preview = self.prepare(central=False);raw = _authoring_preview_json(preview)
        self.assertEqual(raw['schema'], 'doc-warden/authoring-import-preview/v1')
        self.assertNotIn('binding_root', raw)
        raw.pop('active_plan_id');raw.pop('preview_digest')
        raw['preview_digest'] = digest_ref(canonical_json(raw))
        path = self.state / 'preview.json';path.write_bytes(canonical_json(raw))
        self.assertIsNone(_load_authoring_preview(self.repo, path).binding_root)

    def test_central_v2_preview_roundtrip_and_unknown_field_refusal(self):
        preview = self.prepare();raw = _authoring_preview_json(preview)
        self.assertEqual(raw['schema'], 'doc-warden/authoring-import-preview/v2')
        path = self.state / 'preview.json';path.write_bytes(canonical_json(raw))
        self.assertEqual(_load_authoring_preview(self.repo, path), preview)
        raw['unreviewed_authority'] = True;raw.pop('preview_digest')
        raw['preview_digest'] = digest_ref(canonical_json(raw));path.write_bytes(canonical_json(raw))
        with self.assertRaisesRegex(ValueError, 'contract_invalid'):_load_authoring_preview(self.repo, path)

    def test_runtime_file_drift_after_prepare_refuses_for_both_binding_modes(self):
        for central in (False, True):
            for name in ('gsd-core-pin.json', 'runtime-interface.v1.json'):
                with self.subTest(central=central, name=name):
                    preview = self.prepare(central=central)
                    base = self.authority if central else self.repo
                    path = base / '_ops/doc-warden/runtime/gsd-core' / name
                    before = path.read_bytes();path.write_bytes(before + b'\n')
                    try:
                        with self.assertRaisesRegex(ValueError, 'wrong_gsd_pin'):
                            validate_authoring_result(preview, self.result(preview))
                    finally:path.write_bytes(before)

    def test_runtime_file_drift_after_validation_refuses_before_output_write(self):
        for name in ('gsd-core-pin.json', 'runtime-interface.v1.json'):
            with self.subTest(name=name):
                preview = self.prepare();plan = validate_authoring_result(preview, self.result(preview))
                path = self.pin.with_name(name);before = path.read_bytes();path.write_bytes(before + b'\n')
                try:
                    with self.assertRaisesRegex(ValueError, 'observed_input_drift'):
                        apply_preview(plan.transaction, consent_for(plan.transaction))
                    self.assertFalse((self.repo / '.planning/STATE.md').exists())
                finally:path.write_bytes(before)

    def test_input_and_frozen_file_drift_after_validation_refuse(self):
        for field in ('input_paths', 'frozen_paths'):
            with self.subTest(field=field):
                path = self.repo / '.planning/PROJECT.md';path.write_bytes(b'before\n')
                preview = self.prepare(**{field: ('.planning/PROJECT.md',)})
                plan = validate_authoring_result(preview, self.result(preview));path.write_bytes(b'changed\n')
                with self.assertRaisesRegex(ValueError, 'observed_input_drift'):
                    apply_preview(plan.transaction, consent_for(plan.transaction))
                self.assertFalse((self.repo / '.planning/STATE.md').exists())

    def test_co_written_input_uses_preimage_and_keeps_receipt_replay(self):
        path = self.repo / '.planning/PROJECT.md';path.write_bytes(b'before\n')
        preview = self.prepare(input_paths=('.planning/PROJECT.md',))
        plan = validate_authoring_result(preview, self.result(preview, {'.planning/PROJECT.md': b'after\n'}))
        consent = consent_for(plan.transaction);receipt = apply_preview(plan.transaction, consent)
        self.assertEqual(apply_preview(plan.transaction, consent), receipt)
        self.assertEqual(path.read_bytes(), b'after\n')

    def test_central_authority_drift_after_prepare_refuses(self):
        preview = self.prepare();path = self.authority / '_ops/doc-warden/POLICY.md'
        path.write_bytes(path.read_bytes() + b'\nfixture drift\n')
        with self.assertRaisesRegex(ValueError, 'authoring_authority_changed'):
            validate_authoring_result(preview, self.result(preview))

    def test_schema_set_drift_after_validation_refuses(self):
        preview = self.prepare();plan = validate_authoring_result(preview, self.result(preview))
        path = self.authority / '_ops/doc-warden/schemas/v2/extra.schema.json';path.write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError, 'observed_input_drift'):
            apply_preview(plan.transaction, consent_for(plan.transaction))

    def test_missing_authority_does_not_fall_back_to_zero_bindings(self):
        self.selector.unlink()
        with self.assertRaisesRegex(ValueError, 'authoring_authority_unavailable'):self.prepare()

    def test_selection_rejects_wrong_owner_missing_receipt_or_changed_sidecar(self):
        selector = json.loads(self.selector.read_bytes())
        for field, value, code in (
            ('github_repository_id', 145, 'authoring_authority_selector_invalid'),
            ('plan_receipt_id', str(uuid.uuid4()), 'authoring_authority_selector_mismatch'),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code):
                self.selector.write_bytes(canonical_json(selector | {field: value}))
                self.prepare()
        self.selector.write_bytes(canonical_json(selector))
        sidecar = self.central_plan.with_suffix('.governance.json')
        sidecar.write_bytes(sidecar.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'authority_freeze_mismatch'):
            self.prepare()

    def test_prepare_refuses_a_selected_plan_after_an_approved_successor(self):
        selector = json.loads(self.selector.read_bytes())
        successor = draft_artifact('plan', {
            'title': 'Successor plan', 'lifecycle': 'approved', 'version': 2, 'supersedes': selector['plan_id'],
            'approval': {'actor': 'fixture', 'date': '2026-01-01'},
        }, repo=self.authority)
        apply_preview(successor, consent_for(successor.transaction))
        with self.assertRaisesRegex(ValueError, 'authority_artifact_required'):
            self.prepare()

    def test_symlinked_runtime_binding_refuses(self):
        original = self.state / 'pin.json';original.write_bytes(self.pin.read_bytes())
        self.pin.unlink();self.pin.symlink_to(original)
        with self.assertRaises(ValueError):self.prepare()

    def test_profile_must_exist_be_enabled_and_match_runtime_bindings(self):
        original = json.loads(self.profile.read_bytes())
        for field, value in (('enabled', False), ('gsd_pin_digest', 'sha256:'+'0'*64),
                             ('gsd_interface_digest', 'sha256:'+'0'*64)):
            with self.subTest(field=field):
                self.profile.write_bytes(canonical_json(dict(original, **{field: value})))
                with self.assertRaises(ValueError):self.prepare()
        self.profile.unlink()
        with self.assertRaisesRegex(ValueError, 'v2_repository_profile_required'):self.prepare()

    def test_profile_drift_after_validation_refuses(self):
        preview = self.prepare();plan = validate_authoring_result(preview, self.result(preview))
        value = json.loads(self.profile.read_bytes());value['maintenance']['last_checked_revision'] = 'b'*40
        self.profile.write_bytes(canonical_json(value))
        with self.assertRaisesRegex(ValueError, 'observed_input_drift'):
            apply_preview(plan.transaction, consent_for(plan.transaction))

    def test_cli_central_prepare_validate_and_stored_apply_route(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['prepare-authoring', '--repo', str(self.repo), '--operation-id', str(uuid.uuid4()),
                                   '--binding-root', str(self.authority)]), 0)
        raw = json.loads(output.getvalue());path = self.state / 'preview.json';path.write_bytes(canonical_json(raw))
        state = self.repo / '.planning/STATE.md';state.write_bytes(b'synthetic authored state\n')
        result = {'source_revision': raw['source_revision'], 'pin_digest': raw['pin_digest'],
                  'changed_file_digests': {'.planning/STATE.md': digest_ref(state.read_bytes())},
                  'checker_passed': True, 'commands': [], 'assumptions_changed': False}
        result_path = self.state / 'result.json';result_path.write_bytes(canonical_json(result))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['validate-authoring', '--repo', str(self.repo), '--preview', str(path),
                                   '--result', str(result_path)]), 0)
        value = json.loads(output.getvalue());self.assertTrue(value['consent_required'])
        transaction = load_preview(value['operation_id'], value['action_digest'])
        consent = self.state / 'consent.json';consent.write_bytes(canonical_json(consent_for(transaction)))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['apply', '--operation-id', value['operation_id'], '--action-digest', value['action_digest'],
                                   '--consent-envelope', str(consent)]), 0)

    def test_local_runtime_drift_after_prepare_refuses_without_central_feature(self):
        preview = prepare_authoring_import(AuthoringScope(repo=self.repo, operation_id=str(uuid.uuid4())))
        path = self.repo / '_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'wrong_gsd_pin'):
            validate_authoring_result(preview, self.result(preview))

    def test_local_runtime_drift_after_validation_refuses_without_central_feature(self):
        preview = prepare_authoring_import(AuthoringScope(repo=self.repo, operation_id=str(uuid.uuid4())))
        plan = validate_authoring_result(preview, self.result(preview))
        path = self.repo / '_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'observed_input_drift'):
            apply_preview(plan.transaction, consent_for(plan.transaction))


if __name__ == '__main__':
    unittest.main()
