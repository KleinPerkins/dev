"""Real disposable Git/file observations, owner semantics and boundary refusals."""
from contextlib import redirect_stdout
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import personal_doc_v2_read as m
from test_personal_git import fixture

REPO = 'KleinPerkins/skills'
KEY = '11111111-1111-4111-8111-111111111111'
HEX = 'sha256:' + '0' * 64


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else value.encode())
    return path


def config(**changes):
    value = {'schema': 'doc-warden/config/v2', 'schema_version': 2,
        'repository_key': KEY, 'github_repository_id': None, 'enabled': True,
        'dynamic_defaults': {'rigor': 'auto'}, 'legacy_roots': [],
        'gsd_pin_digest': HEX, 'gsd_interface_digest': HEX,
        'maintenance': {'status': 'current', 'last_checked_revision': None}}
    value.update(changes)
    return value


def item():
    return {'schema': 'doc-warden/roadmap-item/v2', 'id': 'ROAD-synthetic',
        'kind': 'product', 'outcome': 'Synthetic seed-library outcome',
        'priority': 'P1', 'sequence': 3, 'wave': None, 'status': 'backlog',
        'dependencies': {'planned': [], 'observed': []}, 'required_artifacts': [],
        'active_versions': {}, 'active_plan': None, 'blockers': [],
        'next_action': 'classify_rigor', 'completion_evidence': [],
        'freshness': {'source_revision': 'no-head', 'observed_at': '1970-01-01T00:00:00Z'}}


def roadmap(root, items=None):
    return write(root, m.ROADMAP, '# Roadmap\n\n' + m.views.BEGIN
        + m.d.v2.canonical_json({'schema': 'doc-warden/roadmap/v2', 'items': items if items is not None else [item()]}).decode()
        + m.views.END)


def observe(scope, tool, operation='view', *, fleet=False):
    return m.inspect(scope, tool, m.Authority(), operation, fleet=fleet)


def facts(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_ino,
        path.stat().st_mode, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
        for path in root.rglob('*') if path.is_file() and not path.is_symlink()}


def ast_identity(value):
    # Python minors add optional empty AST fields (type_params began in3.12).
    # Omit empty optional fields consistently while retaining false/zero values.
    if isinstance(value, ast.AST):
        return {'node': type(value).__name__, 'fields': {key: ast_identity(child)
            for key, child in ast.iter_fields(value)
            if child is not None and not (isinstance(child, list) and not child)}}
    if isinstance(value, list):
        return [ast_identity(child) for child in value]
    if value is Ellipsis:
        return {'literal': 'Ellipsis'}
    return value


class Views(unittest.TestCase):
    def test_missing_profile_is_migration_required_and_reads_no_roadmap(self):
        with fixture() as (root, scope, tool, _):
            path = roadmap(root)
            path.write_text('not a valid roadmap; must not be read')
            result = observe(scope, tool)
            row = result['rows'][0]
            self.assertTrue(row['available'])
            self.assertEqual(row['owner_status']['profile'], 'v1')
            self.assertEqual(row['owner_view']['migration_status'], 'migration_required')
            self.assertEqual(row['documentation_files_read'], 0)

    def test_active_profile_and_roadmap_preserve_every_source_file_identity(self):
        with fixture() as (root, scope, tool, git):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            roadmap(root)
            before = facts(root)
            row = observe(scope, tool)['rows'][0]
            self.assertEqual(row['owner_status']['profile'], 'v2')
            self.assertTrue(row['owner_status']['write_enabled'])
            self.assertEqual(row['owner_status']['repository'], str(root))
            self.assertEqual(row['owner_view']['items'], [item()])
            self.assertEqual(row['owner_view']['source_revision'], git('rev-parse', 'HEAD').decode())
            self.assertEqual(row['documentation_files_read'], 2)
            self.assertEqual(facts(root), before)

    def test_doctor_does_not_read_roadmap_or_treat_source_status_as_installation(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            write(root, m.ROADMAP, 'malformed but irrelevant to doctor repo')
            result = observe(scope, tool, 'doctor')
            self.assertEqual(result['rows'][0]['documentation_files_read'], 1)
            self.assertNotIn('owner_view', result['rows'][0])
            self.assertTrue(result['central_activation_is_owner_source_status_not_host_runtime_installation'])
            self.assertFalse(result['active_v2_native_or_full_migration_acceptance'])

    def test_disabled_profile_preserves_owner_view_semantics(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config(enabled=False)))
            roadmap(root)
            row = observe(scope, tool)['rows'][0]
            self.assertFalse(row['owner_status']['write_enabled'])
            self.assertEqual(row['owner_status']['migration_status'], 'write_disabled')
            self.assertEqual(row['owner_view']['migration_status'], 'active')
            self.assertEqual(len(row['owner_view']['items']), 1)

    def test_invalid_profile_stays_known_blocked_not_missing(self):
        cases = [b'{"repository_key":"wrong"}', b'{"x":1,"x":2}',
                 m.d.v2.canonical_json(config(unrecognized=True)), b'{"x":1.2}']
        for raw in cases:
            with self.subTest(raw=raw), fixture() as (root, scope, tool, _):
                write(root, m.PROFILE, raw)
                row = observe(scope, tool)['rows'][0]
                self.assertTrue(row['available'])
                self.assertEqual(row['owner_status']['profile'], 'invalid')
                self.assertEqual(row['owner_view']['migration_status'], 'blocked')

    def test_invalid_roadmap_is_known_blocked_not_empty(self):
        cases = ['plain text', m.views.BEGIN + '{}' + m.views.END,
            m.views.BEGIN + json.dumps({'schema':'doc-warden/roadmap/v2','items':[dict(item(), forbidden=True)]}) + m.views.END]
        for raw in cases:
            with self.subTest(raw=raw), fixture() as (root, scope, tool, _):
                write(root, m.PROFILE, m.d.v2.canonical_json(config()))
                write(root, m.ROADMAP, raw)
                row = observe(scope, tool)['rows'][0]
                self.assertTrue(row['available'])
                self.assertTrue(row['known_invalid_view'])
                self.assertEqual(row['owner_view']['schema'], 'doc-warden/error/v2')

    def test_absent_roadmap_keeps_owner_empty_view(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            self.assertEqual(observe(scope, tool)['rows'][0]['owner_view']['items'], [])

    def test_dirty_and_detached_primary_do_not_gain_legacy_baseline_exclusion(self):
        with fixture() as (root, scope, tool, git):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            roadmap(root)
            git('checkout', '--detach', 'HEAD')
            self.assertEqual(observe(scope, tool)['rows'][0]['owner_view']['items'], [item()])

    def test_foreign_origin_refuses_before_reading_documentation(self):
        with fixture() as (root, scope, tool, git):
            git('remote', 'set-url', 'origin', 'git@github.com:Excluded/work.git')
            with patch.object(m.d.DocReader, 'read', side_effect=AssertionError('documentation opened')):
                self.assertFalse(observe(scope, tool)['rows'][0]['available'])


class Boundaries(unittest.TestCase):
    def test_scope_denied_before_any_filesystem_or_authority_access(self):
        for identifier in ['KleinPerkins/dev', 'KleinPerkins/chaos-scheduler', 'Excluded/work', '../outside']:
            with self.subTest(identifier=identifier), patch.object(m.os, 'open', side_effect=AssertionError('opened')), \
                    patch.object(m, 'Authority', side_effect=AssertionError('authority opened')), redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['view', '--repository', identifier]), 2)

    def test_cli_rejects_root_canvas_refresh_apply_and_hook_without_access(self):
        for arguments in [['view','--root','/not-read'], ['view','--canvas','/not-written'],
                ['doctor','--refresh-projections'], ['apply'], ['hook'], ['runtime'], ['draft']]:
            with self.subTest(arguments=arguments), patch.object(m.os, 'open', side_effect=AssertionError('opened')), \
                    patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    m.main(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_document_symlink_hardlink_directory_and_fifo_are_unavailable(self):
        for kind in ['symlink', 'hardlink', 'directory', 'fifo']:
            with self.subTest(kind=kind), fixture() as (root, scope, tool, _):
                write(root, m.PROFILE, m.d.v2.canonical_json(config()))
                path = root / m.ROADMAP
                if kind == 'symlink':
                    path.symlink_to('/not-read/poison')
                elif kind == 'hardlink':
                    other = write(root, 'other.txt', 'not read')
                    os.link(other, path)
                elif kind == 'directory':
                    path.mkdir()
                else:
                    os.mkfifo(path, 0o600)
                self.assertFalse(observe(scope, tool)['rows'][0]['available'])

    def test_generated_memory_and_unrelated_artifact_bodies_not_read(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            roadmap(root)
            write(root, '.planning/agent-learnings.md', 'synthetic private memory marker')
            write(root, '.planning/artifacts/secret.md', 'synthetic unrelated artifact marker')
            original = m.d.DocReader.read
            read_names = []
            def guarded(reader, name):
                read_names.append(name)
                self.assertIn(name, [m.PROFILE, m.ROADMAP])
                return original(reader, name)
            with patch.object(m.d.DocReader, 'read', guarded):
                self.assertTrue(observe(scope, tool)['rows'][0]['available'])
            self.assertEqual(set(read_names), {m.PROFILE, m.ROADMAP})

    def test_late_ignored_document_change_invalidates_result(self):
        with fixture() as (root, scope, tool, git):
            write(root, '.gitignore', '.planning/\n')
            git('add', '.gitignore'); git('commit', '-m', 'synthetic ignore')
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            path = roadmap(root)
            original = m.d.DocReader.check
            changed = False
            def drift(reader):
                nonlocal changed
                if not changed:
                    changed = True
                    path.write_text(path.read_text() + '\nlate foreign edit\n')
                return original(reader)
            with patch.object(m.d.DocReader, 'check', drift):
                self.assertFalse(observe(scope, tool)['rows'][0]['available'])
            self.assertIn('late foreign edit', path.read_text())

    def test_late_directory_member_change_invalidates_result(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            original = m.d.DocReader.check
            changed = False
            def drift(reader):
                nonlocal changed
                if not changed:
                    changed = True
                    write(root, '.planning/new-foreign-file', 'preserve')
                return original(reader)
            with patch.object(m.d.DocReader, 'check', drift):
                self.assertFalse(observe(scope, tool)['rows'][0]['available'])
            self.assertEqual((root/'.planning/new-foreign-file').read_text(), 'preserve')

    def test_head_adapter_never_executes_arbitrary_git_or_another_root(self):
        root = Path('/synthetic/private-snapshot')
        observed = m.HeadObservation(root, 'a'*40)
        self.assertEqual(observed.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True), 'a'*40+'\n')
        for command in [['git','-C',str(root),'fetch'], ['git','-C','/outside','rev-parse','HEAD']]:
            with self.assertRaises(m.g.Refusal):
                observed.check_output(command, text=True)
        with self.assertRaises(m.g.Refusal):
            m.deny_git(root, 'cat-file', 'blob', 'a'*40)

    def test_distinct_observation_namespaces_do_not_mutate_shared_contract(self):
        authority = m.Authority()
        base = m.d.v2.observation_contract(authority.root, m.deny_git)
        one = m.views.observation_contract(base, m.HeadObservation(Path('/one'), 'a'*40))
        two = m.views.observation_contract(base, m.HeadObservation(Path('/two'), 'b'*40))
        self.assertIsNot(one['_repo_status'].__globals__, two['_repo_status'].__globals__)
        self.assertIs(one['_repo_status'].__globals__['SCHEMA_ROOT'], authority.root)
        self.assertIsNone(m.d.v2.SCHEMA_ROOT)


class FleetAndIntent(unittest.TestCase):
    def test_selected_fleet_never_opens_central_catalog_or_held_roots(self):
        with fixture() as (root, scope, tool, _):
            write(root, m.PROFILE, m.d.v2.canonical_json(config()))
            original = m.s.read_regular
            names = []
            def guarded(parent, name, **kwargs):
                names.append(name)
                self.assertNotEqual(name, 'fleet.json')
                return original(parent, name, **kwargs)
            with patch.object(m.s, 'read_regular', guarded):
                result = observe(scope, tool, fleet=True)
            rows = result['owner_fleet_view']['repositories']
            self.assertEqual([row['repository'] for row in rows], [REPO])
            self.assertEqual(rows[0]['repository_key'], KEY)
            self.assertIsNone(rows[0]['repository_id'])
            self.assertFalse(result['consequential_routes_exposed'])

    def test_unavailable_selected_checkout_remains_explicit_in_fleet(self):
        with fixture() as (_, _, tool, _):
            scope = m.s.PersonalScope(repositories=[REPO, 'KleinPerkins/kp-mcp'])
            result = observe(scope, tool, fleet=True)
            rows = result['owner_fleet_view']['repositories']
            self.assertEqual(len(rows), 2)
            missing = next(row for row in rows if row['repository'] == 'KleinPerkins/kp-mcp')
            self.assertFalse(missing['available'])
            self.assertFalse(missing['mutation_eligible'])
            self.assertIsNone(missing['designated_path'])

    def test_doctor_fleet_uses_selected_count_and_preserves_external_dependency(self):
        with fixture() as (_, scope, tool, _):
            value = observe(scope, tool, 'doctor', fleet=True)['owner_fleet_view']
            self.assertEqual(value['repository_count'], 1)
            self.assertEqual(value['runnerless_v2'], 'blocked_external_dependency')

    def test_all_seventeen_owner_examples_are_proposals_never_authority(self):
        self.assertEqual(len(m.views.INTENT_SPECS), 17)
        for spec in m.views.INTENT_SPECS.values():
            with self.subTest(intent=spec.intent), patch.object(m.os, 'open', side_effect=AssertionError('opened')), \
                    patch.object(m.s, 'operator_home', side_effect=AssertionError('home read')):
                value = m.views.map_intent(spec.example, None).as_dict()
                self.assertEqual(value['intent'], spec.intent)
                self.assertTrue(value['proposal_only'])
                self.assertFalse(value['authorized'])
                self.assertEqual(value['repository_writes'], [])

    def test_ambiguous_and_unknown_intent_do_not_choose_or_authorize(self):
        self.assertEqual(m.views.map_intent('Show the repository roadmap and apply the safe repairs.', None).status, 'ambiguous')
        self.assertEqual(m.views.map_intent('An unknown synthetic action.', None).status, 'unmatched')

    def test_even_matching_operation_data_does_not_authorize_apply(self):
        value = m.views.map_intent('Apply the safe repairs.', {
            'operation_id':'11111111-1111-4111-8111-111111111111', 'action_digest':HEX}).as_dict()
        self.assertFalse(value['authorized'])
        self.assertEqual(value['next_action'], 'review_preview_and_confirm')

    def test_intent_cli_never_opens_operator_root_and_bounds_input(self):
        with patch.object(m.os, 'open', side_effect=AssertionError('opened')), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(['intent', 'What are we working on?']), 0)
        self.assertEqual(json.loads(out.getvalue())['intent'], 'view_repo')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['intent', 'x'*8193]), 2)


class Schemas(unittest.TestCase):
    def test_pre312_absence_of_empty_type_parameters_keeps_owner_identity(self):
        node = next(n for n in ast.parse(Path(m.views.__file__).read_text()).body
                    if isinstance(n, ast.ClassDef) and n.name == 'RoadmapView')
        older = copy.deepcopy(node)
        if hasattr(older, 'type_params'):
            del older.type_params
        self.assertEqual(ast_identity(node), ast_identity(older))

    def test_nonempty_semantic_change_does_not_keep_owner_identity(self):
        node = next(n for n in ast.parse(Path(m.views.__file__).read_text()).body
                    if isinstance(n, ast.ClassDef) and n.name == 'RoadmapView')
        changed = copy.deepcopy(node)
        changed.body[-1].value = ast.Constant(value=True)
        self.assertNotEqual(ast_identity(node), ast_identity(changed))

    def test_complete_twenty_three_schema_set_and_hashes(self):
        authority = m.Authority()
        self.assertEqual(authority.root, m.HERE / 'doc_v2_active_schemas/schemas')
        self.assertEqual(len(authority.files), 23)
        authority.check()
        self.assertIn('roadmap.schema.json', authority.files)
        self.assertIn('m3-acceptance.schema.json', authority.files)

    def test_changed_schema_or_extra_member_refuses(self):
        for changed in [False, True]:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as raw:
                authority = m.Authority()
                root = Path(raw).resolve()
                for name, data in authority.files.items():
                    (root/name).write_bytes(data)
                authority.root = root
                if changed:
                    (root/'roadmap.schema.json').write_bytes(b'{}')
                else:
                    (root/'foreign-file').write_bytes(b'preserve')
                with self.assertRaises(m.g.Refusal):
                    authority.check()

    def test_all_twenty_one_owner_definitions_match_frozen_ASTs(self):
        source = Path(m.views.__file__).read_text()
        nodes = {}
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [part.id for part in node.targets if isinstance(part, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            for name in names:
                nodes[name] = node
        self.assertEqual(len(m.views.OWNER_AST_SHA256), 21)
        for identity, expected in m.views.OWNER_AST_SHA256.items():
            name = identity.split(':', 1)[1]
            normalized = json.dumps(ast_identity(nodes[name]), sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected, identity)


if __name__ == '__main__':
    unittest.main()
