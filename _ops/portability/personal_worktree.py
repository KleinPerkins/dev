"""Scoped primary worktree observations for the personal Dev doctor projection.

Uses Git's repository-local ignore rules after descriptor checks. No mutation,
remote request, nested checkout/submodule traversal, global profile read, native
publication or full doctor acceptance. Later visible edits refuse; this is not a
sandbox against a hostile same-user writer.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import unicodedata

HERE=Path(__file__).absolute().parent
GIT_MODULE_SHA256='eb6eba70b21e0c8c0650b0e940a6290cb500e9bfdb2b638a8e9203f7ceef1d58'
git_source=HERE/'personal_git.py'
if git_source.is_symlink() or hashlib.sha256(git_source.read_bytes()).hexdigest()!=GIT_MODULE_SHA256:
    raise ValueError('accepted personal Git dependency changed')
sys.path.insert(0,str(HERE))
import personal_git as g
if Path(g.__file__).absolute()!=git_source:raise ValueError('personal Git imported from another root')
s=g.scope_module

MAX_TREE_ENTRIES=50000
MAX_TREE_SECONDS=12.0
MAX_PROBES=1024
BATCH=128
COMMANDS={
    'index':('ls-files','--stage','-z'),
    'ignore':('check-ignore','--no-index','-z','--stdin'),
    'status':('status','--porcelain=v1','-z','--untracked-files=normal','--ignore-submodules=all'),
}
HELD_NAMES={'affirm','chaos-scheduler'}


def parts(path: str, *, trailing=False) -> tuple[str,...]:
    if trailing and path.endswith('/'):path=path[:-1]
    if not path or path.startswith('/') or '\0' in path:raise g.Refusal('worktree-relative-path-held')
    values=tuple(path.split('/'))
    if any(v in {'','.','..'} for v in values):raise g.Refusal('worktree-relative-path-held')
    return values


def fact(info) -> dict:
    return {**s.identity(info),'type':stat.S_IFMT(info.st_mode),'nlink':info.st_nlink,
            'size':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}


def digest(value) -> str:
    return g.sha(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode())


def index_paths(raw: bytes) -> dict[str,set[str]]:
    if raw and not raw.endswith(b'\0'):raise g.Refusal('worktree-index-shape-held')
    result={}
    for record in raw.split(b'\0')[:-1]:
        meta,separator,path=record.partition(b'\t')
        if not separator:raise g.Refusal('worktree-index-shape-held')
        match=re.fullmatch(rb'(100644|100755|120000|160000) ([0-9a-f]{40}) ([0-3])',meta)
        if not match:raise g.Refusal('worktree-index-shape-held')
        name=path.decode('utf-8','surrogateescape');values=parts(name)
        if any(v.casefold()=='.git' for v in values):raise g.Refusal('worktree-index-path-held')
        result.setdefault(name,set()).add(match[1].decode())
    return result


def porcelain(raw: bytes) -> dict:
    if raw and not raw.endswith(b'\0'):raise g.Refusal('worktree-status-shape-held')
    records=raw.split(b'\0')[:-1];cursor=0;codes=Counter();paths=[]
    while cursor<len(records):
        record=records[cursor];cursor+=1
        if len(record)<4 or record[2:3]!=b' ':raise g.Refusal('worktree-status-shape-held')
        code=record[:2].decode('ascii')
        if any(c not in ' MADRCUT?!' for c in code) or code=='  ':raise g.Refusal('worktree-status-shape-held')
        name=record[3:].decode('utf-8','surrogateescape');parts(name,trailing=True)
        paths.append(name);codes[code]+=1
        if 'R' in code or 'C' in code:
            if cursor>=len(records):raise g.Refusal('worktree-status-rename-held')
            old=records[cursor].decode('utf-8','surrogateescape');cursor+=1;parts(old);paths.append(old)
    return {'clean_under_personal_policy':not records,'reported_change_items':sum(codes.values()),
            'reported_untracked_items':codes.get('??',0),'codes':dict(codes),
            'reported_path_names_sha256':digest(paths)}


class PersonalWorktree:
    def __init__(self, repo, tool):
        self.repo,self.tool=repo,tool
        self.git=g.PersonalGit(repo,tool)
        self.probes=[];self.controls={};self.tree_ready=False;self.ignore_ready=False
        self.exclude_path='/dev/null'
        self.shared_indexes=self.shared_index_facts()

    def shared_index_facts(self):
        fd=s.child_directory(self.repo._fd,('.git',))
        try:
            with os.scandir(fd) as entries:
                names=[e.name for e in entries if e.name.startswith('sharedindex.')]
            if len(names)>1024:raise g.Refusal('shared-index-inventory-bound')
            result={}
            for name in names:
                if not re.fullmatch(r'sharedindex\.[0-9a-f]{40}',name):raise g.Refusal('shared-index-name-held')
                result[name]=g.file_fact(self.repo,'.git/'+name,required=True)
            return result
        finally:os.close(fd)

    def unchanged(self):
        self.git.unchanged_config()
        if self.shared_index_facts()!=self.shared_indexes:raise g.Refusal('shared-index-changed')

    def run(self, name, data=None):
        if name not in COMMANDS:raise g.Refusal('worktree-verb-held')
        if name=='status' and not self.tree_ready:raise g.Refusal('worktree-status-needs-fence')
        if name=='ignore' and not self.ignore_ready:raise g.Refusal('worktree-ignore-needs-controls')
        if self.git._active_gitdir is None:raise g.Refusal('worktree-private-metadata-view-required')
        if len(self.probes)>=MAX_PROBES:raise g.Refusal('worktree-process-bound')
        self.unchanged();self.recheck_controls();self.tool.assert_current()
        argv=[str(self.tool.path),*g.FLAGS]
        # check-ignore consumes literal pathnames rather than pathspec magic.
        # A fixed negative global flag overrides inherited literal-pathspecs=1;
        # stdin names are prefixed ./ and never have a trailing directory slash.
        if name=='ignore':argv.append('--no-literal-pathspecs')
        for value in g.OVERRIDES:argv.extend(['-c',value])
        argv.extend(['-c','core.excludesFile='+self.exclude_path,
                     '--git-dir='+str(self.git._active_gitdir),'--work-tree='+str(self.repo.path),*COMMANDS[name]])
        code,out,err=g.bounded_process(argv,self.repo.path,data)
        self.tool.assert_current();self.unchanged();self.recheck_controls()
        self.probes.append({'name':name,'exit_code':code,'stdout_bytes':len(out),
                            'stderr_bytes':len(err),'stderr_sha256':g.sha(err) if err else None})
        if code not in ((0,1) if name=='ignore' else (0,)) or err:
            raise g.Refusal('scoped-worktree-command-unavailable-'+name)
        return out

    def control(self, relative, *, optional=True):
        values=parts(relative)
        if any(v.casefold()=='agent-learnings.md' for v in values):
            raise g.Refusal('generated-memory-control-pointer-held')
        try:parent=s.child_directory(self.repo._fd,values[:-1])
        except FileNotFoundError:
            if not optional:raise g.Refusal('worktree-control-missing') from None
            result={'kind':'absent'};self.controls[relative]=result;return None
        try:
            try:info=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:
                if not optional:raise g.Refusal('worktree-control-missing') from None
                self.controls[relative]={'kind':'absent'};return None
            if not stat.S_ISREG(info.st_mode):raise g.Refusal('worktree-control-alias-or-type-held')
            data=s.read_regular(parent,values[-1])
            current=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            if fact(current)!=fact(info):raise g.Refusal('worktree-control-changed')
            self.controls[relative]={'kind':'file',**fact(info),'sha256':g.sha(data),
                                     'parent_identity':s.identity(os.fstat(parent))}
            return data
        finally:os.close(parent)

    def recheck_controls(self):
        for relative,expected in list(self.controls.items()):
            self.control(relative)
            if self.controls[relative]!=expected:raise g.Refusal('worktree-control-changed')

    def configure_ignore(self, temporary):
        value=g.last(self.git.config,'core.excludesfile')
        if 'core.excludesfile' in self.git.config and value is None:
            raise g.Refusal('invalid-local-excludes-setting')
        if value not in (None,'','/dev/null'):
            if value.startswith(('~','%(')):raise g.Refusal('local-excludes-file-outside-personal-root')
            candidate=Path(value)
            if candidate.is_absolute():
                try:relative=str(candidate.relative_to(self.repo.path))
                except ValueError:raise g.Refusal('local-excludes-file-outside-personal-root') from None
            else:relative=value
            values=parts(relative)
            if any(v.casefold() in HELD_NAMES for v in values):raise g.Refusal('local-excludes-file-unclassified')
            self.classify_control_ancestors(relative)
            data=self.control(relative,optional=False)
            p=Path(temporary)/'personal-local-excludes';p.write_bytes(data);p.chmod(0o600)
            self.exclude_path=str(p)
        for name in ('.git/info/exclude','.git/info/attributes','.git/info/sparse-checkout'):
            self.control(name)

    def classify_control_ancestors(self, relative):
        values=parts(relative)
        if any(v.casefold() in HELD_NAMES or v.casefold()=='agent-learnings.md' for v in values):
            raise g.Refusal('worktree-control-pointer-held')
        fd=os.dup(self.repo._fd)
        deadline=time.monotonic()+MAX_TREE_SECONDS
        try:
            for index,name in enumerate(values[:-1]):
                if time.monotonic()>=deadline:raise g.Refusal('worktree-control-parent-bound')
                child=os.open(name,s.DIR_FLAGS,dir_fd=fd)
                os.close(fd);fd=child
                if os.fstat(fd).st_uid!=os.getuid():raise g.Refusal('worktree-control-parent-owner-held')
                # Only the selected primary's top-level .git is classified Git
                # metadata. Other ancestors must not be nested checkout roots.
                if index==0 and name=='.git':continue
                with os.scandir(fd) as entries:
                    for count,entry in enumerate(entries,1):
                        if count>MAX_TREE_ENTRIES or time.monotonic()>=deadline:
                            raise g.Refusal('worktree-control-parent-bound')
                        if entry.name.casefold()=='.git':raise g.Refusal('nested-control-pointer-held')
        finally:os.close(fd)

    def key(self, path):
        if self.precompose:path=unicodedata.normalize('NFC',path)
        return path.casefold() if self.ignorecase else path

    def classify_index(self, raw):
        self.indexed=index_paths(raw)
        self.ignorecase=g.git_bool(g.last(self.git.config,'core.ignorecase','false'))
        self.precompose=g.git_bool(g.last(self.git.config,'core.precomposeunicode','false'))
        self.tracked={};self.directories=set()
        for path,modes in self.indexed.items():
            key=self.key(path)
            if key in self.tracked:raise g.Refusal('worktree-index-normalization-ambiguous')
            self.tracked[key]=modes
            values=parts(path)
            self.directories.update(self.key('/'.join(values[:i])) for i in range(1,len(values)))
        if any(parts(path)[-1].casefold()=='agent-learnings.md' for path in self.indexed):
            raise g.Refusal('tracked-generated-memory-status-held')
        if any('160000' in modes for modes in self.indexed.values()):
            raise g.Refusal('unclassified-submodule-status-held')

    def ignored(self, names):
        result=set()
        for offset in range(0,len(names),BATCH):
            batch=names[offset:offset+BATCH]
            mapping={('./'+name).encode('utf-8','surrogateescape'):name for name in batch}
            data=b''.join(name+b'\0' for name in mapping)
            raw=self.run('ignore',data)
            if raw and not raw.endswith(b'\0'):raise g.Refusal('ignore-output-shape-held')
            for name in raw.split(b'\0')[:-1]:
                if name not in mapping:raise g.Refusal('ignore-output-path-escaped')
                result.add(mapping[name])
        return result

    def scan(self):
        self.controls={};self.ignore_ready=False
        self.configure_ignore(self.temporary)
        rows=[];pruned=0;count=0;deadline=time.monotonic()+MAX_TREE_SECONDS
        pending=[(os.dup(self.repo._fd),'')]
        try:
            while pending:
                fd,prefix=pending.pop()
                try:
                    with os.scandir(fd) as iterator:
                        entries=[]
                        for entry in iterator:
                            count+=1
                            if count>MAX_TREE_ENTRIES or time.monotonic()>=deadline:raise g.Refusal('worktree-inventory-bound')
                            entries.append(entry.name)
                    if prefix and any(name.casefold()=='.git' for name in entries):
                        raise g.Refusal('unclassified-nested-checkout-held')
                    self.control((prefix+'/' if prefix else '')+'.gitignore')
                    self.control((prefix+'/' if prefix else '')+'.gitattributes')
                    self.ignore_ready=True
                    slots=[];queries=[]
                    for name in entries:
                        if not prefix and name.casefold()=='.git':continue
                        relative=(prefix+'/' if prefix else '')+name;key=self.key(relative)
                        if name.casefold() in HELD_NAMES and key not in self.directories and key not in self.tracked:
                            raise g.Refusal('unclassified-work-or-protected-name-held')
                        info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                        slots.append((name,relative,key,info))
                        queries.append(relative)
                    ignored=self.ignored(queries)
                    for name,relative,key,info in slots:
                        if stat.S_ISDIR(info.st_mode):
                            if relative in ignored and key not in self.directories:
                                # Ignore contents/mtime; identity/type still detects replacement.
                                rows.append({'path':relative,'kind':'pruned-directory',**s.identity(info)})
                                pruned+=1;continue
                            if info.st_uid!=os.getuid():raise g.Refusal('worktree-directory-owner-held')
                            child=os.open(name,s.DIR_FLAGS,dir_fd=fd)
                            if s.identity(os.fstat(child))!=s.identity(info):os.close(child);raise g.Refusal('worktree-directory-changed')
                            rows.append({'path':relative,'kind':'directory',**fact(info)})
                            pending.append((child,relative))
                        elif stat.S_ISLNK(info.st_mode):
                            if key in self.directories:raise g.Refusal('tracked-parent-symlink-held')
                            if relative in ignored and key not in self.tracked:
                                rows.append({'path':relative,'kind':'ignored-link',**s.identity(info)});continue
                            rows.append({'path':relative,'kind':'link',**fact(info),
                                         'link_text_sha256':g.sha(os.readlink(name,dir_fd=fd).encode('utf-8','surrogateescape'))})
                        elif stat.S_ISREG(info.st_mode):
                            if relative in ignored and key not in self.tracked:
                                rows.append({'path':relative,'kind':'ignored-file',**s.identity(info)});continue
                            if key in self.tracked and (info.st_nlink!=1 or info.st_uid!=os.getuid() or not info.st_mode & stat.S_IRUSR):
                                raise g.Refusal('tracked-file-shared-or-owner-held')
                            rows.append({'path':relative,'kind':'file',**fact(info)})
                        elif relative in ignored and key not in self.tracked:
                            rows.append({'path':relative,'kind':'ignored-special',**s.identity(info)})
                        else:raise g.Refusal('unclassified-special-worktree-file-held')
                finally:os.close(fd)
        finally:
            for fd,_ in pending:os.close(fd)
        self.recheck_controls();self.unchanged()
        return {'entries':count,'ignored_directories_pruned':pruned,
                'tree_sha256':digest(sorted(rows,key=lambda r:r['path'])),
                'controls_sha256':digest(self.controls)}

    def observe(self):
        with self.git.private_gitdir(worktree_controls=True):return self.observe_in_view()

    def observe_in_view(self):
        metadata=self.git.observe()
        self.classify_index(self.run('index'))
        temp_parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        with tempfile.TemporaryDirectory(prefix='personal-worktree-',dir=temp_parent) as temporary:
            self.temporary=temporary
            before=self.scan();self.tree_ready=True
            result=porcelain(self.run('status'))
            self.tree_ready=False
            after=self.scan()
            if before!=after:raise g.Refusal('worktree-changed-during-observation')
            self.git.finish();self.unchanged()
        return {**metadata,**result,'worktree_status_proven':True,'worktree_fence':after,
                'tracked_index_paths':len(self.indexed),'worktree_probes':self.probes,
                'ignore_policy':'repository .gitignore, info/exclude and classified repository-local core.excludesFile; no global/system config or implicit global excludes',
                'nested_checkouts_or_submodules_inspected':False,'generated_memory_contents_read':False,
                'source_or_config_writes':False,'native_or_complete_doctor_qualified':False}


def inspect(scope,tool):
    rows=[]
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:rows.append(PersonalWorktree(repo,tool).observe())
        except (ValueError,OSError,UnicodeError) as error:
            rows.append({'id':target['id'],'status':'unavailable','reason':str(error) if isinstance(error,g.Refusal) else 'scoped-worktree-unavailable',
                         'worktree_status_proven':False,'native_or_complete_doctor_qualified':False})
    return {'schema':'personal-portability/personal-worktree/v1','rows':rows,'target_count':len(rows),
            'network_requests':0,'source_or_config_writes':False,'new_shared_links':0,'new_workers':0,
            'complete_doctor_or_native_qualification':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect'])
    parser.add_argument('--repository',action='append')
    args=parser.parse_args(argv)
    try:
        scope=s.PersonalScope(repositories=args.repository)
        result=inspect(scope,g.GitTool());print(json.dumps(result,sort_keys=True))
        return 2 if any(not row['worktree_status_proven'] for row in result['rows']) else 0
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'scope-or-tool-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
