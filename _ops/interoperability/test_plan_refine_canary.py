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
import plan_refine_canary as m
spec = importlib.util.spec_from_file_location('plan_refine_fixture', m.FIXTURE / 'fixture.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

def mutable_fixture_copy(source, destination):
    # Only new, deliberately mutable test copies receive writable permissions.
    result = shutil.copytree(source, destination)
    target = Path(destination).resolve()
    assert target.is_relative_to(Path(tempfile.gettempdir()).resolve())
    target.chmod(0o700)
    for path in target.rglob('*'):
        assert not path.is_symlink()
        path.chmod(0o700 if path.is_dir() else 0o600)
    return result

@contextmanager
def transaction():
    with tempfile.TemporaryDirectory(prefix='plan-refine-owner-') as raw:
        root = Path(raw).resolve()
        home = root / 'home'
        for shelf in ('.codex/skills', '.agents/skills', '.cursor/skills', '.claude/skills'):
            (home / shelf).mkdir(parents=True)
        source = home / 'dev/capabilities/skills/global/skills/plan-refine'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('synthetic instructions\n')
        config = home / '.codex/config.toml'
        config.write_text('[skills]\n')
        config.chmod(384)
        args = Namespace(home=home, operation_dir=root / 'operation', portability_manifest=root / 'manifest.json', approve=None)
        proof = {'desired': {'plan-refine': str(source)}, 'manifest': {'manifest_path': str(args.portability_manifest)}, 'payload_sha256': m.PAYLOAD}
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, 'home', return_value=home))
            stack.enter_context(patch.object(m, 'LINK_MODE', 448 if hasattr(os, 'lchmod') else 511))
            stack.enter_context(patch.object(m, 'source_proof', side_effect=lambda *_: copy.deepcopy(proof)))
            stack.enter_context(patch.object(m, 'host_observation', return_value={'build': '23880', 'cli_sha256': m.CLI_SHA256}))
            fake_os = types.SimpleNamespace(**vars(os))

            class FixtureEnvironment(dict):

                def get(self, key, default=None):
                    return str(home / '.codex') if key == 'CODEX_HOME' else super().get(key, default)
            fake_os.environ = FixtureEnvironment(os.environ)
            stack.enter_context(patch.object(m, 'os', fake_os))
            yield Namespace(root=root, home=home, config=config, source=source, args=args, proof=proof, target=home / '.codex/skills/plan-refine')

def preview(f):
    value = m.preview(f.args)
    f.args.approve = value['action_sha256']
    return m.load(f.args.operation_dir)

class Profile(unittest.TestCase):

    def test_profile_binds_one_skill_without_modifying_the_accepted_profile(self):
        self.assertEqual(m.SKILLS, ('plan-refine',))
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
                mutable_fixture_copy(m.FIXTURE, replacement)
                p = replacement / 'workload.json'
                brief = json.loads(p.read_bytes())
                if change == 'workers':
                    brief['parent_protocol']['worker_count'] = 2
                elif change == 'outputs':
                    brief['outputs'].append('extra.md')
                else:
                    brief['required_skills'].append('frontend-design')
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
            with self.assertRaisesRegex(ValueError, 'cannot be replayed'):
                m.apply(f.args)

    def test_existing_paths_and_aliases_are_preserved(self):
        for kind in ('file', 'directory', 'same-link', 'dangling-link', 'agents-alias'):
            with self.subTest(kind=kind), transaction() as f:
                target = f.target if kind != 'agents-alias' else f.home / '.agents/skills/plan-refine'
                if kind == 'file':
                    target.write_text('foreign bytes')
                elif kind == 'directory':
                    target.mkdir()
                else:
                    target.symlink_to(f.source if kind != 'dangling-link' else f.root / 'missing')
                before = m.observation(target)
                with self.assertRaises(ValueError):
                    m.preview(f.args)
                self.assertEqual(m.observation(target), before)

    def test_wrong_approval_does_not_publish(self):
        with transaction() as f:
            preview(f)
            f.args.approve = '0' * 64
            with self.assertRaises(ValueError):
                m.apply(f.args)
            self.assertEqual(m.observation(f.target), {'kind': 'absent'})

    def test_native_opt_out_is_preserved(self):
        for where in ('codex', 'agents', 'source', 'tilde'):
            with self.subTest(where=where), transaction() as f:
                location = str(f.source) if where == 'source' else '~/.codex/skills/plan-refine/SKILL.md' if where == 'tilde' else str(f.home / ('.' + where) / 'skills/plan-refine')
                f.config.write_text('[[skills.config]]\npath=' + json.dumps(location) + '\nenabled=false\n')
                before = f.config.read_bytes()
                with self.assertRaisesRegex(ValueError, 'explicitly disabled'):
                    m.preview(f.args)
                self.assertEqual(f.config.read_bytes(), before)

    def test_config_or_source_drift_holds_apply_but_not_exact_rollback(self):
        with transaction() as f:
            preview(f)
            m.apply(f.args)
            f.config.write_text('# foreign configuration\n')
            f.proof['payload_sha256'] = 'foreign source'
            with self.assertRaises(ValueError):
                m.apply(f.args)
            self.assertEqual(m.apply(f.args, undo=True)['status'], 'rolled-back')
            self.assertEqual(f.config.read_text(), '# foreign configuration\n')
            with self.assertRaises(ValueError):
                m.verify(f.args)

    def test_implementation_and_source_notes_drift_hold_apply(self):
        with transaction() as f:
            preview(f)
            replacement = f.root / 'fixture-source'
            mutable_fixture_copy(m.FIXTURE, replacement)
            p = replacement / 'source-notes.json'
            p.write_bytes(p.read_bytes() + b'\n')
            with patch.object(m, 'FIXTURE', replacement), self.assertRaises(ValueError):
                m.apply(f.args)
            self.assertEqual(m.observation(f.target), {'kind': 'absent'})

    def test_interrupted_publication_resumes_with_same_owned_inode(self):
        with transaction() as f:
            plan = preview(f)
            real = os.link

            def lost(src, dst, **kwargs):
                real(src, dst, **kwargs)
                raise OSError('lost publication response')
            with patch.object(m.os, 'link', side_effect=lost), self.assertRaises(OSError):
                m.apply(f.args)
            owned = m.observation(f.target)
            self.assertEqual(owned, m.ownership(plan, plan['targets'][0]))
            self.assertEqual(m.apply(f.args)['status'], 'already-applied')
            self.assertEqual(m.observation(f.target), owned)
            m.apply(f.args, undo=True)

    def test_same_source_foreign_link_is_held_during_rollback(self):
        with transaction() as f:
            preview(f)
            m.apply(f.args)
            f.target.rename(f.root / 'original-inode')
            f.target.symlink_to(f.source)
            before = m.observation(f.target)
            with self.assertRaisesRegex(ValueError, 'foreign edits preserved'):
                m.apply(f.args, undo=True)
            self.assertEqual(m.observation(f.target), before)

    def test_new_foreign_staging_is_not_published_or_removed(self):
        with transaction() as f:
            plan = preview(f)
            stage = Path(plan['targets'][0]['staging'])
            stage.write_text('foreign winner')
            with self.assertRaises(ValueError):
                m.apply(f.args)
            with self.assertRaises(ValueError):
                m.apply(f.args, undo=True)
            self.assertEqual(stage.read_text(), 'foreign winner')

class Source(unittest.TestCase):

    @contextmanager
    def source(self):
        with tempfile.TemporaryDirectory(prefix='plan-refine-source-') as raw:
            home = Path(raw).resolve()
            root = home / 'dev/capabilities/skills'
            names = ['SKILL.md', 'install.sh', 'meta.yml', 'tests/test_skill_contract.py']
            rows, git = ([], [])
            for name in names:
                relative = 'global/skills/plan-refine/' + name
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = ('synthetic ' + name).encode()
                path.write_bytes(data)
                blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\x00' + data).hexdigest()
                rows.append({'path': relative, 'mode': '100644', 'git_blob': blob, 'sha256': m.sha(data)})
                git.append(('100644 blob ' + blob + '\t' + relative).encode() + b'\x00')
            with patch.object(m, 'PAYLOAD', m.sha(m.canonical(rows))), patch.object(m.atom.shared, 'portability_manifest_proof', return_value={'synthetic': True}), patch.object(m.atom.shared, 'pinned_primary_observation', return_value={'synthetic': True}), patch.object(m.atom.shared, 'git_bytes', return_value=b''.join(git)), patch.object(m, 'local_dependencies', return_value={'synthetic': True}):
                yield (home, root / 'global/skills/plan-refine')

    def test_exact_four_file_subdirectory_layout_is_supported(self):
        with self.source() as (home, source):
            proof = m.source_proof(home, home / 'manifest')
            self.assertEqual(proof['file_count'], 4)
            self.assertEqual(proof['desired'], {'plan-refine': str(source)})

    def test_untracked_file_empty_directory_and_changed_blob_refuse(self):
        for kind in ('file', 'directory', 'changed', 'symlink', 'hardlink'):
            with self.subTest(kind=kind), self.source() as (home, source):
                if kind == 'file':
                    (source / 'extra').write_text('foreign')
                elif kind == 'directory':
                    (source / 'extra').mkdir()
                elif kind == 'changed':
                    (source / 'SKILL.md').write_text('changed')
                elif kind == 'symlink':
                    (source / 'tests').rename(source / 'moved')
                    (source / 'tests').symlink_to(source / 'moved')
                else:
                    os.link(source / 'SKILL.md', source / 'extra')
                with self.assertRaises((ValueError, OSError)):
                    m.source_proof(home, home / 'manifest')

def synthetic_outputs():
    return {'botanical.html': "<!doctype html><html><head><style>\n@font-face {font-family: ThemeHeaders;src:url('fonts/DejaVuSerif-Bold.ttf');font-weight:700;}\n@font-face {font-family: ThemeBody;src:url('fonts/DejaVuSans.ttf');}\n:root {--background:#f5f3ed;--text:#b7472a;--heading:#4a7c59;--accent:#f9a620;}\nbody {background:var(--background);color:var(--text);font-family:ThemeBody;}\nh1 {color:var(--heading);font-family:ThemeHeaders;font-size:32px;}\n</style></head><body><main><h1>Seed Library</h1><p>Save a seed, share a season.</p>\n<ul><li>Tomato</li><li>Basil</li><li>Marigold</li></ul></main></body></html>", 'awaiting-selection.md': 'View the [theme showcase](' + str(Path.home() / 'dev/capabilities/skills/global/skills/plan-refine/theme-showcase.pdf') + '). Which theme would you like? I will wait for your selection.\n', 'custom-theme.json': json.dumps({'name': 'Seed Workshop', 'colors': {'background': '#f7f4ea', 'text': '#142f43', 'accent': '#d97b42'}, 'fonts': {'headers': 'DejaVu Serif Bold', 'body': 'DejaVu Sans'}, 'applied': False, 'review_required': True}), 'worker-notes.md': 'Synthetic checker fixture only; not an actual native read. SKILL.md and botanical-garden.md identify the source. The selected case uses Botanical Garden; the unselected case waits, and the custom proposal requires review.\n'}
