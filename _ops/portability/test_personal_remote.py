"""Staged remote scope/hash proofs and private qualified-process fixtures.

Fixture compiler hashes/controllers are test-only. No fixture establishes Rust,
operator visibility, actual remote, native or release qualification.
"""
import ast
import builtins
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat
import symtable
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_remote as m
from test_personal_profile import NOW,policy,git_tree

REPO='KleinPerkins/skills'
HEAD='f'*40
BASE='b'*40
HEX='sha256:'+'a'*64


def envelope(rows=None):return {'schema':'personal-doctor-remote-observations/v1','observed_at':NOW.isoformat(),'requests':rows or []}


def row(url,data,outcome='ok'):return {'url':url,'outcome':outcome,'data':data}


def metadata(repo=REPO):return {'id':m.p.REPOSITORY_IDS[repo],'full_name':repo,'default_branch':'main'}


def object_tree(files):
    blobs={};entries=[]
    for name,raw in sorted(files.items()):
        oid=m.git_blob(raw);blobs[oid]=raw.decode()
        entries.append({'path':name,'mode':'100644','type':'blob','sha':oid})
    github=git_tree(entries);root=git_tree([{'path':'.github','mode':'040000','type':'tree','sha':github['sha']}])
    return root,github,blobs


def fleet_evidence(authority,*,mutation=None):
    projected=authority.projection(REPO);assignment=projected.assignment
    recipe=b'{"fixture":"synthetic immutable recipe"}\n'
    payload={'repository_id':'skills','activation_generation':authority.controller['release']['activation_generation'],
             'lock_contract_version':1,'catalog_id':'pr-automation-execution-catalog/v1',
             'profile_id':assignment['profile_ref']['id'],'profile_digest':assignment['profile_ref']['digest'],
             'image_digest':m.owner.expected_profile_image(authority.controller,assignment['profile_ref']['id']),
             'catalog_digest':HEX,'recipe_digest':HEX,'assignment_digest':HEX,
             'recipe_base_sha':BASE,'recipe_blob_sha':m.git_blob(recipe)}
    lock={'schema_version':'pr-automation-lock/v2','lock_digest':HEX,'payload':payload}
    config=policy(authority);rules=copy.deepcopy(projected.ruleset)
    rules.update(id=authority.targets[REPO]['merge_safety_ruleset_id'],source_type='Repository',source=REPO)
    if mutation:mutation(config,lock,rules)
    files={'pr-automation.json':json.dumps(config,separators=(',',':')).encode(),
           'pr-recipe.json':recipe,'pr-automation.lock.json':json.dumps(lock,separators=(',',':')).encode()}
    root,github,blobs=object_tree(files);historical,historical_github,historical_blobs=object_tree({'pr-recipe.json':recipe})
    prefix=m.base(REPO)
    branch={'name':'main','commit':{'sha':HEAD,'commit':{'tree':{'sha':root['sha']}}}}
    requests=[row(prefix,metadata()),row(prefix+'/branches/main',branch),
              row(prefix+'/rulesets?per_page=100&page=1',[{'id':rules['id'],'name':rules['name'],'target':'branch','enforcement':'active'}]),
              row(prefix+'/rulesets/'+str(rules['id']),rules),
              row(prefix+'/git/commits/'+BASE,{'sha':BASE,'tree':{'sha':historical['sha']}})]
    objects={t['sha']:t for t in (root,github,historical,historical_github)}
    requests += [row(prefix+'/git/trees/'+oid,value) for oid,value in objects.items()]
    requests += [row(prefix+'/git/blobs/'+oid,value) for oid,value in {**blobs,**historical_blobs}.items()]
    return envelope(requests)


def observed(value,authority=None,selected=None):
    authority=authority or m.p.Authority()
    return m.Observations(value,selected or [REPO],authority,now=NOW)


class FixtureCompiler:
    calls=0
    def __init__(self,home,controller):self.controller=controller
    def validate(self,repo,assignment,recipe,lock):
        type(self).calls+=1;payload=json.loads(lock)['payload']
        return {'validated':True,'schema_version':'pr-automation-lock/v2','lock_contract_version':1,
                'covered_digests':{key:payload[key] for key in m.owner.LOCK_COVERED_DIGEST_FIELDS},
                'compiler_digest':self.controller['release']['lock_compiler_digest']}


class Protocol(unittest.TestCase):
    def test_only_selected_canonical_GET_targets_and_fresh_snapshots(self):
        authority=m.p.Authority()
        for url in ('https://api.github.com/repos/Other/skills',m.base(REPO)+'/contents/.github/pr-automation.json',
                    m.base(REPO)+'/branches/../main',m.base(REPO)+'/branches/feature/raw',
                    m.base(REPO)+'/rulesets?per_page=100&page=11',m.base(REPO)+'/git/trees/'+'A'*40):
            with self.subTest(url=url),self.assertRaises(m.g.Refusal):observed(envelope([row(url,{})]),authority)
        value=envelope();value['observed_at']=(NOW-dt.timedelta(seconds=301)).isoformat()
        with self.assertRaises(m.g.Refusal):observed(value,authority)
        value=envelope([row(m.base(REPO),metadata())]);value['requests']*=2
        with self.assertRaises(m.g.Refusal):observed(value,authority)

    def test_identity_precedes_every_dependent_request(self):
        value=envelope([row(m.base(REPO),{**metadata(),'id':1}),row(m.base(REPO)+'/branches/main',{'name':'main','commit':{'sha':HEAD}})])
        obs=observed(value);result=m.sync(REPO,{'available':True,'head':HEAD,'branch':'main'},obs)
        self.assertFalse(result['available']);self.assertEqual(obs.used,{m.base(REPO)})
        self.assertEqual(obs.missing,{})

    def test_detached_skip_and_named_branch_equal_different_and_fallback(self):
        authority=m.p.Authority()
        obs=observed(None,authority);result=m.sync(REPO,{'available':True,'head':HEAD,'branch':None},obs)
        self.assertEqual(result['classification'],'NOT_APPLICABLE');self.assertEqual(obs.missing,{})
        for remote_head,expected in ((HEAD,'EQUAL'),('e'*40,'DIFFERENT')):
            value=envelope([row(m.base(REPO),metadata()),row(m.base(REPO)+'/branches/feature%2Fseeds',{'name':'feature/seeds','commit':{'sha':remote_head}})])
            obs=observed(value,authority);result=m.sync(REPO,{'available':True,'head':HEAD,'branch':'feature/seeds'},obs)
            self.assertEqual(result['classification'],expected);obs.check_used()
        obs=observed(envelope([row(m.base(REPO),metadata())]),authority)
        result=m.sync(REPO,{'available':True,'head':HEAD,'branch':'main'},obs)
        self.assertFalse(result['available']);self.assertIn('local tracking',result['fallback'])
        self.assertEqual(list(obs.missing),[m.base(REPO)+'/branches/main'])

    def test_unproven_dynamic_objects_are_not_silently_ignored(self):
        obs=observed(envelope([row(m.base(REPO)+'/git/trees/'+'d'*40,{'PRIVATE_UNPROVEN':'not emitted'})]))
        with self.assertRaises(m.g.Refusal):obs.check_used()

    def test_ruleset_pagination_completeness_and_duplicates(self):
        prefix=m.base(REPO)+'/rulesets?per_page=100&page='
        value=envelope([row(prefix+'1',[{'id':i} for i in range(1,101)]),row(prefix+'2',[{'id':101}])])
        self.assertEqual(len(observed(value).rulesets(REPO)),101)
        value['requests'][1]['data']=[{'id':1}]
        with self.assertRaises(m.Unavailable):observed(value).rulesets(REPO)
        with self.assertRaises(m.Unavailable):observed(envelope(value['requests'][:1])).rulesets(REPO)

    def test_blob_tree_hashes_types_and_extra_paths(self):
        a=m.p.Authority();value=fleet_evidence(a);obs=observed(value,a)
        obs.metadata(REPO);branch=obs.branch(REPO,'main');tree=obs.tree_at(REPO,HEAD,branch=branch)
        raw,oid=obs.file(REPO,tree,m.p.POLICY);self.assertEqual(m.git_blob(raw),oid)
        with self.assertRaises(m.g.Refusal):obs.file(REPO,tree,'agent-learnings.md')
        tree_url=m.base(REPO)+'/git/trees/'+tree
        next(row for row in value['requests'] if row['url']==tree_url)['data']['tree'][0]['sha']='0'*40
        obs=observed(value,a)
        with self.assertRaises(m.Unavailable):obs.file(REPO,tree,m.p.POLICY)

    def test_malformed_branch_commit_tree_and_authority_stay_unavailable(self):
        obs=observed(None)
        for value in (None,{'commit':None},{'commit':{'commit':None}},
                      {'commit':{'commit':{'tree':[]}}}):
            with self.subTest(value=value),self.assertRaises(m.Unavailable):obs.tree_at(REPO,HEAD,branch=value or {})
        for controller in (None,{}, {'release':None},{'release':[]}):
            with self.subTest(controller=controller),self.assertRaises(m.Unavailable):m.QualifiedCompiler(Path('/not-read'),controller)


class Fleet(unittest.TestCase):
    def test_complete_exact_control_and_lock_flow_requires_compiler_proof(self):
        authority=m.p.Authority();obs=observed(fleet_evidence(authority),authority);FixtureCompiler.calls=0
        with patch.object(m,'QualifiedCompiler',FixtureCompiler):result=m.fleet_row(REPO,authority,obs,Path('/not-an-operator-root'))
        self.assertEqual(result['classification'],'MATCH',result);self.assertEqual(result['lock_currency'],'CURRENT')
        self.assertEqual(FixtureCompiler.calls,1);self.assertFalse(result['operator_full_visibility_attested']);obs.check_used()

    def test_missing_qualified_compiler_is_unknown_after_metadata_not_current(self):
        authority=m.p.Authority();obs=observed(fleet_evidence(authority),authority)
        with tempfile.TemporaryDirectory() as raw:result=m.fleet_row(REPO,authority,obs,Path(raw).resolve())
        self.assertEqual(result['classification'],'UNAVAILABLE');self.assertEqual(result['control_parity'],'MATCH')
        self.assertEqual(result['policy_digest_parity'],'MATCH');self.assertEqual(result['lock_currency'],'UNAVAILABLE')

    def test_wrong_policy_lock_epoch_and_direct_bindings_are_known_drift(self):
        changes=[lambda p,l,r:p.update(controller_release_digest='sha256:'+'0'*64),
                 lambda p,l,r:l['payload'].update(lock_contract_version=9),
                 lambda p,l,r:l['payload'].update(controller_release=HEX),
                 lambda p,l,r:l['payload'].update(profile_digest=HEX),
                 lambda p,l,r:l['payload'].update(image_digest='wrong@'+HEX),
                 lambda p,l,r:l['payload'].update(recipe_blob_sha='0'*40)]
        for change in changes:
            with self.subTest(change=change):
                authority=m.p.Authority();obs=observed(fleet_evidence(authority,mutation=change),authority)
                with patch.object(m,'QualifiedCompiler',side_effect=AssertionError('compiler called before known mismatch')):
                    result=m.fleet_row(REPO,authority,obs,Path('/not-read'))
                self.assertEqual(result['classification'],'DRIFT',result)

    def test_duplicate_managed_rulesets_and_visible_fingerprint_drift(self):
        for mode in ('duplicate','fingerprint'):
            authority=m.p.Authority();value=fleet_evidence(authority)
            if mode=='duplicate':
                item=next(r for r in value['requests'] if '/rulesets?' in r['url']);item['data'].append({**item['data'][0],'id':1})
            else:
                item=next(r for r in value['requests'] if '/rulesets/' in r['url']);item['data']['bypass_actors']=[]
            result=m.fleet_row(REPO,authority,observed(value,authority),Path('/not-read'))
            self.assertEqual(result['classification'],'DRIFT',result)

    def test_missing_and_bad_hash_remote_objects_remain_unknown(self):
        for mode in ('missing','bad-blob','bad-history-commit'):
            authority=m.p.Authority();value=fleet_evidence(authority)
            if mode=='missing':value['requests']=[r for r in value['requests'] if '/git/blobs/' not in r['url']]
            elif mode=='bad-blob':next(r for r in value['requests'] if '/git/blobs/' in r['url'])['data']+='changed'
            else:next(r for r in value['requests'] if '/git/commits/' in r['url'])['data']['sha']='0'*40
            result=m.fleet_row(REPO,authority,observed(value,authority),Path('/not-read'))
            self.assertEqual(result['classification'],'UNAVAILABLE',result)

    def test_unenrolled_is_not_applicable_without_remote_request(self):
        authority=m.p.Authority();repo='KleinPerkins/sterling.io';obs=observed(None,authority,[repo])
        result=m.fleet_row(repo,authority,obs,Path('/not-read'))
        self.assertEqual(result['classification'],'NOT_APPLICABLE');self.assertTrue(result['available']);self.assertEqual(obs.missing,{})


class QualifiedProcess(unittest.TestCase):
    def compiler(self,home,script):
        authority=m.p.Authority();controller=copy.deepcopy(authority.controller);raw=script.encode()
        controller['release']['lock_compiler_digest']='sha256:'+m.g.sha(raw)
        target=home/m.COMPILER_PREFIX/m.g.sha(raw)/'lock-compiler';target.parent.mkdir(parents=True);target.write_bytes(raw);target.chmod(0o500)
        return m.QualifiedCompiler(home,controller),authority,target

    def inputs(self,authority):
        value=fleet_evidence(authority)
        blobs={r['url'].split('/')[-1]:r['data'].encode() for r in value['requests'] if '/git/blobs/' in r['url']}
        lock=next(raw for raw in blobs.values() if b'"schema_version"' in raw)
        recipe=next(raw for raw in blobs.values() if b'"fixture"' in raw)
        return authority.projection(REPO).assignment,recipe,lock

    def test_exact_private_argv_inputs_clean_environment_and_source_preservation(self):
        script='#!/bin/sh\n[ -z "$OPENAI_API_KEY" ] || exit 9\n[ "$1" = validate ] || exit 10\nprintf FIXTURE_VALID\n'
        with tempfile.TemporaryDirectory() as raw:
            home=Path(raw).resolve();compiler,a,path=self.compiler(home,script);assignment,recipe,lock=self.inputs(a)
            before={**m.w.fact(path.lstat()),'sha':m.g.sha(path.read_bytes())}
            with patch.dict(os.environ,{'OPENAI_API_KEY':'SYNTHETIC_NEVER_FORWARD'}):proof=compiler.validate(REPO,assignment,recipe,lock)
            self.assertTrue(proof['validated']);self.assertEqual(proof['validator_stdout_sha256'],m.g.sha(b'FIXTURE_VALID'))
            self.assertEqual({**m.w.fact(path.lstat()),'sha':m.g.sha(path.read_bytes())},before)

    def test_rejected_validator_is_known_error_but_process_failure_is_unavailable(self):
        with tempfile.TemporaryDirectory() as raw:
            compiler,a,path=self.compiler(Path(raw).resolve(),'#!/bin/sh\nexit 8\n');assignment,recipe,lock=self.inputs(a)
            with self.assertRaises(m.owner.ControlPlaneError):compiler.validate(REPO,assignment,recipe,lock)
            with patch.object(m.g,'bounded_process',side_effect=m.g.Refusal('process-timeout')),self.assertRaises(m.Unavailable):compiler.validate(REPO,assignment,recipe,lock)

    def test_binary_reader_does_not_weaken_the_shared_control_file_limit(self):
        with tempfile.TemporaryDirectory() as raw:
            limit=m.s.MAX_FILE_BYTES
            script='#!/bin/sh\n'+('# qualified fixture padding\n'*50000)+'exit 0\n'
            compiler,a,path=self.compiler(Path(raw).resolve(),script)
            self.assertGreater(len(compiler.raw),limit);self.assertEqual(compiler.raw,path.read_bytes())
            self.assertEqual(m.s.MAX_FILE_BYTES,limit)

    def test_wrong_digest_alias_shared_write_mode_and_source_change_are_held(self):
        for mode in ('digest','alias','shared','mode','changed'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as raw:
                home=Path(raw).resolve();compiler,a,path=self.compiler(home,'#!/bin/sh\nexit 0\n')
                if mode=='alias':path.unlink();path.symlink_to('/not-read')
                if mode=='shared':os.link(path,path.parent/'foreign')
                if mode=='mode':path.chmod(0o700)
                if mode in ('digest','changed'):path.chmod(0o700);path.write_bytes(b'changed');path.chmod(0o500)
                with self.assertRaises(m.Unavailable):compiler.check()

    def test_owner_closure_has_bound_globals_and_only_private_validation_writes(self):
        path=Path(m.owner.__file__);missing=set()
        def walk(table):
            for item in table.get_symbols():
                if item.is_global() and item.is_referenced() and item.get_name() not in vars(m.owner) and not hasattr(builtins,item.get_name()):missing.add(item.get_name())
            for child in table.get_children():walk(child)
        walk(symtable.symtable(path.read_text(),str(path),'exec'));self.assertEqual(missing,set())
        forbidden={'unlink','rename','symlink_to','link_to','mkdir','chmod','Popen','run','system'}
        tree=ast.parse(path.read_text())
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden])
        writes=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='write_bytes']
        self.assertEqual(len(writes),2)


if __name__=='__main__':unittest.main()
