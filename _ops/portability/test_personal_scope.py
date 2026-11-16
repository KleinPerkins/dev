"""Closed selection/no-follow read proofs, including poisoned excluded roots."""
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import personal_scope as m


def document():
    return {'schema':'personal-portability/manifest/v1','profile':'personal-codex',
            'repositories':[{'id':key,'path':value[0],'revision':value[1],
                             'required':True,'disposition':'source-only'} for key,value in m.PROJECTS.items()]}


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='personal-dev-scope-') as raw:
        root = Path(raw).resolve()
        home = root/'home';home.mkdir(mode=0o700)
        doc = document()
        # Poison pointers are deliberately outside the selected twelve, even
        # though their rows exist in the bound synthetic manifest as held data.
        doc['repositories'].extend([
            {'id':'KleinPerkins/held-personal','path':'personal/held-personal','required':True,'disposition':'blocked-review'},
            {'id':'KleinPerkins/chaos-scheduler','path':'personal/chaos-scheduler','required':True,'disposition':'blocked-protected'},
            {'id':'Excluded/work','path':'affirm/src/work','required':False,'disposition':'excluded-work'}])
        manifest = home/m.MANIFEST_RELATIVE;manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(doc));manifest.chmod(0o600)
        for relative,_ in m.PROJECTS.values():
            repo = home/'dev'/relative;repo.mkdir(parents=True,mode=0o700)
            (repo/'.git').mkdir(mode=0o700)
            (repo/'.git/config').write_bytes(b'[user]\n email = synthetic-noreply@example.invalid\n')
        poison = root/'poison';poison.mkdir()
        for relative in ['dev/affirm','dev/personal/held-personal','dev/personal/chaos-scheduler','.codex/worktrees']:
            p=home/relative;p.parent.mkdir(exist_ok=True,parents=True);p.symlink_to(poison,target_is_directory=True)
        with patch.object(m,'operator_home',return_value=home), patch.object(m,'MANIFEST_SHA256',hashlib.sha256(manifest.read_bytes()).hexdigest()):
            yield home,manifest,poison


class PersonalScope(unittest.TestCase):
    def test_operator_home_refuses_root_privilege_mismatch_and_home_redirect(self):
        home=Path('/synthetic/operator')
        for uid,euid,environment,accepted in [(1001,1001,home,True),(0,0,home,False),(1001,0,home,False),(1001,1001,Path('/other'),False)]:
            with self.subTest(uid=uid,euid=euid,environment=environment),patch.object(m.os,'getuid',return_value=uid),patch.object(m.os,'geteuid',return_value=euid),patch.object(m.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(home))),patch.object(Path,'home',return_value=environment):
                if accepted:self.assertEqual(m.operator_home(),home)
                else:
                    with self.assertRaises(ValueError):m.operator_home()

    def test_closed_selection_before_any_filesystem_or_home_access(self):
        for ids in [[],['KleinPerkins/dev'],['KleinPerkins/chaos-scheduler'],['Excluded/work'],['skills'],
                    ['KleinPerkins/skills','KleinPerkins/skills'],[True],[['KleinPerkins/skills']]]:
            with self.subTest(ids=ids), patch.object(m.os,'open',side_effect=AssertionError('filesystem touched')), patch.object(Path,'home',side_effect=AssertionError('home touched')):
                with self.assertRaises(ValueError):m.PersonalScope(repositories=ids)

    def test_parse_every_closed_source_row_and_ignore_unselected_metadata(self):
        doc=document();doc['repositories'].append({'id':'Outside/held','path':'../../poison'})
        rows=m.parse_manifest(json.dumps(doc).encode())
        self.assertEqual(set(rows),set(m.PROJECTS))
        for key,(relative,revision) in m.PROJECTS.items():
            self.assertEqual(rows[key],{'id':key,'path':relative,'revision':revision})

    def test_parse_rejects_schema_profile_duplicates_missing_and_changed_source_facts(self):
        mutations=[lambda d:d.update(schema='other'),lambda d:d.update(profile='work'),
                   lambda d:d['repositories'].append(copy.deepcopy(d['repositories'][0])),lambda d:d['repositories'].pop(),
                   lambda d:d['repositories'][0].update(path='../outside'),lambda d:d['repositories'][0].update(revision='0'*40),
                   lambda d:d['repositories'][0].update(required=1),lambda d:d['repositories'][0].update(disposition='blocked-review'),
                   lambda d:d.update(repositories='not-list')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                d=document();mutate(d)
                with self.assertRaises(ValueError):m.parse_manifest(json.dumps(d).encode())
        with self.assertRaisesRegex(ValueError,'duplicate manifest key'):
            m.parse_manifest(b'{"schema":"x","schema":"y"}')

    def test_inspect_twelve_uses_no_enumeration_git_network_or_mutation(self):
        with fixture() as (home,manifest,poison), ExitStack() as stack:
            real_open=os.open;opened=[];fd_paths={}
            def guarded(path,flags,*args,**kw):
                parent=kw.get('dir_fd')
                full=Path(path) if parent is None else fd_paths[parent]/path
                opened.append(str(full))
                if any(part in full.parts for part in ['affirm','held-personal','chaos-scheduler','.codex','poison']):
                    raise AssertionError('excluded path was accessed')
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertFalse(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
                fd=real_open(path,flags,*args,**kw);fd_paths[fd]=full
                return fd
            stack.enter_context(patch.object(m.os,'open',side_effect=guarded))
            for obj,name in [(m.os,'scandir'),(m.os,'listdir'),(m.os,'walk'),(subprocess,'run'),(socket,'socket'),(m.os,'unlink'),(m.os,'mkdir')]:
                stack.enter_context(patch.object(obj,name,side_effect=AssertionError('enumeration/network/Git/mutation forbidden')))
            result=m.inspect(m.PersonalScope(manifest))
            self.assertEqual(result['target_count'],12)
            self.assertFalse(result['doctor_or_native_qualification_proven'])
            self.assertFalse(result['source_pins_or_cleanliness_inspected'])
            self.assertTrue(opened)

    def test_targets_selects_without_touching_any_repository(self):
        with fixture() as (_,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
            with patch.object(m.os,'open',side_effect=AssertionError('target inspected')):
                self.assertEqual([r['id'] for r in scope.targets()],['KleinPerkins/skills'])
                for identifier in ['KleinPerkins/awa','KleinPerkins/chaos-scheduler','../outside']:
                    with self.assertRaises(ValueError):
                        with scope.repository(identifier):pass

    def test_digest_drift_refuses_before_parsing_or_repository_access(self):
        with fixture() as (_,manifest,_):
            original=manifest.read_bytes();manifest.write_bytes(original+b' ')
            with patch.object(m,'parse_manifest',side_effect=AssertionError('unbound document parsed')):
                with self.assertRaisesRegex(ValueError,'approved portability manifest bytes'):m.PersonalScope(manifest)
            self.assertEqual(manifest.read_bytes(),original+b' ')

    def test_manifest_override_and_cli_scope_expansion_refuse(self):
        with fixture() as (home,manifest,_):
            with patch.object(m.os,'open',side_effect=AssertionError('alternate read')):
                for path in [Path('relative'),home/'other.json',Path('/private/tmp/other.json')]:
                    with self.assertRaises(ValueError):m.PersonalScope(path)
            for flags in [['--root',str(home)],['--remote'],['--write-matrix'],['--fix-hooks'],['--home',str(home)]]:
                with self.subTest(flags=flags), patch('sys.stderr',new=io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:m.main(['inspect',*flags])
                    self.assertEqual(cm.exception.code,2)

    def test_linked_manifest_file_and_parent_and_hardlink_are_refused(self):
        for kind in ['file-link','parent-link','hardlink']:
            with self.subTest(kind=kind),fixture() as (home,manifest,poison):
                if kind=='file-link':
                    original=manifest.read_bytes();manifest.unlink();(poison/'manifest.json').write_bytes(original);manifest.symlink_to(poison/'manifest.json')
                elif kind=='parent-link':
                    manifest.parent.rename(manifest.parent.with_name('original'));manifest.parent.symlink_to(manifest.parent.with_name('original'),target_is_directory=True)
                else:os.link(manifest,poison/'manifest-copy')
                with self.assertRaises((OSError,ValueError)):m.PersonalScope(manifest)

    def test_repository_each_path_component_symlink_refuses(self):
        for relative in ['dev','dev/capabilities','dev/capabilities/skills']:
            with self.subTest(relative=relative),fixture() as (home,manifest,poison):
                scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
                p=home/relative;p.rename(p.with_name(p.name+'-kept'));p.symlink_to(poison,target_is_directory=True)
                with self.assertRaises(OSError):m.inspect(scope)
                self.assertTrue(p.is_symlink())

    def test_private_regular_metadata_read_and_all_lexical_escapes_refuse_before_open(self):
        with fixture() as (_,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
            with scope.repository('KleinPerkins/skills') as repo:
                self.assertIn(b'synthetic-noreply',repo.read_file('.git/config'))
                for path in ['', '/', '../x', '.git/../x', './x', '~/.gitconfig', '.git//config', '.git/config/', 'x\x00y', 'x\ny']:
                    with self.subTest(path=path),patch.object(m.os,'open',side_effect=AssertionError('escape touched')):
                        with self.assertRaises(ValueError):repo.read_file(path)

    def test_linked_child_directory_file_and_hardlinked_file_do_not_escape(self):
        for kind in ['directory-link','file-link','hardlink']:
            with self.subTest(kind=kind),fixture() as (home,manifest,poison):
                repo_path=home/'dev/capabilities/skills';target=repo_path/'.git/config'
                if kind=='directory-link':
                    (repo_path/'.git').rename(repo_path/'.git-kept');(repo_path/'.git').symlink_to(poison,target_is_directory=True)
                elif kind=='file-link':
                    target.unlink();(poison/'config').write_bytes(b'never read');target.symlink_to(poison/'config')
                else:os.link(target,poison/'config')
                with m.PersonalScope(manifest,repositories=['KleinPerkins/skills']).repository('KleinPerkins/skills') as repo:
                    with self.assertRaises((OSError,ValueError)):repo.read_file('.git/config')

    def test_missing_special_large_and_invalid_byte_limits_refuse(self):
        with fixture() as (home,manifest,_):
            path=home/'dev/capabilities/skills'
            (path/'large').write_bytes(b'x'*100)
            os.mkfifo(path/'fifo',0o600)
            with m.PersonalScope(manifest,repositories=['KleinPerkins/skills']).repository('KleinPerkins/skills') as repo:
                with self.assertRaises(FileNotFoundError):repo.read_file('missing')
                for name,limit in [('large',10),('fifo',10),('large',True),('large',0),('large',m.MAX_FILE_BYTES+1)]:
                    with self.subTest(name=name,limit=limit),self.assertRaises(ValueError):repo.read_file(name,max_bytes=limit)

    def test_in_place_edit_during_read_is_visible_and_preserved(self):
        with fixture() as (home,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
            config=home/'dev/capabilities/skills/.git/config';real_read=os.read;once=[]
            with scope.repository('KleinPerkins/skills') as repo:
                def edit(fd,n):
                    data=real_read(fd,n)
                    if not once:once.append(True);config.write_bytes(b'foreign owner edit preserved')
                    return data
                with patch.object(m.os,'read',side_effect=edit),self.assertRaisesRegex(ValueError,'changed during read'):repo.read_file('.git/config')
            self.assertEqual(config.read_bytes(),b'foreign owner edit preserved')

    def test_replaced_repository_path_refuses_and_preserves_both_directories(self):
        with fixture() as (home,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills']);path=home/'dev/capabilities/skills'
            with self.assertRaisesRegex(ValueError,'path changed'):
                with scope.repository('KleinPerkins/skills'):
                    path.rename(path.with_name('skills-kept'));path.mkdir(mode=0o700);(path/'foreign').write_bytes(b'keep')
            self.assertTrue(path.with_name('skills-kept').is_dir());self.assertEqual((path/'foreign').read_bytes(),b'keep')

    def test_replaced_file_and_parent_paths_are_visible_and_preserved(self):
        for kind in ['file','parent']:
            with self.subTest(kind=kind),fixture() as (home,manifest,_):
                scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
                folder=home/'dev/capabilities/skills/.git';config=folder/'config';real_read=os.read;once=[]
                with scope.repository('KleinPerkins/skills') as repo:
                    def replace(fd,n):
                        data=real_read(fd,n)
                        if not once:
                            once.append(True)
                            if kind=='file':config.rename(folder/'config-kept');config.write_bytes(b'foreign replacement')
                            else:folder.rename(folder.with_name('.git-kept'));folder.mkdir(mode=0o700);config.write_bytes(b'foreign replacement')
                        return data
                    with patch.object(m.os,'read',side_effect=replace),self.assertRaisesRegex(ValueError,'changed during read'):
                        repo.read_file('.git/config')
                self.assertEqual(config.read_bytes(),b'foreign replacement')

    def test_foreign_child_directory_is_refused(self):
        with fixture() as (_,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills'])
            with scope.repository('KleinPerkins/skills') as repo:
                real_fstat=os.fstat
                def foreign(fd):
                    info=real_fstat(fd)
                    return SimpleNamespace(st_uid=os.getuid()+1) if stat_is_directory(info) else info
                def stat_is_directory(info):
                    import stat
                    return stat.S_ISDIR(info.st_mode)
                with patch.object(m.os,'fstat',side_effect=foreign),self.assertRaisesRegex(ValueError,'child directory'):
                    repo.read_file('.git/config')

    def test_caller_failure_closes_repository_descriptor(self):
        with fixture() as (_,manifest,_):
            scope=m.PersonalScope(manifest,repositories=['KleinPerkins/skills']);fd=None
            with self.assertRaisesRegex(RuntimeError,'caller failed'):
                with scope.repository('KleinPerkins/skills') as repo:fd=repo._fd;raise RuntimeError('caller failed')
            with self.assertRaises(OSError):os.fstat(fd)

    def test_cli_selected_inspect_reports_scope_without_qualification(self):
        with fixture() as (_,manifest,_),patch('sys.stdout',new=io.StringIO()) as stdout:
            self.assertEqual(m.main(['inspect','--portability-manifest',str(manifest),'--repository','KleinPerkins/skills']),0)
            result=json.loads(stdout.getvalue());self.assertEqual(result['target_count'],1)
            self.assertFalse(result['doctor_or_native_qualification_proven'])


if __name__=='__main__':unittest.main()
