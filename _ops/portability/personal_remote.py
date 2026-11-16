"""Staged personal remote sync and exact owner fleet/lock diagnostics.

Only selected personal GitHub GET observations are consumed. The process never
fetches, authenticates, pushes, runs a recipe, changes controller state or grants
owner visibility. Lock currency needs the exact release-qualified compiler.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote,unquote

HERE=Path(__file__).absolute().parent
DEPENDENCIES={
    'personal_profile.py':'b87380607286daf77a9a0dc6e5dcbaa4a1d269e9fc704882734a1005942a7fca',
    'personal_remote_contract.py':'5f41a9e9030964b442d756c38e2f8de31f2d625052435a759f9b2901c6f493fd',
}
for name,digest in DEPENDENCIES.items():
    path=HERE/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('personal remote dependency changed')
sys.path.insert(0,str(HERE))
import personal_profile as p
import personal_remote_contract as owner
for name in DEPENDENCIES:
    if Path(sys.modules[Path(name).stem].__file__).absolute()!=HERE/name:
        raise ValueError('remote dependency imported from another root')
g,w,s=p.g,p.w,p.s
OID=re.compile(r'[0-9a-f]{40}')
MAX_BYTES=16*1024*1024
MAX_REQUESTS=512
MAX_PAGES=10
MAX_FILE_BYTES=2*1024*1024
MAX_COMPILER_BYTES=64*1024*1024
COMPILER_PREFIX=Path('.local/share/personal-portability/qualified-lock-compilers')
LOCK='.github/pr-automation.lock.json'
RECIPE='.github/pr-recipe.json'


class Unavailable(RuntimeError):
    """Unavailable evidence must not be relabeled a known semantic mismatch."""


def branch_name(value):
    if (not isinstance(value,str) or not value or len(value.encode('utf-8'))>1024
            or any(ord(ch)<32 or ord(ch)==127 for ch in value)
            or any(part in {'','..'} or part.casefold() in w.HELD_NAMES for part in value.split('/'))):
        raise g.Refusal('remote-branch-shape-held')
    return value


def base(repo):
    s.selected_ids([repo]);return 'https://api.github.com/repos/'+repo


def git_blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


class Observations:
    def __init__(self,value,selected,authority,*,now=None):
        self.selected=s.selected_ids(selected);self.authority=authority
        self.entries={};self.used=set();self.dynamic=set();self.missing={};self.allowed=set()
        for repo in self.selected:
            root=base(repo);self.allowed.add(root)
            self.allowed.update(root+'/rulesets?per_page=100&page='+str(page) for page in range(1,MAX_PAGES+1))
            target=authority.targets.get(repo)
            if target and target.get('merge_safety_ruleset_id') is not None:self.allowed.add(root+'/rulesets/'+str(target['merge_safety_ruleset_id']))
        if value is None:return
        if (not isinstance(value,dict) or set(value)!={'schema','observed_at','requests'}
                or value['schema']!='personal-doctor-remote-observations/v1'
                or not isinstance(value['requests'],list) or len(value['requests'])>MAX_REQUESTS
                or len(json.dumps(value,separators=(',',':')).encode())>MAX_BYTES):
            raise g.Refusal('remote-observation-envelope-held')
        try:
            observed=dt.datetime.fromisoformat(value['observed_at'].replace('Z','+00:00'))
            current=now or dt.datetime.now(dt.timezone.utc)
            if observed.tzinfo is None or not -5<=(current-observed).total_seconds()<=300:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise g.Refusal('remote-observation-time-held') from None
        for row in value['requests']:
            if (not isinstance(row,dict) or set(row)!={'url','outcome','data'} or not isinstance(row['url'],str)
                    or row['url'] in self.entries or not isinstance(row['outcome'],str) or row['outcome'] not in p.OUTCOMES
                    or (row['outcome']!='ok' and row['data'] is not None)):
                raise g.Refusal('remote-observation-entry-held')
            url=row['url'];dynamic=False
            for repo in self.selected:
                root=base(repo)
                if re.fullmatch(re.escape(root)+r'/git/(trees|blobs|commits)/[0-9a-f]{40}',url):dynamic=True;break
                prefix=root+'/branches/'
                if url.startswith(prefix):
                    encoded=url[len(prefix):]
                    try:name=branch_name(unquote(encoded,errors='strict'))
                    except (ValueError,UnicodeError):continue
                    if encoded==quote(name,safe=''):dynamic=True;break
            if url not in self.allowed and not dynamic:raise g.Refusal('remote-observation-target-held')
            if dynamic:self.dynamic.add(url)
            self.entries[url]=row

    def read(self,url,purpose):
        if url not in self.allowed:raise g.Refusal('remote-unqualified-request-held')
        row=self.entries.get(url)
        if row is None:
            self.missing[url]={'method':'GET','url':url,'purpose':purpose};return 'unavailable',None
        self.used.add(url);return row['outcome'],row['data']

    def metadata(self,repo):
        if repo not in self.selected:raise g.Refusal('remote-unselected-repository-held')
        state,value=self.read(base(repo),'exact personal repository ID/name/default branch before dependent reads')
        if state!='ok' or not p.metadata_identity(repo,value):raise Unavailable('remote-repository-identity-unavailable')
        return value

    def branch(self,repo,name):
        branch_name(name);url=base(repo)+'/branches/'+quote(name,safe='');self.allowed.add(url)
        state,value=self.read(url,'exact observed personal branch tip; read-only live parity')
        if (state!='ok' or not isinstance(value,dict) or value.get('name')!=name
                or not isinstance(value.get('commit'),dict) or not isinstance(value['commit'].get('sha'),str)
                or OID.fullmatch(value['commit']['sha']) is None):
            raise Unavailable('remote-branch-tip-unavailable')
        return value

    def object(self,repo,kind,oid):
        if repo not in self.selected or kind not in {'trees','blobs','commits'} or not isinstance(oid,str) or OID.fullmatch(oid) is None:
            raise g.Refusal('remote-Git-object-pointer-held')
        url=base(repo)+'/git/'+kind+'/'+oid;self.allowed.add(url)
        state,value=self.read(url,'immutable selected personal '+kind+' object '+oid)
        if state!='ok':raise Unavailable('remote-Git-object-unavailable')
        return value

    def tree_at(self,repo,head,*,branch=None):
        if branch is not None:
            commit=branch.get('commit') if isinstance(branch,dict) else None
            inner=commit.get('commit') if isinstance(commit,dict) else None
            tree=inner.get('tree') if isinstance(inner,dict) else None
        else:
            commit=self.object(repo,'commits',head)
            if not isinstance(commit,dict) or commit.get('sha')!=head:raise Unavailable('remote-commit-identity-unavailable')
            tree=commit.get('tree')
        value=tree.get('sha') if isinstance(tree,dict) else None
        if not isinstance(value,str) or OID.fullmatch(value) is None:raise Unavailable('remote-root-tree-unavailable')
        return value

    def file(self,repo,tree,path):
        if path not in {p.POLICY,LOCK,RECIPE}:raise g.Refusal('remote-artifact-path-held')
        parts=path.split('/')
        for index,name in enumerate(parts):
            value=self.object(repo,'trees',tree)
            try:entry=p.tree_entry(value,tree,name)
            except (ValueError,TypeError,KeyError):raise Unavailable('remote-tree-object-hash-unavailable') from None
            if entry is None:return None,None
            if index<len(parts)-1:
                if entry['mode']!='040000':raise Unavailable('remote-artifact-parent-type-held')
                tree=entry['sha'];continue
            if entry['mode'] not in {'100644','100755'}:raise Unavailable('remote-artifact-file-type-held')
            oid=entry['sha'];blob=self.object(repo,'blobs',oid)
            # The personal connector's blob route supplies decoded UTF-8 text.
            # No contents-URL base64 ambiguity or arbitrary source path exists.
            if not isinstance(blob,str):raise Unavailable('remote-artifact-body-unavailable')
            raw=blob.encode('utf-8')
            if len(raw)>MAX_FILE_BYTES or git_blob(raw)!=oid:raise Unavailable('remote-blob-object-hash-unavailable')
            return raw,oid
        raise Unavailable('remote-artifact-path-unavailable')

    def rulesets(self,repo):
        rows=[];seen=set()
        for page in range(1,MAX_PAGES+1):
            state,value=self.read(base(repo)+'/rulesets?per_page=100&page='+str(page),'complete bounded ruleset metadata listing; duplicate managed names remain visible')
            if state!='ok' or not isinstance(value,list) or len(value)>100:raise Unavailable('remote-ruleset-listing-unavailable')
            for row in value:
                if not isinstance(row,dict) or not p.positive(row.get('id')) or row['id'] in seen:raise Unavailable('remote-ruleset-listing-identity-unavailable')
                seen.add(row['id']);rows.append(row)
            if len(value)<100:return rows
        raise Unavailable('remote-ruleset-pagination-bound')

    def check_used(self):
        if self.dynamic-self.used:raise g.Refusal('remote-unproven-dynamic-response-held')


def sync(repo,status,observations):
    if not status.get('available'):return {'available':False,'classification':'UNAVAILABLE','fallback':'local status unavailable'}
    name=status.get('branch')
    if name is None:return {'available':True,'classification':'NOT_APPLICABLE','reason':'detached-HEAD; canonical route falls back to local tracking','fallback':'local-tracking'}
    try:
        observations.metadata(repo);branch=observations.branch(repo,name)
        head=branch['commit']['sha'];equal=head==status['head']
        return {'available':True,'classification':'EQUAL' if equal else 'DIFFERENT','remote_head':head,
                'canonical_sync_label':'0/0' if equal else 'live≠','live_remote_parity_proven':equal,
                'fetch_push_or_recipe_execution':False}
    except (ValueError,UnicodeError,Unavailable):
        return {'available':False,'classification':'UNAVAILABLE','fallback':'last-fetch local tracking only','live_remote_parity_proven':False}


class PrivateDirectories:
    def __init__(self):self.active=set()

    @contextmanager
    def TemporaryDirectory(self,*,prefix):
        if prefix!='pr-automation-lock-validate-':raise Unavailable('remote-private-directory-verb-held')
        parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        previous=os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory(prefix=prefix,dir=parent) as raw:
                root=Path(raw);self.active.add(root)
                try:yield raw
                finally:self.active.remove(root)
        finally:os.umask(previous)


class QualifiedCompiler:
    """Only the fixed private digest-addressed artifact; never a caller command."""
    def __init__(self,home,controller):
        release=controller.get('release') if isinstance(controller,dict) else None
        digest=release.get('lock_compiler_digest') if isinstance(release,dict) else None
        if not isinstance(digest,str) or re.fullmatch(r'sha256:[0-9a-f]{64}',digest) is None:raise Unavailable('remote-compiler-authority-unavailable')
        self.expected=digest;self.path=home/COMPILER_PREFIX/digest[7:]/'lock-compiler'
        self.before,self.raw=self.read()
        if 'sha256:'+g.sha(self.raw)!=digest:raise Unavailable('remote-qualified-compiler-digest-mismatch')
        self.controller=controller

    def read(self):
        try:
            parent=s.absolute_directory(self.path.parent)
            try:
                before=os.stat(self.path.name,dir_fd=parent,follow_symlinks=False)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1
                        or stat.S_IMODE(before.st_mode)!=0o500 or before.st_size>MAX_COMPILER_BYTES):
                    raise Unavailable('remote-qualified-compiler-file-held')
                # The accepted scope reader intentionally caps *controls* at
                # 1 MiB. Do not change that shared limit to read a Rust binary.
                descriptor=os.open(self.path.name,s.FILE_FLAGS,dir_fd=parent)
                try:
                    if w.fact(os.fstat(descriptor))!=w.fact(before):raise Unavailable('remote-qualified-compiler-changed')
                    data=bytearray()
                    while len(data)<=MAX_COMPILER_BYTES:
                        block=os.read(descriptor,min(65536,MAX_COMPILER_BYTES+1-len(data)))
                        if not block:break
                        data.extend(block)
                    if len(data)>MAX_COMPILER_BYTES or w.fact(os.fstat(descriptor))!=w.fact(before):
                        raise Unavailable('remote-qualified-compiler-changed')
                    raw=bytes(data)
                finally:os.close(descriptor)
                after=os.stat(self.path.name,dir_fd=parent,follow_symlinks=False)
                if w.fact(before)!=w.fact(after):raise Unavailable('remote-qualified-compiler-changed')
                return w.fact(after),raw
            finally:os.close(parent)
        except (ValueError,OSError):raise Unavailable('remote-qualified-compiler-unavailable') from None

    def check(self):
        if self.read()!=(self.before,self.raw):raise Unavailable('remote-qualified-compiler-changed')

    def validate(self,repo,assignment,recipe,lock):
        self.check()
        # A qualified artifact for another OS is held rather than rebuilt or
        # silently substituted. Platform qualification remains an owner gate.
        if self.raw.startswith(b'\x7fELF') and sys.platform!='linux':raise Unavailable('remote-qualified-compiler-platform-unavailable')
        parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        with tempfile.TemporaryDirectory(prefix='personal-lock-compiler-',dir=parent) as temporary:
            binary=Path(temporary)/'lock-compiler';binary.write_bytes(self.raw);binary.chmod(0o500)
            private=PrivateDirectories()
            def process(argv):
                flags=('--recipe','--repository-id','--activation-generation','--profile-id','--recipe-base-sha','--recipe-blob-sha','--lock')
                if len(argv)!=16 or argv[:2]!=[str(binary),'validate'] or tuple(argv[2::2])!=flags:
                    raise Unavailable('remote-qualified-compiler-verb-held')
                args=dict(zip(argv[2::2],argv[3::2]));directory=Path(args['--recipe']).parent
                if (directory not in private.active or Path(args['--recipe'])!=directory/'recipe.json' or Path(args['--lock'])!=directory/'lock.json'
                        or args['--repository-id']!=repo.split('/')[1] or args['--profile-id']!=assignment['profile_ref']['id']
                        or args['--activation-generation']!=str(self.controller['release']['activation_generation'])
                        or OID.fullmatch(args['--recipe-base-sha']) is None or OID.fullmatch(args['--recipe-blob-sha']) is None):
                    raise Unavailable('remote-qualified-compiler-arguments-held')
                before={name:(directory/name).read_bytes() for name in ('recipe.json','lock.json')}
                try:code,out,err=g.bounded_process(argv,directory)
                except (ValueError,OSError):raise Unavailable('remote-qualified-compiler-process-unavailable') from None
                self.check()
                if any((directory/name).read_bytes()!=raw for name,raw in before.items()):raise Unavailable('remote-validator-input-changed')
                if code:raise owner.ControlPlaneError('qualified validator rejected exact supplied inputs')
                if err:raise Unavailable('remote-qualified-compiler-stderr-held')
                return subprocess.CompletedProcess(argv,code,out,err)
            contract=owner.observation_contract(private,process)
            proof=contract['validate_artifact_bytes'](recipe,lock,binary,self.controller,repo=repo,
                profile_id=assignment['profile_ref']['id'],profile_digest=assignment['profile_ref']['digest'])
            proof['validator_stdout_sha256']=g.sha(proof.pop('validator').encode())
        self.check();return proof


def fleet_row(repo,authority,observations,home):
    result={'available':False,'classification':'UNAVAILABLE','repository':repo,'control_parity':'UNAVAILABLE',
            'policy_digest_parity':'UNAVAILABLE','lock_currency':'UNAVAILABLE',
            'operator_full_visibility_attested':False,'advisory_outside_repository_verdict':True}
    target=authority.targets.get(repo)
    if target is None:return {**result,'available':True,'classification':'NOT_APPLICABLE',
        'control_parity':'NOT_APPLICABLE','policy_digest_parity':'NOT_APPLICABLE','lock_currency':'NOT_APPLICABLE',
        'reason':'selected repository is outside the canonical enrolled fleet'}
    try:
        metadata=observations.metadata(repo);branch=observations.branch(repo,target['default_branch'])
        head=branch['commit']['sha'];tree=observations.tree_at(repo,head,branch=branch)
        raw,_=observations.file(repo,tree,p.POLICY)
        if raw is None:raise owner.ControlPlaneError('merged policy absent')
        try:
            policy=p.strict_json(raw);authority.policy(repo,policy)
        except (ValueError,TypeError,KeyError,SystemExit,p.p.ControlPlaneError):
            raise owner.ControlPlaneError('merged policy does not satisfy current authority') from None
        result['policy_digest_parity']='MATCH';result['observed_commit']=head
        listed=observations.rulesets(repo)
        owner.validate_managed_ruleset_listing(listed,expected_ruleset_id=target['merge_safety_ruleset_id'],expected_repo=repo)
        state,ruleset=observations.read(base(repo)+'/rulesets/'+str(target['merge_safety_ruleset_id']),'exact managed ruleset identity and both observed fingerprint projections')
        if state!='ok':raise Unavailable('remote-exact-ruleset-unavailable')
        owner.validate_live_ruleset_identity(ruleset,expected_ruleset_id=target['merge_safety_ruleset_id'],expected_repo=repo)
        if not p.fingerprint_shape(ruleset):raise Unavailable('remote-fingerprint-observation-incomplete')
        pair=p.p.ruleset_fingerprint_pair(ruleset);projection=authority.projection(repo)
        if pair!={'runtime_app_visible':projection.runtime_app_visible_fingerprints,'operator_full':projection.operator_full_fingerprints}:
            raise owner.ControlPlaneError('observed control projections differ from current authority')
        result['control_parity']='MATCH'
        assignment=projection.assignment
        if assignment is None or assignment['coverage_mode'] not in {'shadow','local'}:
            return {**result,'available':True,'classification':'MATCH','lock_currency':'NOT_APPLICABLE'}
        lock_bytes,_=observations.file(repo,tree,LOCK)
        if lock_bytes is None:raise owner.ControlPlaneError('merged lock absent')
        try:lock=p.strict_json(lock_bytes)
        except ValueError:raise owner.ControlPlaneError('merged lock is malformed') from None
        if not isinstance(lock,dict):raise owner.ControlPlaneError('merged lock shape invalid')
        payload=lock.get('payload');base_sha=payload.get('recipe_base_sha') if isinstance(payload,dict) else None
        if not isinstance(base_sha,str) or OID.fullmatch(base_sha) is None:raise owner.ControlPlaneError('lock base malformed')
        errors=owner.lock_metadata_errors(lock,authority.controller,repo=repo,profile_id=assignment['profile_ref']['id'],profile_digest=assignment['profile_ref']['digest'])
        if errors:raise owner.ControlPlaneError('lock direct authority mismatch')
        current,current_blob=observations.file(repo,tree,RECIPE)
        if current is None:raise owner.ControlPlaneError('current recipe absent')
        owner._require_current_recipe_binding(current,current_blob,payload,source='selected remote current recipe')
        historical_tree=observations.tree_at(repo,base_sha)
        historical,historical_blob=observations.file(repo,historical_tree,RECIPE)
        if historical is None or historical_blob!=payload['recipe_blob_sha']:raise owner.ControlPlaneError('pinned historical recipe absent or changed')
        compiler=QualifiedCompiler(home,authority.controller)
        proof=compiler.validate(repo,assignment,historical,lock_bytes)
        if (not isinstance(proof,dict) or proof.get('validated') is not True or proof.get('schema_version')!=owner.LOCK_SCHEMA
                or proof.get('lock_contract_version')!=owner.LOCK_CONTRACT_VERSION
                or set(proof.get('covered_digests',{}))!=set(owner.LOCK_COVERED_DIGEST_FIELDS)):
            raise Unavailable('remote-qualified-lock-proof-incomplete')
        return {**result,'available':True,'classification':'MATCH','lock_currency':'CURRENT','artifact_validation':proof}
    except (owner.ControlPlaneError,SystemExit):
        return {**result,'available':True,'classification':'DRIFT','reason':'current owner control/policy/lock contract mismatch'}
    except (Unavailable,ValueError,OSError,TypeError,KeyError,UnicodeError):
        return {**result,'reason':'required personal remote evidence or exact qualified compiler unavailable'}
