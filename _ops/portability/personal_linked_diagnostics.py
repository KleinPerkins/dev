"""Bound linked identity, hook/memory, baseline and personal profile diagnostics.

Read-only successor components over the accepted linked status backend. Exact
input integrity is not human consent, additional-root admission, native exposure,
active-v2 documentation authority or complete doctor/migration acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

HERE=Path(__file__).absolute().parent
LINKED_SHA256='eafd14c18e1748e3438f6e0feaedbae151cce0466351eaa852fd6585eb3c13c4'
source=HERE/'personal_linked_worktree.py'
if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=LINKED_SHA256:
    raise ValueError('accepted personal linked status dependency changed')
sys.path.insert(0,str(HERE))
import personal_linked_worktree as l
if Path(l.__file__).absolute()!=source:raise ValueError('linked status imported from another root')
p=l.r.p
b,c,g,w,s=p.b,p.c,l.g,l.w,l.s
OWNER_REF='a0b536ee72c3e7b018159c201c3a4e10c9c7bd9b'
DOCTOR_BLOB='7e8aed3984be06ad970366313e43e1eebea8d40d'
MAX_INPUT_BYTES=p.MAX_RECEIPT_BYTES+2*l.MAX_BINDING_BYTES


class CommonControlTree:
    """Reader-only common metadata view; never a checkout or Git query view."""
    classify_control_ancestors=w.PersonalWorktree.classify_control_ancestors

    def __init__(self,context):
        common=context.common.directory
        self.repo=s.RepositoryView(common.fd,context.primary.row,common.path)


class LinkedControls(c.PersonalControls):
    def __init__(self,context,tool):
        self.context=context;self.tree=l.LinkedWorktree(context,tool)
        self.repo,self.tool=context.repo,tool
        self.reader=c.Reader(self.tree)
        self.common_reader=c.Reader(CommonControlTree(context))

    def hook_reader(self,raw):
        if not isinstance(raw,str):raise g.Refusal('invalid-hook-path-setting')
        if not raw:return self.common_reader,'hooks','bound-common-default'
        candidate=Path(raw)
        if candidate.is_absolute() and candidate.is_relative_to(self.context.common.directory.path):
            path=c.hook_path(raw,self.context.common.directory.path)
            return self.common_reader,path,'bound-common-explicit'
        return self.reader,c.hook_path(raw,self.repo.path),'bound-checkout-explicit'

    def hooks(self):
        cfg=self.tree.git.config;configured='core.hookspath' in cfg;raw=g.last(cfg,'core.hookspath','')
        result={'configured_override':configured,'configured_path_sha256':g.sha(str(raw).encode()),
                'hook_execution_proven':False,'hook_bodies_executed':False,
                'registration_source_ref':c.REGISTRATION_SOURCE_REF,'registration_source_blob':c.REGISTRATION_SOURCE_BLOB,
                'linked_default_hooks_scope':'bound common metadata; explicit relative paths retain actual gitfile semantics'}
        if isinstance(raw,str) and raw.rstrip('/')=='/dev/null':
            return {**result,'available':True,'canonical_guard_state':'inert-hookspath',
                    'registration_guard':'not-active','verdict':'DRIFT','note':'explicit-null-hooks-path'}
        try:
            reader,path,scope=self.hook_reader(raw);result['resolved_scope']=scope
            relative=(path+'/' if path else '')+'pre-commit'
            data,state=reader.read(relative)
            active=data is not None and c.GUARD_MARKER in data
            if not active:
                kind=('foreign-hookspath' if '.husky' in str(raw) or 'lefthook' in str(raw)
                      else 'inert-hookspath') if raw else 'missing'
                return {**result,'available':True,'canonical_guard_state':kind,
                        'registration_guard':'not-active','verdict':'DRIFT' if kind=='inert-hookspath' else 'ADVISORY'}
            guard,guard_state=reader.read((path+'/' if path else '')+'registration-guard')
            current=guard is not None and g.sha(guard)==c.REGISTRATION_SHA256
            executable=bool(state['mode']&stat.S_IXUSR)
            guard_executable=guard is not None and bool(guard_state['mode']&stat.S_IXUSR)
            return {**result,'available':True,'canonical_guard_state':'active','marker_is_structural_only':True,
                    'dispatcher_executable':executable,'registration_guard':'missing' if guard is None else 'current' if current else 'stale',
                    'registration_guard_executable':guard_executable,
                    'verdict':'OK' if current and executable and guard_executable else 'ADVISORY'}
        except (ValueError,OSError) as error:
            return {**result,'available':False,'canonical_guard_state':'unavailable','registration_guard':'unavailable',
                    'verdict':'ADVISORY','reason':str(error) if isinstance(error,g.Refusal) else 'bound-linked-hook-control-unavailable'}

    def check(self):
        self.context.check();self.reader.check();self.common_reader.check();self.tree.recheck_controls()
        if self.memory_fact()!=self.memory_preimage:raise g.Refusal('linked-memory-metadata-changed')
        self.tree.git.finish();self.tree.unchanged()

    def observe(self):
        result=super().observe();self.check()
        return {**result,'common_hook_control_evidence_sha256':w.digest(self.common_reader.evidence),
                'linked_hook_and_memory_contract_observed':True}


class LinkedBaseline(b.PersonalBaseline):
    def __init__(self,context,tool,templates):
        if set(templates)!=set(b.TEMPLATE_HASHES) or any(g.sha(templates[n])!=h for n,h in b.TEMPLATE_HASHES.items()):
            raise g.Refusal('immutable-baseline-template-drift')
        self.context=context;self.repo,self.tool,self.templates=context.repo,tool,dict(templates)
        self.tree=l.LinkedWorktree(context,tool);self.reader=b.BaselineReader(self.tree);self.eligibility_ready=False


def documentation_applicability():
    # The canonical doctor's documentation loop explicitly enumerates primaries
    # rather than expanding registered linked worktrees. Preserve this boundary;
    # do not turn a skip into v2 documentation or file-compliance acceptance.
    return {'available':True,'classification':'NOT_APPLICABLE','reason':'canonical-doctor-documentation-loop-is-primary-only',
            'canonical_doctor_blob':DOCTOR_BLOB,'source_lines':[460,465,473,484,489],
            'documentation_bodies_read':False,'legacy_structural_check_executed':False,
            'active_v2_documentation_capability_qualified':False,'verdict':'OK'}


def unavailable(component,error):
    return {'available':False,'verdict':'ADVISORY','component':component,
            'reason':str(error) if isinstance(error,g.Refusal) else 'bound-linked-'+component+'-unavailable'}


def baseline_state(value):
    return {**b.PersonalBaseline.stable(value),**{key:value.get(key) for key in (
        'baseline_available','baseline_eligibility','baseline_compliance','baseline_file_states',
        'baseline_control_evidence_sha256','baseline_unavailable_reasons')}}


def profile(context,tool,baseline,authority,responses,templates):
    if not baseline.get('baseline_available'):raise g.Refusal('linked-profile-baseline-applicability-unavailable')
    tree=l.LinkedWorktree(context,tool);identity=tree.git.observe()
    if identity['head']!=baseline['head'] or identity['branch']!=baseline['branch']:
        raise g.Refusal('linked-profile-head-or-branch-changed')
    reader=p.ProfileReader(tree);raw,_=reader.read(p.POLICY)
    local=p.local_contract(reader,context.repo.row['id'],authority,raw)
    remote=p.remote_contract(context.repo.row['id'],raw is not None,baseline,authority,responses)
    reader.check();tree.git.finish();tree.unchanged()
    after=LinkedBaseline(context,tool,templates).observe()
    if not after['baseline_available'] or baseline_state(baseline)!=baseline_state(after):
        raise g.Refusal('linked-profile-baseline-applicability-changed')
    reader.check();authority.unchanged()
    available,verdict=p.outcomes(local,remote)
    value={'available':available,'verdict':verdict,'profile_present':raw is not None,'local':local,'remote':remote,
            'local_control_evidence_sha256':w.digest(reader.evidence),'legacy_state_or_status_adopted':False,
            'legacy_doctor_compatibility_result':'v3 is incompatible with the legacy unversioned closed v1 verifier' if local['version']=='pr-automation/v3' else 'not applicable' if raw is None else 'legacy compatibility not evaluated',
            'operator_full_visibility_attested':False}
    return value,(reader,tree)


def inspect(scope,tool,raw,digest,authority,responses):
    try:
        with l.bound_checkout(scope,tool,raw,digest) as context:
            templates=b.load_templates();components={};controls=None;baseline_check=None;profile_checks=None
            try:
                controls=LinkedControls(context,tool);value=controls.observe()
                components['controls']={'available':value['controls_available'],'verdict':value['controls_verdict'],'observation':value}
            except (ValueError,OSError,UnicodeError) as error:components['controls']=unavailable('controls',error)
            try:
                baseline_check=LinkedBaseline(context,tool,templates);baseline=baseline_check.observe()
                components['baseline']={'available':baseline['baseline_available'],'verdict':baseline['baseline_diagnostic_verdict'],'observation':baseline}
            except (ValueError,OSError,UnicodeError) as error:
                baseline={'baseline_available':False,'baseline_eligibility':{'classification':'UNAVAILABLE'}}
                components['baseline']=unavailable('baseline',error)
            if 'observation' in components['controls']:
                identity=components['controls']['observation']
                components['identity']={'available':True,'verdict':'OK' if identity['effective_email_canonical'] else 'VIOLATION',
                                        'effective_email_canonical':identity['effective_email_canonical'],
                                        'local_identity_canonical':identity['local_identity_canonical'],
                                        'effective_personal_identity_canonical':identity['effective_personal_identity_canonical'],
                                        'raw_email_or_name_emitted':False,'canonical_doctor_blob':DOCTOR_BLOB}
            else:components['identity']=unavailable('identity',g.Refusal('linked-identity-control-observation-unavailable'))
            try:components['profile'],profile_checks=profile(context,tool,baseline,authority,responses,templates)
            except (ValueError,OSError,UnicodeError,SystemExit,p.p.ControlPlaneError) as error:components['profile']=unavailable('profile',error)
            components['documentation']=documentation_applicability()
            if baseline.get('baseline_available'):
                after=LinkedBaseline(context,tool,templates).observe()
                if not after['baseline_available'] or baseline_state(baseline)!=baseline_state(after):
                    raise g.Refusal('linked-diagnostic-final-baseline-or-worktree-changed')
                baseline_check.reader.check()
            if profile_checks is not None:
                reader,tree=profile_checks;reader.check();tree.git.finish();tree.unchanged()
            if controls is not None and hasattr(controls,'memory_preimage'):controls.check()
            authority.unchanged();connector_protocol_valid=True
            try:responses.check_used()
            except g.Refusal as error:
                components['profile']=unavailable('profile',error);connector_protocol_valid=False
            context.check()
            value={'schema':'personal-portability/personal-linked-diagnostics/v1','owner_ref':OWNER_REF,
                   'repository':context.repo.row['id'],'binding_sha256':digest,
                   'available':all(row['available'] for row in components.values()),
                   'verdict':c.verdict(*(row['verdict'] for row in components.values())),
                   'components':components,'requests':list(responses.missing.values()),
                   'connector_observation_protocol_accepted':connector_protocol_valid,
                   'original_primary_pin_is_not_a_linked_revision_acceptance':True,
                   'source_or_configuration_writes':False,'generated_memory_contents_read':False,
                   'network_requests_by_this_process':0,'new_shared_links':0,'new_model_workers':0,
                   'legacy_state_or_status_adopted':False,'operator_full_visibility_attested':False,
                   'connector_receipt_grants_no_auth_or_owner_approval':True,
                   'actual_owner_additional_root_acceptance_or_full_doctor_or_native_acceptance':False}
        return value
    except (ValueError,OSError,UnicodeError,TypeError,KeyError,SystemExit,p.p.ControlPlaneError) as error:
        return {'schema':'personal-portability/personal-linked-diagnostics/v1','available':False,'verdict':'ADVISORY',
                'reason':str(error) if isinstance(error,g.Refusal) else 'bound-linked-diagnostics-unavailable',
                'partial_component_results_invalidated':True,'actual_target_status_proven':False,
                'full_doctor_or_native_acceptance':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--binding-sha256',required=True);args=parser.parse_args(argv)
    try:
        raw=sys.stdin.buffer.read(MAX_INPUT_BYTES+1)
        if len(raw)>MAX_INPUT_BYTES:raise g.Refusal('linked-diagnostic-input-byte-bound')
        envelope=p.strict_json(raw)
        if (not isinstance(envelope,dict) or set(envelope)!={'schema','binding_text','responses'}
                or envelope['schema']!='personal-linked-diagnostic-input/v1' or not isinstance(envelope['binding_text'],str)):
            raise g.Refusal('linked-diagnostic-input-contract-differs')
        binding=envelope['binding_text'].encode();value=l.read_binding(binding,args.binding_sha256)
        scope=s.PersonalScope(repositories=[value['repository']]);authority=p.Authority()
        responses=p.Responses(envelope['responses'],scope.repositories,authority)
        result=inspect(scope,g.GitTool(),binding,args.binding_sha256,authority,responses)
        print(json.dumps(result,sort_keys=True));return 1 if result['verdict']=='VIOLATION' else 0 if result['available'] else 2
    except (ValueError,OSError,UnicodeError,TypeError,KeyError,SystemExit,p.p.ControlPlaneError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error,g.Refusal) else 'linked-diagnostic-input-scope-or-authority-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
