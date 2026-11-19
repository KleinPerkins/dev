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



class OriginalSourceContinuity(unittest.TestCase):
    def test_bootstrap_requires_original_history_and_exact_consumed_source(self):
        sources = module('original_sources')
        for owner in sources.ORIGINALS:
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                original = root / 'original'
                original.mkdir()
                def git(where, *args):
                    return subprocess.check_output(['git', '-C', str(where), *args], stderr=subprocess.PIPE).decode().strip()
                def commit(where, text):
                    git(where, 'add', '.')
                    git(where, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', text)
                git(original, 'init', '-q')
                (original / 'bootstrap.sh').write_text('echo original\n')
                (original / '.gitignore').write_text('global/ignored.py\n')
                (original / 'global').mkdir()
                (original / 'global/source.py').write_text('original = True\n')
                if owner == 'KleinPerkins/kp-mcp':
                    (original / 'pyproject.toml').write_text('[tool.uv]\npackage = false\n[tool.uv.workspace]\nmembers = []\n')
                    (original / 'uv.lock').write_text('version = 1\n')
                commit(original, 'original history')
                anchor = git(original, 'rev-parse', 'HEAD')
                git(original, 'remote', 'add', 'origin', f'git@github.com:{owner}.git')
                with mock.patch.dict(sources.ANCHORS, {owner: anchor}), \
                     mock.patch.object(sources, 'endpoint', side_effect=AssertionError('offline verifier used API')):
                    self.assertEqual(sources.verify_checkout(original, owner), owner)
                    # Established older detached source remains valid on the
                    # same original history without a live API lookup.
                    (original / 'README.md').write_text('later original snapshot\n')
                    commit(original, 'later original snapshot')
                    later = git(original, 'rev-parse', 'HEAD')
                    with mock.patch.dict(sources.ANCHORS, {owner: later}):
                        git(original, 'checkout', '-q', '--detach', anchor)
                        self.assertEqual(sources.verify_checkout(original, owner), owner)
                        git(original, 'checkout', '-q', '--detach', later)
                    # A successor imports the object, but its actual HEAD belongs
                    # to independent clean history and must never authorize use.
                    successor = root / 'successor'
                    successor.mkdir()
                    git(successor, 'init', '-q')
                    (successor / 'bootstrap.sh').write_text('echo successor-controlled\n')
                    commit(successor, 'independent clean root')
                    git(successor, 'remote', 'add', 'origin', f'git@github.com:{owner}.git')
                    git(successor, 'fetch', '-q', str(original), anchor)
                    self.assertEqual(sources.verify_repository(successor, owner), owner)
                    before = (successor / 'bootstrap.sh').read_bytes()
                    with self.assertRaisesRegex(ValueError, 'original history'):
                        sources.verify_checkout(successor, owner)
                    self.assertEqual((successor / 'bootstrap.sh').read_bytes(), before)
                    # Local replace refs and legacy grafts cannot fabricate the
                    # original ancestry of an independent successor root.
                    bad_head = git(successor, 'rev-parse', 'HEAD')
                    git(successor, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                        'replace', '--graft', bad_head, anchor)
                    with self.assertRaisesRegex(ValueError, 'original history'):
                        sources.verify_checkout(successor, owner)
                    git(successor, 'replace', '-d', bad_head)
                    grafts = successor / '.git/info/grafts'
                    grafts.write_text(bad_head + ' ' + anchor + '\n')
                    with self.assertRaisesRegex(ValueError, 'original history'):
                        sources.verify_checkout(successor, owner)
                    self.assertEqual(grafts.read_text(), bad_head + ' ' + anchor + '\n')
                    grafts.unlink()
                    # Existing original code remains offline, but modified,
                    # staged, untracked and ignored consumed inputs refuse.
                    source = original / 'global/source.py'
                    source.write_text('modified = True\n')
                    with self.assertRaisesRegex(ValueError, 'modified'):
                        sources.verify_checkout(original, owner)
                    git(original, 'add', 'global/source.py')
                    source.write_text('original = True\n')
                    with self.assertRaisesRegex(ValueError, 'staged'):
                        sources.verify_checkout(original, owner)
                    git(original, 'reset', '-q', 'HEAD', '--', 'global/source.py')
                    for relative in ('global/extra.py', 'global/ignored.py', 'global/__pycache__/source.pyc'):
                        extra = original / relative
                        extra.parent.mkdir(parents=True, exist_ok=True)
                        extra.write_bytes(b'unverified source')
                        with self.assertRaisesRegex(ValueError, 'untracked or ignored'):
                            sources.verify_checkout(original, owner)
                        self.assertEqual(extra.read_bytes(), b'unverified source')
                        extra.unlink()
                    link = original / 'global/linked.py'
                    link.symlink_to(root / 'outside-source')
                    with self.assertRaisesRegex(ValueError, 'linked'):
                        sources.verify_checkout(original, owner)
                    self.assertTrue(link.is_symlink())
                    link.unlink()
                    self.assertEqual(sources.verify_checkout(original, owner), owner)

    def test_local_jobs_runtime_state_is_data_not_a_source_escape(self):
        import stat
        sources = module('original_sources')
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q')
            git('remote', 'add', 'origin', 'git@github.com:KleinPerkins/skills.git')
            (root / 'bootstrap.sh').write_text('echo original source\n')
            template = root / sources.DASHBOARD_TEMPLATE
            template.parent.mkdir(parents=True)
            template.write_text('export const DASHBOARD = __DASHBOARD_JSON__;\n')
            (template.parent.parent / '.gitignore').write_text('canvases/*.generated.canvas.tsx\ncanvases/*.canvas.data.json\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'original dashboard source')
            anchor = git('rev-parse', 'HEAD')
            live = root / sources.DASHBOARD_LIVE
            rendered = 'export const DASHBOARD = {\n  "schema": "dashboard/v1",\n  "instances": []\n};\n'
            with mock.patch.dict(sources.ANCHORS, {'KleinPerkins/skills': anchor}), \
                 mock.patch.object(sources, 'endpoint', side_effect=AssertionError('offline state check used API')):
                sources.verify_checkout(root, 'KleinPerkins/skills')
                # These are post-commit runtime writes, never resealed as source.
                live.write_text(rendered)
                for path in sources.DASHBOARD_STATE - {sources.DASHBOARD_LIVE}:
                    (root / path).write_text('{"canvasState": {}}\n')
                self.assertEqual(git('status', '--porcelain'), '')
                sources.verify_checkout(root, 'KleinPerkins/skills')
                self.assertEqual(live.read_text(), rendered)
                for injected in (rendered + 'run_unverified();\n', rendered.replace('"dashboard/v1"', '"wrong-schema"'),
                                 rendered.replace('  "instances": []', '  "instances": (run_unverified())')):
                    live.write_text(injected)
                    with self.assertRaisesRegex(ValueError, 'unverified dashboard'):
                        sources.verify_checkout(root, 'KleinPerkins/skills')
                    self.assertEqual(live.read_text(), injected)
                live.write_text(rendered)
                live.chmod(0o755)
                with self.assertRaisesRegex(ValueError, 'non-executable'):
                    sources.verify_checkout(root, 'KleinPerkins/skills')
                self.assertTrue(live.stat().st_mode & stat.S_IXUSR)
                live.chmod(0o644)
                outside = root.parent / (root.name + '-outside-state')
                try:
                    outside.write_text(rendered)
                    live.unlink()
                    live.symlink_to(outside)
                    with self.assertRaisesRegex(ValueError, 'linked'):
                        sources.verify_checkout(root, 'KleinPerkins/skills')
                    self.assertTrue(live.is_symlink())
                    self.assertEqual(outside.read_text(), rendered)
                    live.unlink()
                    live.write_text(rendered)
                finally:
                    outside.unlink(missing_ok=True)
                for suffix in ('py', 'sh', 'pyc'):
                    (root / '.git/info/exclude').write_text('**/adjacent.' + suffix + '\n')
                    extra = live.parent / ('adjacent.' + suffix)
                    extra.write_text('unverified executable/import source\n')
                    self.assertEqual(git('status', '--porcelain'), '')
                    with self.assertRaisesRegex(ValueError, 'untracked or ignored'):
                        sources.verify_checkout(root, 'KleinPerkins/skills')
                    self.assertTrue(extra.exists())
                    extra.unlink()
                sidecar = root / next(iter(sources.DASHBOARD_STATE - {sources.DASHBOARD_LIVE}))
                sidecar.write_text('[]\n')
                with self.assertRaisesRegex(ValueError, 'unverified dashboard'):
                    sources.verify_checkout(root, 'KleinPerkins/skills')
                sidecar.write_text('{}\n')
                sources.verify_checkout(root, 'KleinPerkins/skills')

    def test_mcp_existing_uv_runtime_is_preserved_without_source_admission(self):
        import os
        sources = module('original_sources')
        owner = 'KleinPerkins/kp-mcp'
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q')
            git('remote', 'add', 'origin', 'git@github.com:' + owner + '.git')
            (root / 'pyproject.toml').write_text('[tool.uv]\npackage = false\n[tool.uv.workspace]\nmembers = ["*-kit"]\n')
            (root / 'uv.lock').write_text('version = 1\n')
            (root / '.gitignore').write_text('.venv/\n**/ignored.py\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'original uv workspace')
            anchor = git('rev-parse', 'HEAD')
            environment = root / '.venv'
            environment.mkdir()
            runtime = environment / 'host-owned-runtime.py'
            runtime.write_bytes(b'opaque existing dependency bytes\n')
            runtime.chmod(0o755)
            initial = (runtime.read_bytes(), runtime.stat().st_mode)
            clean_env = {key: value for key, value in os.environ.items()
                         if key not in ('UV_PROJECT_ENVIRONMENT', 'UV_PROJECT', 'UV_WORKING_DIR')}
            with mock.patch.dict(sources.ANCHORS, {owner: anchor}), \
                 mock.patch.dict(os.environ, clean_env, clear=True), \
                 mock.patch.object(sources, 'endpoint', side_effect=AssertionError('offline runtime check used API')):
                self.assertEqual(git('status', '--porcelain'), '')
                sources.verify_checkout(root, owner)
                self.assertEqual((runtime.read_bytes(), runtime.stat().st_mode), initial)
                # Only the established workspace environment location is opaque.
                # Neither ignored source nor a kit-local environment is admitted.
                for relative in ('ignored.py', '__pycache__/extra.pyc', 'extra-kit/.venv/ignored.py'):
                    extra = root / relative
                    extra.parent.mkdir(parents=True, exist_ok=True)
                    extra.write_bytes(b'unverified source')
                    with self.assertRaisesRegex(ValueError, 'untracked or ignored'):
                        sources.verify_checkout(root, owner)
                    self.assertEqual(extra.read_bytes(), b'unverified source')
                    extra.unlink()
                for key, accepted in (('UV_PROJECT_ENVIRONMENT', '.venv'), ('UV_PROJECT', '.'), ('UV_WORKING_DIR', '.')):
                    with mock.patch.dict(os.environ, {key: accepted}):
                        sources.verify_checkout(root, owner)
                    with mock.patch.dict(os.environ, {key: '../other-workspace'}):
                        with self.assertRaisesRegex(ValueError, 'redirection'):
                            sources.verify_checkout(root, owner)
                    self.assertEqual((runtime.read_bytes(), runtime.stat().st_mode), initial)
                # A symlink cannot redirect the environment root outside this contract.
                moved = root / '.environment-fixture'
                environment.rename(moved)
                environment.symlink_to(moved, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'root redirection'):
                    sources.verify_checkout(root, owner)
                self.assertTrue(environment.is_symlink())
                environment.unlink()
                moved.rename(environment)
                # Untracked project metadata cannot authorize another runtime root.
                project = root / 'pyproject.toml'
                original = project.read_bytes()
                project.write_bytes(original + b'# modified workspace\n')
                with self.assertRaisesRegex(ValueError, 'modified'):
                    sources.verify_checkout(root, owner)
                self.assertEqual(project.read_bytes(), original + b'# modified workspace\n')
                project.write_bytes(original)
                sources.verify_checkout(root, owner)
                self.assertEqual((runtime.read_bytes(), runtime.stat().st_mode), initial)

    def test_rejected_clone_cannot_be_used_on_a_second_bootstrap_attempt(self):
        import os
        import shutil
        import sys
        for script, owner, identity, destination in (
                ('bootstrap.sh', 'skills', 1275604090, 'skills'),
                ('mcp-bootstrap.sh', 'kp-mcp', 1271164179, 'mcp')):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                dev = root / 'dev'
                cap = dev / 'capabilities'
                helpers = dev / '_ops/interoperability'
                cap.mkdir(parents=True)
                helpers.mkdir(parents=True)
                checkout = root / 'wrong-history'
                checkout.mkdir()
                marker = root / 'source-was-used'
                (checkout / 'bootstrap.sh').write_text('touch ' + str(marker) + '\n')
                for args in (('init', '-q'), ('config', 'user.name', 'Fixture'),
                             ('config', 'user.email', 'fixture@example.test'),
                             ('add', '.'), ('commit', '-qm', 'wrong history'),
                             ('remote', 'add', 'origin', f'git@github.com:KleinPerkins/{owner}.git')):
                    subprocess.run(['git', '-C', str(checkout), *args], check=True, capture_output=True)
                source = ROOT.parent.parent
                shutil.copyfile(source / 'capabilities' / script, cap / script)
                shutil.copyfile(source / 'capabilities/mcp-pins.env', cap / 'mcp-pins.env')
                for name in ('original_sources.py', 'inventory.py', 'mcp_maintenance.py'):
                    shutil.copyfile(ROOT / name, helpers / name)
                fake = root / 'tools'
                fake.mkdir()
                real_git = shutil.which('git')
                clone_log = root / 'clones'
                (fake / 'git').write_text('#!' + sys.executable + '\n' +
                    'import os,shutil,sys\n'
                    'if sys.argv[1] == "clone":\n'
                    ' shutil.copytree(' + repr(str(checkout)) + ',sys.argv[-1])\n'
                    ' with open(' + repr(str(clone_log)) + ',"a") as f:f.write("clone\\n")\n'
                    'else:os.execv(' + repr(real_git) + ',[' + repr(real_git) + ']+sys.argv[1:])\n')
                (fake / 'gh').write_text('#!' + sys.executable + '\nimport json,sys\n' +
                    'assert sys.argv[1:] == ["api","--hostname","github.com","/repositories/' + str(identity) + '"]\n' +
                    'print(json.dumps(' + repr(dict(id=identity, full_name='KleinPerkins/' + owner, private=True)) + '))\n')
                (fake / 'uv').write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
                for tool in fake.iterdir():
                    tool.chmod(0o700)
                home = root / 'home'
                home.mkdir()
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith(('GIT_', 'SNOW_KIT_', 'KP_MCP_', 'DEV_MCP_'))
                       and key not in ('BASH_ENV', 'ENV', 'CAP_SKILLS_REPO_URL')}
                env.update(HOME=str(home), XDG_STATE_HOME=str(home / '.local/state'),
                           XDG_DATA_HOME=str(home / '.local/share'), XDG_CONFIG_HOME=str(home / '.config'),
                           PATH=str(fake) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
                if owner == 'kp-mcp':
                    # An override may select a runtime pin; it must never turn
                    # a successor HEAD into the original-history source anchor.
                    forged_pin = root / 'runtime-pin.env'
                    bad_head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
                    forged_pin.write_text('SNOW_KIT_REPO=git@github.com:KleinPerkins/kp-mcp.git\n'
                                          'SNOW_KIT_TAG=snow-kit-v0.2.0\nSNOW_KIT_SHA=' + bad_head + '\n')
                    env['SNOW_KIT_PIN_FILE'] = str(forged_pin)
                for attempt in range(2):
                    result = subprocess.run(['bash', str(cap / script)], env=env,
                                            capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0, (attempt, result.stdout, result.stderr))
                    self.assertIn('pinned object unavailable', result.stderr)
                    self.assertTrue((cap / destination / '.git').is_dir())
                    self.assertFalse(marker.exists())
                self.assertEqual(clone_log.read_text(), 'clone\n')

    @mock.patch.dict('os.environ', {'GH_HOST': 'untrusted-host.invalid'})
    def test_original_id_routes_current_and_retained_endpoints_only(self):
        sources = module('original_sources')
        for owner, (identity, retained) in sources.ORIGINALS.items():
            for name in (owner, retained):
                with self.subTest(owner=owner, name=name), mock.patch.object(
                        sources.subprocess, 'run', return_value=mock.Mock(
                            stdout=json.dumps(dict(id=identity, full_name=name, private=True)))) as request:
                    self.assertEqual(sources.endpoint(owner), name)
                    self.assertEqual(request.call_args.args[0], ['gh', 'api', '--hostname', 'github.com', f'/repositories/{identity}'])
                    self.assertNotIn('GH_HOST', request.call_args.kwargs['env'])
                    self.assertEqual(sources.verify_url('git@github.com:' + name + '.git', owner), name)

    def test_clean_successor_ids_and_unexpected_names_or_visibility_refuse(self):
        sources = module('original_sources')
        for owner, clean_id in (('KleinPerkins/skills', 1461925043), ('KleinPerkins/kp-mcp', 1460922143)):
            identity, retained = sources.ORIGINALS[owner]
            for row in (dict(id=clean_id, full_name=owner, private=True),
                        dict(id=identity, full_name='other/' + retained.split('/')[1], private=True),
                        dict(id=identity, full_name=retained, private=False),
                        dict(id=str(identity), full_name=owner, private=True)):
                with self.subTest(row=row), mock.patch.object(sources.subprocess, 'run',
                        return_value=mock.Mock(stdout=json.dumps(row))):
                    with self.assertRaisesRegex(ValueError, 'identity mismatched'):
                        sources.endpoint(owner)

    def test_unknown_endpoint_and_rename_redirect_do_not_qualify(self):
        sources = module('original_sources')
        with mock.patch.object(sources, 'endpoint', return_value='KleinPerkins/skills-private-original') as request:
            with self.assertRaisesRegex(ValueError, 'endpoint mismatched'):
                sources.verify_url('git@github.com:other/skills.git', 'KleinPerkins/skills')
            request.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'stale'):
                sources.verify_url('git@github.com:KleinPerkins/skills.git', 'KleinPerkins/skills')

    def test_unavailable_live_identity_fails_closed(self):
        sources = module('original_sources')
        for error in (OSError(), subprocess.TimeoutExpired('gh', 30), subprocess.CalledProcessError(1, 'gh')):
            with mock.patch.object(sources.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(ValueError, 'unavailable'):
                    sources.endpoint('KleinPerkins/skills')

    def test_local_old_objects_survive_rename_without_network_or_receipt_edits(self):
        sources = module('original_sources')
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q')
            (root / 'payload').write_text('original history')
            git('add', 'payload')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'original')
            original = git('rev-parse', 'HEAD')
            git('remote', 'add', 'origin', 'git@github.com:KleinPerkins/skills.git')
            with mock.patch.object(sources, 'endpoint', side_effect=AssertionError('local operation attempted API')):
                for name in ('skills', 'skills-private-original'):
                    git('remote', 'set-url', 'origin', 'git@github.com:KleinPerkins/' + name + '.git')
                    self.assertEqual(sources.verify_repository(root, 'KleinPerkins/skills', revision=original),
                                     'KleinPerkins/' + name)
                with self.assertRaisesRegex(ValueError, 'pinned object'):
                    sources.verify_repository(root, 'KleinPerkins/skills', revision='0' * 40)
                git('config', 'remote.origin.pushurl', 'git@github.com:KleinPerkins/skills.git')
                with self.assertRaisesRegex(ValueError, 'remote identity'):
                    sources.verify_repository(root, 'KleinPerkins/skills', revision=original)
                git('config', '--unset', 'remote.origin.pushurl')
                git('config', 'url.git@github.com:other/skills.git.insteadOf',
                    'git@github.com:KleinPerkins/skills-private-original.git')
                with self.assertRaisesRegex(ValueError, 'identity'):
                    sources.verify_repository(root, 'KleinPerkins/skills', revision=original)


if __name__ == '__main__':
    unittest.main()
