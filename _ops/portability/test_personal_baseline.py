"""Five-file canonical oracles, full aggregation matrix and scoped Git fixtures."""
from contextlib import contextmanager,redirect_stdout
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_baseline as m
from test_personal_git import fixture
g,w,s=m.g,m.w,m.s
LIB=Path(__file__).parents[1]/'bin/baseline-lib.sh'
# Successor delivery-policy changes leave the eight qualified pure baseline bodies
# unchanged. Bind this reviewed library container separately from historical provenance.
LIB_SHA256='72dc35fc69a318c92c77a9fd64c24dd2d550cad678fbe46aba559ad572273ea2'
CURRENT_OWNER_LIBRARY_BLOB='ea14195da47b61e55734e8ebdca8cf16bc957700'


def observe(scope,tool):
    with scope.repository('KleinPerkins/skills') as repo:
        return m.PersonalBaseline(repo,tool,m.load_templates()).observe()


def commit_fixture(git):
    git('add','-A');git('commit','--allow-empty','-m','synthetic baseline state')


def complete(root):
    templates=m.load_templates();(root/'.github').mkdir(exist_ok=True)
    (root/'SECURITY.md').write_bytes(templates['SECURITY.md'])
    (root/'.github/dependabot.yml').write_bytes(templates['dependabot.yml'])
    (root/'.gitignore').write_bytes(m.HASH_BEGIN+b'\n'+templates['gitignore-block.txt']+m.HASH_END+b'\n')
    (root/'README.md').write_text('Synthetic project documentation, freely maintained\n')
    (root/'.github/CODEOWNERS').write_text('# Synthetic custom ownership is allowed\n* @example\n')


@contextmanager
def oracle():
    # Only exact current accepted PURE read-only function bodies are evaluated
    # against disposable fixture files. Never source/execute the full library,
    # lib.sh, archived recovery code, GitHub/profile verbs or a target checkout.
    raw=LIB.read_bytes();assert hashlib.sha256(raw).hexdigest()==LIB_SHA256
    source=raw.decode();names=['bl_render_security_md','bl_render_dependabot','bl_render_gitignore_block',
                             'bl_check_managed_file','bl_check_create_only','bl_extract_block',
                             'bl_check_gitignore_block','bl_overall_verdict']
    functions=[]
    for name in names:
        match=re.search(r'(?m)^'+name+r'\(\) *\{[^\n]*\}$',source)
        if not match:match=re.search(r'(?ms)^'+name+r'\(\) *\{\n.*?^\}$',source)
        assert match,name
        functions.append(match[0])
    constants=[]
    for name in ['BL_MARK_HTML_BEGIN','BL_MARK_HTML_END','BL_MARK_HASH_BEGIN','BL_MARK_HASH_END']:
        match=re.search(r"(?m)^"+name+r"='[^\n]*'$",source);assert match,name
        constants.append(match[0])
    # The canonical bl_baseline_verdict caller binds repo before the nested
    # function's same-command local declaration expands f="$repo/...".
    # Preserve that dynamic caller binding; keep nounset enabled.
    script='\n'.join(['set -eu','BL_TEMPLATE_DIR="$1"; shift',*constants,*functions,
                       'fn="$1"; shift','repo="${1:-}"','"$fn" "$@"'])+'\n'
    with tempfile.TemporaryDirectory(prefix='personal-baseline-oracle-') as rawdir:
        path=Path(rawdir)/'pure-oracle.sh';path.write_text(script);path.chmod(0o600)
        def run(name,*args):
            assert name in names
            r=subprocess.run(['/bin/bash','--noprofile','--norc',str(path),str(m.HERE.parent/'baseline/template'),name,*map(str,args)],
                             capture_output=True,env=g.clean_environment(),timeout=5)
            if r.returncode:raise AssertionError((name,r.returncode,r.stderr.decode(errors='replace')))
            return r.stdout.decode().strip()
        yield run


class Templates(unittest.TestCase):
    def test_actual_templates_are_bound_to_exact_owner_hashes(self):
        templates=m.load_templates();self.assertEqual(set(templates),set(m.TEMPLATE_HASHES))
        for name,data in templates.items():self.assertEqual(hashlib.sha256(data).hexdigest(),m.TEMPLATE_HASHES[name])
        raw=LIB.read_bytes();self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),CURRENT_OWNER_LIBRARY_BLOB)

    def test_qualified_pure_functions_remain_byte_identical(self):
        expected = {'bl_render_security_md': 'ca473b99c6574bd28c4826976b287fa4577cb12f003164ccdf1ef5f31091bbec', 'bl_render_dependabot': 'ddf71f80e74866757067d4ed5eb999e8363c7f76cca7b2947c93bdce8746834d', 'bl_render_gitignore_block': '82e950b95f85a6cfcbd474b6923b9325adce128c919630b09e8ef14f11456ffe', 'bl_check_managed_file': '29eadc47cff09192072fe5a2bf31e23663574f0a642949628b7c54d9759861ad', 'bl_check_create_only': 'f0ef734dc7be351b889f2109d9cf5f0f70b8ecb00ae309f60bdcb1e1e85342e3', 'bl_extract_block': 'c93c834f0fe807d8460d8d9ed20afca2da725307dfadf187f865d4038c7196b4', 'bl_check_gitignore_block': '9d2168733b4b48cf905e4764318e6632b904f5f7279f5876ee79f1ac1db44112', 'bl_overall_verdict': '94a19baaf1e5310aa1778b7b476818e622cf30872f8edd2798cf26b498fa2d36'}
        source=LIB.read_text()
        for name,digest in expected.items():
            match=re.search(r'(?m)^'+name+r'\(\) *\{[^\n]*\}$',source)
            if not match:match=re.search(r'(?ms)^'+name+r'\(\) *\{\n.*?^\}$',source)
            self.assertIsNotNone(match,name)
            self.assertEqual(hashlib.sha256(match[0].encode()).hexdigest(),digest,name)

    def test_templates_or_aliases_cannot_be_substituted(self):
        accepted=m.load_templates()
        with tempfile.TemporaryDirectory() as raw:
            here=Path(raw).resolve()/'_ops/portability';here.mkdir(parents=True)
            template=here.parent/'baseline/template';template.mkdir(parents=True)
            for name,data in accepted.items():(template/name).write_bytes(data)
            for name,data in accepted.items():
                with self.subTest(name=name,kind='byte-drift'):
                    (template/name).write_bytes(data+b'\n')
                    with patch.object(m,'HERE',here),self.assertRaisesRegex(g.Refusal,'template-drift'):m.load_templates()
                    (template/name).write_bytes(data)
                with self.subTest(name=name,kind='alias'):
                    (template/name).unlink();(template/name).symlink_to('/not-followed')
                    with patch.object(m,'HERE',here),self.assertRaises(ValueError):m.load_templates()
                    (template/name).unlink();(template/name).write_bytes(data)

    def test_successor_security_policy_preserves_governed_delivery_semantics(self):
        current=m.load_templates()['SECURITY.md']
        self.assertIn(b'This repository is owned by **KleinPerkins**.',current)
        self.assertIn(b"Fixes follow the repository's governed verification, review and delivery process.",current)
        self.assertNotIn(b'This is a private repository',current)
        self.assertNotIn(b'fixes are pushed directly to `main`',current)
        predecessor=current.replace(b'This repository is owned',b'This is a private repository owned').replace(
            b"triaged promptly. Fixes follow the repository's governed verification, review and delivery process.",
            b'triaged promptly and fixes are pushed directly to `main` once verified.')
        self.assertEqual(hashlib.sha256(predecessor).hexdigest(),
                         'c3277d1c32d73cd80f805da82bf69c89b0aca9ae79eb934c0b09749bbc0cf98e')
        self.assertEqual(m.managed(predecessor,current,m.HTML_BEGIN),'STALE')
        altered=dict(m.load_templates());altered['SECURITY.md']=predecessor
        with patch.object(w,'PersonalWorktree',side_effect=AssertionError('target probe')):
            with self.assertRaisesRegex(g.Refusal,'template-drift'):m.PersonalBaseline(None,None,altered)

    def test_oracle_rejects_library_tampering_before_starting_any_process(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'baseline-lib.sh';path.write_bytes(LIB.read_bytes()+b'\n# synthetic drift\n')
            with patch(__name__+'.LIB',path),patch.object(subprocess,'run',side_effect=AssertionError('process started')):
                with self.assertRaises(AssertionError) as error:
                    with oracle():pass
            self.assertNotEqual(str(error.exception),'process started')

    def test_constructor_refuses_unbound_template_map_before_probe(self):
        with fixture() as (_,scope,tool,_),scope.repository('KleinPerkins/skills') as repo:
            with patch.object(w,'PersonalWorktree',side_effect=AssertionError('target probe')):
                with self.assertRaises(g.Refusal):m.PersonalBaseline(repo,tool,{})


class CanonicalOracles(unittest.TestCase):
    def test_all_192_aggregation_combinations_match_accepted_owner_function(self):
        count=0
        with oracle() as run:
            for sec,co,gi,rd,db in itertools.product(['MISSING','CURRENT','STALE','CUSTOM'],['MISSING','PRESENT'],['MISSING','CURRENT','STALE'],['MISSING','PRESENT'],['MISSING','CURRENT','STALE','CUSTOM']):
                states=dict(zip(m.FILES,[sec,co,gi,rd,db]));expected=run('bl_overall_verdict',sec,co,gi,rd,db)
                with self.subTest(states=states):self.assertEqual(m.overall(states),expected)
                count+=1
        self.assertEqual(count,192)

    def test_managed_security_and_dependabot_bytes_match_owner(self):
        templates=m.load_templates()
        with oracle() as run,tempfile.TemporaryDirectory() as raw:
            root=Path(raw);(root/'.github').mkdir()
            for path,name,marker,render,kind in [('SECURITY.md','SECURITY.md',m.HTML_BEGIN,'bl_render_security_md','html'),
                                               ('.github/dependabot.yml','dependabot.yml',m.HASH_BEGIN,'bl_render_dependabot','hash')]:
                expected=templates[name]
                variants=[None,b'custom owner file\n',expected,expected+b'\n',expected.replace(b'\n',b'\r\n'),b'prefix\n'+expected,marker+b'\nsynthetic stale content\n',b'\0'+marker+b'\n']
                for data in variants:
                    target=root/path
                    if target.exists():target.unlink()
                    if data is not None:target.write_bytes(data)
                    with self.subTest(path=path,variant=None if data is None else g.sha(data)):
                        self.assertEqual(m.managed(data,expected,marker),run('bl_check_managed_file',root,path,render,kind))

    def test_gitignore_exact_awk_and_shell_substitution_semantics(self):
        body=m.load_templates()['gitignore-block.txt'];block=m.HASH_BEGIN+b'\n'+body+m.HASH_END+b'\n'
        variants=[None,b'custom ignores\n',block,b'custom-before\n'+block+b'custom-after\n',block.rstrip(b'\n'),
                  block.replace(b'\n',b'\r\n'),block+block,m.HASH_BEGIN+b'\nmissing end\n',
                  m.HASH_END+b'\n'+block,b'prefix '+block,block.replace(m.HASH_END,b'prefix '+m.HASH_END),
                  block+b'\n\n',block.replace(body,b'changed\n'),m.HASH_BEGIN+b' '+m.HASH_END+b'\n',
                  block.replace(m.HASH_END,m.HASH_END+b'\n\n'),
                  block.replace(body,b'\0'+body),block.replace(m.HASH_END,b'\0'+m.HASH_END),
                  block.replace(m.HASH_BEGIN,m.HASH_BEGIN+b'\0'),b'\0'+block,
                  block.replace(m.HASH_BEGIN,m.HASH_BEGIN+b'\0ignored synthetic tail')]
        with oracle() as run,tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'.gitignore'
            for data in variants:
                # The production tool/route is Mac-bound. Other CI awk
                # implementations have different NUL string semantics; their
                # ordinary text fixtures are portable evidence only. Every NUL
                # vector is exercised against real BSD awk on the destination.
                if sys.platform!='darwin' and data is not None and b'\0' in data:continue
                if path.exists():path.unlink()
                if data is not None:path.write_bytes(data)
                with self.subTest(variant=None if data is None else g.sha(data)):
                    self.assertEqual(m.gitignore(data,body),run('bl_check_gitignore_block',root))

    def test_create_only_contents_are_not_template_compliance(self):
        with oracle() as run,tempfile.TemporaryDirectory() as raw:
            root=Path(raw);(root/'.github').mkdir()
            for path in ['README.md','.github/CODEOWNERS']:
                self.assertEqual(run('bl_check_create_only',root,path),'MISSING')
                (root/path).write_bytes(b'arbitrary synthetic project-owned data\0\n')
                self.assertEqual(run('bl_check_create_only',root,path),'PRESENT')

    def test_unavailable_or_partial_result_shape_never_becomes_compliant(self):
        states=dict(zip(m.FILES,['CURRENT','PRESENT','CURRENT','PRESENT','CURRENT']))
        for change in [{'SECURITY.md':'UNAVAILABLE'},{'README.md':'CURRENT'},{'extra':'PRESENT'}]:
            with self.subTest(change=change),self.assertRaises(g.Refusal):m.overall({**states,**change})


class Eligibility(unittest.TestCase):
    def test_clean_main_dirty_detached_and_feature_order(self):
        base={'id':'KleinPerkins/skills','expected_personal_origin_verified':True,'worktree_status_proven':True,'clean_under_personal_policy':True,'branch':'main'}
        cases=[({},'ELIGIBLE','eligible'),({'clean_under_personal_policy':False},'EXCLUDED','dirty-working-tree'),
               ({'branch':None},'EXCLUDED','detached-HEAD'),({'branch':'feature'},'EXCLUDED','not-clean-main-branch'),
               ({'branch':None,'clean_under_personal_policy':False},'EXCLUDED','dirty-working-tree')]
        for changes,state,reason in cases:
            with self.subTest(changes=changes):self.assertEqual(m.eligibility({**base,**changes}),{'classification':state,'reason':reason})

    def test_unknown_status_and_identity_are_unavailable_not_excluded(self):
        base={'id':'KleinPerkins/skills','expected_personal_origin_verified':True,'worktree_status_proven':True,'clean_under_personal_policy':True,'branch':'main'}
        for changes in [{'id':'KleinPerkins/chaos-scheduler'},{'id':'Excluded/work'},
                        {'expected_personal_origin_verified':False},{'worktree_status_proven':False},
                        {'clean_under_personal_policy':None}]:
            with self.subTest(changes=changes),self.assertRaises(g.Refusal):m.eligibility({**base,**changes})

    def test_actual_detached_dirty_and_nonmain_repos_do_not_read_baseline_files(self):
        for kind,reason in [('detached','detached-HEAD'),('dirty','dirty-working-tree'),('feature','not-clean-main-branch')]:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                if kind=='detached':git('checkout','--detach')
                elif kind=='dirty':(root/'fixture.txt').write_text('later user work\n')
                else:git('switch','-c','synthetic-feature')
                with patch.object(m.PersonalBaseline,'file_checks',side_effect=AssertionError('inapplicable file checks')):
                    result=observe(scope,tool)
                self.assertEqual(result['baseline_eligibility']['reason'],reason)
                self.assertTrue(result['baseline_available']);self.assertFalse(result['baseline_files_inspected'])
                self.assertIsNone(result['baseline_compliance'])

    def test_file_checks_cannot_bypass_eligibility_fence(self):
        with fixture() as (_,scope,tool,_),scope.repository('KleinPerkins/skills') as repo:
            ctx=m.PersonalBaseline(repo,tool,m.load_templates())
            with self.assertRaisesRegex(g.Refusal,'need-eligibility'):ctx.file_checks()


class ActualFiles(unittest.TestCase):
    def test_clean_main_complete_preserves_source_and_index(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit_fixture(git)
            before={name:(root/name).read_bytes() for name in [*m.FILES,'.git/index','.git/config']}
            result=observe(scope,tool)
            self.assertEqual(result['baseline_compliance'],'COMPLIANT');self.assertTrue(result['baseline_available'])
            self.assertEqual(result['baseline_file_states'],dict(zip(m.FILES,['CURRENT','PRESENT','CURRENT','PRESENT','CURRENT'])))
            self.assertFalse(result['create_only_bodies_read']);self.assertFalse(result['full_doctor_or_native_qualification'])
            self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_missing_and_partial_do_not_change_files_or_raise_violation(self):
        for kind,expected in [('missing','MISSING'),('partial','PARTIAL')]:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                (root/'README.md').write_text('synthetic create-only README');(root/'.github').mkdir()
                (root/'.github/CODEOWNERS').write_text('synthetic custom owner')
                if kind=='partial':(root/'SECURITY.md').write_text('custom security')
                commit_fixture(git);result=observe(scope,tool)
                self.assertEqual(result['baseline_compliance'],expected)
                self.assertEqual(result['baseline_diagnostic_verdict'],'ADVISORY')
                self.assertFalse((root/'.github/dependabot.yml').exists())

    def test_all_five_file_states_match_exact_owner_oracle(self):
        with oracle() as run,fixture() as (root,scope,tool,git):
            complete(root);(root/'SECURITY.md').write_text('custom security')
            (root/'.github/dependabot.yml').write_bytes(m.HASH_BEGIN+b'\nstale config\n')
            (root/'README.md').unlink();commit_fixture(git);result=observe(scope,tool)
            expected={'SECURITY.md':run('bl_check_managed_file',root,'SECURITY.md','bl_render_security_md','html'),
                      '.github/CODEOWNERS':run('bl_check_create_only',root,'.github/CODEOWNERS'),
                      '.gitignore':run('bl_check_gitignore_block',root),
                      'README.md':run('bl_check_create_only',root,'README.md'),
                      '.github/dependabot.yml':run('bl_check_managed_file',root,'.github/dependabot.yml','bl_render_dependabot','hash')}
            self.assertEqual(result['baseline_file_states'],expected)

    def test_create_only_reader_never_reads_even_large_bodies(self):
        with fixture() as (root,scope,tool,git):
            complete(root);(root/'README.md').write_bytes(b'x'*(s.MAX_FILE_BYTES+1));commit_fixture(git)
            real=m.BaselineReader.read
            def no_create_body(self,relative):
                if relative in ['README.md','.github/CODEOWNERS']:raise AssertionError('create-only body read')
                return real(self,relative)
            with patch.object(m.BaselineReader,'read',no_create_body):result=observe(scope,tool)
            self.assertEqual(result['baseline_compliance'],'COMPLIANT')

    def test_create_only_aliases_special_shared_files_and_nested_parents_hold(self):
        for kind in ['symlink','FIFO','hardlink','parent','nested']:
            with self.subTest(kind=kind),fixture() as (root,scope,tool,git):
                complete(root);p=root/'.github/CODEOWNERS'
                if kind=='parent':
                    for child in (root/'.github').iterdir():child.unlink()
                    (root/'.github').rmdir();(root/'.github').symlink_to('/not-followed')
                elif kind=='nested':(root/'.github/.git').write_text('gitdir: /not-followed')
                else:
                    p.unlink()
                    if kind=='symlink':p.symlink_to('/not-read')
                    elif kind=='FIFO':os.mkfifo(p,0o600)
                    else:os.link(root/'README.md',p)
                # Direct metadata-only reader is independently fenced; no Git
                # command can traverse these synthetic unsafe control paths.
                with scope.repository('KleinPerkins/skills') as repo:
                    reader=m.BaselineReader(w.PersonalWorktree(repo,tool))
                    with self.assertRaises((ValueError,OSError)):reader.presence('.github/CODEOWNERS')

    def test_unsafe_managed_file_returns_unavailable_not_missing_or_compliant(self):
        with fixture() as (root,scope,tool,git):
            complete(root);p=root/'SECURITY.md';p.unlink();p.symlink_to('/not-read');commit_fixture(git)
            result=observe(scope,tool)
            self.assertFalse(result['baseline_available']);self.assertIsNone(result['baseline_compliance'])
            self.assertEqual(result['baseline_file_states']['SECURITY.md'],'UNAVAILABLE')

    def test_no_baseline_file_body_or_private_path_is_emitted(self):
        with fixture() as (root,scope,tool,git):
            complete(root);(root/'SECURITY.md').write_text('PRIVATE_SYNTHETIC_BODY_MARKER');commit_fixture(git)
            result=observe(scope,tool);self.assertNotIn('PRIVATE_SYNTHETIC_BODY_MARKER',json.dumps(result))

    def test_later_baseline_edit_is_preserved_and_refused(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit_fixture(git)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalBaseline(repo,tool,m.load_templates());real=ctx.file_checks
                def edit():
                    result=real();(root/'README.md').write_text('later owner README edit\n');return result
                with patch.object(ctx,'file_checks',side_effect=edit),self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual((root/'README.md').read_text(),'later owner README edit\n')

    def test_later_unrelated_edit_invalidates_clean_eligibility_without_reset(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit_fixture(git)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalBaseline(repo,tool,m.load_templates());real=ctx.file_checks
                def edit():
                    result=real();(root/'fixture.txt').write_text('later unrelated user edit\n');return result
                with patch.object(ctx,'file_checks',side_effect=edit),self.assertRaisesRegex(g.Refusal,'eligibility-changed'):ctx.observe()
            self.assertEqual((root/'fixture.txt').read_text(),'later unrelated user edit\n')

    def test_later_template_edit_is_held_without_target_mutation(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit_fixture(git)
            with scope.repository('KleinPerkins/skills') as repo:
                ctx=m.PersonalBaseline(repo,tool,m.load_templates())
                with patch.object(m,'load_templates',side_effect=g.Refusal('immutable-baseline-template-drift')):
                    with self.assertRaises(g.Refusal):ctx.observe()
            self.assertEqual((root/'SECURITY.md').read_bytes(),m.load_templates()['SECURITY.md'])


class Boundaries(unittest.TestCase):
    def test_wrong_origin_refuses_before_baseline_reads(self):
        with fixture() as (_,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with patch.object(m.BaselineReader,'read',side_effect=AssertionError('baseline body entered')):result=m.inspect(scope,tool)
            self.assertFalse(result['rows'][0]['baseline_available'])

    def test_status_refusal_stays_unavailable_without_file_checks(self):
        with fixture() as (_,scope,tool,_),patch.object(w.PersonalWorktree,'observe',side_effect=g.Refusal('synthetic-status-unavailable')):
            result=m.inspect(scope,tool);self.assertFalse(result['rows'][0]['baseline_available'])
            self.assertEqual(result['rows'][0]['baseline_eligibility']['classification'],'UNAVAILABLE')

    def test_CLI_rejects_apply_enforce_roots_templates_remote_and_extra_verbs(self):
        for args in [['apply'],['enforce'],['inspect','--root','/elsewhere'],['inspect','--templates','/elsewhere'],['inspect','--remote'],['inspect','--write-matrix']]:
            with self.subTest(args=args),patch('sys.stderr',new=io.StringIO()):
                with self.assertRaises(SystemExit) as cm:m.main(args)
                self.assertEqual(cm.exception.code,2)

    def test_actual_CLI_advisory_exit_is_not_full_acceptance(self):
        with fixture() as (_,scope,tool,_),redirect_stdout(io.StringIO()) as capture:
            code=m.main(['inspect','--repository','KleinPerkins/skills'])
        self.assertEqual(code,0);result=json.loads(capture.getvalue())
        self.assertEqual(result['rows'][0]['baseline_compliance'],'MISSING')
        self.assertFalse(result['full_doctor_or_native_qualification'])


if __name__=='__main__':unittest.main()
