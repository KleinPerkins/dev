"""Synthetic linked controls/baseline/profile composition and privacy fixtures."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_linked_diagnostics as m
from test_personal_git import fixture
from test_personal_linked_registry import linked
from test_personal_linked_worktree import encoded,target_git
from test_personal_controls import active
from test_personal_baseline import complete
from test_personal_profile import controls,raw_responses,NOW

REPO='KleinPerkins/skills'


def diagnose(scope,tool,authority=None,responses=None):
    authority=authority or m.p.Authority();raw,digest=encoded(scope,tool)
    receipts=m.p.Responses(responses,scope.repositories,authority,now=NOW)
    return m.inspect(scope,tool,raw,digest,authority,receipts)


def commit(target):target_git(target,'add','-A');target_git(target,'commit','--allow-empty','-m','synthetic linked diagnostics')


def clean_main(primary,target,git):
    git('switch','--detach');target_git(target,'switch','main')


def selected_responses(authority,*keys):
    value=raw_responses(authority);urls=m.p.urls(REPO,authority);allowed={urls[k] for k in keys}
    value['requests']=[r for r in value['requests'] if r['url'] in allowed]
    return value


class Hooks(unittest.TestCase):
    def test_default_hook_comes_from_common_metadata_not_own_admin(self):
        for common in (False,True):
            with self.subTest(common=common),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);active(primary if common else entry,'.git/hooks' if common else 'hooks')
                result=diagnose(scope,tool);self.assertTrue(result['available'],result)
                hook=result['components']['controls']['observation']['hooks']
                self.assertEqual(hook['canonical_guard_state'],'active' if common else 'missing')
                self.assertEqual(hook['resolved_scope'],'bound-common-default')
                self.assertEqual(hook['verdict'],'OK' if common else 'ADVISORY')

    def test_explicit_common_and_target_hook_roots_and_own_overlay(self):
        for kind in ('common','target-relative','target-absolute','target-root','own-overlay'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git)
                if kind=='common':directory=active(primary);git('config','core.hooksPath',str(directory))
                else:
                    directory=active(target,'.' if kind=='target-root' else 'custom')
                    path=str(directory) if kind=='target-absolute' else '.' if kind=='target-root' else 'custom'
                    if kind=='own-overlay':
                        git('config','extensions.worktreeConfig','true');target_git(target,'config','--worktree','core.hooksPath',path)
                    else:git('config','core.hooksPath',path)
                result=diagnose(scope,tool);self.assertTrue(result['available'],result)
                hook=result['components']['controls']['observation']['hooks']
                self.assertEqual((hook['canonical_guard_state'],hook['registration_guard'],hook['verdict']),('active','current','OK'))

    def test_literal_dot_git_override_is_not_remapped_to_common_hooks(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);active(primary);git('config','core.hooksPath','.git/hooks')
            result=diagnose(scope,tool);hook=result['components']['controls']['observation']['hooks']
            self.assertFalse(result['available']);self.assertEqual(hook['canonical_guard_state'],'unavailable')
            self.assertEqual(hook['resolved_scope'],'bound-checkout-explicit')

    def test_missing_stale_and_nonexecutable_guards_preserve_canonical_outcomes(self):
        for kind in ('missing','stale','dispatcher-mode','guard-mode'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);directory=active(primary)
                if kind=='missing':(directory/'registration-guard').unlink()
                if kind=='stale':(directory/'registration-guard').write_text('synthetic stale guard\n')
                if kind=='dispatcher-mode':(directory/'pre-commit').chmod(0o600)
                if kind=='guard-mode':(directory/'registration-guard').chmod(0o600)
                hook=diagnose(scope,tool)['components']['controls']['observation']['hooks']
                self.assertTrue(hook['available']);self.assertEqual(hook['verdict'],'ADVISORY')
                self.assertEqual(hook['registration_guard'],'missing' if kind=='missing' else 'stale' if kind=='stale' else 'current')

    def test_null_foreign_and_inert_paths_are_not_qualified_active(self):
        for path,kind,verdict in (('/dev/null','inert-hookspath','DRIFT'),('custom','inert-hookspath','DRIFT'),('.husky/_','foreign-hookspath','ADVISORY'),('lefthook','foreign-hookspath','ADVISORY')):
            with self.subTest(path=path),fixture() as (primary,scope,tool,git):
                linked(primary,scope,git);git('config','core.hooksPath',path)
                hook=diagnose(scope,tool)['components']['controls']['observation']['hooks']
                self.assertEqual((hook['canonical_guard_state'],hook['verdict']),(kind,verdict))

    def test_external_alias_shared_fifo_and_generated_memory_hook_paths_remain_unavailable(self):
        for kind in ('external','alias','shared','fifo','memory','protected'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);directory=active(primary)
                if kind=='external':git('config','core.hooksPath','/outside/PRIVATE_SYNTHETIC_HOOK')
                if kind=='alias':(directory/'pre-commit').unlink();(directory/'pre-commit').symlink_to('/not-read')
                if kind=='shared':os.link(directory/'pre-commit',directory/'preserved-hook')
                if kind=='fifo':(directory/'pre-commit').unlink();os.mkfifo(directory/'pre-commit',0o600)
                if kind=='memory':git('config','core.hooksPath','agent-learnings.md/hooks')
                if kind=='protected':git('config','core.hooksPath','chaos-scheduler/hooks')
                result=diagnose(scope,tool);self.assertFalse(result['available'])
                self.assertFalse(result['components']['controls']['observation']['hooks']['available'])
                self.assertNotIn('PRIVATE_SYNTHETIC_HOOK',json.dumps(result))

    def test_hook_body_is_never_executed(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);directory=active(primary);marker=scope.home/'HOOK_EXECUTED'
            (directory/'pre-commit').write_bytes(b'#!/bin/sh\n# '+m.c.GUARD_MARKER+b'\ntouch '+str(marker).encode()+b'\nexit 99\n')
            result=diagnose(scope,tool);self.assertTrue(result['available'],result);self.assertFalse(marker.exists())
            self.assertFalse(result['components']['controls']['observation']['hooks']['hook_bodies_executed'])


class MemoryAndIdentity(unittest.TestCase):
    def test_generated_memory_FIFO_can_be_ignored_without_body_reads(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);active(primary)
            (target/'.gitignore').write_text('agent-learnings.md\n');commit(target);os.mkfifo(target/'agent-learnings.md',0o600)
            original=m.s.read_regular
            def guarded(parent,name,**kw):
                if name=='agent-learnings.md':raise AssertionError('generated body read')
                return original(parent,name,**kw)
            with patch.object(m.s,'read_regular',guarded):result=diagnose(scope,tool)
            self.assertFalse(result['available']);memory=result['components']['controls']['observation']['memory']
            self.assertEqual((memory['state'],memory['verdict']),('unavailable','ADVISORY'));self.assertFalse(memory['body_read'])
            self.assertFalse(result['generated_memory_contents_read'])

    def test_tracked_memory_violation_survives_unavailable_status_and_profile(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);(target/'agent-learnings.md').write_text('PRIVATE_SYNTHETIC_GENERATED_BODY\n');commit(target)
            original=m.s.read_regular
            def guarded(parent,name,**kw):
                if name=='agent-learnings.md':raise AssertionError('generated body read')
                return original(parent,name,**kw)
            with patch.object(m.s,'read_regular',guarded):result=diagnose(scope,tool)
            self.assertFalse(result['available']);self.assertEqual(result['verdict'],'VIOLATION')
            self.assertEqual(result['components']['controls']['observation']['memory']['state'],'tracked')
            self.assertFalse(result['components']['baseline']['available']);self.assertFalse(result['components']['profile']['available'])
            self.assertNotIn('PRIVATE_SYNTHETIC_GENERATED_BODY',json.dumps(result))

    def test_tracked_AGENTS_verdict_is_local_and_not_adopted_as_context(self):
        for text,verdict in (('# Synthetic\nagent-learnings.md\n','OK'),('# Synthetic\n','ADVISORY'),('## Learned User Preferences\nPRIVATE_SYNTHETIC_CONTENT\n','DRIFT')):
            with self.subTest(verdict=verdict),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);active(primary);(target/'AGENTS.md').write_text(text);commit(target)
                result=diagnose(scope,tool);self.assertTrue(result['available'],result)
                agents=result['components']['controls']['observation']['agents'];self.assertEqual(agents['verdict'],verdict)
                self.assertFalse(agents['content_or_context_emitted']);self.assertNotIn('PRIVATE_SYNTHETIC_CONTENT',json.dumps(result))

    def test_effective_email_violation_survives_unavailable_hook(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);git('config','core.hooksPath','/outside/not-read')
            git('config','extensions.worktreeConfig','true');target_git(target,'config','--worktree','user.email','synthetic@example.invalid')
            result=diagnose(scope,tool);self.assertFalse(result['available']);self.assertEqual(result['verdict'],'VIOLATION')
            self.assertEqual(result['components']['identity']['verdict'],'VIOLATION');self.assertNotIn('synthetic@example.invalid',json.dumps(result))

    def test_local_and_effective_personal_identity_scopes_are_distinct(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);active(primary);git('config','user.email','synthetic@example.invalid')
            git('config','extensions.worktreeConfig','true');target_git(target,'config','--worktree','user.email',m.g.NOREPLY)
            result=diagnose(scope,tool);self.assertTrue(result['available'],result)
            identity=result['components']['identity'];self.assertFalse(identity['local_identity_canonical']);self.assertTrue(identity['effective_email_canonical']);self.assertEqual(identity['verdict'],'OK')


class BaselineAndProfile(unittest.TestCase):
    def test_detached_dirty_and_nonmain_exclusions_preserve_unchecked_compliance(self):
        for kind,reason in (('detached','detached-HEAD'),('dirty','dirty-working-tree'),('branch','not-clean-main-branch')):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);active(primary)
                if kind=='dirty':(target/'fixture.txt').write_text('dirty\n')
                if kind=='branch':target_git(target,'switch','-c','synthetic-linked')
                result=diagnose(scope,tool);self.assertTrue(result['available'],result)
                base=result['components']['baseline']['observation'];self.assertEqual(base['baseline_eligibility'],{'classification':'EXCLUDED','reason':reason})
                self.assertFalse(base['baseline_files_inspected']);self.assertIsNone(base['baseline_compliance'])
                self.assertEqual(result['components']['profile']['local']['status'],'NOT_APPLICABLE');self.assertEqual(result['requests'],[])

    def test_eligible_complete_baseline_and_current_v3_profile_use_owner_contracts(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);clean_main(primary,target,git);active(primary)
            authority=m.p.Authority();complete(target);controls(target,authority);commit(target)
            result=diagnose(scope,tool,authority,raw_responses(authority))
            self.assertTrue(result['available'],result);self.assertEqual(result['verdict'],'OK')
            base=result['components']['baseline']['observation'];profile=result['components']['profile']
            self.assertEqual(base['baseline_compliance'],'COMPLIANT');self.assertEqual(base['baseline_eligibility']['classification'],'ELIGIBLE')
            self.assertEqual(profile['local']['status'],'COMPLIANT');self.assertEqual(profile['remote']['review'],'CLEAN');self.assertEqual(profile['remote']['history'],'ENFORCED')
            self.assertFalse(profile['legacy_state_or_status_adopted']);self.assertFalse(profile['operator_full_visibility_attested'])
            self.assertEqual(result['requests'],[])

    def test_eligible_missing_baseline_does_not_require_history(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);clean_main(primary,target,git);active(primary);authority=m.p.Authority()
            result=diagnose(scope,tool,authority,selected_responses(authority,'metadata','review'))
            self.assertTrue(result['available'],result);self.assertEqual(result['verdict'],'ADVISORY')
            self.assertEqual(result['components']['baseline']['observation']['baseline_compliance'],'MISSING')
            self.assertEqual(result['components']['profile']['remote']['history'],'NOT_APPLICABLE')

    def test_missing_staged_connector_response_is_unknown_and_emits_only_selected_request(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);active(primary);authority=m.p.Authority();controls(target,authority);commit(target)
            result=diagnose(scope,tool,authority)
            self.assertFalse(result['available']);self.assertEqual(result['verdict'],'ADVISORY')
            self.assertEqual(result['components']['profile']['remote']['admin_bypass'],'UNKNOWN')
            self.assertEqual(len(result['requests']),1);self.assertEqual(result['requests'][0]['url'],m.p.urls(REPO,authority)['metadata'])

    def test_review_drift_and_plan_limited_history_remain_visible(self):
        for kind in ('review','history'):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);clean_main(primary,target,git);active(primary);complete(target);commit(target)
                authority=m.p.Authority();value=selected_responses(authority,'metadata','review','history');urls=m.p.urls(REPO,authority)
                for row in value['requests']:
                    if row['url']==urls[kind]:
                        if kind=='history':row['outcome']='plan-limit';row['data']=None
                        else:row['data']=[{'type':'pull_request','parameters':{'required_approving_review_count':1}}]
                result=diagnose(scope,tool,authority,value)
                self.assertEqual(result['available'],kind=='review');self.assertEqual(result['verdict'],'DRIFT' if kind=='review' else 'ADVISORY')
                self.assertEqual(result['components']['profile']['remote'][kind],'REVIEW_DRIFT' if kind=='review' else 'UNENFORCED_PLAN_LIMIT')

    def test_primary_only_documentation_skip_does_not_qualify_active_v2(self):
        with fixture() as (primary,scope,tool,git):
            linked(primary,scope,git);doc=diagnose(scope,tool)['components']['documentation']
            self.assertEqual(doc['classification'],'NOT_APPLICABLE');self.assertFalse(doc['documentation_bodies_read'])
            self.assertFalse(doc['legacy_structural_check_executed']);self.assertFalse(doc['active_v2_documentation_capability_qualified'])

    def test_unproven_remote_blob_refuses_profile_without_erasing_local_violation(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);(target/'agent-learnings.md').write_text('synthetic generated\n');commit(target)
            value={'schema':'personal-profile-responses/v1','observed_at':NOW.isoformat(),'requests':[
                {'url':'https://api.github.com/repos/'+REPO+'/git/blobs/'+'0'*40,'outcome':'ok','data':'PRIVATE_UNPROVEN_BLOB'}]}
            result=diagnose(scope,tool,responses=value)
            self.assertFalse(result['available']);self.assertEqual(result['verdict'],'VIOLATION')
            self.assertFalse(result['connector_observation_protocol_accepted']);self.assertFalse(result['components']['profile']['available'])
            self.assertEqual(result['components']['profile']['reason'],'unproven-profile-git-object-response-held')
            self.assertNotIn('PRIVATE_UNPROVEN_BLOB',json.dumps(result))

    def test_baseline_create_only_bodies_are_not_read_by_control_readers(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);clean_main(primary,target,git);active(primary);complete(target);commit(target)
            authority=m.p.Authority();value=selected_responses(authority,'metadata','review','history');original=m.s.read_regular
            def guarded(parent,name,**kw):
                if name in ('README.md','CODEOWNERS'):raise AssertionError('create-only baseline body read')
                return original(parent,name,**kw)
            with patch.object(m.s,'read_regular',guarded):result=diagnose(scope,tool,authority,value)
            self.assertTrue(result['available'],result)
            self.assertEqual(result['components']['baseline']['observation']['baseline_compliance'],'COMPLIANT')
            self.assertFalse(result['components']['baseline']['observation']['create_only_bodies_read'])


class StabilityAndInput(unittest.TestCase):
    def test_late_common_hook_change_invalidates_the_composed_result(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);directory=active(primary);original=m.profile
            def late(*args):
                result=original(*args);(directory/'pre-commit').write_bytes(b'# '+m.c.GUARD_MARKER+b'\n# late edit\n');return result
            with patch.object(m,'profile',late):result=diagnose(scope,tool)
            self.assertFalse(result['available']);self.assertTrue(result['partial_component_results_invalidated'])

    def test_late_ignored_profile_control_change_is_caught_by_retained_reader(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);active(primary);(target/'.gitignore').write_text('.github/\n');commit(target)
            authority=m.p.Authority();controls(target,authority);value=raw_responses(authority,review=False,history=False);original=m.profile
            def late(*args):
                result=original(*args);path=target/m.p.POLICY;path.write_bytes(path.read_bytes()+b'\n');return result
            with patch.object(m,'profile',late):result=diagnose(scope,tool,authority,value)
            self.assertFalse(result['available']);self.assertTrue(result['partial_component_results_invalidated'])

    def test_late_ignored_baseline_body_change_is_not_hidden_by_clean_status(self):
        with fixture() as (primary,scope,tool,git):
            target,entry=linked(primary,scope,git);clean_main(primary,target,git);active(primary);complete(target)
            with (target/'.gitignore').open('a') as stream:stream.write('SECURITY.md\nREADME.md\n.github/\n')
            target_git(target,'add','.gitignore');target_git(target,'commit','-m','synthetic ignored baseline files')
            authority=m.p.Authority();value=selected_responses(authority,'metadata','review','history');original=m.profile
            def late(*args):
                result=original(*args);(target/'SECURITY.md').write_text('synthetic later baseline body\n');return result
            with patch.object(m,'profile',late):result=diagnose(scope,tool,authority,value)
            self.assertFalse(result['available']);self.assertTrue(result['partial_component_results_invalidated'])

    def test_plain_split_sparse_keep_source_bytes_inodes_modes_and_timestamps(self):
        for variant in ('plain','split','sparse'):
            with self.subTest(variant=variant),fixture() as (primary,scope,tool,git):
                (primary/'keep').mkdir();(primary/'keep/value').write_text('one\n');git('add','.');git('commit','-m','synthetic data')
                target,entry=linked(primary,scope,git);active(primary)
                if variant=='split':target_git(target,'update-index','--split-index')
                if variant=='sparse':
                    git('config','extensions.worktreeConfig','true');target_git(target,'sparse-checkout','init','--cone','--sparse-index');target_git(target,'sparse-checkout','set','keep')
                def facts():
                    return {str(p.relative_to(scope.home)):(p.read_bytes(),p.stat().st_ino,stat.S_IMODE(p.stat().st_mode),p.stat().st_mtime_ns,p.stat().st_ctime_ns)
                            for root in (primary,target) for p in root.rglob('*') if p.is_file()}
                before=facts();result=diagnose(scope,tool)
                self.assertTrue(result['available'],result);self.assertEqual(before,facts())

    def test_malformed_or_unbound_input_refuses_before_any_selected_root(self):
        values=[{}, {'schema':'wrong','binding_text':'{}','responses':None},
                {'schema':'personal-linked-diagnostic-input/v1','binding_text':'{}','responses':None},
                {'schema':'personal-linked-diagnostic-input/v1','binding_text':'{}','responses':None,'owner_approved':True}]
        for value in values:
            with self.subTest(value=value),patch.object(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(value).encode()))),patch.object(m.s,'absolute_directory',side_effect=AssertionError('root entered')):
                output=io.StringIO()
                with redirect_stdout(output):code=m.main(['inspect','--binding-sha256','0'*64])
                self.assertEqual(code,2)

    def test_binding_failure_preserves_no_partial_diagnostic_claims(self):
        with fixture() as (primary,scope,tool,git):
            linked(primary,scope,git);authority=m.p.Authority();raw,digest=encoded(scope,tool)
            result=m.inspect(scope,tool,raw,'0'*64,authority,m.p.Responses(None,scope.repositories,authority))
            self.assertFalse(result['available']);self.assertTrue(result['partial_component_results_invalidated']);self.assertNotIn('components',result)

    def test_CLI_exit_codes_distinguish_violation_unknown_and_available(self):
        for kind,expected in (('available',0),('unknown',2),('violation-with-unknown',1)):
            with self.subTest(kind=kind),fixture() as (primary,scope,tool,git):
                target,entry=linked(primary,scope,git);active(primary)
                if kind=='unknown':git('config','core.hooksPath','/outside/not-read')
                if kind=='violation-with-unknown':(target/'agent-learnings.md').write_text('synthetic generated\n');commit(target)
                raw,digest=encoded(scope,tool)
                envelope={'schema':'personal-linked-diagnostic-input/v1','binding_text':raw.decode(),'responses':None}
                output=io.StringIO()
                with patch.object(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(envelope).encode()))),redirect_stdout(output):
                    code=m.main(['inspect','--binding-sha256',digest])
                self.assertEqual(code,expected,output.getvalue())
                result=json.loads(output.getvalue());self.assertFalse(result['actual_owner_additional_root_acceptance_or_full_doctor_or_native_acceptance'])


if __name__=='__main__':unittest.main()
