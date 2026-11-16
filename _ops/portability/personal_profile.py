"""Personal-only runnerless v3 local, delivery and live tripwire diagnostic.

inspect emits staged exact GET requests; a personal connector supplies responses
on stdin for another inspect. This process makes no network requests or source,
configuration, hook, ref, service or shared-discovery changes. Exit 0 is a bounded
diagnostic, never complete doctor/native or migration acceptance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote

HERE=Path(__file__).absolute().parent
DEPENDENCIES={'personal_baseline.py':'48a1e661077b889e9c0e959dfbad4466fd500f7aa546218e86bdcdda68ded4ce',
              'personal_profile_contract.py':'44b3643b30bbfcbae7b82b44dab8d955d14d8b4a5da7e73da781c98e934ea741'}
for name,digest in DEPENDENCIES.items():
    path=HERE/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('accepted personal profile dependency changed')
sys.path.insert(0,str(HERE))
import personal_baseline as b
import personal_profile_contract as p
if Path(b.__file__).absolute()!=HERE/'personal_baseline.py' or Path(p.__file__).absolute()!=HERE/'personal_profile_contract.py':
    raise ValueError('personal profile imported from another root')
c,g,w,s=b.c,b.g,b.w,b.s

OWNER_REF='9ac8369944f45b9e3f5e8d455ee03fad191cfd74'
OWNER_PROFILE_BLOB='35587bb4afc9b4c75b6bc1c5dbce6f172991363a'
DATA_HASHES={'fleet.json':'aca3829b13c4813c711eb4e51376f6c6d9ce5b5dec0db022cdc62a530f1c1802',
             'controller.json':'6e5826f661f027e4a70936344a369685a661796ef58c81a0683d33edf25720e3',
             'coverage-assignments.json':'ee8bcc8bc0a74a7a1ada33c07ae685128553970ceab82b5593319c8389bfce23',
             'merge-safety.ruleset.json.tmpl':'438b6a7bd24bb3738d35ce0903a9362cf976a8c0a3a48c9c0c2639c9e4162109'}
REPOSITORY_IDS={'KleinPerkins/skills':1275604090,'KleinPerkins/kp-mcp':1271164179,
                'KleinPerkins/awa':1289571438,'KleinPerkins/intent-router':1294651532,
                'KleinPerkins/operator-voice':1317232260,'KleinPerkins/sterling':1276598286,
                'KleinPerkins/sterling.io':1439196929,'KleinPerkins/local-jobs':1284625858,
                'KleinPerkins/pr-automation-controller':1297666445,'KleinPerkins/server-guard':1302096938,
                'KleinPerkins/doc-warden-canary':1324068071,'KleinPerkins/kp-pr-bot-canary':1297059298}
POLICY='.github/pr-automation.json'
MANIFEST='.github/pr-verification.json'
CODEOWNERS='.github/CODEOWNERS'
BEGIN='# BEGIN kleinperkins runnerless PR automation v3'
END='# END kleinperkins runnerless PR automation v3'
MAX_RECEIPT_BYTES=1024*1024
OUTCOMES={'ok','not-found','forbidden','plan-limit','timeout','unavailable'}


def strict_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise g.Refusal('duplicate-profile-json-key')
            result[key]=value
        return result
    def nonfinite(value):raise g.Refusal('nonfinite-profile-json-number')
    try:value=json.loads(raw,object_pairs_hook=unique,parse_constant=nonfinite)
    except RecursionError:raise g.Refusal('profile-json-depth-held') from None
    pending=[(value,0)];count=0
    while pending:
        item,depth=pending.pop();count+=1
        if depth>64 or count>50000:raise g.Refusal('profile-json-structure-bound')
        if isinstance(item,float) and not math.isfinite(item):raise g.Refusal('nonfinite-profile-json-number')
        if isinstance(item,dict):pending.extend((child,depth+1) for child in item.values())
        elif isinstance(item,list):pending.extend((child,depth+1) for child in item)
    return value


def positive(value):return type(value) is int and value>0


class Authority:
    def __init__(self):
        parent=s.absolute_directory(HERE.parent/'baseline/profiles/pr-automation/v3')
        try:self.raw={name:s.read_regular(parent,name) for name in DATA_HASHES}
        finally:os.close(parent)
        if any(g.sha(self.raw[name])!=digest for name,digest in DATA_HASHES.items()):
            raise g.Refusal('qualified-profile-authority-drift')
        self.fleet=strict_json(self.raw['fleet.json'])
        self.controller=strict_json(self.raw['controller.json'])
        self.assignments=strict_json(self.raw['coverage-assignments.json'])
        self.template=self.raw['merge-safety.ruleset.json.tmpl'].decode('utf-8')
        self.targets={t['repo']:t for t in p._validated_fleet_targets(self.fleet)}
        if set(REPOSITORY_IDS)!=set(s.PROJECTS):raise g.Refusal('profile-selection-authority-drift')
        if 'KleinPerkins/chaos-scheduler' not in self.controller.get('hard_exclusions',[]):
            raise g.Refusal('permanent-profile-exclusion-missing')
        for repo in s.PROJECTS:
            if repo in self.targets:
                t=self.targets[repo]
                if t['repository_id']!=REPOSITORY_IDS[repo] or t['default_branch']!='main':
                    raise g.Refusal('selected-profile-identity-authority-drift')
                self.projection(repo)

    def projection(self,repo):
        s.selected_ids([repo])
        target=self.targets.get(repo)
        if target is None:return None
        return p.resolve_repository_projection(self.assignments,self.fleet,self.controller,
                    repository_id=REPOSITORY_IDS[repo],repo=repo,default_branch='main',template_source=self.template)

    def policy(self,repo,value):
        if not policy_identity(repo,value):raise g.Refusal('profile-policy-identity-unavailable')
        if not positive(value.get('activation_generation')):raise g.Refusal('profile-generation-unavailable')
        p.validate_policy(value,POLICY,assignments=self.assignments,fleet=self.fleet,
                          controller=self.controller,template_source=self.template)

    def unchanged(self):
        if Authority().raw!=self.raw:raise g.Refusal('qualified-profile-authority-changed')


def urls(repo,authority):
    s.selected_ids([repo])
    prefix='https://api.github.com/repos/'+repo
    values={'metadata':prefix,'review':prefix+'/rules/branches/'+quote('main',safe='')+'?per_page=100&page=1',
            'history':prefix+'/rulesets?per_page=100&page=1','branch':prefix+'/branches/main'}
    target=authority.targets.get(repo)
    if target is not None and target['merge_safety_ruleset_id'] is not None:
        values['merge_safety']=prefix+'/rulesets/'+str(target['merge_safety_ruleset_id'])
    return values


class Responses:
    """Bounded untrusted connector observations; no credential/owner authority."""
    def __init__(self,value,selected,authority,*,now=None):
        self.selected=s.selected_ids(selected)
        self.allowed={url for repo in self.selected for url in urls(repo,authority).values()}
        self.entries={};self.missing={};self.dynamic=set();self.used=set()
        if value is None:return
        if not isinstance(value,dict) or set(value)!={'schema','observed_at','requests'} or value['schema']!='personal-profile-responses/v1':
            raise g.Refusal('profile-response-schema-held')
        try:
            timestamp=dt.datetime.fromisoformat(value['observed_at'])
            if timestamp.utcoffset()!=dt.timedelta(0):raise ValueError()
            age=((now or dt.datetime.now(dt.timezone.utc))-timestamp).total_seconds()
            if not  -30<=age<=300:raise ValueError()
        except (ValueError,TypeError,OverflowError):raise g.Refusal('profile-response-time-unavailable') from None
        entries=value['requests']
        if not isinstance(entries,list) or len(entries)>100:raise g.Refusal('profile-response-count-held')
        for entry in entries:
            if not isinstance(entry,dict) or set(entry)!={'url','outcome','data'}:raise g.Refusal('profile-response-entry-held')
            url=entry['url']
            dynamic=isinstance(url,str) and any(re.fullmatch(re.escape('https://api.github.com/repos/'+repo)+r'/git/(trees|blobs)/[0-9a-f]{40}',url) for repo in self.selected)
            if not isinstance(url,str) or (url not in self.allowed and not dynamic) or url in self.entries:
                raise g.Refusal('profile-response-target-or-duplicate-held')
            if not isinstance(entry['outcome'],str) or entry['outcome'] not in OUTCOMES:
                raise g.Refusal('profile-response-outcome-held')
            if entry['outcome']!='ok' and entry['data'] is not None:raise g.Refusal('profile-error-response-body-held')
            self.entries[url]=entry
            if dynamic:self.dynamic.add(url)

    def read(self,url,purpose):
        if url not in self.allowed:raise g.Refusal('unselected-profile-request-held')
        if url not in self.entries:
            self.missing[url]={'method':'GET','url':url,'purpose':purpose}
            return 'unavailable',None
        entry=self.entries[url]
        self.used.add(url)
        return entry['outcome'],entry['data']

    def git_object(self,repo,kind,sha,purpose):
        if repo not in self.selected or kind not in {'trees','blobs'} or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha):
            raise g.Refusal('profile-git-object-pointer-held')
        url='https://api.github.com/repos/'+repo+'/git/'+kind+'/'+sha
        self.allowed.add(url)
        return self.read(url,purpose)

    def check_used(self):
        if self.dynamic-self.used:raise g.Refusal('unproven-profile-git-object-response-held')


def metadata_identity(repo,value):
    return (isinstance(value,dict) and positive(value.get('id')) and value['id']==REPOSITORY_IDS[repo]
            and value.get('full_name')==repo and value.get('default_branch')=='main')


def policy_identity(repo,value):
    return (isinstance(value,dict) and positive(value.get('repository_id'))
            and value['repository_id']==REPOSITORY_IDS[repo] and value.get('owner')=='KleinPerkins'
            and value.get('name')==repo.split('/')[1] and value.get('default_branch')=='main')


def review_policy(value):
    if not isinstance(value,list) or len(value)>=100:return 'UNKNOWN'
    drift=False
    for rule in value:
        if not isinstance(rule,dict) or not isinstance(rule.get('type'),str):return 'UNKNOWN'
        if rule['type']!='pull_request':continue
        params=rule.get('parameters')
        if params is None:params={}
        if not isinstance(params,dict):return 'UNKNOWN'
        count=params.get('required_approving_review_count')
        if count is None:continue
        if isinstance(count,bool) or not isinstance(count,(int,float)) or (isinstance(count,float) and not math.isfinite(count)):return 'UNKNOWN'
        drift|=count>0
    return 'REVIEW_DRIFT' if drift else 'CLEAN'


def history_policy(value):
    if not isinstance(value,list) or len(value)>=100:return 'UNKNOWN'
    if any(not isinstance(row,dict) for row in value):return 'UNKNOWN'
    matches=[r for r in value if r.get('name')=='kleinperkins-dev-baseline']
    if len(matches)>1:return 'UNKNOWN'
    if not matches:return 'REQUIRED'
    if not positive(matches[0].get('id')) or not isinstance(matches[0].get('enforcement'),str):return 'UNKNOWN'
    return 'ENFORCED' if matches[0]['enforcement']=='active' else 'REQUIRED'


def ruleset_identity(repo,target,value):
    wanted={'id':target['merge_safety_ruleset_id'],'name':'kleinperkins-merge-safety',
            'target':'branch','enforcement':'active','source_type':'Repository','source':repo}
    return (isinstance(value,dict) and positive(value.get('id')) and all(value.get(k)==v for k,v in wanted.items()))


def admin_bypass(value):
    actors=value.get('bypass_actors')
    if not isinstance(actors,list):return 'UNKNOWN'
    if any(isinstance(a,dict) and a.get('actor_type')=='RepositoryRole'
           and type(a.get('actor_id')) is int and a['actor_id']==5 for a in actors):return 'CLEAN'
    return 'UNKNOWN'  # App redaction cannot prove an owner-visible negative.


def fingerprint_shape(value):
    rules=value.get('rules');conditions=value.get('conditions');actors=value.get('bypass_actors')
    if not isinstance(rules,list) or not isinstance(conditions,dict) or not isinstance(actors,list):return False
    if any(not isinstance(a,dict) for a in actors):return False
    refs=conditions.get('ref_name')
    if not isinstance(refs,dict):return False
    for key in ('include','exclude'):
        if not isinstance(refs.get(key),list) or any(not isinstance(v,str) for v in refs[key]):return False
    for rule in rules:
        if not isinstance(rule,dict) or not isinstance(rule.get('type'),str):return False
        params=rule.get('parameters')
        if params is not None and not isinstance(params,dict):return False
        if rule['type']=='required_status_checks':
            if not isinstance(params,dict) or not isinstance(params.get('required_status_checks'),list):return False
            if any(not isinstance(check,dict) for check in params['required_status_checks']):return False
    return True


def tree_entry(value,expected_sha,name):
    if (not isinstance(value,dict) or value.get('sha')!=expected_sha or value.get('truncated') is not False
            or not isinstance(value.get('tree'),list) or len(value['tree'])>1000):
        raise g.Refusal('deployed-profile-tree-response-held')
    seen=set();entries=[]
    kinds={'040000':'tree','100644':'blob','100755':'blob','120000':'blob','160000':'commit'}
    for entry in value['tree']:
        if not isinstance(entry,dict):raise g.Refusal('deployed-profile-tree-entry-held')
        path,mode,kind,sha=(entry.get(k) for k in ('path','mode','type','sha'))
        if (not isinstance(path,str) or not path or path in {'.','..'} or '/' in path or '\0' in path or path in seen
                or not isinstance(mode,str) or kinds.get(mode)!=kind
                or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha)):
            raise g.Refusal('deployed-profile-tree-entry-held')
        seen.add(path);entries.append(entry)
    try:
        entries.sort(key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode('utf-8'))
        raw=b''.join(e['mode'].lstrip('0').encode('ascii')+b' '+e['path'].encode('utf-8')+b'\0'+bytes.fromhex(e['sha']) for e in entries)
    except UnicodeError:raise g.Refusal('deployed-profile-tree-name-held') from None
    if hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=expected_sha:
        raise g.Refusal('deployed-profile-tree-object-hash-held')
    return next((entry for entry in entries if entry['path']==name),None)


def deployed_policy(repo,authority,responses):
    state,branch=responses.read(urls(repo,authority)['branch'],'exact qualified default-branch commit and root tree')
    if state!='ok':return 'UNKNOWN',None,None
    try:
        if not isinstance(branch,dict) or branch.get('name')!='main':raise ValueError()
        commit=branch['commit'];head=commit['sha'];root_sha=commit['commit']['tree']['sha']
        if not isinstance(head,str) or not re.fullmatch(r'[0-9a-f]{40}',head):raise ValueError()
        state,root=responses.git_object(repo,'trees',root_sha,'exact default-branch root tree; select only .github metadata')
        if state!='ok':return 'UNKNOWN',None,None
        github=tree_entry(root,root_sha,'.github')
        if github is None:return 'NOT_STAGED',None,head
        if github['type']!='tree' or github['mode']!='040000':raise ValueError()
        state,tree=responses.git_object(repo,'trees',github['sha'],'exact .github tree; select only pr-automation.json metadata')
        if state!='ok':return 'UNKNOWN',None,None
        leaf=tree_entry(tree,github['sha'],'pr-automation.json')
        if leaf is None:return 'NOT_STAGED',None,head
        if (leaf['type']!='blob' or leaf['mode'] not in {'100644','100755'}
                or type(leaf.get('size')) is not int or not 0<=leaf['size']<=s.MAX_FILE_BYTES):raise ValueError()
        state,text=responses.git_object(repo,'blobs',leaf['sha'],'exact regular pr-automation.json blob; UTF-8 bytes must reproduce its object hash')
        if state!='ok' or not isinstance(text,str):return 'UNKNOWN',None,None
        raw=text.encode('utf-8')
        if len(raw)!=leaf['size'] or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=leaf['sha']:
            raise g.Refusal('deployed-profile-blob-object-hash-held')
        return 'OBSERVED',strict_json(raw),head
    except (ValueError,TypeError,KeyError,UnicodeError):return 'UNKNOWN',None,None


class ProfileReader(c.Reader):
    def workflows(self):
        try:
            self.tree.classify_control_ancestors('.github/workflows/scoped-profile-probe')
            fd=s.child_directory(self.repo._fd,('.github','workflows'))
        except FileNotFoundError:return {'kind':'absent'},[]
        try:
            names=sorted(os.listdir(fd))
            if len(names)>100:raise g.Refusal('profile-workflow-entry-bound')
            return {'kind':'directory','facts':w.fact(os.fstat(fd)),'names_sha256':w.digest(names)},[
                name for name in names if fnmatch.fnmatchcase(name,'*.y*ml')]
        finally:os.close(fd)


def local_contract(reader,repo,authority,raw_policy):
    result={'status':'COMPLIANT','version':None,'issues':[],'controls_read':1,'workflows_checked':0}
    if raw_policy is None:return {**result,'status':'NOT_APPLICABLE'}
    deadline=time.monotonic()+12
    try:
        value=strict_json(raw_policy)
        if isinstance(value,dict):result['version']=value.get('version')
        if not isinstance(value,dict) or value.get('version')!='pr-automation/v3':
            return {**result,'status':'UNAVAILABLE','issues':['non-v3 profile requires its separate compatibility workflow']}
        authority.policy(repo,value)
    except (ValueError,TypeError,KeyError,SystemExit,p.ControlPlaneError):result['issues'].append('local v3 policy differs from qualified owner contract')
    manifest,_=reader.read(MANIFEST);result['controls_read']+=1
    try:
        value=strict_json(manifest)
        if not isinstance(value,dict):raise ValueError()
        p.validate_manifest(value,MANIFEST)
    except (ValueError,TypeError,KeyError,SystemExit,p.ControlPlaneError):result['issues'].append('local verification manifest differs from qualified closed contract')
    owners,_=reader.read(CODEOWNERS);result['controls_read']+=1
    try:
        text=owners.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        if text.count(BEGIN)!=1 or text.count(END)!=1:result['issues'].append('CODEOWNERS v3 block must occur exactly once')
        if any(v not in text for v in ('/.github/ @KleinPerkins','/CODEOWNERS @KleinPerkins','/_ops/ @KleinPerkins')):
            result['issues'].append('CODEOWNERS protected-path owner missing')
    except (AttributeError,UnicodeError):result['issues'].append('CODEOWNERS unavailable')
    before,names=reader.workflows();total=len(raw_policy)+len(manifest or b'')+len(owners or b'')
    for name in names:
        if time.monotonic()>deadline or total>4*1024*1024:raise g.Refusal('profile-control-time-or-byte-bound')
        data,_=reader.read('.github/workflows/'+name)
        if data is None:raise g.Refusal('profile-workflow-disappeared')
        total+=len(data);result['controls_read']+=1;result['workflows_checked']+=1
        text=data.decode('utf-8',errors='replace').lower()
        if 'pr-automation' in text or 'kleinperkins-review-bot' in text:result['issues'].append('legacy Actions PR automation present')
    reader.check()
    if time.monotonic()>deadline or total>4*1024*1024:raise g.Refusal('profile-control-time-or-byte-bound')
    if reader.workflows()!=(before,names):raise g.Refusal('profile-workflow-directory-changed')
    result['status']='NONCOMPLIANT' if result['issues'] else 'COMPLIANT'
    return result


def remote_contract(repo,profile_present,baseline,authority,responses):
    eligible=baseline['baseline_eligibility']['classification']=='ELIGIBLE'
    history=eligible and baseline['baseline_compliance']=='COMPLIANT'
    result={'review':'NOT_APPLICABLE','history':'NOT_APPLICABLE','admin_bypass':'NOT_APPLICABLE',
            'deployed_fingerprint':'NOT_APPLICABLE','deployed_policy_contract':'NOT_APPLICABLE',
            'live_app_fingerprint':'NOT_APPLICABLE','operator_full_attestation':False}
    wanted=[]
    if eligible:wanted.append('review')
    if history:wanted.append('history')
    if profile_present:wanted+=['admin_bypass','deployed_fingerprint','deployed_policy_contract','live_app_fingerprint']
    if not wanted:return result
    for key in wanted:result[key]='UNKNOWN'
    endpoints=urls(repo,authority)
    state,data=responses.read(endpoints['metadata'],'live personal repository identity before dependent requests')
    if state!='ok' or not metadata_identity(repo,data):return result
    if eligible:
        state,data=responses.read(endpoints['review'],'effective default-branch human-review tripwire')
        result['review']=review_policy(data) if state=='ok' else 'UNKNOWN'
    if history:
        state,data=responses.read(endpoints['history'],'qualified baseline history ruleset status')
        result['history']='UNENFORCED_PLAN_LIMIT' if state=='plan-limit' else history_policy(data) if state=='ok' else 'UNKNOWN'
    if not profile_present:return result
    target=authority.targets.get(repo);projection=authority.projection(repo)
    if target is None or projection is None:return result
    if target['merge_safety_ruleset_id'] is None:
        result['admin_bypass']='NOT_ENROLLED';result['live_app_fingerprint']='NOT_ENROLLED'
    else:
        state,data=responses.read(endpoints['merge_safety'],'exact enrolled merge-safety identity, visible admin bypass and App fingerprint')
        if state=='ok' and ruleset_identity(repo,target,data):
            result['admin_bypass']=admin_bypass(data)
            if fingerprint_shape(data):
                try:
                    pair=p.ruleset_fingerprint_pair(data)
                    result['live_app_fingerprint']='CLEAN' if pair['runtime_app_visible']==projection.runtime_app_visible_fingerprints else 'DRIFT'
                except (ValueError,TypeError,AttributeError,KeyError):pass
    state,policy,head=deployed_policy(repo,authority,responses)
    if state=='NOT_STAGED':
        result['deployed_fingerprint']='NOT_STAGED';result['deployed_policy_contract']='NOT_STAGED';return result
    if state!='OBSERVED':return result
    try:
        if not policy_identity(repo,policy):return result
        result['deployed_policy_commit']=head
        fingerprints=policy.get('ruleset_fingerprints')
        result['deployed_fingerprint']='CLEAN' if isinstance(fingerprints,list) and all(isinstance(v,str) for v in fingerprints) and sorted(fingerprints)==sorted(projection.runtime_app_visible_fingerprints) else 'STALE_FINGERPRINT'
        try:
            authority.policy(repo,policy);result['deployed_policy_contract']='COMPLIANT'
        except (ValueError,TypeError,KeyError,SystemExit,p.ControlPlaneError):result['deployed_policy_contract']='NONCOMPLIANT'
    except (ValueError,TypeError,KeyError,UnicodeError):pass
    return result


def outcomes(local,remote):
    available=local['status']!='UNAVAILABLE' and not any(v in ('UNKNOWN','UNENFORCED_PLAN_LIMIT') for v in remote.values())
    levels=['OK']
    if local['status'] not in {'COMPLIANT','NOT_APPLICABLE'} or not available:levels.append('ADVISORY')
    if remote['history']=='REQUIRED' or remote['deployed_policy_contract'] in {'NONCOMPLIANT','NOT_STAGED'}:levels.append('ADVISORY')
    if remote['review']=='REVIEW_DRIFT' or remote['deployed_fingerprint']=='STALE_FINGERPRINT' or remote['live_app_fingerprint']=='DRIFT':levels.append('DRIFT')
    return available,c.verdict(*levels)


def inspect(scope,tool,authority,responses):
    rows=[];templates=b.load_templates()
    for target in scope.targets():
        repo_id=target['id']
        try:
            with scope.repository(repo_id) as repo:
                baseline=b.PersonalBaseline(repo,tool,templates).observe()
                if not baseline['baseline_available']:raise g.Refusal('profile-baseline-applicability-unavailable')
                tree=w.PersonalWorktree(repo,tool);identity=tree.git.observe()
                if identity['head']!=baseline['head'] or identity['branch']!=baseline['branch']:
                    raise g.Refusal('profile-repository-head-or-branch-changed')
                reader=ProfileReader(tree);raw,_=reader.read(POLICY)
                local=local_contract(reader,repo_id,authority,raw)
                remote=remote_contract(repo_id,raw is not None,baseline,authority,responses)
                reader.check();tree.git.finish();tree.unchanged()
                after=b.PersonalBaseline(repo,tool,templates).observe()
                if (not after['baseline_available'] or b.PersonalBaseline.stable(baseline)!=b.PersonalBaseline.stable(after)
                        or after['baseline_eligibility']!=baseline['baseline_eligibility']
                        or after['baseline_compliance']!=baseline['baseline_compliance']):
                    raise g.Refusal('profile-baseline-applicability-changed')
                reader.check();authority.unchanged()
                available,verdict=outcomes(local,remote)
                rows.append({'id':repo_id,'available':available,'verdict':verdict,
                             'head':identity['head'],'pin_matches':identity['pin_matches'],
                             'baseline_eligibility':baseline['baseline_eligibility'],
                             'baseline_compliance':baseline['baseline_compliance'],
                             'profile_present':raw is not None,'local':local,'remote':remote,
                             'local_control_evidence_sha256':w.digest(reader.evidence),
                             'legacy_doctor_compatibility_result':'v3 is incompatible with the legacy unversioned closed v1 verifier' if local['version']=='pr-automation/v3' else 'not applicable' if raw is None else 'legacy compatibility not evaluated',
                             'legacy_state_or_status_adopted':False})
        except (ValueError,OSError,UnicodeError,SystemExit,p.ControlPlaneError) as error:
            rows.append({'id':repo_id,'available':False,'verdict':'ADVISORY',
                         'reason':str(error) if isinstance(error,g.Refusal) else 'bounded-personal-profile-unavailable'})
    responses.check_used()
    return {'schema':'personal-portability/personal-profile/v1','owner_ref':OWNER_REF,
            'owner_profile_blob':OWNER_PROFILE_BLOB,'qualified_authority_sha256':dict(DATA_HASHES),
            'rows':rows,'requests':list(responses.missing.values()),
            'connector_receipt_grants_no_auth_or_owner_approval':True,
            'network_requests_by_this_process':0,'source_or_configuration_writes':False,
            'new_shared_links':0,'new_workers':0,'legacy_doctor_changed':False,
            'control_plane_or_lock_currency_or_full_doctor_or_native_acceptance':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--repository',action='append')
    parser.add_argument('--responses-stdin',action='store_true');args=parser.parse_args(argv)
    try:
        selected=s.selected_ids(args.repository)
        scope=s.PersonalScope(repositories=selected);authority=Authority()
        value=None
        if args.responses_stdin:
            raw=sys.stdin.buffer.read(MAX_RECEIPT_BYTES+1)
            if len(raw)>MAX_RECEIPT_BYTES:raise g.Refusal('profile-response-byte-bound')
            value=strict_json(raw)
        responses=Responses(value,selected,authority)
        result=inspect(scope,g.GitTool(),authority,responses)
        print(json.dumps(result,sort_keys=True));return 2 if any(not r['available'] for r in result['rows']) else 0
    except (ValueError,OSError,UnicodeError,TypeError,KeyError,SystemExit,p.ControlPlaneError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'personal-profile-authority-scope-or-input-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
