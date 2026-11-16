#!/usr/bin/env python3
"""New-repository sharding contracts. Validation never executes test commands."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, quote

REQUIREMENT = '.github/test-sharding-required.json'
MANIFEST = '.github/test-shards.json'
REQUIRED = {'schema': 'dev-test-sharding-requirement/v1', 'required': True}
SCHEMA = 'dev-test-sharding/v1'

class Refusal(ValueError): pass

def require(condition, reason):
    if not condition: raise Refusal(reason)

def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result

def parse(data):
    try: return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error: raise Refusal('invalid JSON: ' + str(error)) from error

def closed(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields.split()), label + ': invalid fields')

def relative(value, pattern=False):
    require(isinstance(value, str) and bool(value), 'empty path')
    require('\\' not in value and not any(ord(c) < 32 for c in value), 'unsafe path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/')), 'unsafe path')
    require(pattern or not any(c in value for c in '*?[]'), 'test membership must use exact paths')
    return value

def safe_path(root, value):
    relative(value)
    path = root
    for part in PurePosixPath(value).parts:
        path = path / part
        require(not path.is_symlink(), 'symlinked contract/test path')
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'missing regular file: ' + value)
    return path

def git(root, *args, check=True):
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(root), *args],
                            capture_output=True, timeout=20, check=False)
    require(not check or result.returncode == 0, 'Git history unavailable')
    return result

def validate_requirement(value):
    closed(value, 'schema required', 'requirement')
    require(value['schema'] == REQUIRED['schema'] and value['required'] is True, 'invalid sharding requirement')

def requirement(root):
    """The birth commit retains the requirement even if either current file is deleted."""
    current = root / REQUIREMENT
    if current.exists() or current.is_symlink():
        validate_requirement(parse(safe_path(root, REQUIREMENT).read_bytes()))
        return True
    if git(root, 'rev-parse', '--verify', 'HEAD', check=False).returncode:
        return False
    require(git(root, 'rev-parse', '--is-shallow-repository').stdout.strip() == b'false',
            'complete history required to determine sharding requirement')
    roots = git(root, 'rev-list', '--max-parents=0', 'HEAD').stdout.decode().splitlines()
    for revision in roots:
        result = git(root, 'show', revision + ':' + REQUIREMENT, check=False)
        if result.returncode == 0:
            validate_requirement(parse(result.stdout))
            return True
    return False

def bootstrap(root, aggregate):
    require(root.is_dir() and not root.is_symlink(), 'invalid repository root')
    initial = git(root, 'rev-parse', '--verify', 'HEAD', check=False).returncode != 0
    require(initial or requirement(root), 'existing repositories are not automatically retrofitted')
    directory = root / '.github'
    require(not directory.is_symlink(), 'symlinked configuration directory')
    directory.mkdir(exist_ok=True)
    pending = dict(schema=SCHEMA, state='pending', aggregate=aggregate,
                   discovery=dict(include=['test_*.py', 'tests/**/*', 'Tests/**/*'], exclude=[]), shards=[])
    for name, value in ((REQUIREMENT, REQUIRED), (MANIFEST, pending)):
        target = root / name
        if target.exists() or target.is_symlink():
            observed = parse(safe_path(root, name).read_bytes())
            require(observed == value, 'bootstrap preimage changed: ' + name)
        else:
            # O_EXCL and NOFOLLOW preserve foreign state on interrupted/resumed scaffolds.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'w') as handle:
                handle.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return dict(required=True, state='pending', manifest=MANIFEST, activation_allowed=False)

def validate(root, *, activation=False):
    required = requirement(root)
    if not required and not (root / MANIFEST).exists():
        return dict(required=False, state='legacy', activation_allowed=True)
    data = safe_path(root, MANIFEST).read_bytes()
    value = parse(data)
    closed(value, 'schema state aggregate discovery shards', 'manifest')
    require(value['schema'] == SCHEMA, 'unsupported sharding schema')
    require(value['state'] in ('pending', 'configured'), 'invalid sharding state')
    require(value['aggregate'] in ('ci-required', 'pr-automation / verify'), 'invalid aggregate gate')
    closed(value['discovery'], 'include exclude', 'discovery')
    for key, patterns in value['discovery'].items():
        require(isinstance(patterns, list) and len(patterns) <= 100, 'invalid discovery patterns')
        for pattern in patterns: relative(pattern, pattern=True)
    require(value['discovery']['include'], 'test discovery is required')
    require(isinstance(value['shards'], list), 'invalid shards')
    if value['state'] == 'pending':
        require(not value['shards'], 'pending foundation must not claim configured shards')
        require(not activation, 'test sharding pending; verification activation is blocked')
        return dict(required=required, state='pending', manifest=MANIFEST, activation_allowed=False)
    require(2 <= len(value['shards']) <= 32, 'at least two nonempty test shards are required')
    discovered = set()
    for pattern in value['discovery']['include']:
        for path in root.glob(pattern):
            if path.is_symlink(): raise Refusal('symlink in test discovery')
            if path.is_file(): discovered.add(path.relative_to(root).as_posix())
    excluded = set()
    for pattern in value['discovery']['exclude']:
        excluded.update(path.relative_to(root).as_posix() for path in root.glob(pattern) if path.is_file())
    discovered -= excluded
    require(discovered, 'test discovery is empty')
    ids, members = set(), set()
    for shard in value['shards']:
        closed(shard, 'id tests command timeout_seconds', 'shard')
        identity = shard['id']
        require(isinstance(identity, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}', identity), 'invalid shard id')
        require(identity not in ids, 'duplicate shard id')
        ids.add(identity)
        require(type(shard['timeout_seconds']) is int and 1 <= shard['timeout_seconds'] <= 1800, 'invalid timeout')
        command = shard['command']
        require(isinstance(command, list) and 0 < len(command) <= 64 and
                all(isinstance(arg, str) and arg and '\0' not in arg for arg in command), 'missing or invalid shard command')
        require(not command[0].startswith('/') and not any(c in command[0] for c in '\r\n'), 'nonportable executable')
        if '/' in command[0]:
            executable = safe_path(root, command[0])
            require(os.access(executable, os.X_OK), 'shard command is not executable')
        tests = shard['tests']
        require(isinstance(tests, list) and tests, 'empty shard')
        for test in tests:
            relative(test)
            safe_path(root, test)
            require(test not in members, 'duplicate test assignment: ' + test)
            members.add(test)
    require(members == discovered, 'test coverage mismatch; unassigned=' + ','.join(sorted(discovered-members)) +
            '; undiscovered=' + ','.join(sorted(members-discovered)))
    return dict(required=required, state='configured', manifest=MANIFEST,
                contract_sha256=hashlib.sha256(data).hexdigest(), shards=sorted(ids),
                test_files=len(members), aggregate=value['aggregate'], activation_allowed=True)

def validate_reports(contract, reports, revision):
    require(contract.get('state') == 'configured', 'configured contract required')
    require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision), 'exact source revision required')
    require(isinstance(reports, list) and len(reports) == len(contract['shards']), 'missing shard results')
    observed = set()
    for report in reports:
        closed(report, 'schema shard revision contract_sha256 status tests', 'result')
        require(report['schema'] == 'dev-test-shard-result/v1', 'invalid result schema')
        require(report['shard'] in contract['shards'] and report['shard'] not in observed, 'unknown or duplicate result')
        observed.add(report['shard'])
        require(report['revision'] == revision and report['contract_sha256'] == contract['contract_sha256'], 'stale shard result')
        require(report['status'] == 'passed' and type(report['tests']) is int and report['tests'] > 0,
                'failed, skipped, cancelled or empty shard result')
    return dict(status='passed', shards=sorted(observed))

def github(path):
    result = subprocess.run(['gh', 'api', '--hostname', 'github.com', path], capture_output=True, timeout=30)
    require(result.returncode == 0, 'GitHub sharding observation unavailable')
    return parse(result.stdout)

def remote_file(repository, path, revision, request):
    value = request('repos/' + repository + '/contents/' + path + '?' + urlencode(dict(ref=revision)))
    require(isinstance(value, dict) and value.get('type') == 'file' and value.get('encoding') == 'base64', 'remote file unavailable')
    try: return base64.b64decode(value['content'], validate=False)
    except (ValueError, KeyError, TypeError) as error: raise Refusal('invalid remote content') from error

def validate_remote(repository, ref, request=github):
    """Read the recorded requirement's history; a current-file deletion is not an opt-out."""
    require(isinstance(repository, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'invalid repository')
    require(isinstance(ref, str) and bool(ref), 'verified remote ref required')
    commit = request('repos/' + repository + '/commits/' + quote(ref, safe=''))
    revision = commit.get('sha') if isinstance(commit, dict) else None
    require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision), 'invalid observed revision')
    history = request('repos/' + repository + '/commits?' + urlencode(dict(sha=revision, path=REQUIREMENT, per_page=1)))
    require(isinstance(history, list), 'requirement history unavailable')
    if not history:
        return dict(required=False, state='legacy', activation_allowed=True, revision=revision)
    tree = request('repos/' + repository + '/git/trees/' + revision + '?recursive=1')
    require(isinstance(tree, dict) and tree.get('truncated') is False and isinstance(tree.get('tree'), list), 'incomplete repository tree')
    entries = tree['tree']
    require(len(entries) <= 20000, 'repository tree exceeds sharding validation limit')
    # Only tree metadata and the two contracts are materialized, never host data,
    # repository programs or arbitrary source content. The directory is always removed.
    with tempfile.TemporaryDirectory(prefix='dev-sharding-observation-') as directory:
        root = Path(directory)
        for entry in entries:
            require(isinstance(entry, dict), 'invalid tree entry')
            path = relative(entry.get('path'))
            kind, mode = entry.get('type'), entry.get('mode')
            if kind == 'tree': continue
            require(kind == 'blob' and mode in ('100644', '100755'), 'unsupported source symlink/submodule')
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=False)
            target.chmod(0o755 if mode == '100755' else 0o644)
        require((root / REQUIREMENT).is_file(), 'recorded sharding requirement was removed')
        (root / REQUIREMENT).write_bytes(remote_file(repository, REQUIREMENT, revision, request))
        require((root / MANIFEST).is_file(), 'recorded sharding manifest was removed')
        (root / MANIFEST).write_bytes(remote_file(repository, MANIFEST, revision, request))
        result = validate(root, activation=True)
    return dict(result, revision=revision)

def controller_coverage(contract, authority, *, repository, repository_id, assignment, proof):
    if not contract['required']: return
    require(contract['aggregate'] == 'pr-automation / verify', 'runnerless aggregate gate mismatch')
    closed(authority, 'schema repositories', 'controller sharding coverage')
    require(authority['schema'] == 'dev-test-sharding-coverage/v1' and isinstance(authority['repositories'], list), 'invalid coverage authority')
    matches = []
    for record in authority['repositories']:
        closed(record, 'repository repository_id contract_sha256 profile_ref lock_digest shards', 'coverage record')
        if record['repository'] == repository: matches.append(record)
    require(len(matches) == 1, 'new repository requires approved controller shard coverage')
    record = matches[0]
    require(type(record['repository_id']) is int and record['repository_id'] == repository_id, 'coverage repository identity mismatch')
    require(record['contract_sha256'] == contract['contract_sha256'], 'controller coverage contract mismatch')
    require(record['profile_ref'] == assignment['profile_ref'], 'controller coverage profile mismatch')
    require(proof.get('validated') is True and isinstance(proof.get('lock_digest'), str) and
            record['lock_digest'] == proof['lock_digest'], 'controller coverage lock mismatch')
    require(isinstance(record['shards'], list) and sorted(record['shards']) == contract['shards'], 'controller coverage omits shards')

def legacy_preflight(arguments):
    for argument in arguments:
        if argument.startswith('-'): continue
        path = Path(argument).expanduser().absolute()
        if not path.is_dir(): continue
        result = git(path, 'rev-parse', '--show-toplevel', check=False)
        if result.returncode: continue
        root = Path(result.stdout.decode().strip())
        require(not requirement(root), 'new sharded repositories require v3 or native onboarding; legacy activation refused')
    return dict(status='legacy-compatible')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['bootstrap', 'view', 'verify', 'aggregate', 'verify-remote', 'legacy-preflight'])
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--repository')
    parser.add_argument('--ref')
    parser.add_argument('--require', action='store_true', help='Refuse a missing recorded requirement')
    parser.add_argument('--legacy-arguments', nargs=argparse.REMAINDER, default=[])
    parser.add_argument('--activation', action='store_true')
    parser.add_argument('--aggregate', default='ci-required', choices=['ci-required', 'pr-automation / verify'])
    parser.add_argument('--reports', type=Path)
    parser.add_argument('--revision')
    args = parser.parse_args()
    try:
        if args.action == 'legacy-preflight':
            print(json.dumps(legacy_preflight(args.legacy_arguments), sort_keys=True))
            return 0
        if args.action == 'verify-remote':
            result = validate_remote(args.repository, args.ref)
            require(not args.require or result['required'], 'recorded sharding requirement is missing')
            if result['required']:
                require(result['aggregate'] == args.aggregate, 'activation aggregate gate mismatch')
            print(json.dumps(result, sort_keys=True))
            return 0
        require(args.repo is not None, '--repo is required')
        root = args.repo.absolute()
        require(not root.is_symlink(), 'symlinked repository root')
        result = bootstrap(root, args.aggregate) if args.action == 'bootstrap' else validate(root, activation=args.activation)
        if args.action == 'aggregate':
            require(args.reports is not None and bool(args.revision), 'reports and revision are required')
            result = validate_reports(result, parse(args.reports.read_bytes()), args.revision)
        print(json.dumps(result, sort_keys=True))
    except (Refusal, OSError, subprocess.TimeoutExpired) as error:
        print('test-sharding: refused: ' + str(error), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
