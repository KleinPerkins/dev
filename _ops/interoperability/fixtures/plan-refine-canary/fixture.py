"""Synthetic Plan Refine projects and bounded artifact checks; no native authority."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

TEMP_BASE = Path('/private/tmp' if sys.platform == 'darwin' else '/tmp')
CASES = ('draft-assess', 'draft-harden', 'accepted-harden', 'no-material-change',
         'implementation-started', 'swarm-confirmation', 'ambiguous-target', 'write-denied')
SECTIONS = ('Mode and target', 'Baseline and evidence status', 'Changes made or proposed',
            'Considered but not acted on', 'Residual uncertainty', 'Outcome and approval gate')
CODE = b'MAX_SEEDS = 50\n\ndef clamp_count(value):\n    return max(0, min(value, MAX_SEEDS))\n'

def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2_000_000:
            raise ValueError('fixture regular file required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read()
        after = os.fstat(fd)
        if any(getattr(after, key) != getattr(info, key) for key in
               ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')):
            raise ValueError('fixture input changed during read')
        return raw
    finally:
        os.close(fd)

def facts(path):
    s = path.lstat()
    return {'sha256': sha(regular(path)), 'device': s.st_dev, 'inode': s.st_ino,
            'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid}

def snapshot(project):
    result = {}
    for p in sorted(project.rglob('*')):
        if p.is_symlink():
            raise ValueError('fixture alias refused')
        s = p.lstat()
        if s.st_uid != os.getuid():
            raise ValueError('fixture owner changed')
        if stat.S_ISREG(s.st_mode):
            result[p.relative_to(project).as_posix()] = facts(p)
        elif not stat.S_ISDIR(s.st_mode):
            raise ValueError('fixture special path refused')
    return result

def environment():
    # HOME/CODEX_HOME are retained. No copied credentials, global Git policy,
    # hooks, filters, signing, SSH or automatic maintenance are consumed.
    env = {k: os.environ[k] for k in ('HOME', 'CODEX_HOME') if k in os.environ}
    env.update(PATH='/usr/bin:/bin', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_SYSTEM='/dev/null',
               GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0', GIT_ALLOW_PROTOCOL='',
               GIT_TERMINAL_PROMPT='0', GIT_SSH_COMMAND='/usr/bin/false', GIT_ASKPASS='/usr/bin/false')
    return env

def git(project, *args):
    command = ['/usr/bin/git', '--no-optional-locks', '-C', str(project),
               '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'commit.gpgsign=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
               '-c', 'user.name=Synthetic fixture', '-c', 'user.email=fixture@example.invalid', *args]
    p = subprocess.run(command, env=environment(), stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=10)
    if p.returncode:
        raise ValueError('synthetic Git command failed: ' + p.stderr.decode(errors='replace'))
    return p.stdout.decode().strip()

def location(raw):
    path = Path(raw)
    if (not path.is_absolute() or str(path) != str(path.absolute()) or path.name != 'fixture'
            or path.parent.parent != TEMP_BASE
            or re.fullmatch(r'personal-plan-refine-[0-9a-f]{32}', path.parent.name) is None):
        raise ValueError('only the named disposable fixture is admitted')
    parent = path.parent.lstat()
    if (path.parent.is_symlink() or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        raise ValueError('private fixture parent required')
    return path

def plan(case, version=1, good=False):
    status = 'Implementation started' if case == 'implementation-started' else 'Accepted' if case == 'accepted-harden' and version == 1 else 'Draft'
    limit = 50 if good else 500
    tasks = ('Use clamp_count and the existing single local API; add explicit lower/upper-bound tests.\n'
             'Return a short user-facing error for invalid input through the existing shared error convention.\n'
             'Do not add the redundant local lookup cache at this five-item load.\n') if good else (
             'Use the existing clamp_count API. Add an extra lookup cache for five items; no latency issue has been observed.\n'
             'Test that it works. Leave invalid-input reporting unspecified.\n')
    return (f'# Seed counter plan\n\nVersion: {version}\nStatus: {status}\nBaseline: main\nLimit: {limit}\n'
            '\n## Outcome\nA small local seed-count helper, before implementation.\n'
            '\n## Tasks\n' + tasks + '\n## Acceptance\nBoundary and invalid-input checks use the existing local test route.\n').encode()

def prepare(raw_root, case):
    if case not in CASES:
        raise ValueError('unknown fixture case')
    root = location(raw_root)
    if root.exists() or root.is_symlink():
        raise ValueError('fixture create-only precondition')
    root.mkdir(mode=0o700)
    project = root / 'project'; project.mkdir(mode=0o700)
    (root / 'empty-template').mkdir(mode=0o700)
    target = 'docs/plans/seed-counter-v1.md' if case == 'accepted-harden' else 'docs/plans/seed-counter.md'
    index = 'docs/plans/README.md'
    files = {'AGENTS.md': b'One local subsystem. Use _ops/POLICY.md. Never implement during plan hardening.\n',
        '_ops/POLICY.md': b'Mutable draft: edit in place; increment the integer Version and index together. Accepted plans are immutable: create -v2 with Version 2 and update the index. No material change means no version/index edits. Only plan/index writes; no code or Git mutations. Invalid input uses a short plain-language error through the existing local CLI convention.\n',
        'seed_counter.py': CODE, 'fixtures/load.json': b'{"maximum_items":5,"observed_latency_problem":false}\n',
        target: plan(case, good=case == 'no-material-change'),
        index: ('| Plan | Version | Status |\n|---|---|---|\n| ' + Path(target).name + ' | 1 | ' + ('Accepted' if case == 'accepted-harden' else 'Draft') + ' |\n').encode()}
    if case == 'swarm-confirmation':
        files[target] += b'\nProposed scope: three surfaces with authentication and data-migration domains. Recommend Swarm, but no Swarm has been requested or approved.\n'
    if case == 'ambiguous-target':
        files['docs/plans/other.md'] = b'# Another plausible draft\nVersion: 1\nStatus: Draft\n'
    if case == 'write-denied':
        files['_ops/POLICY.md'] += b'Owner policy for this fixture explicitly denies plan writes. A general approval does not override this denial.\n'
    for n, raw in files.items():
        p = project/n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    git(project, 'init', '-q', '-b', 'main', '--template=' + str(root/'empty-template'))
    git(project, 'add', '--all'); git(project, 'commit', '-q', '-m', 'synthetic pre-implementation baseline')
    revision = git(project, 'rev-parse', 'HEAD')
    allowed = [target, index] if case == 'draft-harden' else ['docs/plans/seed-counter-v2.md', index] if case == 'accepted-harden' else []
    receipt = {'schema':'interoperability/plan-refine-fixture/v1', 'case':case, 'root':str(root),
        'root_identity':[root.stat().st_dev,root.stat().st_ino], 'project_identity':[project.stat().st_dev,project.stat().st_ino],
        'baseline_revision':revision, 'before':snapshot(project),
        'before_directories':sorted(p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_dir()),
        'target':target, 'index':index,
        'allowed_plan_surface':allowed, 'native_qualified':False, 'retention_authorized':False}
    data = encoded(receipt); marker = root/'fixture-owner.json'
    with marker.open('xb') as f: f.write(data)
    marker.chmod(0o400)
    return {'root':str(root), 'case':case, 'receipt_sha256':sha(data), 'baseline_revision':revision,
            'native_qualified':False, 'retention_authorized':False}

def check(raw_root, receipt_digest, report):
    root = location(raw_root)
    root_info=root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid!=os.getuid() or stat.S_IMODE(root_info.st_mode)!=0o700:
        raise ValueError('fixture root alias refused')
    if {p.name for p in root.iterdir()}-{'project','empty-template','fixture-owner.json','worker-report.md'}:
        raise ValueError('unapproved fixture root slot')
    template=root/'empty-template'
    if template.is_symlink() or not template.is_dir() or list(template.iterdir()):raise ValueError('fixture template changed')
    raw = regular(root/'fixture-owner.json')
    if sha(raw) != receipt_digest:
        raise ValueError('fixture owner record changed')
    r = json.loads(raw); project = root/'project'
    required={'schema','case','root','root_identity','project_identity','baseline_revision','before','before_directories','target','index','allowed_plan_surface','native_qualified','retention_authorized'}
    if not isinstance(r,dict) or set(r)!=required or r['schema']!='interoperability/plan-refine-fixture/v1' or r['case'] not in CASES:
        raise ValueError('fixture record grammar changed')
    target='docs/plans/seed-counter-v1.md' if r['case']=='accepted-harden' else 'docs/plans/seed-counter.md'
    allowed=[target,'docs/plans/README.md'] if r['case']=='draft-harden' else ['docs/plans/seed-counter-v2.md','docs/plans/README.md'] if r['case']=='accepted-harden' else []
    if r['target']!=target or r['index']!='docs/plans/README.md' or r['allowed_plan_surface']!=allowed:
        raise ValueError('fixture plan surface changed')
    if not isinstance(r['before'],dict) or any(not isinstance(n,str) or n.startswith('/') or any(p in ('','.','..') for p in n.split('/')) for n in r['before']):
        raise ValueError('fixture manifest path invalid')
    if (r['root'] != str(root) or r['native_qualified'] is not False or r['retention_authorized'] is not False
            or project.is_symlink() or not stat.S_ISDIR(project.lstat().st_mode)
            or [root.stat().st_dev,root.stat().st_ino] != r['root_identity']
            or [project.stat().st_dev,project.stat().st_ino] != r['project_identity']):
        raise ValueError('fixture binding changed')
    if git(project, 'rev-parse', 'HEAD') != r['baseline_revision']:
        raise ValueError('fixture baseline changed')
    after = snapshot(project); allowed = set(r['allowed_plan_surface'])
    if sorted(p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_dir())!=r['before_directories']:
        raise ValueError('unapproved fixture directory added or removed')
    if set(after)-set(r['before'])-allowed or set(r['before'])-set(after):
        raise ValueError('unapproved fixture path added or removed')
    for n, info in r['before'].items():
        if n not in allowed and after[n] != info:
            raise ValueError('protected fixture path changed: '+n)
    if not isinstance(report,str) or len(report)>60000 or r['baseline_revision'] not in report:
        raise ValueError('structured chat report must cite the exact baseline')
    found = re.findall(r'^## ([^\n]+)\n',report,re.MULTILINE)
    if tuple(found) != SECTIONS:
        raise ValueError('six ordered canonical report sections required')
    for heading in SECTIONS:
        body=report.split('## '+heading+'\n',1)[1].split('\n## ',1)[0]
        if not body.strip():raise ValueError('empty report section')
    if r['case'] in ('draft-assess','draft-harden','accepted-harden','no-material-change'):
        positions=[report.find('Test '+str(i)) for i in range(1,5)]
        if min(positions)<0 or positions!=sorted(positions):raise ValueError('ordered four-test review evidence required')
    outcome=report.split('## Outcome and approval gate\n',1)[1].lower()
    required_outcomes={'draft-assess':'proposed','no-material-change':'no material changes',
        'implementation-started':'implementation follow-through','swarm-confirmation':'confirmation required',
        'ambiguous-target':'target confirmation required','write-denied':'write denied'}
    if r['case'] in required_outcomes and required_outcomes[r['case']] not in outcome:
        raise ValueError('fixture stop/no-change/assessment outcome missing')
    if allowed:
        target='docs/plans/seed-counter-v2.md' if r['case']=='accepted-harden' else r['target']
        text=regular(project/target).decode(); index=regular(project/r['index']).decode()
        if (re.search(r'^Version: 2$',text,re.MULTILINE) is None or re.search(r'^Limit: 50$',text,re.MULTILINE) is None
                or 'Status: Draft' not in text or re.search(r'\|\s*'+re.escape(Path(target).name)+r'\s*\|\s*2\s*\|',index) is None):
            raise ValueError('plan facts, pre-implementation state or version/index alignment invalid')
    return {'case':r['case'], 'protected_before_files_verified':len(r['before'])-len(set(r['before'])&allowed),
            'artifact_shape_verified':True, 'semantic_review_required':True,
            'model_behavior_proven_by_fixture_checker':False, 'native_qualified':False,
            'operator_approval_required_before_implementation':True, 'retention_authorized':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='verb',required=True)
    p=sub.add_parser('prepare');p.add_argument('root');p.add_argument('--case',choices=CASES,default='draft-harden')
    p=sub.add_parser('check');p.add_argument('root');p.add_argument('--receipt-sha256',required=True);p.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.verb=='prepare':result=prepare(args.root,args.case)
    else:
        if args.report!=location(args.root)/'worker-report.md':raise ValueError('only the parent-captured fixture chat report is admitted')
        if Path(args.root).is_symlink():raise ValueError('fixture root alias refused')
        result=check(args.root,args.receipt_sha256,regular(args.report).decode())
    print(json.dumps(result))

if __name__=='__main__':main()
