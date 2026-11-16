#!/usr/bin/env python3
"""Opt-in, read-only verification after an explicitly accepted APFS identity attestation.

The approved legacy engine, manifest and journals are never edited. Verification
writes only the legacy bound report and its report-owner record. This does not
authorize resume, rollback, directory adoption, or any other repository mutation.
A preview digest is not operator consent. Source acceptance and exact operator
acceptance of the preview are external prerequisites to the verify invocation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import uuid

ENGINE_SHA = '1960480349368b6c41cb5dfb50ec3e7f4ed62fc5244e79666739f0f62999fffd'
MANIFEST_SHA = 'e6e9bf948d1f664367456fffe06e408a08b50933466022b8b7dc2e30a35bf725'
SKILLS_ACTION = '527692fac99ce00b3567fc921b53f731605f778fbd45e8a3c61463794b4f9f24'
OWNER_FILES = {
 '_ops/interoperability/skill_migration.py': '79460a05441a2403c89ab96e8d38ef4f65a8b30b416817d7b2cae76b4f091a08',
 '_ops/interoperability/inventory.py': '5414d384788924f66f7ed324aa2c0092c5367a58ac914c36532c85a5fcd9f64e',
 'capabilities/bootstrap.sh': '8893eb54ec53cf3d6df5f8212df3a4c838200b234e893d08100a751f15d23eec',
}
SCHEMA = 'personal-portability/device-attestation/v1'


def canonical(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def real_path(raw):
 p=Path(raw).expanduser().absolute()
 for ancestor in (p,*p.parents):
  if ancestor.is_symlink(): raise ValueError('symlinked path is not an attestation target')
 return p


def regular(path,mode=None):
 p=real_path(path);s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid():
  raise ValueError('unshared, operator-owned regular file required')
 if mode is not None and stat.S_IMODE(s.st_mode)!=mode: raise ValueError('private record mode changed')
 return p.read_bytes()


def directory(path):
 p=real_path(path);s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid(): raise ValueError('operator-owned directory required')
 return {'path':str(p),'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode)}


def volume(path):
 # df resolves the actual backing device, including the macOS Data firmlink.
 p=subprocess.run(['/bin/df','-P',str(path)],capture_output=True,text=True,check=True)
 lines=p.stdout.splitlines()
 if len(lines)!=2: raise ValueError('ambiguous backing filesystem')
 device=lines[1].split()[0]
 if not re.fullmatch(r'/dev/disk[0-9]+s[0-9]+',device): raise ValueError('ordinary APFS volume required')
 p=subprocess.run(['/usr/sbin/diskutil','info','-plist',device],capture_output=True,check=True)
 data=plistlib.loads(p.stdout)
 if data.get('Error') or data.get('FilesystemType')!='apfs' or not data.get('Internal'):
  raise ValueError('internal APFS volume identity unavailable')
 identifier=str(uuid.UUID(data['VolumeUUID'])).upper()
 return {'volume_uuid':identifier,'filesystem':'apfs','internal':True}


def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path)
 result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
 return result


def normalized_journal(original,root,new_device):
 """Translate only declared directory observations in a private in-memory copy."""
 result=copy.deepcopy(original);old=result['root_binding']['current']['device']
 root_info=directory(root)
 if root_info['device']!=new_device or root_info['inode']!=result['root_binding']['current']['inode']:
  raise ValueError('root inode or current device changed')
 def change(observation,path):
  actual=directory(path)
  if observation['device']!=old or actual['device']!=new_device or actual['inode']!=observation['inode']:
   raise ValueError('directory inode or filesystem differs from the declared mapping')
  observation['device']=new_device
 change(result['root_binding']['current'],root)
 for row in result['owned_directories']: change(row,row['path'])
 for action in result['actions'].values():
  if action['status']!='installed' or not action['created'] or action['staging'] is not None:
   raise ValueError('only a completely installed, unstaged source reconstruction can be attested')
  change(action['postimage'],Path(root)/action['path'])
 return result


def original_skill_record(record,receipt,owner):
 unsigned={k:v for k,v in record.items() if k not in {'action_sha256','receipt_sha256'}}
 if record.get('action_sha256')!=SKILLS_ACTION or owner.sha(owner.canonical(unsigned))!=SKILLS_ACTION:
  raise ValueError('original exact approved skill action changed')
 if owner.sha(owner.canonical(receipt))!=record.get('receipt_sha256'):
  raise ValueError('original skill receipt changed')
 checks={
  'schema':owner.RECEIPT_SCHEMA,'operation_id':record['operation_id'],'action_sha256':SKILLS_ACTION,
  'source_proof_sha256':owner.sha(owner.canonical(record['source_proof'])),
  'preimages_sha256':owner.sha(owner.canonical({'managed':record['managed'],'preserved':record['preserved']})),
  'policy_sha256':record['policy_sha256'],'implementation_sha256':record['implementation_sha256'],
 }
 if receipt!=checks or record.get('schema')!=owner.SCHEMA or record.get('source_mode')!='pinned-retained':
  raise ValueError('original owner receipt does not bind this operation')


def normalized_skill(record,operation,new_device):
 result=copy.deepcopy(record);old=result['operation_root']['device']
 if result['operation_dir']!=str(operation): raise ValueError('skill operation location changed')
 for state,path in [(result['operation_root'],operation)]+[(r['state'],r['path']) for r in result['preserved'] if r['state'].get('kind')=='directory']:
  actual=directory(path)
  if state['device']!=old or actual['device']!=new_device or state['inode']!=actual['inode'] or state['mode']!=actual['mode']:
   raise ValueError('skill directory inode, mode or filesystem changed')
  state['device']=new_device
 return result


def inspect(args):
 kit=real_path(args.kit);root=real_path(args.root);state=real_path(args.state_dir)
 runtime=real_path(args.skills_runtime);operation=real_path(args.skills_operation)
 if sha(regular(kit/'engine.py'))!=ENGINE_SHA or sha(regular(kit/'manifest.json'))!=MANIFEST_SHA:
  raise ValueError('approved immutable legacy package changed')
 for name,digest in OWNER_FILES.items():
  if sha(regular(runtime/name))!=digest: raise ValueError('accepted skill workflow export changed')
 engine=module('_attestation_legacy_engine',kit/'engine.py')
 sys.path.insert(0,str(runtime/'_ops/interoperability'))
 module('inventory',runtime/'_ops/interoperability/inventory.py')
 owner=module('_attestation_legacy_skills',runtime/'_ops/interoperability/skill_migration.py')
 current=directory(root)['device'];identity=volume(root)
 for p in [state,operation,Path(root).parent/'.codex/skills']:
  if directory(p)['device']!=current or volume(p)!=identity: raise ValueError('attestation targets span filesystems')
 before={str(p):regular(p,0o600) for p in [state/'journal.json',operation/'operation.json',operation/'preview-receipt.json']}
 journal=json.loads(before[str(state/'journal.json')]);record=json.loads(before[str(operation/'operation.json')]);receipt=json.loads(before[str(operation/'preview-receipt.json')])
 instance=engine.Engine(kit/'manifest.json',root,state,state/'report.json')
 candidate=normalized_journal(journal,root,current)
 instance._validate_journal(candidate)  # authoritative legacy closed-schema/path validator
 rows={r['id']:r for r in instance.manifest['repositories'] if r['disposition'] in engine.ACTIVE_REPOSITORY_DISPOSITIONS}
 for name,action in candidate['actions'].items():
  matches,reason=instance._postimage_matches(root/action['path'],rows[name],action['postimage'],strict_files=False)
  if not matches: raise ValueError(f'{name}: {reason}')
 original_skill_record(record,receipt,owner)
 native=normalized_skill(record,operation,current)
 if native['implementation_sha256']!=owner.implementation_digest(): raise ValueError('skill implementation drift')
 owner.private_operation_current(native);owner.current_source_proof(native);owner.current_policy(native);owner.preserved_current(native);owner.staging_absent(native)
 if owner.prefix_state(native)!=len(native['actions']): raise ValueError('retained skill postimages changed')
 facts={'schema':SCHEMA,'scope':'read-only source/skill verification; only the bound report and report-owner record may be written; no ownership adoption',
  'implementation_sha256':sha(Path(__file__).read_bytes()),'kit':str(kit),'root':str(root),'state_dir':str(state),'skills_runtime':str(runtime),'skills_operation':str(operation),
  'engine_sha256':ENGINE_SHA,'manifest_sha256':MANIFEST_SHA,'original_skill_action_sha256':SKILLS_ACTION,
  'volume':identity,'bound_record_sha256':{p:sha(raw) for p,raw in before.items()},
  'root_inode':directory(root)['inode'],'source_postimages_sha256':sha(canonical(journal['actions'])),
  'source_repositories_verified':len(rows),'retained_skills_verified':len(native['actions']),
  'limitations':['The prior journal has no stable volume UUID; continuity of the old volume is not established. Exact operator acceptance re-attests the present read-only observations.',
                 'Current device numbers are observations, not approval identifiers; the approved APFS UUID, inodes, source records and every legacy content/config/ref check must still match.',
                 'The original engine and skill-operation mutation/rollback interfaces remain fail-closed on their old device bindings. This interface cannot rebind or adopt them.']}
 return facts,engine,owner,journal,record,current


def read_only_engine(legacy,args,facts):
 class AttestedEngine(legacy.Engine):
  def _validate_journal(self,journal):
   if volume(self.root)!=facts['volume']: raise ValueError('approved volume identity changed')
   return super()._validate_journal(normalized_journal(journal,self.root,directory(self.root)['device']))
  def _save_journal(self,*a,**k): raise ValueError('journal writes are forbidden by the attestation interface')
  def apply(self,*a,**k): raise ValueError('mutation is not authorized by a read-only attestation')
  resume=apply
  rollback=apply
  def _base_report(self,command):
   result=super()._base_report(command)
   result['device_attestation']={'action_sha256':args.approve,'scope':'read-only verification','implementation_sha256':sha(Path(__file__).read_bytes()),'original_journal_unchanged':True,'mutation_authority':False}
   return result
 return AttestedEngine(Path(args.kit)/'manifest.json',args.root,args.state_dir,Path(args.state_dir)/'report.json')


def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('command',choices=['preview','verify'])
 for name in ['kit','root','state-dir','skills-runtime','skills-operation']:parser.add_argument('--'+name,required=True)
 parser.add_argument('--attestation',required=True);parser.add_argument('--approve')
 args=parser.parse_args(argv);os.umask(0o077)
 facts,legacy,owner,journal,record,device=inspect(args);digest=sha(canonical(facts));path=real_path(args.attestation)
 if args.command=='preview':
  if args.approve is not None: raise ValueError('a preview is not an approval')
  with path.open('xb') as stream:
   os.fchmod(stream.fileno(),0o600);stream.write(canonical({'facts':facts,'action_sha256':digest,'observed_current_device':device})+b'\n')
  print(json.dumps({'status':'previewed','action_sha256':digest,'source_repositories_verified':facts['source_repositories_verified'],'retained_skills_verified':facts['retained_skills_verified'],'original_records_written':0,'attestation_preview':str(path)}));return 0
 preview=json.loads(regular(path,0o600))
 if set(preview)!={'facts','action_sha256','observed_current_device'} or preview['facts']!=facts or preview['action_sha256']!=digest or args.approve!=digest:
  raise ValueError('exact unchanged attestation and external operator approval required')
 # Neither the journal nor the native skill operation is ever rewritten.
 report=read_only_engine(legacy,args,facts).verify()
 if volume(Path(args.root))!=facts['volume']: raise ValueError('approved volume identity changed during verification')
 for p,digest_before in facts['bound_record_sha256'].items():
  if sha(regular(p,0o600))!=digest_before: raise ValueError('bound source record changed during verification')
 print(json.dumps({'result':report['result'],'errors':len(report['errors']),'source_ready_repositories':sum(r['source_ready'] for r in report['repositories']),'required_blockers':len(report['required_blockers']),'device_attestation':args.approve,'original_records_unchanged':True,'mutation_authority':False}));return legacy._exit_code(report)


if __name__=='__main__':
 try:raise SystemExit(main())
 except (ValueError,OSError,subprocess.SubprocessError) as error:
  print(json.dumps({'result':'refused','reason':str(error)}));raise SystemExit(2)
