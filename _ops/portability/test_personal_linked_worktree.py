"""Disposable linked fixtures only; no operator additional root is opened."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_linked_worktree as m
from test_personal_git import fixture,GIT
from test_personal_linked_registry import linked,RELATIVE_FIXTURE_SUPPORTED

REPO='KleinPerkins/skills'


def encoded(scope,tool):
    proposal=m.r.inspect(scope,tool)['rows'][0]['candidates'][0]
    raw=(json.dumps(m.binding_document(proposal),sort_keys=True,separators=(',',':'))+'\n').encode()
    return raw,m.g.sha(raw)


def target_git(target,*args):
    result=subprocess.run([str(GIT),*m.g.FLAGS,'-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args],
                          cwd=target,env=m.g.clean_environment(),capture_output=True,timeout=5)
    if result.returncode:raise AssertionError((args,result.returncode,result.stderr.decode(errors='replace')))
    return result.stdout.strip()


def observe(scope,tool):
    raw,digest=encoded(scope,tool);return m.inspect(scope,tool,raw,digest)


def snapshots(paths):
    return [(p.read_bytes(),p.stat().st_ino,stat.S_IMODE(p.stat().st_mode),p.stat().st_nlink,
             p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths]


class Binding(unittest.TestCase):
    def test_canonical_binding_requires_exact_digest_and_closed_document(self):
        with fixture() as (primary,scope,tool,git):
            linked(primary,scope,git);raw,digest=encoded(scope,tool)
            self.assertEqual(m.read_binding(raw,digest)['repository'],REPO)
            for bad in ('0'*64,None,'wrong'):
                with self.assertRaises(m.g.Refusal):m.read_binding(raw,bad)
            for kind in ('extra','schema','operation','manifest','repository','proposal','duplicate'):
                with self.subTest(kind=kind):
                    value=json.loads(raw)
                    if kind=='extra':value['owner_approved']=True
                    if kind=='schema':value['schema']='unknown'
                    if kind=='operation':value['operation']='apply'
                    if kind=='manifest':value['manifest_sha256']='0'*64
                    if kind=='repository':value['repository']='KleinPerkins/chaos-scheduler'
                    if kind=='proposal':value['binding_proposal']['target_path']='/not-opened'
                    bad=json.dumps(value).encode()
                    if kind=='duplicate':bad=raw.rstrip()[:-1]+b',"operation":"read-only-linked-worktree"}'
                    with patch.object(m.s,'absolute_directory',side_effect=AssertionError('root opened')):
                        self.assertFalse(m.inspect(scope,tool,bad,m.g.sha(bad))['available'])

    def test_stale_proposal_refuses_before_target_open(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);raw,digest=encoded(scope,tool)
            (entry/'HEAD').write_text('0'*40+'\n')
            original=m.s.absolute_directory
            def guarded(path):
                if Path(path)==target:raise AssertionError('stale target opened')
                return original(path)
            with patch.object(m.s,'absolute_directory',guarded):result=m.inspect(scope,tool,raw,digest)
            self.assertFalse(result['available'])

    def test_wrong_backpointer_holds_before_worktree_construction(self):
        for kind in ('wrong','missing','directory','alias','shared','fifo'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);raw,digest=encoded(scope,tool);gitfile=target/'.git'
                if kind=='wrong':gitfile.write_text('gitdir: /not-opened\n')
                if kind=='missing':gitfile.unlink()
                if kind=='directory':gitfile.unlink();gitfile.mkdir()
                if kind=='alias':gitfile.unlink();gitfile.symlink_to('/not-followed')
                if kind=='shared':os.link(gitfile,target/'other-gitfile-preserved')
                if kind=='fifo':gitfile.unlink();os.mkfifo(gitfile,0o600)
                with patch.object(m.LinkedWorktree,'__init__',side_effect=AssertionError('body path entered')):
                    self.assertFalse(m.inspect(scope,tool,raw,digest)['available'])

    def test_aliased_target_is_not_followed(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);raw,digest=encoded(scope,tool)
            preserved=target.with_name('preserved');target.rename(preserved);target.symlink_to(preserved,target_is_directory=True)
            self.assertFalse(m.inspect(scope,tool,raw,digest)['available'])

    def test_nested_primary_candidate_is_held_before_target_access(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);nested=primary/'not-opened'
            (entry/'gitdir').write_text(str(nested/'.git')+'\n');raw,digest=encoded(scope,tool)
            original=m.s.absolute_directory
            def guarded(path):
                if Path(path)==nested:raise AssertionError('nested target opened')
                return original(path)
            with patch.object(m.s,'absolute_directory',guarded):result=m.inspect(scope,tool,raw,digest)
            self.assertFalse(result['available'])


class LinkedStatus(unittest.TestCase):
    def test_clean_absolute_and_relative_links_use_own_metadata(self):
        for relative in (False,True):
            with self.subTest(relative=relative),fixture() as (primary,scope,tool,git):
                if relative and not RELATIVE_FIXTURE_SUPPORTED:self.skipTest('relative-link synthetic fixture needs Git >=2.48')
                target,entry=linked(primary,scope,git,relative=relative)
                result=observe(scope,tool)
                self.assertTrue(result['available'],result);row=result['observation']
                self.assertTrue(row['clean_under_personal_policy']);self.assertTrue(row['detached'])
                self.assertEqual(row['head'],target_git(target,'rev-parse','HEAD').decode())
                self.assertFalse(result['source_or_config_writes']);self.assertEqual(result['new_model_workers'],0)

    def test_plain_split_sparse_preserve_distinct_HEAD_index_refs_and_source_facts(self):
        for variant in ('plain','split','sparse'):
            with self.subTest(variant=variant),fixture() as (primary,scope,tool,git):
                for name in ('keep','other'):(primary/name).mkdir();(primary/name/'value').write_text('one\n')
                git('add','.');git('commit','-m','synthetic folders')
                initial=git('rev-parse','HEAD').decode();target,entry=linked(primary,scope,git)
                git('config','extensions.worktreeConfig','true')
                if variant=='sparse':target_git(target,'sparse-checkout','init','--cone','--sparse-index');target_git(target,'sparse-checkout','set','keep')
                if variant=='split':target_git(target,'update-index','--split-index')
                (primary/'fixture.txt').write_text('primary later\n');git('add','fixture.txt');git('commit','-m','synthetic primary later')
                later=git('rev-parse','HEAD').decode()
                (target/'keep/value').write_text('own staged\n');target_git(target,'add','keep/value')
                target_git(target,'update-ref','refs/worktree/synthetic',initial)
                git('update-ref','refs/worktree/synthetic',later)
                source=[primary/'.git/config',primary/'.git/HEAD',primary/'.git/index',entry/'HEAD',entry/'index',entry/'gitdir',entry/'commondir',target/'.git',target/'keep/value']
                source += [p for p in (entry/'config.worktree',entry/'info/sparse-checkout') if p.exists()]
                source += list(entry.glob('sharedindex.*'))
                source += [p for top in ('objects','refs') for p in (primary/'.git'/top).rglob('*') if p.is_file()]
                before=snapshots(source);raw,digest=encoded(scope,tool)
                with m.bound_checkout(scope,tool,raw,digest) as context:
                    backend=m.LinkedGit(context,tool)
                    with backend.private_gitdir(worktree_controls=True) as admin:
                        def ref(value):
                            args=[str(tool.path),*m.g.FLAGS,*sum((['-c',x] for x in m.g.OVERRIDES),[]),'--git-dir='+str(admin),'--work-tree='+str(target),'rev-parse','--verify',value]
                            code,out,err=m.g.bounded_process(args,target);self.assertEqual((code,err),(0,b''));return out.strip().decode()
                        self.assertEqual(ref('HEAD'),initial);self.assertEqual(ref('main-worktree/HEAD'),later)
                        self.assertEqual(ref('refs/worktree/synthetic'),initial)
                        self.assertEqual(ref('main-worktree/refs/worktree/synthetic'),later)
                        self.assertEqual(ref('worktrees/'+entry.name+'/HEAD'),initial)
                    result=m.LinkedWorktree(context,tool).observe()
                self.assertEqual(result['head'],initial);self.assertEqual(result['codes'],{'M ':1})
                self.assertEqual(snapshots(source),before)

    def test_local_tracking_refs_report_divergence_without_fetch(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git)
            target_git(target,'switch','-c','synthetic-linked')
            git('config','branch.synthetic-linked.remote','.');git('config','branch.synthetic-linked.merge','refs/heads/main')
            (primary/'fixture.txt').write_text('main\n');git('add','.');git('commit','-m','synthetic main')
            (target/'fixture.txt').write_text('linked\n');target_git(target,'add','.');target_git(target,'commit','-m','synthetic linked')
            result=observe(scope,tool);self.assertTrue(result['available'],result)
            row=result['observation'];self.assertEqual((row['ahead'],row['behind']),(1,1));self.assertEqual(row['remote_requests'],0)

    def test_dirty_and_untracked_are_visible(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);(target/'fixture.txt').write_text('changed\n');(target/'untracked').write_text('synthetic\n')
            result=observe(scope,tool);self.assertTrue(result['available'],result)
            self.assertFalse(result['observation']['clean_under_personal_policy'])
            self.assertEqual(result['observation']['reported_untracked_items'],1)

    def test_common_ignores_and_own_sparse_rules_are_used(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);(primary/'.git/info').mkdir(exist_ok=True)
            (primary/'.git/info/exclude').write_text('common-ignored\n');(target/'common-ignored').write_text('synthetic\n')
            result=observe(scope,tool);self.assertTrue(result['available'],result);self.assertTrue(result['observation']['clean_under_personal_policy'])

    def test_effective_identity_comes_from_own_overlay_and_main_only_worktree_setting_is_ignored(self):
        for overlay in (False,True):
            with self.subTest(overlay=overlay),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);git('config','core.worktree',str(primary))
                if overlay:
                    git('config','extensions.worktreeConfig','true')
                    (entry/'config.worktree').write_text('[core]\n worktree = '+os.path.relpath(target,entry)+'\n[user]\n name = Synthetic Personal\n')
                result=observe(scope,tool);self.assertTrue(result['available'],result)
                row=result['observation'];self.assertTrue(row['local_identity_canonical'])
                self.assertEqual(row['effective_personal_identity_canonical'],not overlay)
                self.assertEqual(row['effective_identity_scope'],'worktree' if overlay else 'local')

    def test_unsafe_overlay_holds_before_any_private_probe(self):
        for body in ('[include]\n path=/not-read\n','[filter "synthetic"]\n process=never\n','[core]\n worktree=/not-read\n','[remote "origin"]\n url=git@github.com:Excluded/work.git\n'):
            with self.subTest(body=body),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);git('config','extensions.worktreeConfig','true');(entry/'config.worktree').write_text(body)
                with patch.object(m.LinkedGit,'probe',side_effect=AssertionError('probe entered')):result=observe(scope,tool)
                self.assertFalse(result['available'])

    def test_hooks_are_never_executed_and_generated_memory_body_is_never_read(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);hooks=primary/'.git/hooks';hooks.mkdir(exist_ok=True)
            marker=scope.home/'never-created';(hooks/'post-index-change').write_text('#!/bin/sh\ntouch '+str(marker)+'\n');(hooks/'post-index-change').chmod(0o700)
            (target/'.gitignore').write_text('agent-learnings.md\n');target_git(target,'add','.gitignore');target_git(target,'commit','-m','synthetic ignore')
            memory=target/'agent-learnings.md';os.mkfifo(memory,0o600)
            original=m.s.read_regular
            def guarded(parent,name,**kwargs):
                if name=='agent-learnings.md':raise AssertionError('memory body read')
                return original(parent,name,**kwargs)
            with patch.object(m.s,'read_regular',guarded):result=observe(scope,tool)
            self.assertTrue(result['available'],result);self.assertTrue(result['observation']['clean_under_personal_policy']);self.assertFalse(marker.exists())

    def test_metadata_locks_unknown_own_refs_and_unbound_other_tracking_refs_are_held(self):
        for kind in ('lock','own-refs','other-tracking','missing-index','shared-alias'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git)
                if kind=='lock':(entry/'index.lock').write_bytes(b'')
                if kind=='own-refs':(entry/'refs/heads').mkdir(parents=True);(entry/'refs/heads/unknown').write_text('0'*40+'\n')
                if kind=='other-tracking':git('config','branch.synthetic.merge','worktrees/unbound/HEAD')
                if kind=='missing-index':(entry/'index').unlink()
                if kind=='shared-alias':(entry/('sharedindex.'+'0'*40)).symlink_to('/not-read')
                with patch.object(m.LinkedGit,'probe',side_effect=AssertionError('probe entered')):result=observe(scope,tool)
                self.assertFalse(result['available'])

    def test_late_target_pointer_index_registry_and_worktree_edits_are_not_clean(self):
        for kind in ('pointer','index','registry','root','body'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);raw,digest=encoded(scope,tool);original=m.LinkedWorktree.run;changed=False
                def late(tree,name,data=None):
                    nonlocal changed
                    result=original(tree,name,data)
                    if name=='status' and not changed:
                        changed=True
                        if kind=='pointer':(target/'.git').write_text('gitdir: /not-opened\n')
                        if kind=='index':(entry/'index').write_bytes((entry/'index').read_bytes()+b'late')
                        if kind=='registry':(entry.parent/'new-entry').mkdir()
                        if kind=='root':target.rename(target.with_name('preserved'));target.mkdir()
                        if kind=='body':(target/'fixture.txt').write_text('late body\n')
                    return result
                with patch.object(m.LinkedWorktree,'run',late):result=m.inspect(scope,tool,raw,digest)
                self.assertFalse(result['available'])

    def test_synthetic_index_copy_byte_and_time_bounds_are_held(self):
        with fixture() as (primary,scope,tool,git):
            linked(primary,scope,git)
            raw,digest=encoded(scope,tool)
            with patch.object(m.g,'MAX_PRIVATE_BYTES',0):self.assertFalse(m.inspect(scope,tool,raw,digest)['available'])
            with patch.object(m.g,'MAX_METADATA_SECONDS',0):self.assertFalse(m.inspect(scope,tool,raw,digest)['available'])

    def test_symlink_and_alternate_object_strategies_are_red_controls_on_qualified_Mac_Git(self):
        if m.g.GIT_SHA256!=hashlib.sha256(GIT.read_bytes()).hexdigest():
            self.skipTest('object-freshening red control is bound to qualified Mac Git; no older equivalence asserted')
        for strategy in ('symlink','alternate'):
            with self.subTest(strategy=strategy),fixture() as (primary,scope,tool,git):
                for name in ('keep','other'):(primary/name).mkdir();(primary/name/'value').write_text('one\n')
                git('add','.');git('commit','-m','synthetic sparse objects')
                target,entry=linked(primary,scope,git);git('config','extensions.worktreeConfig','true')
                target_git(target,'sparse-checkout','init','--cone','--sparse-index');target_git(target,'sparse-checkout','set','keep')
                (target/'keep/value').write_text('staged sparse\n');target_git(target,'add','keep/value')
                def object_facts():return {str(p.relative_to(primary)):snapshots([p])[0] for p in (primary/'.git/objects').rglob('*') if p.is_file()}
                before=object_facts();original=m.copy_tree
                def unsafe(directory,name,destination,budget,**kwargs):
                    if name!='objects':return original(directory,name,destination,budget,**kwargs)
                    self.assertEqual(directory.path,primary/'.git')
                    if strategy=='symlink':destination.symlink_to(primary/'.git/objects',target_is_directory=True)
                    else:
                        (destination/'info').mkdir(parents=True)
                        (destination/'info/alternates').write_text(str(primary/'.git/objects')+'\n')
                with patch.object(m,'copy_tree',unsafe):result=observe(scope,tool)
                self.assertFalse(result['available']);self.assertNotEqual(before,object_facts())

    def test_racy_same_stat_edits_remain_dirty_for_plain_and_split_own_indexes(self):
        for variant in ('plain','split'):
            with self.subTest(variant=variant),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git)
                git('config','core.trustctime','false');git('config','core.checkstat','minimal')
                path=target/'fixture.txt';old=path.stat().st_mtime_ns-5_000_000_000
                os.utime(path,ns=(old,old));target_git(target,'add','fixture.txt')
                if variant=='split':target_git(target,'update-index','--split-index')
                stamp=path.stat();index=entry/'index'
                os.utime(index,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                path.write_text('two\n');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                before=snapshots([index]);result=observe(scope,tool)
                self.assertTrue(result['available'],result);self.assertEqual(result['observation']['codes'],{' M':1})
                self.assertEqual(before,snapshots([index]))


if __name__=='__main__':unittest.main()
