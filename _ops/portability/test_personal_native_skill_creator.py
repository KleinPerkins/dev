"""Offline contract and refusal coverage; no native account or provider access."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import personal_native_skill_creator as owner

CONTEXT = {'expected_email': 'person@example.invalid', 'expected_workspace': '/Users/fixture/project',
           'expected_account_home': '/Users/fixture'}
EMPTY = hashlib.sha256(b'').hexdigest()


def observation():
    files = {name: {'sha256': digest, 'device': 1, 'inode': n + 1, 'uid': 501, 'mode': 0o644,
                    'mtime_ns': 1, 'ctime_ns': 1} for n, (name, digest) in enumerate(owner.PROVIDER.items())}
    steps = []
    for label, script, exit_code in owner.ROSTER:
        steps.append({'label': label, 'script': script, 'exit_code': exit_code, 'stdout_sha256':
                      hashlib.sha256(owner.REPORTS[label].encode()).hexdigest() if label in owner.REPORTS else EMPTY,
                      'stderr_sha256': EMPTY, 'elapsed_seconds': 0.01, 'process_terminal': True})
    return {'schema': owner.SCHEMA, 'host': copy.deepcopy(owner.HOST),
            'identity': {'type': 'chatgpt', 'email': CONTEXT['expected_email'], 'workspace_name': None},
            'workspace': CONTEXT['expected_workspace'],
            'catalog': {'complete_response': True, 'process_terminal': True, 'process_exit_code': 0,
                        'stderr_bytes': 404, 'extra_roots': [], 'token_refresh_requested': False,
                        'threads_or_turns_created': 0, 'model_workers_started': 0,
                        'plugin_installation_or_configuration_changes': False,
                        'requests': [
                            {'method': 'initialize', 'params': {'clientInfo': {'name': 'personal_skill_creator_readonly', 'version': '1.0'}, 'capabilities': {'experimentalApi': True}}},
                            {'method': 'initialized', 'params': {}},
                            {'method': 'account/read', 'params': {'refreshToken': False}},
                            {'method': 'skills/list', 'params': {'cwds': [CONTEXT['expected_workspace']], 'forceReload': True}}]},
            'provider': {'name': 'skill-creator', 'scope': 'system', 'enabled': True, 'plugin_id': None,
                         'path': CONTEXT['expected_account_home'] + '/.codex/skills/.system/skill-creator/SKILL.md',
                         'files_before': files, 'files_after': copy.deepcopy(files)},
            'runtime': copy.deepcopy(owner.RUNTIME),
            'functional': {'guards': {k: True for k in owner.GUARDS}, 'checks': {k: True for k in owner.CHECKS},
                           'steps': steps, 'total_elapsed_seconds': 1.0, 'validator_limit': owner.LIMIT},
            'evidence': {k: 'a' * 64 for k in ('native_catalog_sha256', 'private_runtime_record_sha256',
                         'functional_result_sha256', 'qualification_driver_sha256', 'fixture_inventory_sha256')},
            'safety': {k: 0 for k in owner.ZERO_EFFECTS}}


class NativeSkillCreationContract(unittest.TestCase):
    def reject(self, modify):
        value = observation()
        modify(value)
        with self.assertRaises(owner.ObservationError):
            owner.assess(value, **CONTEXT)

    def test_complete_record_is_private_and_grants_no_authority(self):
        value = observation()
        before = copy.deepcopy(value)
        result = owner.assess(value, **CONTEXT)
        self.assertEqual(result['eligible_for_bounded_destination_record'], ['imported/create-skill'])
        self.assertEqual(result['case_groups_observed'], 20)
        for k in ('legacy_implementation_or_UI_parity_proven', 'source_acceptance_supplied_by_data',
                  'installation_or_publication_authority', 'evidence_authenticity_established_by_data', 'formal_migration_complete'):
            self.assertIs(result[k], False)
        self.assertNotIn(CONTEXT['expected_email'], json.dumps(result))
        self.assertNotIn(CONTEXT['expected_workspace'], json.dumps(result))
        self.assertEqual(value, before)

    def test_data_cannot_supply_approval_source_acceptance_or_publication(self):
        for field in ('approved', 'source_accepted', 'publish', 'expected_email'):
            with self.subTest(field=field): self.reject(lambda v: v.update({field: True}))

    def test_host_change_requires_requalification(self):
        for key in owner.HOST:
            with self.subTest(key=key): self.reject(lambda v: v['host'].update({key: 'changed'}))

    def test_identity_mismatch_and_workspace_are_refused(self):
        for fields in ({'email': 'other@example.invalid'}, {'type': 'apiKey'}, {'workspace_name': 'Company'}):
            with self.subTest(fields=fields): self.reject(lambda v: v['identity'].update(fields))

    def test_expected_context_is_independent_and_personal(self):
        for change in ({'expected_email': 'person@affirm.com'}, {'expected_workspace': '/Users/fixture/affirm/project'},
                       {'expected_account_home': '/Users/fixture/chaos-scheduler'}, {'expected_workspace': '/Users/fixture/../project'},
                       {'expected_email': 'other@example.invalid'}):
            with self.subTest(change=change), self.assertRaises(owner.ObservationError):
                owner.assess(observation(), **{**CONTEXT, **change})

    def test_workspace_must_match_actual_qualified_context(self):
        self.reject(lambda v: v.update(workspace='/Users/fixture/elsewhere'))

    def test_incomplete_or_unreaped_catalog_is_refused(self):
        for change in ({'complete_response': False}, {'process_terminal': False}, {'process_exit_code': -9},
                       {'process_exit_code': False}, {'stderr_bytes': 65537}):
            with self.subTest(change=change): self.reject(lambda v: v['catalog'].update(change))

    def test_catalog_cannot_activate_install_refresh_or_create_workers(self):
        for change in ({'extra_roots': ['/fixture']}, {'token_refresh_requested': True},
                       {'threads_or_turns_created': 1}, {'model_workers_started': 1},
                       {'plugin_installation_or_configuration_changes': True}):
            with self.subTest(change=change): self.reject(lambda v: v['catalog'].update(change))

    def test_request_sequence_and_parameters_are_exact(self):
        self.reject(lambda v: v['catalog']['requests'].append({'method': 'thread/start', 'params': {}}))
        self.reject(lambda v: v['catalog']['requests'][2]['params'].update(refreshToken=True))
        self.reject(lambda v: v['catalog']['requests'][3]['params'].update(cwds=['/fixture/other']))
        self.reject(lambda v: v['catalog']['requests'][3]['params'].update(forceReload=1))

    def test_missing_disabled_duplicate_or_other_provider_is_refused(self):
        for change in ({'enabled': False}, {'name': 'other'}, {'scope': 'user'}, {'plugin_id': 'plugin'},
                       {'path': '/fixture/other/SKILL.md'}):
            with self.subTest(change=change): self.reject(lambda v: v['provider'].update(change))
        self.reject(lambda v: v['provider']['files_before'].pop('SKILL.md'))

    def test_provider_hash_or_identity_drift_is_refused(self):
        self.reject(lambda v: v['provider']['files_after']['SKILL.md'].update(inode=123))
        self.reject(lambda v: v['provider']['files_before']['SKILL.md'].update(sha256='0' * 64))
        self.reject(lambda v: v['provider']['files_before']['SKILL.md'].update(inode=True))

    def test_private_runtime_lock_and_unchanged_configuration_are_required(self):
        for key in owner.RUNTIME:
            changed = not owner.RUNTIME[key] if type(owner.RUNTIME[key]) is bool else 'changed'
            with self.subTest(key=key): self.reject(lambda v: v['runtime'].update({key: changed}))
        self.reject(lambda v: v['runtime'].update(source_build_or_lifecycle_scripts=0))

    def test_each_actual_guard_and_behavior_group_is_required(self):
        for group, fields in (('guards', owner.GUARDS), ('checks', owner.CHECKS)):
            for key in fields:
                with self.subTest(group=group, key=key):
                    self.reject(lambda v: v['functional'][group].update({key: False}))

    def test_validator_limitation_cannot_be_hidden(self):
        self.reject(lambda v: v['functional'].update(validator_limit='validator_proves_behavior'))
        self.reject(lambda v: v['functional']['steps'][16].update(exit_code=1))

    def test_missing_duplicate_reordered_or_extra_case_is_refused(self):
        self.reject(lambda v: v['functional']['steps'].pop())
        self.reject(lambda v: v['functional']['steps'].append(v['functional']['steps'][0]))
        self.reject(lambda v: v['functional']['steps'].__setitem__(1, v['functional']['steps'][0]))
        self.reject(lambda v: v['functional']['steps'].reverse())

    def test_wrong_script_or_case_outcome_is_refused(self):
        self.reject(lambda v: v['functional']['steps'][0].update(script='/fixture/installer'))
        self.reject(lambda v: v['functional']['steps'][3].update(exit_code=0))
        self.reject(lambda v: v['functional']['steps'][9].update(exit_code=0))
        self.reject(lambda v: v['functional']['steps'][0].update(exit_code=False))

    def test_every_child_must_be_terminal(self):
        for i in range(len(owner.ROSTER)):
            with self.subTest(i=i): self.reject(lambda v: v['functional']['steps'][i].update(process_terminal=False))

    def test_deadlines_and_timing_are_not_optional(self):
        for seconds in (-1, 15, float('inf'), float('nan'), True):
            with self.subTest(seconds=seconds): self.reject(lambda v: v['functional']['steps'][0].update(elapsed_seconds=seconds))
        self.reject(lambda v: v['functional'].update(total_elapsed_seconds=150))
        self.reject(lambda v: v['functional'].update(total_elapsed_seconds=0.01))

    def test_resource_output_and_case_logs_are_bound(self):
        self.reject(lambda v: v['functional']['steps'][8].update(stdout_sha256='0' * 64))
        self.reject(lambda v: v['functional']['steps'][10].update(stdout_sha256='0' * 64))
        self.reject(lambda v: v['functional']['steps'][0].update(stderr_sha256='0' * 64))
        self.reject(lambda v: v['functional']['steps'][0].update(stdout_sha256='missing'))

    def test_evidence_digests_are_required(self):
        for key in observation()['evidence']:
            with self.subTest(key=key): self.reject(lambda v: v['evidence'].update({key: ''}))

    def test_zero_effects_cannot_be_boolean_or_nonzero(self):
        for key in owner.ZERO_EFFECTS:
            with self.subTest(key=key): self.reject(lambda v: v['safety'].update({key: 1}))
        self.reject(lambda v: v['safety'].update(model_workers=False))

    def test_unknown_nested_fields_and_nonfinite_values_are_refused(self):
        self.reject(lambda v: v['functional']['checks'].update(user_approved=True))
        self.reject(lambda v: v['provider'].update(source_accepted=True))
        self.reject(lambda v: v['evidence'].update(other='x' * (owner.MAX_BYTES + 1)))


class PrivateInputContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'observation.json'
        self.path.write_text(json.dumps(observation()))
        self.path.chmod(0o600)

    def test_private_file_and_cli_return_sanitized_observation(self):
        value = owner.load_private(self.path)
        self.assertEqual(value, observation())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = owner.main([str(self.path), '--expected-personal-email', CONTEXT['expected_email'],
                '--expected-workspace', CONTEXT['expected_workspace'], '--expected-account-home', CONTEXT['expected_account_home']])
        self.assertEqual(code, 0)
        self.assertNotIn(CONTEXT['expected_email'], output.getvalue())
        self.assertNotIn(self.temp.name, output.getvalue())

    def test_mode_symlink_hardlink_and_directory_are_refused(self):
        self.path.chmod(0o644)
        with self.assertRaises(owner.ObservationError): owner.load_private(self.path)
        self.path.chmod(0o600)
        alias = self.path.with_name('alias');alias.symlink_to(self.path)
        with self.assertRaises(OSError): owner.load_private(alias)
        alias.unlink();os.link(self.path, alias)
        with self.assertRaises(owner.ObservationError): owner.load_private(self.path)
        with self.assertRaises(owner.ObservationError): owner.load_private(self.temp.name)

    def test_fifo_refuses_without_waiting_for_a_writer(self):
        fifo = self.path.with_name('fifo');os.mkfifo(fifo, 0o600)
        with self.assertRaises(owner.ObservationError): owner.load_private(fifo)

    def test_empty_large_duplicate_and_nonfinite_json_are_refused(self):
        for raw in ('', ' ' * (owner.MAX_BYTES + 1), '{"a":1,"a":2}', '{"a":NaN}'):
            with self.subTest(size=len(raw)):
                self.path.write_text(raw)
                with self.assertRaises(owner.ObservationError): owner.load_private(self.path)

    def test_partial_reads_are_collected_and_input_is_preserved(self):
        before = self.path.read_bytes(), self.path.stat().st_ino
        real_read = os.read
        with mock.patch.object(owner.os, 'read', side_effect=lambda fd, n: real_read(fd, min(n, 7))):
            self.assertEqual(owner.load_private(self.path), observation())
        self.assertEqual(before, (self.path.read_bytes(), self.path.stat().st_ino))

    def test_wrong_owner_and_observed_change_are_refused(self):
        real = os.fstat
        def wrong_owner(fd):
            facts = list(real(fd));facts[4] = os.getuid() + 1
            return os.stat_result(facts)
        with mock.patch.object(owner.os, 'fstat', side_effect=wrong_owner), self.assertRaises(owner.ObservationError):
            owner.load_private(self.path)
        calls = []
        def changed(fd):
            result = real(fd)
            if calls:
                facts = list(result);facts[6] += 1;return os.stat_result(facts)
            calls.append(True);return result
        with mock.patch.object(owner.os, 'fstat', side_effect=changed), self.assertRaises(owner.ObservationError):
            owner.load_private(self.path)


if __name__ == '__main__':
    unittest.main()
