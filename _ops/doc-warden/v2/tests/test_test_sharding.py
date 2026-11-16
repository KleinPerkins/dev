"""Hermetic sharding-contract, aggregate and activation regression tests."""
import base64
import copy
import contextlib
import importlib.util
import json
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('test_sharding_owner', ROOT / '_ops/bin/test-sharding.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ShardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sharding-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')

    def git(self, *args):
        return subprocess.check_output(['git','-C',str(self.root),*args],env=self.environment,text=True).strip()

    def configured(self):
        m.bootstrap(self.root,'ci-required')
        for name in ('test_a.py','test_b.py'): (self.root/name).write_text('import unittest\n')
        value = dict(schema=m.SCHEMA,state='configured',aggregate='ci-required',
            discovery=dict(include=['test_*.py'],exclude=[]),
            shards=[dict(id=name,tests=[f'test_{name}.py'],command=['python3',f'test_{name}.py'],timeout_seconds=30)
                    for name in ('a','b')])
        self.write(value)
        return value

    def write(self,value):
        (self.root/m.MANIFEST).write_text(json.dumps(value))

    def test_foundation_pending_and_activation_blocked(self):
        m.bootstrap(self.root,'ci-required')
        self.assertFalse(m.validate(self.root)['activation_allowed'])
        with self.assertRaisesRegex(m.Refusal,'pending'): m.validate(self.root,activation=True)
        self.assertEqual(m.bootstrap(self.root,'ci-required')['state'],'pending')

    def test_legacy_repository_is_not_retrofitted(self):
        (self.root/'README.md').write_text('fixture')
        self.git('add','.');self.git('commit','-qm','fixture foundation')
        self.assertEqual(m.validate(self.root,activation=True)['state'],'legacy')
        with self.assertRaisesRegex(m.Refusal,'not automatically retrofitted'): m.bootstrap(self.root,'ci-required')
        self.assertEqual(m.legacy_preflight(['verify',str(self.root)])['status'],'legacy-compatible')

    def test_new_repository_cannot_activate_through_legacy_paths(self):
        m.bootstrap(self.root,'ci-required')
        with self.assertRaisesRegex(m.Refusal,'legacy activation refused'):
            m.legacy_preflight(['phase-b','activate',str(self.root)])
        before = {name: (self.root/name).read_bytes() for name in (m.REQUIREMENT,m.MANIFEST)}
        result=subprocess.run(['bash',str(ROOT/'_ops/bin/repo-baseline.sh'),'profile','pr-automation',
            'phase-b','activate',str(self.root)],capture_output=True,text=True,env=self.environment)
        self.assertNotEqual(result.returncode,0)
        # The successor wrapper now refuses all retired-controller mutations
        # before reaching the narrower historical sharding activation guard.
        self.assertEqual(result.stderr.strip(),
                         'REFUSED: retired controller mutation; historical inspection only')
        self.assertEqual(before, {name: (self.root/name).read_bytes() for name in before})

    def test_native_new_product_cannot_be_misclassified_as_legacy(self):
        with (mock.patch.object(m,'validate_remote',return_value={'required':False}),
              mock.patch.object(m.sys,'argv',['test-sharding.py','verify-remote','--repository','fixture-owner/product','--ref','main','--require']),
              contextlib.redirect_stderr(io.StringIO()) as errors):
            self.assertEqual(m.main(),1)
        self.assertIn('requirement is missing',errors.getvalue())

    def test_birth_requirement_survives_current_file_deletion(self):
        m.bootstrap(self.root,'ci-required')
        self.git('add','.');self.git('commit','-qm','fixture sharding foundation')
        (self.root/m.REQUIREMENT).unlink();(self.root/m.MANIFEST).unlink()
        self.assertTrue(m.requirement(self.root))
        with self.assertRaisesRegex(m.Refusal,'missing regular'): m.validate(self.root,activation=True)

    def test_configuration_covers_each_discovered_test_once(self):
        self.configured()
        result=m.validate(self.root,activation=True)
        self.assertEqual(result['shards'],['a','b']);self.assertEqual(result['test_files'],2)
        (self.root/'test_new.py').write_text('new test')
        with self.assertRaisesRegex(m.Refusal,'unassigned=test_new.py'):m.validate(self.root,activation=True)

    def test_invalid_shards_are_refused(self):
        original=self.configured()
        for label,mutate in {
            'empty':lambda v:v['shards'][0].update(tests=[]),
            'duplicate membership':lambda v:v['shards'][1].update(tests=['test_a.py']),
            'duplicate id':lambda v:v['shards'][1].update(id='a'),
            'command':lambda v:v['shards'][0].update(command=[]),
            'one shard':lambda v:v.update(shards=v['shards'][:1]),
            'timeout bool':lambda v:v['shards'][0].update(timeout_seconds=True),
            'absolute executable':lambda v:v['shards'][0].update(command=['/private/program']),
            'traversal':lambda v:v['shards'][0].update(tests=['../foreign.py']),
        }.items():
            with self.subTest(label=label):
                value=copy.deepcopy(original);mutate(value);self.write(value)
                with self.assertRaises(m.Refusal):m.validate(self.root,activation=True)

    def test_symlinked_paths_and_duplicate_json_keys_are_refused(self):
        self.configured();path=self.root/'test_a.py';path.unlink();path.symlink_to('test_b.py')
        with self.assertRaises(m.Refusal):m.validate(self.root,activation=True)
        with self.assertRaises(m.Refusal):m.parse('{"schema":1,"schema":2}')
        with self.assertRaises(m.Refusal):m.validate_requirement({'schema':m.REQUIRED['schema'],'required':1})

    def reports(self,contract):
        return [dict(schema='dev-test-shard-result/v1',shard=identity,revision='a'*40,
                     contract_sha256=contract['contract_sha256'],status='passed',tests=2) for identity in contract['shards']]

    def test_aggregate_rejects_every_incomplete_or_stale_result(self):
        self.configured();contract=m.validate(self.root);reports=self.reports(contract)
        self.assertEqual(m.validate_reports(contract,reports,'a'*40)['status'],'passed')
        for status in ('failed','skipped','cancelled','missing','pending'):
            changed=copy.deepcopy(reports);changed[0]['status']=status
            with self.subTest(status=status),self.assertRaises(m.Refusal):m.validate_reports(contract,changed,'a'*40)
        for field,value in [('tests',0),('tests',True),('shard','unknown'),('revision','b'*40),('contract_sha256','b'*64)]:
            changed=copy.deepcopy(reports);changed[0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(m.Refusal):m.validate_reports(contract,changed,'a'*40)
        for changed in (reports[:1],reports+[reports[0]],[reports[0],reports[0]]):
            with self.assertRaises(m.Refusal):m.validate_reports(contract,changed,'a'*40)

    def request(self,path):
        if '/commits?' in path:return [{'sha':'a'*40}] if self.remote_required else []
        if '/commits/' in path:return {'sha':'a'*40}
        if '/git/trees/' in path:
            return {'truncated':False,'tree':[dict(path=name,type='blob',mode='100644')
                    for name in [m.REQUIREMENT,m.MANIFEST,'test_a.py','test_b.py'] if name not in self.removed]}
        if '/contents/' in path:
            name=path.split('/contents/',1)[1].split('?',1)[0]
            return dict(type='file',encoding='base64',content=base64.b64encode((self.root/name).read_bytes()).decode())
        raise AssertionError(path)

    def test_remote_history_blocks_deleting_requirement_or_manifest(self):
        self.configured();self.remote_required=True;self.removed=[]
        contract=m.validate_remote('fixture-owner/product','main',self.request)
        self.assertTrue(contract['activation_allowed'])
        for path in (m.REQUIREMENT,m.MANIFEST):
            self.removed=[path]
            with self.assertRaisesRegex(m.Refusal,'removed'):m.validate_remote('fixture-owner/product','main',self.request)
        self.remote_required=False
        self.assertEqual(m.validate_remote('fixture-owner/product','main',self.request)['state'],'legacy')

    def test_remote_pending_fails_before_activation(self):
        m.bootstrap(self.root,'ci-required');self.remote_required=True;self.removed=[]
        with self.assertRaisesRegex(m.Refusal,'pending'):m.validate_remote('fixture-owner/product','main',self.request)

    def test_native_activation_rejects_controller_aggregate(self):
        contract={'required':True,'aggregate':'pr-automation / verify'}
        with (mock.patch.object(m,'validate_remote',return_value=contract),
              mock.patch.object(m.sys,'argv',['test-sharding.py','verify-remote','--repository','fixture-owner/product','--ref','main']),
              contextlib.redirect_stderr(io.StringIO()) as errors):
            self.assertEqual(m.main(),1)
        self.assertIn('aggregate gate mismatch',errors.getvalue())

    def test_controller_coverage_must_bind_identity_profile_lock_and_all_shards(self):
        value=self.configured();value['aggregate']='pr-automation / verify';self.write(value);contract=m.validate(self.root)
        assignment={'profile_ref':{'id':'fixture.v1','digest':'sha256:'+'1'*64}}
        proof={'validated':True,'lock_digest':'sha256:'+'2'*64}
        empty={'schema':'dev-test-sharding-coverage/v1','repositories':[]}
        kwargs=dict(repository='fixture-owner/product',repository_id=123,assignment=assignment,proof=proof)
        with self.assertRaisesRegex(m.Refusal,'approved controller'):m.controller_coverage(contract,empty,**kwargs)
        record=dict(repository='fixture-owner/product',repository_id=123,contract_sha256=contract['contract_sha256'],
                    profile_ref=assignment['profile_ref'],lock_digest=proof['lock_digest'],shards=contract['shards'])
        authority=dict(empty,repositories=[record]);m.controller_coverage(contract,authority,**kwargs)
        with self.assertRaisesRegex(m.Refusal,'aggregate gate mismatch'):
            m.controller_coverage(dict(contract,aggregate='ci-required'),authority,**kwargs)
        for field,value in [('repository_id',True),('contract_sha256','bad'),('profile_ref',{}),('lock_digest','bad'),('shards',['a'])]:
            changed=copy.deepcopy(authority);changed['repositories'][0][field]=value
            with self.subTest(field=field),self.assertRaises(m.Refusal):m.controller_coverage(contract,changed,**kwargs)

if __name__=='__main__':unittest.main()
