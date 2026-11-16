import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from fixture_factory import ROOT
import test_new_repo_e2e as bootstrap_fixtures


class NativeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith('GIT_') and key not in {'BASH_ENV', 'ENV'}}
        self.session_id = f'shadow-sync-delivery-test-{uuid.uuid4()}'
        self.environment['DEV_SESSION_ID'] = self.session_id
        self.auth_root = tempfile.TemporaryDirectory(prefix='native-gh-isolation-')
        self.addCleanup(self.auth_root.cleanup)
        self.environment.update(GH_CONFIG_DIR=self.auth_root.name, GH_TOKEN='',
                                GITHUB_TOKEN='', GH_ENTERPRISE_TOKEN='',
                                GITHUB_ENTERPRISE_TOKEN='', GH_HOST='github.com')

    def shell(self, body, *arguments, env=None):
        return subprocess.run(
            ['bash', '-c', '. "$1"; ' + body, 'fixture',
             str(ROOT / '_ops/bin/baseline-lib.sh'), *map(str, arguments)],
            env={**self.environment, **(env or {})},
            capture_output=True, text=True,
        )

    def make_repo(self, root, origin='git@github.com:KleinPerkins/shadow-sync.git'):
        repo = root / 'repository'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)],
                       check=True, env=self.environment)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', origin],
                       check=True, env=self.environment)
        return repo

    def test_only_exact_owner_and_name_get_native_class(self):
        names = ['KleinPerkins/shadow-sync', 'KleinPerkins/shadow-sync-test',
                 'someone/shadow-sync', 'KleinPerkins/skills',
                 'KleinPerkins/sterling.io', 'kleinperkins/shadow-sync', '',
                 'KleinPerkins/machine-monitor', 'kleinperkins/Machine-Monitor',
                 'KleinPerkins/machine-monitor-neighbor']
        for name in names:
            with self.subTest(name=name):
                result = self.shell('bl_delivery_class "$2"', name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'native-github' if
                                 name in {names[0], 'KleinPerkins/machine-monitor'} else 'identity-unverified' if
                                 name in {'kleinperkins/shadow-sync', 'kleinperkins/Machine-Monitor'} else 'actions-app' if name in {'KleinPerkins/skills', 'KleinPerkins/sterling.io'} else 'unenrolled')

    def test_machine_monitor_bootstrap_records_pending_sharding(self):
        with tempfile.TemporaryDirectory(prefix='machine-monitor-foundation-') as directory:
            root = Path(directory)
            result = bootstrap_fixtures.NewRepositoryEndToEndTests.run_scaffold(
                self, root, 'machine-monitor', '--public', '--no-pr-automation',
                '--fixture-repository-id', '987654321', extra_env=self.environment)
            payload = bootstrap_fixtures.NewRepositoryEndToEndTests.result(result)
            repo = root / 'machine-monitor'
            self.assertEqual(payload['delivery']['repository'], 'KleinPerkins/machine-monitor')
            self.assertEqual(payload['commit_count'], 2)
            self.assertTrue(payload['test_sharding']['required'])
            self.assertFalse(payload['test_sharding']['activation_allowed'])
            self.assertEqual(payload['test_sharding']['state'], 'pending')
            self.assertEqual(json.loads((repo/'.github/test-shards.json').read_text())['aggregate'], 'ci-required')
            self.assertEqual(payload['workflows_present'], [])
            self.assertFalse((repo/'.github/pr-automation.json').exists())
            origin='git@github.com:KleinPerkins/machine-monitor.git'
            self.assertEqual(subprocess.check_output(['git','-C',str(repo),'remote','get-url','origin'],
                env=self.environment,text=True).strip(),origin)

    def test_machine_monitor_identity_cannot_claim_shadow_sync_observation(self):
        with tempfile.TemporaryDirectory(prefix='machine-monitor-identity-') as directory:
            repo = self.make_repo(Path(directory), 'git@github.com:KleinPerkins/machine-monitor.git')
            profile=repo/'.planning/doc-warden.json';profile.parent.mkdir()
            profile.write_text(json.dumps({'github_repository_id':1449284973}))
            for name,status in [('KleinPerkins/machine-monitor',0),('KleinPerkins/shadow-sync',1)]:
                result=self.shell('gh() { printf "%s\\n" "$NATIVE_GH_JSON"; }; bl_verify_native_identity "$2"',
                    repo,env={'NATIVE_GH_JSON':json.dumps(dict(id=1449284973,full_name=name,visibility='public'))})
                self.assertEqual(result.returncode,status,result.stderr)

    def test_machine_monitor_modes_are_exact_and_public_only(self):
        with tempfile.TemporaryDirectory(prefix='machine-monitor-modes-') as directory:
            root=Path(directory)
            command=[str(ROOT/'_ops/bin/dev-new-repo.sh'),'machine-monitor','--fixture-root',str(root),'--dry-run']
            for flags,success in [(['--public'],True),([],False),(['--private'],False),
                                  (['--public','--pr-automation'],False),(['--public','--legacy-v1'],False),
                                  (['--public','--capability'],False)]:
                result=subprocess.run(command+flags,capture_output=True,text=True,env=self.environment)
                self.assertEqual(result.returncode==0,success,result.stderr)
                self.assertFalse((root/'machine-monitor').exists())

    def test_resume_cannot_erase_new_repository_sharding_requirement(self):
        with tempfile.TemporaryDirectory(prefix='machine-monitor-resume-') as directory:
            root=Path(directory)
            first=bootstrap_fixtures.NewRepositoryEndToEndTests.run_scaffold(
                self,root,'machine-monitor','--public','--no-pr-automation',
                '--fixture-interrupt-after','initial-commit-landed',check=False,extra_env=self.environment)
            self.assertEqual(first.returncode,75,first.stderr)
            repo=root/'machine-monitor'
            for name in ('test-sharding-required.json','test-shards.json'):(repo/'.github'/name).unlink()
            environment=dict(self.environment,DEV_SESSION_ID=self.session_id)
            subprocess.run(['git','-C',str(repo),'add','-u'],check=True,env=environment)
            subprocess.run(['git','-C',str(repo),'commit','--amend','--no-edit'],check=True,env=environment,
                           capture_output=True)
            resumed=bootstrap_fixtures.NewRepositoryEndToEndTests.run_scaffold(
                self,root,'machine-monitor','--public','--no-pr-automation','--resume',
                check=False,extra_env=self.environment)
            self.assertNotEqual(resumed.returncode,0)
            self.assertIn('persisted test-sharding requirement is missing',resumed.stderr)
            self.assertFalse((root/'.doc-warden-fixture-remotes/machine-monitor.json').exists())

    def test_spoofed_origin_refuses_before_baseline_mutation(self):
        with tempfile.TemporaryDirectory(prefix='native-delivery-') as directory:
            root = Path(directory)
            repo = self.make_repo(root, 'https://evilgithub.com/KleinPerkins/shadow-sync.git')
            classification = self.shell('bl_repo_delivery_class "$2"', repo)
            self.assertEqual(classification.stdout.strip(), 'identity-unverified')
            for verb in ('apply', 'enforce', 'reconcile-merge-safety'):
                result = self.shell(
                    'gh() { return 97; }; . \"$3\" \"$4\" \"$2\"', repo,
                    ROOT / '_ops/bin/repo-baseline.sh', verb)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('REFUS', result.stderr)
            self.assertFalse((repo / 'SECURITY.md').exists())

    def test_native_reconciliation_never_calls_github(self):
        with tempfile.TemporaryDirectory(prefix='native-delivery-') as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            marker = root / 'called'
            result = self.shell(
                'gh() { : > "$NATIVE_CALL_MARKER"; return 97; }; '
                '. "$3" reconcile-merge-safety "$2"', repo,
                ROOT / '_ops/bin/repo-baseline.sh',
                env={'NATIVE_CALL_MARKER': str(marker)})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('retired controller', result.stderr)
            self.assertFalse(marker.exists())

    def test_live_native_identity_must_match_recorded_id_and_public_name(self):
        with tempfile.TemporaryDirectory(prefix='native-delivery-') as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            profile = repo / '.planning/doc-warden.json'
            profile.parent.mkdir()
            profile.write_text(json.dumps({'github_repository_id': 1442961455}))
            command = ('gh() { printf "%s\\n" "$NATIVE_GH_JSON"; }; '
                       'bl_verify_native_identity "$2"')
            valid = {'id': 1442961455, 'full_name': 'KleinPerkins/shadow-sync', 'visibility': 'public'}
            for payload, expected in [(valid, 0), ({**valid, 'id': 9}, 1),
                                      ({**valid, 'id': True}, 1),
                                      ({**valid, 'full_name': 'KleinPerkins/shadow-sync-copy'}, 1),
                                      ({**valid, 'visibility': 'private'}, 1)]:
                result = self.shell(command, repo, env={
                    'NATIVE_GH_JSON': json.dumps(payload)})
                self.assertEqual(result.returncode, expected, result.stderr)
            profile.unlink()
            profile.symlink_to(root / 'absent')
            self.assertNotEqual(self.shell(command, repo, env={
                'NATIVE_GH_JSON': json.dumps(valid)}).returncode, 0)

    def test_native_dry_run_and_rejected_modes_leave_no_target(self):
        with tempfile.TemporaryDirectory(prefix='native-delivery-') as directory:
            root = Path(directory)
            command = [str(ROOT / '_ops/bin/dev-new-repo.sh'), 'shadow-sync',
                       '--fixture-root', str(root), '--dry-run']
            for arguments, succeeds in [(['--public'], True),
                                       (['--public', '--no-pr-automation'], True),
                                       ([], False), (['--private'], False),
                                       (['--public', '--pr-automation'], False),
                                       (['--public', '--legacy-v1'], False),
                                       (['--public', '--capability'], False)]:
                result = subprocess.run(command + arguments, capture_output=True,
                                        text=True, env=self.environment)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                if succeeds:
                    self.assertIn('native GitHub CI', result.stdout)
                    self.assertIn('"controller_enrollment": false', result.stdout)
                    self.assertNotIn('runnerless only', result.stdout)
                    self.assertNotIn('v2_specific_runnerless', result.stdout)
                    self.assertNotIn('no hosted/self-hosted runner', result.stdout)
                self.assertFalse((root / 'shadow-sync').exists())
            command[1] = 'shadow-sync-neighbor'
            result = subprocess.run(command + ['--public'], capture_output=True,
                                    text=True, env=self.environment, check=True)
            self.assertIn('unenrolled', result.stdout)
            self.assertNotIn('native GitHub CI', result.stdout)

    def test_native_fixture_bootstrap_binds_id_without_runnerless_or_workflows(self):
        authority = ROOT / '_ops/baseline/profiles/pr-automation/v3'
        files = ['fleet.json', 'controller.json', 'coverage-assignments.json']
        for name in files:
            self.assertNotIn('shadow-sync', (authority / name).read_text().lower())
        before = {name: hashlib.sha256((authority / name).read_bytes()).hexdigest()
                  for name in files}
        with tempfile.TemporaryDirectory(prefix='native-delivery-') as directory:
            root = Path(directory)
            result = bootstrap_fixtures.NewRepositoryEndToEndTests.run_scaffold(
                self, root, 'shadow-sync', '--public', '--no-pr-automation',
                '--fixture-repository-id', '987654321', extra_env=self.environment)
            payload = bootstrap_fixtures.NewRepositoryEndToEndTests.result(result)
            repo = root / 'shadow-sync'
            self.assertEqual(payload['github_repository_id'], 987654321)
            self.assertEqual(payload['commit_count'], 2)
            self.assertNotIn('runnerless', payload)
            self.assertFalse(payload['delivery']['controller_enrollment'])
            self.assertEqual(payload['delivery']['delivery_class'], 'native-github')
            self.assertEqual(payload['bindings']['github_repository_id'], 987654321)
            self.assertEqual(payload['inventory_observation']['status'],
                             'pending_repository_owned_observation')
            self.assertFalse((repo / '.github/pr-automation.json').exists())
            self.assertFalse((repo / '.github/pr-verification.json').exists())
            self.assertEqual(payload['workflows_present'], [])
            self.assertTrue(payload['remote_creation_evidence']['marker_cleared'])
        self.assertEqual(before, {name: hashlib.sha256((authority / name).read_bytes()).hexdigest()
                                  for name in files})


    def test_aliases_and_multiple_origins_are_refused_by_verify(self):
        origins = ['git@github.com:kleinperkins/Shadow-Sync.git',
                   'https://GITHUB.COM/KleinPerkins/shadow-sync.git',
                   'git@github.com:KleinPerkins/shadow-sync.git']
        for origin in origins:
            with self.subTest(origin=origin), tempfile.TemporaryDirectory(prefix='native-alias-') as directory:
                repo = self.make_repo(Path(directory), origin)
                if origin == origins[-1]:
                    subprocess.run(['git', '-C', str(repo), 'config', '--add',
                                    'remote.origin.url', 'https://example.invalid/other/repo.git'],
                                   check=True, env=self.environment)
                self.assertEqual(self.shell('bl_repo_delivery_class "$2"', repo).stdout.strip(),
                                 'identity-unverified')
                result = self.shell('. "$3" verify "$2"', repo,
                                    ROOT / '_ops/bin/repo-baseline.sh')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('REFUSED', result.stderr)

    def test_direct_profile_cannot_override_native_identity_or_environment(self):
        with tempfile.TemporaryDirectory(prefix='native-stage-') as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for environment in ({}, {'BASH_FUNC_git%%': '() { echo unrelated/repo; }',
                                     'PATH': '/nonexistent'}):
                result = subprocess.run(
                    [os.sys.executable, str(ROOT / '_ops/baseline/profiles/pr-automation/v3/profile.py'),
                     'stage', '--repo-root', str(repo), '--name', 'awa', '--repository-id', '123',
                     '--default-branch', 'main', '--activation-generation', '1'],
                    env={**self.environment, **environment}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('retired controller', result.stderr)
                self.assertFalse((repo / '.github').exists())

    def test_native_contract_contamination_and_ordinary_codeowners(self):
        with tempfile.TemporaryDirectory(prefix='native-contract-') as directory:
            repo = self.make_repo(Path(directory))
            github = repo / '.github'
            github.mkdir()
            owners = github / 'CODEOWNERS'
            owners.write_text('* @KleinPerkins\n.github/workflows/ @KleinPerkins\n')
            self.assertEqual(self.shell('bl_native_contracts_absent "$2"', repo).returncode, 0)
            contaminants = [('pr-automation.json', '{}'), ('pr-verification.json', '{}'),
                            ('pr-recipe.json', '{}'), ('pr-automation.lock.json', '{}'),
                            ('CODEOWNERS', '# BEGIN kleinperkins runnerless PR automation v3\n'),
                            ('CODEOWNERS', '# END kleinperkins runnerless PR automation v3\n')]
            for name, content in contaminants:
                with self.subTest(name=name, content=content):
                    path = github / name
                    original = path.read_bytes() if path.exists() else None
                    path.write_text(content)
                    self.assertNotEqual(self.shell('bl_native_contracts_absent "$2"', repo).returncode, 0)
                    result = self.shell('. "$3" verify "$2"', repo,
                                        ROOT / '_ops/bin/repo-baseline.sh')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('contradictory runnerless', result.stderr)
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)

    def test_doctor_review_policy_only_exempts_native_identity(self):
        # Execute the real per-repository doctor path against disposable roots;
        # omit its fleet driver and replace only remote observation functions.
        doctor = (ROOT / '_ops/checks/dev-doctor.sh').read_text()
        marker = '# Drive\n# ---------------------------------------------------------------------------\n'
        self.assertEqual(doctor.count(marker), 1)
        definitions = doctor.split(marker)[0]
        definitions = definitions.replace(
            'SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"',
            'SELF_DIR="' + str(ROOT / '_ops/checks') + '"')
        for name, expected in [('shadow-sync', 'SUCCESSOR_NOT_READY'),
                               ('shadow-sync-neighbor', 'DELIVERY_UNKNOWN')]:
            with tempfile.TemporaryDirectory(prefix='native-doctor-') as directory:
                root = Path(directory)
                repo = self.make_repo(root, f'git@github.com:KleinPerkins/{name}.git')
                body = definitions + '\n' + r'''
bl_github_controls() { printf 'UNKNOWN\tfixture\n'; }
bl_check_no_required_reviews() { printf 'REVIEW_DRIFT\trequired approval fixture\n'; }
ROOT="$NATIVE_FIXTURE_ROOT"
analyze_repo "$NATIVE_FIXTURE_REPO"
'''
                result = subprocess.run(['/bin/bash', '-c', body],
                                        env={**self.environment, 'NATIVE_FIXTURE_ROOT': str(root),
                                             'NATIVE_FIXTURE_REPO': str(repo)},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                if name == 'shadow-sync':
                    self.assertNotIn('REVIEW_DRIFT', result.stdout)

    def test_baseline_apply_and_verify_preserve_native_workflows(self):
        with tempfile.TemporaryDirectory(prefix='native-preserve-') as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            workflow = repo / '.github/workflows/ci.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('name: native product CI\non: push\n')
            before = workflow.read_bytes()
            subprocess.run(['git', '-C', str(repo), 'add', '.github/workflows/ci.yml'],
                           check=True, env=self.environment)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
                           check=True, env=self.environment)
            # Source real CLI functions without its final dispatcher, then stub
            # remote observations and placement to this one isolated fixture.
            source = (ROOT / '_ops/bin/repo-baseline.sh').read_text()
            cut = source.rfind('case "$VERB" in')
            self.assertGreater(cut, source.index('cmd_apply()'))
            definitions = source[:cut].replace(
                'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"',
                'SCRIPT_DIR="' + str(ROOT / '_ops/bin') + '"')
            definitions = definitions.replace('VERB="${1:-}"', 'VERB=apply')
            body = definitions + r'''
bl_classify_repo() { printf 'ELIGIBLE\tfixture\tKleinPerkins/shadow-sync\tfixture\n'; }
bl_github_controls() { printf 'UNKNOWN\tfixture\n'; }
cmd_apply "$NATIVE_FIXTURE_REPO"
cmd_verify "$NATIVE_FIXTURE_REPO"
'''
            result = subprocess.run(['/bin/bash', '-c', body],
                                    env={**self.environment, 'NATIVE_FIXTURE_REPO': str(repo),
                                         'DEV_SESSION_ID': self.session_id},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Delivery policy: native-github', result.stdout)
            self.assertEqual(workflow.read_bytes(), before)

    def test_resume_refuses_changed_fetch_or_push_destination_before_remote_calls(self):
        with tempfile.TemporaryDirectory(prefix='native-resume-') as directory:
            root = Path(directory)
            run = bootstrap_fixtures.NewRepositoryEndToEndTests.run_scaffold
            result = run(self, root, 'shadow-sync', '--public',
                         '--fixture-repository-id', '987654321', extra_env=self.environment)
            repo = root / 'shadow-sync'
            calls = root / '.doc-warden-fixture-remotes/shadow-sync.calls'
            before = calls.read_bytes()
            for key in ['remote.origin.url', 'remote.origin.pushurl']:
                previous = subprocess.run(['git', '-C', str(repo), 'config', '--get', key],
                                          capture_output=True, text=True, env=self.environment)
                subprocess.run(['git', '-C', str(repo), 'config', key,
                                'git@github.com:KleinPerkins/unrelated.git'], check=True,
                               env=self.environment)
                attempt = run(self, root, 'shadow-sync', '--resume',
                              '--fixture-repository-id', '987654321', check=False,
                              extra_env=self.environment)
                self.assertNotEqual(attempt.returncode, 0)
                self.assertIn('origin or push URL changed', attempt.stderr)
                self.assertEqual(calls.read_bytes(), before)
                if previous.returncode == 0:
                    subprocess.run(['git', '-C', str(repo), 'config', key, previous.stdout.strip()],
                                   check=True, env=self.environment)
                else:
                    subprocess.run(['git', '-C', str(repo), 'config', '--unset', key],
                                   check=True, env=self.environment)


    def test_historical_settings_observation_requires_exact_native_readback(self):
        with tempfile.TemporaryDirectory(prefix='native-readback-') as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            profile = repo / '.planning/doc-warden.json'
            profile.parent.mkdir()
            profile.write_text(json.dumps({'github_repository_id': 1442961455}))
            live = dict(id=1442961455, full_name='KleinPerkins/shadow-sync', visibility='public',
                        default_branch='main', allow_squash_merge=True, allow_merge_commit=False,
                        allow_rebase_merge=False, allow_auto_merge=True, delete_branch_on_merge=True)
            rules = json.loads((ROOT / '_ops/baseline/template/github/ruleset-branch.json.tmpl')
                               .read_text().replace('{{DEFAULT_BRANCH}}', 'main'))
            rules['id'] = 42
            body = '. "$NATIVE_BASELINE_LIB"\n' + r'''
bl_gh_timeout() { shift; "$@"; }
gh() {
  case "$*" in
    *rulesets/42*) printf '%s\n' "$NATIVE_RULES" ;;
    *repos/KleinPerkins/shadow-sync*) printf '%s\n' "$NATIVE_LIVE" ;;
    *) return 97 ;;
  esac
}
bl_verify_native_applied_settings "$NATIVE_FIXTURE_REPO" main 42
'''
            cases = [(live, rules, True), ({**live, 'allow_merge_commit': True}, rules, False),
                     ({**live, 'id': 999}, rules, False),
                     ({**live, 'default_branch': 'other'}, rules, False),
                     (live, {**rules, 'rules': []}, False),
                     (live, {**rules, 'id': 43}, False)]
            for metadata, rule, succeeds in cases:
                with self.subTest(metadata=metadata, rules=rule):
                    (root / 'state.json').unlink(missing_ok=True)
                    result = subprocess.run(['/bin/bash', '-c', body], capture_output=True, text=True,
                        env={**self.environment, 'NATIVE_FIXTURE_ROOT': str(root),
                             'NATIVE_FIXTURE_REPO': str(repo), 'NATIVE_LIVE': json.dumps(metadata),
                             'NATIVE_BASELINE_LIB': str(ROOT / '_ops/bin/baseline-lib.sh'),
                             'NATIVE_RULES': json.dumps(rule)})
                    self.assertFalse((root / 'mutated').exists())
                    self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                    self.assertFalse((root / 'state.json').exists())
                    if succeeds:
                        self.assertIn('dev-native-delivery-readback/v1', result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
