"""Refusal and preservation regressions for the opt-in read-only recovery path."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import os
import unittest
from unittest.mock import patch

import device_attestation as m


class Fixture(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name).resolve();(self.root/'repo').mkdir()
  self.device=self.root.stat().st_dev;self.old=self.device+100
  self.journal={'root_binding':{'preimage':{'state':'absent','device':None,'inode':None},'current':{'state':'directory','device':self.old,'inode':self.root.stat().st_ino}},'owned_directories':[{'path':str(self.root),'device':self.old,'inode':self.root.stat().st_ino}], 'actions':{'one':{'path':'repo','status':'installed','created':True,'staging':None,'postimage':{'device':self.old,'inode':(self.root/'repo').stat().st_ino,'head':'a'*40,'other':'untouched'}}}}

 def test_translation_preserves_input_and_nonidentity_fields(self):
  original=copy.deepcopy(self.journal);result=m.normalized_journal(self.journal,self.root,self.device)
  self.assertEqual(self.journal,original)
  self.assertEqual(result['root_binding']['preimage'],original['root_binding']['preimage'])
  self.assertEqual(result['actions']['one']['postimage']['other'],'untouched')
  self.assertEqual(result['actions']['one']['postimage']['device'],self.device)
  self.assertEqual(result['actions']['one']['postimage']['inode'],original['actions']['one']['postimage']['inode'])

 def test_replaced_root_refuses(self):
  self.journal['root_binding']['current']['inode']+=1
  with self.assertRaisesRegex(ValueError,'root inode'):m.normalized_journal(self.journal,self.root,self.device)

 def test_replaced_repository_refuses(self):
  self.journal['actions']['one']['postimage']['inode']+=1
  with self.assertRaisesRegex(ValueError,'inode'):m.normalized_journal(self.journal,self.root,self.device)

 def test_mixed_old_devices_refuse(self):
  self.journal['actions']['one']['postimage']['device']+=1
  with self.assertRaisesRegex(ValueError,'filesystem'):m.normalized_journal(self.journal,self.root,self.device)

 def test_other_current_device_refuses(self):
  with self.assertRaisesRegex(ValueError,'device'):m.normalized_journal(self.journal,self.root,self.device+1)

 def test_partial_or_unowned_install_refuses(self):
  for field,value in [('status','ready_to_install'),('created',False),('staging',{'nonce':'x'})]:
   j=copy.deepcopy(self.journal);j['actions']['one'][field]=value
   with self.subTest(field=field),self.assertRaisesRegex(ValueError,'completely installed'):m.normalized_journal(j,self.root,self.device)

 def test_symlinked_repository_refuses(self):
  (self.root/'repo').rmdir();(self.root/'repo').symlink_to(self.root)
  with self.assertRaisesRegex(ValueError,'symlink'):m.normalized_journal(self.journal,self.root,self.device)

 def test_unshared_private_files_required(self):
  p=self.root/'record';p.write_text('private');p.chmod(0o600)
  self.assertEqual(m.regular(p,0o600),b'private')
  (self.root/'alias').hardlink_to(p)
  with self.assertRaisesRegex(ValueError,'unshared'):m.regular(p,0o600)

 def test_native_directory_modes_and_aliases_are_preserved(self):
  d=m.directory(self.root)
  record={'operation_dir':str(self.root),'operation_root':{'kind':'directory','device':self.old,'inode':d['inode'],'mode':d['mode']},'preserved':[{'path':str(self.root/'absent'),'state':{'kind':'absent'}}]}
  old=copy.deepcopy(record);result=m.normalized_skill(record,self.root,self.device)
  self.assertEqual(record,old);self.assertEqual(result['preserved'],old['preserved'])
  record['operation_root']['mode']^=0o100
  with self.assertRaisesRegex(ValueError,'mode'):m.normalized_skill(record,self.root,self.device)


class ApprovalBoundary(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name).resolve()/'attestation.json'
  self.facts={'volume':{'volume_uuid':'A'},'bound_record_sha256':{},'source_repositories_verified':12,'retained_skills_verified':2}
  self.digest=m.sha(m.canonical(self.facts))
  self.path.write_text(json.dumps({'facts':self.facts,'action_sha256':self.digest,'observed_current_device':1}));self.path.chmod(0o600)
  self.args=['verify','--kit','/kit','--root','/root','--state-dir','/state','--skills-runtime','/runtime','--skills-operation','/operation','--attestation',str(self.path)]

 def test_digest_is_not_inferred_from_preview(self):
  with patch.object(m,'inspect',return_value=(self.facts,None,None,None,None,2)),patch.object(m,'read_only_engine') as engine:
   with self.assertRaisesRegex(ValueError,'approval'):m.main(self.args)
   engine.assert_not_called()

 def test_changed_volume_or_bound_record_refuses_before_report_write(self):
  for changed in [dict(self.facts,volume={'volume_uuid':'B'}),dict(self.facts,bound_record_sha256={'/journal':'changed'})]:
   with self.subTest(changed=changed),patch.object(m,'inspect',return_value=(changed,None,None,None,None,2)),patch.object(m,'read_only_engine') as engine:
    with self.assertRaisesRegex(ValueError,'unchanged'):m.main(self.args+['--approve',self.digest])
    engine.assert_not_called()

 def test_approved_stable_identity_allows_new_volatile_device_number(self):
  legacy=SimpleNamespace(_exit_code=lambda r:4)
  engine=SimpleNamespace(verify=lambda:{'result':'incomplete','errors':[],'repositories':[{'source_ready':True}]*12,'required_blockers':[{}]*100})
  with patch.object(m,'inspect',return_value=(self.facts,legacy,None,None,None,999)),patch.object(m,'read_only_engine',return_value=engine),patch.object(m,'volume',return_value=self.facts['volume']),redirect_stdout(io.StringIO()):
   self.assertEqual(m.main(self.args+['--approve',self.digest]),4)

 def test_preview_never_overwrites_an_existing_attestation(self):
  with patch.object(m,'inspect',return_value=(self.facts,None,None,None,None,2)):
   with self.assertRaises(FileExistsError):m.main(['preview']+self.args[1:])


class MutationDenial(unittest.TestCase):
 def test_adapter_cannot_resume_apply_rollback_or_write_journal(self):
  class Base:
   def __init__(self,*args):pass
  args=SimpleNamespace(kit='/kit',root='/root',state_dir='/state',approve='approved')
  engine=m.read_only_engine(SimpleNamespace(Engine=Base),args,{'volume':{}})
  for operation in ['apply','resume','rollback','_save_journal']:
   with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'forbidden|not authorized'):getattr(engine,operation)()


class LegacyIntegration(unittest.TestCase):
 """Exercise real Git and the unchanged canonical engine against disposable state."""
 def setUp(self):
  import engine
  self.legacy=engine
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name).resolve();self.root=self.base/'destination';self.root.mkdir();self.repo=self.root/'skills';self.repo.mkdir();self.state=self.base/'state';self.state.mkdir(mode=0o700)
  self.env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_OPTIONAL_LOCKS':'0'}
  def git(*args):return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,env=self.env,stderr=subprocess.DEVNULL).strip()
  self.git=git;git('init','-b','main');git('config','user.name','KleinPerkins');git('config','user.email','49759187+KleinPerkins@users.noreply.github.com')
  (self.repo/'source.txt').write_text('reviewed fixture\n');git('add','source.txt');git('commit','-m','fixture');head=git('rev-parse','HEAD');git('remote','add','origin','git@github.com:KleinPerkins/skills.git');git('update-ref','refs/remotes/origin/main',head)
  self.manifest=self.base/'manifest.json';self.manifest.write_text(json.dumps({'schema':'personal-portability/manifest/v1','profile':'personal-codex','platform':{'os':'Darwin','architecture':'arm64'},'repositories':[{'id':'KleinPerkins/skills','path':'skills','revision':head,'disposition':'source-only','reason':'isolated test fixture','required':True}],'capabilities':[],'local_state':[]}))
  original=engine.Engine(self.manifest,self.root,self.state)
  journal=original._new_journal();action=journal['actions']['KleinPerkins/skills'];row=original.manifest['repositories'][0]
  action.update(status='installed',created=True,postimage=original._postimage(self.repo,row,head))
  journal['owned_directories']=[{'path':str(self.root),'device':self.root.stat().st_dev,'inode':self.root.stat().st_ino}]
  for obj in [journal['root_binding']['current'],journal['owned_directories'][0],action['postimage']]:obj['device']+=100
  self.journal_path=self.state/'journal.json';self.journal_path.write_bytes(engine._json_bytes(journal));self.journal_path.chmod(0o600);self.before=self.journal_path.read_bytes()
  self.args=SimpleNamespace(kit=str(self.base/'kit'),root=str(self.root),state_dir=str(self.state),approve='fixture-acceptance');(self.base/'kit').mkdir();(self.base/'kit/manifest.json').write_bytes(self.manifest.read_bytes())
  self.facts={'volume':{'volume_uuid':'fixture-volume'}}

 def test_real_legacy_verify_recovers_only_read_only_observations(self):
  with patch.object(m,'volume',return_value=self.facts['volume']):
   adapted=m.read_only_engine(self.legacy,self.args,self.facts);adapted.platform_probe=lambda:('Darwin','arm64');report=adapted.verify()
  self.assertEqual(report['errors'],[]);self.assertTrue(report['repositories'][0]['source_ready']);self.assertFalse(report['operational_complete'])
  self.assertEqual(self.journal_path.read_bytes(),self.before)
  self.assertTrue((self.state/'report.json').is_file());self.assertTrue((self.state/'.report-owner.json').is_file())
  self.assertFalse(report['device_attestation']['mutation_authority'])

 def test_real_git_metadata_drift_is_not_excused_by_device_attestation(self):
  self.git('config','user.name','later edit')
  with patch.object(m,'volume',return_value=self.facts['volume']):
   adapted=m.read_only_engine(self.legacy,self.args,self.facts);adapted.platform_probe=lambda:('Darwin','arm64');report=adapted.verify()
  self.assertFalse(report['repositories'][0]['source_ready']);self.assertTrue(report['errors'])
  self.assertEqual(self.journal_path.read_bytes(),self.before)

 def test_real_legacy_engine_still_refuses_without_adapter(self):
  original=self.legacy.Engine(self.manifest,self.root,self.state);original.platform_probe=lambda:('Darwin','arm64');report=original.verify()
  self.assertTrue(any('root directory binding changed' in e for e in report['errors']))
  self.assertEqual(self.journal_path.read_bytes(),self.before)


if __name__=='__main__':unittest.main()
