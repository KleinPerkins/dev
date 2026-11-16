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

sys.path.insert(0, str(Path(__file__).parent))
import internal_comms_canary as m

spec = importlib.util.spec_from_file_location('internal_comms_fixture', m.FIXTURE / 'fixture.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@contextmanager
def transaction():
    with tempfile.TemporaryDirectory(prefix='internal-comms-owner-') as raw:
        root = Path(raw).resolve()
        home = root / 'home'
        for shelf in ('.codex/skills', '.agents/skills', '.cursor/skills', '.claude/skills'):
            (home / shelf).mkdir(parents=True)
        source = home / 'dev/capabilities/skills/global/skills/internal-comms'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('synthetic instructions\n')
        config = home / '.codex/config.toml'
        config.write_text('[skills]\n')
        config.chmod(0o600)
        args = Namespace(home=home, operation_dir=root / 'operation', portability_manifest=root / 'manifest.json', approve=None)
        proof = {'desired': {'internal-comms': str(source)},
                 'manifest': {'manifest_path': str(args.portability_manifest)}, 'payload_sha256': m.PAYLOAD}
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, 'home', return_value=home))
            stack.enter_context(patch.object(m, 'LINK_MODE', 0o700 if hasattr(os, 'lchmod') else 0o777))
            stack.enter_context(patch.object(m, 'source_proof', side_effect=lambda *_: copy.deepcopy(proof)))
            stack.enter_context(patch.object(m, 'host_observation', return_value={'build': '23880', 'cli_sha256': m.CLI_SHA256}))
            stack.enter_context(patch.dict(os.environ, {'CODEX_HOME': str(home / '.codex')}))
            yield Namespace(root=root, home=home, config=config, source=source, args=args, proof=proof,
                            target=home / '.codex/skills/internal-comms')


def preview(f):
    value = m.preview(f.args)
    f.args.approve = value['action_sha256']
    return m.load(f.args.operation_dir)


class Profile(unittest.TestCase):
    def test_profile_binds_one_skill_without_modifying_the_accepted_profile(self):
        self.assertEqual(m.SKILLS, ('internal-comms',))
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
                target = f.target if kind != 'agents-alias' else f.home / '.agents/skills/internal-comms'
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
                location = str(f.source) if where == 'source' else '~/.codex/skills/internal-comms/SKILL.md' if where == 'tilde' else str(f.home / ('.' + where) / 'skills/internal-comms')
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
        with tempfile.TemporaryDirectory(prefix='internal-comms-source-') as raw:
            home = Path(raw).resolve();root = home / 'dev/capabilities/skills'
            names = ['LICENSE.txt', 'SKILL.md', 'examples/3p-updates.md', 'examples/company-newsletter.md',
                     'examples/faq-answers.md', 'examples/general-comms.md', 'install.sh', 'meta.yml']
            rows, git = [], []
            for name in names:
                relative = 'global/skills/internal-comms/' + name
                path = root / relative;path.parent.mkdir(parents=True, exist_ok=True)
                data = ('synthetic ' + name).encode();path.write_bytes(data)
                blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                rows.append({'path': relative, 'mode': '100644', 'git_blob': blob, 'sha256': m.sha(data)})
                git.append(('100644 blob ' + blob + '\t' + relative).encode() + b'\0')
            with patch.object(m, 'PAYLOAD', m.sha(m.canonical(rows))), \
                    patch.object(m.atom.shared, 'portability_manifest_proof', return_value={'synthetic': True}), \
                    patch.object(m.atom.shared, 'pinned_primary_observation', return_value={'synthetic': True}), \
                    patch.object(m.atom.shared, 'git_bytes', return_value=b''.join(git)):
                yield home, root / 'global/skills/internal-comms'

    def test_exact_eight_file_subdirectory_layout_is_supported(self):
        with self.source() as (home, source):
            proof = m.source_proof(home, home / 'manifest')
            self.assertEqual(proof['file_count'], 8)
            self.assertEqual(proof['desired'], {'internal-comms': str(source)})

    def test_untracked_file_empty_directory_and_changed_blob_refuse(self):
        for kind in ('file', 'directory', 'changed', 'symlink', 'hardlink'):
            with self.subTest(kind=kind), self.source() as (home, source):
                if kind == 'file': (source / 'extra').write_text('foreign')
                elif kind == 'directory': (source / 'extra').mkdir()
                elif kind == 'changed': (source / 'SKILL.md').write_text('changed')
                elif kind == 'symlink': (source / 'examples').rename(source / 'moved');(source / 'examples').symlink_to(source / 'moved')
                else: os.link(source / 'SKILL.md', source / 'extra')
                with self.assertRaises((ValueError, OSError)): m.source_proof(home, home / 'manifest')


def synthetic_outputs():
    notes = json.loads((m.FIXTURE / 'source-notes.json').read_bytes())
    facts = notes['newsletter_facts']
    newsletter = []
    for n, row in enumerate(facts):
        if n % 5 == 0: newsletter.append('## Company updates ' + str(n//5 + 1))
        text = row['text'].split(';')[0].rstrip('.')
        newsletter.append('- ' + text + '. [' + row['id'] + '](' + row['url'] + ')')
    answers = [
        'All 1,008 synthetic accounts can access Seed Hub. [Source](' + facts[0]['url'] + ')',
        'Saved seed lists remain stored during maintenance. [Source](' + facts[4]['url'] + ')',
        'The shared handbook contains the accessibility guide. [Source](' + facts[11]['url'] + ')',
        'The release date is unconfirmed; the project owner must provide an official response. [Source](' + facts[19]['url'] + ')']
    return {'3p-update.md': '🌱 Canopy Tools (2026-10-26 to 2026-11-01)\nProgress: We shipped Seed Hub to 1,008 synthetic accounts on October 30.\nPlans: We will review translation coverage next week.\nProblems: Translation review needs a volunteer editor.\n',
        'newsletter.md': '\n'.join(newsletter) + '\n',
        'faq.md': '\n'.join(line for pair in zip(notes['faq_questions'], answers) for line in ('- *Question*: ' + pair[0], '- *Answer*: ' + pair[1])) + '\n',
        'announcement.md': '# Seed Hub maintenance\n\nOn November 4 at 09:00 UTC, planned maintenance will last 2 minutes.\n\nPlease save your drafts before maintenance.\n',
        'clarification.md': 'Who is the audience, what is the purpose, and which tone and format should the communication use?\n',
        'worker-notes.md': 'Synthetic shape fixture only; no native source reads are claimed. ' + ', '.join(checker.GUIDES) + '\n'}


class Shapes(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix='internal-comms-shapes-') as raw:
            root = Path(raw).resolve();root.chmod(0o700)
            operation_id, action = str(uuid.uuid4()), 'a' * 64
            marker = {'schema': 'interoperability/internal-comms-fixture/v1', 'operation_id': operation_id, 'action_sha256': action}
            data = {name: value.encode() for name, value in synthetic_outputs().items()}
            data.update({'fixture-owner.json': json.dumps(marker).encode(), 'source-notes.json': (m.FIXTURE / 'source-notes.json').read_bytes()})
            for name, value in data.items():
                p = root / name;p.write_bytes(value);p.chmod(0o600)
            yield root, operation_id, action

    def test_shape_pass_does_not_prove_native_behavior_or_semantic_acceptance(self):
        with self.fixture() as args:
            result = checker.run(*args)
            self.assertGreater(result['check_count'], 30)
            self.assertTrue(result['semantic_review_required'])
            self.assertFalse(result['actual_native_source_reads_proven_by_this_check'])
            self.assertFalse(result['worker_timing_or_rollback_proven_by_this_check'])
            self.assertFalse(result['native_or_retained_accepted'])

    def test_wrong_action_or_operation_binding_refuses(self):
        with self.fixture() as (root, identifier, action):
            for other_id, other_action in [(str(uuid.uuid4()), action), (identifier, 'b' * 64)]:
                with self.assertRaises(ValueError): checker.run(root, other_id, other_action)

    def test_unknown_missing_symlink_hardlink_and_nonprivate_outputs_refuse(self):
        for kind in ('extra', 'missing', 'link', 'shared', 'mode', 'directory', 'nonutf8', 'oversize'):
            with self.subTest(kind=kind), self.fixture() as (root, identifier, action):
                p = root / 'announcement.md'
                if kind == 'extra': (root / 'foreign').write_text('preserve')
                elif kind == 'missing': p.unlink()
                elif kind == 'link': p.unlink();p.symlink_to(root / 'newsletter.md')
                elif kind == 'shared': os.link(p, root.parent / (root.name + '-shared'))
                elif kind == 'mode': p.chmod(0o644)
                elif kind == 'directory': p.unlink();p.mkdir()
                elif kind == 'nonutf8': p.write_bytes(b'\xff')
                else: p.write_bytes(b'x' * 32769)
                try:
                    with self.assertRaises((ValueError, OSError, UnicodeError)): checker.run(root, identifier, action)
                finally:
                    if kind == 'shared': (root.parent / (root.name + '-shared')).unlink()

    def test_unsafe_or_changed_source_links_and_source_notes_refuse(self):
        with self.fixture() as (root, identifier, action):
            p = root / 'newsletter.md';p.write_text(p.read_text().replace('example.invalid', 'unexpected.example'))
            with self.assertRaises(ValueError): checker.run(root, identifier, action)
        with self.fixture() as (root, identifier, action):
            p = root / 'source-notes.json';p.write_bytes(p.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'source notes changed'): checker.run(root, identifier, action)

    def test_formatting_context_uncertainty_and_source_coverage_regressions_refuse(self):
        changes = [('3p-update.md', lambda s: s.replace('Problems:', 'Risks:')),
            ('3p-update.md', lambda s: s.replace('1,008', '1,009')),
            ('newsletter.md', lambda s: s.replace('- We shipped', 'We shipped', 1)),
            ('faq.md', lambda s: s.replace('unconfirmed', 'confirmed')),
            ('announcement.md', lambda s: s.replace('09:00 UTC', '10:00 UTC')),
            ('clarification.md', lambda s: s.replace('audience', 'readers')),
            ('worker-notes.md', lambda s: s.replace('general-comms.md', 'other.md'))]
        for name, change in changes:
            with self.subTest(name=name), self.fixture() as (root, identifier, action):
                p = root / name;p.write_text(change(p.read_text()))
                with self.assertRaises(ValueError): checker.run(root, identifier, action)


if __name__ == '__main__':
    unittest.main()
