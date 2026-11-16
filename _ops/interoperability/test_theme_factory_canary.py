"""One-skill profile isolation, publication recovery and fixture refusal tests."""
from argparse import Namespace
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import types

sys.path.insert(0, str(Path(__file__).parent))
import theme_factory_canary as m

spec = importlib.util.spec_from_file_location('theme_factory_fixture', m.FIXTURE / 'fixture.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@contextmanager
def transaction():
    with tempfile.TemporaryDirectory(prefix='theme-factory-owner-') as raw:
        root = Path(raw).resolve()
        home = root / 'home'
        for shelf in ('.codex/skills', '.agents/skills', '.cursor/skills', '.claude/skills'):
            (home / shelf).mkdir(parents=True)
        source = home / 'dev/capabilities/skills/global/skills/theme-factory'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('synthetic instructions\n')
        config = home / '.codex/config.toml'
        config.write_text('[skills]\n')
        config.chmod(0o600)
        args = Namespace(home=home, operation_dir=root / 'operation', portability_manifest=root / 'manifest.json', approve=None)
        proof = {'desired': {'theme-factory': str(source)},
                 'manifest': {'manifest_path': str(args.portability_manifest)}, 'payload_sha256': m.PAYLOAD}
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, 'home', return_value=home))
            stack.enter_context(patch.object(m, 'LINK_MODE', 0o700 if hasattr(os, 'lchmod') else 0o777))
            stack.enter_context(patch.object(m, 'source_proof', side_effect=lambda *_: copy.deepcopy(proof)))
            stack.enter_context(patch.object(m, 'host_observation', return_value={'build': '23880', 'cli_sha256': m.CLI_SHA256}))
            fake_os = types.SimpleNamespace(**vars(os))
            class FixtureEnvironment(dict):
                # Mock only the in-process host-path observation. Mapping copies
                # used for real child probes retain the actual environment.
                def get(self, key, default=None):
                    return str(home / '.codex') if key == 'CODEX_HOME' else super().get(key, default)
            fake_os.environ = FixtureEnvironment(os.environ)
            stack.enter_context(patch.object(m, 'os', fake_os))
            yield Namespace(root=root, home=home, config=config, source=source, args=args, proof=proof,
                            target=home / '.codex/skills/theme-factory')


def preview(f):
    value = m.preview(f.args)
    f.args.approve = value['action_sha256']
    return m.load(f.args.operation_dir)


class Profile(unittest.TestCase):
    def test_profile_binds_one_skill_without_modifying_the_accepted_profile(self):
        self.assertEqual(m.SKILLS, ('theme-factory',))
        self.assertEqual(m.accepted.SKILLS, ('capability', 'frontend-design'))
        self.assertIsNot(m.WORKER, m.accepted.WORKER)
        for name in ('preview', 'load', 'apply', 'verify', 'rollback', 'unchanged', 'main'):
            self.assertIs(getattr(m, name).__globals__, vars(m))
            self.assertIs(getattr(m, name).__code__, getattr(m.accepted, name).__code__)

    def test_one_worker_scope_is_frozen_and_fixture_outputs_have_no_native_authority(self):
        value = m.workload(Path('/synthetic-operation'))
        self.assertEqual(value['outputs'], list(m.OUTPUTS))
        self.assertTrue(value['semantic_review_required'])
        self.assertFalse(value['automated_shape_checks_are_native_acceptance'])
        self.assertEqual(m.WORKER['count'], 1)
        self.assertEqual(m.WORKER['first_parent_wait_ms'], 60000)
        self.assertEqual(m.WORKER['hard_deadline_ms'], 120000)

    def test_more_workers_or_changed_outputs_refuse_before_publication(self):
        for change in ('workers', 'outputs', 'skills'):
            with self.subTest(change=change), transaction() as f:
                replacement = f.root / 'fixture-source'
                shutil.copytree(m.FIXTURE, replacement)
                p = replacement / 'workload.json'
                brief = json.loads(p.read_bytes())
                if change == 'workers': brief['parent_protocol']['worker_count'] = 2
                elif change == 'outputs': brief['outputs'].append('extra.md')
                else: brief['required_skills'].append('frontend-design')
                p.write_text(json.dumps(brief))
                with patch.object(m, 'FIXTURE', replacement), self.assertRaises(ValueError):
                    m.preview(f.args)
                self.assertEqual(m.observation(f.target), {'kind': 'absent'})

    def test_exact_one_link_lifecycle_and_rollback_never_retains_or_qualifies(self):
        with transaction() as f:
            original = m.preserved(f.home)
            plan = preview(f)
            self.assertEqual(len(plan['targets']), 1)
            self.assertEqual(m.verify(f.args)['status'], 'verified-preimage')
            self.assertEqual(m.apply(f.args)['status'], 'applied-canary')
            self.assertEqual(m.observation(f.target), m.ownership(plan, plan['targets'][0]))
            self.assertEqual(m.apply(f.args)['status'], 'already-applied')
            self.assertFalse(m.verify(f.args)['native_qualified'])
            self.assertFalse(m.verify(f.args)['retention_authorized'])
            self.assertEqual(m.apply(f.args, undo=True)['status'], 'rolled-back')
            self.assertEqual(m.apply(f.args, undo=True)['status'], 'rolled-back')
            self.assertEqual(m.verify(f.args)['status'], 'verified-preimage')
            self.assertEqual(m.preserved(f.home), original)
            with self.assertRaisesRegex(ValueError, 'cannot be replayed'): m.apply(f.args)

    def test_existing_paths_and_aliases_are_preserved(self):
        for kind in ('file', 'directory', 'same-link', 'dangling-link', 'agents-alias'):
            with self.subTest(kind=kind), transaction() as f:
                target = f.target if kind != 'agents-alias' else f.home / '.agents/skills/theme-factory'
                if kind == 'file': target.write_text('foreign bytes')
                elif kind == 'directory': target.mkdir()
                else: target.symlink_to(f.source if kind != 'dangling-link' else f.root / 'missing')
                before = m.observation(target)
                with self.assertRaises(ValueError): m.preview(f.args)
                self.assertEqual(m.observation(target), before)

    def test_wrong_approval_does_not_publish(self):
        with transaction() as f:
            preview(f)
            f.args.approve = '0' * 64
            with self.assertRaises(ValueError): m.apply(f.args)
            self.assertEqual(m.observation(f.target), {'kind': 'absent'})

    def test_native_opt_out_is_preserved(self):
        for where in ('codex', 'agents', 'source', 'tilde'):
            with self.subTest(where=where), transaction() as f:
                location = str(f.source) if where == 'source' else '~/.codex/skills/theme-factory/SKILL.md' if where == 'tilde' else str(f.home / ('.' + where) / 'skills/theme-factory')
                f.config.write_text('[[skills.config]]\npath=' + json.dumps(location) + '\nenabled=false\n')
                before = f.config.read_bytes()
                with self.assertRaisesRegex(ValueError, 'explicitly disabled'): m.preview(f.args)
                self.assertEqual(f.config.read_bytes(), before)

    def test_config_or_source_drift_holds_apply_but_not_exact_rollback(self):
        with transaction() as f:
            preview(f); m.apply(f.args)
            f.config.write_text('# foreign configuration\n')
            f.proof['payload_sha256'] = 'foreign source'
            with self.assertRaises(ValueError): m.apply(f.args)
            self.assertEqual(m.apply(f.args, undo=True)['status'], 'rolled-back')
            self.assertEqual(f.config.read_text(), '# foreign configuration\n')
            with self.assertRaises(ValueError): m.verify(f.args)

    def test_implementation_and_source_notes_drift_hold_apply(self):
        with transaction() as f:
            preview(f)
            replacement = f.root / 'fixture-source'
            shutil.copytree(m.FIXTURE, replacement)
            p = replacement / 'source-notes.json';p.write_bytes(p.read_bytes() + b'\n')
            with patch.object(m, 'FIXTURE', replacement), self.assertRaises(ValueError): m.apply(f.args)
            self.assertEqual(m.observation(f.target), {'kind': 'absent'})

    def test_interrupted_publication_resumes_with_same_owned_inode(self):
        with transaction() as f:
            plan = preview(f)
            real = os.link
            def lost(src, dst, **kwargs):
                real(src, dst, **kwargs)
                raise OSError('lost publication response')
            with patch.object(m.os, 'link', side_effect=lost), self.assertRaises(OSError): m.apply(f.args)
            owned = m.observation(f.target)
            self.assertEqual(owned, m.ownership(plan, plan['targets'][0]))
            self.assertEqual(m.apply(f.args)['status'], 'already-applied')
            self.assertEqual(m.observation(f.target), owned)
            m.apply(f.args, undo=True)

    def test_same_source_foreign_link_is_held_during_rollback(self):
        with transaction() as f:
            preview(f); m.apply(f.args)
            f.target.rename(f.root / 'original-inode')
            f.target.symlink_to(f.source)
            before = m.observation(f.target)
            with self.assertRaisesRegex(ValueError, 'foreign edits preserved'): m.apply(f.args, undo=True)
            self.assertEqual(m.observation(f.target), before)

    def test_new_foreign_staging_is_not_published_or_removed(self):
        with transaction() as f:
            plan = preview(f)
            stage = Path(plan['targets'][0]['staging'])
            stage.write_text('foreign winner')
            with self.assertRaises(ValueError): m.apply(f.args)
            with self.assertRaises(ValueError): m.apply(f.args, undo=True)
            self.assertEqual(stage.read_text(), 'foreign winner')


class Source(unittest.TestCase):
    @contextmanager
    def source(self):
        with tempfile.TemporaryDirectory(prefix='theme-factory-source-') as raw:
            home = Path(raw).resolve();root = home / 'dev/capabilities/skills'
            names = ["LICENSE.txt","SKILL.md","install.sh","meta.yml","theme-showcase.pdf","themes/arctic-frost.md","themes/botanical-garden.md","themes/desert-rose.md","themes/forest-canopy.md","themes/golden-hour.md","themes/midnight-galaxy.md","themes/modern-minimalist.md","themes/ocean-depths.md","themes/sunset-boulevard.md","themes/tech-innovation.md"]
            rows, git = [], []
            for name in names:
                relative = 'global/skills/theme-factory/' + name
                path = root / relative;path.parent.mkdir(parents=True, exist_ok=True)
                data = ('synthetic ' + name).encode();path.write_bytes(data)
                blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                rows.append({'path': relative, 'mode': '100644', 'git_blob': blob, 'sha256': m.sha(data)})
                git.append(('100644 blob ' + blob + '\t' + relative).encode() + b'\0')
            with patch.object(m, 'PAYLOAD', m.sha(m.canonical(rows))), \
                    patch.object(m.atom.shared, 'portability_manifest_proof', return_value={'synthetic': True}), \
                    patch.object(m.atom.shared, 'pinned_primary_observation', return_value={'synthetic': True}), \
                    patch.object(m.atom.shared, 'git_bytes', return_value=b''.join(git)), \
                    patch.object(m, 'local_dependencies', return_value={'synthetic': True}):
                yield home, root / 'global/skills/theme-factory'

    def test_exact_fifteen_file_subdirectory_layout_is_supported(self):
        with self.source() as (home, source):
            proof = m.source_proof(home, home / 'manifest')
            self.assertEqual(proof['file_count'], 15)
            self.assertEqual(proof['desired'], {'theme-factory': str(source)})

    def test_untracked_file_empty_directory_and_changed_blob_refuse(self):
        for kind in ('file', 'directory', 'changed', 'symlink', 'hardlink'):
            with self.subTest(kind=kind), self.source() as (home, source):
                if kind == 'file': (source / 'extra').write_text('foreign')
                elif kind == 'directory': (source / 'extra').mkdir()
                elif kind == 'changed': (source / 'SKILL.md').write_text('changed')
                elif kind == 'symlink': (source / 'themes').rename(source / 'moved');(source / 'themes').symlink_to(source / 'moved')
                else: os.link(source / 'SKILL.md', source / 'extra')
                with self.assertRaises((ValueError, OSError)): m.source_proof(home, home / 'manifest')


def synthetic_outputs():
    return {'botanical.html': '''<!doctype html><html><head><style>
@font-face {font-family: ThemeHeaders;src:url('fonts/DejaVuSerif-Bold.ttf');font-weight:700;}
@font-face {font-family: ThemeBody;src:url('fonts/DejaVuSans.ttf');}
:root {--background:#f5f3ed;--text:#b7472a;--heading:#4a7c59;--accent:#f9a620;}
body {background:var(--background);color:var(--text);font-family:ThemeBody;}
h1 {color:var(--heading);font-family:ThemeHeaders;font-size:32px;}
</style></head><body><main><h1>Seed Library</h1><p>Save a seed, share a season.</p>
<ul><li>Tomato</li><li>Basil</li><li>Marigold</li></ul></main></body></html>''',
        'awaiting-selection.md': 'View the [theme showcase](' + str(Path.home() / 'dev/capabilities/skills/global/skills/theme-factory/theme-showcase.pdf') + '). Which theme would you like? I will wait for your selection.\n',
        'custom-theme.json': json.dumps({'name': 'Seed Workshop', 'colors': {'background': '#f7f4ea', 'text': '#142f43', 'accent': '#d97b42'}, 'fonts': {'headers': 'DejaVu Serif Bold', 'body': 'DejaVu Sans'}, 'applied': False, 'review_required': True}),
        'worker-notes.md': 'Synthetic checker fixture only; not an actual native read. SKILL.md and botanical-garden.md identify the source. The selected case uses Botanical Garden; the unselected case waits, and the custom proposal requires review.\n'}


class Shapes(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix='theme-factory-shapes-') as raw:
            root = Path(raw).resolve();root.chmod(0o700)
            operation_id, action = str(uuid.uuid4()), 'a' * 64
            marker = {'schema': 'interoperability/theme-factory-fixture/v1', 'operation_id': operation_id, 'action_sha256': action}
            data = {name: value.encode() for name, value in synthetic_outputs().items()}
            data.update({'fixture-owner.json': json.dumps(marker).encode(), 'source-notes.json': (m.FIXTURE / 'source-notes.json').read_bytes()})
            for name, value in data.items():
                p = root / name;p.write_bytes(value);p.chmod(0o600)
            (root / 'fonts').mkdir(mode=0o700)
            hashes = {}
            for name in checker.FONT_DIGESTS:
                p = root / 'fonts' / name;p.write_bytes(('synthetic ' + name).encode());p.chmod(0o600)
                hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
            with patch.object(checker, 'FONT_DIGESTS', hashes):
                yield root, operation_id, action

    def test_shape_pass_has_no_native_semantic_timing_or_retention_authority(self):
        with self.fixture() as args:
            result = checker.run(*args)
            self.assertGreaterEqual(result['check_count'], 14)
            self.assertFalse(result['native_or_retained_accepted'])
            self.assertFalse(result['actual_native_source_reads_proven_by_this_check'])
            self.assertFalse(result['worker_timing_or_rollback_proven_by_this_check'])
            self.assertTrue(result['semantic_review_required'])

    def test_marker_operation_and_action_mismatches_refuse(self):
        for value in ('operation', 'action', 'marker'):
            with self.subTest(value=value), self.fixture() as (root, operation, action):
                if value == 'operation': operation = str(uuid.uuid4())
                elif value == 'action': action = 'b' * 64
                else: (root / 'fixture-owner.json').write_text('{}')
                with self.assertRaises(ValueError): checker.run(root, operation, action)

    def test_passive_subheadings_and_small_labels_preserve_shape_authority(self):
        with self.fixture() as args:
            p = args[0] / 'botanical.html'
            p.write_text(p.read_text().replace('<li>Tomato</li>',
                '<li><h3>Tomato</h3><small>Shared seed</small></li>'))
            result = checker.run(*args)
            self.assertFalse(result['native_or_retained_accepted'])
            self.assertFalse(result['actual_native_source_reads_proven_by_this_check'])
            self.assertTrue(result['semantic_review_required'])

    def test_each_final_color_role_can_end_at_the_css_block_boundary(self):
        roles = [('background', '#f5f3ed'), ('text', '#b7472a'),
                 ('heading', '#4a7c59'), ('accent', '#f9a620')]
        original = ':root {--background:#f5f3ed;--text:#b7472a;--heading:#4a7c59;--accent:#f9a620;}'
        for final in roles:
            for ending in ('}', ' \n }'):
                with self.subTest(final=final[0], ending=ending), self.fixture() as args:
                    ordered = [r for r in roles if r != final] + [final]
                    declaration = ':root {' + ';'.join('--' + k + ':' + v for k, v in ordered) + ending
                    p = args[0] / 'botanical.html';html = p.read_text()
                    self.assertIn(original, html)
                    p.write_text(html.replace(original, declaration))
                    self.assertFalse(checker.run(*args)['native_or_retained_accepted'])

    def test_passive_markup_and_unterminated_final_declaration_work_together(self):
        with self.fixture() as args:
            p = args[0] / 'botanical.html'
            p.write_text(p.read_text().replace('<li>Tomato</li>',
                '<li><h3>Tomato</h3><small>Shared seed</small></li>').replace(
                '--accent:#f9a620;}', '--accent:#f9a620}'))
            self.assertTrue(checker.run(*args)['semantic_review_required'])

    def test_new_passive_tags_still_refuse_active_external_and_inline_attributes(self):
        for tag in ('h3', 'small'):
            for attr in ('onclick="alert(1)"', 'src="https://example.invalid/x"',
                         'href="https://example.invalid/x"', 'style="display:none"',
                         'http-equiv="refresh"'):
                with self.subTest(tag=tag, attr=attr), self.fixture() as args:
                    p = args[0] / 'botanical.html'
                    p.write_text(p.read_text().replace('<li>Tomato</li>',
                        '<li><' + tag + ' ' + attr + '>Tomato</' + tag + '></li>'))
                    with self.assertRaises(ValueError): checker.run(*args)

    def test_final_declaration_support_preserves_duplicate_and_bad_value_refusal(self):
        replacements = ('--accent:#f9a620;--accent:#f9a620}',
                        '--accent:#f9a620 garbage}',
                        '--accent:#f9a620 background:#f5f3ed}',
                        '--accent:#f9a620', '--accent:#123456}')
        for after in replacements:
            with self.subTest(after=after), self.fixture() as args:
                p = args[0] / 'botanical.html'
                p.write_text(p.read_text().replace('--accent:#f9a620;}', after))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_passive_markup_does_not_admit_other_active_or_external_tags(self):
        for element in ('<script>alert(1)</script>', '<iframe></iframe>', '<object></object>',
                        '<embed>', '<link>', '<svg></svg>', '<img>'):
            with self.subTest(element=element), self.fixture() as args:
                p = args[0] / 'botanical.html'
                p.write_text(p.read_text().replace('<li>Tomato</li>',
                    '<li><h3>Tomato</h3><small>Shared seed</small>' + element + '</li>'))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_output_set_identity_and_modes_are_enforced(self):
        for kind in ('unknown', 'missing', 'symlink', 'hardlink', 'mode'):
            with self.subTest(kind=kind), self.fixture() as args:
                root = args[0];p = root / 'botanical.html'
                if kind == 'unknown': (root / 'unselected.html').write_text('not authorized')
                elif kind == 'missing': p.unlink()
                elif kind == 'mode': p.chmod(0o644)
                elif kind == 'symlink': p.rename(root / 'other');p.symlink_to(root / 'other')
                else: os.link(p, root / 'other')
                with self.assertRaises((ValueError, OSError)): checker.run(*args)

    def test_font_and_license_modification_aliases_and_extra_files_refuse(self):
        for kind in ('changed-font', 'changed-license', 'extra', 'linked-directory', 'mode', 'hardlink'):
            with self.subTest(kind=kind), self.fixture() as args:
                root = args[0];fonts = root / 'fonts';font = fonts / 'DejaVuSans.ttf'
                if kind == 'changed-font': font.write_bytes(b'changed')
                elif kind == 'changed-license': (fonts / 'LICENSE').write_text('changed')
                elif kind == 'extra': (fonts / 'extra').write_text('extra')
                elif kind == 'mode': font.chmod(0o644)
                elif kind == 'hardlink': os.link(font, fonts / 'extra')
                else: fonts.rename(root / 'other');fonts.symlink_to(root / 'other')
                with self.assertRaises((ValueError, OSError)): checker.run(*args)

    def test_changed_source_notes_and_duplicate_custom_keys_refuse(self):
        for kind in ('notes', 'duplicates'):
            with self.subTest(kind=kind), self.fixture() as args:
                root = args[0]
                if kind == 'notes': (root / 'source-notes.json').write_text('{}')
                else:
                    p = root / 'custom-theme.json';p.write_text(p.read_text().replace('"applied": false', '"applied": false, "applied": false'))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_active_HTML_and_remote_or_unreviewed_resource_regressions_refuse(self):
        replacements = [('<main>', '<script>alert(1)</script><main>'),
                        ('<main>', '<iframe src="https://example.invalid"></iframe><main>'),
                        ('<main>', '<main onclick="alert(1)">'),
                        ('fonts/DejaVuSans.ttf', 'https://example.invalid/font.ttf'),
                        ('fonts/DejaVuSans.ttf', 'file:///private/font.ttf')]
        for before, after in replacements:
            with self.subTest(after=after), self.fixture() as args:
                p = args[0] / 'botanical.html';p.write_text(p.read_text().replace(before, after))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_wrong_color_roles_missing_content_and_unbound_fonts_refuse(self):
        replacements = [('--text:#b7472a;', '--text:#f9a620;'),
                        ('--accent:#f9a620;', '--accent:#f9a620;--accent:#f9a620;'),
                        ('color:var(--text);', 'background-color:var(--text);'),
                        ('Marigold', 'invented seed'),
                        ('ThemeHeaders', 'UnboundHeaders'),
                        ('fonts/DejaVuSans.ttf', 'fonts/other.ttf')]
        for before, after in replacements:
            with self.subTest(after=after), self.fixture() as args:
                p = args[0] / 'botanical.html';p.write_text(p.read_text().replace(before, after))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_unselected_case_must_offer_canonical_showcase_ask_and_wait(self):
        replacements = [('theme-showcase.pdf', 'different.pdf'), ('Which theme would you like?', 'Use this.'),
                        ('I will wait for your selection.', 'Applied immediately.')]
        for before, after in replacements:
            with self.subTest(after=after), self.fixture() as args:
                p = args[0] / 'awaiting-selection.md';p.write_text(p.read_text().replace(before, after))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_custom_theme_requires_review_and_readable_roles(self):
        cases = [('applied', True), ('review_required', False), ('name', 'Wrong theme'),
                 ('fonts', {}), ('colors', {'background': '#ffffff', 'text': '#fafafa', 'accent': '#fafafa'}),
                 ('unknown', 'extra')]
        for key, value in cases:
            with self.subTest(key=key), self.fixture() as args:
                p = args[0] / 'custom-theme.json';v = json.loads(p.read_text());v[key] = value;p.write_text(json.dumps(v))
                with self.assertRaises(ValueError): checker.run(*args)

    def test_changed_output_during_read_is_refused(self):
        with self.fixture() as args:
            original = checker.regular;count = 0
            def changed(path, *a, **kw):
                nonlocal count
                value = original(path, *a, **kw)
                if path.name == 'worker-notes.md':
                    count += 1
                    if count == 1: path.write_text('later edit')
                return value
            with patch.object(checker, 'regular', side_effect=changed), self.assertRaises(ValueError): checker.run(*args)


class Dependencies(unittest.TestCase):
    @contextmanager
    def inputs(self):
        with tempfile.TemporaryDirectory(prefix='theme-factory-dependencies-') as raw:
            home = Path(raw).resolve();fonts = {}
            for relative in m.FONT_FILES:
                p = home / m.FONT_ROOT / relative;p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(('synthetic ' + relative).encode());fonts[relative] = m.sha(p.read_bytes())
            browsers = home / '.local/share/personal-portability/playwright-browsers';browser_hashes = {}
            for relative in m.atom.BROWSER_FILES:
                p = browsers / relative;p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(('synthetic ' + relative).encode());browser_hashes[relative] = m.sha(p.read_bytes())
            with patch.object(m, 'FONT_FILES', fonts), patch.object(m.atom, 'BROWSER_FILES', browser_hashes), \
                    patch.object(m.atom, 'tree_digest', return_value=(m.atom.RUNTIME, 115)):
                yield home

    def test_exact_existing_dependencies_are_observed_without_installing(self):
        with self.inputs() as home:
            result = m.local_dependencies(home)
            self.assertEqual(len(result['fonts']), 3)
            self.assertFalse(result['downloads_or_system_font_installation_authorized'])

    def test_changed_font_license_or_browser_and_links_refuse(self):
        for kind in ('font', 'license', 'browser', 'symlink', 'hardlink', 'runtime'):
            with self.subTest(kind=kind), self.inputs() as home:
                p = home / m.FONT_ROOT / ('LICENSE' if kind == 'license' else 'fonts/truetype/DejaVuSans.ttf')
                if kind == 'browser': p = home / '.local/share/personal-portability/playwright-browsers' / next(iter(m.atom.BROWSER_FILES))
                if kind == 'runtime':
                    with patch.object(m.atom, 'tree_digest', return_value=('0' * 64, 115)), self.assertRaises(ValueError): m.local_dependencies(home)
                    continue
                if kind == 'symlink': p.rename(p.with_suffix('.original'));p.symlink_to(p.with_suffix('.original'))
                elif kind == 'hardlink': os.link(p, p.with_suffix('.other'))
                else: p.write_bytes(b'changed')
                with self.assertRaises((ValueError, OSError)): m.local_dependencies(home)

    def test_parent_HOME_and_CODEX_HOME_environment_are_not_redirected(self):
        before = dict(os.environ)
        with transaction() as fixture:
            self.assertEqual(dict(m.os.environ), before)
            preview(fixture);m.apply(fixture.args);m.apply(fixture.args, undo=True)
        self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main()
