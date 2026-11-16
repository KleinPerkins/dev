"""Owner parity, scoped connector protocol and real no-follow Git fixtures."""
import ast
from contextlib import redirect_stdout
import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_profile as m
from test_personal_git import fixture,GIT
from test_personal_baseline import complete

REPO='KleinPerkins/skills'
NOW=dt.datetime.now(dt.timezone.utc)
DATA=Path(__file__).parents[1]/'baseline/profiles/pr-automation/v3'
ORIGINAL=DATA/'profile.py'
BEGIN=m.BEGIN.encode();END=m.END.encode()
OWNERS=BEGIN+b'\n/.github/ @KleinPerkins\n/CODEOWNERS @KleinPerkins\n/_ops/ @KleinPerkins\n'+END+b'\n'


def policy(authority,repo=REPO):
    projection=authority.projection(repo)
    return {'version':'pr-automation/v3','repository_id':m.REPOSITORY_IDS[repo],
            'owner':'KleinPerkins','name':repo.split('/')[1],'default_branch':'main','activation_generation':3,
            'check_name':'pr-automation / verify','verifier_app_id':4274739,'verifier_integration_id':4274739,
            'reviewer_app_id':4269364,'reviewer_integration_id':4269364,
            'protected_paths':['.github','CODEOWNERS','_ops'],
            'ruleset_fingerprints':projection.runtime_app_visible_fingerprints,
            'max_changed_files':200,'max_total_patch_bytes':5_000_000,
            'controller_release_digest':m.p.RELEASE_DIGEST}


def manifest():
    return {'version':'pr-automation-verification/v1','secondary_sources':[],
            'jobs':[{'id':'verify-repository-contract','image':m.p.EXECUTION_IMAGE_REF,
                     'argv':['repository-contract'],'environment':{'CI':'true'},'network':'none',
                     'discovery':{'kind':'literal_stdout','literal':'PR_AUTOMATION_VERIFY_OK'},
                     'limits':{'timeout_seconds':120,'cpus_millis':500,'memory_mib':512,'pids':64,
                               'disk_mib':128,'inodes':4096,'output_bytes':32768}}]}


def git_tree(entries):
    entries=copy.deepcopy(entries)
    ordered=sorted(entries,key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode())
    raw=b''.join(e['mode'].lstrip('0').encode()+b' '+e['path'].encode()+b'\0'+bytes.fromhex(e['sha']) for e in ordered)
    return {'sha':hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),'truncated':False,'tree':entries}


def policy_chain(value,*,mode='100644',absent=False):
    raw=json.dumps(value).encode();sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    github=git_tree([] if absent else [{'path':'pr-automation.json','type':'commit' if mode=='160000' else 'blob','mode':mode,'sha':sha,'size':len(raw)}])
    root=git_tree([{'path':'.github','type':'tree','mode':'040000','sha':github['sha']}])
    branch={'name':'main','commit':{'sha':'f'*40,'commit':{'tree':{'sha':root['sha']}}}}
    return branch,root,github,sha,raw.decode()


def replace_policy(source,value,*,mode='100644',absent=False):
    branch,root,github,sha,text=policy_chain(value,mode=mode,absent=absent)
    base=source['requests'][0]['url']
    source['requests']=[r for r in source['requests'] if '/git/' not in r['url'] and not r['url'].endswith('/branches/main')]
    source['requests']+=[{'url':base+'/branches/main','outcome':'ok','data':branch},
                        {'url':base+'/git/trees/'+root['sha'],'outcome':'ok','data':root},
                        {'url':base+'/git/trees/'+github['sha'],'outcome':'ok','data':github}]
    if not absent:source['requests'].append({'url':base+'/git/blobs/'+sha,'outcome':'ok','data':text})


def raw_responses(authority,*,repo=REPO,review=True,history=True):
    urls=m.urls(repo,authority);projected=authority.projection(repo)
    ruleset=copy.deepcopy(projected.ruleset)
    ruleset.update(id=authority.targets[repo]['merge_safety_ruleset_id'],source_type='Repository',source=repo)
    values={'metadata':{'id':m.REPOSITORY_IDS[repo],'full_name':repo,'default_branch':'main'},'merge_safety':ruleset}
    if review:values['review']=[]
    if history:values['history']=[{'id':99,'name':'kleinperkins-dev-baseline','enforcement':'active'}]
    result={'schema':'personal-profile-responses/v1','observed_at':NOW.isoformat(),
            'requests':[{'url':urls[k],'outcome':'ok','data':v} for k,v in values.items()]}
    replace_policy(result,policy(authority,repo))
    return result


def baseline(eligible=False,compliant=False):
    return {'baseline_eligibility':{'classification':'ELIGIBLE' if eligible else 'EXCLUDED'},
            'baseline_compliance':'COMPLIANT' if compliant else 'MISSING' if eligible else None}


def observe(scope,tool,authority,responses=None):
    return m.inspect(scope,tool,authority,m.Responses(responses,scope.repositories,authority,now=NOW))


def controls(root,authority):
    (root/'.github').mkdir(exist_ok=True)
    (root/m.POLICY).write_text(json.dumps(policy(authority)))
    (root/m.MANIFEST).write_text(json.dumps(manifest()))
    (root/m.CODEOWNERS).write_bytes(OWNERS)


# The reviewed successor container refuses retired mutation dispatch; its qualified
# read-only definitions retain exact AST parity with the historical owner projection.
CURRENT_OWNER_PROFILE_BLOB='c2096764f44ad65a5a7f891d777584c45855b42a'

def owner_oracle():
    raw=ORIGINAL.read_bytes()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==CURRENT_OWNER_PROFILE_BLOB
    source=ast.parse(raw)
    defs={n.name:n for n in ast.parse((Path(__file__).parent/'personal_profile_contract.py').read_bytes()).body
          if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    constants={'CHECK','NODE_CHECK_PREFIX','MAX_NODE_CHECK_NAME_BYTES','MAX_NODE_JOB_ID_BYTES','MAX_DEFAULT_BRANCH_BYTES',
               'RELEASE_DIGEST','EXECUTION_IMAGE','EXECUTION_DIGEST','EXECUTION_IMAGE_REF','MEMORY_MIB',
               'PROTECTED_PATHS','HARD_EXCLUSION','COVERAGE_MODES'}
    nodes=[]
    for node in source.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in defs:nodes.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in node.targets):nodes.append(node)
    namespace={'Any':object,'NamedTuple':m.p.NamedTuple,'copy':copy,'hashlib':hashlib,'json':json,'re':m.re,'HERE':DATA}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ORIGINAL)+' [pure oracle only]','exec'),namespace)
    return namespace,defs,source


class OwnerAuthority(unittest.TestCase):
    def test_owner_oracle_rejects_container_drift_before_execution(self):
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'profile.py';path.write_bytes(ORIGINAL.read_bytes()+b'\n# inert owner drift fixture\n')
            with patch(__name__+'.ORIGINAL',path),patch('builtins.exec',side_effect=AssertionError('oracle executed')):
                with self.assertRaises(AssertionError) as error:owner_oracle()
            self.assertNotEqual(str(error.exception),'oracle executed')

    def test_immutable_source_data_and_all_selected_projection_pairs_match_exact_owner(self):
        authority=m.Authority();oracle,_,_=owner_oracle();count=0
        for repo in m.REPOSITORY_IDS:
            if repo not in authority.targets:continue
            args={'repository_id':m.REPOSITORY_IDS[repo],'repo':repo,'default_branch':'main'}
            expected=oracle['resolve_repository_projection'](authority.assignments,authority.fleet,authority.controller,**args)
            actual=authority.projection(repo)
            self.assertEqual(actual._asdict(),expected._asdict());count+=1
            value=policy(authority,repo)
            oracle['validate_policy'](value,m.POLICY,assignments=authority.assignments,fleet=authority.fleet,controller=authority.controller)
            authority.policy(repo,value)
        self.assertEqual(count,10)

    def test_only_three_reviewed_io_adapters_differ_from_exact_current_owner_definitions(self):
        _,defs,source=owner_oracle();original={n.name:n for n in source.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        changed={'_render_base_ruleset','resolve_repository_projection','validate_policy'}
        for name,node in defs.items():
            with self.subTest(name=name):
                if name in changed:self.assertNotEqual(ast.dump(node),ast.dump(original[name]))
                else:self.assertEqual(ast.dump(node),ast.dump(original[name]))
        parsed=ast.parse((Path(__file__).parent/'personal_profile_contract.py').read_bytes())
        for node in ast.walk(parsed):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):self.assertNotIn(node.func.id,{'open','exec','eval','load_json','__import__'})
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,{'read_text','read_bytes','write_text','write_bytes','run','Popen'})

    def test_render_inputs_and_manifest_failures_preserve_owner_outcomes(self):
        authority=m.Authority();oracle,_,_=owner_oracle()
        for branch in ('main','release-2','wrong/branch','',True,'x'*101):
            for engine in (oracle['validate_default_branch'],m.p.validate_default_branch):
                if isinstance(branch,str) and 0<len(branch)<=100 and '/' not in branch:engine(branch)
                else:
                    with self.assertRaises(m.p.ControlPlaneError if engine is m.p.validate_default_branch else oracle['ControlPlaneError']):engine(branch)
        for value in (manifest(),{**manifest(),'secondary_sources':['other']},{**manifest(),'jobs':[]},{**manifest(),'extra':1}):
            results=[]
            for engine in (oracle['validate_manifest'],m.p.validate_manifest):
                try:engine(value,m.MANIFEST);results.append('pass')
                except SystemExit:results.append('fail')
            self.assertEqual(results[0],results[1])
        for source in (authority.template.replace('{{DEFAULT_BRANCH}}','main'),authority.template+'{{DEFAULT_BRANCH}}'):
            with self.assertRaises(m.p.ControlPlaneError):m.p._render_base_ruleset('main',source)

    def test_data_change_or_alias_refuses_before_destination_or_connector_queries(self):
        authority=m.Authority()
        with patch.object(m,'DATA_HASHES',{**m.DATA_HASHES,'fleet.json':'0'*64}),self.assertRaisesRegex(m.g.Refusal,'authority-drift'):m.Authority()
        with patch.object(m.s,'selected_ids',side_effect=m.g.Refusal('scope-held')):
            with self.assertRaises(m.g.Refusal):authority.projection('Other/repository')

    def test_qualified_source_identity_and_generation_fail_closed(self):
        authority=m.Authority()
        for field,value in [('repository_id',True),('repository_id',1),('owner','Other'),('name','awa'),('default_branch','other'),('activation_generation',True),('activation_generation',0)]:
            changed=policy(authority);changed[field]=value
            with self.subTest(field=field,value=value),self.assertRaises((m.g.Refusal,SystemExit)):authority.policy(REPO,changed)


class ReceiptProtocol(unittest.TestCase):
    def setUp(self):self.authority=m.Authority()

    def test_only_metadata_is_requested_before_exact_live_identity(self):
        responses=m.Responses(None,[REPO],self.authority)
        result=m.remote_contract(REPO,True,baseline(True,True),self.authority,responses)
        self.assertEqual([r['url'] for r in responses.missing.values()],[m.urls(REPO,self.authority)['metadata']])
        self.assertEqual(result['review'],'UNKNOWN')

    def test_metadata_unlocks_only_applicable_exact_requests(self):
        source=raw_responses(self.authority);source['requests']=source['requests'][:1]
        for eligible,compliant,count in [(False,False,2),(True,False,3),(True,True,4)]:
            responses=m.Responses(source,[REPO],self.authority,now=NOW)
            m.remote_contract(REPO,True,baseline(eligible,compliant),self.authority,responses)
            self.assertEqual(len(responses.missing),count)
            self.assertTrue(all(r['method']=='GET' and r['url'] in responses.allowed for r in responses.missing.values()))

    def test_wrong_id_name_or_branch_never_unlocks_dependent_requests(self):
        for field,values in {'id':[True,0,-1,'1275604090',1],'full_name':['Other/skills','KleinPerkins/awa'],
                             'default_branch':[None,'other','main/x']}.items():
            for value in values:
                source=raw_responses(self.authority);source['requests']=source['requests'][:1];source['requests'][0]['data'][field]=value
                responses=m.Responses(source,[REPO],self.authority,now=NOW)
                with self.subTest(field=field,value=value):
                    result=m.remote_contract(REPO,True,baseline(True,True),self.authority,responses)
                    self.assertEqual(responses.missing,{});self.assertEqual(result['admin_bypass'],'UNKNOWN')

    def test_no_profile_and_excluded_baseline_make_no_remote_request(self):
        responses=m.Responses(None,[REPO],self.authority)
        result=m.remote_contract(REPO,False,baseline(),self.authority,responses)
        self.assertEqual(responses.missing,{})
        self.assertTrue(all(v=='NOT_APPLICABLE' for k,v in result.items() if k!='operator_full_attestation'))

    def test_unknown_scope_extra_keys_duplicate_or_non_get_targets_are_refused(self):
        for mode in ('foreign','duplicate','extra','non-get','other-selected','error-body','bad-outcome','count'):
            source=raw_responses(self.authority)
            if mode=='foreign':source['requests'][0]['url']='https://api.github.com/repos/Affirm/example'
            if mode=='duplicate':source['requests'].append(source['requests'][0])
            if mode=='extra':source['token']='SYNTHETIC_NEVER_USE'
            if mode=='non-get':source['requests'][0]['method']='POST'
            if mode=='other-selected':source['requests'][0]['url']='https://api.github.com/repos/KleinPerkins/awa'
            if mode=='error-body':source['requests'][0].update(outcome='forbidden')
            if mode=='bad-outcome':source['requests'][0].update(outcome='accepted')
            if mode=='count':source['requests']*=20
            with self.subTest(mode=mode),self.assertRaises(m.g.Refusal):m.Responses(source,[REPO],self.authority,now=NOW)

    def test_timestamp_requires_fresh_utc_with_no_operator_clock_override(self):
        for timestamp in (None,'bad',NOW.replace(tzinfo=None).isoformat(),(NOW-dt.timedelta(seconds=301)).isoformat(),
                          (NOW+dt.timedelta(seconds=31)).isoformat(),NOW.astimezone(dt.timezone(dt.timedelta(hours=1))).isoformat()):
            source=raw_responses(self.authority);source['observed_at']=timestamp
            with self.subTest(timestamp=timestamp),self.assertRaises(m.g.Refusal):m.Responses(source,[REPO],self.authority,now=NOW)

    def test_duplicate_keys_nonfinite_numbers_and_deep_json_are_refused(self):
        for raw in (b'{"a":1,"a":2}',b'{"n":NaN}',b'{"n":Infinity}',b'{"n":1e999999}',b'['*2000+b']'*2000):
            with self.subTest(raw=raw[:30]),self.assertRaises(m.g.Refusal):m.strict_json(raw)

    def test_json_depth_and_node_bounds_hold_on_both_parser_implementations(self):
        self.assertEqual(m.strict_json(b'['*64+b'0'+b']'*64),self.nested(64))
        for raw in (b'['*65+b'0'+b']'*65,b'['+b','.join([b'0']*50000)+b']'):
            with self.assertRaises(m.g.Refusal):m.strict_json(raw)

    @staticmethod
    def nested(count):
        result=0
        for _ in range(count):result=[result]
        return result

    def test_git_path_proof_and_blob_bytes_must_match_before_deployed_policy_is_observed(self):
        value=raw_responses(self.authority);responses=m.Responses(value,[REPO],self.authority,now=NOW)
        state,actual,head=m.deployed_policy(REPO,self.authority,responses)
        self.assertEqual(state,'OBSERVED');self.assertEqual(actual,policy(self.authority));self.assertEqual(head,'f'*40)
        for mode in ('120000','160000'):
            changed=raw_responses(self.authority);replace_policy(changed,policy(self.authority),mode=mode)
            response=m.Responses(changed,[REPO],self.authority,now=NOW)
            with self.subTest(mode=mode):self.assertEqual(m.deployed_policy(REPO,self.authority,response)[0],'UNKNOWN')
        for kind in ('bytes','sha','size','truncated','duplicate','wrong-branch'):
            changed=raw_responses(self.authority)
            if kind=='bytes':next(r for r in changed['requests'] if '/git/blobs/' in r['url'])['data']+=' '
            if kind in ('sha','size','truncated','duplicate'):
                tree=next(r['data'] for r in changed['requests'] if '/git/trees/' in r['url'])
                if kind=='sha':tree['sha']='0'*40
                if kind=='size':tree['tree'][0]['sha']='0'*40
                if kind=='truncated':tree['truncated']=True
                if kind=='duplicate':tree['tree']*=2
            if kind=='wrong-branch':next(r for r in changed['requests'] if r['url'].endswith('/branches/main'))['data']['name']='other'
            response=m.Responses(changed,[REPO],self.authority,now=NOW)
            with self.subTest(kind=kind):self.assertEqual(m.deployed_policy(REPO,self.authority,response)[0],'UNKNOWN')

    def test_unproven_git_object_response_is_held_without_a_request_or_content_use(self):
        source=raw_responses(self.authority)
        source['requests'].append({'url':'https://api.github.com/repos/'+REPO+'/git/blobs/'+'1'*40,'outcome':'ok','data':'unrelated synthetic bytes'})
        response=m.Responses(source,[REPO],self.authority,now=NOW)
        m.remote_contract(REPO,True,baseline(),self.authority,response)
        with self.assertRaisesRegex(m.g.Refusal,'unproven-profile'):response.check_used()

    def test_tree_object_hash_matches_git_in_disposable_fixture_with_git_sorting_and_modes(self):
        entries=[{'path':'z','type':'blob','mode':'120000','sha':'a'*40},
                 {'path':'dir','type':'tree','mode':'040000','sha':'b'*40},
                 {'path':'dir.txt','type':'blob','mode':'100644','sha':'c'*40},
                 {'path':'executable','type':'blob','mode':'100755','sha':'d'*40}]
        tree=git_tree(entries)
        with fixture() as (root,scope,tool,git):
            text=''.join(e['mode']+' '+e['type']+' '+e['sha']+'\t'+e['path']+'\n' for e in entries)
            result=subprocess.run([str(GIT),'mktree','--missing'],input=text.encode(),cwd=root,
                                  env=m.g.clean_environment(),capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip().decode(),tree['sha'])
        self.assertEqual(m.tree_entry(tree,tree['sha'],'dir')['mode'],'040000')

    def test_blob_size_metadata_cannot_override_the_object_bytes(self):
        for size in (True,-1,1,m.s.MAX_FILE_BYTES+1):
            source=raw_responses(self.authority)
            github=next(r['data'] for r in source['requests'] if '/git/trees/' in r['url'] and any(e['path']=='pr-automation.json' for e in r['data']['tree']))
            github['tree'][0]['size']=size
            responses=m.Responses(source,[REPO],self.authority,now=NOW)
            with self.subTest(size=size):self.assertEqual(m.deployed_policy(REPO,self.authority,responses)[0],'UNKNOWN')


class RemoteSemantics(unittest.TestCase):
    def setUp(self):self.authority=m.Authority()
    def remote(self,source=None,*,eligible=False,compliant=False):
        response=m.Responses(raw_responses(self.authority) if source is None else source,[REPO],self.authority,now=NOW)
        return m.remote_contract(REPO,True,baseline(eligible,compliant),self.authority,response)

    def test_all_current_v3_remote_contracts_pass_without_operator_full_attestation(self):
        result=self.remote(eligible=True,compliant=True)
        for key in ('review','admin_bypass','deployed_fingerprint','live_app_fingerprint'):self.assertEqual(result[key],'CLEAN')
        self.assertEqual(result['history'],'ENFORCED');self.assertEqual(result['deployed_policy_contract'],'COMPLIANT')
        self.assertFalse(result['operator_full_attestation'])

    def test_complete_proof_is_bound_independently_for_each_selected_enrolled_repository(self):
        count=0
        for repo in m.REPOSITORY_IDS:
            if repo not in self.authority.targets:continue
            response=m.Responses(raw_responses(self.authority,repo=repo),[repo],self.authority,now=NOW)
            result=m.remote_contract(repo,True,baseline(),self.authority,response);response.check_used()
            with self.subTest(repo=repo):
                self.assertEqual(result['admin_bypass'],'CLEAN');self.assertEqual(result['deployed_fingerprint'],'CLEAN')
                self.assertEqual(result['deployed_policy_contract'],'COMPLIANT')
            count+=1
        self.assertEqual(count,10)

    def test_review_tripwire_retains_numeric_positive_semantics_and_holds_malformed_input(self):
        for count,expected in [(0,'CLEAN'),(1,'REVIEW_DRIFT'),(2.5,'REVIEW_DRIFT'),(10**500,'REVIEW_DRIFT'),
                               (None,'CLEAN'),(True,'UNKNOWN'),('1','UNKNOWN'),(float('inf'),'UNKNOWN')]:
            with self.subTest(count=str(count)[:30]):self.assertEqual(m.review_policy([{'type':'pull_request','parameters':{'required_approving_review_count':count}}]),expected)
        for value in ({},[None],[{'type':'pull_request','parameters':[]}],[{'type':'deletion'}]*100):self.assertEqual(m.review_policy(value),'UNKNOWN')

    def test_history_distinguishes_active_required_and_partial_or_ambiguous_unknown(self):
        self.assertEqual(m.history_policy([]),'REQUIRED')
        row={'id':123,'name':'kleinperkins-dev-baseline','enforcement':'active'}
        self.assertEqual(m.history_policy([row]),'ENFORCED')
        self.assertEqual(m.history_policy([{**row,'enforcement':'disabled'}]),'REQUIRED')
        for value in ([row,row],[{**row,'id':True}],[None],[row]*100,{}):self.assertEqual(m.history_policy(value),'UNKNOWN')

    def test_every_enrolled_ruleset_identity_field_precedes_bypass_and_fingerprint(self):
        for field in ('id','name','target','enforcement','source_type','source'):
            source=raw_responses(self.authority);source['requests'][1]['data'][field]=None
            with self.subTest(field=field):
                result=self.remote(source);self.assertEqual(result['admin_bypass'],'UNKNOWN');self.assertEqual(result['live_app_fingerprint'],'UNKNOWN')

    def test_hidden_missing_malformed_or_wrong_actor_is_unknown_never_false_negative(self):
        for actors in (None,[],{},[{'actor_id':True,'actor_type':'RepositoryRole'}],
                       [{'actor_id':'5','actor_type':'RepositoryRole'}],[{'actor_id':5,'actor_type':'Integration'}]):
            source=raw_responses(self.authority);source['requests'][1]['data']['bypass_actors']=actors
            with self.subTest(actors=actors):self.assertEqual(self.remote(source)['admin_bypass'],'UNKNOWN')

    def test_fingerprint_drift_is_reported_but_malformed_rules_stay_unknown(self):
        source=raw_responses(self.authority);source['requests'][1]['data']['rules'].append({'type':'deletion'})
        self.assertEqual(self.remote(source)['live_app_fingerprint'],'DRIFT')
        for rules in (None,'bad',[None],[{'type':'pull_request','parameters':[]}],
                      [{'type':'required_status_checks','parameters':{'required_status_checks':1}}]):
            source=raw_responses(self.authority);source['requests'][1]['data']['rules']=rules
            with self.subTest(rules=rules):self.assertEqual(self.remote(source)['live_app_fingerprint'],'UNKNOWN')

    def test_wrong_policy_identity_is_unknown_and_identity_bound_wrong_fingerprint_is_stale(self):
        for field,value in [('repository_id',True),('repository_id',1),('owner','Other'),('name','awa'),('default_branch','other')]:
            source=raw_responses(self.authority);value_policy=policy(self.authority);value_policy[field]=value
            replace_policy(source,value_policy)
            with self.subTest(field=field):self.assertEqual(self.remote(source)['deployed_fingerprint'],'UNKNOWN')
        source=raw_responses(self.authority);value=policy(self.authority);value['ruleset_fingerprints']=[]
        replace_policy(source,value)
        self.assertEqual(self.remote(source)['deployed_fingerprint'],'STALE_FINGERPRINT')

    def test_known_absence_differs_from_forbidden_timeout_and_unavailable(self):
        source=raw_responses(self.authority);replace_policy(source,policy(self.authority),absent=True)
        self.assertEqual(self.remote(source)['deployed_fingerprint'],'NOT_STAGED')
        for outcome in ('not-found','forbidden','plan-limit','timeout','unavailable'):
            source=raw_responses(self.authority)
            next(r for r in source['requests'] if r['url'].endswith('/branches/main')).update(outcome=outcome,data=None)
            with self.subTest(outcome=outcome):self.assertEqual(self.remote(source)['deployed_fingerprint'],'UNKNOWN')

    def test_unavailable_never_becomes_ok_and_defined_drift_preserves_severity(self):
        local={'status':'COMPLIANT'};remote=self.remote(eligible=True,compliant=True)
        self.assertEqual(m.outcomes(local,remote),(True,'OK'))
        for key,value,available,verdict in [('review','UNKNOWN',False,'ADVISORY'),('history','UNENFORCED_PLAN_LIMIT',False,'ADVISORY'),
                                          ('history','REQUIRED',True,'ADVISORY'),('review','REVIEW_DRIFT',True,'DRIFT'),
                                          ('deployed_fingerprint','STALE_FINGERPRINT',True,'DRIFT'),('live_app_fingerprint','DRIFT',True,'DRIFT')]:
            changed={**remote,key:value}
            with self.subTest(key=key,value=value):self.assertEqual(m.outcomes(local,changed),(available,verdict))


class LocalAndCaller(unittest.TestCase):
    def setUp(self):self.authority=m.Authority()

    def test_real_eligible_and_detached_profiles_preserve_applicability_and_source_indexes(self):
        with fixture() as (root,scope,tool,git):
            complete(root);controls(root,self.authority);git('add','-A');git('commit','-m','synthetic v3 contracts')
            index=root/'.git/index';before=(index.read_bytes(),index.stat().st_ino,index.stat().st_mtime_ns,index.stat().st_ctime_ns)
            result=observe(scope,tool,self.authority,raw_responses(self.authority));row=result['rows'][0]
            self.assertTrue(row['available']);self.assertEqual(row['local']['status'],'COMPLIANT')
            self.assertEqual(row['baseline_eligibility']['classification'],'ELIGIBLE');self.assertEqual(row['remote']['history'],'ENFORCED')
            self.assertEqual(result['requests'],[])
            self.assertEqual((index.read_bytes(),index.stat().st_ino,index.stat().st_mtime_ns,index.stat().st_ctime_ns),before)
            git('checkout','--detach','HEAD')
            result=observe(scope,tool,self.authority,raw_responses(self.authority,review=False,history=False));row=result['rows'][0]
            self.assertTrue(row['available']);self.assertEqual(row['remote']['review'],'NOT_APPLICABLE')
            self.assertEqual(row['remote']['history'],'NOT_APPLICABLE');self.assertEqual(row['local']['status'],'COMPLIANT')

    def test_profile_runs_outside_dirty_and_non_main_baseline_exclusions(self):
        with fixture() as (root,scope,tool,git):
            controls(root,self.authority);git('add','-A');git('commit','-m','synthetic v3')
            git('checkout','-b','synthetic-feature');(root/'fixture.txt').write_text('dirty change\n')
            result=observe(scope,tool,self.authority,raw_responses(self.authority,review=False,history=False));row=result['rows'][0]
            self.assertTrue(row['available']);self.assertEqual(row['baseline_eligibility']['reason'],'dirty-working-tree')
            self.assertEqual(row['local']['status'],'COMPLIANT');self.assertEqual(row['remote']['admin_bypass'],'CLEAN')

    def test_no_profile_on_detached_primary_is_explicitly_inapplicable(self):
        with fixture() as (root,scope,tool,git):
            git('checkout','--detach','HEAD');result=observe(scope,tool,self.authority);row=result['rows'][0]
            self.assertTrue(row['available']);self.assertFalse(row['profile_present'])
            self.assertEqual(row['local']['status'],'NOT_APPLICABLE');self.assertEqual(result['requests'],[])

    def test_non_v3_profiles_are_unavailable_without_legacy_state_adoption_or_other_file_reads(self):
        with fixture() as (root,scope,tool,git):
            (root/'.github').mkdir();(root/m.POLICY).write_text('{"schema":"pr-automation/v1"}')
            git('add','-A');git('commit','-m','synthetic compatibility')
            git('checkout','--detach','HEAD');result=observe(scope,tool,self.authority,raw_responses(self.authority));row=result['rows'][0]
            self.assertFalse(row['available']);self.assertEqual(row['local']['status'],'UNAVAILABLE')
            self.assertFalse(row['legacy_state_or_status_adopted']);self.assertEqual(row['local']['controls_read'],1)
            self.assertEqual(row['legacy_doctor_compatibility_result'],'legacy compatibility not evaluated')

    def test_wrong_local_contract_missing_codeowners_or_legacy_workflow_is_noncompliant(self):
        for kind in ('manifest','owners','workflow','duplicate-block'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                controls(root,self.authority)
                if kind=='manifest':(root/m.MANIFEST).write_text('{"jobs":[]}')
                if kind=='owners':(root/m.CODEOWNERS).unlink()
                if kind=='duplicate-block':(root/m.CODEOWNERS).write_bytes(OWNERS+OWNERS)
                if kind=='workflow':
                    (root/'.github/workflows').mkdir();(root/'.github/workflows/odd.yextraml').write_text('# PR-AUTOMATION\n')
                git('add','-A');git('commit','-m','synthetic drift');git('checkout','--detach','HEAD')
                result=observe(scope,tool,self.authority,raw_responses(self.authority));row=result['rows'][0]
                self.assertTrue(row['available']);self.assertEqual(row['local']['status'],'NONCOMPLIANT')
                self.assertEqual(row['verdict'],'ADVISORY')

    def test_alias_fifo_shared_or_nested_controls_are_unavailable_before_body_reads(self):
        for kind in ('alias','fifo','shared','nested','workflow-alias'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                controls(root,self.authority);git('add','-A');git('commit','-m','synthetic safe preimage')
                path=root/m.MANIFEST
                if kind=='alias':path.unlink();path.symlink_to('/not-followed')
                if kind=='fifo':path.unlink();os.mkfifo(path,0o600)
                if kind=='shared':os.link(path,root/'shared-control')
                if kind=='nested':(root/'.github/.git').mkdir()
                if kind=='workflow-alias':(root/'.github/workflows').symlink_to('/not-followed',target_is_directory=True)
                git('checkout','--detach','HEAD')
                result=observe(scope,tool,self.authority)
                self.assertFalse(result['rows'][0]['available'])

    def test_late_control_changes_are_not_reported_as_compliant(self):
        with fixture() as (root,scope,tool,git):
            controls(root,self.authority);git('add','-A');git('commit','-m','synthetic safe');git('checkout','--detach','HEAD')
            original=m.ProfileReader.check;changed=False
            def late(reader):
                nonlocal changed
                if not changed:
                    changed=True;(root/m.CODEOWNERS).write_bytes(OWNERS+b'# visible later edit\n')
                return original(reader)
            with patch.object(m.ProfileReader,'check',late):result=observe(scope,tool,self.authority)
            self.assertFalse(result['rows'][0]['available']);self.assertIn('visible later edit',(root/m.CODEOWNERS).read_text())

    def test_bad_origin_stops_before_control_or_connector_probes(self):
        with fixture() as (root,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with (patch.object(m.ProfileReader,'read',side_effect=AssertionError('control opened')),
                  patch.object(m.Responses,'read',side_effect=AssertionError('connector requested'))):
                result=observe(scope,tool,self.authority)
            self.assertFalse(result['rows'][0]['available'])

    def test_cli_refuses_arbitrary_roots_writers_and_unselected_ids(self):
        for args in (['apply'],['inspect','--root','/not-opened'],['inspect','--repository','KleinPerkins/chaos-scheduler']):
            out=io.StringIO()
            with redirect_stdout(out):
                try:code=m.main(args)
                except SystemExit as error:code=error.code
            self.assertNotEqual(code,0)

    def test_cli_rejects_oversized_input_before_destination_git_or_control_probes(self):
        with fixture() as (root,scope,tool,git):
            class Input:
                buffer=io.BytesIO(b'x'*(m.MAX_RECEIPT_BYTES+1))
            out=io.StringIO()
            with (patch.object(m.sys,'stdin',Input()),patch.object(m.g,'GitTool',side_effect=AssertionError('destination Git tool')),
                  redirect_stdout(out)):
                result=m.main(['inspect','--repository',REPO,'--responses-stdin'])
            self.assertEqual(result,2);self.assertIn('profile-response-byte-bound',out.getvalue())


if __name__=='__main__':unittest.main()
