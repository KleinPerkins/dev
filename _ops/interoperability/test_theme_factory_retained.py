"""Owned disposable lifecycle and real synthetic-process cases; no native launch."""
from argparse import Namespace
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import uuid

import theme_factory_retained as r
from test_theme_factory_canary import transaction


def process_proof(action):
    value={'schema':'interoperability/theme-factory-catalog-process/v1','action_sha256':action,
        'success':True,'duration_ms':1,'exit_code':0,'methods':list(r.native.PROTOCOL['methods']),
        'exclusive_child_custody_lost':False,'new_model_workers_conversation_threads_or_token_refresh_methods':0}
    for k in ('original_child_reaped','actual_stdout_EOF','actual_stderr_EOF','process_group_absent_at_observation',
        'strict_actual_hard_deadline_passed','actual_HOME_CODEX_HOME_preserved','OS_network_and_fork_denied',
        'original_birth_captured_before_parent_signal_restore','single_main_thread_owner'):value[k]=True
    return value


def synthetic_catalog(plan):
    op=Path(plan['operation_dir'])/('catalog-'+str(uuid.uuid4()));op.mkdir(mode=0o700)
    proof=process_proof(plan['action_sha256']);p=op/'process-result.json'
    r.core.atom.write_once(p,proof)
    return {'identity':{'name':'theme-factory','enabled':True,'link_path':str(Path(plan['target'])/'SKILL.md'),
            'canonical_source_path':str(Path(plan['desired'])/'SKILL.md'),'same_file_verified':True},
        'process_record':str(p),'process_record_sha256':r.core.sha(r.core.regular(p))}


@contextmanager
def fixture():
    with transaction() as f:
        (f.home/'Codex').mkdir()
        f.args.native_evidence=f.root/'native.json';f.args.operation='apply'
        proof={'local_path':str(f.args.native_evidence),'sha256':r.EVIDENCE_SHA,'owner':'synthetic'}
        with patch.object(r,'evidence',side_effect=lambda _:copy.deepcopy(proof)), \
             patch.object(r.native,'cli_proof',return_value={'path':'synthetic','sha256':r.native.CLI_SHA}), \
             patch.object(r,'catalog',side_effect=synthetic_catalog) as catalog:
            f.evidence=proof;f.catalog=catalog;yield f


def prepare(f):
    result=r.preview(f.args);f.args.approve=result['action_sha256'];return r.load(f.args.operation_dir)


class Retained(unittest.TestCase):
    def test_lifecycle_has_one_total_native_attempt_and_preserves_inner_canary(self):
        with fixture() as f:
            original=r.core.preserved(f.home);plan=prepare(f)
            self.assertNotEqual(plan['action_sha256'],plan['core_action_sha256'])
            self.assertFalse(r.core.load(f.args.operation_dir/'transaction')['retention_authorized'])
            self.assertEqual(r.execute(f.args)['status'],'applied-retained')
            receipt=(f.args.operation_dir/'retained.json').read_bytes()
            self.assertEqual(r.execute(f.args)['status'],'already-retained')
            f.args.operation='verify';self.assertEqual(r.execute(f.args)['status'],'verified-retained')
            self.assertEqual((f.args.operation_dir/'retained.json').read_bytes(),receipt)
            f.catalog.assert_called_once()
            f.args.operation='rollback';self.assertEqual(r.execute(f.args)['status'],'rolled-back')
            self.assertEqual(r.core.preserved(f.home),original)
            f.args.operation='verify';self.assertEqual(r.execute(f.args)['status'],'verified-preimage')
            f.args.operation='apply'
            with self.assertRaises(ValueError):r.execute(f.args)
            f.catalog.assert_called_once()

    def test_preview_and_preimage_verify_start_no_catalog(self):
        with fixture() as f:
            prepare(f);f.args.operation='verify'
            self.assertFalse(r.execute(f.args)['retention_applied']);f.catalog.assert_not_called()

    def test_inner_or_wrong_digest_never_approves_retention(self):
        for kind in ('inner','wrong'):
            with self.subTest(kind=kind),fixture() as f:
                p=prepare(f);f.args.approve=p['core_action_sha256'] if kind=='inner' else '0'*64
                with self.assertRaisesRegex(ValueError,'separate exact'):r.execute(f.args)
                self.assertFalse(os.path.lexists(f.target));f.catalog.assert_not_called()

    def test_native_failure_rolls_back_and_never_replays_attempt(self):
        with fixture() as f:
            before=r.core.preserved(f.home);prepare(f);f.catalog.side_effect=ValueError('synthetic failure')
            with self.assertRaisesRegex(ValueError,'exact link rollback verified'):r.execute(f.args)
            self.assertFalse(os.path.lexists(f.target));self.assertEqual(r.core.preserved(f.home),before)
            with self.assertRaises(ValueError):r.execute(f.args)
            f.catalog.assert_called_once()

    def test_lost_retained_target_is_not_recreated_or_reported_retained(self):
        for operation in ('apply','verify'):
            with self.subTest(operation=operation),fixture() as f:
                prepare(f);r.execute(f.args);f.target.unlink();f.args.operation=operation
                with self.assertRaisesRegex(ValueError,'missing'):r.execute(f.args)
                self.assertFalse(os.path.lexists(f.target));f.catalog.assert_called_once()

    def test_lost_receipt_holds_existing_link_without_new_catalog(self):
        with fixture() as f:
            prepare(f);r.execute(f.args);inode=f.target.lstat().st_ino
            (f.args.operation_dir/'retained.json').unlink()
            with self.assertRaisesRegex(ValueError,'allowance already consumed'):r.execute(f.args)
            self.assertEqual(f.target.lstat().st_ino,inode);f.catalog.assert_called_once()

    def test_preexisting_attempt_holds_before_publication_or_second_process(self):
        with fixture() as f:
            plan=prepare(f);r.core.atom.write_once(f.args.operation_dir/'native-attempt.json',{'action_sha256':plan['action_sha256'],'maximum_processes':1})
            for operation in ('apply','verify'):
                f.args.operation=operation
                with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'allowance already consumed'):r.execute(f.args)
            self.assertFalse(os.path.lexists(f.target));f.catalog.assert_not_called()

    def test_foreign_target_replacement_is_preserved_after_catalog_failure(self):
        for kind in ('file','same-source-link'):
            with self.subTest(kind=kind),fixture() as f:
                prepare(f)
                def replace(plan):
                    f.target.rename(f.root/'keep-owned')
                    if kind=='file':f.target.write_text('foreign')
                    else:f.target.symlink_to(f.source)
                    raise ValueError('native failure')
                f.catalog.side_effect=replace
                with self.assertRaisesRegex(ValueError,'foreign edits preserved'):r.execute(f.args)
                self.assertTrue(os.path.lexists(f.target))
                if kind=='file':self.assertEqual(f.target.read_text(),'foreign')
                else:self.assertNotEqual(f.target.lstat().st_ino,(f.root/'keep-owned').lstat().st_ino)

    def test_evidence_cli_source_policy_or_preserved_drift_holds_before_publication(self):
        for kind in ('evidence','cli','source','policy','preserved'):
            with self.subTest(kind=kind),fixture() as f:
                prepare(f)
                if kind=='evidence':f.evidence['owner']='drift'
                elif kind=='cli':r.native.cli_proof.return_value={'path':'changed'}
                elif kind=='source':f.proof['payload_sha256']='changed'
                elif kind=='policy':f.config.write_text('# changed\n')
                else:(f.home/'.cursor/skills/theme-factory').mkdir()
                with self.assertRaises(ValueError):r.execute(f.args)
                self.assertFalse(os.path.lexists(f.target));f.catalog.assert_not_called()

    def test_post_native_drift_rolls_back_without_replacing_owner_config(self):
        with fixture() as f:
            prepare(f)
            def drift(plan):
                result=synthetic_catalog(plan);f.config.write_text('# later owner config\n');return result
            f.catalog.side_effect=drift
            with self.assertRaisesRegex(ValueError,'exact recovery requires inspection'):r.execute(f.args)
            self.assertFalse(os.path.lexists(f.target));self.assertEqual(f.config.read_text(),'# later owner config\n')

    def test_receipt_write_failure_rolls_back(self):
        with fixture() as f:
            prepare(f);original=r.core.atom.write_once
            def fail(path,value):
                if path.name=='retained.json':raise OSError('synthetic disk full')
                return original(path,value)
            with patch.object(r.core.atom,'write_once',side_effect=fail):
                with self.assertRaisesRegex(ValueError,'exact link rollback verified'):r.execute(f.args)
            self.assertFalse(os.path.lexists(f.target))

    def test_native_receipt_drift_refuses_verification_without_new_process(self):
        with fixture() as f:
            prepare(f);out=r.execute(f.args);p=Path(out['native_catalog']['process_record']);p.write_text('{}')
            f.args.operation='verify'
            with self.assertRaisesRegex(ValueError,'process record changed'):r.execute(f.args)
            self.assertTrue(f.target.is_symlink());f.catalog.assert_called_once()

    def test_rollback_remains_available_without_evidence_or_cli(self):
        with fixture() as f:
            prepare(f);r.execute(f.args);f.args.operation='rollback'
            with patch.object(r,'evidence',side_effect=ValueError('gone')),patch.object(r.native,'cli_proof',side_effect=ValueError('gone')):
                self.assertEqual(r.execute(f.args)['status'],'rolled-back')
            self.assertFalse(os.path.lexists(f.target));f.catalog.assert_called_once()

    def test_foreign_targets_and_native_optouts_refuse_preview(self):
        for kind in ('foreign','optout'):
            with self.subTest(kind=kind),fixture() as f:
                if kind=='foreign':f.target.write_text('owner')
                else:f.config.write_text('[[skills.config]]\npath='+json.dumps(str(f.target))+'\nenabled=false\n')
                before=f.config.read_bytes()
                with self.assertRaises(ValueError):r.preview(f.args)
                self.assertEqual(f.config.read_bytes(),before);f.catalog.assert_not_called()

    def test_wrong_or_nonprivate_native_evidence_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()/'proof.json';p.write_text('{}');p.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'exact immutable'):r.evidence(p)
            p.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'private exact'):r.evidence(p)

    def test_exact_private_native_evidence_predicates_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()/'proof.json'
            value={'schema':'personal-portability/theme-factory-bounded-native-evidence-owner-acceptance/v1',
                'action_sha256':r.EVIDENCE_ACTION,'original_native_action':r.ORIGINAL_ACTION,
                'accepted_corrected_checker_source':r.CHECKER_REVISION,'actual_exact_owner_approval_received':True,
                'bounded_native_discovery_and_use_evidence_accepted':True,'retained_interface_or_installation_authorized':False,
                'original_refused_receipt_or_action_rewritten':False}
            for wrong in (None,'schema','actual_exact_owner_approval_received','retained_interface_or_installation_authorized'):
                with self.subTest(wrong=wrong):
                    d=copy.deepcopy(value)
                    if wrong=='schema':d[wrong]='unknown'
                    elif wrong:d[wrong]=not d[wrong]
                    raw=r.core.canonical(d);p.write_bytes(raw);p.chmod(0o600)
                    with patch.object(r,'EVIDENCE_SHA',hashlib.sha256(raw).hexdigest()):
                        if wrong:
                            with self.assertRaises(ValueError):r.evidence(p)
                        else:self.assertEqual(r.evidence(p)['state']['inode'],p.stat().st_ino)


class Identity(unittest.TestCase):
    def test_catalog_invocation_redirects_only_private_runtime_storage_and_preserves_environment(self):
        with fixture() as f:
            p=prepare(f);before={k:(k in os.environ,os.environ.get(k)) for k in ('HOME','CODEX_HOME')}
            with patch.object(r.native,'_exchange',return_value=({'data':[]},{'synthetic':True})) as exchange:
                r.native.run(p)
            command,operation,home,cwd,executables,action=exchange.call_args.args
            self.assertEqual(command[0],str(r.native.CLI));self.assertEqual(command[-2:],['app-server','--stdio'])
            self.assertEqual(command[1],'-c');self.assertEqual(command[3],'-c');self.assertEqual(len(command),7)
            settings={**tomllib.loads(command[2]),**tomllib.loads(command[4])}
            self.assertEqual(set(settings),{'sqlite_home','log_dir'})
            self.assertEqual(Path(settings['sqlite_home']),operation/'state')
            self.assertEqual(Path(settings['log_dir']),operation/'logs')
            self.assertEqual(home,f.home);self.assertEqual(cwd,f.home/'Codex');self.assertEqual(action,p['action_sha256'])
            self.assertEqual(before,{k:(k in os.environ,os.environ.get(k)) for k in before})

    def test_only_owned_literal_or_canonical_same_file_path_is_allowed(self):
        with fixture() as f:
            p=prepare(f);r.core.apply(Namespace(operation_dir=f.args.operation_dir/'transaction',approve=p['core_action_sha256']))
            alias=f.root/'alias';alias.symlink_to(f.source)
            for path in (f.target/'SKILL.md',f.source/'SKILL.md',alias/'SKILL.md'):
                response={'data':[{'cwd':p['native_cwd'],'skills':[{'name':'theme-factory','enabled':True,'path':str(path)}]}]}
                if path.parent==alias:
                    with self.assertRaises(ValueError):r._identity(p,response)
                else:self.assertTrue(r._identity(p,response)['same_file_verified'])

    def test_incomplete_disabled_duplicate_or_wrong_scope_refuses(self):
        with fixture() as f:
            p=prepare(f)
            for response in ({'data':[]},{'data':[None]},{'data':[{'cwd':'wrong'}]},
                {'data':[{'cwd':p['native_cwd'],'skills':[]}]},
                {'data':[{'cwd':p['native_cwd'],'skills':[{'name':'theme-factory','enabled':False}]}]}):
                with self.subTest(response=response),self.assertRaises(ValueError):r._identity(p,response)

    def test_every_native_custody_and_timing_gate_is_required(self):
        plan={'action_sha256':'a'*64};proof=process_proof(plan['action_sha256']);r.valid_process(plan,proof)
        for key in ('actual_stdout_EOF','actual_stderr_EOF','original_child_reaped','strict_actual_hard_deadline_passed',
                'process_group_absent_at_observation','actual_HOME_CODEX_HOME_preserved','original_birth_captured_before_parent_signal_restore'):
            value=copy.deepcopy(proof);value[key]=False
            with self.subTest(key=key),self.assertRaises(ValueError):r.valid_process(plan,value)


@unittest.skipUnless(sys.platform=='darwin','Darwin OS-fenced transport cases require separate actual Mac qualification')
class Transport(unittest.TestCase):
    def exchange(self,kind,interrupt=False,hard_boundary=False,lost_custody=False):
        with tempfile.TemporaryDirectory(prefix='theme-retained-transport-') as tmp:
            root=Path(tmp).resolve();operation=root/'catalog';cwd=root/'scope';cwd.mkdir()
            command=[sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/theme-factory-retained/catalog_peer.py'),kind,str(operation)]
            executables=[Path(sys.executable).resolve(),(Path(sys.prefix)/'Resources/Python.app/Contents/MacOS/Python').resolve()]
            limits={**r.native.PROTOCOL,'work_seconds':.35,'term_seconds':.5,'kill_seconds':.65,'hard_seconds':1.5}
            mask=r.native.signal.pthread_sigmask
            actual_wait=r.native.os.waitpid;actual_clock=r.native.time.monotonic
            origin=[];observed=[]
            def clock():
                current=actual_clock()
                if not origin:origin.append(current)
                return origin[0]+limits['hard_seconds'] if hard_boundary and observed else current
            def wait(pid,flags):
                result=actual_wait(pid,flags)
                if result[0]:
                    observed.append(result)
                    if lost_custody:raise ChildProcessError('controlled foreign reaper after actual exclusive terminal observation')
                return result
            original_read=r.native.os.read;diagnostic=[]
            def read_stream(fd,size):
                chunk=original_read(fd,size)
                if chunk and sum(map(len,diagnostic))<4096:diagnostic.append(chunk[:4096])
                return chunk
            def interrupted(how,signals):
                result=mask(how,signals)
                if how==signal.SIG_SETMASK:raise KeyboardInterrupt('synthetic deferred interruption')
                return result
            def preserve():
                selected=os.environ.get('THEME_RETAINED_TEST_EVIDENCE')
                if not selected:return
                target=Path(selected).resolve()
                if not target.is_relative_to(Path(os.environ['TMPDIR']).resolve()):raise ValueError('test evidence escaped private fixture storage')
                target.mkdir(mode=0o700,exist_ok=True)
                dest=target/(kind+'-'+str(uuid.uuid4()));dest.mkdir(mode=0o700)
                for name in ('catalog.sb','process-result.json','custody-observer.json'):
                    p=operation/name
                    if p.is_file():r.native.write_once(dest/name,p.read_bytes(),0o400)
            with patch.dict(r.native.PROTOCOL,limits),patch.object(r.native.signal,'pthread_sigmask',side_effect=interrupted if interrupt else mask),patch.object(r.native.os,'read',side_effect=read_stream),patch.object(r.native.os,'waitpid',side_effect=wait),patch.object(r.native.time,'monotonic',side_effect=clock):
                try:result=r.native._exchange(command,operation,Path(os.environ['HOME']),cwd,executables,'a'*64)
                except r.native.CatalogFailure as error:
                    if lost_custody:
                        self.assertEqual(len(observed),1);self.assertEqual(os.waitstatus_to_exitcode(observed[0][1]),0)
                        self.assertFalse(error.evidence['original_child_reaped']);self.assertTrue(error.evidence['exclusive_child_custody_lost'])
                        self.assertIsNone(error.evidence['exit_code']);self.assertFalse(error.evidence['success'])
                        self.assertEqual(error.evidence['signals_to_original_unreaped_child'],[])
                        self.assertEqual(len(r.native._OWNED_CHILDREN),1)
                        held=r.native._OWNED_CHILDREN[0];self.assertEqual(held.pid,observed[0][0])
                        with self.assertRaisesRegex(ValueError,'remains retained'):r.native._spawn_owned([],dict(os.environ))
                        r.native._OWNED_CHILDREN.remove(held)
                        r.native.write_once(operation/'custody-observer.json',r.core.canonical({
                            'schema':'theme-factory-test/controlled-exclusive-reaper/v1','original_birth_pid':held.pid,
                            'actual_original_status':0,'actual_exclusive_wait_completed':True,
                            'original_owner_refused_to_invent_status_or_signal_again':True,
                            'test_scope_retired_only_the_observed_terminal_handle':True})+b'\n')
                    else:self.assertTrue(error.evidence['original_child_reaped'])
                    preserve()
                    self.assertTrue(error.evidence['actual_stdout_EOF'] and error.evidence['actual_stderr_EOF'])
                    self.assertTrue(error.evidence['process_group_absent_at_observation'])
                    self.assertFalse(r.native._OWNED_CHILDREN)
                    # Only the exact synthetic peer can execute under the outer
                    # harness. Preserve its bounded diagnostic on a refusal.
                    raise r.native.CatalogFailure(str(error)+'; synthetic peer streams='+repr(b''.join(diagnostic)),error.evidence) from error
                preserve()
                self.assertFalse(r.native._OWNED_CHILDREN)
                self.assertEqual(result[1],json.loads((operation/'process-result.json').read_bytes()))
                return result

    def test_actual_synthetic_peer_proves_guards_EOF_and_exclusive_reap(self):
        response,proof=self.exchange('success')
        self.assertEqual(response,{'data':[]});self.assertTrue(proof['success'])
        self.assertTrue(proof['original_birth_captured_before_parent_signal_restore'])
        self.assertEqual(proof['methods'],r.native.PROTOCOL['methods'])
        self.assertEqual(proof['signals_to_original_unreaped_child'],[])

    def test_actual_partial_duplicate_unknown_nonzero_and_early_peers_refuse(self):
        for kind in ('partial','duplicate','unknown-id','nonzero','early'):
            with self.subTest(kind=kind):
                with self.assertRaises(r.native.CatalogFailure) as caught:self.exchange(kind)
                self.assertEqual(caught.exception.evidence['exit_code'],3 if kind=='nonzero' else 0)

    def test_actual_stderr_overflow_is_drained_and_refused(self):
        with self.assertRaisesRegex(r.native.CatalogFailure,'output exceeded'):self.exchange('stderr-overflow')

    def test_actual_work_deadline_keeps_and_reaps_original_peer(self):
        with self.assertRaisesRegex(r.native.CatalogFailure,'work deadline'):self.exchange('work-timeout')

    def test_actual_unresponsive_peer_requires_original_child_kill_and_reap(self):
        with self.assertRaises(r.native.CatalogFailure) as caught:self.exchange('ignore-eof')
        self.assertEqual(caught.exception.evidence['signals_to_original_unreaped_child'],['TERM','KILL'])
        self.assertEqual(caught.exception.evidence['exit_code'],-signal.SIGKILL)

    def test_actual_deferred_capture_interruption_retains_the_original_peer(self):
        with self.assertRaisesRegex(r.native.CatalogFailure,'interrupted during original-child capture') as caught:self.exchange('success',interrupt=True)
        self.assertEqual(caught.exception.evidence['exit_code'],0)

    def test_actual_terminal_peer_at_injected_exact_hard_boundary_refuses(self):
        with self.assertRaisesRegex(r.native.CatalogFailure,'actual hard deadline') as caught:self.exchange('success',hard_boundary=True)
        self.assertFalse(caught.exception.evidence['strict_actual_hard_deadline_passed'])
        self.assertFalse(caught.exception.evidence['success'])

    def test_actual_terminal_peer_with_controlled_foreign_reap_never_invents_status(self):
        with self.assertRaisesRegex(r.native.CatalogFailure,'exclusive child custody lost') as caught:self.exchange('success',lost_custody=True)
        self.assertIsNone(caught.exception.evidence['exit_code'])


if __name__=='__main__':unittest.main()
