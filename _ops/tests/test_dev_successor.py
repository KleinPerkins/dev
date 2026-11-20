#!/usr/bin/env python3
"""Fresh-history identity, immutable provenance, and real artifact transactions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('dev_successor',ROOT/'_ops/checks/dev-successor.py')
successor=importlib.util.module_from_spec(spec);spec.loader.exec_module(successor)
sys.path.insert(0,str(ROOT/'_ops/doc-warden/v2'))
from doc_warden.adrs import preview_adr_draft, preview_adr_update
from doc_warden.artifacts import apply_preview, consent_for
from doc_warden.bootstrap import adopt_accepted_authorities, ACCEPTED_COMMIT
from doc_warden.canonical import parse_artifact
from doc_warden.validators import read_repository_config

class SuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='dev-successor-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'repo';self.root.mkdir()
        self.record=json.loads((ROOT/successor.RECORD).read_bytes())
        paths={r['path'] for k in ('retained_policy','historical_provenance') for r in self.record[k]}
        paths|={successor.RECORD,'_ops/checks/dev-successor.py','_ops/bin/doc-warden.sh','_ops/doc-warden/triggers.v2.json','_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json','_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json'}
        for name in paths:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
        adr_index = self.root / "docs/adr/README.md"
        adr_index.parent.mkdir(parents=True)
        adr_index.write_text(
            "# Architecture decision records\n\n"
            "| ADR | Status | One-line decision |\n"
            "|---|---|---|\n",
            encoding="utf-8",
        )
        shutil.copytree(ROOT/'_ops/doc-warden/schemas',self.root/'_ops/doc-warden/schemas')
        self.git('init','-q','-b','main');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid');self.git('add','.');self.git('commit','-qm','fresh synthetic successor')
        p=patch.dict(os.environ,{'XDG_STATE_HOME':str(Path(self.tmp.name)/'state')});p.start();self.addCleanup(p.stop)
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],text=True,stderr=subprocess.PIPE).strip()
    def validate(self,**kwargs):return successor.validate(self.root,repository_id=kwargs.pop('repository_id',successor.REPOSITORY_ID),repository=kwargs.pop('repository','KleinPerkins/dev-temp'),**kwargs)
    def test_valid_both_closed_names_source_only(self):
        for name in successor.NAME_PHASES.values():
            result=self.validate(repository=name);self.assertFalse(result['runtime_authority']);self.assertEqual(result['delivery'],'pending-successor-qualification')
    def test_wrong_old_bool_ids_and_unknown_names_refused(self):
        for value in (1278387789,1,True,'1459458379'):
            with self.subTest(value=value), self.assertRaises(ValueError):self.validate(repository_id=value)
        for value in ('Other/dev','KleinPerkins/Dev','KleinPerkins/other'):
            with self.subTest(value=value), self.assertRaises(ValueError):self.validate(repository=value)
    def test_closed_schema_and_no_self_approval(self):
        for key in self.record:
            candidate=copy.deepcopy(self.record);candidate.pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(record=candidate)
        for key,value in [('approved',True),('runtime_authority',True),('accepted_plan_sha256','0'*64)]:
            candidate=copy.deepcopy(self.record);candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(record=candidate)
    def test_policy_and_historical_digest_drift_refused(self):
        for field in ('retained_policy','historical_provenance'):
            p=self.root/self.record[field][0]['path'];before=p.read_bytes();p.write_bytes(before+b'drift')
            with self.assertRaisesRegex(ValueError,'binding_digest_drift'):self.validate()
            p.write_bytes(before)
    def test_binding_escape_duplicate_symlink_mode_refused(self):
        for mutation in ('escape','duplicate','symlink','mode'):
            with self.subTest(mutation=mutation):
                candidate=copy.deepcopy(self.record);row=candidate['retained_policy'][0];p=self.root/row['path']
                if mutation=='escape':row['path']='../escape'
                if mutation=='duplicate':candidate['retained_policy'].append(copy.deepcopy(row))
                if mutation=='mode':row['git_mode']='100755'
                if mutation=='symlink':
                    raw=p.read_bytes();p.unlink();p.symlink_to(self.root/'OPERATING-MANUAL.md')
                with self.assertRaises(ValueError):self.validate(record=candidate)
                if mutation=='symlink':p.unlink();p.write_bytes(raw)
    def test_no_old_commit_and_unmodified_bootstrap_refuses(self):
        self.assertEqual(self.git('rev-list','--count','HEAD'),'1')
        self.git('remote','add','origin','git@github.com:KleinPerkins/dev.git')
        with self.assertRaisesRegex(ValueError,'section0_commit_not_in_history'):adopt_accepted_authorities(self.root,ACCEPTED_COMMIT)
        result=subprocess.run(['git','-C',str(self.root),'cat-file','-e',ACCEPTED_COMMIT],capture_output=True)
        self.assertNotEqual(result.returncode,0)
    def test_actual_draft_update_apply_uses_new_identity(self):
        draft=preview_adr_draft({'title':'Fresh baseline choice','body':'# Choice\n\nOriginal synthetic decision.\n'},repo=self.root)
        self.assertFalse((self.root/draft.artifact_path).exists())
        receipt=apply_preview(draft,consent_for(draft.transaction))
        self.assertEqual(receipt['github_repository_id'],successor.REPOSITORY_ID)
        self.assertEqual(receipt['repository_key'],successor.REPOSITORY_KEY)
        before=(self.root/draft.artifact_path).read_bytes()
        update=preview_adr_update(draft.artifact_id,{'title':'Fresh baseline choice','body':'# Choice\n\nRevised synthetic decision.\n'},repo=self.root)
        self.assertEqual((self.root/draft.artifact_path).read_bytes(),before)
        apply_preview(update,consent_for(update.transaction))
        artifact=parse_artifact(self.root/draft.artifact_path)
        self.assertEqual(artifact.metadata['repository_key'],successor.REPOSITORY_KEY)
        self.assertIn(b'Revised synthetic decision.',(self.root/draft.artifact_path).read_bytes())
        self.validate()
    def test_old_artifact_cannot_claim_current_identity_in_body(self):
        source=self.root/'_ops/adr/0014-shadowsync-native-github-delivery-exception.md'
        target=self.root/'docs/adr/0001-old-record.md'
        target.write_bytes(source.read_bytes()+successor.REPOSITORY_KEY.encode())
        with self.assertRaisesRegex(ValueError,'predecessor_artifact_replay'):self.validate()

    def test_old_receipt_replay_rejected_by_real_transaction(self):
        draft=preview_adr_draft({'title':'No old receipt'},repo=self.root)
        receipt=apply_preview(draft,consent_for(draft.transaction))
        path=self.root/f'_ops/doc-warden/state/v2/receipts/{draft.transaction.operation_id}.json'
        receipt['repository_key']='54aec621-9236-53d2-87b7-9a60ef4ec92e';receipt['github_repository_id']=1278387789
        path.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):apply_preview(draft,consent_for(draft.transaction))
    def test_predecessor_plan_is_never_current_approval(self):
        from doc_warden.artifacts import _bindings
        from doc_warden.gsd_adapter import _central_authority_bindings
        self.assertTrue((self.root/'_ops/plans/doc-warden-execution-plan-v2.md').is_file())
        self.assertEqual(_bindings(self.root)['approved_plan_digest'],'sha256:'+'0'*64)
        with self.assertRaisesRegex(ValueError,'authoring_authority_unavailable'):
            _central_authority_bindings(self.root)

    def test_portability_cannot_import_predecessor_history(self):
        manifest=json.loads((ROOT/'_ops/portability/manifest.json').read_bytes())
        row=next(r for r in manifest['repositories'] if r['id']=='KleinPerkins/dev')
        self.assertIsNone(row['revision']);self.assertEqual(row['disposition'],'blocked-review')

    def test_current_config_does_not_index_predecessor_roots(self):
        config=read_repository_config(self.root);self.assertEqual(config['legacy_roots'],[])
        self.assertEqual(config['github_repository_id'],successor.REPOSITORY_ID)
        from doc_warden.artifact_discovery import artifact_paths, adr_directory
        self.assertEqual(adr_directory(self.root),'docs/adr')
        self.assertEqual(list(artifact_paths(self.root)),[])
        self.assertTrue(list((self.root/'_ops/adr').glob('*.md')))
    def test_successor_activation_is_not_runnerless_qualification(self):
        from doc_warden.activation import validate_activation
        with patch('doc_warden.activation.runnerless_delivery_preview',side_effect=AssertionError('retired delivery must not run')):
            value=validate_activation(self.root,observe_runnerless=False)
        self.assertEqual(value['status'],'active');self.assertEqual(value['runnerless_v2'],'retired');self.assertFalse(value['successor_source']['runtime_authority'])

if __name__=='__main__':unittest.main()
