"""Fenced personal active-v2 doctor/view observations and proposal-only intents.

This is a dependency toward the full active-v2 distribution, not its replacement
or native acceptance. No previews, apply, hooks, maintenance, authoring runtime,
services, arbitrary roots, legacy state import, or shared publication are exposed.
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

HERE = Path(__file__).absolute().parent
DEPENDENCIES = {
    'personal_documentation.py': 'e42b8fd3453e45768107a811f3e3a3a5e2bea70f198090d59aa569d90c040c0c',
    'personal_doc_v2_views_contract.py': 'ab166eb60a69b338af110bba85734890e200205bb503dfaf81a86e34b4d634bd',
}
if not sys.dont_write_bytecode:
    raise ValueError('personal active-v2 observations require Python -B')
for name, digest in DEPENDENCIES.items():
    path = HERE / name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('personal active-v2 dependency changed')
sys.path.insert(0, str(HERE))
import personal_documentation as d
import personal_doc_v2_views_contract as views
for name in DEPENDENCIES:
    if Path(sys.modules[Path(name).stem].__file__).absolute() != HERE / name:
        raise ValueError('personal active-v2 import root differs')

g, w, s = d.g, d.w, d.s
OWNER_REF = views.OWNER_REF
SCHEMA_SOURCE_SHA256 = 'ea7dcf66f70268acc0b7d3398c4ee78c7744758bde6f99c4d1b4846cb6a1024a'
PROFILE = '.planning/doc-warden.json'
ROADMAP = '.planning/ROADMAP.md'


class Authority:
    """A distinct complete schema set preserves the predecessor's exact closure."""
    def __init__(self):
        self.root = HERE / 'doc_v2_active_schemas/schemas'
        self.source = HERE / 'doc_v2_active_schemas/SOURCE.json'
        self.files = {}
        fd = s.absolute_directory(self.source.parent)
        try:
            raw = s.read_regular(fd, self.source.name)
        finally:
            os.close(fd)
        if g.sha(raw) != SCHEMA_SOURCE_SHA256:
            raise g.Refusal('active-v2-schema-source-changed')
        self.source_raw = raw
        fd = s.absolute_directory(self.root)
        try:
            source = d.strict_json(raw)
            if (set(source) != {'schema', 'owner_ref', 'files'}
                    or source['schema'] != 'personal-portability/active-v2-schema-source/v1'
                    or source['owner_ref'] != OWNER_REF):
                raise g.Refusal('active-v2-schema-source-held')
            names = [row['name'] for row in source['files']]
            if len(names) != 23 or len(set(names)) != 23 or set(os.listdir(fd)) != set(names):
                raise g.Refusal('active-v2-schema-members-held')
            for row in source['files']:
                if (set(row) != {'name', 'sha256', 'git_blob'}
                        or re.fullmatch(r'[a-z0-9-]+\.schema\.json', row['name']) is None):
                    raise g.Refusal('active-v2-schema-name-held')
                data = s.read_regular(fd, row['name'])
                blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                if g.sha(data) != row['sha256'] or blob != row['git_blob']:
                    raise g.Refusal('active-v2-schema-bytes-changed')
                self.files[row['name']] = data
        finally:
            os.close(fd)

    def check(self):
        fd = s.absolute_directory(self.source.parent)
        try:
            if s.read_regular(fd, self.source.name) != self.source_raw:
                raise g.Refusal('active-v2-schema-source-changed')
        finally:
            os.close(fd)
        fd = s.absolute_directory(self.root)
        try:
            if set(os.listdir(fd)) != set(self.files):
                raise g.Refusal('active-v2-schema-members-changed')
            for name, old in self.files.items():
                if s.read_regular(fd, name) != old:
                    raise g.Refusal('active-v2-schema-changed')
        finally:
            os.close(fd)


class HeadObservation:
    """Supply one already-qualified HEAD; never execute an owner subprocess."""
    def __init__(self, root, head):
        if re.fullmatch(r'[0-9a-f]{40}', head) is None:
            raise g.Refusal('active-v2-head-held')
        self.root, self.head = root, head
        self.calls = 0

    def check_output(self, command, *, text):
        expected = ['git', '-C', str(self.root), 'rev-parse', 'HEAD']
        if command != expected or text is not True or self.calls >= 8:
            raise g.Refusal('active-v2-process-outside-closed-head-contract')
        self.calls += 1
        return self.head + '\n'


def deny_git(*args, **kwargs):
    raise g.Refusal('active-v2-view-provenance-process-not-supported')


def snapshot_file(reader, root, relative):
    state = reader.state(relative)
    if state is None:
        return False
    if state['type'] != stat.S_IFREG:
        raise g.Refusal('active-v2-view-input-type-held')
    raw = reader.read(relative)
    if raw is None:
        raise g.Refusal('active-v2-view-input-unavailable')
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as file:
        file.write(raw)
    return True


def inspect_repository(repo, tool, authority, operation):
    if operation not in {'doctor', 'view'}:
        raise g.Refusal('active-v2-read-operation-held')
    tree = w.PersonalWorktree(repo, tool)
    before = tree.observe()
    reader = d.DocReader(tree)
    temporary_parent = '/private/tmp' if sys.platform == 'darwin' else '/tmp'
    with tree.git.private_gitdir(worktree_controls=True), tempfile.TemporaryDirectory(
            prefix='personal-active-v2-read-', dir=temporary_parent) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        snapshot_file(reader, root, PROFILE)
        process = HeadObservation(root, before['head'])
        base = d.v2.observation_contract(authority.root, deny_git)
        contract = views.observation_contract(base, process)
        status = contract['_repo_status'](root)
        # The source status is evaluated on the private snapshot. Its repository
        # label is explicitly projected back onto the fenced source identity.
        status['repository'] = str(repo.path)
        value = {'id': repo.row['id'], 'relative_path': repo.row['path'],
                 'head': before['head'], 'pin_matches': before['pin_matches'],
                 'available': True, 'owner_status': status,
                 'observation_transport': 'fenced private file snapshot and qualified HEAD'}
        if operation == 'view':
            if status['profile'] != 'v2':
                value['owner_view'] = {'schema': 'doc-warden/roadmap-view/v2', 'repository_key': None,
                    'source_revision': before['head'], 'migration_status': status['migration_status'], 'items': []}
                if 'reason' in status:
                    value['owner_view']['reason'] = status['reason']
            else:
                snapshot_file(reader, root, ROADMAP)
                try:
                    config = contract['read_repository_config'](root)
                    observed = contract['roadmap_view'](root, config['repository_key'])
                    value['owner_view'] = {'schema': 'doc-warden/roadmap-view/v2',
                        'repository_key': observed.repository_key, 'source_revision': observed.source_revision,
                        'migration_status': 'active', 'items': list(observed.items)}
                except ValueError as error:
                    reason = str(error)
                    code = reason if re.fullmatch(r'[a-z][a-z0-9_]*', reason) else 'invalid_input'
                    value['owner_view'] = {'schema': 'doc-warden/error/v2', 'status': 'blocked',
                        'code': code, 'checked': ['closed_cli_contract'], 'uncertain': [code],
                        'next_action': 'correct_input_and_retry', 'repository_writes': [],
                        'message': ('I checked the closed doc-warden CLI contract. The requested '
                            f'operation is uncertain because {code}. Next action: '
                            'correct the named input or precondition and retry.')}
                    value['known_invalid_view'] = True
        reader.check()
        tree.git.finish()
        tree.unchanged()
        authority.check()
        after = w.PersonalWorktree(repo, tool).observe()
        if d.stable(before) != d.stable(after):
            raise g.Refusal('active-v2-primary-observation-changed')
        reader.check()
        tree.git.finish()
        authority.check()
        value.update(document_evidence_sha256=reader.digest(), documentation_files_read=len(reader.cache),
                     generated_memory_contents_read=False, source_or_configuration_writes=False)
        return value


def inspect(scope, tool, authority, operation, *, fleet=False):
    if operation not in {'doctor', 'view'} or type(fleet) is not bool:
        raise g.Refusal('active-v2-read-operation-held')
    rows = []
    authority.check()
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:
                row = inspect_repository(repo, tool, authority, operation)
        except (ValueError, OSError, UnicodeError, RecursionError):
            row = {'id': target['id'], 'relative_path': target['path'], 'available': False,
                   'classification': 'UNAVAILABLE', 'source_or_configuration_writes': False}
        rows.append(row)
    authority.check()
    result = {'schema': 'personal-portability/personal-active-v2-read/v1', 'owner_ref': OWNER_REF,
        'operation': operation, 'rows': rows, 'scope': 'selected exact manifest personal primaries only',
        'central_activation_is_owner_source_status_not_host_runtime_installation': True,
        'network_requests': 0, 'source_or_configuration_writes': False, 'new_model_workers': 0,
        'new_shared_links': 0, 'generated_memory_contents_read': False, 'legacy_state_imported': False,
        'consequential_routes_exposed': False, 'active_v2_native_or_full_migration_acceptance': False}
    if fleet:
        observations = []
        for row in rows:
            status = row.get('owner_status', {})
            observations.append(views.CheckoutObservation(repository=row['id'], repository_id=None,
                path=str(scope.home / 'dev' / row['relative_path']) if row['available'] else None,
                available=row['available'], reason=None if row['available'] else 'scoped_observation_unavailable',
                owner='KleinPerkins', next_action='inspect_current_checkout' if row['available'] else 'correct_scoped_observation',
                repository_key=status.get('repository_key')))
        repositories = views.deduplicate_observations(observations)
        result['fleet_source'] = 'Original manifest-selected personal cohort; central mixed catalog not opened'
        if operation == 'view':
            result['owner_fleet_view'] = views.render_fleet_snapshot(repositories, source_revision=OWNER_REF)
        else:
            result['owner_fleet_view'] = {'schema': 'doc-warden/fleet-preview/v2', 'status': 'preview',
                'repository_count': len(repositories), 'runnerless_v2': 'blocked_external_dependency',
                'read_only': True, 'repository_writes': []}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for name in ('doctor', 'view'):
        sub = commands.add_parser(name)
        sub.add_argument('--repository', action='append')
        sub.add_argument('--fleet', action='store_true')
    intent = commands.add_parser('intent')
    intent.add_argument('utterance')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'intent':
            if len(args.utterance.encode('utf-8')) > 8192:
                raise g.Refusal('active-v2-intent-input-bound')
            result = views.map_intent(args.utterance, None).as_dict()
            print(json.dumps(result, sort_keys=True))
            return 0
        selected = s.selected_ids(args.repository)
        authority = Authority()
        result = inspect(s.PersonalScope(repositories=selected), g.GitTool(), authority, args.operation, fleet=args.fleet)
        print(json.dumps(result, sort_keys=True))
        if any(not row['available'] for row in result['rows']):
            return 2
        return 1 if any(row.get('known_invalid_view') for row in result['rows']) else 0
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError):
        print(json.dumps({'status': 'refused', 'reason': 'personal-active-v2-authority-scope-or-input-unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
