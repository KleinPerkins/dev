"""Retained boundary tests; transaction's complete canary tests remain unchanged."""
from argparse import Namespace
from contextlib import contextmanager
import copy
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import isokit_retained as r
from test_isokit_migration import fixture as core_fixture


@contextmanager
def fixture():
    with core_fixture() as f:
        (f.home / 'Codex').mkdir()
        f.args.native_evidence = f.root / 'native.json'
        f.args.operation = 'apply'
        proof = {'repository': 'KleinPerkins/skills', 'revision': 'e' * 40, 'path': r.EVIDENCE_PATH,
                 'sha256': r.EVIDENCE_SHA, 'local_path': str(f.args.native_evidence)}
        observed = {'name': 'isokit', 'path': str(f.target / 'SKILL.md'), 'enabled': True,
                    'fresh_catalog': True, 'extra_roots': False, 'model_worker_started': False}
        with patch.object(r, 'evidence', side_effect=lambda _: copy.deepcopy(proof)), \
             patch.object(r, 'cli_proof', return_value={'path': 'synthetic', 'sha256': r.CLI_SHA}), \
             patch.object(r, 'catalog', return_value=observed) as native:
            f.native, f.evidence = native, proof
            yield f


def prepare(f):
    row = r.preview(f.args)
    f.args.approve = row['action_sha256']
    return r.load(f.args.operation_dir)


class Retention(unittest.TestCase):
    def test_retained_lifecycle_preserves_original_transaction_semantics(self):
        with fixture() as f:
            before = r.core.preserved(f.home)
            plan = prepare(f)
            child = r.core.load(f.args.operation_dir / 'transaction')
            self.assertFalse(child['retention_authorized'])
            self.assertNotEqual(plan['action_sha256'], child['action_sha256'])
            self.assertEqual(r.execute(f.args)['status'], 'applied-retained')
            self.assertTrue(f.target.is_symlink())
            self.assertEqual(r.execute(f.args)['status'], 'applied-retained')
            f.args.operation = 'verify'
            self.assertEqual(r.execute(f.args)['status'], 'verified-retained')
            f.args.operation = 'rollback'
            self.assertEqual(r.execute(f.args)['status'], 'rolled-back')
            self.assertEqual(r.core.preserved(f.home), before)
            f.args.operation = 'verify'
            self.assertEqual(r.execute(f.args)['status'], 'verified-preimage')
            f.args.operation = 'apply'
            with self.assertRaisesRegex(ValueError, 'cannot be replayed'):
                r.execute(f.args)

    def test_core_action_cannot_approve_retention(self):
        with fixture() as f:
            plan = prepare(f)
            f.args.approve = plan['core_action_sha256']
            with self.assertRaisesRegex(ValueError, 'separate exact'):
                r.execute(f.args)
            self.assertFalse(f.target.exists())
            f.native.assert_not_called()

    def test_native_failure_rolls_back_exactly_and_consumes_operation(self):
        with fixture() as f:
            before = r.core.preserved(f.home)
            prepare(f)
            f.native.side_effect = ValueError('missing native skill')
            with self.assertRaisesRegex(ValueError, 'exact rollback verified'):
                r.execute(f.args)
            self.assertFalse(f.target.exists())
            self.assertEqual(r.core.preserved(f.home), before)
            self.assertFalse((f.args.operation_dir / 'retained.json').exists())
            f.native.side_effect = None
            with self.assertRaisesRegex(ValueError, 'cannot be replayed'):
                r.execute(f.args)

    def test_native_failure_does_not_remove_later_replacement(self):
        with fixture() as f:
            prepare(f)
            def replace(_):
                f.target.rename(f.root / 'keep-inode')
                f.target.write_text('later owner file')
                raise ValueError('native failed')
            f.native.side_effect = replace
            with self.assertRaisesRegex(ValueError, 'exact recovery requires inspection'):
                r.execute(f.args)
            self.assertEqual(f.target.read_text(), 'later owner file')

    def test_canonical_catalog_does_not_adopt_same_source_foreign_link_inode(self):
        with fixture() as f:
            prepare(f)
            def replace_and_report(_):
                f.target.rename(f.root / 'keep-owned-link')
                f.target.symlink_to(f.desired)
                return {'name': 'isokit', 'path': str(f.desired / 'SKILL.md'), 'enabled': True,
                        'fresh_catalog': True, 'extra_roots': False, 'model_worker_started': False}
            f.native.side_effect = replace_and_report
            with self.assertRaisesRegex(ValueError, 'exact recovery requires inspection'):
                r.execute(f.args)
            self.assertTrue(f.target.is_symlink())
            self.assertNotEqual(f.target.lstat().st_ino, (f.root / 'keep-owned-link').lstat().st_ino)
            self.assertEqual(f.target.resolve(), f.desired)
            self.assertFalse((f.args.operation_dir / 'retained.json').exists())

    def test_source_config_host_or_preserved_path_drift_refuses(self):
        for drift in ('source', 'config', 'host', 'preserved'):
            with self.subTest(drift=drift), fixture() as f:
                prepare(f)
                if drift == 'source': f.proof['payload_sha256'] = 'drift'
                elif drift == 'config': f.config.write_text('# owner edit\n')
                elif drift == 'preserved': (f.home / '.cursor/skills/isokit').mkdir()
                host = {'build': 'other'} if drift == 'host' else {'build': r.core.HOST_BUILD}
                with patch.object(r.core, 'host_observation', return_value=host):
                    with self.assertRaises(ValueError): r.execute(f.args)
                self.assertFalse(f.target.exists())
                f.native.assert_not_called()

    def test_changed_evidence_or_transaction_record_refuses_before_publication(self):
        for drift in ('evidence', 'child', 'root'):
            with self.subTest(drift=drift), fixture() as f:
                prepare(f)
                if drift == 'evidence': f.evidence['revision'] = 'changed'
                elif drift == 'child':
                    p = f.args.operation_dir / 'transaction/operation.json'
                    p.write_bytes(p.read_bytes() + b' ')
                else:
                    f.args.operation_dir.chmod(0o755)
                with self.assertRaises(ValueError): r.execute(f.args)
                self.assertFalse(f.target.exists())

    def test_retained_receipt_write_failure_rolls_back(self):
        with fixture() as f:
            prepare(f)
            original = r.core.write_once
            def write(path, value):
                if path.name == 'retained.json': raise OSError('disk full')
                return original(path, value)
            with patch.object(r.core, 'write_once', side_effect=write):
                with self.assertRaisesRegex(ValueError, 'exact rollback verified'):
                    r.execute(f.args)
            self.assertFalse(f.target.exists())

    def test_evidence_or_cli_drift_during_native_check_triggers_rollback(self):
        for kind in ('evidence', 'cli'):
            with self.subTest(kind=kind), fixture() as f:
                prepare(f)
                original = f.native.return_value
                def drift(_):
                    if kind == 'evidence': f.evidence['revision'] = 'changed'
                    else: r.cli_proof.return_value = {'path': 'replaced', 'sha256': 'drift'}
                    return original
                f.native.side_effect = drift
                with self.assertRaisesRegex(ValueError, 'exact rollback verified'):
                    r.execute(f.args)
                self.assertFalse(f.target.exists())

    def test_cli_drift_before_apply_refuses_without_publication_or_native_process(self):
        with fixture() as f:
            prepare(f)
            with patch.object(r, 'cli_proof', return_value={'path': 'other', 'sha256': 'drift'}):
                with self.assertRaisesRegex(ValueError, 'bundled CLI changed'):
                    r.execute(f.args)
            f.native.assert_not_called()
            self.assertFalse(f.target.exists())
            self.assertFalse((f.args.operation_dir / 'transaction/link-owner.json').exists())

    def test_rollback_does_not_need_native_cli_or_evidence(self):
        with fixture() as f:
            prepare(f)
            r.execute(f.args)
            f.args.operation = 'rollback'
            with patch.object(r, 'evidence', side_effect=ValueError('missing')), \
                 patch.object(r, 'catalog', side_effect=ValueError('missing')):
                self.assertEqual(r.execute(f.args)['status'], 'rolled-back')
            self.assertFalse(f.target.exists())

    def test_foreign_target_and_explicit_opt_out_are_preserved(self):
        for drift in ('target', 'opt-out'):
            with self.subTest(drift=drift), fixture() as f:
                if drift == 'target': f.target.write_text('owner')
                else: f.config.write_text(f'[[skills.config]]\npath = "{f.target}"\nenabled = false\n')
                with self.assertRaises(ValueError): r.preview(f.args)
                self.assertEqual(f.target.read_text() if drift == 'target' else f.config.read_text(),
                                 'owner' if drift == 'target' else f'[[skills.config]]\npath = "{f.target}"\nenabled = false\n')

    def test_exact_evidence_hash_and_revision_are_required(self):
        with core_fixture() as f:
            path = f.root / 'proof.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'exact immutable'):
                r.evidence(path)


class NativeCatalog(unittest.TestCase):
    def run_catalog(self, rows, *, error=False, timeout=False, missing=False, retarget=False):
        with tempfile.TemporaryDirectory(prefix='native-catalog-path-') as temp:
            root = Path(temp).resolve()
            source = root / 'source/isokit'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('synthetic skill bytes\n')
            target = root / '.codex/skills/isokit'
            target.parent.mkdir(parents=True)
            target.symlink_to(source)
            (root / 'foreign-alias').symlink_to(source)
            other = root / 'other'
            other.mkdir()
            (other / 'SKILL.md').write_bytes((source / 'SKILL.md').read_bytes())
            if missing: target.unlink()
            def rooted(value):
                if isinstance(value, dict): return {k: rooted(v) for k, v in value.items()}
                if isinstance(value, list): return [rooted(v) for v in value]
                if isinstance(value, str) and value.startswith('/synthetic'):
                    return str(root) + value[len('/synthetic'):]
                return value
            if retarget:
                samefile = Path.samefile
                def changed(path, other_path):
                    target.unlink()
                    target.symlink_to(other)
                    return samefile(path, other_path)
                with patch.object(Path, 'samefile', changed):
                    return self._run_catalog(rooted(rows), target=str(target), error=error, timeout=timeout)
            return self._run_catalog(rooted(rows), target=str(target), error=error, timeout=timeout)

    def _run_catalog(self, rows, *, target, error=False, timeout=False):
        plan = {'native_cli': {'path': 'synthetic', 'sha256': r.CLI_SHA},
                'native_cwd': str(Path(target).parents[2] / 'Codex'), 'target': target}
        process = Mock()
        process.stdin = io.BytesIO()
        class Output(io.BytesIO):
            def fileno(self): return 12345
        process.stdout = Output()
        messages = [{'id': 1, 'result': {}}, {'id': 2, 'result': {'data': rows}}]
        if error: messages[1] = {'id': 2, 'error': {'code': -1}}
        payload = b''.join(r.core.canonical(v) + b'\n' for v in messages)
        with patch.object(r, 'cli_proof', return_value=plan['native_cli']), \
             patch.object(r.subprocess, 'Popen', return_value=process) as spawn, \
             patch.object(r.select, 'select', return_value=([process.stdout], [], [])), \
             patch.object(r.os, 'read', return_value=payload), \
             patch.object(r.time, 'monotonic', side_effect=[0, 20] if timeout else None,
                          return_value=0):
            try:
                return r.catalog(plan)
            finally:
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.args[0], [str(r.CLI), 'app-server', '--stdio'])
                process.terminate.assert_called_once()
                process.wait.assert_called_once_with(timeout=2)
                self.assertTrue(process.stdin.closed)
                self.assertTrue(process.stdout.closed)

    def test_exact_enabled_link_is_discovered_without_extra_roots_or_workers(self):
        rows = [{'cwd': '/synthetic/Codex', 'skills': [{'name': 'isokit',
                 'path': '/synthetic/.codex/skills/isokit/SKILL.md', 'enabled': True}], 'errors': []}]
        result = self.run_catalog(rows)
        self.assertTrue(result['fresh_catalog'])
        self.assertFalse(result['model_worker_started'])
        self.assertFalse(result['extra_roots'])

    def test_canonical_source_path_from_native_symlink_loader_is_accepted(self):
        rows = [{'cwd': '/synthetic/Codex', 'skills': [{'name': 'isokit',
                 'path': '/synthetic/source/isokit/SKILL.md', 'enabled': True}], 'errors': []}]
        result = self.run_catalog(rows)
        self.assertEqual(result['reported_path_kind'], 'canonical-source')
        self.assertEqual(result['path'], result['canonical_source_path'])
        self.assertNotEqual(result['path'], result['link_path'])
        self.assertTrue(result['same_file_verified'])

    def test_same_file_other_alias_and_same_bytes_other_file_are_not_allowed_paths(self):
        for path in ['/synthetic/foreign-alias/SKILL.md', '/synthetic/other/SKILL.md']:
            rows = [{'cwd': '/synthetic/Codex', 'skills': [{'name': 'isokit', 'path': path, 'enabled': True}]}]
            with self.subTest(path=path), self.assertRaises(ValueError): self.run_catalog(rows)

    def test_stale_literal_entry_without_owned_target_file_refuses(self):
        rows = [{'cwd': '/synthetic/Codex', 'skills': [{'name': 'isokit',
                 'path': '/synthetic/.codex/skills/isokit/SKILL.md', 'enabled': True}]}]
        with self.assertRaises(ValueError): self.run_catalog(rows, missing=True)

    def test_retarget_during_canonical_identity_check_refuses_same_bytes(self):
        rows = [{'cwd': '/synthetic/Codex', 'skills': [{'name': 'isokit',
                 'path': '/synthetic/source/isokit/SKILL.md', 'enabled': True}]}]
        with self.assertRaisesRegex(ValueError, 'exact retained Isokit source'):
            self.run_catalog(rows, retarget=True)

    def test_incomplete_disabled_wrong_path_or_duplicate_catalog_refuses(self):
        exact = {'name': 'isokit', 'path': '/synthetic/.codex/skills/isokit/SKILL.md', 'enabled': True}
        for kind in ('empty', 'cwd', 'errors', 'missing', 'disabled', 'path', 'duplicate'):
            with self.subTest(kind=kind):
                rows = [{'cwd': '/synthetic/Codex', 'skills': [copy.deepcopy(exact)]}]
                if kind == 'empty': rows = []
                elif kind == 'cwd': rows[0]['cwd'] = '/other'
                elif kind == 'errors': rows[0]['errors'] = [{'message': 'parse failed'}]
                elif kind == 'missing': rows[0]['skills'] = []
                elif kind == 'disabled': rows[0]['skills'][0]['enabled'] = False
                elif kind == 'path': rows[0]['skills'][0]['path'] = '/other/SKILL.md'
                else: rows[0]['skills'].append(copy.deepcopy(exact))
                with self.assertRaises(ValueError): self.run_catalog(rows)

    def test_protocol_error_and_deadline_refuse_and_stop_process(self):
        with self.assertRaisesRegex(ValueError, 'request refused'):
            self.run_catalog([], error=True)
        with self.assertRaisesRegex(ValueError, 'deadline'):
            self.run_catalog([], timeout=True)


if __name__ == '__main__':
    unittest.main()
