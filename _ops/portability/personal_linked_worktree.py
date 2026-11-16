"""Exact-binding linked checkout status using disposable own/common Git metadata.

Preview opens only the accepted primary registry. Inspect additionally requires
an exact caller-supplied private binding digest. This input does not manufacture
human consent, install a capability, or qualify the complete doctor/native route.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

HERE=Path(__file__).absolute().parent
REGISTRY_SHA256='207597cb1c7a195e29e8fdb1c9934a28d6610c8c6707eca9dfb08ff9d00c53e4'
source=HERE/'personal_linked_registry.py'
if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=REGISTRY_SHA256:
    raise ValueError('accepted personal linked registry dependency changed')
sys.path.insert(0,str(HERE))
import personal_linked_registry as r
if Path(r.__file__).absolute()!=source:raise ValueError('linked registry imported from another root')
g,w,s=r.g,r.w,r.s
OWNER_REF='be42049dc0d8cf5a7df45e4342ec7c5056453fa8'
SCHEMA='personal-portability/personal-linked-read-binding/v1'
MAX_BINDING_BYTES=65536
MAX_INDEX_BYTES=128*1024*1024


def binding_document(candidate):
    if candidate.get('status')!='proposed-uninspected':raise g.Refusal('linked-proposal-not-available')
    proposal=candidate['binding_proposal']
    if candidate['candidate_sha256']!=w.digest(proposal):raise g.Refusal('linked-proposal-digest-differs')
    return {'schema':SCHEMA,'operation':'read-only-linked-worktree',
            'registry_owner_ref':OWNER_REF,'manifest_sha256':s.MANIFEST_SHA256,
            'repository':proposal['repository'],'candidate_sha256':candidate['candidate_sha256'],
            'binding_proposal':proposal}


def read_binding(raw,expected_sha256):
    if (not isinstance(raw,bytes) or len(raw)>MAX_BINDING_BYTES
            or not isinstance(expected_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha256)
            or g.sha(raw)!=expected_sha256):raise g.Refusal('exact-linked-binding-bytes-required')
    try:value=r.p.strict_json(raw)
    except (ValueError,TypeError,UnicodeError):raise g.Refusal('linked-binding-document-invalid') from None
    keys={'schema','operation','registry_owner_ref','manifest_sha256','repository','candidate_sha256','binding_proposal'}
    if (not isinstance(value,dict) or set(value)!=keys or value['schema']!=SCHEMA
            or value['operation']!='read-only-linked-worktree' or value['registry_owner_ref']!=OWNER_REF
            or value['manifest_sha256']!=s.MANIFEST_SHA256):raise g.Refusal('linked-binding-contract-differs')
    s.selected_ids([value['repository']])
    proposal=value['binding_proposal']
    if (not isinstance(proposal,dict) or proposal.get('repository')!=value['repository']
            or w.digest(proposal)!=value['candidate_sha256']):raise g.Refusal('linked-binding-proposal-differs')
    return value


def candidate_for(repo,tool,home,digest):
    found=r.one(repo,tool,home)
    values=[c for c in found['candidates'] if c.get('status')=='proposed-uninspected' and c.get('candidate_sha256')==digest]
    if len(values)!=1:raise g.Refusal('exact-linked-proposal-no-longer-current')
    return values[0]


class LinkedContext:
    def __init__(self,primary,common,registry,entry,target,repo):
        self.primary,self.common,self.registry,self.entry,self.target,self.repo=primary,common,registry,entry,target,repo

    def check(self):
        self.common.check();self.registry.check();self.entry.check();self.target.check()


@contextmanager
def bound_checkout(scope,tool,raw,digest):
    # Document and exact selected repository are checked before opening even a
    # primary root. A registry pointer by itself never enters this route.
    binding=read_binding(raw,digest);identifier=binding['repository'];proposal=binding['binding_proposal']
    if identifier not in scope.repositories:raise g.Refusal('linked-binding-outside-selected-repositories')
    with scope.repository(identifier) as primary:
        if candidate_for(primary,tool,scope.home,binding['candidate_sha256'])['binding_proposal']!=proposal:
            raise g.Refusal('linked-binding-proposal-changed')
        fd=s.child_directory(primary._fd,('.git',))
        try:
            directory=r.MetadataDirectory(fd,primary.path/'.git');common=r.CommonMetadata(primary,tool,directory)
            with directory.child('worktrees') as registry:
                name=Path(proposal['entry_path']).name;r.component(name)
                registry.membership=tuple(sorted(os.listdir(registry.fd)))
                with registry.child(name) as entry:
                    current=r.propose(primary,common,registry,entry,scope.home)
                    if current['binding_proposal']!=proposal:raise g.Refusal('linked-proposal-preimage-changed')
                    path=Path(proposal['target_path'])
                    # Linked descendants of approved primaries are nested roots,
                    # never a separate additional checkout admission.
                    if any(path.is_relative_to(scope.home/'dev'/row[0]) for row in s.PROJECTS.values()):
                        raise g.Refusal('linked-nested-primary-root-held')
                    common.check()
                    target_fd=s.absolute_directory(path)
                    try:
                        target=r.MetadataDirectory(target_fd,path)
                        gitfile=target.read('.git',limit=r.MAX_POINTER_BYTES)
                        if not gitfile.startswith(b'gitdir: '):raise g.Refusal('linked-target-gitfile-invalid')
                        backpointer,_=r.pointer(gitfile[len(b'gitdir: '):],path)
                        if backpointer!=entry.path:raise g.Refusal('linked-target-backpointer-differs')
                        row={**primary.row,'path':str(path.relative_to(scope.home))}
                        repo=s.RepositoryView(target_fd,row,path)
                        context=LinkedContext(primary,common,registry,entry,target,repo)
                        context.check();yield context;context.check()
                    finally:os.close(target_fd)
        finally:os.close(fd)


def copy_file(directory,name,destination,budget,*,required=False):
    state=r.file_state(directory.fd,name,required=required,limit=MAX_INDEX_BYTES)
    previous=directory.observed.get(name)
    if previous is not None:
        if previous['state']!=state:raise g.Refusal('linked-copy-preimage-changed')
    else:directory.state(name,required=required,limit=MAX_INDEX_BYTES)
    if state['kind']=='absent':return
    budget['bytes']+=state['size'];budget['entries']+=1
    if (budget['bytes']>g.MAX_PRIVATE_BYTES or budget['entries']>g.MAX_METADATA_ENTRIES
            or time.monotonic()>=budget['deadline']):raise g.Refusal('linked-private-copy-bound')
    fd=os.open(name,s.FILE_FLAGS,dir_fd=directory.fd)
    try:
        before=os.fstat(fd)
        if {'kind':'file',**w.fact(before)}!=state:raise g.Refusal('linked-copy-source-changed')
        destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        output=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(output,'wb') as stream:
            remaining=before.st_size
            while remaining:
                if time.monotonic()>=budget['deadline']:raise g.Refusal('linked-private-copy-bound')
                block=os.read(fd,min(remaining,65536))
                if not block:raise g.Refusal('linked-copy-source-changed')
                stream.write(block);remaining-=len(block)
        os.utime(destination,ns=(before.st_atime_ns,before.st_mtime_ns),follow_symlinks=False)
        if ({'kind':'file',**w.fact(os.fstat(fd))}!=state
                or r.file_state(directory.fd,name,limit=MAX_INDEX_BYTES)!=state):
            raise g.Refusal('linked-copy-source-changed')
    finally:os.close(fd)


def copy_tree(directory,name,destination,budget,*,own_refs=False):
    try:info=os.stat(name,dir_fd=directory.fd,follow_symlinks=False)
    except FileNotFoundError:
        raise g.Refusal('linked-copy-tree-disappeared') from None
    if not stat.S_ISDIR(info.st_mode):raise g.Refusal('linked-copy-tree-type-held')
    previous=copy.deepcopy(directory.children.get(name))
    with directory.child(name) as child:
        names=tuple(sorted(os.listdir(child.fd)));child.membership=names
        if own_refs and any(n not in {'bisect','rewritten','worktree'} for n in names):
            raise g.Refusal('unknown-own-worktree-ref-namespace-held')
        destination.mkdir(mode=0o700,parents=True,exist_ok=True)
        for item in names:
            budget['entries']+=1
            if budget['entries']>g.MAX_METADATA_ENTRIES or time.monotonic()>=budget['deadline']:
                raise g.Refusal('linked-private-copy-bound')
            state=os.stat(item,dir_fd=child.fd,follow_symlinks=False)
            if stat.S_ISDIR(state.st_mode):copy_tree(child,item,destination/item,budget)
            elif stat.S_ISREG(state.st_mode):copy_file(child,item,destination/item,budget,required=True)
            else:raise g.Refusal('linked-private-ref-alias-held')
    if previous is not None and directory.children[name]!=previous:raise g.Refusal('linked-ref-copy-preimage-changed')


class LinkedGit(g.PersonalGit):
    def __init__(self,context,tool):
        self.context,self.repo,self.tool=context,context.repo,tool
        self.base_config=context.common.config
        self.config_raw=context.common.config_raw
        self.config={key:list(values) for key,values in self.base_config.items()}
        self.overlay_config={};self.worktree_raw=None
        enabled=g.git_bool(g.last(self.config,'extensions.worktreeconfig','false'))
        if enabled:
            self.worktree_raw=context.entry.read('config.worktree',required=False,limit=s.MAX_FILE_BYTES)
            if self.worktree_raw is not None:
                self.overlay_config=tool.parse_config(self.worktree_raw)
                for key,values in self.overlay_config.items():self.config.setdefault(key,[]).extend(values)
        else:
            # Git applies these common settings only to the main checkout when
            # per-worktree configuration is disabled.
            for key in ('core.bare','core.worktree'):self.config.pop(key,None)
        worktree=g.last(self.config,'core.worktree')
        if 'core.worktree' in self.config and worktree is None:raise g.Refusal('invalid-linked-worktree-setting')
        if worktree is not None:
            candidate,_=r.pointer(worktree.encode(),context.entry.path)
            if candidate!=self.repo.path:raise g.Refusal('linked-effective-worktree-outside-binding')
        checked={key:list(values) for key,values in self.config.items() if key!='core.worktree'}
        r.validate_common_config(checked,self.repo)
        for key,values in self.config.items():
            if key.startswith('branch.') and key.endswith('.merge'):
                for value in values:
                    if value and value.startswith('worktrees/') and not value.startswith('worktrees/'+context.entry.path.name+'/'):
                        raise g.Refusal('unbound-other-worktree-tracking-ref-held')
        self.probes=[];self._active_gitdir=None;self.storage=context.common.storage
        self.absent_trees=[]
        self.shared_indexes=self.shared_index_facts()

    def shared_index_facts(self):
        entry=self.context.entry;names=tuple(sorted(os.listdir(entry.fd)))
        if len(names)>1024:raise g.Refusal('linked-admin-inventory-bound')
        if entry.membership is not None and entry.membership!=names:raise g.Refusal('linked-admin-membership-changed')
        entry.membership=names
        if any(name.endswith('.lock') for name in names):raise g.Refusal('linked-admin-lock-present')
        indexes={}
        for name in names:
            if name.startswith('sharedindex.'):
                if not re.fullmatch(r'sharedindex\.[0-9a-f]{40}',name):raise g.Refusal('linked-shared-index-name-held')
                indexes[name]=entry.state(name,required=True,limit=MAX_INDEX_BYTES)
        return indexes

    def unchanged_config(self):
        self.context.check()
        for directory,name in self.absent_trees:
            try:os.stat(name,dir_fd=directory.fd,follow_symlinks=False)
            except FileNotFoundError:continue
            raise g.Refusal('linked-absent-metadata-tree-appeared')

    def copy_optional_tree(self,directory,name,destination,budget,*,own_refs=False):
        try:os.stat(name,dir_fd=directory.fd,follow_symlinks=False)
        except FileNotFoundError:
            self.absent_trees.append((directory,name));return
        copy_tree(directory,name,destination,budget,own_refs=own_refs)

    @contextmanager
    def private_gitdir(self,*,worktree_controls=False):
        if self._active_gitdir is not None:yield self._active_gitdir;return
        self.unchanged_config()
        if self.shared_index_facts()!=self.shared_indexes:raise g.Refusal('linked-shared-index-changed')
        common=self.context.common.directory;entry=self.context.entry
        parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        with tempfile.TemporaryDirectory(prefix='personal-linked-Git-',dir=parent) as temporary:
            private=Path(temporary)/'common';admin=private/'worktrees'/entry.path.name
            admin.mkdir(mode=0o700,parents=True)
            budget={'bytes':0,'entries':0,'deadline':time.monotonic()+g.MAX_METADATA_SECONDS}
            for name in ('HEAD','packed-refs','shallow'):copy_file(common,name,private/name,budget,required=name=='HEAD')
            for name in ('HEAD','index'):copy_file(entry,name,admin/name,budget,required=True)
            for name in self.shared_indexes:copy_file(entry,name,admin/name,budget,required=True)
            self.copy_optional_tree(common,'refs',private/'refs',budget)
            self.copy_optional_tree(entry,'refs',admin/'refs',budget,own_refs=True)
            (private/'refs').mkdir(mode=0o700,exist_ok=True)
            # Sparse-index expansion can write trees and freshen existing loose
            # objects, including read alternates. Copy only the already audited
            # personal object store into this bounded disposable view. No links,
            # alternates, source permissions or source timestamps are changed.
            copy_tree(common,'objects',private/'objects',budget)
            (private/'config').write_bytes(self.private_config());(private/'config').chmod(0o600)
            (admin/'commondir').write_text(str(private)+'\n');(admin/'commondir').chmod(0o600)
            if worktree_controls:
                for directory,names,destination in ((common,('exclude','attributes'),private/'info'),(entry,('sparse-checkout',),admin/'info')):
                    try:os.stat('info',dir_fd=directory.fd,follow_symlinks=False)
                    except FileNotFoundError:self.absent_trees.append((directory,'info'));continue
                    with directory.child('info') as info:
                        for name in names:copy_file(info,name,destination/name,budget)
            self.unchanged_config();self._active_gitdir=admin
            try:yield admin;self.finish()
            finally:self._active_gitdir=None

    def finish(self):
        self.unchanged_config()
        if self.shared_index_facts()!=self.shared_indexes:raise g.Refusal('linked-shared-index-changed')


class LinkedWorktree(w.PersonalWorktree):
    def __init__(self,context,tool):
        self.repo,self.tool=context.repo,tool;self.git=LinkedGit(context,tool)
        self.probes=[];self.controls={};self.tree_ready=False;self.ignore_ready=False;self.exclude_path='/dev/null'
        self.shared_indexes=self.shared_index_facts()

    def shared_index_facts(self):return self.git.shared_index_facts()

    def configure_ignore(self,temporary):
        value=g.last(self.git.config,'core.excludesfile')
        if 'core.excludesfile' in self.git.config and value is None:raise g.Refusal('invalid-local-excludes-setting')
        if value not in (None,'','/dev/null'):
            if value.startswith(('~','%(')):raise g.Refusal('local-excludes-file-outside-personal-root')
            candidate=Path(value)
            if candidate.is_absolute():
                try:relative=str(candidate.relative_to(self.repo.path))
                except ValueError:raise g.Refusal('local-excludes-file-outside-personal-root') from None
            else:relative=value
            self.classify_control_ancestors(relative);data=self.control(relative,optional=False)
            path=Path(temporary)/'linked-local-excludes';path.write_bytes(data);path.chmod(0o600);self.exclude_path=str(path)
        # Common exclude/attributes and own sparse-checkout were already copied
        # and are rechecked through the bound metadata descriptors. A literal
        # user-configured .git/... path must retain real gitfile semantics.
        self.git.unchanged_config()

    def classify_index(self,raw):
        indexed=w.index_paths(raw)
        if any(part.casefold() in w.HELD_NAMES for path in indexed for part in w.parts(path)):
            raise g.Refusal('linked-index-excluded-name-held')
        super().classify_index(raw)


def inspect(scope,tool,raw,digest):
    try:
        with bound_checkout(scope,tool,raw,digest) as context:
            observation=LinkedWorktree(context,tool).observe()
            return {'schema':'personal-portability/personal-linked-worktree/v1','available':True,
                    'binding_sha256':digest,'observation':observation,'additional_root_count':1,
                    'metadata_layout':'separate private common and correctly nested own admin directory',
                    'generated_memory_contents_read':False,'source_or_config_writes':False,
                    'network_requests':0,'new_shared_links':0,'new_model_workers':0,
                    'hook_memory_baseline_profile_documentation_caller_or_native_acceptance':False}
    except (ValueError,OSError,UnicodeError,TypeError,KeyError) as error:
        return {'schema':'personal-portability/personal-linked-worktree/v1','available':False,
                'reason':str(error) if isinstance(error,g.Refusal) else 'bound-linked-worktree-unavailable',
                'actual_target_status_proven':False,'full_doctor_or_native_acceptance':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['preview','inspect']);parser.add_argument('--repository')
    parser.add_argument('--candidate-sha256');parser.add_argument('--binding-sha256');args=parser.parse_args(argv)
    try:
        if args.operation=='preview':
            if not args.repository or not args.candidate_sha256 or args.binding_sha256:raise g.Refusal('exact-registry-candidate-required')
            scope=s.PersonalScope(repositories=s.selected_ids([args.repository]));tool=g.GitTool()
            with scope.repository(args.repository) as repo:
                value=binding_document(candidate_for(repo,tool,scope.home,args.candidate_sha256))
            raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
            print(json.dumps({'binding':value,'canonical_binding_sha256':g.sha(raw),'target_opened':False,
                              'owner_consent_or_native_acceptance_granted':False},sort_keys=True));return 0
        if args.repository or args.candidate_sha256:raise g.Refusal('inspect-requires-only-exact-binding-input')
        raw=sys.stdin.buffer.read(MAX_BINDING_BYTES+1);value=read_binding(raw,args.binding_sha256)
        result=inspect(s.PersonalScope(repositories=[value['repository']]),g.GitTool(),raw,args.binding_sha256)
        print(json.dumps(result,sort_keys=True));return 0 if result['available'] else 2
    except (ValueError,OSError,UnicodeError,TypeError,KeyError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'linked-scope-tool-or-input-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
