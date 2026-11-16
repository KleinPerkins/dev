"""Real Git ignore/status fixtures and refusal-before-traversal proofs."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_worktree as w
import personal_git as g
from test_personal_git import fixture


def observe(scope,tool):
    with scope.repository('KleinPerkins/skills') as repo:return w.PersonalWorktree(repo,tool).observe()


def ignore_file(root,git,text):
    (root/'.gitignore').write_text(text);git('add','-f','.gitignore');git('commit','-m','synthetic ignore policy')


class Parsers(unittest.TestCase):
    def test_literal_relative_names_spaces_newlines_and_unicode(self):
        for path in ['space name','line\nname','tab\tname','café/file','~literal',':(literal)*']:
            self.assertTrue(w.parts(path))
        for path in ['', '/', '../x', 'x/../y','./x','x//y','x\0y']:
            with self.assertRaises(g.Refusal):w.parts(path)

    def test_index_stage_and_rename_porcelain_parse(self):
        raw=b'100644 '+b'a'*40+b' 0\tspace name\0'+b'120000 '+b'b'*40+b' 2\tline\nname\0'
        result=w.index_paths(raw);self.assertEqual(result['space name'],{'100644'})
        self.assertEqual(result['line\nname'],{'120000'})
        status=w.porcelain(b'R  new name\0old name\0?? untracked dir/\0')
        self.assertEqual(status['reported_change_items'],2)
        self.assertEqual(status['reported_untracked_items'],1)
        self.assertEqual(status['codes'],{'R ':1,'??':1})

    def test_malformed_index_paths_and_status_records_hold(self):
        for raw in [b'no nul',b'bad\0',b'100644 '+b'a'*40+b' 0\t../outside\0',b'100644 '+b'a'*40+b' 0\t.git/config\0']:
            with self.assertRaises(g.Refusal):w.index_paths(raw)
        for raw in [b'bad',b'ZZ name\0',b'R  missing-from\0',b'?? ../outside\0']:
            with self.assertRaises((g.Refusal,UnicodeError)):w.porcelain(raw)


class Worktree(unittest.TestCase):
    def test_clean_primary_preserves_index_config_and_source(self):
        with fixture() as (root,scope,tool,_):
            before={p:(root/p).read_bytes() for p in ['.git/config','.git/index','fixture.txt']}
            result=observe(scope,tool)
            self.assertTrue(result['clean_under_personal_policy']);self.assertTrue(result['worktree_status_proven'])
            self.assertFalse(result['nested_checkouts_or_submodules_inspected'])
            self.assertFalse(result['native_or_complete_doctor_qualified'])
            self.assertEqual(before,{p:(root/p).read_bytes() for p in before})

    def test_private_index_does_not_hide_racy_same_stat_content_edits(self):
        for kind in ['plain','split']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                git('config','core.trustctime','false');git('config','core.checkstat','minimal')
                path=root/'fixture.txt';original=path.stat()
                old=original.st_mtime_ns-5_000_000_000
                os.utime(path,ns=(old,old));git('add','fixture.txt')
                if kind=='split':git('update-index','--split-index')
                stamp=path.stat();index=root/'.git/index'
                # A real Git racy-clean boundary: cache stat fields still match
                # after a same-size edit, so the source index mtime forces Git
                # to compare contents. Never freshen that mtime in the view.
                os.utime(index,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                path.write_text('two\n');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                expected=git('status','--porcelain=v1','--untracked-files=normal')
                self.assertTrue(expected)
                before=index.read_bytes(),index.stat().st_mtime_ns,index.stat().st_ctime_ns
                result=observe(scope,tool)
                self.assertFalse(result['clean_under_personal_policy'])
                self.assertEqual(result['codes'],{' M':1})
                self.assertEqual(before,(index.read_bytes(),index.stat().st_mtime_ns,index.stat().st_ctime_ns))

    def test_staged_sparse_index_preserves_source_object_bytes_inodes_and_timestamps(self):
        with fixture() as (root,scope,tool,git):
            for name in ('keep','other'):(root/name).mkdir();(root/name/'value').write_text('one\n')
            git('add','.');git('commit','-m','synthetic sparse objects')
            git('sparse-checkout','init','--cone','--sparse-index');git('sparse-checkout','set','keep')
            (root/'keep/value').write_text('staged sparse\n');git('add','keep/value')
            def facts():
                return {str(p.relative_to(root)):(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns,p.stat().st_ctime_ns)
                        for p in (root/'.git/objects').rglob('*') if p.is_file()}
            before=facts();result=observe(scope,tool)
            self.assertFalse(result['clean_under_personal_policy']);self.assertEqual(result['codes'],{'M ':1})
            self.assertEqual(facts(),before)

    def test_modified_deleted_staged_and_untracked_are_not_clean(self):
        for kind in ['modified','deleted','staged','untracked']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                if kind=='deleted':(root/'fixture.txt').unlink()
                elif kind=='untracked':(root/'new.txt').write_text('synthetic')
                else:
                    (root/'fixture.txt').write_text('changed\n')
                    if kind=='staged':git('add','fixture.txt')
                result=observe(scope,tool)
                self.assertFalse(result['clean_under_personal_policy']);self.assertGreater(result['reported_change_items'],0)
                self.assertEqual(result['reported_untracked_items'],1 if kind=='untracked' else 0)

    def test_rename_and_unmerged_index_semantics(self):
        with fixture() as (root,scope,tool,git):
            git('mv','fixture.txt','renamed file.txt')
            result=observe(scope,tool);self.assertEqual(result['codes'],{'R ':1})
        with fixture() as (root,scope,tool,git):
            head=git('rev-parse','HEAD').decode();blob=git('rev-parse','HEAD:fixture.txt').decode()
            # Index-only synthetic conflict, no merge or external repository.
            data=('0 '+'0'*40+'\tfixture.txt\n'+''.join(f'100644 {blob} {stage}\tfixture.txt\n' for stage in [1,2,3])).encode()
            r=g.bounded_process([str(tool.path),'--no-optional-locks','update-index','--index-info'],root,data)
            self.assertEqual(r[0],0)
            result=observe(scope,tool);self.assertIn('UU',result['codes'])

    def test_negation_anchor_directory_patterns_and_nested_overrides(self):
        with fixture() as (root,scope,tool,git):
            ignore_file(root,git,'*.tmp\n!important.tmp\n/root-only.txt\ncache/\n')
            (root/'ignored.tmp').write_text('ignored');(root/'important.tmp').write_text('visible')
            (root/'root-only.txt').write_text('ignored')
            sub=root/'sub';sub.mkdir();(sub/'root-only.txt').write_text('visible')
            (sub/'.gitignore').write_text('!nested.tmp\n');(sub/'nested.tmp').write_text('visible')
            cache=root/'cache';cache.mkdir();os.mkfifo(cache/'.gitignore',0o600)
            result=observe(scope,tool)
            self.assertFalse(result['clean_under_personal_policy'])
            self.assertGreaterEqual(result['worktree_fence']['ignored_directories_pruned'],1)

    def test_ignored_directory_never_reads_child_FIFO_ignore_or_nested_checkout(self):
        with fixture() as (root,scope,tool,git):
            ignore_file(root,git,'cache/\n')
            cache=root/'cache';cache.mkdir();os.mkfifo(cache/'.gitignore',0o600)
            (cache/'.git').symlink_to('/not-read')
            result=observe(scope,tool)
            self.assertTrue(result['clean_under_personal_policy'])
            self.assertEqual(result['worktree_fence']['ignored_directories_pruned'],1)

    def test_unignored_child_FIFO_control_refuses_before_status(self):
        with fixture() as (root,scope,tool,_):
            child=root/'child';child.mkdir();os.mkfifo(child/'.gitignore',0o600)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with self.assertRaisesRegex(g.Refusal,'control-alias-or-type'):ctx.observe()
                self.assertFalse(any(p['name']=='status' for p in ctx.probes))

    def test_tracked_paths_are_checked_even_inside_ignored_directory(self):
        with fixture() as (root,scope,tool,git):
            child=root/'cache';child.mkdir();(child/'kept.txt').write_text('tracked')
            git('add','cache/kept.txt');git('commit','-m','synthetic tracked under ignored parent')
            ignore_file(root,git,'cache/\n')
            (child/'kept.txt').write_text('changed');(child/'ignored-extra').write_text('ignored')
            result=observe(scope,tool)
            self.assertFalse(result['clean_under_personal_policy']);self.assertEqual(result['reported_untracked_items'],0)

    def test_unicode_tracked_directory_is_not_pruned_under_ignore(self):
        with fixture() as (root,scope,tool,git):
            git('config','core.precomposeUnicode','true')
            child=root/'café';child.mkdir();(child/'kept.txt').write_text('tracked')
            git('add','café/kept.txt');git('commit','-m','synthetic unicode tracked path')
            ignore_file(root,git,'café/\n');(child/'kept.txt').write_text('changed')
            result=observe(scope,tool);self.assertFalse(result['clean_under_personal_policy'])

    def test_literal_special_filenames_and_directory_names_do_not_become_magic(self):
        with fixture() as (root,scope,tool,_):
            for name in ['space name','line\nname','tab\tname',':(literal)*','~literal','café']:
                (root/name).mkdir();(root/name/'file').write_text('synthetic')
            result=observe(scope,tool)
            self.assertFalse(result['clean_under_personal_policy']);self.assertEqual(result['reported_untracked_items'],6)

    def test_ignored_file_body_changes_do_not_make_the_worktree_dirty(self):
        with fixture() as (root,scope,tool,git):
            ignore_file(root,git,'*.cache\n')
            p=root/'synthetic.cache';p.write_text('one')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool);real=ctx.run
                def mutate(name,data=None):
                    result=real(name,data)
                    if name=='status':p.write_text('later ignored content')
                    return result
                with patch.object(ctx,'run',side_effect=mutate):result=ctx.observe()
            self.assertTrue(result['clean_under_personal_policy']);self.assertEqual(p.read_text(),'later ignored content')

    def test_info_exclude_and_scoped_local_excludes_are_applied(self):
        with fixture() as (root,scope,tool,git):
            (root/'.git/info').mkdir(exist_ok=True);(root/'.git/info/exclude').write_text('info-extra\n')
            (root/'local-ignore').write_text('local-extra\nlocal-ignore\n')
            git('config','core.excludesFile','local-ignore')
            (root/'info-extra').write_text('ignored');(root/'local-extra').write_text('ignored')
            result=observe(scope,tool);self.assertTrue(result['clean_under_personal_policy'])

    def test_external_excludes_are_not_followed(self):
        for value in ['/not-read','~/.config/git/ignore','%(prefix)/not-read','../not-read']:
            with self.subTest(value=value),fixture() as (_,scope,tool,git):
                git('config','core.excludesFile',value)
                with self.assertRaises(g.Refusal):observe(scope,tool)

    def test_tracked_generated_memory_FIFO_is_never_read_and_blocks_status(self):
        with fixture() as (root,scope,tool,git):
            p=root/'agent-learnings.md';p.write_text('synthetic memory');git('add','agent-learnings.md');git('commit','-m','synthetic tracked memory name')
            p.unlink();os.mkfifo(p,0o600)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with patch.object(ctx,'scan',side_effect=AssertionError('worktree inspected')):
                    with self.assertRaisesRegex(g.Refusal,'tracked-generated-memory'):ctx.observe()

    def test_untracked_generated_memory_FIFO_can_remain_ignored_without_read(self):
        with fixture() as (root,scope,tool,git):
            ignore_file(root,git,'agent-learnings.md\n');os.mkfifo(root/'agent-learnings.md',0o600)
            result=observe(scope,tool);self.assertTrue(result['clean_under_personal_policy'])
            self.assertFalse(result['generated_memory_contents_read'])

    def test_known_work_and_protected_names_stop_before_child_stat(self):
        for name in ['affirm','chaos-scheduler']:
            with self.subTest(name=name),fixture() as (root,scope,tool,_):
                (root/name).symlink_to('/not-read',target_is_directory=True)
                with scope.repository('KleinPerkins/skills') as repo:
                    ctx=w.PersonalWorktree(repo,tool);real=os.stat
                    def guarded(path,*args,**kw):
                        if path==name:raise AssertionError('forbidden child stat')
                        return real(path,*args,**kw)
                    with patch.object(w.os,'stat',side_effect=guarded):
                        with self.assertRaisesRegex(g.Refusal,'work-or-protected'):ctx.observe()

    def test_unregistered_nested_checkout_is_held_before_its_control_read(self):
        with fixture() as (root,scope,tool,_):
            child=root/'nested';child.mkdir();(child/'.git').symlink_to('/not-read')
            os.mkfifo(child/'.gitignore',0o600)
            with self.assertRaisesRegex(g.Refusal,'nested-checkout'):observe(scope,tool)

    def test_gitlink_is_held_without_traversing_its_checkout(self):
        with fixture() as (root,scope,tool,git):
            head=git('rev-parse','HEAD').decode();git('update-index','--add','--cacheinfo',f'160000,{head},module')
            (root/'module').symlink_to('/not-read')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with patch.object(ctx,'scan',side_effect=AssertionError('submodule tree touched')):
                    with self.assertRaisesRegex(g.Refusal,'submodule'):ctx.observe()

    def test_leaf_symlink_does_not_follow_target_contents(self):
        with fixture() as (root,scope,tool,git):
            outside=root.parent/'outside';outside.mkdir();os.mkfifo(outside/'.gitignore',0o600)
            (root/'link').symlink_to(outside,target_is_directory=True)
            git('add','link');git('commit','-m','synthetic leaf link')
            result=observe(scope,tool);self.assertTrue(result['clean_under_personal_policy'])

    def test_tracked_parent_symlink_refuses_before_status(self):
        with fixture() as (root,scope,tool,git):
            child=root/'tracked';child.mkdir();(child/'file').write_text('synthetic')
            git('add','tracked/file');git('commit','-m','synthetic tracked parent')
            child.rename(root/'kept-parent');child.symlink_to(root/'kept-parent',target_is_directory=True)
            with self.assertRaisesRegex(g.Refusal,'tracked-parent-symlink'):observe(scope,tool)

    def test_control_symlink_hardlink_and_special_files_hold(self):
        for kind in ['link','hardlink','fifo']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                p=root/'.gitignore'
                if kind=='link':p.symlink_to('/not-read')
                elif kind=='hardlink':os.link(root/'fixture.txt',p)
                else:os.mkfifo(p,0o600)
                with self.assertRaises((g.Refusal,ValueError)):observe(scope,tool)

    def test_tracked_shared_file_and_unignored_special_file_hold(self):
        for kind in ['hardlink','fifo']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                if kind=='hardlink':os.link(root/'fixture.txt',root/'shared')
                else:os.mkfifo(root/'synthetic-fifo',0o600)
                with self.assertRaises(g.Refusal):observe(scope,tool)

    def test_tree_and_control_edits_during_observation_are_preserved_and_refused(self):
        for name in ['fixture.txt','.gitignore']:
            with self.subTest(name=name),fixture() as (root,scope,tool,git):
                if name=='.gitignore':ignore_file(root,git,'*.cache\n')
                with scope.repository('KleinPerkins/skills') as repo:
                    ctx=w.PersonalWorktree(repo,tool);real=ctx.run
                    def mutate(verb,data=None):
                        result=real(verb,data)
                        if verb=='status':(root/name).write_text('later owner edit preserved\n')
                        return result
                    with patch.object(ctx,'run',side_effect=mutate),self.assertRaisesRegex(g.Refusal,'changed'):
                        ctx.observe()
                self.assertEqual((root/name).read_text(),'later owner edit preserved\n')

    def test_sparse_checkout_and_split_index_keep_metadata_unchanged(self):
        with fixture() as (root,scope,tool,git):
            (root/'keep').mkdir();(root/'omit').mkdir()
            (root/'keep/file').write_text('keep');(root/'omit/file').write_text('omit')
            git('add','keep','omit');git('commit','-m','synthetic sparse source')
            git('sparse-checkout','init','--cone');git('sparse-checkout','set','keep')
            before=(root/'.git/index').read_bytes();result=observe(scope,tool)
            self.assertTrue(result['clean_under_personal_policy']);self.assertEqual((root/'.git/index').read_bytes(),before)
        with fixture() as (root,scope,tool,git):
            git('update-index','--split-index');before=(root/'.git/index').read_bytes()
            result=observe(scope,tool);self.assertTrue(result['clean_under_personal_policy'])
            self.assertEqual((root/'.git/index').read_bytes(),before)

    def test_split_index_alias_is_held_before_index_query(self):
        with fixture() as (root,scope,tool,git):
            git('update-index','--split-index')
            p=next((root/'.git').glob('sharedindex.*'));p.rename(p.with_name('kept-'+p.name));p.symlink_to('/not-read')
            with scope.repository('KleinPerkins/skills') as repo:
                with self.assertRaises(g.Refusal):w.PersonalWorktree(repo,tool)

    def test_nested_tracked_generated_memory_is_held_before_body_or_status(self):
        with fixture() as (root,scope,tool,git):
            directory=root/'synthetic';directory.mkdir()
            path=directory/'agent-learnings.md';path.write_text('synthetic old machine context')
            git('add','synthetic/agent-learnings.md');git('commit','-m','synthetic nested memory')
            path.unlink();os.mkfifo(path,0o600)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with patch.object(ctx,'scan',side_effect=AssertionError('tree scanned')):
                    with self.assertRaisesRegex(g.Refusal,'tracked-generated-memory'):ctx.observe()
                self.assertFalse(any(p['name']=='status' for p in ctx.probes))

    def test_local_excludes_cannot_read_generated_memory_as_a_control(self):
        with fixture() as (root,scope,tool,git):
            path=root/'agent-learnings.md';os.mkfifo(path,0o600)
            git('config','core.excludesFile','agent-learnings.md')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with self.assertRaisesRegex(g.Refusal,'control-pointer-held'):ctx.observe()
                self.assertFalse(any(p['name']=='status' for p in ctx.probes))

    def test_local_excludes_in_nested_checkout_hold_before_control_read(self):
        with fixture() as (root,scope,tool,git):
            nested=root/'nested';nested.mkdir();(nested/'.git').symlink_to('/not-followed')
            os.mkfifo(nested/'ignore',0o600);git('config','core.excludesFile','nested/ignore')
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                with self.assertRaisesRegex(g.Refusal,'nested-control-pointer'):ctx.observe()
                self.assertFalse(any(p['name']=='ignore' for p in ctx.probes))

    def test_direct_status_ignore_and_unknown_verbs_need_fences(self):
        with fixture() as (_,scope,tool,_):
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=w.PersonalWorktree(repo,tool)
                for name in ['status','ignore','fetch','push','reset']:
                    with self.assertRaises(g.Refusal):ctx.run(name)

    def test_inventory_bound_returns_unavailable_not_clean(self):
        with fixture() as (_,scope,tool,_),patch.object(w,'MAX_TREE_ENTRIES',1):
            result=w.inspect(scope,tool)
            self.assertFalse(result['rows'][0]['worktree_status_proven'])
            self.assertEqual(result['rows'][0]['status'],'unavailable')

    def test_wrong_origin_stops_before_worktree_scan(self):
        with fixture() as (_,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with patch.object(w.PersonalWorktree,'scan',side_effect=AssertionError('worktree scanned')):
                with self.assertRaisesRegex(g.Refusal,'personal-origin'):observe(scope,tool)

    def test_CLI_rejects_roots_writers_and_extra_commands(self):
        for args in [['status'],['inspect','--root','/elsewhere'],['inspect','--remote'],['inspect','--fix-hooks']]:
            with self.subTest(args=args),patch('sys.stderr',new=io.StringIO()):
                with self.assertRaises(SystemExit) as cm:w.main(args)
                self.assertEqual(cm.exception.code,2)


if __name__=='__main__':unittest.main()
