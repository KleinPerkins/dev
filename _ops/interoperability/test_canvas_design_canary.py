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
import canvas_design_canary as m

spec = importlib.util.spec_from_file_location('canvas_design_fixture', m.FIXTURE / 'fixture.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@contextmanager
def transaction():
    with tempfile.TemporaryDirectory(prefix='canvas-design-owner-') as raw:
        root = Path(raw).resolve()
        home = root / 'home'
        for shelf in ('.codex/skills', '.agents/skills', '.cursor/skills', '.claude/skills'):
            (home / shelf).mkdir(parents=True)
        source = home / 'dev/capabilities/skills/global/skills/canvas-design'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('synthetic instructions\n')
        config = home / '.codex/config.toml'
        config.write_text('[skills]\n')
        config.chmod(0o600)
        args = Namespace(home=home, operation_dir=root / 'operation', portability_manifest=root / 'manifest.json', approve=None)
        proof = {'desired': {'canvas-design': str(source)},
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
                            target=home / '.codex/skills/canvas-design')


def preview(f):
    value = m.preview(f.args)
    f.args.approve = value['action_sha256']
    return m.load(f.args.operation_dir)


class Profile(unittest.TestCase):
    def test_profile_binds_one_skill_without_modifying_the_accepted_profile(self):
        self.assertEqual(m.SKILLS, ('canvas-design',))
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
                target = f.target if kind != 'agents-alias' else f.home / '.agents/skills/canvas-design'
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
                location = str(f.source) if where == 'source' else '~/.codex/skills/canvas-design/SKILL.md' if where == 'tilde' else str(f.home / ('.' + where) / 'skills/canvas-design')
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
        with tempfile.TemporaryDirectory(prefix='canvas-design-source-') as raw:
            home=Path(raw).resolve();root=home/'dev/capabilities/skills'
            names=['SKILL.md','LICENSE.txt','install.sh','meta.yml','canvas-fonts/font.ttf']
            rows=[];git=[]
            for name in names:
                relative='global/skills/canvas-design/'+name;p=root/relative;p.parent.mkdir(parents=True,exist_ok=True)
                data=('synthetic '+name).encode();p.write_bytes(data)
                blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                rows.append(dict(path=relative,mode='100644',git_blob=blob,sha256=m.sha(data)))
                git.append(('100644 blob '+blob+'\t'+relative).encode()+b'\0')
            with ExitStack() as stack:
                for target,name,value in [(m,'FILE_COUNT',5),(m,'PAYLOAD',m.sha(m.canonical(rows))),
                    (m.atom.shared,'portability_manifest_proof',{'synthetic':True}),
                    (m.atom.shared,'pinned_primary_observation',{'synthetic':True}),
                    (m.atom.shared,'git_bytes',b''.join(git)),(m,'local_dependencies',{'synthetic':True})]:
                    stack.enter_context(patch.object(target,name,return_value=value) if callable(getattr(target,name)) else patch.object(target,name,value))
                yield home,root/'global/skills/canvas-design'

    def test_closed_source_and_font_subdirectory_are_supported(self):
        with self.source() as (home,source):
            proof=m.source_proof(home,home/'manifest')
            self.assertEqual(proof['file_count'],5)
            self.assertEqual(proof['desired'],{'canvas-design':str(source)})

    def test_untracked_file_empty_directory_changed_blob_links_and_missing_font_refuse(self):
        for kind in ('file','directory','changed','symlink','hardlink','missing'):
            with self.subTest(kind=kind),self.source() as (home,source):
                if kind=='file':(source/'extra').write_text('foreign')
                elif kind=='directory':(source/'extra').mkdir()
                elif kind=='changed':(source/'SKILL.md').write_text('changed')
                elif kind=='symlink':(source/'canvas-fonts').rename(source/'moved');(source/'canvas-fonts').symlink_to(source/'moved')
                elif kind=='hardlink':os.link(source/'SKILL.md',source/'extra')
                else:(source/'canvas-fonts/font.ttf').unlink()
                with self.assertRaises((ValueError,OSError)):m.source_proof(home,home/'manifest')


def philosophy():
    return '# Patient Geometry\n\n'+'\n\n'.join(('This movement gives space to repeated forms and the intervals between them. Color follows the quiet rhythm of a season, while typography marks only the necessary coordinates. Careful craft and precise alignment make every return legible without turning the image into an explanation.' for _ in range(4)))+'\n'


class Fixture(unittest.TestCase):
    def test_complete_philosophy_and_bounded_notes_have_only_shape_authority(self):
        self.assertEqual(len(checker.check_texts(philosophy(),'Read actual SKILL.md; used Instrument Sans and Geist Mono; refined spacing.')),2)

    def test_missing_movement_incomplete_paragraphs_and_overlong_notes_refuse(self):
        for body,notes in [('Name\n\nsmall','SKILL.md Instrument Geist'),(philosophy(),'word '*181),(philosophy(),'claims without source')]:
            with self.subTest(body=body[:20],notes=notes[:20]),self.assertRaises(ValueError):checker.check_texts(body,notes)

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix='canvas-fixture-') as raw:
            root=Path(raw).resolve();root.chmod(0o700);fonts=root/'fonts';fonts.mkdir(mode=0o700)
            operation=str(uuid.uuid4());action='b'*64
            payload={'fixture-owner.json':json.dumps(dict(schema='interoperability/canvas-design-fixture/v1',operation_id=operation,action_sha256=action)).encode(),
                'source-notes.json':(m.FIXTURE/'source-notes.json').read_bytes(),'philosophy.md':philosophy().encode(),'worker-notes.md':b'Read actual SKILL.md; used Instrument Sans and Geist Mono; refined spacing.','artwork.pdf':b'synthetic parser seam only'}
            for name,data in payload.items():(root/name).write_bytes(data);(root/name).chmod(0o600)
            digests={}
            for name in checker.FONT_DIGESTS:
                data=('synthetic '+name).encode();(fonts/name).write_bytes(data);(fonts/name).chmod(0o600);digests[name]=hashlib.sha256(data).hexdigest()
            with patch.object(checker,'FONT_DIGESTS',digests),patch.object(checker,'inspect_pdf',return_value={'synthetic_parser_seam':True}):yield root,operation,action

    def test_exact_private_fixture_can_be_observed_without_acceptance(self):
        with self.fixture() as (root,operation,action):
            result=checker.inspect(root,operation,action)
            self.assertFalse(result['native_or_retained_acceptance'])
            self.assertTrue(result['semantic_and_render_review_still_required'])
            self.assertEqual(set(result['output_sha256']),set(m.OUTPUTS))

    def test_wrong_operation_or_action_refuses(self):
        with self.fixture() as (root,operation,action):
            for op,ac in [(str(uuid.uuid4()),action),(operation,'c'*64)]:
                with self.assertRaises(ValueError):checker.inspect(root,op,ac)

    def test_foreign_mode_links_inventory_and_modified_inputs_refuse(self):
        for kind in ('output-mode','output-link','font-link','font-change','license-missing','extra-output','scratch','notes-change','hardlink'):
            with self.subTest(kind=kind),self.fixture() as (root,operation,action):
                p=root/'philosophy.md'
                if kind=='output-mode':p.chmod(0o644)
                elif kind=='output-link':p.rename(root/'moved');p.symlink_to(root/'moved')
                elif kind=='font-link':(root/'fonts').rename(root/'moved');(root/'fonts').symlink_to(root/'moved')
                elif kind=='font-change':(root/'fonts/GeistMono-Regular.ttf').write_bytes(b'changed')
                elif kind=='license-missing':(root/'fonts/GeistMono-OFL.txt').unlink()
                elif kind=='extra-output':(root/'extra.md').write_text('extra')
                elif kind=='scratch':(root/'scratch').mkdir()
                elif kind=='notes-change':(root/'source-notes.json').write_bytes(b'{}')
                else:os.link(p,root/'foreign-alias')
                with self.assertRaises((ValueError,OSError)):checker.inspect(root,operation,action)

    def test_replaced_root_during_parse_is_held_and_foreign_replacement_preserved(self):
        with self.fixture() as (root,operation,action):
            moved=root.with_name(root.name+'-moved')
            def replace(_):
                root.rename(moved);root.mkdir(mode=0o700)
                for name in os.listdir(moved):
                    src=moved/name;dst=root/name
                    if src.is_dir():shutil.copytree(src,dst)
                    else:shutil.copy2(src,dst)
                return {'synthetic_parser_seam':True}
            try:
                with patch.object(checker,'inspect_pdf',side_effect=replace),self.assertRaisesRegex(ValueError,'identity changed'):checker.inspect(root,operation,action)
                self.assertTrue(root.is_dir());self.assertTrue(moved.is_dir())
            finally:shutil.rmtree(moved)

    def test_output_replacement_during_parse_is_held(self):
        with self.fixture() as (root,operation,action):
            def replace(_):
                p=root/'philosophy.md';data=p.read_bytes();p.unlink();p.write_bytes(data);p.chmod(0o600)
                return {'synthetic_parser_seam':True}
            with patch.object(checker,'inspect_pdf',side_effect=replace),self.assertRaisesRegex(ValueError,'identity changed'):checker.inspect(root,operation,action)


class Backend(unittest.TestCase):
    @contextmanager
    def backend(self):
        with tempfile.TemporaryDirectory(prefix='canvas-backend-') as raw:
            home=Path(raw).resolve();fonts=home/'dev/capabilities/skills/global/skills/canvas-design/canvas-fonts';fonts.mkdir(parents=True)
            font_data={}
            for name in m.FONT_FILES:
                data=('synthetic '+name).encode();(fonts/name).write_bytes(data);font_data[name]=m.sha(data)
            backend=home/m.PDF_ROOT;python=backend/m.PDF_PYTHON;python.parent.mkdir(parents=True);python.write_bytes(b'synthetic interpreter')
            relative='python/lib/python3.12/site-packages/synthetic';package=backend/relative;package.mkdir(parents=True);(package/'module.py').write_text('synthetic module')
            digest,count,_=m.dependency_tree(package)
            with patch.object(m,'FONT_FILES',font_data),patch.object(m,'PDF_PYTHON_SHA256',m.sha(python.read_bytes())),patch.object(m,'PDF_TREES',{relative:{'sha256':digest,'files':count}}):yield home,python,package

    def test_exact_backend_is_bound_without_execution_or_native_authority(self):
        with self.backend() as (home,python,package):
            result=m.local_dependencies(home)
            self.assertEqual(result['PDF_render_backend'],'pypdfium2')
            self.assertEqual(sum(r['files'] for r in result['backend_package_trees'].values()),1)
            self.assertFalse(result['whole_OS_arbitrary_workload_or_native_qualification_proven'])

    def test_changed_missing_added_or_linked_backend_inputs_refuse(self):
        for kind in ('python','changed-module','extra-module','missing-module','linked-package','linked-module'):
            with self.subTest(kind=kind),self.backend() as (home,python,package):
                if kind=='python':python.write_bytes(b'foreign interpreter')
                elif kind=='changed-module':(package/'module.py').write_text('changed')
                elif kind=='extra-module':(package/'extra.py').write_text('foreign')
                elif kind=='missing-module':(package/'module.py').unlink()
                elif kind=='linked-package':package.rename(package.with_name('foreign'));package.symlink_to(package.with_name('foreign'))
                else:(package/'module.py').rename(package/'foreign.py');(package/'module.py').symlink_to(package/'foreign.py')
                with self.assertRaises((ValueError,OSError)):m.local_dependencies(home)


if __name__=='__main__':unittest.main()
