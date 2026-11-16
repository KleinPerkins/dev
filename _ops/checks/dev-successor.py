#!/usr/bin/env python3
"""Offline source-adoption validation. This never grants runtime or seed authority."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

RECORD = '_ops/policy/dev-successor.json'
REPOSITORY_ID = 1459458379
REPOSITORY_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://api.github.com/repositories/1459458379'))
NAME_PHASES = {'preparation': 'KleinPerkins/dev-temp', 'final': 'KleinPerkins/dev'}
PREDECESSOR_EVIDENCE = 'b08786ecab5baee0b177a424957f9c8f5cc3360eca9dcaa2b785246914b6b364'
PLAN = 'be6fd4f89d0c132f1a277c84065a7f316cc7c2706dc5b6ad2b9db333ea4eb39a'
SCOPE = ['current-source-operating-baseline', 'source-only-document-artifact-transactions']
EXCLUDED = ['awa', 'doc-warden-v2-unfinished', 'intent-router', 'pr-automation-controller', 'scheduler']
POLICIES = {'.doc-warden.yml', '.planning/doc-warden.json', '_ops/POLICY.md', 'OPERATING-MANUAL.md', '_ops/rules/agent-context.md', '_ops/doc-warden/POLICY.md'}
HISTORICAL = {
    '_ops/adr/0001-doc-warden-owning-subsystem.md',
    '_ops/adr/0002-doc-warden-reconciliation-doctrine.md',
    '_ops/adr/0003-doc-warden-local-only-no-cpp.md',
    '_ops/adr/0004-optimize-context-projections-without-moving-authority.md',
    '_ops/adr/0005-harden-context-measurement-before-e09.md',
    '_ops/adr/0008-chaos-scheduler-doc-warden-docs-governance.md',
    '_ops/adr/0009-doc-warden-v2-gsd-aligned-governance.md',
    '_ops/adr/0010-agentic-execution-safety-layer-deferred.md',
    '_ops/adr/0011-manifest-driven-verification-selector.md',
    '_ops/adr/0012-source-owned-cursor-codex-interoperability.md',
    '_ops/adr/0013-coordinated-maintenance-for-source-owned-mcp-migration.md',
    '_ops/adr/0014-shadowsync-native-github-delivery-exception.md',
    '_ops/adr/0015-dev-owned-shadowsync-host-policy-projection-and-atomic-binding.md',
    '_ops/adr/0016-canonical-typed-plan-authority-and-acceptance.md',
    '_ops/adr/0017-machine-monitor-native-delivery-and-mandatory-new-repository-test-sharding.md',
    '_ops/adr/0018-independent-repository-visibility-and-distribution.md',
    '_ops/plans/agent-worktree-automation-end-state-v3.md',
    '_ops/plans/agentic-execution-safety-layer-deferred-v1.md',
    '_ops/plans/agentic-plan-template-upgrade-v1.md',
    '_ops/plans/archive/agent-worktree-automation-end-state-v1.md',
    '_ops/plans/archive/agent-worktree-automation-end-state-v2.md',
    '_ops/plans/capability-local-opt-out-v1.md',
    '_ops/plans/capability-local-opt-out-v2.md',
    '_ops/plans/context-efficiency-d01-capability-discovery-inventory-v1.md',
    '_ops/plans/context-efficiency-e06-dev-host-overlay-v1.md',
    '_ops/plans/context-efficiency-e06-dev-host-overlay-v2.md',
    '_ops/plans/context-efficiency-e06-dev-host-overlay-v3.md',
    '_ops/plans/context-efficiency-program-v1.md',
    '_ops/plans/context-efficiency-program-v2.md',
    '_ops/plans/context-efficiency-release2-closure-v1.md',
    '_ops/plans/context-efficiency-s01-dev-static-reduction-v1.md',
    '_ops/plans/doc-warden-execution-plan-v1.md',
    '_ops/plans/doc-warden-execution-plan-v2.md',
    '_ops/plans/kp-context-measurement-v1-tooling-v1.md',
    '_ops/plans/local-ci-migration-v2.md',
    '_ops/plans/manifest-driven-verification-execution-v1.md',
    '_ops/plans/manifest-driven-verification-target-design-v1.md',
    '_ops/plans/operator-voice-toolkit-build-plan-v4.md',
    '_ops/plans/operator-voice-toolkit-build-plan-v5.md',
    '_ops/plans/operator-voice-toolkit-forensic-audit-v1.md',
    '_ops/verification/verification-rollout-ledger.json',
}
FIELDS = {'schema','github_repository_id','repository_key','name_phases','accepted_plan_sha256','predecessor_private_evidence','retained_policy','historical_provenance','semantic_adoption_scope','excluded_paused_work','source_identity_semantics','runtime_authority','source_admission'}

def need(condition, reason):
    if not condition:
        raise ValueError(reason)

def object_pairs(pairs):
    result = {}
    for k, v in pairs:
        need(k not in result, 'duplicate_json_key')
        result[k] = v
    return result

def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=object_pairs)

def file_binding(root, row):
    need(isinstance(row, dict) and set(row)=={'path','sha256','git_mode'}, 'binding_schema')
    name=row['path']
    need(isinstance(name,str) and name and not name.startswith('/') and str(PurePosixPath(name))==name and '..' not in PurePosixPath(name).parts and '\\' not in name,'binding_path')
    need(isinstance(row['sha256'],str) and re.fullmatch('[0-9a-f]{64}',row['sha256']) is not None,'binding_digest')
    need(row['git_mode'] in ('100644','100755'),'binding_mode')
    p=root
    for part in PurePosixPath(name).parts:
        p=p/part
        need(not p.is_symlink(),'binding_symlink')
    mode=p.stat().st_mode
    need(stat.S_ISREG(mode),'binding_not_regular')
    need(('100755' if mode&0o111 else '100644')==row['git_mode'],'binding_mode_drift')
    need(hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],'binding_digest_drift')

def validate(root: Path, *, repository_id: int, repository: str | None, record=None):
    root=root.resolve(strict=True)
    need(type(repository_id) is int and repository_id==REPOSITORY_ID,'successor_identity_mismatch')
    need(repository is None or repository in NAME_PHASES.values(),'successor_name_mismatch')
    value=read_json(root/RECORD) if record is None else record
    need(isinstance(value,dict) and set(value)==FIELDS,'successor_schema')
    expected={'schema':'dev-successor-adoption/v1','github_repository_id':REPOSITORY_ID,'repository_key':REPOSITORY_KEY,'name_phases':NAME_PHASES,'accepted_plan_sha256':PLAN,'semantic_adoption_scope':SCOPE,'excluded_paused_work':EXCLUDED,'source_identity_semantics':'fresh-history-new-immutable-id-no-predecessor-approval-replay','source_admission':'pending-independent-bootstrap-review-and-exact-administrative-release'}
    for k,v in expected.items():
        need(value[k]==v and type(value[k]) is type(v),'successor_'+k)
    need(value['runtime_authority'] is False,'runtime_authority_forbidden')
    evidence=value['predecessor_private_evidence']
    need(isinstance(evidence,dict) and set(evidence)=={'reference','sha256'} and evidence['reference']=='private-predecessor-current-source-assessment-v1','predecessor_evidence_schema')
    need(isinstance(evidence['sha256'],str) and re.fullmatch('[0-9a-f]{64}',evidence['sha256']) is not None and evidence['sha256']==PREDECESSOR_EVIDENCE,'predecessor_evidence_digest')
    sets={}
    for field in ('retained_policy','historical_provenance'):
        rows=value[field];need(isinstance(rows,list) and bool(rows),'binding_list')
        for row in rows:file_binding(root,row)
        names=[row['path'] for row in rows]
        need(names==sorted(set(names)),'binding_order_or_duplicate')
        sets[field]=set(names)
    need(sets['retained_policy']==POLICIES,'retained_policy_set')
    need(not sets['retained_policy']&sets['historical_provenance'],'historical_authority_overlap')
    need(sets['historical_provenance']==HISTORICAL,'historical_provenance_set')
    config=read_json(root/'.planning/doc-warden.json')
    need(config.get('github_repository_id')==REPOSITORY_ID and config.get('repository_key')==REPOSITORY_KEY,'doc_warden_identity_mismatch')
    need(config.get('legacy_roots')==[],'predecessor_artifacts_current')
    for relative in ('.planning/artifacts', 'docs/adr'):
        for artifact in (root / relative).glob('*.md'):
            if artifact.name == 'README.md':
                continue
            need(not artifact.is_symlink(), 'current_artifact_symlink')
            raw = artifact.read_text()
            need(raw.startswith('---\n') and '\n---\n' in raw[4:], 'current_artifact_metadata')
            metadata = json.loads(raw[4:].split('\n---\n', 1)[0], object_pairs_hook=object_pairs)
            need(isinstance(metadata, dict) and metadata.get('schema') == 'doc-warden/artifact/v2'
                 and metadata.get('repository_key') == REPOSITORY_KEY
                 and metadata.get('github_repository_id') == REPOSITORY_ID,
                 'predecessor_artifact_replay')
    return {'schema':'dev-successor-source-validation/v1','repository_id':repository_id,'repository':repository,'phase':next((k for k,v in NAME_PHASES.items() if v==repository),'not-observed'),'source_bindings':'valid','source_admission':value['source_admission'],'runtime_authority':False,'delivery':'pending-successor-qualification','historical_records_are_current_authority':False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--repository-id',required=True,type=int);p.add_argument('--repository',required=True);a=p.parse_args(argv)
    try:result=validate(a.root,repository_id=a.repository_id,repository=a.repository)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'refused','reason':str(exc)}));return 1
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
