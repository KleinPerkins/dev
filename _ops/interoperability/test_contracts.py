import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parent

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

inventory = module('inventory')
qualification = module('qualification')


class EvidenceContract(unittest.TestCase):
    def setUp(self):
        self.row = dict(schema=qualification.SCHEMA, capability='native-worktree-attach',
                        owner='KleinPerkins/dev', source_revision='a'*40, payload_sha256='b'*64,
                        host='codex', surface='local-macos-desktop', host_build='test-build',
                        adapter_revision=None, check='WSP-01', outcome='pass',
                        observed_at='2026-10-27T18:00:00Z',
                        evidence_ref='_ops/interoperability/evidence/2026-10-27/execution.json#entry',
                        limitations=['host-build-unavailable', 'not-awa-registration'],
                        rollback_revision='c'*40)

    def test_valid_record_and_expiry(self):
        qualification.validate(self.row)
        args = dict(source_revision='a'*40, payload_sha256='b'*64, host_build='test-build', adapter_revision=None)
        self.assertTrue(qualification.current(self.row, **args))
        self.assertFalse(qualification.current(dict(self.row, host_build=None), **dict(args, host_build=None)))
        for key in args:
            changed = dict(args, **{key: 'changed'})
            self.assertFalse(qualification.current(self.row, **changed))

    def test_closed_fields_reject_config_and_content(self):
        for key in ('token', 'environment', 'prompt', 'body', 'raw_log', 'approval'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                qualification.validate(dict(self.row, **{key: 'not-allowed'}))

    def test_no_unbound_pass_or_arbitrary_reason_or_reference(self):
        for change in ({'source_revision': None}, {'payload_sha256': None},
                       {'limitations': ['secret-bearing-error-text']},
                       {'evidence_ref': 'https://example.com'}, {'evidence_ref': '../private'},
                       {'host': 'imagined-host'}, {'host_build': None, 'limitations': []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                qualification.validate(dict(self.row, **change))


class InventorySafety(unittest.TestCase):
    def test_excluded_remote_alias_before_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True)
            subprocess.run(['git', '-C', directory, 'remote', 'add', 'origin',
                            'git@github.com:KleinPerkins/innocent-name.git'], check=True)
            subprocess.run(['git', '-C', directory, 'remote', 'add', 'upstream',
                            'git@github.com:KleinPerkins/chaos-scheduler.git'], check=True)
            self.assertEqual(inventory.repository(path), (None, 'excluded'))

    def test_excluded_upstream_with_explicit_port(self):
        responses = {'rev-parse': '/synthetic', 'config': 'remote.origin.url git@github.com:KleinPerkins/innocent.git\nremote.upstream.url ssh://git@github.com:22/KleinPerkins/chaos-scheduler.git', 'remote': 'git@github.com:KleinPerkins/innocent.git'}
        with mock.patch.object(inventory, 'git', side_effect=lambda path, *args: responses[args[0]]):
            self.assertEqual(inventory.repository(Path('/synthetic')), (None, 'excluded'))
        responses['config'] = 'remote.origin.url git@github.com:KleinPerkins/innocent.git\nremote.upstream.url git@unknown-alias:owner/repo'
        with mock.patch.object(inventory, 'git', side_effect=lambda path, *args: responses[args[0]]):
            self.assertEqual(inventory.repository(Path('/synthetic'))[1], 'unresolved-identity')

    def test_failed_status_is_unknown_and_excluded_file_link_is_not_read(self):
        with mock.patch.object(inventory, 'repository', return_value=('KleinPerkins/skills', None)), mock.patch.object(inventory, 'git', return_value=None):
            rows = inventory.refresh_repositories([{'path': '/synthetic', 'head': 'a'*40, 'scope': 'metadata-only'}], 'now')
            self.assertIsNone(rows[0]['dirty'])
            self.assertEqual(rows[0]['qualification'], 'metadata-incomplete')
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); entry = home / '.agents/skills/sample'; entry.mkdir(parents=True)
            target = home / 'excluded'; target.mkdir(); (target / 'SKILL.md').write_text('do not hash')
            (entry / 'SKILL.md').symlink_to(target / 'SKILL.md')
            def owner(path):
                return (None, 'excluded') if path == target.resolve() else (None, 'no-repository')
            with mock.patch.object(inventory, 'repository', side_effect=owner), mock.patch.object(inventory, 'digest', side_effect=AssertionError('content read')):
                self.assertEqual(inventory.skill_exposures(home, 'now'), [])

    def test_canonical_file_owner_and_revision_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); entry = home / '.agents/skills/sample'; entry.mkdir(parents=True)
            target = home / 'other-repo'; target.mkdir(); (target / 'SKILL.md').write_text('sample')
            (entry / 'SKILL.md').symlink_to(target / 'SKILL.md')
            def owner(path):
                return ('KleinPerkins/canonical', None) if path == target.resolve() else (None, 'no-repository')
            with mock.patch.object(inventory, 'repository', side_effect=owner), mock.patch.object(inventory, 'git', return_value='a'*40) as git:
                rows = inventory.skill_exposures(home, 'now')
                self.assertEqual(rows[0]['owner'], 'KleinPerkins/canonical')
                self.assertEqual(rows[0]['source_revision'], 'a'*40)
                git.assert_called_once_with(target.resolve(), 'rev-parse', 'HEAD')

    def test_remote_parsing_refuses_credentials_and_unknown_hosts(self):
        self.assertEqual(inventory.identity('git@github.com:KleinPerkins/skills.git'), 'KleinPerkins/skills')
        self.assertEqual(inventory.identity('https://github.com/KleinPerkins/skills'), 'KleinPerkins/skills')
        self.assertEqual(inventory.identity('ssh://git@github.com/KleinPerkins/chaos-scheduler.git'), 'KleinPerkins/chaos-scheduler')
        self.assertEqual(inventory.identity('git://github.com/KleinPerkins/chaos-scheduler.git'), 'KleinPerkins/chaos-scheduler')
        self.assertIsNone(inventory.identity('https://user:credential@github.com/owner/repo'))
        self.assertIsNone(inventory.identity('git@other.example:owner/repo.git'))

    def test_unknown_repository_remote_does_not_read_skill_content(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / '.agents/skills/sample'
            skill.mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', str(skill)], check=True)
            subprocess.run(['git', '-C', str(skill), 'remote', 'add', 'origin',
                            'git@unrecognized-alias:owner/repo.git'], check=True)
            (skill / 'SKILL.md').write_text('content must not be digested')
            rows = inventory.skill_exposures(home, '2026-10-27T18:00:00Z')
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]['sha256'])

    def test_mcp_projection_does_not_export_values_or_assume_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.cursor').mkdir()
            (home / '.cursor/mcp.json').write_text(json.dumps({'mcpServers': {
                'disabled-service': {'url': 'https://example.test/private', 'disabled': True,
                                     'headers': {'Authorization': 'synthetic-secret'}, 'timeout': 22},
                'unknown-state': {'command': '/nonexistent', 'env': {'KEY': 'synthetic-secret'}},
                'chaos-scheduler': {'command': 'never-run'}}}))
            rows = inventory.mcp_entries(home, '2026-10-27T18:00:00Z')
            self.assertEqual(len(rows), 2)
            self.assertFalse(rows[0]['enabled'])
            self.assertIsNone(rows[1]['enabled'])
            encoded = json.dumps(rows)
            self.assertNotIn('synthetic-secret', encoded)
            self.assertNotIn('example.test', encoded)
            self.assertNotIn('/nonexistent', encoded)
            self.assertTrue(all(row['safe_read_succeeded'] == 'unknown' for row in rows))

    def test_malformed_config_refuses_instead_of_partial_success(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.codex').mkdir()
            (home / '.codex/config.toml').write_text('[mcp_servers.bad\n')
            with self.assertRaises(ValueError):
                inventory.mcp_entries(home, '2026-10-27T18:00:00Z')

    def test_metadata_ignores_unowned_fields_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'meta.yml'
            p.write_text('id: sample\nowner: KleinPerkins\nsecret: hidden\n')
            self.assertEqual(inventory.flat_metadata(p), {'id': 'sample', 'owner': 'KleinPerkins'})
            p.write_text('id: one\nid: two\n')
            with self.assertRaises(ValueError):
                inventory.flat_metadata(p)



class FrozenWorkloadAndCatalog(unittest.TestCase):
    def test_workload_freeze_and_repetition_budget(self):
        path = ROOT / 'fixtures/workloads.v1.json'
        expected = (ROOT / 'fixtures/workloads.v1.sha256').read_text().split()[0]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
        data = json.loads(path.read_text())
        self.assertEqual(len({row['id'] for row in data['workflows']}), 6)
        self.assertEqual(len(data['hosts']) * data['repetitions'] * len(data['workflows']), 36)
        for row in data['workflows']:
            self.assertTrue(row['input'])
            self.assertTrue(row['rubric'])
            self.assertTrue(row['cases'])
        self.assertFalse(data['canary_contract']['service_writes'])
        self.assertFalse(data['canary_contract']['automatic_authentication'])

    def test_catalog_coverage_and_dependency_projection(self):
        # Exercise current projection code with synthetic owner metadata. Historical
        # machine observations and their task DAG are private, not source fixtures.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for cap in ('mapped', 'new-capability'):
                entry = root / 'global/skills' / cap / 'meta.yml'
                entry.parent.mkdir(parents=True)
                entry.write_text(f'id: {cap}\nkind: skills\nscope: global\nowner: KleinPerkins\n')
            task_map = [{'capability': 'mapped', 'tasks': ['INT-008', 'INT-023'],
                         'proposed_action': 'preserve owner contract'},
                        {'capability': 'removed', 'tasks': ['INT-999']}]
            with mock.patch.object(inventory, 'repository', return_value=('KleinPerkins/skills', None)), \
                 mock.patch.object(inventory, 'git', return_value='a' * 40):
                caps, mapping = inventory.refresh_capabilities(root, task_map, 'synthetic-observation')
            self.assertEqual({row['id'] for row in caps}, {'mapped', 'new-capability'})
            self.assertEqual({row['capability'] for row in mapping}, {row['id'] for row in caps})
            expected = {'mapped': ['INT-008', 'INT-023'], 'new-capability': ['INT-001', 'INT-023']}
            for row, projected in zip(caps, mapping):
                self.assertEqual(row['dependencies'], expected[row['id']])
                self.assertEqual(projected['tasks'], row['dependencies'])
                self.assertEqual(projected['owner'], 'KleinPerkins/skills')
                self.assertEqual(projected['source_revision'], 'a' * 40)
                self.assertEqual(projected['qualification'], 'metadata-observed; native qualification pending')
                self.assertEqual(projected['proposed_action'], row['disposition'])
                self.assertEqual(row['sha256'], hashlib.sha256(Path(row['path']).read_bytes()).hexdigest())
            self.assertEqual(mapping[0]['proposed_action'], 'preserve owner contract')
            self.assertEqual(mapping[1]['proposed_action'], 'owner review required')
            for owner, reason in ((None, 'excluded'), ('KleinPerkins/other', None)):
                with mock.patch.object(inventory, 'repository', return_value=(owner, reason)), \
                     mock.patch.object(inventory, 'flat_metadata', side_effect=AssertionError('unowned content read')):
                    with self.assertRaises(ValueError):
                        inventory.refresh_capabilities(root, task_map, 'synthetic-observation')



if __name__ == '__main__':
    unittest.main()
