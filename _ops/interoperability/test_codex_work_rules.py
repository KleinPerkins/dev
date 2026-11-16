"""Synthetic-only source/profile/build gates and personal instruction transaction."""
from argparse import Namespace
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import codex_work_rules as w
import native_rules as n
import qualification


class WorkRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-work-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.dev, self.source, self.home = (self.root / name for name in ('dev', 'source', 'home'))
        self.template = self.dev / '_ops/rules/hosts/codex-work-dispatch.md'
        self.template.parent.mkdir(parents=True)
        self.template.write_bytes((w.ROOT / '_ops/rules/hosts/codex-work-dispatch.md').read_bytes())
        self.registry = self.dev / '_ops/interoperability/evidence/codex-work-activation-bindings.json'
        self.registry.parent.mkdir(parents=True)
        self.info, self.cli = self.root / 'Info.plist', self.root / 'synthetic-cli'
        self.info.write_bytes(plistlib.dumps({'CFBundleVersion': 'fixture-build'}))
        self.cli.write_bytes(b'non-executable fixture, never invoked')
        files = {}
        for name in w.FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('Synthetic text for ' + Path(name).name + '\n').encode())
            files[name] = w.sha(path.read_bytes())
        self.receipt = self.source / '.source-export.json'
        self.receipt.write_text(json.dumps(dict(schema='interoperability/codex-work-source-export/v1',
            repository='KleinPerkins/skills', revision='1'*40, accepted=True, files=files)))
        self.qual = self.root / 'qualification.json'
        self.row = dict(schema='interoperability/qualification/v1', capability='codex-work-dispatch',
            owner='KleinPerkins/skills', source_revision='1'*40,
            payload_sha256=w.sha(w.canonical({Path(name).name: value for name, value in files.items()})),
            host='codex', surface='local-macos-desktop', host_build='fixture-build', adapter_revision='1'*40,
            check=w.CHECK, outcome='pass', observed_at='2026-11-02T00:00:00Z',
            evidence_ref='docs/evidence/synthetic-only.json',
            limitations=['model-execution-unverified', 'not-activation', 'not-awa-registration'], rollback_revision='0'*40)
        self.qual.write_text(json.dumps([self.row]))
        self.binding = dict(source_revision='1'*40, payload_sha256=self.row['payload_sha256'],
            native_tool='collaboration.spawn_agent', host_build='fixture-build',
            host_info_sha256=w.sha(self.info.read_bytes()), host_cli_sha256=w.sha(self.cli.read_bytes()),
            qualification_sha256=w.sha(self.qual.read_bytes()))
        self.write_registry([self.binding])
        for name, value in [('ROOT', self.dev), ('HOST_INFO', self.info), ('HOST_CLI', self.cli)]:
            mock = patch.object(w, name, value); mock.start(); self.addCleanup(mock.stop)
        (self.home / '.codex').mkdir(parents=True)
        self.target = self.home / '.codex/AGENTS.md'
        self.original = 'Owner text  \r\nKeep é and blank lines.\n\n'.encode()
        self.target.write_bytes(self.original); self.target.chmod(0o640)
        self.args = Namespace(home=self.home, dev_source=self.dev, skills_source=self.root / 'unused-skills',
            awa_source=self.root / 'unused-awa', qualification=self.qual, host_build='fixture-build',
            operation_dir=self.root / 'private-operation', approve=None, work_source=self.source)

    def write_registry(self, rows):
        self.registry.write_text(json.dumps(dict(schema='interoperability/codex-work-activation-bindings/v1', bindings=rows)))

    def prepared(self):
        return w.prepare(self.source, 'fixture-build')

    def rebind_qualification(self, rows):
        self.qual.write_text(json.dumps(rows))
        binding = dict(self.binding, qualification_sha256=w.sha(self.qual.read_bytes()))
        self.write_registry([binding])

    def preview(self):
        plan = n.preview(self.args); self.args.approve = plan['action_sha256']; return plan

    def test_synthetic_binding_never_in_production_and_unlisted_source_refuses(self):
        live = json.loads((n.ROOT / '_ops/interoperability/evidence/codex-work-activation-bindings.json').read_text())
        self.assertNotIn('1'*40, [row['source_revision'] for row in live['bindings']])
        self.write_registry([])
        with self.assertRaisesRegex(ValueError, 'qualification unavailable'): self.preview()
        self.assertFalse(self.args.operation_dir.exists())
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_personal_render_exact_profile_policy_and_no_legacy_reads(self):
        with patch.object(n, 'render', side_effect=AssertionError('legacy renderer called')), patch.object(n, 'qualified', side_effect=AssertionError('legacy qualification called')):
            prepared = self.prepared(); plan = self.preview()
        body = prepared['blocks'][w.MARKER]
        for value in ('collaboration.spawn_agent', 'codex-work-decision/v2', 'fork_turns:none',
                      'caller_fields', 'grants no delegation permission', 'Parent target', 'AWA authority'):
            self.assertIn(value, body)
        self.assertNotIn('affirm/src', body)
        self.assertNotIn('cursor-mcp-safety-mirror', body)
        self.assertEqual(plan['delta'], [w.MARKER])
        self.assertNotIn('economy_resolver', plan)
        self.assertEqual(plan['work_source'], str(self.source))
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_rendered_block_hash_matches_actual_body(self):
        block = self.prepared()['blocks'][w.MARKER]
        body = ''.join(block.splitlines(keepends=True)[2:-1])
        self.assertIn('sha256:' + w.sha(body.encode()), block.splitlines()[1])

    def test_native_transaction_idempotence_private_storage_and_exact_rollback(self):
        self.preview()
        self.assertEqual(self.args.operation_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.args.operation_dir / 'before').stat().st_mode & 0o777, 0o600)
        self.assertEqual(n.apply_operation(self.args)['status'], 'applied')
        applied = self.target.read_bytes()
        self.assertTrue(applied.startswith(self.original))
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(n.apply_operation(self.args)['status'], 'already-applied')
        self.assertEqual(self.target.read_bytes(), applied)
        self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'rolled-back')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse((self.home / '.cursor').exists())
        self.assertFalse((self.home / '.claude').exists())

    def test_current_source_projection_verify_and_foreign_edit_preservation(self):
        self.preview(); n.apply_operation(self.args)
        _, before, after = n.expected(self.dev, self.args.skills_source, self.args.awa_source,
                                      self.target, work_source=self.source, build='fixture-build')
        self.assertEqual(before, after)
        self.target.write_bytes(b'New owner edit')
        with self.assertRaises(ValueError): n.apply_operation(self.args, rollback=True)
        self.assertEqual(self.target.read_bytes(), b'New owner edit')

    def test_missing_target_create_then_rollback_only_created_file(self):
        self.target.unlink(); self.preview(); n.apply_operation(self.args)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        n.apply_operation(self.args, rollback=True)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.target.parent.is_dir())

    def test_exact_consequence_digest_and_source_drift_required(self):
        self.preview(); self.args.approve = '0'*64
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.args.approve = n.load_operation(self.args.operation_dir)[0]['action_sha256']
        (self.source / w.FILES[0]).write_text('Changed source')
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_qualification_drift_blocks_apply_but_not_exact_rollback(self):
        self.preview(); n.apply_operation(self.args)
        self.qual.write_text('[]')
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'rolled-back')
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_registry_closed_unique_profile_and_digests(self):
        for key, value in [('native_tool', 'multi_agent_v1.spawn_agent'), ('source_revision', 'short'),
                           ('payload_sha256', True), ('unknown', 'extra')]:
            row = dict(self.binding); row[key] = value; self.write_registry([row])
            with self.subTest(key=key), self.assertRaises(ValueError): self.prepared()
        self.write_registry([self.binding, self.binding])
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.prepared()

    def test_source_revision_build_and_host_bytes_not_transferable(self):
        for key, value in [('source_revision', '2'*40), ('host_build', 'other-build'),
                           ('host_info_sha256', '2'*64), ('host_cli_sha256', '2'*64)]:
            row = dict(self.binding); row[key] = value; self.write_registry([row])
            with self.subTest(key=key), self.assertRaises(ValueError): self.prepared()
        self.write_registry([self.binding])
        self.info.write_bytes(plistlib.dumps({'CFBundleVersion': 'different-build'}))
        self.binding['host_info_sha256'] = w.sha(self.info.read_bytes()); self.write_registry([self.binding])
        with self.assertRaises(ValueError): self.prepared()

    def test_source_receipt_acceptance_and_exact_closure(self):
        original = json.loads(self.receipt.read_text())
        for key, value in [('accepted', 1), ('accepted', False), ('repository', 'Other/repo'),
                           ('schema', 'unknown'), ('files', {}), ('unknown', True)]:
            row = dict(original); row[key] = value; self.receipt.write_text(json.dumps(row))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.prepared()
        self.receipt.write_text(json.dumps(original)[:-1] + ',"accepted":true}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.prepared()

    def test_resealing_receipt_cannot_accept_different_payload(self):
        path = self.source / w.FILES[0]; path.write_text('Changed fixture')
        receipt = json.loads(self.receipt.read_text()); receipt['files'][w.FILES[0]] = w.sha(path.read_bytes())
        self.receipt.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'payload differs'): self.prepared()

    def test_symlink_and_hardlink_sources_refused(self):
        path = self.source / w.FILES[0]; data = path.read_bytes(); path.unlink()
        other = self.root / 'other'; other.write_bytes(data); path.symlink_to(other)
        with self.assertRaises(ValueError): self.prepared()
        path.unlink(); os.link(other, path)
        with self.assertRaises(ValueError): self.prepared()

    def test_each_qualification_field_and_legacy_check_refused(self):
        changes = [('capability', 'native-model-dispatch'), ('owner', 'KleinPerkins/dev'),
            ('source_revision', '2'*40), ('payload_sha256', '2'*64), ('host', 'fixture'),
            ('surface', 'fixture'), ('host_build', 'other-build'), ('adapter_revision', '2'*40),
            ('check', 'MOD-02-native-request-and-result'), ('outcome', 'unknown')]
        for key, value in changes:
            row = dict(self.row); row[key] = value; self.rebind_qualification([row])
            with self.subTest(key=key), self.assertRaises(ValueError):
                w.qualified(self.qual, 'fixture-build', self.prepared(), validator=qualification)

    def test_passing_labels_with_unresolved_limitations_refused(self):
        for limitation in ['native-not-observed', 'fixture-only', 'host-build-unavailable', 'source-drift',
                           'source-merge-pending', 'owner-decision-required', 'account-unverified']:
            row = dict(self.row, limitations=[limitation]); self.rebind_qualification([row])
            with self.subTest(limitation=limitation), self.assertRaises(ValueError):
                w.qualified(self.qual, 'fixture-build', self.prepared(), validator=qualification)

    def test_native_unknown_identity_is_not_fabricated(self):
        self.assertTrue(w.qualified(self.qual, 'fixture-build', self.prepared(), validator=qualification))
        self.assertIn('model-execution-unverified', self.row['limitations'])

    def test_template_unknown_or_missing_slots_refused(self):
        original = self.template.read_text()
        for changed in [original.replace('{{source_revision}}', ''), original + '{{unknown}}']:
            self.template.write_text(changed)
            with self.assertRaises(ValueError): self.prepared()

    def test_project_preserves_unmanaged_bytes_and_refuses_conflicts(self):
        blocks = self.prepared()['blocks']; original = self.original.decode()
        result = w.project(original, blocks)
        self.assertTrue(result.startswith(original)); self.assertEqual(w.project(result, blocks), result)
        for text in [result + blocks[w.MARKER], '<!-- END codex-work-dispatch -->\n' + result,
                     result.replace('<!-- END codex-work-dispatch -->', ''), 'native-entry-routing/v1\n',
                     '<!-- BEGIN cursor-rules-mirror (managed by KleinPerkins/dev) -->\n']:
            with self.subTest(text=text[:40]), self.assertRaises(ValueError): w.project(text, blocks)

    def test_unknown_or_mixed_operation_profile_refused(self):
        self.preview(); path = self.args.operation_dir / 'operation.json'; original = json.loads(path.read_text())
        for key, value in [('work_profile', 'unknown'), ('work_source', 'relative'), ('delta', ['cursor-rules-mirror']),
                           ('economy_resolver', {})]:
            plan = dict(original); plan[key] = value; del plan['action_sha256']; plan['action_sha256'] = n.sha(n.canonical(plan))
            path.write_bytes(n.canonical(plan))
            with self.subTest(key=key), self.assertRaises(ValueError): n.load_operation(self.args.operation_dir)

    def test_broad_installer_refuses_personal_profile_before_any_mutation(self):
        self.target.write_text('codex-work-dispatch/v1\nOwner bytes\n'); before = self.target.read_bytes()
        result = subprocess.run(['bash', str(n.ROOT / '_ops/bin/install-agent-rules.sh')],
            env=dict(os.environ, OM_RULES_HOME=str(self.home)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('broad install refused before mutation', result.stdout)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse((self.home / '.cursor').exists()); self.assertFalse((self.home / '.claude').exists())

    def test_actual_cli_empty_registry_refuses_without_host_change(self):
        result = subprocess.run([sys.executable, str(n.ROOT / '_ops/interoperability/native_rules.py'),
            'preview', '--work-source', str(self.source), '--home', str(self.home),
            '--host-build', 'fixture-build', '--qualification', str(self.qual),
            '--operation-dir', str(self.args.operation_dir)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'refused')
        self.assertIn('qualification unavailable', result.stdout)
        self.assertFalse(self.args.operation_dir.exists())
        self.assertEqual(self.target.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
