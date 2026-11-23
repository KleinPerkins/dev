"""Personal doctor caller candidate: scoped, read-only, staged connector input.

Source engineering only until dependency/source and native owner acceptance.
Additional-root bindings are integrity evidence, never human decisions. The
owning workflow must obtain the actual root-specific decision before using one.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).absolute().parent
DEPENDENCIES={
    'personal_linked_diagnostics.py':'58e080685ab863722ca06b4305997013279c43a88648b9e729b39a0bd62a09a7',
    'personal_documentation.py':'e42b8fd3453e45768107a811f3e3a3a5e2bea70f198090d59aa569d90c040c0c',
    'personal_remote.py':'357a5c81f1487b4388837052941b1a1f28e02c7435320f4b8754b4d0de62f132',
}
for name,digest in DEPENDENCIES.items():
    path=HERE/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('personal doctor dependency changed')
sys.path.insert(0,str(HERE))
import personal_linked_diagnostics as d
import personal_documentation as doc
import personal_remote as remote
for name in DEPENDENCIES:
    if Path(sys.modules[Path(name).stem].__file__).absolute()!=HERE/name:
        raise ValueError('personal doctor dependency imported from another root')
l,p,b,c,g,w,s=d.l,d.p,d.b,d.c,d.g,d.w,d.s
r=l.r
DOCTOR_BLOB=d.DOCTOR_BLOB
MAX_BINDINGS=16
MAX_INPUT=doc.MAX_INPUT+remote.MAX_BYTES+(MAX_BINDINGS+1)*p.MAX_RECEIPT_BYTES+MAX_BINDINGS*l.MAX_BINDING_BYTES
IDENTITY_FIELDS=('head','branch','config_sha256','worktree_config_sha256',
                 'expected_personal_origin_verified','local_identity_canonical',
                 'effective_email_canonical','effective_personal_identity_canonical')


def unavailable(reason):
    return {'available':False,'verdict':'ADVISORY','reason':reason}


def safe_reason(error,default):return str(error) if isinstance(error,g.Refusal) else default


class Inputs:
    """Closed data-only envelope; it grants no account, root or native authority."""
    def __init__(self,value,selected,authority,*,now=None,remote_enabled=False):
        self.selected=s.selected_ids(selected);self.linked=[]
        if value is None:value={'schema':'personal-doctor-input/v1','responses':None,'legacy_receipts':None,'linked':[],'remote':None}
        if (not isinstance(value,dict) or set(value)!={'schema','responses','legacy_receipts','linked','remote'}
                or value['schema']!='personal-doctor-input/v1' or not isinstance(value['linked'],list)
                or len(value['linked'])>MAX_BINDINGS):
            raise g.Refusal('doctor-input-contract-differs')
        if not remote_enabled and value['remote'] is not None:raise g.Refusal('doctor-remote-input-needs-explicit-mode')
        self.remote_enabled=remote_enabled
        self.remote=remote.Observations(value['remote'],self.selected,authority,now=now)
        self.responses=p.Responses(value['responses'],self.selected,authority,now=now)
        self.receipts=doc.LegacyReceipts(value['legacy_receipts'],self.selected)
        seen=set()
        for entry in value['linked']:
            if (not isinstance(entry,dict) or set(entry)!={'binding_text','binding_sha256','responses'}
                    or not isinstance(entry['binding_text'],str)):
                raise g.Refusal('doctor-linked-input-contract-differs')
            raw=entry['binding_text'].encode('utf-8');digest=entry['binding_sha256']
            binding=l.read_binding(raw,digest);key=(binding['repository'],binding['candidate_sha256'])
            if key[0] not in self.selected or key in seen:raise g.Refusal('doctor-duplicate-or-unselected-linked-binding')
            seen.add(key)
            responses=p.Responses(entry['responses'],[key[0]],authority,now=now)
            self.linked.append({'raw':raw,'digest':digest,'binding':binding,'responses':responses})


def identity(metadata):
    if metadata.get('expected_personal_origin_verified') is not True:raise g.Refusal('doctor-personal-origin-unavailable')
    return {'available':True,'verdict':'OK' if metadata['effective_email_canonical'] else 'VIOLATION',
            'effective_email_canonical':metadata['effective_email_canonical'],
            'local_identity_canonical':metadata['local_identity_canonical'],
            'effective_personal_identity_canonical':metadata['effective_personal_identity_canonical'],
            'raw_identity_emitted':False}


def status(metadata):
    if metadata.get('worktree_status_proven') is not True:
        return unavailable('doctor-worktree-status-unavailable')
    ahead,behind=metadata['ahead'],metadata['behind']
    notes=[]
    if not metadata['clean_under_personal_policy']:notes.append('uncommitted-changes')
    if ahead or behind:notes.append('out-of-sync-local-tracking')
    return {'available':True,'verdict':'ADVISORY' if notes else 'OK','notes':notes,
            'head':metadata['head'],'branch':metadata['branch'],'detached':metadata['detached'],
            'expected_pin':metadata['expected_pin'],'pin_matches':metadata['pin_matches'],
            'clean_under_personal_policy':metadata['clean_under_personal_policy'],
            'ahead':ahead,'behind':behind,'upstream_present':metadata['upstream'] is not None,
            'sync_evidence':'last-fetch local tracking refs only; no live parity inferred',
            'unpushed_work_advisory':bool(ahead and ahead>0),'push_performed':False,
            'reported_change_items':metadata['reported_change_items']}


def core_verdict(components):
    values=[value['verdict'] for value in components.values() if not value.get('outside_canonical_repository_verdict')]
    return c.verdict(*values) if values else 'ADVISORY'


def project_sync(components,repo,observations):
    local=copy.deepcopy(components.get('status',unavailable('doctor-status-unavailable')))
    value=remote.sync(repo,local,observations)
    components['remote_sync']={'available':value['available'],'verdict':'OK','observation':value,
                               'outside_canonical_repository_verdict':True}
    if value['available'] and value['classification'] in {'EQUAL','DIFFERENT'}:
        projected=copy.deepcopy(local)
        projected['local_tracking_notes']=list(local['notes'])
        projected['local_tracking_unpushed_work_advisory']=local['unpushed_work_advisory']
        projected['notes']=[note for note in local['notes'] if note!='out-of-sync-local-tracking']
        if value['classification']=='DIFFERENT':projected['notes'].append('remote-branch-tip-differs')
        else:projected['unpushed_work_advisory']=False
        projected['canonical_sync_label']=value['canonical_sync_label']
        projected['live_remote_parity_proven']=value['classification']=='EQUAL'
        projected['verdict']='ADVISORY' if projected['notes'] else 'OK'
        components['status']=projected
    return local


def linked_components(result,entry,home,remote_observations=None):
    components=result.get('components',{})
    base_observation=components.get('baseline',{}).get('observation',{})
    components['status']=status(base_observation)
    target=Path(entry['binding']['binding_proposal']['target_path'])
    try:relative=target.relative_to(home/'dev').as_posix()
    except ValueError:relative=str(target)
    place='cap' if relative.startswith('capabilities/') else 'pers' if relative.startswith('personal/') else 'repo'
    identity_available=components.get('identity',{}).get('available',False)
    components['placement']={'available':identity_available,'verdict':'OK' if identity_available else 'ADVISORY',
                             'class':place,'bound_personal_repository':True,'additional_root_decision_granted_by_data':False}
    controls=components.get('controls',{});observation=controls.get('observation')
    if observation is not None:
        # Preserve the actual legacy caller's lexical guard scope. The accepted
        # bound-common helper observation stays visible even outside that scope.
        controls['bound_helper_verdict']=controls['verdict']
        controls['canonical_hook_scope_applicable']=place in {'cap','pers'}
        if place=='repo':
            controls['verdict']=c.verdict(observation['memory']['verdict'],observation['agents']['verdict'])
    local=None
    if remote_observations is not None and identity_available:local=project_sync(components,entry['binding']['repository'],remote_observations)
    result.update(components=components,verdict=core_verdict(components),
                  available=all(row['available'] for row in components.values()),
                  _local_status_before_remote=local)
    return result


def primary_profile(repo,tool,baseline,authority,responses):
    if not baseline.get('baseline_available'):raise g.Refusal('doctor-profile-baseline-applicability-unavailable')
    tree=w.PersonalWorktree(repo,tool);metadata=tree.git.observe()
    if metadata['head']!=baseline['head'] or metadata['branch']!=baseline['branch']:
        raise g.Refusal('doctor-profile-head-or-branch-changed')
    reader=p.ProfileReader(tree);raw,_=reader.read(p.POLICY)
    local=p.local_contract(reader,repo.row['id'],authority,raw)
    remote=p.remote_contract(repo.row['id'],raw is not None,baseline,authority,responses)
    reader.check();tree.git.finish();tree.unchanged()
    available,verdict=p.outcomes(local,remote)
    return {'available':available,'verdict':verdict,'profile_present':raw is not None,'local':local,'remote':remote,
            'local_control_evidence_sha256':w.digest(reader.evidence),'legacy_state_or_status_adopted':False,
            'legacy_doctor_compatibility_result':'v3 is incompatible with the legacy unversioned closed v1 verifier' if local['version']=='pr-automation/v3' else 'not applicable' if raw is None else 'legacy compatibility not evaluated',
            'operator_full_visibility_attested':False},(reader,tree)


def primary(repo,tool,authority,doc_authority,receipts,responses,templates,home,remote_observations=None):
    components={};controls=None;baseline_check=None;profile_checks=None;baseline={};metadata=None
    try:
        controls=c.PersonalControls(repo,tool);value=controls.observe()
        components['identity']=identity(value)
        metadata={key:value[key] for key in IDENTITY_FIELDS}
        components['controls']={'available':value['controls_available'],'verdict':value['controls_verdict'],'observation':value}
    except (ValueError,OSError,UnicodeError) as error:
        components['identity']=unavailable('doctor-identity-unavailable')
        components['controls']=unavailable(safe_reason(error,'doctor-controls-unavailable'))
    try:
        baseline_check=b.PersonalBaseline(repo,tool,templates);baseline=baseline_check.observe()
        components['status']=status(baseline)
        components['baseline']={'available':baseline['baseline_available'],
                                'verdict':baseline['baseline_diagnostic_verdict'],'observation':baseline}
        observed={key:baseline[key] for key in IDENTITY_FIELDS}
        if metadata is not None and metadata!=observed:
            raise g.Refusal('doctor-primary-identity-changed-between-components')
        metadata=observed
        if not components['identity']['available']:components['identity']=identity(baseline)
        components['placement']={'available':True,'verdict':'OK','class':'cap' if repo.row['path'].startswith('capabilities/') else 'pers',
                                 'expected_personal_origin_verified':True,'manifest_path_verified':True}
    except (ValueError,OSError,UnicodeError) as error:
        components['status']=unavailable('doctor-worktree-status-unavailable')
        components['baseline']=unavailable(safe_reason(error,'doctor-baseline-unavailable'))
        components['placement']=unavailable('doctor-origin-or-placement-unavailable')
        if isinstance(error,g.Refusal) and str(error)=='doctor-primary-identity-changed-between-components':raise
    try:
        components['profile'],profile_checks=primary_profile(repo,tool,baseline,authority,responses)
    except (ValueError,OSError,UnicodeError,KeyError,TypeError,SystemExit,p.p.ControlPlaneError) as error:
        components['profile']=unavailable(safe_reason(error,'doctor-profile-unavailable'))
    try:
        documentation=doc.inspect_repository(repo,tool,doc_authority,receipts)
        components['documentation']={**documentation,'verdict':'ADVISORY' if not documentation['available'] else 'OK',
                                     'outside_canonical_repository_verdict':True}
    except (ValueError,OSError,UnicodeError,doc.UnavailableEvidence,RecursionError):
        components['documentation']={**unavailable('doctor-documentation-unavailable'),'outside_canonical_repository_verdict':True}
    try:registry=r.one(repo,tool,home)
    except (ValueError,OSError,UnicodeError) as error:registry={'id':repo.row['id'],'available':False,'candidates':None,'reason':safe_reason(error,'doctor-registry-unavailable')}
    local_status=None
    if remote_observations is not None:
        if metadata is None:
            components['remote_sync']={**unavailable('doctor-origin-unavailable-before-remote-read'),'outside_canonical_repository_verdict':True}
            components['fleet']={**unavailable('doctor-origin-unavailable-before-fleet-read'),'outside_canonical_repository_verdict':True}
        else:
            local_status=project_sync(components,repo.row['id'],remote_observations)
            fleet=remote.fleet_row(repo.row['id'],authority,remote_observations,home)
            components['fleet']={**fleet,'verdict':'OK','outside_canonical_repository_verdict':True}

    # Retained component readers remain live through composition. A later body
    # change holds that component without erasing independent identity facts.
    if controls is not None and hasattr(controls,'memory_preimage'):
        try:
            controls.reader.check();controls.tree.recheck_controls()
            if controls.memory_fact()!=controls.memory_preimage:raise g.Refusal('doctor-memory-metadata-changed')
            controls.tree.git.finish();controls.tree.unchanged()
        except (ValueError,OSError):components['controls']=unavailable('doctor-final-controls-changed')
    if baseline_check is not None and 'head' in baseline:
        try:
            after=b.PersonalBaseline(repo,tool,templates).observe()
            if d.baseline_state(after)!=d.baseline_state(baseline):raise g.Refusal('doctor-final-baseline-changed')
            baseline_check.reader.check()
        except (ValueError,OSError):
            components['baseline']=unavailable('doctor-final-baseline-changed')
            components['status']=unavailable('doctor-final-worktree-status-changed')
    if profile_checks is not None:
        try:
            reader,tree=profile_checks;reader.check();tree.git.finish();tree.unchanged()
        except (ValueError,OSError):components['profile']=unavailable('doctor-final-profile-changed')
    if 'document_evidence_sha256' in components['documentation'] or components['documentation'].get('classification')=='NOT_APPLICABLE':
        try:
            after=doc.inspect_repository(repo,tool,doc_authority,receipts)
            expected={k:v for k,v in components['documentation'].items() if k not in {'verdict','outside_canonical_repository_verdict'}}
            if after!=expected:raise g.Refusal('doctor-final-documentation-changed')
        except (ValueError,OSError,UnicodeError,doc.UnavailableEvidence):
            components['documentation']={**unavailable('doctor-final-documentation-changed'),'outside_canonical_repository_verdict':True}
    try:
        if r.one(repo,tool,home)!=registry:raise g.Refusal('doctor-final-registry-changed')
    except (ValueError,OSError):registry={'id':repo.row['id'],'available':False,'candidates':None,'reason':'doctor-final-registry-changed'}
    if metadata is not None:
        current=g.PersonalGit(repo,tool).observe()
        if {key:current[key] for key in IDENTITY_FIELDS}!=metadata:
            # An origin/config/HEAD boundary change invalidates the joined row.
            raise g.Refusal('doctor-final-primary-identity-or-source-changed')
    authority.unchanged();doc_authority.check()
    verdict=core_verdict(components)
    return {'id':repo.row['id'],'relative_path':repo.row['path'],'kind':'primary',
            'available':all(v['available'] for v in components.values()) and registry['available'],
            'verdict':verdict,'components':components,'linked_registry':registry,
            '_local_status_before_remote':local_status}


def inspect(scope,tool,authority,doc_authority,inputs):
    if scope.repositories!=inputs.selected:raise g.Refusal('doctor-input-selection-differs')
    templates=b.load_templates();primaries=[];linked=[]
    authority.unchanged();doc_authority.check()
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:
                value=primary(repo,tool,authority,doc_authority,inputs.receipts,inputs.responses,templates,scope.home,
                              inputs.remote if inputs.remote_enabled else None)
        except (ValueError,OSError,UnicodeError,TypeError,KeyError,SystemExit,p.p.ControlPlaneError):
            value={'id':target['id'],'kind':'primary',**unavailable('doctor-primary-boundary-unavailable'),'components':{},
                   'linked_registry':{'available':False,'candidates':None}}
        primaries.append(value)
    protocol_valid=True
    try:inputs.responses.check_used()
    except g.Refusal:
        protocol_valid=False
        for row in primaries:
            row['components']['profile']=unavailable('doctor-unproven-profile-response-held')
            row['available']=False
            row['verdict']=core_verdict(row['components'])
    inspected=set();attempted=set();partially_inspected=set()
    for entry in inputs.linked:
        binding=entry['binding'];key=(binding['repository'],binding['candidate_sha256'])
        owner=next(row for row in primaries if row['id']==key[0])
        candidates=owner['linked_registry'].get('candidates') or []
        if not owner['linked_registry']['available'] or not any(x.get('candidate_sha256')==key[1] and x.get('binding_proposal')==binding['binding_proposal'] for x in candidates):
            linked.append({'id':key[0],'candidate_sha256':key[1],**unavailable('doctor-linked-registry-binding-not-current')})
            continue
        # The owning workflow supplies a binding only after its actual exact
        # additional-root decision. No boolean/token here manufactures consent.
        attempted.add(key)
        result=d.inspect(scope,tool,entry['raw'],entry['digest'],authority,entry['responses'])
        result=linked_components(result,entry,scope.home,inputs.remote if inputs.remote_enabled else None)
        if result.get('components',{}).get('identity',{}).get('available'):partially_inspected.add(key)
        linked.append({'id':key[0],'candidate_sha256':key[1],'kind':'linked',**result})
        if result.get('available'):inspected.add(key)
    uninspected=[]
    for row in primaries:
        registry=row['linked_registry']
        if not registry['available']:continue
        for candidate in registry['candidates']:
            key=(row['id'],candidate.get('candidate_sha256'))
            if key not in inspected:
                uninspected.append({'repository':row['id'],'candidate_sha256':candidate.get('candidate_sha256'),
                                    'registry_name_sha256':candidate.get('registry_name_sha256'),
                                    'status':'partially-inspected-unavailable' if key in partially_inspected else 'inspection-attempt-unavailable' if key in attempted else 'held-uninspected' if candidate['status']=='held-uninspected' else 'proposed-uninspected',
                                    'target_access_attempted':key in attempted,
                                    'owner_additional_root_decision_granted':False,'target_counted_clean':False})
    remote_protocol_valid=True
    try:inputs.remote.check_used()
    except g.Refusal:
        remote_protocol_valid=False
        for row in primaries+linked:
            components=row.get('components',{})
            if row.get('_local_status_before_remote') is not None and components.get('status',{}).get('available'):
                components['status']=row['_local_status_before_remote']
            for component in ('remote_sync','fleet'):
                if component in components:components[component]={**unavailable('doctor-unproven-remote-response-held'),'outside_canonical_repository_verdict':True}
            row['available']=False;row['verdict']=core_verdict(components)
    for row in primaries+linked:row.pop('_local_status_before_remote',None)
    authority.unchanged();doc_authority.check()
    values=primaries+linked;verdict=c.verdict(*(row['verdict'] for row in values))
    available=all(row['available'] for row in values) and not uninspected and protocol_valid and remote_protocol_valid
    return {'schema':'personal-portability/personal-doctor/v1','canonical_doctor_blob':DOCTOR_BLOB,
            'available':available,'verdict':verdict,'primary_rows':primaries,'linked_rows':linked,
            'uninspected_linked_targets':uninspected,'requests':list(inputs.responses.missing.values())+
                [request for entry in inputs.linked for request in entry['responses'].missing.values()]+list(inputs.remote.missing.values()),
            'source_pin_evidence_is_not_live_remote_parity':True,'profile_response_protocol_accepted':protocol_valid,
            'documentation_is_advisory_outside_repository_verdict':True,
            'remote_mode':inputs.remote_enabled,'remote_observation_protocol_accepted':remote_protocol_valid,
            'fleet_scope':'selected manifest-approved personal cohort only; no whole mixed/held fleet expansion',
            'fleet_advisory_outside_repository_verdict':True,
            'connector_data_or_binding_hash_grants_no_auth_or_human_decision':True,
            'network_requests_by_process':0,'source_or_configuration_writes':False,'new_shared_links':0,'new_workers':0,
            'generated_memory_contents_read':False,'legacy_state_imported':False,'operator_full_visibility_attested':False,
            'source_and_native_owner_acceptance':False,'active_v2_documentation_capability_accepted':False,
            'formal_migration_complete':False}


def summary(result):
    rows=result['primary_rows']+result['linked_rows']
    unknown=[{'repository':row['id'],'kind':row.get('kind','linked'),'component':name}
             for row in rows for name,value in row.get('components',{}).items() if not value['available']]
    for row in rows:
        if not row.get('linked_registry',{'available':True})['available']:
            unknown.append({'repository':row['id'],'kind':row.get('kind','linked'),'component':'linked_registry'})
        elif not row['available'] and not row.get('components'):
            unknown.append({'repository':row['id'],'kind':row.get('kind','linked'),'component':'boundary'})
    counts={level:sum(row['verdict']==level for row in rows) for level in c.LEVELS}
    docs={};fleet={}
    for row in rows:
        for name,counts_by_state in (('documentation',docs),('fleet',fleet)):
            value=row.get('components',{}).get(name)
            if value is not None:
                state=value.get('classification','UNAVAILABLE');counts_by_state[state]=counts_by_state.get(state,0)+1
    return {'schema':'personal-portability/personal-doctor-summary/v1','available':result['available'],'verdict':result['verdict'],
            'primary_count':len(result['primary_rows']),'linked_count':len(result['linked_rows']),
            'unresolved_linked_count':len(result['uninspected_linked_targets']),'verdict_counts':counts,
            'unavailable_components':unknown,'documentation_classifications':docs,'fleet_classifications':fleet,
            'pending_GET_requests':len({row['url'] for row in result['requests']}),'remote_mode':result['remote_mode'],
            'operator_full_visibility_attested':False,'source_and_native_owner_acceptance':False,
            'formal_migration_complete':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect', 'inspect-codex', 'inspect-created'])
    parser.add_argument('--repository', action='append')
    parser.add_argument('--input-stdin',action='store_true');parser.add_argument('--remote',action='store_true')
    parser.add_argument('--quiet',action='store_true')
    parser.add_argument('--fixture-root', help='disposable creator root for inspect-created')
    parser.add_argument('--fixture-repository-id', help='exact ID supplied to the fixture creator')
    args=parser.parse_args(argv)
    try:
        if args.operation == 'inspect-created':
            if (len(args.repository or ()) != 1 or args.remote or args.input_stdin
                    or args.fixture_root == ''):
                parser.error('inspect-created requires one explicit repository and local observations')
            import personal_created_doctor as created
            try:
                result = created.diagnose(args.repository[0], args.fixture_root, args.fixture_repository_id)
            except (g.Refusal, created.creator.ScaffoldMismatch) as error:
                print(json.dumps({'status': 'refused', 'reason': str(error)}))
                return 2
            except subprocess.SubprocessError:
                print(json.dumps({'status': 'refused', 'reason': 'creator-check-unavailable'}))
                return 2
            print(json.dumps(result, sort_keys=True))
            return 1 if result['local_git_verdict'] == 'VIOLATION' else 0
        if args.fixture_root is not None or args.fixture_repository_id is not None:
            parser.error('fixture selection is available only for inspect-created')
        if args.operation == 'inspect-codex':
            # The historical cohort includes retired, work-only and held repositories.
            # Select explicitly before opening any repository or reading connector input.
            if not args.repository:
                raise g.Refusal('doctor-explicit-personal-selection-required')
            if any(repo in {'KleinPerkins/sterling', 'KleinPerkins/server-guard',
                            'KleinPerkins/pr-automation-controller'} for repo in args.repository):
                raise g.Refusal('doctor-personal-selection-excluded')
        selected=s.selected_ids(args.repository);authority=p.Authority();doc_authority=doc.Authority();value=None
        if args.input_stdin:
            raw=sys.stdin.buffer.read(MAX_INPUT+1)
            if len(raw)>MAX_INPUT:raise g.Refusal('doctor-input-byte-bound')
            value=p.strict_json(raw)
        inputs=Inputs(value,selected,authority,remote_enabled=args.remote)
        result=inspect(s.PersonalScope(repositories=selected),g.GitTool(),authority,doc_authority,inputs)
        print(json.dumps(summary(result) if args.quiet else result,sort_keys=True))
        return 1 if result['verdict']=='VIOLATION' else 0 if result['available'] else 2
    except (ValueError,OSError,UnicodeError,TypeError,KeyError,SystemExit,p.p.ControlPlaneError):
        print(json.dumps({'status':'refused','reason':'personal-doctor-input-authority-scope-or-tool-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
