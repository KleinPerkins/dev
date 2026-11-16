"""Scoped personal baseline eligibility and five-file compliance observations.

Canonical local diagnostic semantics only. No apply, GitHub/profile check,
worktree discovery, complete doctor/native qualification or mutation authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

HERE=Path(__file__).absolute().parent
CONTROLS_SHA256='63250ccf3a00988249a93f7dcc9eb2628d7ef31a21d5824b06a9cc6a0b03e71a'
dependency=HERE/'personal_controls.py'
if dependency.is_symlink() or hashlib.sha256(dependency.read_bytes()).hexdigest()!=CONTROLS_SHA256:
    raise ValueError('accepted personal controls dependency changed')
sys.path.insert(0,str(HERE))
import personal_controls as c
if Path(c.__file__).absolute()!=dependency:raise ValueError('personal controls imported from another root')
g,w,s=c.g,c.w,c.s
# Historical owner provenance identifies the unchanged pure baseline algorithms.
# TEMPLATE_HASHES independently binds the reviewed successor template bytes.
OWNER_REF='1ed046a1ae572efcc03b193c2fb87d89f65ae9df'
OWNER_LIBRARY_BLOB='9a3f89ef7b4169754280ae6a88091ca8ef94413e'
TEMPLATE_HASHES={
    'SECURITY.md':'b331110c3670cd28ec87e4bdc39f5e23c0488af39a046ab8e7003d4b9f498996',
    'dependabot.yml':'f6bda66056bbf4027696b454e3e44d3c402baa3568cf7b6e06c67d8fa5d3386f',
    'gitignore-block.txt':'82c9825c9bc39a36b98a9f2a6578d272e4381fea603714c4b86d1818599f075a',
}
HTML_BEGIN='<!-- BEGIN KleinPerkins/dev baseline (managed by KleinPerkins/dev; do not hand-edit — see _ops/baseline/README.md in KleinPerkins/dev) -->'.encode()
HASH_BEGIN='# BEGIN KleinPerkins/dev baseline (managed by KleinPerkins/dev; do not hand-edit — see _ops/baseline/README.md in KleinPerkins/dev)'.encode()
HASH_END=b'# END KleinPerkins/dev baseline'
FILES=('SECURITY.md','.github/CODEOWNERS','.gitignore','README.md','.github/dependabot.yml')


def load_templates():
    parent=s.absolute_directory(HERE.parent/'baseline/template')
    try:
        result={name:s.read_regular(parent,name) for name in TEMPLATE_HASHES}
        if any(g.sha(result[name])!=digest for name,digest in TEMPLATE_HASHES.items()):
            raise g.Refusal('immutable-baseline-template-drift')
        return result
    finally:os.close(parent)


def eligibility(observation):
    if observation.get('id') not in s.PROJECTS or observation.get('expected_personal_origin_verified') is not True:
        raise g.Refusal('baseline-origin-or-selection-unavailable')
    if observation.get('worktree_status_proven') is not True or type(observation.get('clean_under_personal_policy')) is not bool:
        raise g.Refusal('baseline-worktree-status-unavailable')
    if not observation['clean_under_personal_policy']:
        return {'classification':'EXCLUDED','reason':'dirty-working-tree'}
    branch=observation.get('branch')
    if not branch:return {'classification':'EXCLUDED','reason':'detached-HEAD'}
    if branch!='main':return {'classification':'EXCLUDED','reason':'not-clean-main-branch'}
    return {'classification':'ELIGIBLE','reason':'eligible'}


def managed(data,expected,marker):
    if data is None:return 'MISSING'
    if marker not in data:return 'CUSTOM'
    return 'CURRENT' if data==expected else 'STALE'


def gitignore(data,body):
    if data is None or HASH_BEGIN not in data:return 'MISSING'
    # Match the qualified Mac BSD awk's LF records, C-string NUL termination,
    # substring markers, print-newline behavior and shell command substitution's
    # removal of trailing LF bytes. Preserve CR. Production Git is Mac-bound;
    # no other host's awk/binary-control-file equivalence is asserted.
    active=False;selected=[]
    records=data.split(b'\n')
    if data.endswith(b'\n'):records=records[:-1]
    for line in records:
        line=line.split(b'\0',1)[0]
        if HASH_BEGIN in line:active=True
        if active:selected.append(line)
        if HASH_END in line:active=False
    extracted=b'\n'.join(selected).rstrip(b'\n')
    expected=(HASH_BEGIN+b'\n'+body+HASH_END+b'\n').rstrip(b'\n')
    return 'CURRENT' if extracted==expected else 'STALE'


def overall(states):
    if set(states)!=set(FILES):raise g.Refusal('baseline-file-result-shape-held')
    core=[states[name] for name in ('SECURITY.md','.gitignore','.github/dependabot.yml')]
    if any(v not in {'MISSING','CURRENT','STALE','CUSTOM'} for v in core):
        raise g.Refusal('baseline-file-result-unavailable')
    aux=[states[name] for name in ('.github/CODEOWNERS','README.md')]
    if any(v not in {'MISSING','PRESENT'} for v in aux):raise g.Refusal('baseline-file-result-unavailable')
    if all(v=='MISSING' for v in core):return 'MISSING'
    if all(v=='CURRENT' for v in core) and all(v=='PRESENT' for v in aux):return 'COMPLIANT'
    return 'PARTIAL'


class BaselineReader(c.Reader):
    def __init__(self, tree):
        super().__init__(tree)
        self.metadata_only=set()

    def presence(self, relative):
        if relative not in {'.github/CODEOWNERS','README.md'}:raise g.Refusal('baseline-create-only-path-held')
        values=w.parts(relative);self.metadata_only.add(relative)
        try:
            self.tree.classify_control_ancestors(relative)
            parent=s.child_directory(self.repo._fd,values[:-1])
        except FileNotFoundError:
            state={'kind':'absent'};self.evidence[relative]=state;return 'MISSING'
        try:
            try:info=os.stat(values[-1],dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:
                state={'kind':'absent'};self.evidence[relative]=state;return 'MISSING'
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
                raise g.Refusal('baseline-create-only-type-or-ownership-held')
            again=s.child_directory(self.repo._fd,values[:-1])
            try:
                if s.identity(os.fstat(again))!=s.identity(os.fstat(parent)):
                    raise g.Refusal('baseline-create-only-parent-changed')
            finally:os.close(again)
            if w.fact(os.stat(values[-1],dir_fd=parent,follow_symlinks=False))!=w.fact(info):
                raise g.Refusal('baseline-create-only-changed')
            self.evidence[relative]={'kind':'file',**w.fact(info),
                                     'parent_identity':s.identity(os.fstat(parent)),
                                     'body_read':False}
            return 'PRESENT'
        finally:os.close(parent)

    def check(self):
        for path,state in list(self.evidence.items()):
            if path in self.metadata_only:self.presence(path)
            else:self.read(path)
            if self.evidence[path]!=state:raise g.Refusal('baseline-control-changed-during-observation')


class PersonalBaseline:
    def __init__(self,repo,tool,templates):
        if set(templates)!=set(TEMPLATE_HASHES) or any(g.sha(templates[n])!=h for n,h in TEMPLATE_HASHES.items()):
            raise g.Refusal('immutable-baseline-template-drift')
        self.repo,self.tool,self.templates=repo,tool,dict(templates)
        self.tree=w.PersonalWorktree(repo,tool);self.reader=BaselineReader(self.tree)
        self.eligibility_ready=False

    def file_checks(self):
        if not self.eligibility_ready:raise g.Refusal('baseline-file-checks-need-eligibility')
        states={};unavailable={}
        for path in FILES:
            try:
                if path in {'.github/CODEOWNERS','README.md'}:states[path]=self.reader.presence(path)
                else:
                    data,_=self.reader.read(path)
                    if path=='.gitignore':states[path]=gitignore(data,self.templates['gitignore-block.txt'])
                    else:states[path]=managed(data,self.templates['SECURITY.md' if path=='SECURITY.md' else 'dependabot.yml'],HTML_BEGIN if path=='SECURITY.md' else HASH_BEGIN)
            except (ValueError,OSError) as error:
                states[path]='UNAVAILABLE'
                unavailable[path]=str(error) if isinstance(error,g.Refusal) else 'scoped-baseline-control-unavailable'
        return states,unavailable

    @staticmethod
    def stable(observation):
        return {k:observation[k] for k in ('head','branch','detached','clean_under_personal_policy','worktree_fence')}

    def observe(self):
        before=self.tree.observe();classification=eligibility(before)
        result={**before,'baseline_eligibility':classification,'baseline_available':True,
                'baseline_files_inspected':False,'baseline_file_states':None,'baseline_compliance':None,
                'baseline_diagnostic_verdict':'OK','template_owner_ref':OWNER_REF,
                'canonical_library_blob':OWNER_LIBRARY_BLOB,'template_sha256':dict(TEMPLATE_HASHES),
                'GitHub_delivery_or_runnerless_profile_checked':False,
                'full_doctor_or_native_qualification':False}
        if classification['classification']!='ELIGIBLE':return result
        self.eligibility_ready=True
        states,unavailable=self.file_checks()
        self.reader.check()
        after=self.tree.observe()
        self.reader.check()
        if self.stable(before)!=self.stable(after):raise g.Refusal('baseline-eligibility-changed-during-observation')
        self.tree.git.finish();self.tree.unchanged()
        if load_templates()!=self.templates:raise g.Refusal('immutable-baseline-template-drift')
        compliance=None if unavailable else overall(states)
        return {**result,'baseline_available':not unavailable,'baseline_files_inspected':True,
                'baseline_file_states':states,'baseline_unavailable_reasons':unavailable,
                'baseline_compliance':compliance,'baseline_diagnostic_verdict':'OK' if compliance=='COMPLIANT' else 'ADVISORY',
                'baseline_control_evidence_sha256':w.digest(self.reader.evidence),
                'create_only_bodies_read':False,'source_or_config_writes':False}


def inspect(scope,tool):
    templates=load_templates();rows=[]
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:rows.append(PersonalBaseline(repo,tool,templates).observe())
        except (ValueError,OSError,UnicodeError) as error:
            rows.append({'id':target['id'],'baseline_available':False,'baseline_compliance':None,
                         'baseline_eligibility':{'classification':'UNAVAILABLE'},
                         'reason':str(error) if isinstance(error,g.Refusal) else 'scoped-baseline-unavailable',
                         'full_doctor_or_native_qualification':False})
    return {'schema':'personal-portability/personal-baseline/v1','target_count':len(rows),'rows':rows,
            'network_requests':0,'source_or_config_writes':False,'new_shared_links':0,'new_workers':0,
            'full_doctor_or_native_qualification':False,'profile_and_documentation_checks_still_required':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--repository',action='append')
    args=parser.parse_args(argv)
    try:
        result=inspect(s.PersonalScope(repositories=args.repository),g.GitTool())
        print(json.dumps(result,sort_keys=True));return 2 if any(not r['baseline_available'] for r in result['rows']) else 0
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'scope-tool-or-template-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
