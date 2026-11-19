#!/usr/bin/env python3
"""Separate exact-pin Isokit retention after accepted native canary evidence.

The unchanged canary transaction owns publication and inode-exact recovery.
This interface supplies the separate retained preview/consent boundary and a
fresh read-only native catalog postcondition. It never starts a model worker.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

HERE = Path(__file__).absolute().parent
import hashlib

CORE_SHA = "878ad35c858e0d0b04fd421e16a4b1df6ae6e2fccabb382977d26b9bf10f362e"
if (HERE / 'isokit_migration.py').is_symlink() or hashlib.sha256((HERE / 'isokit_migration.py').read_bytes()).hexdigest() != CORE_SHA:
    raise ValueError('accepted Isokit transaction changed')
sys.path.insert(0, str(HERE))
import isokit_migration as core

SCHEMA = 'interoperability/isokit-retained/v1'
EVIDENCE_REVISION = '765bdcbbd96d25343fe2594d939a83a9dcd76cab'
EVIDENCE_PATH = 'docs/evidence/isokit/build-23880-execution.json'
EVIDENCE_SHA = '12d9de33442ee59e0038a4ce08bde90ce4566838fdf4798c78352cf7d1e18165'
CLI = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
CLI_SHA = '58a91f6ea19bea477ae3a2ec48d619f0039afe75d3476260747e11d201fa7cea'


def implementation():
    return core.sha(core.canonical({'isokit_retained.py': core.sha(core.regular(Path(__file__).absolute())),
                                    'transaction': core.implementation()}))


def evidence(path):
    raw = core.regular(path)
    if core.sha(raw) != EVIDENCE_SHA or len(EVIDENCE_REVISION) != 40:
        raise ValueError('exact immutable accepted Skills evidence required')
    row = json.loads(raw)
    if (row['schema'] != 'skills/isokit-native-observation/v1' or row['outcome'] != 'pass'
            or row['host']['build'] != core.HOST_BUILD
            or row['source']['checkout_revision'] != core.PIN
            or row['source']['tracked_payload_inventory_sha256'] != core.PAYLOAD
            or row['native']['duration_ms'] > row['native']['hard_deadline_ms']
            or row['rollback']['passed'] is not True):
        raise ValueError('native proof does not qualify this build and payload')
    return {'repository': 'KleinPerkins/skills', 'revision': EVIDENCE_REVISION,
            'path': EVIDENCE_PATH, 'sha256': EVIDENCE_SHA, 'local_path': str(path)}


def cli_proof():
    digest = core.sha(core.regular(CLI))
    if digest != CLI_SHA:
        raise ValueError('qualified bundled native CLI changed')
    return {'path': str(CLI), 'sha256': digest}


def qualification_unchanged(plan):
    if (evidence(Path(plan['native_evidence']['local_path'])) != plan['native_evidence']
            or cli_proof() != plan['native_cli']):
        raise ValueError('accepted native evidence or bundled CLI changed')


def catalog(plan):
    """Initialize a short-lived local stdio parser; only request skills/list.

    No extra roots, account/token refresh, threads, turns or tool execution.
    Output stays in memory; return only the exact Isokit discovery fact.
    """
    if cli_proof() != plan['native_cli']:
        raise ValueError('native CLI changed')
    process = subprocess.Popen([str(CLI), 'app-server', '--stdio'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 12
    pending = b''
    def send(method, params, identifier=None):
        message = {'method': method, 'params': params}
        if identifier is not None:
            message['id'] = identifier
        process.stdin.write(core.canonical(message) + b'\n')
        process.stdin.flush()
    def receive(identifier):
        nonlocal pending
        while time.monotonic() < deadline:
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                message = json.loads(line)
                if message.get('id') == identifier:
                    if 'error' in message:
                        raise ValueError('native catalog request refused')
                    return message['result']
            if not select.select([process.stdout], [], [], min(0.25, max(0, deadline-time.monotonic())))[0]:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError('native catalog closed before response')
            pending += chunk
            if len(pending) > 16 * 1024 * 1024:
                raise ValueError('native catalog response exceeded bound')
        raise ValueError('native catalog deadline exceeded')
    try:
        send('initialize', {'clientInfo': {'name': 'isokit_retained_verify', 'version': '1.0'},
                            'capabilities': {'experimentalApi': True}}, 1)
        receive(1)
        send('initialized', {})
        send('skills/list', {'cwds': [plan['native_cwd']], 'forceReload': True}, 2)
        response = receive(2)
        rows = response.get('data', [])
        if len(rows) != 1 or rows[0].get('cwd') != plan['native_cwd'] or rows[0].get('errors'):
            raise ValueError('native skill catalog incomplete')
        matches = [s for s in rows[0].get('skills', []) if s.get('name') == 'isokit']
        if len(matches) != 1 or matches[0].get('enabled') is not True:
            raise ValueError('native catalog did not discover exactly the retained Isokit link')
        skill = Path(plan['target']) / 'SKILL.md'
        try:
            canonical = skill.resolve(strict=True)
            reported = matches[0].get('path')
            # The native loader can canonicalize a symlinked skill. Accept only
            # this owned alias or its exact source, with current file identity.
            if reported not in (str(skill), str(canonical)) or not skill.samefile(reported):
                raise ValueError('native catalog path is not the exact retained Isokit source')
        except OSError as error:
            raise ValueError('native catalog skill file is missing or changed') from error
        return {'name': 'isokit', 'path': matches[0]['path'], 'enabled': True,
                'link_path': str(skill), 'canonical_source_path': str(canonical),
                'reported_path_kind': 'home-link' if reported == str(skill) else 'canonical-source',
                'same_file_verified': True,
                'fresh_catalog': True, 'extra_roots': False, 'model_worker_started': False}
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        process.stdin.close()
        process.stdout.close()


def preview(args):
    home = args.home.expanduser().absolute()
    proof = evidence(args.native_evidence.expanduser().absolute())
    native_cli = cli_proof()
    cwd = home / 'Codex'
    core.directory(cwd)
    operation = core.shared.private_operation_path(args.operation_dir, (home / 'dev', home / '.codex', home / '.agents', home / '.cursor', home / '.claude'))
    core.directory(operation.parent)
    operation.mkdir(mode=0o700)
    # Failed preview directories are retained for inspection; no host link is created.
    transaction = argparse.Namespace(home=home, operation_dir=operation / 'transaction', portability_manifest=args.portability_manifest)
    proposed = core.preview(transaction)
    plan = {'schema': SCHEMA, 'operation_dir': str(operation), 'operation_root': core.directory(operation),
            'implementation_sha256': implementation(), 'core_action_sha256': proposed['action_sha256'],
            'core_record_sha256': core.sha(core.regular(transaction.operation_dir / 'operation.json')),
            'native_evidence': proof, 'native_cli': native_cli, 'native_cwd': str(cwd),
            'target': proposed['target'], 'retention_requested': True,
            'native_qualified_by': 'Accepted temporary native canary for this exact build and pinned payload',
            'postcondition': 'Exact owned link/source/config verification and unique native skill at that link or its canonical same-file source; no additional model worker',
            'affected_sessions': 'All Codex sessions scanning the shared skill root; existing contexts may retain prior discovery.',
            'external_consent': 'Separate exact operation approval required; a digest alone is not consent.'}
    digest = core.sha(core.canonical(plan))
    core.write_once(operation / 'operation.lock', {})
    core.write_once(operation / 'retained-operation.json', {**plan, 'action_sha256': digest})
    return {'status': 'previewed-retained', 'operation_dir': str(operation), 'action_sha256': digest,
            'target': plan['target'], 'retention_applied': False, 'model_worker_started': False}


def load(operation):
    operation = operation.expanduser().absolute()
    if core.directory(operation)['mode'] != 0o700:
        raise ValueError('retained operation root must be private')
    path = operation / 'retained-operation.json'
    if core.observation(path)['mode'] != 0o600 or core.observation(path)['uid'] != os.getuid():
        raise ValueError('retained record must be private and operator-owned')
    plan = json.loads(core.regular(path))
    digest = plan.pop('action_sha256')
    if (core.sha(core.canonical(plan)) != digest or plan['schema'] != SCHEMA
            or plan['operation_dir'] != str(operation) or plan['operation_root'] != core.directory(operation)
            or plan['implementation_sha256'] != implementation() or plan['retention_requested'] is not True):
        raise ValueError('retained operation identity or implementation changed')
    transaction = operation / 'transaction'
    if core.sha(core.regular(transaction / 'operation.json')) != plan['core_record_sha256']:
        raise ValueError('underlying transaction record changed')
    child = core.load(transaction)
    if (child['action_sha256'] != plan['core_action_sha256'] or child['target'] != plan['target']
            or plan['native_cwd'] != str(Path(child['home']) / 'Codex')):
        raise ValueError('retained operation escaped its exact transaction')
    plan['action_sha256'] = digest
    return plan


def execute(args):
    plan = load(args.operation_dir)
    if args.operation != 'verify' and args.approve != plan['action_sha256']:
        raise ValueError('separate exact retained action approval required')
    child = argparse.Namespace(operation_dir=Path(plan['operation_dir']) / 'transaction', approve=plan['core_action_sha256'])
    with core.operation_lock(child.operation_dir):
        if args.operation == 'rollback':
            result = core.apply(child, rollback=True)
            core.verify(child)
            return {'status': result['status'], 'retention_applied': False}
        qualification_unchanged(plan)
        if args.operation == 'verify':
            state = core.verify(child)
            if state['status'] == 'verified-preimage':
                return {'status': 'verified-preimage', 'retention_applied': False}
            receipt = json.loads(core.regular(Path(plan['operation_dir']) / 'retained.json'))
            if receipt['action_sha256'] != plan['action_sha256']:
                raise ValueError('retained receipt mismatch')
            observed = catalog(plan)
            core.verify(child)
            qualification_unchanged(plan)
            return {'status': 'verified-retained', 'retention_applied': True, 'native_catalog': observed}
        try:
            core.apply(child)
            core.verify(child)
            observed = catalog(plan)
            core.verify(child)
            qualification_unchanged(plan)
            path = Path(plan['operation_dir']) / 'retained.json'
            receipt = {'action_sha256': plan['action_sha256'], 'native_catalog': observed}
            if core.observation(path)['kind'] == 'absent':
                core.write_once(path, receipt)
            elif json.loads(core.regular(path)) != receipt:
                raise ValueError('retained receipt changed')
            return {'status': 'applied-retained', 'retention_applied': True, 'native_catalog': observed,
                    'native_evidence_revision': EVIDENCE_REVISION, 'model_worker_started': False}
        except BaseException as failure:
            try:
                core.apply(child, rollback=True)
                core.verify(child)
            except BaseException as recovery:
                raise ValueError('retained postcondition failed; exact recovery requires inspection: ' + str(recovery)) from failure
            raise ValueError('retained postcondition failed; exact rollback verified: ' + str(failure)) from failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preview', 'apply', 'verify', 'rollback'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--operation-dir', type=Path, required=True)
    parser.add_argument('--portability-manifest', type=Path)
    parser.add_argument('--native-evidence', type=Path)
    parser.add_argument('--approve')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.operation == 'preview':
            if args.portability_manifest is None or args.native_evidence is None or args.approve is not None:
                raise ValueError('preview requires exact manifest/evidence and is not approval')
            result = preview(args)
        else:
            with core.operation_lock(args.operation_dir):
                result = execute(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'refused', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
