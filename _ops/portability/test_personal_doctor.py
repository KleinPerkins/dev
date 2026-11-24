"""Disposable caller composition, final fences and explicit unknown fixtures."""
from contextlib import redirect_stdout
import copy
import fcntl
import io
import json
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_doctor as m
from test_personal_git import FIXTURE_FLAGS, fixture, qualified_fixture_tool
from test_personal_controls import active
from test_personal_baseline import complete as baseline_complete
from test_personal_documentation import complete as documentation_complete,PLAN,write
from test_personal_profile import controls as profile_controls,raw_responses,NOW
from test_personal_linked_registry import linked
from test_personal_linked_worktree import encoded
from test_personal_remote import envelope as remote_envelope,row as remote_row,metadata as remote_metadata
from test_personal_remote import fleet_evidence,FixtureCompiler

REPO='KleinPerkins/skills'


def envelope(responses=None,receipts=True,bindings=None,remote=None):
    return {'schema':'personal-doctor-input/v1','responses':responses,'legacy_receipts':{
        'schema':'personal-doc-receipt-observations/v1','repositories':[{'repository':REPO,'namespace':'skills','files':[]}]} if receipts else None,
        'linked':bindings or [],'remote':remote}


def diagnose(scope,tool,raw=None,authority=None,remote=False):
    authority=authority or m.p.Authority();inputs=m.Inputs(raw,scope.repositories,authority,now=NOW,remote_enabled=remote)
    return m.inspect(scope,tool,authority,m.doc.Authority(),inputs)


def commit(git):git('add','-A');git('commit','--allow-empty','-m','synthetic doctor fixture')


class Primary(unittest.TestCase):
    def test_created_checkout_refuses_invalid_selectors_before_checkout_access(self):
        import personal_scaffold as creator

        cases = {
            'invalid': 'select the exact KleinPerkins repository name',
            'Other/example': 'select the exact KleinPerkins repository name',
            'KleinPerkins/': 'expected a new personal product name',
            'KleinPerkins/../example': 'expected a new personal product name',
        }
        with patch.object(creator, 'owner_location', side_effect=AssertionError('unexpected checkout access')):
            for repository, reason in cases.items():
                with self.subTest(repository=repository), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(m.main(['inspect-created', '--repository', repository]), 2)
                    self.assertEqual(json.loads(output.getvalue()), {'status': 'refused', 'reason': reason})

    def test_new_personal_checkout_is_bound_to_the_creator_and_reports_real_local_state(self):
        source = Path(__file__).resolve().parents[2]
        name = 'sample.created-doctor'
        with tempfile.TemporaryDirectory(dir='/tmp') as raw, qualified_fixture_tool(), patch.object(m.g, 'FLAGS', FIXTURE_FLAGS):
            root = Path(raw).resolve()
            parent = root / 'personal/src/KleinPerkins'
            parent.mkdir(parents=True)
            checkout = parent / name
            env = {**os.environ, 'DEV_SESSION_ID': 'created-doctor-' + root.name,
                   'XDG_STATE_HOME': str(root / 'state'), 'GIT_CONFIG_GLOBAL': '/dev/null',
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ALLOW_PROTOCOL': 'file'}
            subprocess.run(['bash', str(source / '_ops/bin/dev-new-repo.sh'), '--personal-codex',
                            name, '--fixture-root', str(root)], cwd=parent, env=env,
                           capture_output=True, check=True)

            def git(*args):
                return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=checkout, env=env)

            def inspect(code=0):
                image = lambda: (git('rev-parse', 'HEAD'), git('for-each-ref'), git('status', '--porcelain', '-z'),
                                 (checkout / '.git/index').read_bytes(), (checkout / '.git/config').read_bytes(),
                                 (checkout / '.git/doc-warden-new-repo.json').read_bytes())
                before = image()
                with redirect_stdout(io.StringIO()) as output:
                    actual = m.main(['inspect-created', '--repository', 'KleinPerkins/' + name,
                                     '--fixture-root', str(root)])
                result = json.loads(output.getvalue())
                self.assertEqual(actual, code, result)
                self.assertEqual(image(), before)
                return result

            clean = inspect()
            self.assertEqual(clean['head'], git('rev-parse', 'HEAD').decode().strip())
            self.assertEqual(clean['branch'], 'main')
            self.assertEqual(clean['local_git_verdict'], 'OK')
            self.assertEqual(clean['linked_registrations'], 0)
            self.assertIsNone(clean['recorded_repository_id'])
            self.assertFalse(clean['hosted_identity_verified'])
            self.assertIsNone(clean['upstream'])
            checkout_fd = os.open(checkout, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(checkout_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(inspect(2), {'status': 'refused', 'reason': 'the selected checkout is busy'})
            finally:
                os.close(checkout_fd)
            receipt = checkout / '.git/doc-warden-new-repo.json'
            saved = receipt.read_bytes()
            receipt.write_bytes(b'{')
            self.assertEqual(inspect(2), {'status': 'refused', 'reason': 'the creation record is unreadable'})
            receipt.write_bytes(saved)
            with (checkout / 'README.md').open('a') as stream:
                stream.write('\nfixture change\n')
            self.assertEqual(inspect()['codes'], {' M': 1})
            git('add', 'README.md')
            self.assertEqual(inspect()['codes'], {'M ': 1})
            git('config', '--local', 'user.email', 'different@example.invalid')
            self.assertEqual(inspect(1)['local_git_verdict'], 'VIOLATION')
            original = root / 'original'
            checkout.rename(original)
            shutil.copytree(original, checkout, symlinks=True)
            self.assertEqual(inspect(2)['status'], 'refused')

    def test_detached_primary_preserves_all_exclusions_and_known_hook_advisory(self):
        with fixture() as (root,scope,tool,git):
            git('switch','--detach');result=diagnose(scope,tool);self.assertTrue(result['available'],result)
            row=result['primary_rows'][0];parts=row['components']
            self.assertEqual(row['verdict'],'ADVISORY');self.assertTrue(parts['status']['detached'])
            self.assertEqual(parts['baseline']['observation']['baseline_eligibility']['reason'],'detached-HEAD')
            self.assertEqual(parts['documentation']['classification'],'NOT_APPLICABLE')
            self.assertFalse(parts['documentation']['documentation_bodies_read'])
            self.assertEqual(parts['controls']['observation']['hooks']['canonical_guard_state'],'missing')
            self.assertFalse(result['formal_migration_complete']);self.assertFalse(result['source_and_native_owner_acceptance'])

    def test_complete_eligible_baseline_profile_and_structural_components(self):
        with fixture() as (root,scope,tool,git):
            authority=m.p.Authority();baseline_complete(root);documentation_complete(root);active(root)
            profile_controls(root,authority);commit(git)
            result=diagnose(scope,tool,envelope(raw_responses(authority)),authority)
            row=result['primary_rows'][0];self.assertTrue(result['available'],result)
            self.assertEqual(row['components']['baseline']['observation']['baseline_compliance'],'COMPLIANT')
            self.assertEqual(row['components']['profile']['local']['version'],'pr-automation/v3')
            self.assertEqual(row['components']['documentation']['classification'],'CONFORMANT')
            self.assertIn('incompatible',row['components']['profile']['legacy_doctor_compatibility_result'])
            self.assertFalse(row['components']['profile']['operator_full_visibility_attested'])

    def test_unknown_legacy_receipts_do_not_erase_identity_violation(self):
        with fixture() as (root,scope,tool,git):
            documentation_complete(root);write(root,'docs/plans/synthetic-v1.md',PLAN);commit(git)
            git('config','user.email','synthetic-wrong@example.invalid')
            result=diagnose(scope,tool,envelope(receipts=False));row=result['primary_rows'][0]
            self.assertEqual(result['verdict'],'VIOLATION');self.assertFalse(result['available'])
            self.assertEqual(row['components']['documentation']['classification'],'UNAVAILABLE')
            self.assertEqual(row['components']['identity']['verdict'],'VIOLATION')
            self.assertNotIn('synthetic-wrong',json.dumps(result))

    def test_documentation_contradiction_is_outside_repository_verdict(self):
        with fixture() as (root,scope,tool,git):
            authority=m.p.Authority();documentation_complete(root);active(root)
            write(root,'AGENTS.md','<!-- doc-warden:begin -->\n<!-- doc-warden:begin -->\n<!-- doc-warden:end -->\n');commit(git)
            responses=raw_responses(authority)
            allowed={m.p.urls(REPO,authority)[key] for key in ('metadata','review')}
            responses['requests']=[r for r in responses['requests'] if r['url'] in allowed]
            result=diagnose(scope,tool,envelope(responses),authority)
            row=result['primary_rows'][0];self.assertTrue(result['available'],result)
            self.assertEqual(row['components']['documentation']['classification'],'CONTRADICTORY')
            self.assertNotEqual(result['verdict'],'VIOLATION')
            self.assertTrue(result['documentation_is_advisory_outside_repository_verdict'])

    def test_dirty_tree_status_and_baseline_skip_remain_visible(self):
        with fixture() as (root,scope,tool,git):
            write(root,'fixture.txt','uncommitted synthetic bytes')
            result=diagnose(scope,tool);parts=result['primary_rows'][0]['components']
            self.assertEqual(parts['status']['notes'],['uncommitted-changes'])
            self.assertEqual(parts['baseline']['observation']['baseline_eligibility']['reason'],'dirty-working-tree')
            self.assertEqual(parts['documentation']['reason'],'dirty-working-tree')

    def test_tracked_memory_is_violation_without_body_read(self):
        with fixture() as (root,scope,tool,git):
            write(root,'agent-learnings.md','PRIVATE_SYNTHETIC_MEMORY');commit(git)
            original=m.s.read_regular
            def guarded(parent,name,*args,**kw):
                if name=='agent-learnings.md':raise AssertionError('generated memory read')
                return original(parent,name,*args,**kw)
            with patch.object(m.s,'read_regular',guarded):result=diagnose(scope,tool)
            self.assertEqual(result['verdict'],'VIOLATION',result)
            self.assertNotIn('PRIVATE_SYNTHETIC_MEMORY',json.dumps(result))

    def test_unproven_dynamic_response_invalidates_profile_only(self):
        with fixture() as (root,scope,tool,git):
            authority=m.p.Authority();git('switch','--detach');git('config','user.email','synthetic-wrong@example.invalid')
            raw={'schema':'personal-profile-responses/v1','observed_at':NOW.isoformat(),'requests':[{
                'url':'https://api.github.com/repos/'+REPO+'/git/trees/'+'a'*40,'outcome':'ok','data':{'PRIVATE_UNPROVEN':'not emitted'}}]}
            result=diagnose(scope,tool,envelope(raw),authority)
            self.assertFalse(result['profile_response_protocol_accepted']);self.assertEqual(result['verdict'],'VIOLATION')
            self.assertEqual(result['primary_rows'][0]['components']['profile']['reason'],'doctor-unproven-profile-response-held')
            self.assertNotIn('PRIVATE_UNPROVEN',json.dumps(result))


class Linked(unittest.TestCase):
    def test_registry_candidate_stays_visible_and_unopened_without_binding(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);git('switch','--detach')
            with patch.object(m.l,'bound_checkout',side_effect=AssertionError('unapproved target opened')):result=diagnose(scope,tool)
            self.assertFalse(result['available']);self.assertEqual(result['linked_rows'],[])
            self.assertEqual(len(result['uninspected_linked_targets']),1)
            self.assertFalse(result['uninspected_linked_targets'][0]['target_counted_clean'])

    def test_exact_disposable_binding_joins_linked_own_status_and_controls(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);git('switch','--detach');raw,digest=encoded(scope,tool)
            result=diagnose(scope,tool,envelope(bindings=[{'binding_text':raw.decode(),'binding_sha256':digest,'responses':None}]))
            self.assertTrue(result['available'],result);self.assertEqual(result['uninspected_linked_targets'],[])
            self.assertEqual(len(result['linked_rows']),1)
            self.assertEqual(result['linked_rows'][0]['components']['documentation']['classification'],'NOT_APPLICABLE')
            self.assertTrue(result['connector_data_or_binding_hash_grants_no_auth_or_human_decision'])

    def test_duplicate_or_modified_binding_refused_before_root_open(self):
        with fixture() as (root,scope,tool,git):
            target,entry=linked(root,scope,git);raw,digest=encoded(scope,tool);authority=m.p.Authority()
            entry={'binding_text':raw.decode(),'binding_sha256':digest,'responses':None}
            with patch.object(m.l,'bound_checkout',side_effect=AssertionError('target opened')):
                with self.assertRaises(m.g.Refusal):m.Inputs(envelope(bindings=[entry,entry]),scope.repositories,authority,now=NOW)
                entry['binding_text']+=' '
                with self.assertRaises(m.g.Refusal):m.Inputs(envelope(bindings=[entry]),scope.repositories,authority,now=NOW)

    def test_linked_own_dirty_status_and_lexical_hook_scope(self):
        for inside in (False,True):
            with self.subTest(inside=inside),fixture() as (root,scope,tool,git):
                if inside:
                    target=scope.home/'dev/personal/synthetic-caller';target.parent.mkdir(parents=True)
                    git('worktree','add','--detach',str(target),'HEAD')
                else:target,_=linked(root,scope,git)
                git('switch','--detach');(target/'fixture.txt').write_text('own linked uncommitted bytes')
                raw,digest=encoded(scope,tool)
                result=diagnose(scope,tool,envelope(bindings=[{'binding_text':raw.decode(),'binding_sha256':digest,'responses':None}]))
                self.assertTrue(result['available'],result)
                self.assertTrue(result['primary_rows'][0]['components']['status']['clean_under_personal_policy'])
                parts=result['linked_rows'][0]['components']
                self.assertEqual(parts['status']['notes'],['uncommitted-changes'])
                self.assertEqual(parts['placement']['class'],'pers' if inside else 'repo')
                self.assertEqual(parts['controls']['canonical_hook_scope_applicable'],inside)
                self.assertEqual(parts['controls']['observation']['hooks']['canonical_guard_state'],'missing')
                if not inside:
                    observed=parts['controls']['observation']
                    self.assertEqual(parts['controls']['verdict'],m.c.verdict(observed['memory']['verdict'],observed['agents']['verdict']))

    def test_failed_attempt_and_partial_inspection_remain_distinct_from_unopened(self):
        for partial in (False,True):
            with self.subTest(partial=partial),fixture() as (root,scope,tool,git):
                linked(root,scope,git);git('switch','--detach');raw,digest=encoded(scope,tool)
                value={'available':False,'verdict':'ADVISORY'}
                if partial:value['components']={'identity':{'available':True,'verdict':'OK'},'baseline':m.unavailable('synthetic-baseline-held')}
                with patch.object(m.d,'inspect',return_value=value):
                    result=diagnose(scope,tool,envelope(bindings=[{'binding_text':raw.decode(),'binding_sha256':digest,'responses':None}]))
                unresolved=result['uninspected_linked_targets'][0]
                self.assertEqual(unresolved['status'],'partially-inspected-unavailable' if partial else 'inspection-attempt-unavailable')
                self.assertTrue(unresolved['target_access_attempted']);self.assertFalse(unresolved['target_counted_clean'])


class RemoteComposition(unittest.TestCase):
    def fleet(self,classification='MATCH',available=True):
        return {'available':available,'classification':classification,'operator_full_visibility_attested':False}

    def named_tracking(self,root,git):
        initial=git('rev-parse','HEAD').decode();git('update-ref','refs/remotes/origin/main',initial)
        git('switch','-c','synthetic-seeds');git('config','branch.synthetic-seeds.remote','origin')
        git('config','branch.synthetic-seeds.merge','refs/heads/main')
        (root/'fixture.txt').write_text('new synthetic commit');commit(git)
        return git('rev-parse','HEAD').decode()

    def snapshot(self,head):
        prefix=m.remote.base(REPO)
        return remote_envelope([remote_row(prefix,remote_metadata()),remote_row(prefix+'/branches/synthetic-seeds',
            {'name':'synthetic-seeds','commit':{'sha':head}})])

    def test_live_equal_and_different_replace_stale_local_tracking_label(self):
        for equal in (True,False):
            with self.subTest(equal=equal),fixture() as (root,scope,tool,git):
                head=self.named_tracking(root,git)
                with patch.object(m.remote,'fleet_row',return_value=self.fleet()):
                    result=diagnose(scope,tool,envelope(remote=self.snapshot(head if equal else 'e'*40)),remote=True)
                self.assertTrue(result['available'],result);parts=result['primary_rows'][0]['components'];status=parts['status']
                self.assertEqual(status['ahead'],1);self.assertTrue(status['local_tracking_unpushed_work_advisory'])
                self.assertEqual(status['canonical_sync_label'],'0/0' if equal else 'live≠')
                self.assertNotIn('out-of-sync-local-tracking',status['notes'])
                self.assertEqual('remote-branch-tip-differs' in status['notes'],not equal)
                self.assertEqual(status['unpushed_work_advisory'],not equal)
                self.assertEqual(parts['remote_sync']['observation']['classification'],'EQUAL' if equal else 'DIFFERENT')

    def test_full_staged_fleet_composes_with_sync_and_requires_qualified_compiler(self):
        for qualified_fixture in (False,True):
            with self.subTest(qualified_fixture=qualified_fixture),fixture() as (root,scope,tool,git):
                authority=m.p.Authority();head=self.named_tracking(root,git);snapshot=fleet_evidence(authority)
                snapshot['requests'].append(self.snapshot(head)['requests'][1])
                # Only this explicit test double substitutes for Rust. Real
                # qualification is deliberately not inferred from this fixture.
                if qualified_fixture:
                    with patch.object(m.remote,'QualifiedCompiler',FixtureCompiler):
                        result=diagnose(scope,tool,envelope(remote=snapshot),authority,remote=True)
                else:result=diagnose(scope,tool,envelope(remote=snapshot),authority,remote=True)
                parts=result['primary_rows'][0]['components'];fleet=parts['fleet']
                self.assertTrue(result['remote_observation_protocol_accepted'],result)
                self.assertEqual(parts['remote_sync']['observation']['classification'],'EQUAL')
                self.assertEqual(fleet['control_parity'],'MATCH');self.assertEqual(fleet['policy_digest_parity'],'MATCH')
                self.assertEqual(fleet['lock_currency'],'CURRENT' if qualified_fixture else 'UNAVAILABLE')
                self.assertEqual(result['available'],qualified_fixture)
                self.assertFalse(fleet['operator_full_visibility_attested'])

    def test_unavailable_remote_falls_back_to_local_tracking_and_stays_unknown(self):
        with fixture() as (root,scope,tool,git):
            self.named_tracking(root,git)
            with patch.object(m.remote,'fleet_row',return_value=self.fleet()):result=diagnose(scope,tool,envelope(),remote=True)
            self.assertFalse(result['available']);parts=result['primary_rows'][0]['components']
            self.assertIn('out-of-sync-local-tracking',parts['status']['notes'])
            self.assertTrue(parts['status']['unpushed_work_advisory']);self.assertFalse(parts['remote_sync']['available'])
            self.assertEqual(result['requests'][0]['method'],'GET')

    def test_fleet_drift_is_advisory_and_unavailable_fleet_does_not_become_healthy(self):
        for classification,available in (('DRIFT',True),('UNAVAILABLE',False)):
            with self.subTest(classification=classification),fixture() as (root,scope,tool,git):
                git('switch','--detach');offline=diagnose(scope,tool)
                with patch.object(m.remote,'fleet_row',return_value=self.fleet(classification,available)):
                    result=diagnose(scope,tool,envelope(),remote=True)
                self.assertEqual(result['verdict'],offline['verdict']);self.assertEqual(result['available'],available)
                self.assertEqual(result['primary_rows'][0]['components']['fleet']['classification'],classification)
                self.assertEqual(m.summary(result)['fleet_classifications'],{classification:1})

    def test_origin_refusal_precedes_all_remote_reads(self):
        with fixture() as (root,scope,tool,git):
            git('remote','set-url','origin','git@github.com:Excluded/work.git')
            with patch.object(m.remote.Observations,'read',side_effect=AssertionError('remote read after origin refusal')):
                result=diagnose(scope,tool,envelope(),remote=True)
            self.assertFalse(result['available']);self.assertEqual(result['requests'],[])

    def test_unproven_remote_input_preserves_independent_identity_violation(self):
        with fixture() as (root,scope,tool,git):
            git('switch','--detach');git('config','user.email','synthetic-wrong@example.invalid')
            remote=remote_envelope([remote_row(m.remote.base(REPO)+'/git/trees/'+'d'*40,{'PRIVATE_UNPROVEN':'not emitted'})])
            with patch.object(m.remote,'fleet_row',return_value=self.fleet()):result=diagnose(scope,tool,envelope(remote=remote),remote=True)
            self.assertFalse(result['remote_observation_protocol_accepted']);self.assertEqual(result['verdict'],'VIOLATION')
            self.assertFalse(result['available']);self.assertNotIn('PRIVATE_UNPROVEN',json.dumps(result))
            self.assertEqual(result['primary_rows'][0]['components']['identity']['verdict'],'VIOLATION')

    def test_invalid_remote_input_cannot_restore_late_invalidated_status(self):
        with fixture() as (root,scope,tool,git):
            git('switch','--detach');value=diagnose(scope,tool)['primary_rows'][0]
            value['_local_status_before_remote']=copy.deepcopy(value['components']['status'])
            value['components']['status']=m.unavailable('doctor-final-worktree-status-changed');value['available']=False
            remote=remote_envelope([remote_row(m.remote.base(REPO)+'/git/trees/'+'d'*40,{})])
            with patch.object(m,'primary',return_value=value):result=diagnose(scope,tool,envelope(remote=remote),remote=True)
            self.assertEqual(result['primary_rows'][0]['components']['status']['reason'],'doctor-final-worktree-status-changed')
            self.assertFalse(result['available'])

    def test_nonremote_mode_refuses_remote_data_before_scope(self):
        with patch.object(m.s,'PersonalScope',side_effect=AssertionError('root opened')):
            with self.assertRaises(m.g.Refusal):m.Inputs(envelope(remote=remote_envelope()),[REPO],m.p.Authority(),now=NOW)


class FinalFencesAndCLI(unittest.TestCase):
    def test_quiet_summary_and_complete_unknown_violation_exit_semantics(self):
        for unknown,violation,expected in ((False,False,0),(True,False,2),(True,True,1)):
            with self.subTest(unknown=unknown,violation=violation),fixture() as (root,scope,tool,git):
                git('switch','--detach')
                if violation:git('config','user.email','synthetic-wrong@example.invalid')
                result=diagnose(scope,tool)
                if unknown:
                    result['available']=False;result['primary_rows'][0]['available']=False
                    result['primary_rows'][0]['linked_registry']={'available':False,'candidates':None}
                out=io.StringIO()
                with redirect_stdout(out),patch.object(m.g,'GitTool',return_value=tool),patch.object(m,'inspect',return_value=result):
                    self.assertEqual(m.main(['inspect','--repository',REPO,'--quiet']),expected)
                value=json.loads(out.getvalue());self.assertEqual(value['primary_count'],1)
                self.assertEqual(value['schema'],'personal-portability/personal-doctor-summary/v1')
                self.assertEqual(value['available'],not unknown);self.assertFalse(value['formal_migration_complete'])
                if unknown:self.assertEqual(value['unavailable_components'][0]['component'],'linked_registry')

    def test_late_hook_and_ignored_documentation_changes_invalidate_component(self):
        for mode in ('hook','documentation'):
            with self.subTest(mode=mode),fixture() as (root,scope,tool,git):
                authority=m.p.Authority();documentation_complete(root);active(root)
                write(root,'.gitignore','docs/\n');commit(git)
                original=m.doc.inspect_repository;calls=0
                def late(*args,**kw):
                    nonlocal calls
                    value=original(*args,**kw);calls+=1
                    if calls==1:
                        write(root,'.git/hooks/pre-commit' if mode=='hook' else 'docs/plans/README.md','late changed synthetic bytes')
                    return value
                with patch.object(m.doc,'inspect_repository',late):result=diagnose(scope,tool,envelope(raw_responses(authority)),authority)
                row=result['primary_rows'][0];component='controls' if mode=='hook' else 'documentation'
                self.assertFalse(row['components'][component]['available'],row)

    def test_config_change_between_components_invalidates_joined_row(self):
        with fixture() as (root,scope,tool,git):
            original=m.c.PersonalControls.observe
            def changed(check):
                value=original(check);git('config','user.email','synthetic-new@example.invalid');return value
            with patch.object(m.c.PersonalControls,'observe',changed):result=diagnose(scope,tool)
            row=result['primary_rows'][0];self.assertFalse(row['available'])
            self.assertEqual(row['reason'],'doctor-primary-boundary-unavailable')

    def test_source_bytes_indexes_and_objects_preserved(self):
        with fixture() as (root,scope,tool,git):
            git('switch','--detach')
            def facts():return {str(p.relative_to(root)):{**m.w.fact(p.lstat()),'sha':m.g.sha(p.read_bytes())} for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
            before=facts();result=diagnose(scope,tool);self.assertTrue(result['available'],result)
            self.assertEqual(before,facts())

    def test_input_refuses_before_scope_and_cli_violation_exit(self):
        with fixture() as (root,scope,tool,git):
            out=io.StringIO()
            with redirect_stdout(out),patch.object(m.sys,'stdin',io.TextIOWrapper(io.BytesIO(b'{}'))),patch.object(m.s,'PersonalScope',side_effect=AssertionError('root opened')):
                self.assertEqual(m.main(['inspect','--repository',REPO,'--input-stdin']),2)
            git('switch','--detach');git('config','user.email','synthetic-wrong@example.invalid');out=io.StringIO()
            with redirect_stdout(out),patch.object(m.g,'GitTool',return_value=tool):self.assertEqual(m.main(['inspect','--repository',REPO]),1)
            self.assertEqual(json.loads(out.getvalue())['verdict'],'VIOLATION')


class PersonalCodexDoctorTests(unittest.TestCase):
    def test_link_is_repeatable_and_preserves_occupied_slots(self):
        ops = Path(__file__).resolve().parents[1]
        source = ops / 'skills/personal/dev-doctor'
        helper = ops / 'bin/link-personal-codex-skill.py'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slot = root / 'skills/dev-doctor'
            command = [sys.executable, '-I', '-B', str(helper), str(source), str(slot)]
            subprocess.run(command, capture_output=True, check=True)
            self.assertEqual(os.readlink(slot), str(source))
            inode = slot.lstat().st_ino
            subprocess.run(command, capture_output=True, check=True)
            self.assertEqual(slot.lstat().st_ino, inode)
            slot.rename(root / 'saved-link')
            slot.symlink_to(root / 'foreign')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(os.readlink(slot), str(root / 'foreign'))
            slot.unlink()
            slot.mkdir()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertTrue(slot.is_dir())

    def test_refuses_unselected_held_retired_or_outside_ids_before_opening(self):
        selections = [
            [], ['KleinPerkins/server-guard'], ['KleinPerkins/pr-automation-controller'],
            ['KleinPerkins/sterling'], ['KleinPerkins/chaos-labs'], ['KleinPerkins/cpp'],
            [REPO, 'KleinPerkins/server-guard'],
        ]
        for repositories in selections:
            with self.subTest(repositories=repositories), redirect_stdout(io.StringIO()), \
                    patch.object(m.p, 'Authority', side_effect=AssertionError('owner state opened')):
                args = ['inspect-codex']
                for repository in repositories:
                    args.extend(['--repository', repository])
                self.assertEqual(m.main(args), 2)

    def test_known_identity_violation_uses_the_existing_owner_diagnosis(self):
        with fixture() as (root, scope, tool, git):
            git('config', 'user.email', 'synthetic-wrong@example.invalid')
            output = io.StringIO()
            with redirect_stdout(output), patch.object(m.g, 'GitTool', return_value=tool):
                self.assertEqual(m.main(['inspect-codex', '--repository', REPO, '--quiet']), 1)
            self.assertEqual(json.loads(output.getvalue())['verdict'], 'VIOLATION')


if __name__=='__main__':unittest.main()
