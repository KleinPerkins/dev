"""Read-only linked-worktree registry discovery for twelve exact personal primaries.

Only approved primary/common Git metadata is opened. A registry pointer proposes
an additional root; it never authorizes opening it. Target metadata, checkout
contents, status, native discovery and complete doctor acceptance remain gated
on the separate exact binding and linked inspection owner route.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE=Path(__file__).absolute().parent
PROFILE_SHA256='b87380607286daf77a9a0dc6e5dcbaa4a1d269e9fc704882734a1005942a7fca'
source=HERE/'personal_profile.py'
if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=PROFILE_SHA256:
    raise ValueError('accepted personal profile dependency changed')
sys.path.insert(0,str(HERE))
import personal_profile as p
if Path(p.__file__).absolute()!=source:raise ValueError('personal profile imported from another root')
g,w,s=p.g,p.w,p.s
SOURCE_REF='25ac6d21cf85736f6f4315a0fc9d36dc28de5048'
MAX_REGISTRY_ENTRIES=128
MAX_POINTER_BYTES=4096
MAX_REGISTRY_SECONDS=12.0
HELD_NAMES={'affirm','chaos-scheduler'}


def component(value):
    if not isinstance(value,str) or not value or value in {'.','..'} or '/' in value or '\0' in value:
        raise g.Refusal('linked-metadata-child-name-held')
    return value


def file_state(fd,name,*,required=False,limit=s.MAX_FILE_BYTES):
    component(name)
    try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:
        if required:raise g.Refusal('required-linked-metadata-missing') from None
        return {'kind':'absent'}
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
            or info.st_size>limit):raise g.Refusal('linked-metadata-file-type-or-ownership-held')
    return {'kind':'file',**w.fact(info)}


class MetadataDirectory:
    """Pinned owned metadata descriptor. This is never a checkout/Git query root."""
    def __init__(self,fd,path):
        self.fd,self.path=fd,Path(path)
        info=os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():raise g.Refusal('linked-metadata-directory-owner-held')
        self.identity=s.identity(info);self.observed={};self.children={};self.membership=None

    @contextmanager
    def child(self,name):
        component(name)
        fd=os.open(name,s.DIR_FLAGS,dir_fd=self.fd)
        try:
            child=MetadataDirectory(fd,self.path/name)
            yield child
            child.check()
            self.children[name]={'identity':child.identity,'observed':copy.deepcopy(child.observed),
                                 'children':copy.deepcopy(child.children),'membership':child.membership}
        finally:os.close(fd)

    def state(self,name,*,required=False,limit=s.MAX_FILE_BYTES):
        result=file_state(self.fd,name,required=required,limit=limit)
        self.observed[name]={'state':result,'limit':limit,'read':False}
        return result

    def read(self,name,*,required=True,limit=MAX_POINTER_BYTES):
        before=file_state(self.fd,name,required=required,limit=limit)
        if before['kind']=='absent':
            self.observed[name]={'state':before,'limit':limit,'read':False};return None
        data=s.read_regular(self.fd,name,max_bytes=limit)
        if file_state(self.fd,name,required=True,limit=limit)!=before:raise g.Refusal('linked-metadata-file-changed')
        self.observed[name]={'state':before,'limit':limit,'read':True,'sha256':g.sha(data)}
        return data

    def check_path(self):
        fd=s.absolute_directory(self.path)
        try:
            if s.identity(os.fstat(fd))!=self.identity:raise g.Refusal('linked-metadata-directory-path-changed')
        finally:os.close(fd)

    def check(self):
        self.check_path()
        for name,expected in list(self.observed.items()):
            if file_state(self.fd,name,limit=expected['limit'])!=expected['state']:
                raise g.Refusal('linked-metadata-preimage-changed')
            if expected['read'] and g.sha(s.read_regular(self.fd,name,max_bytes=expected['limit']))!=expected['sha256']:
                raise g.Refusal('linked-metadata-bytes-changed')
        for name,expected in self.children.items():
            fd=os.open(name,s.DIR_FLAGS,dir_fd=self.fd)
            try:
                current=MetadataDirectory(fd,self.path/name)
                if current.identity!=expected['identity']:raise g.Refusal('linked-metadata-child-directory-changed')
                current.observed=copy.deepcopy(expected['observed']);current.children=copy.deepcopy(expected['children'])
                current.membership=expected['membership']
                current.check()
            finally:os.close(fd)
        if self.membership is not None and tuple(sorted(os.listdir(self.fd)))!=self.membership:
            raise g.Refusal('linked-registry-membership-changed')


def validate_common_config(config,repo):
    # Qualified Git 2.54 supports the relative-worktree linking extension. It is
    # interpreted only as metadata syntax here, never passed to an actual-root
    # Git command or expanded into target access. Unknown extensions still hold.
    checked={key:list(values) for key,values in config.items()}
    if 'extensions.relativeworktrees' in checked:
        enabled=g.git_bool(g.last(checked,'extensions.relativeworktrees'))
        if enabled and g.last(checked,'core.repositoryformatversion','0')!='1':
            raise g.Refusal('relative-worktree-format-unavailable')
        del checked['extensions.relativeworktrees']
    g.validate_config(checked,repo.row['id'],repo.path)


class CommonMetadata:
    def __init__(self,repo,tool,directory):
        self.repo,self.tool,self.directory=repo,tool,directory
        self.config_raw=directory.read('config',limit=s.MAX_FILE_BYTES)
        self.config=tool.parse_config(self.config_raw)
        validate_common_config(self.config,repo)
        # No registry, overlay, ref/object or linked-root access precedes the
        # common personal-origin/config boundary above.
        for name in ('commondir','gitdir'):
            if directory.state(name)['kind']!='absent':raise g.Refusal('expected-primary-common-metadata-held')
        if g.file_fact(repo,'.git/info/grafts') is not None:raise g.Refusal('rewritten-common-ancestry-held')
        self.storage=g.storage_inventory(repo)

    def check(self):
        self.tool.assert_current();self.directory.check()
        if g.storage_inventory(self.repo)!=self.storage:raise g.Refusal('linked-common-storage-changed')
        self.directory.check()


def pointer(raw,base):
    try:text=raw.rstrip(b'\r\n').decode('utf-8')
    except (AttributeError,UnicodeError):raise g.Refusal('linked-pointer-encoding-held') from None
    if not text or '\0' in text or text!=text.strip():raise g.Refusal('linked-pointer-shape-held')
    value=Path(text)
    if not value.is_absolute():value=base/value
    # Pure lexical normalization only. Never resolve/stat/follow a target path.
    return Path(os.path.normpath(value)),not Path(text).is_absolute()


def propose(repo,common,registry,entry,home):
    gitdir_raw=entry.read('gitdir');commondir_raw=entry.read('commondir')
    gitdir,relative_gitdir=pointer(gitdir_raw,entry.path)
    commondir,relative_common=pointer(commondir_raw,entry.path)
    if commondir!=common.directory.path:raise g.Refusal('linked-common-pointer-identity-differs')
    if gitdir.name!='.git':raise g.Refusal('linked-backpointer-is-not-gitfile')
    target=gitdir.parent
    if any(part.casefold() in HELD_NAMES for part in target.parts):raise g.Refusal('linked-excluded-target-held')
    if not target.is_relative_to(home):raise g.Refusal('linked-external-target-needs-owner-classification')
    primaries=[home/'dev'/row[0] for row in s.PROJECTS.values()]
    if any(target==path or target in path.parents for path in primaries):
        raise g.Refusal('linked-primary-or-ancestor-target-held')
    # HEAD/index are metadata facts only; do not read an index or HEAD body to
    # propose identity. Missing index is visible and never implies a clean tree.
    head=entry.state('HEAD',required=True,limit=MAX_POINTER_BYTES)
    index=entry.state('index',limit=128*1024*1024)
    locked=entry.state('locked',limit=MAX_POINTER_BYTES)
    binding={'repository':repo.row['id'],'primary_path':str(repo.path),'primary_identity':repo.identity,
             'common_path':str(common.directory.path),'common_identity':common.directory.identity,
             'common_config_sha256':g.sha(common.config_raw),'common_storage':common.storage,
             'registry_path':str(registry.path),'registry_identity':registry.identity,
             'entry_path':str(entry.path),'entry_identity':entry.identity,
             'target_path':str(target),'target_gitfile_path':str(gitdir),
             'gitdir_sha256':g.sha(gitdir_raw),'commondir_sha256':g.sha(commondir_raw),
             'gitdir_relative':relative_gitdir,'commondir_relative':relative_common,
             'metadata':{'HEAD':head,'index':index,'locked':locked}}
    return {'status':'proposed-uninspected','candidate_sha256':w.digest(binding),'binding_proposal':binding,
            'target_metadata_opened':False,'target_body_opened':False,'source_index_body_read':False,
            'locked_reason_body_read':False,'actual_target_head_or_status_proven':False,
            'explicit_additional_binding_accepted':False}


def one(repo,tool,home):
    common_fd=s.child_directory(repo._fd,('.git',))
    try:
        directory=MetadataDirectory(common_fd,repo.path/'.git');common=CommonMetadata(repo,tool,directory)
        result={'id':repo.row['id'],'available':True,'origin_verified':True,'common_config_sha256':g.sha(common.config_raw),
                'common_storage':common.storage,'registry_present':False,'candidates':[],
                'all_discovered_targets_inspected':False,'actual_target_status_proven':False}
        try:
            with directory.child('worktrees') as registry:
                result['registry_present']=True;deadline=time.monotonic()+MAX_REGISTRY_SECONDS
                result['registry_identity']=registry.identity
                names=sorted(os.listdir(registry.fd))
                if len(names)>MAX_REGISTRY_ENTRIES:raise g.Refusal('linked-registry-entry-bound')
                registry.membership=tuple(names)
                for name in names:
                    if time.monotonic()>=deadline:raise g.Refusal('linked-registry-time-bound')
                    if name.casefold() in HELD_NAMES:
                        result['candidates'].append({'status':'held-uninspected','registry_name_sha256':g.sha(name.encode('utf-8','surrogateescape')),
                          'reason':'excluded-registry-name-held-before-entry-access','target_metadata_opened':False,'target_body_opened':False})
                        continue
                    try:
                        with registry.child(name) as entry:
                            proposal=propose(repo,common,registry,entry,home)
                        result['candidates'].append(proposal)
                    except (ValueError,OSError,UnicodeError) as error:
                        result['candidates'].append({'status':'held-uninspected','registry_name_sha256':g.sha(name.encode('utf-8','surrogateescape')),
                          'reason':str(error) if isinstance(error,g.Refusal) else 'linked-entry-metadata-unavailable',
                          'target_metadata_opened':False,'target_body_opened':False})
                registry.check()
                if sorted(os.listdir(registry.fd))!=names:raise g.Refusal('linked-registry-membership-changed')
        except FileNotFoundError:
            # Recheck absence after the source checks below. No target is opened.
            pass
        common.check()
        exists=False
        try:
            info=os.stat('worktrees',dir_fd=directory.fd,follow_symlinks=False);exists=True
            if not stat.S_ISDIR(info.st_mode):raise g.Refusal('linked-registry-type-held')
            if result['registry_present'] and s.identity(info)!=result['registry_identity']:
                raise g.Refusal('linked-registry-final-identity-changed')
        except FileNotFoundError:pass
        if exists!=result['registry_present']:raise g.Refusal('linked-registry-presence-changed')
        result['registered_entry_count']=len(result['candidates'])
        result['proposed_count']=sum(r['status']=='proposed-uninspected' for r in result['candidates'])
        result['held_count']=sum(r['status']=='held-uninspected' for r in result['candidates'])
        return result
    finally:os.close(common_fd)


def inspect(scope,tool):
    rows=[]
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:rows.append(one(repo,tool,scope.home))
        except (ValueError,OSError,UnicodeError) as error:
            rows.append({'id':target['id'],'available':False,'candidates':None,
                         'reason':str(error) if isinstance(error,g.Refusal) else 'linked-common-metadata-unavailable'})
    return {'schema':'personal-portability/personal-linked-registry/v1','source_ref':SOURCE_REF,
            'manifest_sha256':s.MANIFEST_SHA256,'rows':rows,'selected_primary_count':len(rows),
            'new_target_roots_opened':0,'target_status_queries':0,'network_requests':0,'source_or_config_writes':False,
            'Git_process_scope':'qualified --no-includes config parser on stdin only; no actual-root Git commands',
            'new_shared_links':0,'new_model_workers':0,'full_linked_observability_or_doctor_or_native_acceptance':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--repository',action='append');args=parser.parse_args(argv)
    try:
        result=inspect(s.PersonalScope(repositories=s.selected_ids(args.repository)),g.GitTool())
        print(json.dumps(result,sort_keys=True));return 2 if any(not r['available'] for r in result['rows']) else 0
    except (ValueError,OSError,UnicodeError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'linked-scope-or-tool-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
