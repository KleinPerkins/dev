#!/usr/bin/env python3
"""Successor retirement fences exercised through real subprocess entry points."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '_ops/baseline/profiles/pr-automation'
spec = importlib.util.spec_from_file_location('delivery_policy', ROOT / '_ops/baseline/delivery-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class SuccessorDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dev-delivery-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'alias'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
                        'git@github.com:KleinPerkins/dev-temp.git'], check=True)
        self.bin = self.base / 'bin'; self.bin.mkdir()
        self.log = self.base / 'forbidden-calls'
        for name in ['gh', 'ssh', 'curl', 'scp']:
            tool = self.bin / name
            tool.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$FENCE_LOG"\nexit 91\n')
            tool.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k not in {
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
            'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'BASH_ENV', 'ENV', 'GH_TOKEN',
            'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'}
                    and not k.startswith('BASH_FUNC_')}
        self.env.update(GH_CONFIG_DIR=str(self.base / 'empty-gh-config'),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FENCE_LOG=str(self.log), PYTHONDONTWRITEBYTECODE='1')

    def snapshot(self):
        return {str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.repo.rglob('*') if p.is_file()}

    def call(self, args):
        return subprocess.run([str(x) for x in args], env=self.env, cwd=self.base,
                              text=True, capture_output=True, timeout=20)

    def refused(self, args):
        before = self.snapshot()
        result = self.call(args)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('retired', result.stderr.lower())
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else '')

    def test_cohort_counts_ids_and_new_dev_identity(self):
        p = policy.load_policy()
        self.assertEqual(len(p['repositories']), 20)
        self.assertEqual(policy.classify('KleinPerkins/dev-temp', p), 'actions-app')
        self.assertEqual(policy.classify('KleinPerkins/dev', p), 'actions-app')
        self.assertEqual(policy.classify('KleinPerkins/unknown', p), 'unenrolled')
        self.assertEqual(policy.classify('kleinperkins/dev', p), 'identity-unverified')
        self.assertEqual(policy.classify('KleinPerkins/chaos-scheduler', p), 'excluded')

    def test_all_phase_a_mutating_commands_refuse(self):
        for verb in ['apply', 'enforce', 'pause', 'repair', 'rollback']:
            with self.subTest(verb=verb):
                self.refused([sys.executable, '-B', PROFILE / 'profile.py', verb, self.repo])

    def test_all_phase_b_mutating_commands_refuse(self):
        for verb in ['apply', 'preflight', 'credential-provision', 'credential-revoke',
                     'enforce-canary', 'qualify', 'promote', 'activate-canary', 'pause',
                     'repair', 'rollback', 'activate']:
            with self.subTest(verb=verb):
                self.refused([sys.executable, '-B', PROFILE / 'fleet.py', verb, self.repo])

    def test_all_v3_mutating_commands_refuse_before_argument_resolution(self):
        for verb in ['stage', 'sync', 'activate', 'rollback', 'record-created-ruleset', 'plan']:
            with self.subTest(verb=verb):
                self.refused([sys.executable, '-B', PROFILE / 'v3/profile.py', verb,
                              '--repo-root', self.repo, '--repo', 'KleinPerkins/dev',
                              '--repository-id', '1278387789'])

    def test_wrappers_refuse_old_control_mutation(self):
        for args in [['reconcile-merge-safety', self.repo, '--create'],
                     ['enforce', self.repo], ['profile', 'pr-automation', 'apply', self.repo],
                     ['profile', 'pr-automation', 'phase-b', 'activate', self.repo],
                     ['profile', 'pr-automation', 'v3', 'stage', '--repo-root', self.repo]]:
            with self.subTest(args=args):
                self.refused(['bash', ROOT / '_ops/bin/repo-baseline.sh', *args])

    def test_changed_origin_aliases_private_unknown_cannot_restore(self):
        for origin in ['git@github.com:kleinperkins/dev.git',
                       'https://github.com/KleinPerkins/chaos-labs.git',
                       'git@github.com:KleinPerkins/new-name.git',
                       'https://example.test/KleinPerkins/dev.git']:
            subprocess.run(['git', '-C', str(self.repo), 'remote', 'set-url', 'origin', origin], check=True)
            with self.subTest(origin=origin):
                self.refused([sys.executable, '-B', PROFILE / 'v3/profile.py', 'stage',
                              '--repo-root=' + str(self.repo), '--name', 'awa'])

    def test_copied_legacy_contract_cannot_reactivate(self):
        (self.repo / '.github').mkdir()
        (self.repo / '.github/pr-automation.json').write_text('{"schema":"pr-automation/v3"}')
        self.refused([sys.executable, '-B', PROFILE / 'v3/profile.py', 'activate',
                      '--repo', 'KleinPerkins/dev-temp', '--target-root', self.repo])
        self.assertEqual(policy.observe(self.repo, policy.load_policy())[0], 'DELIVERY_DRIFT')

    def test_explicit_old_flag_refuses_normal_resume_and_legacy(self):
        for flags in [[], ['--resume'], ['--legacy-v1'], ['--private', '--resume', '--legacy-v1']]:
            with self.subTest(flags=flags):
                self.refused(['bash', ROOT / '_ops/bin/dev-new-repo.sh', 'alias',
                              '--pr-automation', '--fixture-root', self.base, *flags])

    def test_unknown_private_normal_resume_and_legacy_previews_are_unenrolled(self):
        for flags in [[], ['--resume'], ['--legacy-v1']]:
            with self.subTest(flags=flags):
                result = self.call(['bash', ROOT / '_ops/bin/dev-new-repo.sh',
                                    'unknown-repo', '--private', '--dry-run', *flags])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('profile.py" stage', result.stdout)
                self.assertNotIn('reconcile-merge-safety', result.stdout)
                self.assertNotIn('runnerless authority observation', result.stdout)
                self.assertIn('unenrolled', result.stdout)
                self.assertFalse(self.log.exists())

    def test_legacy_scaffold_generates_successor_aggregate_without_enrollment(self):
        # Run the actual scaffold/sharding writer in a disposable shadow root.
        # External service and local guard installation are inert fixture stubs.
        shadow = self.base / 'shadow'
        for relative in ['_ops/bin/dev-new-repo.sh', '_ops/bin/lib.sh',
                         '_ops/bin/baseline-lib.sh', '_ops/bin/test-sharding.py',
                         '_ops/baseline/delivery-policy.py',
                         '_ops/baseline/delivery-policy.json']:
            target = shadow / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        for name in ['install-identity-guard.sh', 'repo-baseline.sh']:
            (shadow / '_ops/bin' / name).write_text('#!/bin/sh\nexit 0\n')
        gh = self.bin / 'gh'
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FENCE_LOG"\nexit 0\n')
        gh.chmod(0o755)
        empty_hooks = self.base / 'empty-hooks'; empty_hooks.mkdir()
        env = dict(self.env, GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='core.hooksPath',
                   GIT_CONFIG_VALUE_0=str(empty_hooks), GIT_CONFIG_KEY_1='commit.gpgsign',
                   GIT_CONFIG_VALUE_1='false')
        resolved = subprocess.check_output(['bash', '-c', 'command -v gh'], env=env, text=True).strip()
        self.assertEqual(Path(resolved).resolve(), gh.resolve(), 'fixture CLI was shadowed')
        result = subprocess.run(['bash', str(shadow / '_ops/bin/dev-new-repo.sh'),
                                 'new-private-fixture', '--legacy-v1', '--no-push'],
                                env=env, cwd=self.base, capture_output=True, text=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = shadow / 'personal/new-private-fixture/.github/test-shards.json'
        contract = json.loads(generated.read_text())
        self.assertEqual(contract['aggregate'], 'ci-required')
        self.assertEqual(contract['state'], 'pending')
        self.assertEqual(contract['shards'], [])
        self.assertEqual(self.log.read_text().splitlines(),
                         ['auth status', 'repo create KleinPerkins/new-private-fixture --private'])
        self.assertFalse((generated.parent / 'pr-automation.json').exists())

    def test_private_no_ci_and_retired_are_distinct(self):
        p = policy.load_policy()
        self.assertEqual(policy.classify('KleinPerkins/chaos-labs', p), 'private-no-ci')
        self.assertEqual(policy.classify('KleinPerkins/sterling', p), 'retired')
        self.assertEqual(policy.classify('KleinPerkins/sterling.io', p), 'actions-app')
        self.refused(['bash', ROOT / '_ops/bin/dev-new-repo.sh', 'sterling', '--dry-run'])

    def test_manifest_presence_never_claims_readiness(self):
        status, _ = policy.observe(self.repo, policy.load_policy())
        self.assertEqual(status, 'SUCCESSOR_NOT_READY')
        for name in ['ci-contract.json', 'review-enrollments.json',
                     'workflows/ci.yml', 'workflows/reviewer-app.yml']:
            path = self.repo / '.github' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        self.assertEqual(policy.observe(self.repo, policy.load_policy())[0], 'SUCCESSOR_UNVERIFIED')

    def test_classification_rejects_ambiguous_origin(self):
        subprocess.run(['git', '-C', str(self.repo), 'config', '--add', 'remote.origin.url',
                        'git@github.com:KleinPerkins/awa.git'], check=True)
        result = self.call(['bash', '-c', '. "$1"; bl_repo_delivery_class "$2"',
                            'classify', ROOT / '_ops/bin/baseline-lib.sh', self.repo])
        self.assertEqual(result.stdout.strip(), 'identity-unverified')

    def test_read_only_historical_help_remains_available(self):
        for path in [PROFILE / 'profile.py', PROFILE / 'fleet.py', PROFILE / 'v3/profile.py']:
            self.assertEqual(self.call([sys.executable, '-B', path, '--help']).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_policy_rejects_old_id_and_mutation_switch(self):
        from unittest.mock import patch
        original = json.loads(policy.POLICY.read_text())
        for mutate in ['old-id', 'enabled', 'extra']:
            value = json.loads(json.dumps(original))
            if mutate == 'old-id':
                next(x for x in value['repositories'] if x['repository'] == 'KleinPerkins/dev')['repository_id'] = 1278387789
            elif mutate == 'enabled': value['live_mutation_authorized'] = True
            else: value['bypass'] = True
            with self.subTest(mutate=mutate), patch.object(Path, 'read_text', return_value=json.dumps(value)):
                with self.assertRaises(ValueError): policy.load_policy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
