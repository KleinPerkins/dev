"""Canonical hook/memory outcomes and refusal-before-content fixtures."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_controls as m
from test_personal_git import fixture
g,w=m.g,m.w
GUARD=Path(__file__).parents[1]/'hooks/registration-guard'


def observe(scope,tool):
    with scope.repository('KleinPerkins/skills') as repo:return m.PersonalControls(repo,tool).observe()


def active(root,path='.git/hooks',*,guard=True):
    directory=root/path;directory.mkdir(parents=True,exist_ok=True)
    pc=directory/'pre-commit'
    pc.write_bytes(b'#!/bin/sh\n# '+m.GUARD_MARKER+b'\nexit 99\n');pc.chmod(0o700)
    if guard:
        data=GUARD.read_bytes();assert hashlib.sha256(data).hexdigest()==m.REGISTRATION_SHA256
        (directory/'registration-guard').write_bytes(data);(directory/'registration-guard').chmod(0o700)
    return directory


def tracked_agents(root,git,text):
    (root/'AGENTS.md').write_text(text);git('add','AGENTS.md');git('commit','-m','synthetic tracked control')


class HookPaths(unittest.TestCase):
    def test_relative_and_exact_absolute_paths_normalize_without_expanding(self):
        root=Path('/synthetic/personal')
        for value,expected in [('./hooks//','hooks'),('.', ''),('/synthetic/personal/hooks','hooks'),('/synthetic/personal','')]:
            self.assertEqual(m.hook_path(value,root),expected)
        for value in [None,'~/hooks','%(prefix)/hooks','../hooks','hooks/../other','/outside/hooks','affirm/hooks','chaos-scheduler/hooks','agent-learnings.md/hooks','a\nb']:
            with self.subTest(value=value),self.assertRaises(g.Refusal):m.hook_path(value,root)


class Hooks(unittest.TestCase):
    def test_missing_guard_is_advisory_without_installing(self):
        with fixture() as (root,scope,tool,_):
            before=(root/'.git/config').read_bytes();r=observe(scope,tool)
            self.assertEqual(r['hooks']['canonical_guard_state'],'missing')
            self.assertEqual(r['controls_verdict'],'ADVISORY');self.assertTrue(r['controls_available'])
            self.assertFalse((root/'.git/hooks/pre-commit').exists())
            self.assertEqual((root/'.git/config').read_bytes(),before)
            self.assertFalse(r['complete_doctor_or_native_qualification'])

    def test_exact_active_marker_and_owner_guard_are_structural_not_execution(self):
        with fixture() as (root,scope,tool,_):
            directory=active(root);sentinel=root/'HOOK_WAS_EXECUTED'
            (directory/'pre-commit').write_bytes(b'#!/bin/sh\n# '+m.GUARD_MARKER+b'\ntouch "'+str(sentinel).encode()+b'"\nexit 99\n')
            r=observe(scope,tool)
            self.assertEqual(r['hooks']['canonical_guard_state'],'active')
            self.assertEqual(r['hooks']['registration_guard'],'current')
            self.assertEqual(r['hooks']['verdict'],'OK');self.assertFalse(r['hooks']['hook_execution_proven'])
            self.assertFalse(sentinel.exists())

    def test_relative_absolute_root_and_worktree_overlay_hook_paths(self):
        for kind in ['relative','absolute','root','overlay']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                path='.' if kind=='root' else 'custom';active(root,path)
                if kind=='overlay':
                    git('config','extensions.worktreeConfig','true')
                    git('config','--worktree','core.hooksPath','custom')
                else:git('config','core.hooksPath',str(root/path) if kind=='absolute' else path)
                result=observe(scope,tool);self.assertEqual(result['hooks']['verdict'],'OK')

    def test_custom_foreign_and_inert_overrides_preserve_original_verdicts(self):
        for path,kind,level in [('custom','inert-hookspath','DRIFT'),('.husky/_','foreign-hookspath','ADVISORY'),('lefthook','foreign-hookspath','ADVISORY')]:
            with self.subTest(path=path),fixture() as (_,scope,tool,git):
                git('config','core.hooksPath',path);r=observe(scope,tool)['hooks']
                self.assertEqual((r['canonical_guard_state'],r['verdict']),(kind,level));self.assertTrue(r['available'])

    def test_null_hooks_path_is_known_inert_without_outside_access(self):
        with fixture() as (_,scope,tool,git):
            git('config','core.hooksPath','/dev/null');r=observe(scope,tool)['hooks']
            self.assertEqual((r['canonical_guard_state'],r['verdict']),('inert-hookspath','DRIFT'))

    def test_external_and_protected_paths_are_held_before_control_reader(self):
        for path in ['/outside/PRIVATE_SYNTHETIC','~/hooks','affirm/hooks','chaos-scheduler/hooks']:
            with self.subTest(path=path),fixture() as (_,scope,tool,git):
                git('config','core.hooksPath',path)
                with patch.object(m.Reader,'read',side_effect=AssertionError('control reader entered')):
                    r=observe(scope,tool)
                self.assertFalse(r['controls_available']);self.assertEqual(r['hooks']['canonical_guard_state'],'unavailable')
                self.assertNotIn('PRIVATE_SYNTHETIC',json.dumps(r))

    def test_nested_checkout_hooks_are_not_read(self):
        with fixture() as (root,scope,tool,git):
            nested=root/'nested';nested.mkdir();(nested/'.git').symlink_to('/not-followed')
            os.mkfifo(nested/'pre-commit',0o600);git('config','core.hooksPath','nested')
            r=observe(scope,tool);self.assertFalse(r['hooks']['available'])
            self.assertEqual(r['hooks']['reason'],'nested-control-pointer-held')

    def test_active_missing_stale_and_nonexecutable_guards_are_advisory(self):
        for kind in ['missing','stale','dispatcher-nonexec','guard-nonexec','other-exec-only']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                directory=active(root,guard=kind!='missing')
                if kind=='stale':(directory/'registration-guard').write_text('synthetic stale')
                if kind=='dispatcher-nonexec':(directory/'pre-commit').chmod(0o600)
                if kind=='guard-nonexec':(directory/'registration-guard').chmod(0o600)
                if kind=='other-exec-only':(directory/'pre-commit').chmod(0o601)
                r=observe(scope,tool)['hooks'];self.assertEqual(r['canonical_guard_state'],'active')
                self.assertEqual(r['verdict'],'ADVISORY')
                if kind in ['missing','stale']:self.assertEqual(r['registration_guard'],kind)

    def test_symlink_hardlink_special_and_parent_aliases_stay_unavailable(self):
        for kind in ['link','hardlink','FIFO','parent']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                directory=root/'custom';directory.mkdir();p=directory/'pre-commit'
                if kind=='parent':
                    directory.rmdir();directory.symlink_to('/not-followed')
                elif kind=='link':p.symlink_to('/not-read')
                elif kind=='hardlink':
                    source=root/'synthetic';source.write_text('synthetic');os.link(source,p)
                else:os.mkfifo(p,0o600)
                git('config','core.hooksPath','custom');r=observe(scope,tool)
                self.assertFalse(r['hooks']['available']);self.assertFalse(r['controls_available'])

    def test_guard_control_later_edit_is_preserved_and_refused(self):
        with fixture() as (root,scope,tool,_):
            directory=active(root)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalControls(repo,tool);real=ctx.agents
                def edit(indexed):
                    result=real(indexed);(directory/'registration-guard').write_text('later user edit');return result
                with patch.object(ctx,'agents',side_effect=edit),self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual((directory/'registration-guard').read_text(),'later user edit')


class Memory(unittest.TestCase):
    def test_absent_memory_is_ok_without_reading_any_body(self):
        with fixture() as (_,scope,tool,_):
            r=observe(scope,tool);self.assertEqual(r['memory']['state'],'absent')
            self.assertFalse(r['memory']['body_read']);self.assertFalse(r['generated_memory_contents_read'])

    def test_tracked_root_and_nested_FIFO_memory_produce_violation_without_reads(self):
        for relative in ['agent-learnings.md','nested/agent-learnings.md']:
            with self.subTest(relative=relative),fixture() as (root,scope,tool,git):
                p=root/relative;p.parent.mkdir(exist_ok=True);p.write_text('synthetic old context')
                git('add',relative);git('commit','-m','synthetic memory index name');p.unlink();os.mkfifo(p,0o600)
                r=observe(scope,tool)
                self.assertEqual(r['memory']['state'],'tracked');self.assertEqual(r['controls_verdict'],'VIOLATION')
                self.assertFalse(r['memory']['body_read'])

    def test_present_ignored_unignored_and_info_exclude_memory(self):
        for kind in ['ignored','unignored','info','local']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                memory=root/'agent-learnings.md';memory.write_text('PRIVATE_SYNTHETIC_CONTEXT')
                if kind=='ignored':(root/'.gitignore').write_text('agent-learnings.md\n')
                if kind=='info':
                    (root/'.git/info').mkdir(exist_ok=True)
                    (root/'.git/info/exclude').write_text('agent-learnings.md\n')
                if kind=='local':
                    (root/'custom.ignore').write_text('agent-learnings.md\n');git('config','core.excludesFile','custom.ignore')
                real=m.s.read_regular
                def safe_read(parent,name,**kw):
                    if name=='agent-learnings.md':raise AssertionError('memory body read')
                    return real(parent,name,**kw)
                with patch.object(m.s,'read_regular',side_effect=safe_read):r=observe(scope,tool)
                self.assertEqual(r['memory']['verdict'],'DRIFT' if kind=='unignored' else 'OK')
                self.assertNotIn('PRIVATE_SYNTHETIC_CONTEXT',json.dumps(r));self.assertFalse(r['memory']['body_read'])

    def test_memory_alias_special_shared_and_foreign_types_remain_unknown(self):
        for kind in ['symlink','FIFO','hardlink','directory']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                p=root/'agent-learnings.md'
                if kind=='symlink':p.symlink_to('/not-read')
                elif kind=='FIFO':os.mkfifo(p,0o600)
                elif kind=='directory':p.mkdir()
                else:
                    source=root/'synthetic';source.write_text('synthetic');os.link(source,p)
                r=observe(scope,tool);self.assertFalse(r['memory']['available']);self.assertFalse(r['controls_available'])

    def test_invalid_external_or_generated_memory_excludes_do_not_read_bodies(self):
        for value in ['/outside/ignore','agent-learnings.md','nested/ignore']:
            with self.subTest(value=value),fixture() as (root,scope,tool,git):
                (root/'agent-learnings.md').write_text('PRIVATE_SYNTHETIC_CONTEXT')
                if value=='nested/ignore':
                    nested=root/'nested';nested.mkdir();(nested/'.git').write_text('gitdir: /not-followed');os.mkfifo(nested/'ignore',0o600)
                git('config','core.excludesFile',value);r=observe(scope,tool)
                self.assertEqual(r['memory']['state'],'indeterminate');self.assertFalse(r['memory']['available'])
                self.assertFalse(r['memory']['body_read'])

    def test_ignore_command_failure_stays_indeterminate(self):
        with fixture() as (root,scope,tool,_):
            (root/'agent-learnings.md').write_text('synthetic')
            with patch.object(w.PersonalWorktree,'ignored',side_effect=g.Refusal('synthetic-ignore-refusal')):r=observe(scope,tool)
            self.assertEqual(r['memory']['state'],'indeterminate');self.assertFalse(r['controls_available'])

    def test_memory_metadata_later_edit_is_preserved_and_refused(self):
        with fixture() as (root,scope,tool,_):
            p=root/'agent-learnings.md';p.write_text('synthetic first')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalControls(repo,tool);real=ctx.agents
                def edit(indexed):
                    result=real(indexed);p.write_text('later synthetic owner edit');return result
                with patch.object(ctx,'agents',side_effect=edit),self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual(p.read_text(),'later synthetic owner edit')

    def test_memory_ignore_control_later_edit_is_preserved_and_refused(self):
        with fixture() as (root,scope,tool,_):
            (root/'agent-learnings.md').write_text('synthetic body never read')
            p=root/'.gitignore';p.write_text('agent-learnings.md\n')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalControls(repo,tool);real=ctx.agents
                def edit(indexed):
                    result=real(indexed);p.write_text('later user ignore edit\n');return result
                with patch.object(ctx,'agents',side_effect=edit),self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual(p.read_text(),'later user ignore edit\n')


class Agents(unittest.TestCase):
    def test_untracked_AGENTS_FIFO_is_not_read(self):
        with fixture() as (root,scope,tool,_):
            os.mkfifo(root/'AGENTS.md',0o600);r=observe(scope,tool)
            self.assertEqual(r['agents']['state'],'not-tracked');self.assertFalse(r['agents']['body_read'])

    def test_tracked_pointer_missing_pointer_and_both_learned_heading_types(self):
        for text,level in [('agent-learnings.md\n','OK'),('# Hand authored\n','ADVISORY'),
                           ('## Learned User Preferences\nPRIVATE_SYNTHETIC_CONTEXT\n','DRIFT'),
                           ('## Learned Workspace Facts\nagent-learnings.md\n','DRIFT')]:
            with self.subTest(level=level),fixture() as (root,scope,tool,git):
                tracked_agents(root,git,text);r=observe(scope,tool)
                self.assertEqual(r['agents']['verdict'],level);self.assertNotIn('PRIVATE_SYNTHETIC_CONTEXT',json.dumps(r))
                self.assertFalse(r['agents']['content_or_context_emitted'])

    def test_tracked_AGENTS_aliases_special_missing_and_size_bounds_remain_unknown(self):
        for kind in ['symlink','FIFO','missing','oversized']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                tracked_agents(root,git,'agent-learnings.md\n');p=root/'AGENTS.md';p.unlink()
                if kind=='symlink':p.symlink_to('/not-read')
                elif kind=='FIFO':os.mkfifo(p,0o600)
                elif kind=='oversized':p.write_bytes(b'x'*(m.s.MAX_FILE_BYTES+1))
                r=observe(scope,tool);self.assertFalse(r['agents']['available']);self.assertFalse(r['controls_available'])

    def test_AGENTS_later_edit_is_preserved_and_refused(self):
        with fixture() as (root,scope,tool,git):
            tracked_agents(root,git,'agent-learnings.md\n')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalControls(repo,tool);real=ctx.agents
                def edit(indexed):
                    result=real(indexed);(root/'AGENTS.md').write_text('later user edit');return result
                with patch.object(ctx,'agents',side_effect=edit),self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual((root/'AGENTS.md').read_text(),'later user edit')


class Boundary(unittest.TestCase):
    def test_control_ancestor_time_and_entry_bounds_stay_unavailable(self):
        for limit in ['time','entries']:
            with self.subTest(limit=limit),fixture() as (root,scope,tool,git):
                active(root,'custom');git('config','core.hooksPath','custom')
                with patch.object(w,'MAX_TREE_SECONDS',0) if limit=='time' else patch.object(w,'MAX_TREE_ENTRIES',1):
                    result=observe(scope,tool)
                self.assertFalse(result['hooks']['available'])
                self.assertEqual(result['hooks']['reason'],'worktree-control-parent-bound')

    def test_wrong_origin_stops_before_hook_or_memory_inspection(self):
        with fixture() as (_,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with patch.object(m.Reader,'read',side_effect=AssertionError('read entered')):
                result=m.inspect(scope,tool)
            self.assertFalse(result['rows'][0]['controls_available'])
            self.assertIsNone(result['rows'][0]['controls_verdict'])

    def test_CLI_rejects_unscoped_roots_writers_remote_and_extra_verbs(self):
        for args in [['apply'],['inspect','--root','/elsewhere'],['inspect','--remote'],['inspect','--fix-hooks']]:
            with self.subTest(args=args),patch('sys.stderr',new=io.StringIO()):
                with self.assertRaises(SystemExit) as cm:m.main(args)
                self.assertEqual(cm.exception.code,2)

    def test_actual_CLI_violation_and_unavailable_exits(self):
        for kind,expected in [('tracked',1),('external-hooks',2),('missing-hooks',0)]:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                if kind=='tracked':
                    (root/'agent-learnings.md').write_text('synthetic');git('add','agent-learnings.md');git('commit','-m','synthetic tracked memory')
                if kind=='external-hooks':git('config','core.hooksPath','/outside')
                with redirect_stdout(io.StringIO()) as capture:
                    code=m.main(['inspect','--repository','KleinPerkins/skills'])
                self.assertEqual(code,expected);result=json.loads(capture.getvalue())
                self.assertFalse(result['complete_doctor_or_native_qualification'])


if __name__=='__main__':unittest.main()
