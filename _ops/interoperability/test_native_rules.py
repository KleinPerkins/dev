"""INT-007B projection, qualification, transaction and rollback outcome tests."""
from argparse import Namespace
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import native_rules as n
import render_rules as r
from test_rule_preparation import SourcePreparation


class NativeRendering(SourcePreparation):
    def setUp(self):
        super().setUp()
        (self.dev / '_ops/rules/global/worktree-default.mdc').write_text('---\nalwaysApply: true\n---\n# fixture\n\n## Required behavior\nworktree-default original owner instruction\n\nThe helper cannot move the current Cursor agent.\n')
        host = self.dev / '_ops/rules/hosts'
        host.mkdir()
        for name in ('codex-entry.md', 'codex-routing.md'):
            (host / name).write_bytes((n.ROOT / '_ops/rules/hosts' / name).read_bytes())
        path = self.skills / 'global/rules/subagent-orchestration/subagent-orchestration.mdc'
        path.write_text('---\nalwaysApply: true\n---\n# Shared rule\n\n## Model Choice\nOriginal Cursor resolver\n\n## Sync Or Async\nJoin workers.\n\n## Fleet Stewardship\nClean resources.\n')

    def native(self):
        return r.prepare(self.dev, self.skills, self.awa, 'codex', native_codex=True)

    def test_native_entry_routing_and_owner_stewardship(self):
        rendered = self.native()
        body = ''.join(rendered['blocks'].values())
        self.assertEqual(rendered['pending'], [])
        for text in ('create_worktree', 'attach_worktree', 'DEV_SESSION_ID', 'common directory',
                     'codex_dispatch.py', n.REVISION, n.PAYLOAD, 'CODEX-DISPATCH.md',
                     'collaboration.spawn_agent', 'codex-work-decision/v2', 'fork_turns: "none"',
                     'dispatch.caller_fields', 'pass no `agent_type`',
                     'reasoning_effort', 'target `parent`', '15 minutes',
                     '## Sync Or Async\nJoin workers.',
                     '## Fleet Stewardship\nClean resources.', 'AWA registration and'):
            self.assertIn(text, body)
        for text in ('Cursor **Agents Window**', 'Original Cursor resolver', 'verify_model_tiers.py plan',
                     'multi_agent_v1.spawn_agent', 'fork_context: false', 'codex-model-tiers.json'):
            self.assertNotIn(text, body)
        self.assertEqual(self.native(), rendered)
        self.assertFalse((Path(self.temp.name) / '.cursor').exists())

    def test_checked_in_context_native_preview_and_mirror(self):
        # Exercise the checked-in Dev SOT, not only a hand-maintained fixture.
        context = (n.ROOT / '_ops/rules/agent-context.md').read_text()
        native = r.prepare(n.ROOT, self.skills, self.awa, 'codex', native_codex=True)
        preview = r.prepare(n.ROOT, self.skills, self.awa, 'codex')
        native_context = native['blocks'][r.MARKERS[0]]
        self.assertIn(context, native_context)
        self.assertIn('For Codex, inspect native attachments and create/attach', native_context)
        self.assertIn('A printed helper path is not native attachment or AWA protection.', native_context)
        self.assertIn('Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks).', native_context)
        self.assertIn('Preserve owner exclusions and separate indexes.', native_context)
        self.assertEqual(native['activation'], 'native-candidate')
        self.assertEqual(native['pending'], [])
        self.assertEqual(preview['activation'], 'withheld-INT-007B')
        self.assertEqual(preview['pending'], ['native-entry:INT-007B', 'native-routing:INT-009'])
        self.assertIn('Native Codex entry is withheld in this preparation preview.', preview['blocks'][r.MARKERS[0]])
        self.assertNotIn('For Codex, inspect native attachments', preview['blocks'][r.MARKERS[0]])
        self.assertNotIn('### worktree-default', preview['blocks'][r.MARKERS[1]])
        self.assertNotIn('### subagent-orchestration', preview['blocks'][r.MARKERS[1]])
        _, mirror = r.parse_rule((n.ROOT / '_ops/rules/dev-operating-model.mdc').read_text())
        self.assertEqual(mirror, context.strip() + '\n')
        for host in ('cursor', 'claude'):
            rendered = r.prepare(n.ROOT, self.skills, self.awa, host)
            self.assertIn(context, rendered['blocks'][r.MARKERS[0]])
        original = 'Private owner prose  \n\n'
        projected = r.project(original, native['blocks'])
        self.assertTrue(projected.startswith(original))
        self.assertEqual(r.project(projected, native['blocks']), projected)

    def test_pinned_git_export_digest_and_source_identity(self):
        prefix = 'global/rules/subagent-orchestration/'
        program = ("import hashlib,json,pathlib\n"
                   "root=pathlib.Path(__file__).parent\n"
                   "names=('codex_dispatch.py','codex-work-policy.json','CODEX-DISPATCH.md')\n"
                   "value={k:hashlib.sha256((root/k).read_bytes()).hexdigest() for k in names}\n"
                   "print(json.dumps({'source_sha256':hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()}))\n")
        files = {'codex_dispatch.py': program.encode(), 'codex-work-policy.json': b'{}',
                 'CODEX-DISPATCH.md': b'Fixture contract',
                 'subagent-orchestration.mdc': (self.skills / prefix / 'subagent-orchestration.mdc').read_bytes()}
        payload = n.sha(n.canonical({k: n.sha(v) for k, v in files.items() if not k.endswith('.mdc')}))
        reads = []
        def read(root, command, ref):
            self.assertEqual(root, self.skills)
            self.assertEqual(command, 'show')
            self.assertTrue(ref.startswith(n.REVISION + ':' + prefix))
            name = ref.split('/')[-1]
            reads.append(name)
            return files[name]
        owners = {self.dev: 'KleinPerkins/dev', self.skills: 'KleinPerkins/skills', self.awa: 'KleinPerkins/awa'}
        with patch.object(n.original_sources, 'verify_repository'), \
             patch.object(n.inventory, 'repository', side_effect=lambda root: (owners[root], None)), \
             patch.object(n, 'git', side_effect=read), patch.object(n, 'PAYLOAD', payload):
            result = n.render(self.dev, self.skills, self.awa)
            self.assertEqual(set(reads), set(files))
            self.assertNotIn('economy_resolver', result)
            self.assertEqual(result['resolver']['entrypoint'], 'codex_dispatch.py')
            self.assertEqual(result['resolver']['payload_sha256'], payload)
            for name in ('codex-work-policy.json', 'CODEX-DISPATCH.md'):
                original = files[name]
                files[name] += b'changed'
                with self.assertRaisesRegex(ValueError, 'payload changed'):
                    n.render(self.dev, self.skills, self.awa)
                files[name] = original
        with patch.object(n.inventory, 'repository', return_value=('foreign/owner', None)):
            with self.assertRaisesRegex(ValueError, 'identity'):
                n.render(self.dev, self.skills, self.awa)

    def test_native_selection_keeps_other_hosts_and_conditions(self):
        cursor, claude = self.render('cursor'), self.render('claude')
        native = self.native()
        self.assertEqual(cursor, self.render('cursor'))
        self.assertEqual(claude, self.render('claude'))
        # Apart from the provenance stamp, service policy is byte-identical.
        old = self.render('codex')['blocks'][r.MARKERS[2]].splitlines()[2:]
        self.assertEqual(old, native['blocks'][r.MARKERS[2]].splitlines()[2:])
        with self.assertRaises(ValueError):
            r.prepare(self.dev, self.skills, self.awa, 'claude', native_codex=True)

    def test_unknown_owner_rules_require_classification(self):
        for name in ('new-behavior.mdc', 'new-mcp-safety.mdc'):
            path = self.dev / '_ops/rules/global' / name
            path.write_text('---\nalwaysApply: true\n---\nNew policy\n')
            with self.assertRaises(ValueError): self.native()
            path.unlink()
        path = self.skills / 'global/rules/new-owner-rule.mdc'
        path.write_text('---\nalwaysApply: false\n---\nNew conditional policy\n')
        with self.assertRaises(ValueError): self.native()

    def test_render_hashes_and_parses_one_source_read(self):
        original = Path.read_bytes
        observed = {}
        def read(path):
            observed[path] = observed.get(path, 0) + 1
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            result = self.native()
        for source in result['sources']:
            path = Path(source['path'])
            self.assertEqual(observed[path], 1)
            self.assertEqual(source['sha256'], n.sha(original(path)))

    def test_changed_owner_section_contract_refuses(self):
        path = self.skills / 'global/rules/subagent-orchestration/subagent-orchestration.mdc'
        path.write_text(path.read_text().replace('## Sync Or Async', '## Renamed shared section'))
        with self.assertRaises(ValueError):
            self.native()


def observation():
    return dict(schema='interoperability/qualification/v1', capability='codex-work-assessment',
                owner='KleinPerkins/skills', source_revision=n.REVISION, payload_sha256=n.PAYLOAD,
                host='codex', surface='local-macos-desktop', host_build='test-build',
                adapter_revision=n.REVISION, check=n.PROFILE_CHECK, outcome='pass',
                observed_at='2026-10-28T00:00:00+00:00', evidence_ref='evidence/native.json',
                limitations=['model-execution-unverified'], rollback_revision='0'*40)



class NativeOperations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='int007b-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        (self.home / '.codex').mkdir(parents=True)
        self.target = self.home / '.codex/AGENTS.md'
        self.original = b'User-owned whitespace  \n\nKeep this exactly.\n'
        self.target.write_bytes(self.original)
        self.target.chmod(0o640)
        self.qualification = self.root / 'qualification.json'
        self.qualification.write_text(json.dumps([observation()]))
        self.prepared = dict(blocks={name: r.block(name, '# Owned\n') for name in r.MARKERS},
                             sources=[], resolver=dict(revision=n.REVISION, payload_sha256=n.PAYLOAD))
        self.mock = patch.object(n, 'render', side_effect=lambda *args: copy.deepcopy(self.prepared))
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.args = Namespace(home=self.home, dev_source=self.root / 'dev', skills_source=self.root / 'skills',
                              awa_source=self.root / 'awa', qualification=self.qualification, host_build='test-build',
                              operation_dir=self.root / 'operation', approve=None)

    def preview(self):
        result = n.preview(self.args)
        self.args.approve = result['action_sha256']
        return result

    def test_preview_apply_reapply_and_exact_rollback(self):
        plan = self.preview()
        self.assertEqual(plan['resolver'], self.prepared['resolver'])
        self.assertNotIn('economy_resolver', plan)
        self.assertNotIn('work_profile', plan)
        self.assertNotIn('work_source', plan)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(os.stat(self.args.operation_dir).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.args.operation_dir / 'before').st_mode & 0o777, 0o600)
        self.assertEqual(n.apply_operation(self.args)['status'], 'applied')
        self.assertTrue(self.target.read_bytes().startswith(self.original))
        self.assertEqual(os.stat(self.target).st_mode & 0o777, 0o640)
        timestamp = self.target.stat().st_mtime_ns
        self.assertEqual(n.apply_operation(self.args)['status'], 'already-applied')
        self.assertEqual(self.target.stat().st_mtime_ns, timestamp)
        self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'rolled-back')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'already-rolled-back')

    def test_private_backup_rejected_in_source_or_other_git_before_creation(self):
        self.args.operation_dir = self.args.dev_source / 'operation'
        with self.assertRaises(ValueError): self.preview()
        self.assertFalse(self.args.operation_dir.exists())
        other = self.root / 'other-repository'
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        self.args.operation_dir = other / 'operation'
        with self.assertRaises(ValueError): self.preview()
        self.assertFalse(self.args.operation_dir.exists())

    def test_qualification_hashes_same_bytes_it_validates(self):
        data = self.qualification.read_bytes()
        with patch.object(n, 'regular', side_effect=[data, b'changed']):
            self.assertEqual(n.qualified(self.qualification, 'test-build'), n.sha(data))

    def test_changed_target_or_approval_refuses(self):
        self.preview()
        self.args.approve = '0'*64
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.args.approve = n.load_operation(self.args.operation_dir)[0]['action_sha256']
        self.target.write_text('Concurrent user change')
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_text(), 'Concurrent user change')

    def test_permission_preimage_and_operation_location_refuse(self):
        self.preview()
        self.target.chmod(0o600)
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.target.chmod(0o640)
        moved = self.root / 'moved-operation'
        self.args.operation_dir.rename(moved)
        self.args.operation_dir = moved
        with self.assertRaises(ValueError): n.apply_operation(self.args)

    def test_changed_rollback_target_preserved(self):
        self.preview()
        n.apply_operation(self.args)
        self.target.write_text('Later user change')
        with self.assertRaises(ValueError): n.apply_operation(self.args, rollback=True)
        self.assertEqual(self.target.read_text(), 'Later user change')

    def test_source_and_qualification_changes_refuse(self):
        self.preview()
        self.prepared['sources'].append(dict(changed=True))
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.prepared['sources'].clear()
        self.qualification.write_text(json.dumps([dict(observation(), outcome='unknown')]))
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_interrupted_atomic_write_keeps_preimage_and_cleans_temp(self):
        self.preview()
        with patch.object(n.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(list(self.target.parent.glob('.dev-native-*')), [])
        n.apply_operation(self.args)
        self.assertNotEqual(self.target.read_bytes(), self.original)

    def test_new_file_rollback_removes_only_created_file(self):
        self.target.unlink()
        self.preview()
        n.apply_operation(self.args)
        n.apply_operation(self.args, rollback=True)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.target.parent.is_dir())

    def test_symlink_target_and_parent_refused(self):
        self.target.unlink()
        other = self.root / 'other'
        other.write_bytes(self.original)
        self.target.symlink_to(other)
        with self.assertRaises(ValueError): self.preview()
        self.assertEqual(other.read_bytes(), self.original)
        self.target.unlink()
        self.target.parent.rmdir()
        self.target.parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): self.preview()

    def test_malformed_owned_markers_and_payload_tamper_refused(self):
        self.target.write_text(r.block(r.MARKERS[0], 'x') * 2)
        with self.assertRaises(ValueError): self.preview()
        self.target.write_bytes(self.original)
        self.preview()
        (self.args.operation_dir / 'after').write_text('tampered')
        with self.assertRaises(ValueError): n.apply_operation(self.args)

    def test_exact_qualification_binding_and_unknown_history(self):
        self.assertTrue(n.qualified(self.qualification, 'test-build'))
        changes = [('host_build', None), ('source_revision', '1'*40), ('adapter_revision', '1'*40),
                   ('payload_sha256', '1'*64), ('outcome', 'fail'), ('capability', 'another'),
                   ('owner', 'KleinPerkins/dev'), ('check', 'MOD-01-source-fixtures'),
                   ('host', 'fixture'), ('surface', 'fixture')]
        for key, value in changes:
            row = dict(observation(), **{key: value})
            if key=='host_build': row['limitations'].append('host-build-unavailable')
            self.qualification.write_text(json.dumps([row]))
            with self.subTest(key=key), self.assertRaises(ValueError): n.qualified(self.qualification, 'test-build')
        row = observation()
        row['limitations'].append('host-build-unavailable')
        self.qualification.write_text(json.dumps([row]))
        with self.assertRaises(ValueError): n.qualified(self.qualification, 'test-build')

    def test_one_current_observation_and_history_cannot_supply_missing_evidence(self):
        for rows in ([], [observation(), observation()],
                     [dict(observation(), host_build='old-build')],
                     [dict(observation(), capability='native-model-dispatch',
                           check='MOD-02-native-request-and-result')]):
            self.qualification.write_text(json.dumps(rows))
            with self.assertRaises(ValueError): n.qualified(self.qualification, 'test-build')
        rows = [observation(), dict(observation(), host_build='old-build')]
        self.qualification.write_text(json.dumps(rows))
        self.assertTrue(n.qualified(self.qualification, 'test-build'))

    def test_legacy_profile_cannot_qualify_current_source_and_build(self):
        # An otherwise matching source/payload/build is not proof of this ABI.
        row = dict(observation(), check='MOD-03-assessed-native-dispatch')
        self.qualification.write_text(json.dumps([row]))
        with self.assertRaisesRegex(ValueError, 'collaboration-profile'):
            n.qualified(self.qualification, 'test-build')
        self.qualification.write_text(json.dumps([row, observation()]))
        self.assertTrue(n.qualified(self.qualification, 'test-build'))

    def test_frozen_legacy_observation_does_not_qualify_successor(self):
        # Historical account/host receipts stay in private preservation. Exercise
        # their ABI mismatch with an explicitly synthetic observation instead.
        legacy = dict(observation(), check='MOD-03-assessed-native-dispatch',
                      source_revision='1'*40, adapter_revision='1'*40,
                      payload_sha256='2'*64, host_build='legacy-fixture-build')
        self.qualification.write_text(json.dumps([legacy]))
        with self.assertRaisesRegex(ValueError, 'collaboration-profile'):
            n.qualified(self.qualification, 'legacy-fixture-build')

    def test_current_profile_evidence_binds_source_build_and_native_abi(self):
        # This tests the current validator, not an installed-host qualification.
        row = observation()
        self.qualification.write_text(json.dumps([row]))
        self.assertEqual(n.qualified(self.qualification, 'test-build'),
                         n.sha(self.qualification.read_bytes()))
        for field, changed in (('source_revision', '1'*40),
                               ('adapter_revision', '2'*40),
                               ('payload_sha256', '3'*64),
                               ('check', 'MOD-03-assessed-native-dispatch'),
                               ('host_build', 'other-fixture-build')):
            self.qualification.write_text(json.dumps([dict(row, **{field: changed})]))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'collaboration-profile'):
                n.qualified(self.qualification, 'test-build')
        self.qualification.write_text(json.dumps([row]))
        with self.assertRaisesRegex(ValueError, 'collaboration-profile'):
            n.qualified(self.qualification, 'other-fixture-build')

    def test_passing_label_cannot_override_missing_native_evidence(self):
        for limitation in ('native-not-observed', 'fixture-only', 'host-build-unavailable',
                           'source-drift', 'owner-decision-required', 'source-merge-pending'):
            rows = [dict(observation(), limitations=[limitation])]
            self.qualification.write_text(json.dumps(rows))
            with self.subTest(limitation=limitation), self.assertRaises(ValueError):
                n.qualified(self.qualification, 'test-build')
        rows = [dict(observation(), limitations=['model-execution-unverified',
                    'metrics-unavailable', 'not-activation', 'not-security-isolation'])]
        self.qualification.write_text(json.dumps(rows))
        self.assertTrue(n.qualified(self.qualification, 'test-build'))

    def test_policy_pin_change_refuses_apply_but_preserves_rollback(self):
        self.preview()
        self.prepared['resolver']['payload_sha256'] = '1'*64
        with self.assertRaises(ValueError): n.apply_operation(self.args)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.prepared['resolver']['payload_sha256'] = n.PAYLOAD
        n.apply_operation(self.args)
        self.prepared['resolver']['payload_sha256'] = '1'*64
        self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'rolled-back')
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_previous_operations_remain_rollbackable(self):
        for economy in (False, True):
            self.args.operation_dir = self.root / ('historical-' + str(economy))
            self.preview()
            n.apply_operation(self.args)
            # Old retained operations bind their old implementation/source metadata;
            # only their unchanged target postimage authorizes exact rollback.
            plan, _, _ = n.load_operation(self.args.operation_dir)
            plan['resolver'] = dict(revision='4'*40, payload_sha256='5'*64)
            if economy:
                plan['economy_resolver'] = dict(revision='6'*40, payload_sha256='7'*64)
            del plan['action_sha256']
            plan['implementation_sha256'] = '0'*64
            plan['action_sha256'] = n.sha(n.canonical(plan))
            (self.args.operation_dir / 'operation.json').write_bytes(n.canonical(plan) + b'\n')
            self.args.approve = plan['action_sha256']
            with self.assertRaises(ValueError): n.apply_operation(self.args)
            self.assertEqual(n.apply_operation(self.args, rollback=True)['status'], 'rolled-back')
            self.assertEqual(self.target.read_bytes(), self.original)


class NativeLegacyCoexistence(unittest.TestCase):
    def test_full_installer_preserves_native_and_reconciles_other_hosts(self):
        with tempfile.TemporaryDirectory(prefix='int007b-coexistence-') as tmp:
            root = Path(tmp).resolve()
            dev, home, skills = [root / name for name in ('dev', 'home', 'skills')]
            for relative in ('_ops/bin/lib.sh', '_ops/bin/install-agent-rules.sh'):
                destination = dev / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(n.ROOT / relative, destination)
            (dev / '_ops/rules/global').mkdir(parents=True)
            (dev / '_ops/rules/agent-context.md').write_text('# fixture context\n')
            (dev / '_ops/rules/global/shared.mdc').write_text('---\nalwaysApply: true\n---\nShared fixture policy\n')
            rule = skills / 'subagent-orchestration'
            rule.mkdir(parents=True)
            (rule / 'subagent-orchestration.mdc').write_text('---\nalwaysApply: true\n---\nLegacy routing fixture\n')
            (rule / 'model-tiers.json').write_text('{}')
            (rule / 'verify_model_tiers.py').write_text('raise SystemExit(0)\n')
            (dev / '_ops/interoperability').mkdir()
            # Contract double isolates the shell dispatch: real native verification
            # is exercised by renderer/transaction tests, with no private repo dependency.
            checker = dev / '_ops/interoperability/native_rules.py'
            checker.write_text('import sys\nassert sys.argv[1] == "verify"\nraise SystemExit(0)\n')
            (home / '.codex').mkdir(parents=True)
            native = home / '.codex/AGENTS.md'
            native.write_text('native-entry-routing/v1\nUser and selected native policy\n')
            before = native.read_bytes()
            env = dict(os.environ, OM_RULES_HOME=str(home), OM_CAPABILITY_RULES_DIR=str(skills))
            command = ['bash', str(dev / '_ops/bin/install-agent-rules.sh')]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(native.read_bytes(), before)
            claude = home / '.claude/CLAUDE.md'
            self.assertIn('Legacy routing fixture', claude.read_text())
            timestamp = claude.stat().st_mtime_ns
            second = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(claude.stat().st_mtime_ns, timestamp)
            self.assertEqual(native.read_bytes(), before)
            # Stale native state still cannot prevent an independent Claude refresh.
            checker.write_text('raise SystemExit(1)\n')
            (dev / '_ops/rules/agent-context.md').write_text('# refreshed context\n')
            third = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(third.returncode, 1)
            self.assertIn('refreshed context', claude.read_text())
            self.assertEqual(native.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
