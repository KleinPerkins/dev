#!/usr/bin/env python3
"""Successor source workflow security and complete command ownership contract."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('dev_verify',ROOT/'scripts/verify.py');ci=importlib.util.module_from_spec(s);s.loader.exec_module(ci)
CHECKOUT='actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
SETUP='actions/setup-python@e797f83bcb11b83ae66e0230d6156d7c80228e7c'
def workflow(w):
    ci.closed(w,'name on permissions concurrency jobs');ci.require(w['name']=='CI' and w['permissions']=={'contents':'read'},'source permission scope')
    ci.require(w['on']=={'pull_request':{'types':['opened','reopened','synchronize','ready_for_review']},'push':{'branches':['main']},'workflow_dispatch':{}},'required event/path coverage')
    ci.require(w['concurrency']=={'group':'ci-${{ github.event.pull_request.number || github.ref }}','cancel-in-progress':True},'concurrency')
    ci.require(set(w['jobs'])==set(ci.SHARDS)|{'ci-required'},'job topology')
    for name,job in w['jobs'].items():
        ci.closed(job,'name needs if runs-on timeout-minutes steps' if name=='ci-required' else 'name if runs-on timeout-minutes outputs steps')
        ci.require(job['name']==name and job['runs-on']==('macos-14' if name=='interop-portability' else 'ubuntu-24.04'),'job name/runner')
        ci.require(type(job['timeout-minutes']) is int and 0<job['timeout-minutes']<=30,'unbounded job')
        if name=='ci-required':ci.require(job['needs']==list(ci.SHARDS) and job['if']=='${{ always() }}','aggregate cannot skip failed shards')
        else:
            ci.require(job['if']=="${{ github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main' }}",'dispatch must select main only')
            ci.require(job['outputs']=={'receipt':'${{ steps.verify.outputs.receipt }}'},'receipt output')
        steps=job['steps'];ci.require(len(steps)==(3 if name=='ci-required' else 4),'extra/missing source step')
        ci.require(steps[0]=={'uses':CHECKOUT,'with':{'ref':'${{ github.sha }}','persist-credentials':False,'fetch-depth':0}},'source checkout unsafe')
        ci.require(steps[1]=={'uses':SETUP,'with':{'python-version':'3.12.12'}},'unpinned Python setup')
        if name!='ci-required':ci.require(steps[2]=={'name':'Install locked source test dependency','run':'python3 -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r .github/ci-requirements.txt'},'dependency install not locked')
        last=steps[-1];ci.closed(last,'name env run' if name=='ci-required' else 'name id env run')
        env={'CI_HEAD_SHA':'${{ github.event.pull_request.head.sha }}','CI_BASE_SHA':'${{ github.event.pull_request.base.sha }}'}
        if name=='ci-required':env['CI_NEEDS']='${{ toJSON(needs) }}'
        else:ci.require(last['id']=='verify','wrong receipt step')
        ci.require(last['env']==env,'untrusted/secret source env')
        ci.require(last['run']=='python3 -I -B scripts/verify.py '+('aggregate' if name=='ci-required' else 'shard --shard '+name),'unbound shard command')
class Contract(unittest.TestCase):
    def load(self):return json.loads((ROOT/'.github/workflows/ci.yml').read_text())
    def test_actual_source_workflow(self):workflow(self.load())
    def test_inventory_and_existing_sharding_schema(self):
        c,m,_=ci.policy();self.assertEqual(sum(len(s['tests']) for s in m['shards']),len(list(ROOT.glob('_ops/**/test_*.py')))+len(list(ROOT.glob('tests/test_*.py'))))
        self.assertEqual(json.loads((ROOT/'.github/test-sharding-required.json').read_text()),{'schema':'dev-test-sharding-requirement/v1','required':True})
    def test_workflow_negative_mutations(self):
        mutations=[lambda w:w['on'].pop('workflow_dispatch'),lambda w:w['on']['workflow_dispatch'].update(inputs={'ref':{'type':'string'}}),lambda w:w['on'].update(repository_dispatch={}),lambda w:w['jobs']['owner-contracts'].update({'if':'true'}),lambda w:w.update(permissions={'contents':'write'}),lambda w:w['on']['pull_request'].update(paths=['docs/**']),lambda w:w['jobs'].pop('doc-warden'),lambda w:w['jobs']['ci-required'].update(needs=['ci-negative']),lambda w:w['jobs']['ci-required'].update({'if':'success()'}),lambda w:w['jobs']['interop-portability'].update({'runs-on':'ubuntu-24.04'}),lambda w:w['jobs']['owner-contracts']['steps'][0]['with'].update({'persist-credentials':True}),lambda w:w['jobs']['owner-contracts']['steps'][1].update(uses='actions/setup-python@main'),lambda w:w['jobs']['owner-contracts']['steps'].append({'run':'echo success'}),lambda w:w['jobs']['review-admission']['steps'][-1]['env'].update(TOKEN='${{ secrets.TOKEN }}')]
        for mutate in mutations:
            w=self.load();mutate(w)
            with self.subTest(mutate=mutate),self.assertRaises(ci.ContractError):workflow(w)
    def test_context_path_and_full_inventory_both_include_discovery(self):
        path=json.loads((ROOT/'_ops/verification/path-checks.json').read_text());args=path['areas'][0]['checks'][0]['argv'];self.assertIn('test_capability_discovery_inventory.py',args)
        m=json.loads((ROOT/'.github/test-shards.json').read_text());self.assertIn('_ops/context-measurement/test_capability_discovery_inventory.py',next(s['tests'] for s in m['shards'] if s['id']=='context-measurement'))
    def test_full_union_is_one_dispatcher_and_installed_host_checks_separate(self):
        shell=(ROOT/'_ops/checks/verify-operating-model.sh').read_text();self.assertIn('--ci) exec python3 -I -B "$ROOT/scripts/verify.py" local',shell);self.assertIn('--ci-group)',shell)
        self.assertIn('verify-ci:',(ROOT/'Makefile').read_text());self.assertIn('if [ "$MODE" = "ci" ]; then',shell)
    def test_dependencies_and_disabled_empty_registry_are_not_seed_ready(self):
        lock=(ROOT/'.github/ci-requirements.txt').read_text();self.assertTrue(lock.startswith('PyYAML==6.0.3'));self.assertGreaterEqual(len(re.findall(r'--hash=sha256:[0-9a-f]{64}',lock)),2)
        p=json.loads((ROOT/'.github/review-enrollments.json').read_text());self.assertEqual(p['repository_id'],1459458379)
        self.assertTrue((p['enabled'] is False and not p['producers']) or (p['enabled'] is True and len(p['producers'])==2))
if __name__=='__main__':unittest.main()
