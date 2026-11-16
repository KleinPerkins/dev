"""Scoped hook and memory observations for the personal Dev doctor projection.

Canonical doctor verdicts, not hook execution, generated-memory body reads,
installation, complete doctor/native acceptance or hostile-writer protection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

HERE=Path(__file__).absolute().parent
WORKTREE_SHA256='c1c7dc8e0be221e9cbc492d4359377e0141931ea90bd26bc4a12bad34069d00f'
source=HERE/'personal_worktree.py'
if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=WORKTREE_SHA256:
    raise ValueError('accepted personal worktree dependency changed')
sys.path.insert(0,str(HERE))
import personal_worktree as w
if Path(w.__file__).absolute()!=source:raise ValueError('personal worktree imported from another root')
g,s=w.g,w.s
GUARD_MARKER=b'managed-by: KleinPerkins/dev identity-guard'
REGISTRATION_SOURCE_REF='9073a1d5112c2ebbe4b27f81fca83a51f00bc474'
REGISTRATION_SOURCE_BLOB='b7b4b178fb9b5b6faa1d6fe987f19ef501dffb6b'
REGISTRATION_SHA256='5c0f9780cc6a2f7e198e563e2afe96eb9e7e7e78a37731038b0a5d80897b0069'
LEVELS=('OK','ADVISORY','DRIFT','VIOLATION')


def verdict(*values):
    return max(values,key=LEVELS.index)


def hook_path(value, root):
    if value is None:raise g.Refusal('invalid-hook-path-setting')
    if not isinstance(value,str) or any(ord(c)<32 or ord(c)==127 for c in value):
        raise g.Refusal('invalid-hook-path-setting')
    if value.startswith(('~','%(')):raise g.Refusal('hook-path-outside-selected-root')
    if '..' in value.split('/'):raise g.Refusal('hook-path-outside-selected-root')
    if value.startswith('/'):
        try:value=str(Path(value).relative_to(root))
        except ValueError:raise g.Refusal('hook-path-outside-selected-root') from None
    parts=tuple(part for part in value.split('/') if part not in {'','.'})
    if any(v.casefold() in w.HELD_NAMES or v.casefold()=='agent-learnings.md' for v in parts):
        raise g.Refusal('hook-path-unclassified')
    return '/'.join(parts)


class Reader:
    """Only bounded owned unshared regular controls; never generated memory."""
    def __init__(self, tree):
        self.tree,self.repo=tree,tree.repo
        self.evidence={}

    def read(self, relative):
        values=w.parts(relative)
        if any(v.casefold() in w.HELD_NAMES or v.casefold()=='agent-learnings.md' for v in values):
            raise g.Refusal('control-path-unclassified')
        try:
            self.tree.classify_control_ancestors(relative)
            parent=s.child_directory(self.repo._fd,values[:-1])
        except FileNotFoundError:
            state={'kind':'absent'};self.evidence[relative]=state;return None,state
        try:
            try:before=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:
                state={'kind':'absent'};self.evidence[relative]=state;return None,state
            data=s.read_regular(parent,values[-1])
            current=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            if w.fact(before)!=w.fact(current):raise g.Refusal('control-changed-during-observation')
            # Verify that the current path still addresses the pinned parent.
            again=s.child_directory(self.repo._fd,values[:-1])
            try:
                if s.identity(os.fstat(again))!=s.identity(os.fstat(parent)):
                    raise g.Refusal('control-parent-changed-during-observation')
            finally:os.close(again)
            state={'kind':'file',**w.fact(current),'sha256':g.sha(data),
                   'parent_identity':s.identity(os.fstat(parent))}
            self.evidence[relative]=state;return data,state
        finally:os.close(parent)

    def check(self):
        for path,state in list(self.evidence.items()):
            self.read(path)
            if self.evidence[path]!=state:raise g.Refusal('control-changed-during-observation')


class PersonalControls:
    def __init__(self, repo, tool):
        self.tree=w.PersonalWorktree(repo,tool)
        self.repo,self.tool=repo,tool
        self.reader=Reader(self.tree)

    def hooks(self):
        cfg=self.tree.git.config
        configured='core.hookspath' in cfg
        raw=g.last(cfg,'core.hookspath','')
        result={'configured_override':configured,'configured_path_sha256':g.sha(str(raw).encode()),
                'hook_execution_proven':False,'hook_bodies_executed':False,
                'registration_source_ref':REGISTRATION_SOURCE_REF,'registration_source_blob':REGISTRATION_SOURCE_BLOB}
        if raw and isinstance(raw,str) and raw.rstrip('/')=='/dev/null':
            return {**result,'available':True,'canonical_guard_state':'inert-hookspath',
                    'registration_guard':'not-active','verdict':'DRIFT','note':'explicit-null-hooks-path'}
        try:
            path=hook_path(raw,self.repo.path) if raw else '.git/hooks'
            if configured and raw is None:raise g.Refusal('invalid-hook-path-setting')
            relative=(path+'/' if path else '')+'pre-commit'
            data,state=self.reader.read(relative)
            active=data is not None and GUARD_MARKER in data
            if not active:
                kind=('foreign-hookspath' if '.husky' in str(raw) or 'lefthook' in str(raw)
                      else 'inert-hookspath') if raw else 'missing'
                return {**result,'available':True,'canonical_guard_state':kind,
                        'registration_guard':'not-active','verdict':'DRIFT' if kind=='inert-hookspath' else 'ADVISORY'}
            guard,guard_state=self.reader.read((path+'/' if path else '')+'registration-guard')
            current=guard is not None and g.sha(guard)==REGISTRATION_SHA256
            executable=bool(state['mode']&stat.S_IXUSR)
            guard_executable=guard is not None and bool(guard_state['mode']&stat.S_IXUSR)
            return {**result,'available':True,'canonical_guard_state':'active',
                    'marker_is_structural_only':True,'dispatcher_executable':executable,
                    'registration_guard':'missing' if guard is None else 'current' if current else 'stale',
                    'registration_guard_executable':guard_executable,
                    'verdict':'OK' if current and executable and guard_executable else 'ADVISORY'}
        except (ValueError,OSError) as error:
            return {**result,'available':False,'canonical_guard_state':'unavailable',
                    'registration_guard':'unavailable','verdict':'ADVISORY',
                    'reason':str(error) if isinstance(error,g.Refusal) else 'scoped-hook-control-unavailable'}

    def memory_fact(self):
        try:info=os.stat('agent-learnings.md',dir_fd=self.repo._fd,follow_symlinks=False)
        except FileNotFoundError:return {'kind':'absent'}
        return {'kind':'present',**w.fact(info)}

    def memory(self, indexed):
        names=[name for name in indexed if w.parts(name)[-1].casefold()=='agent-learnings.md']
        state=self.memory_fact();self.memory_preimage=state
        if names:
            return {'available':True,'state':'tracked','tracked_count':len(names),
                    'tracked_names_sha256':w.digest(sorted(names)),'verdict':'VIOLATION',
                    'body_read':False,'presence':state['kind']}
        if state['kind']=='absent':return {'available':True,'state':'absent','verdict':'OK','body_read':False}
        if (state['type']!=stat.S_IFREG or state['uid']!=os.getuid() or state['nlink']!=1):
            return {'available':False,'state':'unavailable','verdict':'ADVISORY','body_read':False,
                    'reason':'generated-memory-type-or-ownership-held'}
        try:
            parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
            with tempfile.TemporaryDirectory(prefix='personal-memory-ignore-',dir=parent) as temp:
                self.tree.configure_ignore(temp)
                self.tree.control('.gitignore');self.tree.control('.gitattributes')
                self.tree.ignore_ready=True
                ignored='agent-learnings.md' in self.tree.ignored(['agent-learnings.md'])
                self.tree.recheck_controls()
            return {'available':True,'state':'ignored' if ignored else 'not-ignored',
                    'verdict':'OK' if ignored else 'DRIFT','body_read':False,
                    'ignore_scope':'personal repository policy; no ambient global excludes'}
        except (ValueError,OSError) as error:
            return {'available':False,'state':'indeterminate','verdict':'ADVISORY','body_read':False,
                    'reason':str(error) if isinstance(error,g.Refusal) else 'scoped-memory-ignore-unavailable'}

    def agents(self, indexed):
        def key(path):
            import unicodedata
            if g.git_bool(g.last(self.tree.git.config,'core.precomposeunicode','false')):
                path=unicodedata.normalize('NFC',path)
            return path.casefold() if g.git_bool(g.last(self.tree.git.config,'core.ignorecase','false')) else path
        keys=[key(path) for path in indexed]
        if len(keys)!=len(set(keys)):raise g.Refusal('control-index-normalization-ambiguous')
        if key('AGENTS.md') not in keys:
            return {'available':True,'state':'not-tracked','body_read':False,'verdict':'OK'}
        try:
            data,_=self.reader.read('AGENTS.md')
            if data is None:return {'available':False,'state':'missing','body_read':False,'verdict':'ADVISORY'}
            learned=bool(re.search(rb'^## Learned (User Preferences|Workspace Facts)\b',data,re.MULTILINE))
            pointer=b'agent-learnings.md' in data
            return {'available':True,'state':'tracked','body_read':True,
                    'generated_learned_headings_present':learned,'memory_pointer_present':pointer,
                    'verdict':'DRIFT' if learned else 'OK' if pointer else 'ADVISORY',
                    'content_or_context_emitted':False}
        except (ValueError,OSError) as error:
            return {'available':False,'state':'unavailable','body_read':False,'verdict':'ADVISORY',
                    'reason':str(error) if isinstance(error,g.Refusal) else 'scoped-AGENTS-control-unavailable'}

    def observe(self):
        with self.tree.git.private_gitdir(worktree_controls=True):
            metadata=self.tree.git.observe()
            indexed=w.index_paths(self.tree.run('index'))
            hooks=self.hooks();memory=self.memory(indexed);agents=self.agents(indexed)
            self.reader.check()
            self.tree.recheck_controls()
            if self.memory_fact()!=self.memory_preimage:raise g.Refusal('memory-metadata-changed-during-observation')
            self.tree.git.finish();self.tree.unchanged()
        available=all(row['available'] for row in (hooks,memory,agents))
        return {**metadata,'hooks':hooks,'memory':memory,'agents':agents,
                'controls_available':available,'controls_verdict':verdict(hooks['verdict'],memory['verdict'],agents['verdict']),
                'control_evidence_sha256':w.digest(self.reader.evidence),
                'control_probes':self.tree.probes,'generated_memory_contents_read':False,
                'source_or_config_writes':False,'new_shared_links':0,'new_workers':0,
                'complete_doctor_or_native_qualification':False}


def inspect(scope,tool):
    rows=[]
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:rows.append(PersonalControls(repo,tool).observe())
        except (ValueError,OSError,UnicodeError) as error:
            rows.append({'id':target['id'],'controls_available':False,'controls_verdict':None,
                         'reason':str(error) if isinstance(error,g.Refusal) else 'scoped-controls-unavailable',
                         'complete_doctor_or_native_qualification':False})
    return {'schema':'personal-portability/personal-controls/v1','target_count':len(rows),'rows':rows,
            'network_requests':0,'source_or_config_writes':False,'new_workers':0,'new_shared_links':0,
            'complete_doctor_or_native_qualification':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--repository',action='append')
    args=parser.parse_args(argv)
    try:
        result=inspect(s.PersonalScope(repositories=args.repository),g.GitTool())
        print(json.dumps(result,sort_keys=True))
        if any(row['controls_verdict']=='VIOLATION' for row in result['rows']):return 1
        return 2 if any(not row['controls_available'] for row in result['rows']) else 0
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'scope-or-tool-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
