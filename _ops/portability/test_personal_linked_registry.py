"""Synthetic-only registry discovery and refusal-before-target-access fixtures."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_linked_registry as m
from test_personal_git import fixture,GIT

REPO='KleinPerkins/skills'
version=subprocess.run([str(GIT),'--version'],env=m.g.clean_environment(),capture_output=True,timeout=5)
match=re.search(rb'git version (\d+)\.(\d+)',version.stdout)
RELATIVE_FIXTURE_SUPPORTED=bool(match and tuple(map(int,match.groups()))>=(2,48))


def linked(root,scope,git,*,relative=False,name='skills'):
    target=scope.home/'.codex/worktrees/synthetic-registry'/name
    target.parent.mkdir(parents=True,mode=0o700)
    args=['worktree','add','--detach']
    if relative:args.append('--relative-paths')
    git(*args,str(target),'HEAD')
    entries=list((root/'.git/worktrees').iterdir());assert len(entries)==1
    return target,entries[0]


def discover(scope,tool):return m.inspect(scope,tool)


def no_targets(scope,callback):
    original=m.s.absolute_directory
    base=scope.home/'.codex/worktrees'
    def guarded(path):
        if Path(path)==base or Path(path).is_relative_to(base):raise AssertionError('additional target root opened')
        return original(path)
    with patch.object(m.s,'absolute_directory',guarded):return callback()


class Discovery(unittest.TestCase):
    def test_empty_registry_is_available_without_claiming_worktree_status(self):
        with fixture() as (root,scope,tool,git):
            result=no_targets(scope,lambda:discover(scope,tool));row=result['rows'][0]
            self.assertTrue(row['available']);self.assertFalse(row['registry_present'])
            self.assertEqual(row['registered_entry_count'],0)
            self.assertFalse(row['actual_target_status_proven'])
            self.assertFalse(result['full_linked_observability_or_doctor_or_native_acceptance'])

    def test_absolute_and_relative_linking_propose_exact_identity_without_target_access(self):
        for relative in (False,True):
            with self.subTest(relative=relative),fixture() as (root,scope,tool,git):
                if relative and not RELATIVE_FIXTURE_SUPPORTED:
                    self.skipTest('relative-link fixture requires Git >=2.48; no older/native equivalence is asserted')
                target,entry=linked(root,scope,git,relative=relative)
                result=no_targets(scope,lambda:discover(scope,tool));row=result['rows'][0]
                self.assertTrue(row['available']);self.assertEqual(row['proposed_count'],1);self.assertEqual(row['held_count'],0)
                proposal=row['candidates'][0];binding=proposal['binding_proposal']
                self.assertEqual(binding['target_path'],str(target));self.assertEqual(binding['target_gitfile_path'],str(target/'.git'))
                self.assertEqual(binding['entry_path'],str(entry));self.assertEqual(binding['common_path'],str(root/'.git'))
                self.assertEqual(binding['gitdir_relative'],relative)
                self.assertEqual(proposal['candidate_sha256'],m.w.digest(binding))
                for key in ('target_metadata_opened','target_body_opened','source_index_body_read','explicit_additional_binding_accepted'):
                    self.assertFalse(proposal[key])

    def test_spaces_and_unicode_pointer_paths_remain_literal_private_metadata(self):
        with fixture() as (root,scope,tool,git):
            target,_=linked(root,scope,git,name='synthetic seed café')
            result=no_targets(scope,lambda:discover(scope,tool));proposal=result['rows'][0]['candidates'][0]
            self.assertEqual(proposal['binding_proposal']['target_path'],str(target))
            self.assertEqual(proposal['status'],'proposed-uninspected')

    def test_discovery_preserves_common_and_admin_bytes_modes_and_timestamps(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git)
            paths=[root/'.git/config',root/'.git/index',root/'.git/HEAD',entry/'gitdir',entry/'commondir',entry/'HEAD',entry/'index',target/'.git']
            def facts():
                return [(p.read_bytes(),p.stat().st_ino,p.stat().st_mode,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths]
            before=facts();no_targets(scope,lambda:discover(scope,tool));self.assertEqual(facts(),before)

    def test_target_gitfile_and_checkout_are_not_required_or_opened_for_a_proposal(self):
        with fixture() as (root,scope,tool,git):
            target,_=linked(root,scope,git);(target/'.git').unlink()
            (target/'fixture.txt').unlink();target.rmdir()
            result=no_targets(scope,lambda:discover(scope,tool));proposal=result['rows'][0]['candidates'][0]
            self.assertEqual(proposal['status'],'proposed-uninspected')
            self.assertFalse(proposal['target_metadata_opened'])

    def test_missing_admin_index_is_a_fact_never_a_clean_or_inspected_target(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);(entry/'index').unlink()
            result=no_targets(scope,lambda:discover(scope,tool));proposal=result['rows'][0]['candidates'][0]
            self.assertEqual(proposal['binding_proposal']['metadata']['index'],{'kind':'absent'})
            self.assertFalse(proposal['actual_target_head_or_status_proven'])

    def test_lock_reason_body_is_never_read(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);(entry/'locked').write_text('SYNTHETIC_PRIVATE_LOCK_REASON')
            original=m.s.read_regular
            def read(fd,name,**kw):
                if name=='locked':raise AssertionError('lock reason read')
                return original(fd,name,**kw)
            with patch.object(m.s,'read_regular',read):result=no_targets(scope,lambda:discover(scope,tool))
            proposal=result['rows'][0]['candidates'][0]
            self.assertEqual(proposal['binding_proposal']['metadata']['locked']['kind'],'file')
            self.assertNotIn('SYNTHETIC_PRIVATE_LOCK_REASON',json.dumps(result))

    def test_no_index_or_head_body_is_read_by_discovery(self):
        with fixture() as (root,scope,tool,git):
            linked(root,scope,git);original=m.s.read_regular
            def read(fd,name,**kw):
                if name in {'HEAD','index'} or name.startswith('sharedindex.'):raise AssertionError('index or HEAD body read')
                return original(fd,name,**kw)
            with patch.object(m.s,'read_regular',read):result=no_targets(scope,lambda:discover(scope,tool))
            self.assertTrue(result['rows'][0]['available']);self.assertEqual(result['rows'][0]['proposed_count'],1)


class Holds(unittest.TestCase):
    def test_wrong_origin_prevents_registry_and_storage_access(self):
        with fixture() as (root,scope,tool,git):
            linked(root,scope,git);git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with (patch.object(m.g,'storage_inventory',side_effect=AssertionError('storage opened')),
                  patch.object(m.MetadataDirectory,'child',side_effect=AssertionError('registry opened'))):
                result=discover(scope,tool)
            self.assertFalse(result['rows'][0]['available'])

    def test_config_includes_filters_unknown_extensions_or_unsafe_other_remotes_hold(self):
        for key,value in [('include.path','/not-read'),('filter.synthetic.process','never execute'),
                          ('extensions.future','true'),('remote.other.url','git@github.com:Excluded/work.git')]:
            with self.subTest(key=key),fixture() as (root,scope,tool,git):
                linked(root,scope,git);git('config',key,value)
                with patch.object(m.MetadataDirectory,'child',side_effect=AssertionError('registry opened')):result=discover(scope,tool)
                self.assertFalse(result['rows'][0]['available'])

    def test_excluded_registry_name_is_held_before_stat_or_pointer_read(self):
        for name in ('affirm','chaos-scheduler'):
            with self.subTest(name=name),fixture() as (root,scope,tool,git):
                registry=root/'.git/worktrees';registry.mkdir();(registry/name).mkdir()
                original=m.MetadataDirectory.child
                def child(directory,value):
                    if value==name:raise AssertionError('excluded registry child opened')
                    return original(directory,value)
                with patch.object(m.MetadataDirectory,'child',child):result=discover(scope,tool)
                row=result['rows'][0];self.assertTrue(row['available']);self.assertEqual(row['held_count'],1)
                self.assertFalse(row['candidates'][0]['target_body_opened'])

    def test_excluded_external_primary_or_ancestor_targets_are_held_without_target_access(self):
        for kind in ('work','protected','external','primary','other-primary','ancestor'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git)
                bad={'work':scope.home/'dev/affirm/example','protected':scope.home/'dev/personal/chaos-scheduler',
                     'external':Path('/outside/not-opened'),'primary':root,'other-primary':scope.home/'dev/capabilities/mcp',
                     'ancestor':scope.home/'dev'}[kind]
                (entry/'gitdir').write_text(str(bad/'.git')+'\n')
                original=m.s.absolute_directory
                def no_bad(path):
                    if bad!=root and Path(path)==bad:raise AssertionError('forbidden target opened')
                    return original(path)
                with patch.object(m.s,'absolute_directory',no_bad):result=discover(scope,tool)
                self.assertEqual(result['rows'][0]['held_count'],1)

    def test_wrong_common_pointer_or_missing_required_pointer_is_held(self):
        for kind in ('wrong-common','missing-gitdir','missing-commondir','missing-head','not-gitfile'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git)
                if kind=='wrong-common':(entry/'commondir').write_text('/outside/not-opened\n')
                if kind=='not-gitfile':(entry/'gitdir').write_text(str(target/'different')+'\n')
                if kind.startswith('missing-'):(entry/kind.removeprefix('missing-')).unlink()
                result=no_targets(scope,lambda:discover(scope,tool))
                self.assertEqual(result['rows'][0]['held_count'],1)

    def test_pointer_alias_fifo_shared_oversized_and_bad_bytes_are_held(self):
        for kind in ('alias','fifo','shared','oversized','encoding','nul','blank','ambiguous-space'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git);path=entry/'gitdir'
                if kind=='alias':path.unlink();path.symlink_to('/not-followed')
                if kind=='fifo':path.unlink();os.mkfifo(path,0o600)
                if kind=='shared':os.link(path,entry/'unread-other')
                if kind=='oversized':path.write_bytes(b'x'*(m.MAX_POINTER_BYTES+1))
                if kind=='encoding':path.write_bytes(b'\xff\n')
                if kind=='nul':path.write_bytes(b'/not-opened\0/.git\n')
                if kind=='blank':path.write_bytes(b'\n')
                if kind=='ambiguous-space':path.write_text(' /not-opened/.git\n')
                result=no_targets(scope,lambda:discover(scope,tool));self.assertEqual(result['rows'][0]['held_count'],1)

    def test_registry_and_entry_aliases_are_not_followed(self):
        for kind in ('registry','entry'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git)
                path=root/'.git/worktrees' if kind=='registry' else entry
                path.rename(path.with_name(path.name+'-preserved'))
                path.symlink_to('/not-followed',target_is_directory=True)
                result=no_targets(scope,lambda:discover(scope,tool));row=result['rows'][0]
                if kind=='registry':self.assertFalse(row['available'])
                else:self.assertGreaterEqual(row['held_count'],1)

    def test_entry_count_and_time_bounds_are_not_reported_as_empty_or_clean(self):
        with fixture() as (root,scope,tool,git):
            linked(root,scope,git)
            with patch.object(m,'MAX_REGISTRY_ENTRIES',0):result=discover(scope,tool)
            self.assertFalse(result['rows'][0]['available'])
            with patch.object(m,'MAX_REGISTRY_SECONDS',0):result=discover(scope,tool)
            self.assertFalse(result['rows'][0]['available'])

    def test_entry_replacement_and_late_pointer_changes_are_detected(self):
        for kind in ('directory','pointer'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git);original=m.propose
                def late(*args):
                    value=original(*args)
                    if kind=='directory':entry.rename(entry.with_name(entry.name+'-preserved'));entry.mkdir()
                    else:(entry/'gitdir').write_text(str(target/'changed')+'\n')
                    return value
                with patch.object(m,'propose',late):result=no_targets(scope,lambda:discover(scope,tool))
                row=result['rows'][0]
                self.assertTrue(not row['available'] or row['held_count']>0)

    def test_new_or_removed_registry_members_are_detected(self):
        for kind in ('add','remove'):
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                target,entry=linked(root,scope,git);original=m.CommonMetadata.check
                def late(common):
                    if kind=='add':(root/'.git/worktrees/new-entry').mkdir()
                    else:entry.rename(root/'.git/removed-entry-preserved')
                    return original(common)
                with patch.object(m.CommonMetadata,'check',late):result=no_targets(scope,lambda:discover(scope,tool))
                self.assertFalse(result['rows'][0]['available'])

    def test_common_config_change_and_external_object_alternates_hold(self):
        with fixture() as (root,scope,tool,git):
            linked(root,scope,git);original=m.propose
            def late(*args):
                value=original(*args)
                with (root/'.git/config').open('a') as f:f.write('\n# visible later edit\n')
                return value
            with patch.object(m,'propose',late):result=no_targets(scope,lambda:discover(scope,tool))
            self.assertFalse(result['rows'][0]['available'])
        with fixture() as (root,scope,tool,git):
            linked(root,scope,git);(root/'.git/objects/info/alternates').write_text('/not-read\n')
            result=discover(scope,tool);self.assertFalse(result['rows'][0]['available'])

    def test_pointer_changes_after_entry_closure_are_detected_by_final_source_recheck(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);original=m.CommonMetadata.check
            def late(common):
                (entry/'gitdir').write_text(str(target/'changed-after-entry-closure')+'\n')
                return original(common)
            with patch.object(m.CommonMetadata,'check',late):result=no_targets(scope,lambda:discover(scope,tool))
            self.assertFalse(result['rows'][0]['available'])

    def test_relative_link_extension_invalid_boolean_or_format_is_unavailable(self):
        for version,value in [('0','true'),('1','invalid')]:
            with self.subTest(version=version,value=value),fixture() as (root,scope,tool,git):
                linked(root,scope,git);git('config','core.repositoryformatversion',version);git('config','extensions.relativeWorktrees',value)
                result=discover(scope,tool);self.assertFalse(result['rows'][0]['available'])

    def test_cli_has_no_root_writer_binding_or_status_shortcut(self):
        for args in (['apply'],['bind'],['inspect','--root','/not-opened'],['inspect','--repository','KleinPerkins/chaos-scheduler']):
            out=io.StringIO()
            with redirect_stdout(out):
                try:code=m.main(args)
                except SystemExit as error:code=error.code
            self.assertNotEqual(code,0)


if __name__=='__main__':unittest.main()
