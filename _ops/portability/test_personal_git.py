"""Config-before-probe, no-follow storage and bounded real metadata fixtures."""
from contextlib import contextmanager, ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_git as m
from test_personal_scope import document

GIT=(m.GIT_PATH if m.GIT_PATH.is_file() else Path(shutil.which('git'))).resolve()
GIT_DIGEST=hashlib.sha256(GIT.read_bytes()).hexdigest()
HELP=subprocess.run([str(GIT),'-h'],capture_output=True).stdout
FIXTURE_FLAGS=m.FLAGS if b'--no-lazy-fetch' in HELP else tuple(f for f in m.FLAGS if f!='--no-lazy-fetch')
# An older CI Git may lack the future global flag. Only disposable, complete,
# local fixtures omit that flag. The compiled macOS route/tool binding and its
# full flag set remain unchanged; fixture evidence grants no native qualification.


@contextmanager
def qualified_fixture_tool():
    with patch.object(m,'GIT_PATH',GIT),patch.object(m,'GIT_SHA256',GIT_DIGEST):
        yield m.GitTool()


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='personal-Git-fixture-') as raw:
        home=Path(raw).resolve()/'home';home.mkdir(mode=0o700)
        manifest=home/m.scope_module.MANIFEST_RELATIVE;manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(document()));manifest.chmod(0o600)
        root=home/'dev/capabilities/skills';root.mkdir(parents=True,mode=0o700)
        def git(*args):
            r=subprocess.run([str(GIT),'-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args],
                             cwd=root,env=m.clean_environment(),capture_output=True,timeout=5)
            if r.returncode:raise AssertionError((args,r.returncode,r.stderr.decode(errors='replace')))
            return r.stdout.strip()
        git('init','--template=','-b','main')
        git('config','user.name','KleinPerkins');git('config','user.email',m.NOREPLY)
        git('remote','add','origin','git@github.com:KleinPerkins/skills.git')
        (root/'fixture.txt').write_text('one\n');git('add','fixture.txt');git('commit','-m','synthetic one')
        with qualified_fixture_tool() as tool,patch.object(m.scope_module,'operator_home',return_value=home),patch.object(m.scope_module,'MANIFEST_SHA256',hashlib.sha256(manifest.read_bytes()).hexdigest()),patch.object(m,'FLAGS',FIXTURE_FLAGS):
            scope=m.scope_module.PersonalScope(repositories=['KleinPerkins/skills'])
            yield root,scope,tool,git


def observe(scope,tool):
    with scope.repository('KleinPerkins/skills') as repo:return m.PersonalGit(repo,tool).observe()


class Config(unittest.TestCase):
    def test_clean_environment_preserves_home_and_omits_foreign_overrides(self):
        foreign={'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'include.path','GIT_CONFIG_VALUE_0':'/not-read',
                 'GIT_DIR':'/not-read','GIT_EXEC_PATH':'/not-executed','GIT_TRACE':'/not-written',
                 'SSH_AUTH_SOCK':'/not-used','HTTPS_PROXY':'/not-used','OPENAI_API_KEY':'synthetic-never-inherit'}
        with patch.dict(os.environ,foreign):
            result=m.clean_environment()
            self.assertFalse(set(foreign)&set(result))
            if 'HOME' in os.environ:self.assertEqual(result['HOME'],os.environ['HOME'])
            self.assertEqual(result['GIT_CONFIG_GLOBAL'],'/dev/null')
            self.assertEqual(result['GIT_ALLOW_PROTOCOL'],'')

    def test_production_route_requires_all_no_side_effect_flags(self):
        self.assertIn('--no-lazy-fetch',m.FLAGS);self.assertIn('--no-optional-locks',m.FLAGS)
        self.assertIn('--no-replace-objects',m.FLAGS)
        self.assertNotIn('status',m.COMMANDS);self.assertNotIn('worktree',m.COMMANDS)
        self.assertNotIn('fetch',m.COMMANDS)

    def test_real_Git_parser_handles_comments_quotes_multivalue_and_boolean(self):
        with qualified_fixture_tool() as tool:
            result=tool.parse_config(b'# fixture\n[core]\n bare\n[remote "origin"]\n url="first\\nsecond"\n url = third # comment\n')
            self.assertEqual(result['core.bare'],[None])
            self.assertEqual(result['remote.origin.url'],['first\nsecond','third'])

    def test_parser_does_not_expand_include_or_ambient_global_config(self):
        with tempfile.TemporaryDirectory() as raw,qualified_fixture_tool() as tool:
            poison=Path(raw)/'poison';os.mkfifo(poison,0o600)
            result=tool.parse_config(f'[include]\n path = {poison}\n'.encode())
            self.assertEqual(result['include.path'],[str(poison)])
            self.assertNotIn('user.email',result)

    def test_parse_failure_is_redacted(self):
        with qualified_fixture_tool() as tool:
            with self.assertRaises(m.Refusal) as cm:tool.parse_config(b'[broken LOCAL_SYNTHETIC_PRIVATE_MARKER')
            self.assertNotIn('LOCAL_SYNTHETIC_PRIVATE_MARKER',str(cm.exception))

    def test_origin_exact_identity_and_all_supported_forms(self):
        expected='KleinPerkins/skills'
        for value in [f'git@github.com:{expected}.git',f'https://github.com/{expected}',f'https://github.com/{expected}.git',f'ssh://git@github.com/{expected}.git']:
            self.assertTrue(m.personal_remote(value,expected))
        for value in [None,'git@github.com:Excluded/work.git','https://user:synthetic@github.com/KleinPerkins/skills','https://github.com.invalid/KleinPerkins/skills','https://github.com/KleinPerkins/skills/extra','git@github.com:KleinPerkins/chaos-scheduler.git']:
            self.assertFalse(m.personal_remote(value,expected))

    def test_include_filters_partial_clone_rewrites_storage_formats_and_alias_paths_hold(self):
        root=Path('/synthetic/personal')
        cases={'include.path':['/not-read'],'includeif.gitdir:/not-read.path':['/not-read'],
               'filter.synthetic.process':['never-execute'],'extensions.partialclone':['origin'],
               'remote.origin.promisor':['true'],'url.ssh://not-used.insteadof':['git@github.com:'],
               'core.alternaterefscommand':['never-execute'],'extensions.refstorage':['reftable'],
               'extensions.objectformat':['sha256'],'extensions.future':['true'],'core.bare':['true'],
               'core.worktree':['/outside'],'remote.other.url':['git@github.com:Excluded/work.git']}
        for key,values in cases.items():
            cfg={'remote.origin.url':['git@github.com:KleinPerkins/skills.git'],key:values}
            with self.subTest(key=key),self.assertRaises(m.Refusal):m.validate_config(cfg,'KleinPerkins/skills',root)
        m.validate_config({'remote.origin.url':['git@github.com:KleinPerkins/skills.git'],'core.worktree':['..']},'KleinPerkins/skills',root)

    def test_duplicate_origin_and_missing_origin_refuse(self):
        for cfg in [{},{'remote.origin.url':[None]},{'remote.origin.url':['git@github.com:KleinPerkins/skills.git']*2}]:
            with self.assertRaisesRegex(m.Refusal,'personal-origin'):m.validate_config(cfg,'KleinPerkins/skills',Path('/synthetic'))

    def test_qualified_binary_drift_stops_before_any_process(self):
        with patch.object(m,'GIT_PATH',GIT),patch.object(m,'GIT_SHA256','0'*64),patch.object(m,'bounded_process',side_effect=AssertionError('process started')):
            with self.assertRaisesRegex(m.Refusal,'binary-changed'):m.GitTool()


class Metadata(unittest.TestCase):
    def test_split_index_metadata_queries_preserve_source_bytes_and_timestamps(self):
        with fixture() as (root,scope,tool,git):
            git('update-index','--split-index')
            shared=list((root/'.git').glob('sharedindex.*'));self.assertTrue(shared)
            for path in shared:os.utime(path,ns=(1000000000,1000000000))
            paths=[root/'.git/index',root/'.git/config',*shared]
            def facts():
                return [(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths]
            before=facts();result=observe(scope,tool)
            self.assertFalse(result['worktree_status_proven']);self.assertEqual(facts(),before)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool);ctx.probe('memory_index');ctx.finish()
            self.assertEqual(facts(),before)

    def test_private_config_preserves_tracking_and_data_policy_without_auth_or_helpers(self):
        with fixture() as (root,scope,tool,git):
            initial=git('rev-parse','HEAD').decode();git('update-ref','refs/remotes/origin/main',initial)
            for key,value in [('branch.main.remote','origin'),('branch.main.merge','refs/heads/main'),
                              ('core.ignorecase','true'),('core.precomposeunicode','true'),
                              ('core.fsmonitor','SYNTHETIC_NEVER_EXECUTE'),
                              ('core.hookspath','/synthetic-not-followed'),
                              ('credential.helper','SYNTHETIC_NEVER_EXECUTE'),
                              ('http.extraHeader','SYNTHETIC_PRIVATE_MARKER'),
                              ('user.signingkey','SYNTHETIC_PRIVATE_MARKER')]:git('config',key,value)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool)
                raw=ctx.private_config();cfg=tool.parse_config(raw)
                self.assertNotIn(b'SYNTHETIC_',raw)
                self.assertEqual(cfg['core.ignorecase'],['true'])
                self.assertEqual(cfg['core.precomposeunicode'],['true'])
                self.assertEqual(cfg['branch.main.remote'],['origin'])
                self.assertEqual(cfg['remote.origin.url'],['git@github.com:KleinPerkins/skills.git'])
                with ctx.private_gitdir() as view:
                    self.assertNotEqual(view,root/'.git')
                    self.assertEqual((view/'config').stat().st_mode&0o777,0o600)
                    self.assertTrue((view/'objects').is_dir())
                    self.assertFalse((view/'objects').is_symlink())
                    original=next(p for p in (root/'.git/objects').rglob('*') if p.is_file())
                    copied=view/'objects'/original.relative_to(root/'.git/objects')
                    self.assertEqual(copied.read_bytes(),original.read_bytes())
                    self.assertFalse(os.path.samefile(copied,original))
                    self.assertEqual(ctx.observe()['upstream'],'origin/main')
                self.assertFalse(view.exists())

    def test_private_metadata_budget_refuses_without_querying_source(self):
        with fixture() as (root,scope,tool,git):
            before=(root/'.git/index').read_bytes()
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool)
                with patch.object(m,'MAX_PRIVATE_BYTES',1),self.assertRaisesRegex(m.Refusal,'copy-bound'):
                    ctx.observe()
                self.assertEqual(ctx.probes,[])
            self.assertEqual((root/'.git/index').read_bytes(),before)

    def test_actual_local_metadata_never_claims_worktree_remote_or_native_proof(self):
        with fixture() as (root,scope,tool,git):
            before=(root/'.git/config').read_bytes(),(root/'.git/index').read_bytes()
            result=observe(scope,tool)
            self.assertEqual(result['head'],git('rev-parse','HEAD').decode())
            self.assertEqual(result['branch'],'main');self.assertFalse(result['detached'])
            self.assertTrue(result['local_identity_canonical']);self.assertIsNone(result['upstream'])
            self.assertFalse(result['pin_matches']);self.assertFalse(result['worktree_status_proven'])
            self.assertFalse(result['doctor_or_native_qualification_proven']);self.assertEqual(result['remote_requests'],0)
            self.assertEqual(before,((root/'.git/config').read_bytes(),(root/'.git/index').read_bytes()))

    def test_detached_HEAD_without_upstream_is_not_declared_remote_sync(self):
        with fixture() as (_,scope,tool,git):
            git('checkout','--detach');result=observe(scope,tool)
            self.assertTrue(result['detached']);self.assertIsNone(result['branch'])
            self.assertIsNone(result['ahead']);self.assertIsNone(result['behind'])

    def test_local_upstream_counts_and_unpushed_work_are_exact(self):
        with fixture() as (root,scope,tool,git):
            initial=git('rev-parse','HEAD');git('update-ref','refs/remotes/origin/main',initial.decode())
            git('config','branch.main.remote','origin');git('config','branch.main.merge','refs/heads/main')
            (root/'fixture.txt').write_text('two\n');git('add','fixture.txt');git('commit','-m','synthetic two')
            result=observe(scope,tool);self.assertEqual((result['ahead'],result['behind']),(1,0))
            self.assertEqual(result['upstream'],'origin/main')

    def test_tracked_memory_is_detected_without_reading_its_contents(self):
        with fixture() as (root,scope,tool,git):
            p=root/'agent-learnings.md';p.write_bytes(b'synthetic old machine memory');git('add','agent-learnings.md');git('commit','-m','synthetic tracked name')
            p.unlink();os.mkfifo(p,0o600)
            result=observe(scope,tool)
            self.assertTrue(result['tracked_agent_learnings']);self.assertFalse(result['generated_memory_contents_read'])
            self.assertFalse(result['worktree_status_proven'])

    def test_wrong_origin_stops_before_other_metadata_or_target_Git(self):
        with fixture() as (_,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            real=m.file_fact
            def config_only(repo,path,**kw):
                if path!='.git/config':raise AssertionError('other metadata read')
                return real(repo,path,**kw)
            with patch.object(m,'file_fact',side_effect=config_only),patch.object(m,'storage_inventory',side_effect=AssertionError('storage read')):
                with self.assertRaisesRegex(m.Refusal,'personal-origin'):observe(scope,tool)

    def test_worktree_overlay_supported_and_actual_identity_is_distinct(self):
        with fixture() as (_,scope,tool,git):
            git('config','extensions.worktreeConfig','true');git('config','user.email','synthetic-other@example.invalid')
            git('config','--worktree','user.email',m.NOREPLY)
            result=observe(scope,tool)
            self.assertFalse(result['local_identity_canonical']);self.assertTrue(result['effective_personal_identity_canonical'])
            self.assertEqual(result['effective_identity_scope'],'worktree')
            self.assertIsNotNone(result['worktree_config_sha256'])

    def test_worktree_extension_without_overlay_and_wrong_name_are_explicit(self):
        with fixture() as (_,scope,tool,git):
            git('config','extensions.worktreeConfig','true');git('config','user.name','Synthetic Different Name')
            result=observe(scope,tool)
            self.assertTrue(result['local_email_canonical']);self.assertFalse(result['local_identity_canonical'])
            self.assertIsNone(result['worktree_config_sha256']);self.assertEqual(result['effective_identity_scope'],'local')

    def test_overlay_include_or_origin_override_refuses_before_target_probes(self):
        for text in ['[include]\n path = /never-read\n','[remote "origin"]\n url = git@github.com:Excluded/work.git\n']:
            with self.subTest(text=text),fixture() as (root,scope,tool,git):
                git('config','extensions.worktreeConfig','true');(root/'.git/config.worktree').write_text(text)
                with patch.object(m,'storage_inventory',side_effect=AssertionError('storage read')):
                    with self.assertRaises(m.Refusal):observe(scope,tool)

    def test_configured_helper_is_never_executed_and_no_worktree_body_is_read(self):
        with fixture() as (root,scope,tool,git):
            sentinel=root/'never-created'
            git('config','core.fsmonitor',f'printf poison > {sentinel}')
            git('config','core.sshCommand',f'printf poison > {sentinel}')
            git('config','credential.helper',f'!printf poison > {sentinel}')
            (root/'fixture.txt').unlink();os.mkfifo(root/'fixture.txt',0o600)
            result=observe(scope,tool)
            self.assertFalse(sentinel.exists());self.assertEqual(len(result['probes']),4)

    def test_commondir_grafts_and_gitdir_pointers_are_not_followed(self):
        for name in ['commondir','gitdir','info/grafts']:
            with self.subTest(name=name),fixture() as (root,scope,tool,_):
                p=root/'.git'/name;p.parent.mkdir(exist_ok=True);p.write_text('/not-read\n')
                with self.assertRaisesRegex(m.Refusal,'non-primary-or-rewritten'):observe(scope,tool)

    def test_alternates_storage_symlink_shared_file_and_special_file_hold(self):
        for kind in ['alternates','directory-link','file-link','hardlink','fifo']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                objects=root/'.git/objects'
                if kind=='alternates':(objects/'info/alternates').write_text('/not-read\n')
                elif kind=='directory-link':(objects/'synthetic-link').symlink_to(root.parent,target_is_directory=True)
                elif kind=='file-link':(objects/'synthetic-link').symlink_to(root/'fixture.txt')
                elif kind=='hardlink':os.link(root/'fixture.txt',objects/'synthetic-shared')
                else:os.mkfifo(objects/'synthetic-fifo',0o600)
                with self.assertRaises(m.Refusal):observe(scope,tool)

    def test_metadata_alias_types_and_index_parent_links_hold(self):
        for kind in ['HEAD-link','index-link','index-hardlink']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,_):
                p=root/'.git'/('HEAD' if kind=='HEAD-link' else 'index')
                if kind=='index-hardlink':os.link(p,root/'synthetic-index-copy')
                else:p.rename(p.with_name(p.name+'-kept'));p.symlink_to(p.with_name(p.name+'-kept'))
                with self.assertRaises(m.Refusal):observe(scope,tool)

    def test_changed_config_stops_before_next_target_probe(self):
        with fixture() as (root,scope,tool,_):
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool);p=root/'.git/config';p.write_bytes(p.read_bytes()+b'\n# later owner edit\n')
                with patch.object(m,'bounded_process',side_effect=AssertionError('target probe started')):
                    with self.assertRaisesRegex(m.Refusal,'config-changed'):ctx.observe()

    def test_changed_refs_are_reported_and_preserved(self):
        with fixture() as (root,scope,tool,git):
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool);git('update-ref','refs/heads/owner-later','HEAD')
                with self.assertRaisesRegex(m.Refusal,'metadata-changed'):ctx.observe()
            self.assertTrue((root/'.git/refs/heads/owner-later').exists())

    def test_identical_config_path_replacement_is_not_adopted(self):
        for overlay in [False,True]:
            with self.subTest(overlay=overlay),fixture() as (root,scope,tool,git):
                if overlay:git('config','extensions.worktreeConfig','true');git('config','--worktree','user.email',m.NOREPLY)
                with scope.repository('KleinPerkins/skills') as repo:
                    ctx=m.PersonalGit(repo,tool);p=root/'.git'/('config.worktree' if overlay else 'config');raw=p.read_bytes()
                    p.rename(p.with_name(p.name+'-owner-kept'));p.write_bytes(raw)
                    with patch.object(m,'bounded_process',side_effect=AssertionError('target probe started')):
                        with self.assertRaisesRegex(m.Refusal,'config-changed'):ctx.observe()
                    self.assertEqual(p.read_bytes(),raw);self.assertTrue(p.with_name(p.name+'-owner-kept').exists())

    def test_unknown_Git_verb_refuses_before_process(self):
        with fixture() as (_,scope,tool,_):
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalGit(repo,tool)
                with patch.object(m,'bounded_process',side_effect=AssertionError('process started')):
                    for name in ['status','fetch','push','worktree','reset','config','head; anything']:
                        with self.assertRaisesRegex(m.Refusal,'closed-metadata'):ctx.probe(name)

    def test_storage_budget_refuses_without_inferred_success(self):
        with fixture() as (_,scope,tool,_),patch.object(m,'MAX_METADATA_ENTRIES',1):
            with self.assertRaisesRegex(m.Refusal,'inventory-bound'):observe(scope,tool)

    def test_inspector_redacts_bad_config_and_returns_unavailable_not_OK(self):
        with fixture() as (root,scope,tool,_):
            (root/'.git/config').write_text('[broken LOCAL_SYNTHETIC_PRIVATE_MARKER')
            result=m.inspect(scope,tool)
            self.assertEqual(result['rows'][0]['status'],'unavailable')
            self.assertNotIn('LOCAL_SYNTHETIC_PRIVATE_MARKER',json.dumps(result))
            self.assertFalse(result['doctor_or_native_qualification_proven'])


class Processes(unittest.TestCase):
    def test_bounded_binary_pipe_input_output_and_stderr(self):
        args=[sys.executable,'-I','-B','-c','import sys;d=sys.stdin.buffer.read();sys.stdout.buffer.write(d);sys.stderr.write("synthetic")']
        code,out,err=m.bounded_process(args,Path(tempfile.gettempdir()),b'x'*200000)
        self.assertEqual(code,0);self.assertEqual(out,b'x'*200000);self.assertEqual(err,b'synthetic')

    def test_timeout_observes_the_same_process_terminal_without_retry(self):
        actual=subprocess.Popen;seen=[]
        def capture(*args,**kw):p=actual(*args,**kw);seen.append(p);return p
        with patch.object(m,'TIMEOUT',0.1),patch.object(m.subprocess,'Popen',side_effect=capture):
            with self.assertRaisesRegex(m.Refusal,'timeout'):m.bounded_process([sys.executable,'-I','-B','-c','import time;time.sleep(10)'],Path(tempfile.gettempdir()))
        self.assertEqual(len(seen),1);self.assertIsNotNone(seen[0].poll())

    def test_output_limit_terminates_the_same_process(self):
        actual=subprocess.Popen;seen=[]
        def capture(*args,**kw):p=actual(*args,**kw);seen.append(p);return p
        with patch.object(m,'MAX_OUTPUT',1024),patch.object(m.subprocess,'Popen',side_effect=capture):
            with self.assertRaisesRegex(m.Refusal,'output-limit'):m.bounded_process([sys.executable,'-I','-B','-c','import sys;sys.stdout.buffer.write(b"x"*100000)'],Path(tempfile.gettempdir()))
        self.assertEqual(len(seen),1);self.assertIsNotNone(seen[0].poll())

    def test_CLI_rejects_extra_roots_commands_and_writers(self):
        for args in [['status'],['inspect','--root','/elsewhere'],['inspect','--remote'],['inspect','--fix-hooks'],['inspect','--Git','/elsewhere']]:
            with self.subTest(args=args),patch('sys.stderr',new=io.StringIO()):
                with self.assertRaises(SystemExit) as cm:m.main(args)
                self.assertEqual(cm.exception.code,2)


if __name__=='__main__':unittest.main()
