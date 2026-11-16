"""Bounded personal Git metadata observations; no worktree or remote inspection.

Dependency for the complete personal Dev doctor. This is not an installed doctor,
source acceptance, native qualification, mutation authority or hostile-user sandbox.
Only the exact manifest-selected primary roots are admitted. No arbitrary Git verb,
root/tool override, linked-checkout traversal, worktree status, fetch or service.
Queries use disposable metadata/index copies to keep even split-index timestamp
refreshes away from the source. The audited object store is read in place.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).absolute().parent
SCOPE_SHA256 = 'f00252220fbeb4ff1784af22407354a0e5a60aa645427b8c27eb1412098f1c69'
scope_source = HERE/'personal_scope.py'
if scope_source.is_symlink() or hashlib.sha256(scope_source.read_bytes()).hexdigest() != SCOPE_SHA256:
    raise ValueError('accepted personal scope dependency changed')
sys.path.insert(0, str(HERE))
import personal_scope as scope_module
if Path(scope_module.__file__).absolute() != scope_source:
    raise ValueError('personal scope imported from a different root')

GIT_PATH = Path('/Library/Developer/CommandLineTools/usr/bin/git')
GIT_SHA256 = '5c5d6527325adcf024e229a9eb540cc0bdd21e1e23ce8f125cf3d8b3704e2659'
NOREPLY = '49759187+KleinPerkins@users.noreply.github.com'
TIMEOUT = 4.0
MAX_OUTPUT = 2*1024*1024
MAX_METADATA_ENTRIES = 50000
MAX_METADATA_SECONDS = 4.0
MAX_PRIVATE_BYTES = 256*1024*1024
FLAGS = ('--no-pager', '--no-replace-objects', '--no-lazy-fetch', '--no-optional-locks')
OVERRIDES = ('core.fsmonitor=false', 'core.untrackedCache=false', 'core.hooksPath=/dev/null',
             'core.attributesFile=/dev/null', 'core.excludesFile=/dev/null',
             'protocol.allow=never', 'protocol.file.allow=never', 'protocol.ssh.allow=never',
             'protocol.https.allow=never', 'protocol.http.allow=never',
             'core.askPass=/usr/bin/false', 'maintenance.auto=false', 'gc.auto=0')
COMMANDS = {
    'head': ('rev-parse', '--verify', 'HEAD'),
    'branch': ('symbolic-ref', '--quiet', '--short', 'HEAD'),
    'upstream': ('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'),
    'ahead_behind': ('rev-list', '--left-right', '--count', '@{upstream}...HEAD'),
    'memory_index': ('ls-files', '--cached', '-z', '--', 'agent-learnings.md', 'AGENTS.md'),
}


class Refusal(ValueError):
    """Safe, non-secret-bearing reason code. Never include raw config/stderr."""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clean_environment() -> dict:
    # Preserve HOME when present; suppress Git global/system config explicitly.
    # Never inherit Git overrides, credentials, tracing, agent or proxy variables.
    env = {'HOME': os.environ['HOME']} if 'HOME' in os.environ else {}
    env.update(PATH='/usr/bin:/bin', LC_ALL='C', LANG='C',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_SYSTEM='/dev/null',
               GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0',
               GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
               GIT_ASKPASS='/usr/bin/false', GIT_PROTOCOL_FROM_USER='0',
               GIT_ALLOW_PROTOCOL='', GIT_LITERAL_PATHSPECS='1')
    return env


def bounded_process(argv: list[str], cwd: Path, data: bytes | None = None) -> tuple[int, bytes, bytes]:
    if data is not None and len(data) > scope_module.MAX_FILE_BYTES:
        raise Refusal('configuration-input-too-large')
    process = subprocess.Popen(argv, cwd=cwd, env=clean_environment(),
                               stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    deadline = time.monotonic()+TIMEOUT
    captured = {'stdout':bytearray(), 'stderr':bytearray()}
    selector = selectors.DefaultSelector()
    sent = 0
    try:
        for stream, name in ((process.stdout,'stdout'),(process.stderr,'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        if data:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
        elif process.stdin:
            process.stdin.close()
        while selector.get_map():
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise Refusal('Git-probe-timeout')
            for key, _ in selector.select(min(remaining,0.1)):
                if key.data == 'stdin':
                    try:
                        sent += os.write(key.fd, data[sent:sent+65536])
                    except BrokenPipeError:
                        sent = len(data)
                    if sent == len(data):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fd,65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    else:
                        captured[key.data].extend(chunk)
                        if len(captured[key.data]) > MAX_OUTPUT:
                            raise Refusal('Git-probe-output-limit')
        try:
            code = process.wait(timeout=max(0.001,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Refusal('Git-probe-timeout') from None
        return code,bytes(captured['stdout']),bytes(captured['stderr'])
    finally:
        if process.poll() is None or selector.get_map():
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.wait(timeout=2)
        selector.close()
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream and not stream.closed:stream.close()


class GitTool:
    def __init__(self):
        self.path = GIT_PATH
        self.digest = GIT_SHA256
        self.assert_current()

    def assert_current(self):
        for path in [*reversed(self.path.parents),self.path.parent]:
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise Refusal('qualified-Git-path-changed')
        info=self.path.lstat()
        # Root-owned Git executables can legitimately share built-in aliases.
        # The fixed path, exact bytes and root ownership define this tool binding.
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or not info.st_mode & stat.S_IXUSR
                or sha(self.path.read_bytes()) != self.digest):
            raise Refusal('qualified-Git-binary-changed')

    def parse_config(self, raw: bytes) -> dict[str,list[str | None]]:
        self.assert_current()
        # --file - and --no-includes parse only stdin. A new empty private cwd
        # prevents discovery of a target or ancestor Git repository.
        temp_parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        with tempfile.TemporaryDirectory(prefix='personal-Git-config-',dir=temp_parent) as temporary:
            code,out,_=bounded_process([str(self.path),'--no-pager','config','--file','-',
                                        '--no-includes','--null','--list'],Path(temporary),raw)
        self.assert_current()
        if code != 0:
            raise Refusal('local-Git-config-parse-refused')
        result={}
        try:
            if out and not out.endswith(b'\0'):
                raise ValueError()
            for record in out.split(b'\0')[:-1]:
                key,separator,value=record.partition(b'\n')
                key=key.decode('utf-8')
                if not key or any(ord(c)<32 for c in key):raise ValueError()
                result.setdefault(key,[]).append(value.decode('utf-8') if separator else None)
        except (UnicodeError,ValueError):
            raise Refusal('local-Git-config-shape-refused') from None
        return result


def last(config: dict, key: str, default=None):
    return config.get(key,[default])[-1]


def git_bool(value, default=False) -> bool:
    if value is None:return True
    if type(value) is not str:raise Refusal('unsupported-Git-boolean')
    if value.lower() in {'true','yes','on','1'}:return True
    if value.lower() in {'false','no','off','0',''}:return False
    raise Refusal('unsupported-Git-boolean')


def personal_remote(value: str | None, expected: str) -> bool:
    if type(value) is not str:return False
    return value in {f'git@github.com:{expected}.git',f'https://github.com/{expected}',
                     f'https://github.com/{expected}.git',f'ssh://git@github.com/{expected}.git'}


def validate_config(config: dict, expected: str, root: Path) -> None:
    if config.get('remote.origin.url') is None or len(config['remote.origin.url']) != 1 or not personal_remote(config['remote.origin.url'][0],expected):
        raise Refusal('expected-personal-origin-not-established')
    for key,values in config.items():
        if key.startswith('include.') or key.startswith('includeif.'):
            raise Refusal('external-config-include-held')
        if key.startswith('filter.'):
            raise Refusal('configured-content-filter-held')
        if key.startswith('url.') and key.endswith(('.insteadof','.pushinsteadof')):
            raise Refusal('unclassified-remote-rewrite-held')
        if key == 'core.alternaterefscommand':
            raise Refusal('configured-alternate-refs-command-held')
        if key.startswith('remote.') and key.endswith(('.url','.pushurl')):
            if not all(any(personal_remote(value,identifier) for identifier in scope_module.PROJECTS) for value in values):
                raise Refusal('unclassified-remote-identity-held')
        if key == 'extensions.partialclone' or key.startswith('remote.') and key.endswith('.promisor') and any(git_bool(v) for v in values):
            raise Refusal('partial-clone-metadata-held')
        if key.startswith('extensions.') and key not in {'extensions.worktreeconfig','extensions.objectformat','extensions.refstorage'}:
            raise Refusal('unclassified-Git-extension-held')
    if last(config,'extensions.objectformat','sha1') != 'sha1' or last(config,'extensions.refstorage','files') != 'files':
        raise Refusal('unclassified-Git-storage-format-held')
    if last(config,'core.repositoryformatversion','0') not in {'0','1'}:
        raise Refusal('unclassified-Git-repository-format-held')
    if git_bool(last(config,'core.bare','false')):
        raise Refusal('expected-primary-checkout-is-bare')
    worktree=last(config,'core.worktree')
    if worktree is not None:
        candidate=Path(worktree)
        if not candidate.is_absolute():candidate=root/'.git'/candidate
        if os.path.abspath(candidate) != str(root):
            raise Refusal('configured-worktree-outside-selected-root')


def file_fact(repo, relative: str, *, required=False, limit=128*1024*1024) -> dict | None:
    parts=scope_module.relative_parts(relative)
    try:parent=scope_module.child_directory(repo._fd,parts[:-1])
    except FileNotFoundError:
        if required:raise Refusal('required-Git-metadata-missing') from None
        return None
    try:
        try:info=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:
            if required:raise Refusal('required-Git-metadata-missing') from None
            return None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > limit):
            raise Refusal('Git-metadata-file-type-or-ownership-held')
        return {**scope_module.identity(info),'size':info.st_size,'nlink':info.st_nlink,
                'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}
    finally:os.close(parent)


def storage_inventory(repo) -> dict:
    rows=[];deadline=time.monotonic()+MAX_METADATA_SECONDS
    for relative in ('.git/objects','.git/refs'):
        try:root=scope_module.child_directory(repo._fd,scope_module.relative_parts(relative))
        except FileNotFoundError:
            if relative=='.git/objects':raise Refusal('required-Git-storage-missing') from None
            rows.append({'path':relative,'kind':'absent'});continue
        rows.append({'path':relative,'kind':'directory',**scope_module.identity(os.fstat(root))})
        pending=[(root,relative)]
        try:
            while pending:
                fd,prefix=pending.pop()
                try:
                    with os.scandir(fd) as entries:
                        for entry in entries:
                            if time.monotonic()>=deadline or len(rows)>=MAX_METADATA_ENTRIES:
                                raise Refusal('Git-storage-inventory-bound')
                            path=prefix+'/'+entry.name
                            if path in {'.git/objects/info/alternates','.git/objects/info/http-alternates'}:
                                raise Refusal('external-object-alternates-held')
                            info=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                            if info.st_uid!=os.getuid() or stat.S_ISLNK(info.st_mode):
                                raise Refusal('Git-storage-link-or-ownership-held')
                            if stat.S_ISDIR(info.st_mode):
                                child=os.open(entry.name,scope_module.DIR_FLAGS,dir_fd=fd)
                                if scope_module.identity(os.fstat(child))!=scope_module.identity(info):
                                    os.close(child);raise Refusal('Git-storage-directory-changed')
                                pending.append((child,path))
                                rows.append({'path':path,'kind':'directory',**scope_module.identity(info)})
                            elif stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                                rows.append({'path':path,'kind':'file',**scope_module.identity(info),
                                             'size':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns})
                            else:raise Refusal('Git-storage-special-or-shared-file-held')
                finally:os.close(fd)
        finally:
            for fd,_ in pending:os.close(fd)
    return {'entries':len(rows),'sha256':sha(json.dumps(sorted(rows,key=lambda r:r['path']),sort_keys=True,separators=(',',':')).encode())}


class PersonalGit:
    def __init__(self, repo, tool: GitTool):
        self.repo,self.tool=repo,tool
        self.config_fact=file_fact(repo,'.git/config',required=True,limit=scope_module.MAX_FILE_BYTES)
        self.config_raw=repo.read_file('.git/config')
        if file_fact(repo,'.git/config',required=True)!=self.config_fact:
            raise Refusal('local-config-changed-during-observation')
        self.base_config=tool.parse_config(self.config_raw)
        # The common origin is established before reading any overlay/other Git
        # metadata. Includes are never expanded by the stdin parser.
        validate_config(self.base_config,repo.row['id'],repo.path)
        self.worktree_raw=None
        self.worktree_fact=None
        self.overlay_config={}
        self.config={k:list(v) for k,v in self.base_config.items()}
        if git_bool(last(self.base_config,'extensions.worktreeconfig','false')):
            self.worktree_fact=file_fact(repo,'.git/config.worktree',limit=scope_module.MAX_FILE_BYTES)
            if self.worktree_fact is not None:self.worktree_raw=repo.read_file('.git/config.worktree')
            if file_fact(repo,'.git/config.worktree')!=self.worktree_fact:
                raise Refusal('worktree-config-changed-during-observation')
            if self.worktree_raw is not None:
                self.overlay_config=tool.parse_config(self.worktree_raw)
                for key,values in self.overlay_config.items():
                    self.config.setdefault(key,[]).extend(values)
                validate_config(self.config,repo.row['id'],repo.path)
        for pointer in ('.git/commondir','.git/gitdir','.git/info/grafts'):
            if file_fact(repo,pointer) is not None:
                raise Refusal('non-primary-or-rewritten-Git-metadata-held')
        self.files={name:file_fact(repo,name,required=name in {'.git/HEAD','.git/index'})
                    for name in ('.git/HEAD','.git/index','.git/packed-refs','.git/shallow')}
        self.storage=storage_inventory(repo)
        self.shared_indexes=self.shared_index_facts()
        self._active_gitdir=None
        self.probes=[]

    def shared_index_facts(self):
        fd=scope_module.child_directory(self.repo._fd,('.git',))
        try:
            with os.scandir(fd) as entries:names=[e.name for e in entries if e.name.startswith('sharedindex.')]
            if len(names)>1024:raise Refusal('shared-index-inventory-bound')
            result={}
            for name in names:
                if not re.fullmatch(r'sharedindex\.[0-9a-f]{40}',name):raise Refusal('shared-index-name-held')
                result[name]=file_fact(self.repo,'.git/'+name,required=True)
            return result
        finally:os.close(fd)

    def copy_metadata_file(self, relative, destination, budget):
        values=scope_module.relative_parts(relative)
        parent=scope_module.child_directory(self.repo._fd,values[:-1])
        fd=None
        try:
            before=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid()
                    or before.st_nlink!=1 or before.st_size>128*1024*1024):
                raise Refusal('private-metadata-source-held')
            budget['bytes']+=before.st_size
            if budget['bytes']>MAX_PRIVATE_BYTES or time.monotonic()>=budget['deadline']:
                raise Refusal('private-metadata-copy-bound')
            fd=os.open(values[-1],scope_module.FILE_FLAGS,dir_fd=parent)
            fields=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
            if fields(os.fstat(fd))!=fields(before):raise Refusal('private-metadata-source-changed')
            destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            target=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(target,'wb') as output:
                remaining=before.st_size
                while remaining:
                    if time.monotonic()>=budget['deadline']:raise Refusal('private-metadata-copy-bound')
                    block=os.read(fd,min(remaining,65536))
                    if not block:raise Refusal('private-metadata-source-changed')
                    output.write(block);remaining-=len(block)
            # Git compares the index timestamp with cached worktree stat times
            # to detect racy same-stat content edits. A freshly dated snapshot
            # can suppress that comparison and falsely report clean. Preserve
            # source timestamps only on the disposable copy, never the source.
            os.utime(destination,ns=(before.st_atime_ns,before.st_mtime_ns),follow_symlinks=False)
            if (fields(os.fstat(fd))!=fields(before)
                    or fields(os.stat(values[-1],dir_fd=parent,follow_symlinks=False))!=fields(before)):
                raise Refusal('private-metadata-source-changed')
        finally:
            if fd is not None:os.close(fd)
            os.close(parent)

    def private_config(self) -> bytes:
        def quoted(value):
            if value is None:return 'true'
            if any(ord(c)<32 and c not in '\n\t\b' for c in value):raise Refusal('private-config-scalar-held')
            return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\t','\\t').replace('\b','\\b')+'"'
        lines=['[advice]','sparseIndexExpanded = false','[core]','repositoryformatversion = 0','bare = false','logallrefupdates = false']
        # Preserve data/normalization policy; never copy credentials, includes,
        # hooks, executable helpers or arbitrary configuration into the view.
        core={'filemode':'true','ignorecase':'false','precomposeunicode':'false','symlinks':'true',
              'sparsecheckout':'false','sparsecheckoutcone':'false','trustctime':'true',
              'ignorestat':'false','checkstat':'default','autocrlf':'false','safecrlf':'false'}
        for key,default in core.items():lines.append(key+' = '+quoted(last(self.config,'core.'+key,default)))
        for key in ('eol','checkroundtripencoding','bigfilethreshold'):
            if 'core.'+key in self.config:lines.append(key+' = '+quoted(last(self.config,'core.'+key)))
        for section,keys in [('index',['sparse']),('status',['renames']),('diff',['renames'])]:
            selected=[key for key in keys if section+'.'+key in self.config]
            if selected:
                lines.append('['+section+']')
                for key in selected:lines.append(key+' = '+quoted(last(self.config,section+'.'+key)))
        grouped={}
        for key,values in self.config.items():
            match=re.fullmatch(r'(branch|remote)\.(.+)\.([a-z][a-z0-9-]*)',key)
            if not match:continue
            section,name,leaf=match.groups()
            allowed={'branch':{'remote','merge'},'remote':{'url','pushurl','fetch'}}
            if leaf in allowed[section]:grouped.setdefault((section,name),[]).append((leaf,values))
        for (section,name),items in sorted(grouped.items()):
            lines.append('['+section+' '+quoted(name)+']')
            for key,values in items:
                for value in values:lines.append(key+' = '+quoted(value))
        return ('\n'.join(lines)+'\n').encode()

    @contextmanager
    def private_gitdir(self, *, worktree_controls=False):
        if self._active_gitdir is not None:
            yield self._active_gitdir;return
        self.unchanged_config()
        if self.shared_index_facts()!=self.shared_indexes:raise Refusal('shared-index-changed')
        parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
        with tempfile.TemporaryDirectory(prefix='personal-Git-view-',dir=parent) as temporary:
            view=Path(temporary)
            budget={'bytes':0,'deadline':time.monotonic()+MAX_METADATA_SECONDS}
            for relative,state in self.files.items():
                if state is not None:self.copy_metadata_file(relative,view/relative.removeprefix('.git/'),budget)
            for name in self.shared_indexes:self.copy_metadata_file('.git/'+name,view/name,budget)
            # Sparse-index expansion can write trees and refresh timestamps of
            # existing loose objects, including alternates, despite optional
            # locks being disabled. Copy the already audited personal store
            # into the same bounded private snapshot instead of linking it.
            for subtree in ('refs','objects'):
                try:root=scope_module.child_directory(self.repo._fd,('.git',subtree))
                except FileNotFoundError:
                    if subtree=='objects':raise Refusal('required-Git-storage-missing') from None
                    root=None
                (view/subtree).mkdir(mode=0o700)
                pending=[] if root is None else [(root,subtree)]
                count=0
                try:
                    while pending:
                        fd,prefix=pending.pop()
                        try:
                            (view/prefix).mkdir(mode=0o700,parents=True,exist_ok=True)
                            with os.scandir(fd) as entries:
                                for entry in entries:
                                    count+=1
                                    if count>MAX_METADATA_ENTRIES or time.monotonic()>=budget['deadline']:
                                        raise Refusal('private-storage-inventory-bound')
                                    info=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                                    if stat.S_ISDIR(info.st_mode):
                                        child=os.open(entry.name,scope_module.DIR_FLAGS,dir_fd=fd)
                                        pending.append((child,prefix+'/'+entry.name))
                                    elif stat.S_ISREG(info.st_mode):self.copy_metadata_file('.git/'+prefix+'/'+entry.name,view/prefix/entry.name,budget)
                                    else:raise Refusal('private-storage-source-held')
                        finally:os.close(fd)
                finally:
                    for fd,_ in pending:os.close(fd)
            (view/'config').write_bytes(self.private_config());(view/'config').chmod(0o600)
            extra={}
            if worktree_controls:
                for relative in ('.git/info/exclude','.git/info/attributes','.git/info/sparse-checkout'):
                    state=file_fact(self.repo,relative);extra[relative]=state
                    if state is not None:self.copy_metadata_file(relative,view/relative.removeprefix('.git/'),budget)
            self._active_gitdir=view
            try:
                yield view
                if any(file_fact(self.repo,path)!=state for path,state in extra.items()):raise Refusal('worktree-Git-control-changed')
                if self.shared_index_facts()!=self.shared_indexes:raise Refusal('shared-index-changed')
            finally:self._active_gitdir=None

    def unchanged_config(self):
        if (file_fact(self.repo,'.git/config',required=True)!=self.config_fact
                or self.repo.read_file('.git/config')!=self.config_raw
                or file_fact(self.repo,'.git/config',required=True)!=self.config_fact):
            raise Refusal('local-config-changed-during-observation')
        if git_bool(last(self.base_config,'extensions.worktreeconfig','false')):
            fact=file_fact(self.repo,'.git/config.worktree')
            current=self.repo.read_file('.git/config.worktree') if fact is not None else None
            if (fact!=self.worktree_fact or current!=self.worktree_raw
                    or file_fact(self.repo,'.git/config.worktree')!=self.worktree_fact):
                raise Refusal('worktree-config-changed-during-observation')

    def probe(self, name: str, allowed=(0,)) -> tuple[int,bytes]:
        if name not in COMMANDS:raise Refusal('Git-verb-outside-closed-metadata-contract')
        if self._active_gitdir is None:
            with self.private_gitdir():return self.probe(name,allowed)
        self.unchanged_config();self.tool.assert_current()
        args=[str(self.tool.path),*FLAGS]
        for setting in OVERRIDES:args.extend(['-c',setting])
        args.extend(['--git-dir='+str(self._active_gitdir),'--work-tree='+str(self.repo.path),*COMMANDS[name]])
        code,out,err=bounded_process(args,self.repo.path)
        self.tool.assert_current();self.unchanged_config()
        self.probes.append({'name':name,'exit_code':code,'stdout_bytes':len(out),'stderr_bytes':len(err),
                            'stderr_sha256':sha(err) if err else None})
        if code not in allowed:raise Refusal('metadata-Git-command-refused-'+name)
        return code,out

    def finish(self):
        self.unchanged_config()
        current={name:file_fact(self.repo,name,required=name in {'.git/HEAD','.git/index'}) for name in self.files}
        if current!=self.files or storage_inventory(self.repo)!=self.storage:
            raise Refusal('Git-metadata-changed-during-observation')
        if self.shared_index_facts()!=self.shared_indexes:raise Refusal('shared-index-changed')

    def observe(self) -> dict:
        with self.private_gitdir():return self.observe_in_view()

    def observe_in_view(self) -> dict:
        _,raw_head=self.probe('head')
        try:head=raw_head.strip().decode('ascii')
        except UnicodeError:raise Refusal('invalid-HEAD-observation') from None
        if not re.fullmatch('[0-9a-f]{40}',head):raise Refusal('invalid-HEAD-observation')
        branch_code,raw_branch=self.probe('branch',(0,1))
        branch=None if branch_code==1 else raw_branch.strip().decode('utf-8')
        code,raw_upstream=self.probe('upstream',(0,1,128))
        upstream=None if code else raw_upstream.strip().decode('utf-8')
        ahead=behind=None
        if upstream:
            _,counts=self.probe('ahead_behind')
            if not re.fullmatch(rb'\d+\s+\d+\s*',counts):raise Refusal('invalid-sync-count-observation')
            behind,ahead=map(int,counts.split())
        _,tracked=self.probe('memory_index')
        if tracked and not tracked.endswith(b'\0'):raise Refusal('invalid-index-name-observation')
        names=tracked.split(b'\0')[:-1]
        if any(name not in {b'agent-learnings.md',b'AGENTS.md'} for name in names):raise Refusal('index-selection-escaped')
        self.finish()
        return {'id':self.repo.row['id'],'relative_path':self.repo.row['path'],
                'expected_personal_origin_verified':True,
                'origin_resolution_scope':'local configuration and worktree overlay; global/system config disabled',
                'config_sha256':sha(self.config_raw),
                'worktree_config_sha256':sha(self.worktree_raw) if self.worktree_raw is not None else None,
                'local_email_canonical':last(self.base_config,'user.email')==NOREPLY,
                'effective_email_canonical':last(self.config,'user.email')==NOREPLY,
                'local_identity_canonical':last(self.base_config,'user.email')==NOREPLY and last(self.base_config,'user.name')=='KleinPerkins',
                'effective_personal_identity_canonical':last(self.config,'user.email')==NOREPLY and last(self.config,'user.name')=='KleinPerkins',
                'effective_identity_scope':'worktree' if any(k in self.overlay_config for k in ['user.name','user.email']) else 'local',
                'head':head,'expected_pin':self.repo.row['revision'],'pin_matches':head==self.repo.row['revision'],
                'branch':branch,'detached':branch is None,'upstream':upstream,'ahead':ahead,'behind':behind,
                'sync_evidence':'local tracking refs only; no fetch or live remote parity',
                'tracked_agent_learnings':b'agent-learnings.md' in names,'tracked_AGENTS':b'AGENTS.md' in names,
                'generated_memory_contents_read':False,'worktree_status_proven':False,
                'Git_storage':self.storage,'probes':self.probes,'remote_requests':0,'writes':False,
                'doctor_or_native_qualification_proven':False}


def inspect(scope,tool) -> dict:
    rows=[]
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:rows.append(PersonalGit(repo,tool).observe())
        except (Refusal,OSError,UnicodeError,ValueError) as error:
            reason=str(error) if isinstance(error,Refusal) else 'scoped-metadata-unavailable'
            rows.append({'id':target['id'],'status':'unavailable','reason':reason,
                         'doctor_or_native_qualification_proven':False})
    return {'schema':'personal-portability/personal-Git-metadata/v1',
            'manifest_sha256':scope_module.MANIFEST_SHA256,'qualified_Git_sha256':tool.digest,
            'rows':rows,'target_count':len(rows),'worktree_or_linked_checkout_traversal':False,
            'network_requests':0,'source_or_config_writes':False,'shared_discovery_changed':False,
            'doctor_or_native_qualification_proven':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect'])
    parser.add_argument('--repository',action='append')
    args=parser.parse_args(argv)
    try:
        scope=scope_module.PersonalScope(repositories=args.repository)
        result=inspect(scope,GitTool())
        print(json.dumps(result,sort_keys=True))
        return 2 if any(row.get('status')=='unavailable' for row in result['rows']) else 0
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,Refusal) else 'scope-or-tool-unavailable'}))
        return 2


if __name__=='__main__':raise SystemExit(main())
