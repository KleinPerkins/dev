#!/usr/bin/env python3
"""Negative CI receipt, schema, command and process-bound regressions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dev_ci',ROOT/'scripts/verify.py');ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
ENV=dict(GITHUB_REPOSITORY='KleinPerkins/dev-temp',GITHUB_REPOSITORY_ID='1459458379',GITHUB_EVENT_NAME='pull_request',GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='100',GITHUB_RUN_ATTEMPT='2',GITHUB_REF='refs/pull/12/merge',CI_HEAD_SHA='c'*40,CI_BASE_SHA='d'*40,GITHUB_WORKFLOW_REF='KleinPerkins/dev-temp/.github/workflows/ci.yml@refs/pull/12/merge',GITHUB_WORKFLOW='CI')

def policy_fixture(root):
    (root/'.github').mkdir()
    for p in ('.github/ci-contract.json','.github/test-shards.json'):(root/p).write_bytes((ROOT/p).read_bytes())
    m=ci.parse((root/'.github/test-shards.json').read_bytes())
    for s in m['shards']:
        for name in s['tests']:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# fixture source only\n')
    return ci.policy(root)
def evidence(c,m,h):
    return {s['id']:{'result':'success','outputs':{'receipt':json.dumps({'schema':'dev-ci-shard/v1','shard':s['id'],'identity':ci.identity(ENV),'result':'success','measurement':{'commands':[x['id'] for x in c['commands'][s['id']]]+s['tests'],'tests':s['tests'],'case_count':2,'case_ids_sha256':'a'*64,'skips':[],'host_not_qualified':[],'logs_sha256':'b'*64,'contract_sha256':h}})}} for s in m['shards']}
class Receipts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.policy=policy_fixture(self.root)
        self.patcher=patch.object(ci,'policy',return_value=self.policy);self.patcher.start();self.addCleanup(self.patcher.stop)
    def test_exact_union_passes(self):ci.validate_aggregate(evidence(*self.policy),ci.identity(ENV))
    def test_dispatch_aggregate_cannot_mix_event_or_run_identity(self):
        expected=ci.identity(dict(ENV,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF='refs/heads/main',
            CI_HEAD_SHA='',CI_BASE_SHA='',GITHUB_WORKFLOW_REF='KleinPerkins/dev-temp/.github/workflows/ci.yml@refs/heads/main'))
        needs=evidence(*self.policy)
        for row in needs.values():
            receipt=json.loads(row['outputs']['receipt']);receipt['identity']=dict(expected)
            row['outputs']['receipt']=json.dumps(receipt)
        ci.validate_aggregate(needs,expected)
        for key,value in (('event','push'),('event','pull_request'),('run_id','101'),('run_attempt','1'),
                ('revision','b'*40),('workflow_sha','b'*40),('ref','refs/heads/topic')):
            changed=copy.deepcopy(needs);receipt=json.loads(changed['owner-contracts']['outputs']['receipt'])
            receipt['identity'][key]=value;changed['owner-contracts']['outputs']['receipt']=json.dumps(receipt)
            with self.subTest(key=key,value=value),self.assertRaises(ci.ContractError):ci.validate_aggregate(changed,expected)
    def test_each_non_success_status_refuses(self):
        for shard in ci.SHARDS:
            for status in ('failure','cancelled','skipped','neutral','timed_out','',None):
                n=evidence(*self.policy);n[shard]['result']=status
                with self.subTest(shard=shard,status=status),self.assertRaises(ci.ContractError):ci.validate_aggregate(n,ci.identity(ENV))
    def test_missing_extra_duplicate_and_malformed_receipts(self):
        n=evidence(*self.policy);cases=[None,{},dict(n,extra={})]
        x=copy.deepcopy(n);x.pop('doc-warden');cases.append(x)
        x=copy.deepcopy(n);x['ci-negative']=x['owner-contracts'];cases.append(x)
        for raw in ('null','[]','{}','not JSON','{"schema":1,"schema":2}'):
            x=copy.deepcopy(n);x['owner-contracts']['outputs']['receipt']=raw;cases.append(x)
        for x in cases:
            with self.subTest(x=x),self.assertRaises((ci.ContractError,ValueError)):ci.validate_aggregate(x,ci.identity(ENV))
    def mutate(self,change):
        n=evidence(*self.policy);r=json.loads(n['owner-contracts']['outputs']['receipt']);change(r);n['owner-contracts']['outputs']['receipt']=json.dumps(r)
        with self.assertRaises(ci.ContractError):ci.validate_aggregate(n,ci.identity(ENV))
    def test_every_identity_field_bound(self):
        for k in ci.IDENTITY_KEYS:self.mutate(lambda r:r['identity'].__setitem__(k,r['identity'][k]+'stale'))
    def test_receipt_schema_and_measurement_failures(self):
        changes=[lambda r:r.update(schema='canary-ci-shard/v1'),lambda r:r.update(extra=True),lambda r:r.update(result='failed'),lambda r:r.update(shard='other')]
        for k,v in [('tests',[]),('commands',[]),('case_count',0),('case_count',True),('contract_sha256','f'*64),('logs_sha256',''),('case_ids_sha256','x'),('skips',[{'module':'missing','case':'test','reason':'pass'}])]:
            changes.append(lambda r,k=k,v=v:r['measurement'].__setitem__(k,v))
        for change in changes:self.mutate(change)
    def test_unknown_and_duplicate_skips_refuse(self):
        row={'module':self.policy[1]['shards'][0]['tests'][0],'case':'fixture.test','reason':'unknown'}
        self.mutate(lambda r:r['measurement'].update(skips=[row]))
        row['reason']=self.policy[0]['allowed_skip_reasons'][0]
        self.mutate(lambda r:r['measurement'].update(case_count=5,skips=[row,row]))
    def test_required_runtime_skip_never_qualifies(self):
        c,m,h=self.policy;shard='doc-warden';row=next(s for s in m['shards'] if s['id']==shard)
        n=evidence(c,m,h);r=json.loads(n[shard]['outputs']['receipt']);reason=c['allowed_skip_reasons'][0]
        r['measurement'].update(skips=[{'module':'_ops/doc-warden/v2/tests/test_cli.py','case':c['nonpassing_runtime_cases'][0],'reason':reason}],host_not_qualified=[reason])
        n[shard]['outputs']['receipt']=json.dumps(r)
        with self.assertRaises(ci.ContractError):ci.validate_aggregate(n,ci.identity(ENV))
    def test_all_skipped_refuses(self):
        row={'module':self.policy[1]['shards'][0]['tests'][0],'case':'fixture.test','reason':self.policy[0]['allowed_skip_reasons'][0]}
        self.mutate(lambda r:r['measurement'].update(case_count=1,skips=[row]))
class IdentityAndBounds(unittest.TestCase):
    def test_shell_startup_cannot_displace_fixture_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);startup=root/'startup.sh';marker=root/'startup-ran'
            startup.write_text('touch "'+str(marker)+'"\nexport PATH=/usr/bin:/bin\n')
            tool=root/'fixture-only-command';tool.write_text('#!/bin/sh\nprintf fixture-ok\n');tool.chmod(0o755)
            with patch.dict(ci.os.environ,{'BASH_ENV':str(startup),'ENV':str(startup),
                    'PATH':str(root)+ci.os.pathsep+ci.os.environ['PATH'],
                    'GH_TOKEN':'synthetic-token-must-not-reach-child'}):
                output=ci.bounded(['/bin/bash','-c',
                    'test -z "${BASH_ENV+x}${ENV+x}${GH_TOKEN+x}" && fixture-only-command'],5)
            self.assertEqual(output,b'fixture-ok');self.assertFalse(marker.exists())
    def test_isolated_doc_warden_module_uses_exact_source_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'activation.json'
            code=("import importlib.util, pathlib, sys; "
                "spec=importlib.util.spec_from_file_location('isolated_ci',"+repr(str(ROOT/'scripts/verify.py'))+"); "
                "runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner); "
                "runner.run_test_module('_ops/doc-warden/v2/tests/test_activation.py',"+repr(str(output))+"); "
                "import doc_warden; "
                "assert pathlib.Path(doc_warden.__file__).resolve().parent == runner.ROOT/'_ops/doc-warden/v2/doc_warden'")
            ci.bounded([sys.executable,'-I','-B','-c',code],60)
            measured=ci.parse(output.read_bytes())
            self.assertEqual(measured['module'],'_ops/doc-warden/v2/tests/test_activation.py')
            self.assertTrue(any('test_policy_runtime_schema_catalog_and_dispatch_activate_atomically' in case
                for case in measured['cases']))
            self.assertEqual(measured['skips'],[])
    def test_subtest_skips_conservatively_bind_registered_parent_without_count_inflation(self):
        policy=ci.policy()[0];reason=policy['allowed_skip_reasons'][0]
        protected=policy['nonpassing_runtime_cases'][0]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);module=root/'tests/test_cli.py';module.parent.mkdir()
            module.write_text("import unittest\nclass Cases(unittest.TestCase):\n"
                " def test_children(self):\n  for value in (1,2):\n   with self.subTest(value=value):self.skipTest("+repr(reason)+")\n"
                "class CliTests(unittest.TestCase):\n def test_runtime_install_requires_digest_bound_generic_apply(self):\n"
                "  with self.subTest(runtime='required'):self.skipTest("+repr(reason)+")\n")
            output=root/'result.json'
            with patch.object(ci,'ROOT',root),patch.object(ci.sys,'path',list(sys.path)),patch.dict(ci.sys.modules):
                ci.run_test_module('tests/test_cli.py',output)
            result=ci.parse(output.read_bytes())
            self.assertEqual(set(result['cases']),{'test_cli.Cases.test_children',protected})
            self.assertEqual(len(result['cases']),2,'subcases must not inflate executed case IDs')
            self.assertEqual(result['skips'],[
                {'case':'test_cli.Cases.test_children','reason':reason},
                {'case':protected,'reason':reason}])
            self.assertIn(protected,{row['case'] for row in result['skips']},
                'required-runtime refusal must still match its canonical parent')
    def test_doc_warden_runner_refuses_installed_package_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);test=root/'_ops/doc-warden/v2/tests/fallback_probe.py'
            test.parent.mkdir(parents=True);test.write_text('import doc_warden\n')
            installed=root/'installed';package=installed/'doc_warden';package.mkdir(parents=True)
            marker=root/'fallback-executed'
            (package/'__init__.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
            with patch.object(ci,'ROOT',root),patch.object(ci.sys,'path',[str(installed),*sys.path]):
                with self.assertRaisesRegex(ci.ContractError,'exact source package'):
                    ci.run_test_module(str(test.relative_to(root)),root/'result.json')
            self.assertFalse(marker.exists());self.assertFalse((root/'result.json').exists())
    def test_all_required_fields_and_wrong_id(self):
        for k in ENV:
            with self.subTest(k=k),self.assertRaises(ci.ContractError):ci.identity(dict(ENV,**{k:''}))
        for repo,id_ in [('KleinPerkins/dev-temp','1278387789'),('KleinPerkins/dev','1278387789'),('other/dev','1459458379')]:
            with self.assertRaises(ci.ContractError):ci.identity(dict(ENV,GITHUB_REPOSITORY=repo,GITHUB_REPOSITORY_ID=id_))
    def test_names_are_closed_and_phase_coherent(self):
        final=dict(ENV,GITHUB_REPOSITORY='KleinPerkins/dev',GITHUB_WORKFLOW_REF=ENV['GITHUB_WORKFLOW_REF'].replace('dev-temp','dev'));ci.identity(final)
        with self.assertRaises(ci.ContractError):ci.identity(dict(final,GITHUB_WORKFLOW_REF=ENV['GITHUB_WORKFLOW_REF']))
    def test_push_tuple_only_main(self):
        push=dict(ENV,GITHUB_EVENT_NAME='push',GITHUB_REF='refs/heads/main',CI_HEAD_SHA='',CI_BASE_SHA='',GITHUB_WORKFLOW_REF='KleinPerkins/dev-temp/.github/workflows/ci.yml@refs/heads/main');ci.identity(push)
        for changes in ({'GITHUB_REF':'refs/heads/other'},{'CI_HEAD_SHA':'a'*40},{'GITHUB_EVENT_NAME':'pull_request_target'},{'GITHUB_RUN_ATTEMPT':'0'}):
            with self.assertRaises(ci.ContractError):ci.identity(dict(push,**changes))
    def test_dispatch_and_push_event_matrix(self):
        for repository in ci.NAMES:
            for event in ('push','workflow_dispatch'):
                env=dict(ENV,GITHUB_REPOSITORY=repository,GITHUB_EVENT_NAME=event,
                    GITHUB_REF='refs/heads/main',CI_HEAD_SHA='',CI_BASE_SHA='',
                    GITHUB_WORKFLOW_REF=repository+'/.github/workflows/ci.yml@refs/heads/main')
                with self.subTest(repository=repository,event=event):
                    self.assertEqual(ci.identity(env)['event'],event)
                negatives=[{'GITHUB_REF':ref,'GITHUB_WORKFLOW_REF':repository+'/.github/workflows/ci.yml@'+ref}
                    for ref in ('refs/heads/topic','refs/tags/main','refs/pull/12/merge','main','')]
                negatives += [{key:value} for key,value in (
                    ('CI_HEAD_SHA','c'*40),('CI_BASE_SHA','d'*40),
                    ('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_SHA','b'*40),
                    ('GITHUB_WORKFLOW_REF',repository+'/.github/workflows/other.yml@refs/heads/main'),
                    ('GITHUB_WORKFLOW_REF',repository+'/.github/workflows/ci.yml@refs/heads/topic'),
                    ('GITHUB_WORKFLOW','Other'),('GITHUB_REPOSITORY_ID','1278387789'))]
                negatives += [{'GITHUB_EVENT_NAME':other} for other in
                    ('pull_request','pull_request_target','repository_dispatch','schedule','workflow_run','')]
                for changes in negatives:
                    with self.subTest(event=event,changes=changes),self.assertRaises(ci.ContractError):
                        ci.identity(dict(env,**changes))
                expected=ci.identity(env)
                with patch.object(ci.subprocess,'check_output',return_value='b'*40),self.assertRaises(ci.ContractError):
                    ci.check_checkout(expected)
                with patch.object(ci.subprocess,'check_output',return_value='a'*40) as checkout:
                    ci.check_checkout(expected);self.assertEqual(checkout.call_count,1)
    def test_pull_request_cannot_use_main_or_dispatch_fields(self):
        ci.identity(ENV)
        for changes in ({'GITHUB_REF':'refs/heads/main'}, {'CI_HEAD_SHA':''}, {'CI_BASE_SHA':''},
                {'GITHUB_EVENT_NAME':'workflow_dispatch'},{'GITHUB_EVENT_NAME':'push'},
                {'GITHUB_WORKFLOW_SHA':'b'*40}):
            with self.subTest(changes=changes),self.assertRaises(ci.ContractError):ci.identity(dict(ENV,**changes))
    def test_merge_parent_order_and_revision(self):
        expected=ci.identity(ENV)
        for outputs in [('a'*40,'d'*40+' '+'c'*40),('b'*40,'d'*40+' '+'c'*40),('a'*40,'c'*40+' '+'d'*40),('a'*40,'d'*40)]:
            with patch.object(ci.subprocess,'check_output',side_effect=outputs):
                if outputs==('a'*40,'d'*40+' '+'c'*40):ci.check_checkout(expected)
                else:
                    with self.assertRaises(ci.ContractError):ci.check_checkout(expected)
    def test_output_timeout_and_nonzero_fail_and_reap(self):
        with patch.object(ci,'MAX_OUTPUT',100):
            with self.assertRaises(ci.ContractError):ci.bounded([sys.executable,'-c','print("x"*101)'],5)
        with self.assertRaises(ci.ContractError):ci.bounded([sys.executable,'-c','import time;time.sleep(10)'],.1)
        with self.assertRaises(ci.ContractError):ci.bounded([sys.executable,'-c','raise SystemExit(2)'],5)
        self.assertEqual(ci.bounded([sys.executable,'-c','print(42)'],5).strip(),b'42')
    def test_failed_command_preserves_early_diagnostic_within_output_bound(self):
        with self.assertRaises(ci.ContractError) as error:
            ci.bounded([sys.executable,'-c','print("EARLY_FAILURE");print("x"*15000);raise SystemExit(1)'],5)
        self.assertIn('EARLY_FAILURE',str(error.exception))
        self.assertIn('x'*15000,str(error.exception))
class Inventory(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);policy_fixture(self.root)
    def modify(self,path,change):
        p=self.root/path;v=json.loads(p.read_text());change(v);p.write_text(json.dumps(v))
    def test_baseline_97_plus_new_unique_test_inventory(self):
        c,m,_=ci.policy(self.root);self.assertEqual(len(c['baseline_tests']),97);self.assertGreater(sum(len(s['tests']) for s in m['shards']),97)
    def test_unlisted_missing_duplicate_and_baseline_coverage_fail(self):
        p=self.root/'tests/test_unlisted.py';p.write_text('');
        with self.assertRaises(ci.ContractError):ci.policy(self.root)
        p.unlink();p=self.root/'tests/test_ci.py';p.unlink()
        with self.assertRaises(ci.ContractError):ci.policy(self.root)
    def test_schema_extra_and_discovery_exclusion_refuse(self):
        self.modify('.github/test-shards.json',lambda m:m['discovery'].update(exclude=['tests/*']))
        with self.assertRaises(ci.ContractError):ci.policy(self.root)
    def test_unknown_command_and_missing_baseline_refuse(self):
        self.modify('.github/test-shards.json',lambda m:m['shards'][0].update(command=['echo','pass']))
        with self.assertRaises(ci.ContractError):ci.policy(self.root)
if __name__=='__main__':unittest.main()
