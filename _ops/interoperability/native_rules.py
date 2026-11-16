"""Bounded Codex instruction projection; explicit preview/apply/verify/rollback.

This is an owner installer interface, not a qualification or authorization issuer.
Operation directories contain private local preimages; never commit them.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import uuid

import qualification
import inventory
import render_rules
import codex_work_rules

REVISION = 'bc58eb77f442307ab4f124ab5aeec3f99571cb21'
PAYLOAD = '4cfb6f107e5a26dbea73c83bf35d4c918dbc73e0ba26498d2605de9ac71a5ba3'
# The closed observation check binds this ABI separately from legacy MOD-03.
PROFILE_CHECK = 'MOD-03-assessed-native-dispatch-collaboration'
MARKER = 'native-entry-routing/v1'
ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def regular(path, *, missing=False):
    path = Path(os.path.abspath(path))
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError('symlinked target/source component refused')
    if not path.exists() and missing:
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('regular unshared file required')
    return path.read_bytes()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def render(dev, skills, awa):
    """Read a pinned skills Git object, never an installed Cursor projection."""
    for root, owner in ((dev, 'KleinPerkins/dev'), (skills, 'KleinPerkins/skills'), (awa, 'KleinPerkins/awa')):
        identity, reason = inventory.repository(root)
        if identity != owner or reason is not None:
            raise ValueError('source identity unavailable, excluded, or mismatched')
    prefix = 'global/rules/subagent-orchestration/'
    with tempfile.TemporaryDirectory(prefix='int007b-source-') as tmp:
        export = Path(tmp)
        directory = export / prefix
        directory.mkdir(parents=True)
        for name in ('codex_dispatch.py', 'codex-work-policy.json', 'CODEX-DISPATCH.md', 'subagent-orchestration.mdc'):
            (directory / name).write_bytes(git(skills, 'show', REVISION + ':' + prefix + name))
        observed = json.loads(subprocess.check_output(['python3', str(directory / 'codex_dispatch.py'), 'source-digest']))
        if observed != {'source_sha256': PAYLOAD}:
            raise ValueError('qualified resolver payload changed')
        result = render_rules.prepare(dev, export, awa, 'codex', native_codex=True)
        for row in result['sources']:
            if row['owner'] == 'KleinPerkins/skills':
                row['path'] = 'git:' + REVISION + ':' + prefix + 'subagent-orchestration.mdc'
        result['resolver'] = dict(repository='KleinPerkins/skills', revision=REVISION,
                                  payload_sha256=PAYLOAD, entrypoint='codex_dispatch.py',
                                  policy='codex-work-policy.json', contract='CODEX-DISPATCH.md')
        return result


def qualified(path, build):
    data = regular(path)
    rows = json.loads(data)
    if not isinstance(rows, list):
        raise ValueError('qualification array required')
    matches = []
    for row in rows:
        qualification.validate(row)
        if (row['capability'], row['owner'], row['check'], row['host'], row['surface'], row['outcome']) == (
                'codex-work-assessment', 'KleinPerkins/skills', PROFILE_CHECK,
                'codex', 'local-macos-desktop', 'pass'):
            matches.append(row)
    if not build:
        raise ValueError('current host build required')
    current = [row for row in matches if qualification.current(
        row, source_revision=REVISION, payload_sha256=PAYLOAD,
        host_build=build, adapter_revision=REVISION)]
    disqualifying = {'host-build-unavailable', 'native-not-observed', 'fixture-only',
                    'source-drift', 'owner-decision-required', 'source-merge-pending'}
    if len(current) != 1 or disqualifying.intersection(current[0]['limitations']):
        raise ValueError('one current passing collaboration-profile work-assessment observation required')
    return sha(data)


def expected(dev, skills, awa, target, *, work_source=None, build=None):
    prepared = render(dev, skills, awa) if work_source is None else codex_work_rules.prepare(work_source, build)
    before = regular(target, missing=True)
    projector = render_rules.project if work_source is None else codex_work_rules.project
    after = projector('' if before is None else before.decode('utf-8'), prepared['blocks']).encode()
    return prepared, before, after


def preview(args):
    target = Path(os.path.abspath(args.home)) / '.codex/AGENTS.md'
    work_source = getattr(args, 'work_source', None)
    prepared, before, after = expected(args.dev_source, args.skills_source, args.awa_source, target,
                                       work_source=work_source, build=args.host_build)
    qualifier = (qualified(args.qualification, args.host_build) if work_source is None else
                 codex_work_rules.qualified(args.qualification, args.host_build, prepared, validator=qualification))
    operation = Path(os.path.abspath(args.operation_dir))
    # Refuse reused operation directories; backups are private and outside the repo.
    for parent in [operation, *operation.parents]:
        if parent.is_symlink():
            raise ValueError('symlinked operation directory refused')
    for source in (args.dev_source, args.skills_source, args.awa_source, *(() if work_source is None else (work_source,))):
        if operation.is_relative_to(source.resolve()):
            raise ValueError('private operation storage must be outside source roots')
    ancestor = operation.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    inside = subprocess.run(['git', '-C', str(ancestor), 'rev-parse', '--is-inside-work-tree'], capture_output=True, text=True)
    if inside.returncode == 0 and inside.stdout.strip() == 'true':
        raise ValueError('private operation storage must be outside Git worktrees')
    operation.mkdir(mode=0o700)
    mode = stat.S_IMODE(target.stat().st_mode) if before is not None else 0o600
    plan = dict(schema='interoperability/native-rule-operation/v1', operation_id=str(uuid.uuid4()),
                operation_dir=str(operation), target=str(target),
                before_sha256=None if before is None else sha(before), after_sha256=sha(after), mode=mode,
                dev_source=str(args.dev_source.resolve()), skills_source=str(args.skills_source.resolve()),
                awa_source=str(args.awa_source.resolve()),
                source_sha256=sha(canonical(prepared)),
                implementation_sha256=implementation_digest(),
                qualification=str(args.qualification.resolve()), qualification_sha256=qualifier,
                host_build=args.host_build, resolver=prepared['resolver'],
                affected_sessions='All Codex sessions reading this home instruction file; existing contexts may retain earlier instructions.',
                delta=list(prepared['blocks']), rollback='Restore exact preimage only while the target matches this postimage.',
                production_rollout=False)
    if work_source is not None:
        plan.update(work_profile='codex-work-dispatch/v1', work_source=str(work_source.absolute()))
    plan['action_sha256'] = sha(canonical(plan))
    for name, data in [('before', before or b''), ('after', after), ('operation.json', canonical(plan) + b'\n')]:
        with (operation / name).open('xb') as stream:
            os.chmod(operation / name, 0o600)
            stream.write(data)
    return {**plan, 'changed': before != after, 'operation_dir': str(operation)}


def implementation_digest():
    return sha(b''.join(Path(__file__).with_name(name).read_bytes() for name in
                       ('native_rules.py', 'render_rules.py', 'qualification.py', 'inventory.py', 'codex_work_rules.py')) +
               (ROOT / '_ops/bin/install-agent-rules.sh').read_bytes() +
               (ROOT / '_ops/rules/hosts/codex-work-dispatch.md').read_bytes() +
               (ROOT / '_ops/interoperability/evidence/codex-work-activation-bindings.json').read_bytes())


def load_operation(path):
    plan = json.loads(regular(path / 'operation.json'))
    digest = plan.pop('action_sha256')
    if sha(canonical(plan)) != digest:
        raise ValueError('operation changed')
    plan['action_sha256'] = digest
    if plan['schema'] != 'interoperability/native-rule-operation/v1':
        raise ValueError('unknown operation schema')
    if plan['operation_dir'] != str(path.absolute()) or str(uuid.UUID(plan['operation_id'])) != plan['operation_id']:
        raise ValueError('operation identity/location changed')
    if 'work_source' in plan or 'work_profile' in plan:
        if (plan.get('work_profile') != 'codex-work-dispatch/v1' or
                not isinstance(plan.get('work_source'), str) or not Path(plan['work_source']).is_absolute() or
                plan['delta'] != [codex_work_rules.MARKER] or 'economy_resolver' in plan):
            raise ValueError('work-dispatch operation profile changed')
    target = Path(plan['target'])
    if not target.is_absolute() or target.parts[-2:] != ('.codex', 'AGENTS.md'):
        raise ValueError('target outside owned Codex instruction interface')
    before, after = regular(path / 'before'), regular(path / 'after')
    if sha(after) != plan['after_sha256'] or (plan['before_sha256'] is not None and sha(before) != plan['before_sha256']):
        raise ValueError('operation payload changed')
    return plan, before, after


def atomic_replace(path, data, mode, expected_sha):
    current = regular(path, missing=True)
    if (None if current is None else sha(current)) != expected_sha:
        raise ValueError('target preimage changed; preserve user changes')
    if not path.parent.is_dir():
        raise ValueError('target parent must already exist')
    fd, tmp = tempfile.mkstemp(prefix='.dev-native-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        again = regular(path, missing=True)
        if (None if again is None else sha(again)) != expected_sha:
            raise ValueError('target changed during apply')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_operation(args, *, rollback=False):
    plan, before, after = load_operation(args.operation_dir)
    if args.approve != plan['action_sha256']:
        raise ValueError('exact preview action digest required')
    target = Path(plan['target'])
    current = regular(target, missing=True)
    actual = None if current is None else sha(current)
    if current is not None and stat.S_IMODE(target.stat().st_mode) != plan['mode']:
        raise ValueError('target mode changed; preserve user changes')
    if rollback:
        if actual == plan['before_sha256']:
            return dict(status='already-rolled-back', target=str(target))
        if actual != plan['after_sha256']:
            raise ValueError('rollback postimage changed; preserve user changes')
        if plan['before_sha256'] is None:
            target.unlink()
        else:
            atomic_replace(target, before, plan['mode'], plan['after_sha256'])
        return dict(status='rolled-back', target=str(target))
    if implementation_digest() != plan['implementation_sha256']:
        raise ValueError('installer source changed')
    if 'work_source' in plan:
        prepared = codex_work_rules.prepare(Path(plan['work_source']), plan['host_build'])
        qualifier = codex_work_rules.qualified(Path(plan['qualification']), plan['host_build'], prepared, validator=qualification)
    else:
        qualifier = qualified(Path(plan['qualification']), plan['host_build'])
        prepared = render(*(Path(plan[name]) for name in ('dev_source', 'skills_source', 'awa_source')))
    if qualifier != plan['qualification_sha256']:
        raise ValueError('qualification changed')
    if sha(canonical(prepared)) != plan['source_sha256']:
        raise ValueError('source preimage changed')
    if actual == plan['after_sha256']:
        return dict(status='already-applied', target=str(target))
    atomic_replace(target, after, plan['mode'], plan['before_sha256'])
    return dict(status='applied', target=str(target), sha256=sha(regular(target)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preview', 'apply', 'verify', 'rollback'))
    parser.add_argument('--dev-source', type=Path, default=ROOT)
    parser.add_argument('--skills-source', type=Path, default=Path.home() / 'dev/capabilities/skills')
    parser.add_argument('--awa-source', type=Path, default=Path.home() / 'dev/capabilities/awa')
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--operation-dir', type=Path)
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--host-build')
    parser.add_argument('--approve')
    parser.add_argument('--work-source', type=Path,
                        help='Opt-in accepted personal Codex work-dispatch export; never selects legacy mirroring')
    args = parser.parse_args()
    try:
        if args.operation == 'preview':
            if not all((args.operation_dir, args.qualification, args.host_build)):
                raise ValueError('preview requires operation directory, qualification and current host build')
            result = preview(args)
        elif args.operation == 'verify':
            prepared, before, after = expected(args.dev_source, args.skills_source, args.awa_source, args.home / '.codex/AGENTS.md',
                                              work_source=args.work_source, build=args.host_build)
            if args.work_source is not None:
                if not args.qualification:
                    raise ValueError('work-dispatch verify requires exact qualification')
                codex_work_rules.qualified(args.qualification, args.host_build, prepared, validator=qualification)
            if before != after:
                raise ValueError('native instructions missing or stale')
            result = dict(status='current-source-projection', native_behavior='requires separate observation')
        else:
            if not args.operation_dir:
                raise ValueError('operation directory required')
            result = apply_operation(args, rollback=args.operation == 'rollback')
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, UnicodeError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps(dict(status='refused', reason=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
