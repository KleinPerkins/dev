"""Owner-oracle parity, v2 freeze/provenance and disposable boundary fixtures."""
from contextlib import contextmanager,redirect_stdout
import copy
import builtins
from dataclasses import FrozenInstanceError,is_dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import symtable
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_documentation as m
from test_personal_git import fixture

REPO='KleinPerkins/skills'
KEY='11111111-1111-4111-8111-111111111111'
ID='22222222-2222-4222-8222-222222222222'
OP='33333333-3333-4333-8333-333333333333'
EVENT='44444444-4444-4444-8444-444444444444'
HEX='sha256:'+'0'*64
PLAN='**Status:** DRAFT\n**Plan-type:** standard\n\n## Body\nSynthetic plan.\n'
ADR='Status: proposed\n\n## Decision\nA\n## Why\nB\n## Consequences\nC\n'
AGENTS='<!-- doc-warden:begin -->\nSynthetic governance\n<!-- doc-warden:end -->\n'


def write(root,path,raw):
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(raw if isinstance(raw,bytes) else raw.encode());return target


def complete(root):
    write(root,'docs/plans/README.md','| Plan |\n|---|\n')
    write(root,'docs/adr/README.md','| ADR |\n|---|\n')
    write(root,'AGENTS.md',AGENTS)


def commit(git):git('add','-A');git('commit','--allow-empty','-m','synthetic documentation fixture')


def empty():return m.LegacyReceipts({'schema':'personal-doc-receipt-observations/v1','repositories':[{'repository':REPO,'namespace':'skills','files':[]}]},[REPO])


def receipts(files):
    return m.LegacyReceipts({'schema':'personal-doc-receipt-observations/v1','repositories':[{
        'repository':REPO,'namespace':'skills','files':[{'name':name,'sha256':m.g.sha(raw),
            'raw_base64':m.base64.b64encode(raw).decode()} for name,raw in files.items()]}]},[REPO])


def observe(scope,tool,evidence=None,authority=None):
    return m.inspect(scope,tool,authority or m.Authority(),evidence or empty())['rows'][0]


@contextmanager
def structural(root,scope,tool,evidence=None):
    with scope.repository(REPO) as repo:
        tree=m.w.PersonalWorktree(repo,tool);reader=m.DocReader(tree)
        with tree.git.private_gitdir(worktree_controls=True),tempfile.TemporaryDirectory() as raw:
            private=m.PrivateGit(tree,reader,Path(raw).resolve())
            yield m.Structural(tree,reader,m.Authority(),evidence or empty(),private)
            reader.check();tree.git.finish()


def config():
    return {'schema':'doc-warden/config/v2','schema_version':2,'repository_key':KEY,
            'github_repository_id':None,'enabled':True,'dynamic_defaults':{'rigor':'auto'},
            'legacy_roots':[],'gsd_pin_digest':HEX,'gsd_interface_digest':HEX,
            'maintenance':{'status':'current','last_checked_revision':None}}


def metadata(lifecycle='draft'):
    return {'schema':'doc-warden/artifact/v2','id':'ADR-'+KEY+'-'+ID,'type':'adr','version':1,
            'repository_key':KEY,'github_repository_id':None,'authority':'semantic',
            'mutability':'frozen_after_approval','lifecycle':lifecycle,'supersedes':None,
            'relations':[],'provenance':[],'approval':None}


def artifact(root,meta=None,path='docs/adr/0001-synthetic.md'):
    write(root,'.planning/doc-warden.json',m.v2.canonical_json(config()))
    raw=b'---\n'+m.v2.canonical_json(meta or metadata()).rstrip(b'\n')+b'\n---\nSynthetic ADR body.\n'
    write(root,path,raw);return raw


def freeze(root,path,raw):
    post={path:m.v2.digest_ref(raw)}
    event={'schema':'doc-warden/operation-event/v2','event_id':EVENT,'operation_id':OP,
           'transition':'accepted_freeze','action_digest':HEX,'source_revision':'no-head',
           'prior_event_digest':None,'outcome':'applied','details':{'postimages':post}}
    record={'schema':'doc-warden/receipt/v2','repository_key':KEY,'github_repository_id':None,
            'canonical_root':'$REPOSITORY_ROOT','operation_id':OP,'event_id':EVENT,
            'prior_event_digest':None,'source_revision':'no-head','action_digest':HEX,
            'preimages':{path:None},'postimages':post,
            'result_tree_digest':m.v2.digest_ref(m.v2.canonical_json({'event':event,'postimages':post})),
            'delivery_commit':None,'transition':'accepted_freeze',
            'bindings':{'policy_version':'synthetic','policy_digest':HEX,'schema_digest':HEX,
                        'trigger_catalog_digest':HEX,'template_digests':{},'gsd_pin_digest':HEX,'approved_plan_digest':HEX},
            'actions':[{'kind':'create','path':path,'content_digest':post[path]}],
            'verification':[],'outcome':'applied','confirmation_digest':HEX}
    write(root,m.RECEIPTS+'/'+OP+'.json',m.v2.canonical_json(record))
    write(root,m.EVENTS+'/'+EVENT+'.json',m.v2.canonical_json(event))
    return record,event


class OwnerOracle(unittest.TestCase):
    """Current source excerpts only; no full owner library/writer execution."""
    def oracle(self,root,function,*args):
        script=Path(m.__file__).parent/'doc_authority/legacy-readonly-oracle.sh'
        self.assertEqual(m.g.sha(script.read_bytes()),'1512af0e597e7f52e32890b50c7a08f07e591be71d6109d81be981a273bdbec1')
        command='source "$1"; shift; function_name="$1"; shift; "$function_name" "$@"'
        value=subprocess.run(['/bin/bash','-c',command,'fixture',str(script),function,str(root),*args],
                             capture_output=True,env={**m.g.clean_environment(),'LC_ALL':'C'},timeout=4)
        self.assertEqual(value.returncode,0,value.stderr);return value.stdout.decode()

    def test_plan_header_todo_type_and_workitem_parity(self):
        cases=[PLAN,'**Status:** ACCEPTED\n<!-- TODO: author -->\n',
               '**Date:** today\n**Plan-type:** standard\n',
               '**Status:** DRAFT\n**Plan-type:**\nstandard\n',
               '**Status:** DRAFT\n## Later\n**Plan-type:** standard\n',
               PLAN.replace('standard','standard extra words'),PLAN.replace('standard','invalid'),
               PLAN+'\n<!-- TODO: author -->\n',PLAN+'\n## Later\n**Status:** ACCEPTED\n<!-- TODO: author -->\n',
               PLAN.replace('standard','agentic-execution')+'## 5. Work items\n **Files:** x\n**Interfaces:** y\n- [X] step\n',
               PLAN.replace('standard','agentic-execution')+'## Other\n**Files:** x\n**Interfaces:** y\n- [ ] step\n',
               PLAN.replace('\n','\r\n'),PLAN+'x'*100000]
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for index,text in enumerate(cases):
                for name in ('synthetic-v1.md','INVALID.md'):
                    with self.subTest(index=index,name=name):
                        write(root,'docs/plans/'+name,text)
                        expected=self.oracle(root,'dwl_classify_plan_file','docs/plans',name)
                        self.assertEqual(m.plan_shape(name,text) or 'CONFORMANT',expected)

    def test_agents_marker_line_counts_order_and_local_pointer(self):
        cases=[AGENTS,'',AGENTS+AGENTS,AGENTS.replace('\nSynthetic governance\n',''),
               '<!-- doc-warden:end -->\n<!-- doc-warden:begin -->\n',
               '<!-- doc-warden:begin --><!-- doc-warden:begin -->\nx\n<!-- doc-warden:end -->\n',
               '<!-- doc-warden:begin --><!-- doc-warden:end -->\n',
               AGENTS+AGENTS+'\nPlanning documents docs/plans/README.md\n']
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for local in (False,True):
                write(root,'docs/plans/README.md','## The convention\n| File |\n|---|\n' if local else '| Plan |\n')
                for index,text in enumerate(cases):
                    with self.subTest(local=local,index=index):
                        write(root,'AGENTS.md',text)
                        self.assertEqual(m.agents_class(text,'docs/plans',local),self.oracle(root,'dwl_classify_agents_md_block'))

    def test_local_convention_index_and_policy_drift_parity(self):
        cases=['| Plan |\n','| File |\n','## The convention\n| File |\n|---|\n',
               'planning-document convention\n| File |\n',
               '## The convention\n| Plan |\n|---|\nnow frozen historical superseded file **Status:**\n',
               '## The convention\n| Plan |\n|---|\nlacks an index\n',
               '|\nPlan |\n']
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for text in cases:
                write(root,'docs/plans/README.md',text)
                self.assertEqual(m.readme_class(text,'Plan',m.convention(text)),self.oracle(root,'dwl_classify_plans_readme','docs/plans'))


class ReceiptAndParser(unittest.TestCase):
    def test_missing_namespace_is_not_known_empty(self):
        with self.assertRaises(m.g.Refusal):m.LegacyReceipts(None,[REPO]).digest(REPO,'docs/plans/synthetic-v1.md')
        self.assertIsNone(empty().digest(REPO,'docs/plans/synthetic-v1.md'))

    def test_newest_relevant_digest_sentinels_and_unknown_parse_order(self):
        path='docs/plans/synthetic-v1.md'
        old=b'approved_actions:\n- path: '+path.encode()+b'\n  content_digest: older\n'
        newer=b'approved_actions:\n- path: '+path.encode()+b'\n  content_digest: index_row\n'
        self.assertEqual(receipts({'a.yml':old,'b.yml':newer}).digest(REPO,path),'older')
        good=newer.replace(b'index_row',b'newest')
        self.assertEqual(receipts({'a.yml':b'[broken','b.yml':good}).digest(REPO,path),'newest')
        with self.assertRaises(m.g.Refusal):receipts({'a.yml':old,'z.yml':b'[broken'}).digest(REPO,path)
        for bad in (b'hello',b'approved_actions: [hello]',b'approved_actions: hello'):
            with self.subTest(bad=bad),self.assertRaises(m.g.Refusal):receipts({'z.yml':bad}).digest(REPO,path)

    def test_namespace_hash_duplicate_and_extra_root_inputs_refused(self):
        value={'schema':'personal-doc-receipt-observations/v1','repositories':[{'repository':REPO,'namespace':'wrong','files':[]}]}
        with self.assertRaises(m.g.Refusal):m.LegacyReceipts(value,[REPO])
        value['repositories'][0]['namespace']='skills';value['repositories']*=2
        with self.assertRaises(m.g.Refusal):m.LegacyReceipts(value,[REPO])
        with self.assertRaises(m.g.Refusal):m.strict_json(b'{"x":1,"x":2}')

    def test_safe_yaml_never_constructs_python_and_is_bounded(self):
        for raw in (b'!!python/object/apply:os.system [touch NEVER]',b'['*70+b'0'+b']'*70,b'x'*(m.yaml.MAX_YAML_BYTES+1)):
            with self.subTest(raw=raw[:40]),self.assertRaises(ValueError):m.yaml.safe_receipt_document(raw)
        module=m.yaml.verified_parser();self.assertFalse(module.__with_libyaml__)
        self.assertEqual(module.__name__,m.yaml.ALIAS)
        self.assertEqual(m.yaml.safe_receipt_document(b'approved_actions: []'),{'approved_actions':[]})

    def test_foreign_yaml_alias_is_refused(self):
        fake=type(sys)(m.yaml.ALIAS);fake.__file__='/not-read/yaml.py'
        with patch.dict(sys.modules,{m.yaml.ALIAS:fake}),self.assertRaises(ValueError):m.yaml.verified_parser()


class StructuralFixtures(unittest.TestCase):
    def test_complete_empty_and_missing_floors(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit(git);result=observe(scope,tool)
            self.assertEqual((result['classification'],result['canonical_check_exit']),('CONFORMANT',0))
            self.assertFalse(result['legacy_state_imported'])

    def test_tracked_only_plan_inventory_and_untracked_supersession(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/plans/old-v1.md',PLAN);write(root,'.gitignore','docs/plans/ignored*.md\n');commit(git)
            write(root,'docs/plans/ignored-v2.md',PLAN+'\n**Supersedes:** `old-v1.md`\n')
            write(root,'docs/plans/README.md','| Plan |\n| old-v1.md |\n');commit(git)
            with structural(root,scope,tool) as check:
                result=check.observe();items={row['path']:row['classification'] for row in result['items']}
                self.assertEqual(items['superseded_plan:docs/plans/old-v1.md'],'DRIFTED')
                self.assertNotIn('docs/plans/ignored-v2.md',items)

    def test_plan_inventory_uses_git_quoting_pathspec_and_exact_raw_override(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/plans/normal-v1.md',PLAN);write(root,'docs/plans/é-v1.md',PLAN);commit(git)
            with structural(root,scope,tool) as check:
                self.assertEqual(check.private.plans('docs/plans'),['normal-v1.md'])
                self.assertEqual(check.private.plans('./docs/plans'),[])
            git('config','core.quotePath','false')
            with structural(root,scope,tool) as check:self.assertEqual(check.private.plans('docs/plans'),['normal-v1.md','é-v1.md'])

    def test_default_missing_receipts_held_and_mismatch_drifts(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/plans/synthetic-v1.md',PLAN);commit(git)
            result=observe(scope,tool,m.LegacyReceipts(None,[REPO]))
            self.assertEqual(result['classification'],'UNAVAILABLE')
            value=receipts({'a.yml':b'approved_actions:\n- path: docs/plans/synthetic-v1.md\n  content_digest: stale\n'})
            self.assertEqual(observe(scope,tool,value)['classification'],'DRIFTED')

    def test_local_convention_skips_body_normalization_but_not_unknown_conditions(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/plans/README.md','## The convention\n| File |\n|---|\n')
            write(root,'docs/plans/INVALID.md','not normalized\n');write(root,'docs/adr/0001-bad.md','not normalized\n')
            write(root,'docs/decisions/one.md','uncovered location\n');commit(git)
            result=observe(scope,tool);self.assertEqual(result['classification'],'NEEDS_OPERATOR')
            self.assertFalse(any(row['path'].endswith('INVALID.md') or row['path'].endswith('0001-bad.md') for row in result['items']))

    def test_unknown_triggers_and_severity_keep_operator_and_contradiction(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/adr/0001-synthetic.md',ADR);write(root,'docs/runbooks/a.md','runbook')
            write(root,'docs/incidents/a.md','incident');write(root,'docs/GLOSSARY.md','terms');write(root,'AGENTS.md',AGENTS+AGENTS)
            commit(git);authority=m.Authority();authority.trigger_ids=set()
            with structural(root,scope,tool) as check:
                check.authority=authority
                result=check.observe();self.assertEqual(result['classification'],'CONTRADICTORY')
                self.assertEqual(sum(row['classification']=='NEEDS_OPERATOR' for row in result['items']),4)

    def test_dirty_detached_and_other_branch_never_read_documentation_bodies(self):
        for mode in ('dirty','detached','other'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);commit(git)
                if mode=='dirty':write(root,'fixture.txt','dirty\n')
                elif mode=='detached':git('switch','--detach')
                else:git('switch','-c','synthetic-other')
                with patch.object(m.DocReader,'read',side_effect=AssertionError('doc body read')):result=observe(scope,tool)
                self.assertEqual(result['classification'],'NOT_APPLICABLE');self.assertFalse(result['documentation_bodies_read'])

    def test_known_contradiction_survives_unavailable_receipts(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'AGENTS.md',AGENTS+AGENTS);write(root,'docs/plans/synthetic-v1.md',PLAN);commit(git)
            result=observe(scope,tool,m.LegacyReceipts(None,[REPO]))
            self.assertEqual((result['classification'],result['worst_known_classification']),('UNAVAILABLE','CONTRADICTORY'))

    def test_known_contradiction_survives_later_unavailable_directory(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'AGENTS.md',AGENTS+AGENTS);(root/'docs/runbooks').symlink_to('/not-read',target_is_directory=True);commit(git)
            result=observe(scope,tool)
            self.assertEqual((result['classification'],result['worst_known_classification']),('UNAVAILABLE','CONTRADICTORY'))

    def test_classic_adr_todo_accepted_and_sections(self):
        for raw,expected in ((ADR,'CONFORMANT'),(ADR+'\n<!-- TODO: author -->','NEEDS_AUTHORING'),
                             (ADR.replace('proposed','ACCEPTED')+'\n<!-- TODO: author -->','CONFORMANT'),
                             (ADR.replace('## Why','### Why'),'DRIFTED')):
            with self.subTest(expected=expected),fixture() as (root,scope,tool,git):
                complete(root);write(root,'docs/adr/0001-synthetic.md',raw);commit(git)
                self.assertEqual(observe(scope,tool)['classification'],expected)

    def test_full_inspection_preserves_source_metadata_objects_and_bytes(self):
        with fixture() as (root,scope,tool,git):
            complete(root);artifact(root);write(root,'docs/plans/synthetic-v1.md',PLAN);commit(git)
            def facts():
                return {str(p.relative_to(root)):{**m.w.fact(p.lstat()),'sha256':m.g.sha(p.read_bytes())}
                        for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
            before=facts();result=observe(scope,tool);self.assertEqual(result['classification'],'CONFORMANT')
            self.assertEqual(facts(),before)

    def test_closed_cli_and_available_unknown_operator_exits(self):
        with fixture() as (root,scope,tool,git):
            complete(root);commit(git)
            for mode,expected in (('clean',0),('receipts-unavailable',2),('operator',3)):
                if mode=='receipts-unavailable':write(root,'docs/plans/synthetic-v1.md',PLAN);commit(git)
                if mode=='operator':(root/'docs/plans/synthetic-v1.md').unlink();write(root,'docs/decisions/a.md','synthetic');commit(git)
                out=io.StringIO()
                with redirect_stdout(out),patch.object(m.g,'GitTool',return_value=tool):code=m.main(['inspect','--repository',REPO])
                self.assertEqual(code,expected,json.loads(out.getvalue()))
            out=io.StringIO()
            with redirect_stdout(out),patch.object(m.sys,'stdin',io.TextIOWrapper(io.BytesIO(b'{}'))),patch.object(m.s,'PersonalScope',side_effect=AssertionError('target opened')):
                self.assertEqual(m.main(['inspect','--repository',REPO,'--receipts-stdin']),2)


class V2Fixtures(unittest.TestCase):
    def test_dataclass_decorators_and_isolated_owner_bindings(self):
        self.assertTrue(is_dataclass(m.v2.ParsedArtifact));self.assertTrue(is_dataclass(m.v2.ProvenanceVerdict))
        value=m.v2.ProvenanceVerdict('verified','synthetic');self.assertEqual(value.status,'verified')
        with self.assertRaises(FrozenInstanceError):value.status='changed'
        a=m.v2.observation_contract(Path('/synthetic/a'),lambda *a:None)
        b=m.v2.observation_contract(Path('/synthetic/b'),lambda *a:None)
        self.assertIsNot(a['validate_adr_record'].__globals__,b['validate_adr_record'].__globals__)
        self.assertEqual(a['load_schema'].__globals__['SCHEMA_ROOT'],Path('/synthetic/a'))
        self.assertIsNone(m.v2.SCHEMA_ROOT)

    def test_curated_owner_closure_has_no_unbound_globals_or_mutation_calls(self):
        path=Path(m.v2.__file__);missing=set()
        def walk(table):
            for item in table.get_symbols():
                if item.is_global() and item.is_referenced() and item.get_name() not in vars(m.v2) and not hasattr(builtins,item.get_name()):missing.add(item.get_name())
            for child in table.get_children():walk(child)
        walk(symtable.symtable(path.read_text(),str(path),'exec'));self.assertEqual(missing,set())
        import ast
        tree=ast.parse(path.read_text())
        forbidden={'write_text','write_bytes','unlink','rename','mkdir','touch','chmod','symlink_to','link_to','Popen','run','check_call','check_output','system'}
        self.assertEqual([n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden],[])

    def test_draft_v2_and_approved_without_freeze(self):
        for lifecycle,expected in (('draft','CONFORMANT'),('approved','DRIFTED')):
            with self.subTest(lifecycle=lifecycle),fixture() as (root,scope,tool,git):
                complete(root);artifact(root,metadata(lifecycle));commit(git)
                self.assertEqual(observe(scope,tool)['classification'],expected)

    def test_approved_freeze_and_byte_event_receipt_tamper(self):
        for mode in ('valid','bytes','event','confirmation','noncanonical','later-invalid'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);raw=artifact(root,metadata('approved'));record,event=freeze(root,'docs/adr/0001-synthetic.md',raw)
                if mode=='bytes':write(root,'docs/adr/0001-synthetic.md',raw+b'changed\n')
                elif mode=='event':event['outcome']='partial';write(root,m.EVENTS+'/'+EVENT+'.json',m.v2.canonical_json(event))
                elif mode=='confirmation':record['confirmation_digest']=None;write(root,m.RECEIPTS+'/'+OP+'.json',m.v2.canonical_json(record))
                elif mode=='noncanonical':write(root,m.RECEIPTS+'/'+OP+'.json',json.dumps(record))
                elif mode=='later-invalid':write(root,m.RECEIPTS+'/zzzz.json','not-json')
                commit(git);result=observe(scope,tool)
                self.assertEqual(result['classification'],'CONFORMANT' if mode in ('valid','later-invalid') else 'DRIFTED',result)

    def test_legacy_adr_is_still_subject_to_v2_frozen_bytes(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'docs/adr/0001-synthetic.md',ADR);write(root,'.planning/doc-warden.json',m.v2.canonical_json(config()))
            freeze(root,'docs/adr/0001-synthetic.md',ADR.encode());write(root,'docs/adr/0001-synthetic.md',ADR+'changed\n');commit(git)
            self.assertEqual(observe(scope,tool)['classification'],'DRIFTED')

    def test_other_artifact_errors_and_duplicate_numbers_affect_v2_adr(self):
        for mode in ('malformed','duplicate-number','wrong-key','uncanonical','override'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);artifact(root)
                if mode=='malformed':write(root,'.planning/artifacts/bad.md','not frontmatter')
                if mode=='duplicate-number':write(root,'docs/adr/0001-other.md',ADR)
                if mode=='wrong-key':meta=metadata();meta['repository_key']=ID;artifact(root,meta)
                if mode=='uncanonical':write(root,'docs/adr/0001-synthetic.md','---\n'+json.dumps(metadata())+'\n---\nbody')
                if mode=='override':write(root,'.doc-warden.yml','adr_dir: docs/adr\nadr_dir: docs/adr\n')
                commit(git);self.assertEqual(observe(scope,tool)['classification'],'DRIFTED')

    def test_local_provenance_uses_private_immutable_blob_not_working_body(self):
        with fixture() as (root,scope,tool,git):
            complete(root);write(root,'assets/source.txt','immutable synthetic asset\n');commit(git);head=git('rev-parse','HEAD').decode()
            meta=metadata();meta['provenance']=[{'schema':'doc-warden/external-asset/v2','provider':'local',
                'canonical_url':'local:assets/source.txt','immutable_revision':head,'source_repository_key':KEY,
                'source_github_repository_id':None,'source_commit':head,'source_path':'assets/source.txt',
                'export_sha256':m.g.sha(b'immutable synthetic asset\n'),'captured_at':'2026-11-01T00:00:00Z',
                'owner':'synthetic owner','license':'synthetic license','egress_projection':'external_asset_pointer/v1'}]
            artifact(root,meta);commit(git)
            original=m.s.read_regular
            def guarded(parent,name,*args,**kw):
                if name=='source.txt':raise AssertionError('working asset body read')
                return original(parent,name,*args,**kw)
            with patch.object(m.s,'read_regular',guarded):result=observe(scope,tool)
            self.assertEqual(result['classification'],'CONFORMANT',result)

    def test_local_provenance_unsafe_current_path_cannot_be_hidden_by_snapshot(self):
        for mode in ('parent-file','parent-alias','leaf-directory','protected','memory'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);write(root,'assets/source.txt','synthetic immutable asset');commit(git);head=git('rev-parse','HEAD').decode()
                source='chaos-scheduler/asset' if mode=='protected' else 'agent-learnings.md' if mode=='memory' else 'assets/source.txt'
                meta=metadata();meta['provenance']=[{'schema':'doc-warden/external-asset/v2','provider':'local',
                    'canonical_url':'local:'+source,'immutable_revision':head,'source_repository_key':KEY,
                    'source_github_repository_id':None,'source_commit':head,'source_path':source,
                    'export_sha256':m.g.sha(b'synthetic immutable asset'),'captured_at':'2026-11-01T00:00:00Z',
                    'owner':'synthetic','license':'synthetic','egress_projection':'external_asset_pointer/v1'}]
                artifact(root,meta)
                if mode.startswith('parent-'):
                    (root/'assets/source.txt').unlink();(root/'assets').rmdir()
                    if mode=='parent-file':write(root,'assets','not a directory')
                    else:(root/'assets').symlink_to('/not-read',target_is_directory=True)
                elif mode=='leaf-directory':(root/'assets/source.txt').unlink();(root/'assets/source.txt').mkdir()
                commit(git)
                with structural(root,scope,tool) as check:result=check.observe()
                self.assertEqual(result['classification'],'UNAVAILABLE',result)


class Boundaries(unittest.TestCase):
    def test_ignored_late_file_directory_state_and_control_edits_are_detected(self):
        for mode in ('body','membership','absent','config','receipt'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);write(root,'.gitignore','docs/\n.doc-warden.yml\n_ops/\n');commit(git)
                with scope.repository(REPO) as repo:
                    reader=m.DocReader(m.w.PersonalWorktree(repo,tool))
                    if mode=='body':reader.read('docs/plans/README.md');write(root,'docs/plans/README.md','changed')
                    if mode=='membership':reader.directory('docs/plans');write(root,'docs/plans/added.md','changed')
                    if mode=='absent':reader.read('docs/adr/absent.md');write(root,'docs/adr/absent.md','changed')
                    if mode=='config':reader.read('.doc-warden.yml');write(root,'.doc-warden.yml','plans_dir: other')
                    if mode=='receipt':reader.directory(m.RECEIPTS);write(root,m.RECEIPTS+'/added.json','{}')
                    with self.assertRaises(m.g.Refusal):reader.check()

    def test_alias_shared_fifo_memory_protected_and_nested_before_body(self):
        for mode in ('alias','shared','fifo','memory','protected','nested','binary','encoding'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                complete(root);path='docs/plans/README.md';target=root/path
                if mode=='alias':target.unlink();target.symlink_to('/not-read')
                if mode=='shared':os.link(target,root/'preserved')
                if mode=='fifo':target.unlink();os.mkfifo(target,0o600)
                if mode=='memory':path='agent-learnings.md';write(root,path,'PRIVATE_SYNTHETIC_MEMORY')
                if mode=='protected':path='chaos-scheduler/control.md'
                if mode=='nested':write(root,'docs/.git','nested pointer')
                if mode=='binary':target.write_bytes(b'abc\0def')
                if mode=='encoding':target.write_bytes(b'\xff')
                with scope.repository(REPO) as repo:
                    reader=m.DocReader(m.w.PersonalWorktree(repo,tool))
                    with self.assertRaises((m.g.Refusal,OSError)):reader.read(path)

    def test_bounds_refuse_without_relaxation(self):
        with fixture() as (root,scope,tool,git):
            complete(root)
            with scope.repository(REPO) as repo:
                reader=m.DocReader(m.w.PersonalWorktree(repo,tool));reader.deadline=time.monotonic()-1
                with self.assertRaises(m.g.Refusal):reader.read('AGENTS.md')
                reader=m.DocReader(m.w.PersonalWorktree(repo,tool))
                with patch.object(m,'MAX_BYTES',1),self.assertRaises(m.g.Refusal):reader.read('AGENTS.md')

    def test_override_keeps_raw_shape_and_rejects_unclassified(self):
        self.assertEqual(m.override('plans_dir: "./docs//plans"\n','plans_dir','docs/plans'),'./docs//plans')
        self.assertEqual(m.override('plans_dir: x..y\n','plans_dir','docs/plans'),'docs/plans')
        # The owner preserves CR instead of trimming it. This bounded reader
        # explicitly holds control-character paths, rather than silently
        # reading the default directory and claiming equivalent conformance.
        with self.assertRaises(m.g.Refusal):m.override('plans_dir: docs/plans \r\n','plans_dir','docs/plans')
        with self.assertRaises(m.g.Refusal):m.override('plans_dir: chaos-scheduler\n','plans_dir','docs/plans')


if __name__=='__main__':unittest.main()
