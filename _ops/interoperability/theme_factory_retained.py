#!/usr/bin/env python3
"""Separate retained Theme Factory operation after exact native-evidence acceptance.

The unchanged one-link transaction supplies inode-owned publication/rollback.
This wrapper permits at most one fresh local catalog child per exact operation;
verify/repeated apply never start another child. No model worker is permitted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE=Path(__file__).absolute().parent
CORE_SHA='9dfb49f38838be9faaeaa932d14b25c68471ef119287afbd524754d7ca089337'
CATALOG_SHA='5431887ad3baf3b606b8cf087af6a23b2dff73a687b1f810196297205f04892c'
for name,digest in [('theme_factory_canary.py',CORE_SHA),('theme_factory_catalog.py',CATALOG_SHA)]:
    path=HERE/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('same-source retained dependency changed: '+name)
sys.path.insert(0,str(HERE))
import theme_factory_canary as core
import theme_factory_catalog as native
if Path(core.__file__).absolute()!=HERE/'theme_factory_canary.py' or Path(native.__file__).absolute()!=HERE/'theme_factory_catalog.py':
    raise ValueError('retained dependency imported from another source')

SCHEMA='interoperability/theme-factory-retained/v1'
EVIDENCE_SHA='25d0b21abe721e1432c8198647facd702e79897bdb938ad740cc316fd24c2278'
EVIDENCE_ACTION='6e1e33cf11a6fa2cbce17982761fd44096fa77b6ec3bdd825773ff97f3185474'
ORIGINAL_ACTION='23ff0416d7a07cec9a5b0adb2591c2b61f9b3bd42e7ce8089f8a1713c2eab8d7'
CHECKER_REVISION='24a24c66ad8d93124ab462df4ea4f30e188980b9'


def implementation():
    if core.sha(core.regular(HERE/'theme_factory_canary.py'))!=CORE_SHA or core.sha(core.regular(HERE/'theme_factory_catalog.py'))!=CATALOG_SHA:
        raise ValueError('same-source retained dependency changed')
    return core.sha(core.canonical({'theme_factory_retained.py':core.sha(core.regular(Path(__file__).absolute())),
        'theme_factory_catalog.py':CATALOG_SHA,'core':core.implementation()}))


def evidence(path):
    path=path.expanduser().absolute();core.atom.shared.no_symlink_components(path)
    state=core.observation(path)
    if state.get('kind')!='file' or state.get('mode')!=0o600 or state.get('uid')!=os.getuid() or path.stat().st_size>65536:
        raise ValueError('private exact native-evidence acceptance required')
    raw=core.regular(path)
    if core.sha(raw)!=EVIDENCE_SHA:raise ValueError('exact immutable native-evidence acceptance required')
    value=core.read_record(path)
    if (value.get('schema')!='personal-portability/theme-factory-bounded-native-evidence-owner-acceptance/v1'
            or value.get('action_sha256')!=EVIDENCE_ACTION or value.get('original_native_action')!=ORIGINAL_ACTION
            or value.get('accepted_corrected_checker_source')!=CHECKER_REVISION
            or value.get('actual_exact_owner_approval_received') is not True
            or value.get('bounded_native_discovery_and_use_evidence_accepted') is not True
            or value.get('retained_interface_or_installation_authorized') is not False
            or value.get('original_refused_receipt_or_action_rewritten') is not False):
        raise ValueError('native-evidence decision does not qualify this retained profile')
    return {'local_path':str(path),'sha256':EVIDENCE_SHA,'action_sha256':EVIDENCE_ACTION,
        'original_canary_action':ORIGINAL_ACTION,'accepted_checker_revision':CHECKER_REVISION,'state':state}


def qualification_unchanged(plan):
    if evidence(Path(plan['native_evidence']['local_path']))!=plan['native_evidence'] or native.cli_proof()!=plan['native_cli']:
        raise ValueError('accepted native evidence or qualified bundled CLI changed')


def _one_target(child):
    rows=child['targets']
    if len(rows)!=1 or rows[0]['name']!='theme-factory':raise ValueError('retained profile escaped its one Theme Factory target')
    return rows[0]


def preview(args):
    home=args.home.expanduser().absolute()
    if home!=Path.home().absolute():raise ValueError('non-default home is outside the retained owner contract')
    accepted=evidence(args.native_evidence);cli=native.cli_proof()
    cwd=home/'Codex';core.directory(cwd)
    operation=core.private_operation(args.operation_dir,home);core.directory(operation.parent)
    operation.mkdir(mode=0o700)
    child_args=argparse.Namespace(home=home,operation_dir=operation/'transaction',portability_manifest=args.portability_manifest)
    proposed=core.preview(child_args);child=core.load(child_args.operation_dir);row=_one_target(child)
    plan={'schema':SCHEMA,'operation_dir':str(operation),'operation_root':core.directory(operation),
        'implementation_sha256':implementation(),'home':str(home),'native_cwd':str(cwd),
        'core_action_sha256':proposed['action_sha256'],
        'core_record_sha256':core.sha(core.regular(child_args.operation_dir/'operation.json')),
        'target':row['target'],'desired':row['desired'],'native_evidence':accepted,'native_cli':cli,
        'catalog_protocol':dict(native.PROTOCOL),'retention_requested':True,'model_worker_count':0,
        'affected_sessions':'All Codex sessions scanning the shared skill root; existing contexts may retain prior discovery.',
        'external_consent':'Separate exact retained operation consent required; an action digest cannot authenticate a human.'}
    digest=core.sha(core.canonical(plan))
    core.atom.write_once(operation/'operation.lock',{})
    core.atom.write_once(operation/'retained-operation.json',{**plan,'action_sha256':digest})
    return {'status':'previewed-retained','operation_dir':str(operation),'action_sha256':digest,
        'target':row['target'],'staging':row['staging'],'retention_applied':False,'new_model_workers':0,
        'maximum_new_catalog_processes':1}


def load(operation):
    home=Path.home().absolute();operation=core.private_operation(operation,home,existing=True)
    if core.directory(operation)['mode']!=0o700:raise ValueError('retained operation must be private')
    plan=core.read_record(operation/'retained-operation.json');digest=plan.pop('action_sha256')
    fields={'schema','operation_dir','operation_root','implementation_sha256','home','native_cwd','core_action_sha256',
        'core_record_sha256','target','desired','native_evidence','native_cli','catalog_protocol','retention_requested',
        'model_worker_count','affected_sessions','external_consent'}
    if (set(plan)!=fields or core.sha(core.canonical(plan))!=digest or plan['schema']!=SCHEMA
            or plan['operation_dir']!=str(operation) or plan['operation_root']!=core.directory(operation)
            or plan['implementation_sha256']!=implementation() or plan['home']!=str(home)
            or plan['native_cwd']!=str(home/'Codex') or plan['retention_requested'] is not True
            or type(plan['model_worker_count']) is not int or plan['model_worker_count']!=0
            or plan['catalog_protocol']!=native.PROTOCOL):raise ValueError('retained operation identity or fixed scope changed')
    transaction=operation/'transaction'
    if core.sha(core.regular(transaction/'operation.json'))!=plan['core_record_sha256']:raise ValueError('underlying transaction record changed')
    child=core.load(transaction);row=_one_target(child)
    if child['action_sha256']!=plan['core_action_sha256'] or row['target']!=plan['target'] or row['desired']!=plan['desired']:
        raise ValueError('retained operation escaped its exact transaction')
    plan['action_sha256']=digest;return plan


def _identity(plan,response):
    rows=response.get('data',[])
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or rows[0].get('cwd')!=plan['native_cwd'] or rows[0].get('errors'):
        raise ValueError('native catalog incomplete for the exact scope')
    skills=rows[0].get('skills',[])
    if not isinstance(skills,list):raise ValueError('native skills must be a list')
    matches=[s for s in skills if isinstance(s,dict) and s.get('name')=='theme-factory']
    if len(matches)!=1 or matches[0].get('enabled') is not True:raise ValueError('native catalog did not discover exactly the enabled Theme Factory skill')
    skill=Path(plan['target'])/'SKILL.md';canonical=skill.resolve(strict=True)
    expected=Path(plan['desired'])/'SKILL.md';reported=matches[0].get('path')
    if canonical!=expected or reported not in (str(skill),str(expected)) or not skill.samefile(reported):
        raise ValueError('native catalog path is not the exact retained Theme Factory source')
    return {'name':'theme-factory','enabled':True,'link_path':str(skill),'canonical_source_path':str(expected),
        'same_file_verified':True}


def valid_process(plan,proof):
    if (proof.get('schema')!='interoperability/theme-factory-catalog-process/v1'
            or proof.get('success') is not True or proof.get('action_sha256')!=plan['action_sha256']
            or proof.get('original_child_reaped') is not True or proof.get('exclusive_child_custody_lost') is not False
            or not all(proof.get(k) is True for k in ('actual_stdout_EOF','actual_stderr_EOF','process_group_absent_at_observation',
                'strict_actual_hard_deadline_passed','actual_HOME_CODEX_HOME_preserved','OS_network_and_fork_denied',
                'original_birth_captured_before_parent_signal_restore','single_main_thread_owner'))
            or proof.get('methods')!=native.PROTOCOL['methods'] or type(proof.get('exit_code')) is not int or proof['exit_code']!=0
            or type(proof.get('duration_ms')) is not int or not 0<=proof['duration_ms']<=12000
            or type(proof.get('new_model_workers_conversation_threads_or_token_refresh_methods')) is not int
            or proof['new_model_workers_conversation_threads_or_token_refresh_methods']!=0):
        raise ValueError('native catalog original-child postcondition incomplete')


def catalog(plan):
    response,observed=native.run(plan);proof=observed['process'];valid_process(plan,proof)
    operation=Path(observed['operation'])
    identifier=str(uuid.UUID(operation.name.removeprefix('catalog-')))
    if operation!=Path(plan['operation_dir'])/('catalog-'+identifier):raise ValueError('native catalog record escaped its operation')
    record=operation/'process-result.json'
    if core.read_record(record)!=proof:raise ValueError('native process receipt changed')
    return {'identity':_identity(plan,response),'process_record':str(record),'process_record_sha256':core.sha(core.regular(record))}


def retained_receipt(plan):
    operation=Path(plan['operation_dir']);value=core.read_record(operation/'retained.json')
    if set(value)!={'schema','action_sha256','native_catalog'} or value['schema']!='interoperability/theme-factory-retained-receipt/v1' or value['action_sha256']!=plan['action_sha256']:
        raise ValueError('retained receipt changed')
    observed=value['native_catalog'];record=Path(observed['process_record'])
    if set(observed)!={'identity','process_record','process_record_sha256'}:raise ValueError('retained catalog receipt shape changed')
    identifier=str(uuid.UUID(record.parent.name.removeprefix('catalog-')))
    if record!=operation/('catalog-'+identifier)/'process-result.json' or core.sha(core.regular(record))!=observed['process_record_sha256']:
        raise ValueError('retained native process record changed')
    proof=core.read_record(record)
    valid_process(plan,proof)
    expected={'name':'theme-factory','enabled':True,'link_path':str(Path(plan['target'])/'SKILL.md'),
        'canonical_source_path':str(Path(plan['desired'])/'SKILL.md'),'same_file_verified':True}
    if observed['identity']!=expected:raise ValueError('retained native identity changed')
    if core.read_record(operation/'native-attempt.json')!={'action_sha256':plan['action_sha256'],'maximum_processes':1}:
        raise ValueError('native attempt owner record changed')
    return value


def execute(args):
    plan=load(args.operation_dir)
    if args.operation!='verify' and args.approve!=plan['action_sha256']:raise ValueError('separate exact retained approval required')
    child=argparse.Namespace(operation_dir=Path(plan['operation_dir'])/'transaction',approve=plan['core_action_sha256'])
    with core.operation_lock(child.operation_dir):
        if args.operation=='rollback':
            result=core.apply(child,undo=True);core.verify(child)
            return {'status':result['status'],'retention_applied':False,'new_catalog_processes':0}
        qualification_unchanged(plan)
        if args.operation=='verify':
            state=core.verify(child)
            if state['status']=='verified-preimage':
                if core.observation(Path(plan['operation_dir'])/'retained.json')['kind']!='absent' and core.observation(child.operation_dir/'rolled-back.json')['kind']=='absent':
                    raise ValueError('retained target is missing; no recreation or native replay permitted')
                if core.observation(Path(plan['operation_dir'])/'native-attempt.json')['kind']!='absent' and core.observation(child.operation_dir/'rolled-back.json')['kind']=='absent':
                    raise ValueError('native allowance already consumed without a completed outcome; owner inspection required')
                return {'status':'verified-preimage','retention_applied':False,'new_catalog_processes':0}
            receipt=retained_receipt(plan)
            return {'status':'verified-retained','retention_applied':True,'native_catalog':receipt['native_catalog'],
                'native_evidence_is_original_completed_operation':True,'new_catalog_processes':0,'new_model_workers':0}
        operation=Path(plan['operation_dir'])
        if core.observation(operation/'retained.json')['kind']!='absent':
            receipt=retained_receipt(plan)
            if core.verify(child)['status']!='verified-canary':raise ValueError('retained target missing or operation rolled back; no replay permitted')
            return {'status':'already-retained','retention_applied':True,'native_catalog':receipt['native_catalog'],'new_catalog_processes':0,'new_model_workers':0}
        if core.observation(operation/'native-attempt.json')['kind']!='absent':raise ValueError('native allowance already consumed; exact rollback or owner inspection required')
        try:
            core.apply(child);core.verify(child)
            core.atom.write_once(operation/'native-attempt.json',{'action_sha256':plan['action_sha256'],'maximum_processes':1})
            observed=catalog(plan)
            core.verify(child);qualification_unchanged(plan)
            core.atom.write_once(operation/'retained.json',{'schema':'interoperability/theme-factory-retained-receipt/v1',
                'action_sha256':plan['action_sha256'],'native_catalog':observed})
            retained_receipt(plan)
            return {'status':'applied-retained','retention_applied':True,'native_catalog':observed,'new_catalog_processes':1,'new_model_workers':0}
        except BaseException as failure:
            try:core.apply(child,undo=True);core.verify(child)
            except BaseException as recovery:raise ValueError('retained failure; foreign edits preserved and exact recovery requires inspection: '+str(recovery)) from failure
            raise ValueError('retained failure; exact link rollback verified: '+str(failure)) from failure


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('preview','apply','verify','rollback'))
    parser.add_argument('--operation-dir',type=Path,required=True)
    parser.add_argument('--portability-manifest',type=Path)
    parser.add_argument('--native-evidence',type=Path)
    parser.add_argument('--approve');args=parser.parse_args(argv);args.home=Path.home();os.umask(0o077)
    try:
        if args.operation=='preview':
            if args.portability_manifest is None or args.native_evidence is None or args.approve is not None:raise ValueError('preview requires manifest/evidence and is not approval')
            result=preview(args)
        else:
            with core.operation_lock(args.operation_dir):result=execute(args)
        print(json.dumps(result,sort_keys=True));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'status':'refused','reason':str(error)}));return 2


if __name__=='__main__':raise SystemExit(main())
