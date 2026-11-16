"""Private bundle regressions; no download, real state, native link or worker."""
import copy
import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import runpy
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import personal_gsd_codex_bundle as m


def mkdir(root, name):
    path = root/name
    path.mkdir(mode=0o700)
    return path


def emission():
    contract, _ = m.load_contract()
    return {'schema': 'personal-portability/gsd-codex-bundle-emission/v1',
            'node_version': '24.22.2', 'guards': dict.fromkeys(m.GUARDS, True),
            'files': [], 'modules': [],
            'builtin_imports': ['crypto', 'fs', 'os', 'path', 'readline', 'vm'],
            'denied_child_imports': ['child_process'],
            'package_module_initialized': True, 'package_install_main_invoked': False,
            'complete_package_companions_preserved': True,
            'public_emitters': ['copyWithPathReplacement', 'installCodexConfig'],
            'role_count': 34, 'native_skill_ids': list(m.SKILLS),
            'HOME_preserved': True, 'CODEX_HOME_preserved': True,
            'native_roots_changed': False, 'model_worker_launched': False,
            'log_call_counts': dict.fromkeys(('log', 'info', 'warn', 'error', 'debug'), 0),
            'configuration_fixture': {'upstream_public_fs_seam': True,
                'project': contract['project_configuration'],
                'global_defaults_sha256': m.digest(b'{}\n'),
                'virtual_global_default_reads': 102, 'real_home_configuration_read': False}}, contract


class ContractTests(unittest.TestCase):
    def test_source_module_initializes_without_an_unavailable_runtime_TOML_parser(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'tomllib':
                raise ModuleNotFoundError('synthetic missing stdlib parser')
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=unavailable):
            module = runpy.run_path(str(Path(m.__file__)), run_name='bundle_dependency_qualification')
        self.assertTrue(callable(module['prepare_into']))
        self.assertTrue(callable(module['verify_into']))

    def test_unavailable_TOML_parser_refuses_actual_validation(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'tomllib':
                raise ModuleNotFoundError('synthetic missing stdlib parser')
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=unavailable), \
                self.assertRaisesRegex(ValueError, 'TOML_parser_unavailable'):
            m._toml(b'name = "synthetic-role"\n')

    def test_contract_binds_whole_package_and_exact_authoring_surface(self):
        value, old = m.load_contract()
        self.assertEqual(value['package_entries'], old['package_entries'])
        self.assertEqual(value['bundle_entries'], 979)
        self.assertEqual(value['selected_skills'], m.SKILLS)
        self.assertEqual(len(value['allowed_authoring_roles']), 9)
        self.assertFalse(value['native_publication_authorized'])

    def changed(self, change):
        value, _ = m.load_contract();change(value)
        real = m.source.regular_bytes
        def read(path, limit):
            return json.dumps(value).encode() if path.name == m.CONTRACT else real(path, limit)
        with patch.object(m.source, 'regular_bytes', side_effect=read), self.assertRaises(ValueError):
            m.load_contract()

    def test_unknown_contract_field_refuses(self):
        self.changed(lambda value: value.update(apply_authorized=True))

    def test_boolean_cannot_replace_count(self):
        self.changed(lambda value: value.update(package_entries=True))

    def test_incomplete_runtime_count_refuses(self):
        self.changed(lambda value: value.update(runtime_entries=4))

    def test_extra_skill_refuses(self):
        self.changed(lambda value: value['selected_skills'].append('gsd-ship'))

    def test_extra_role_refuses(self):
        self.changed(lambda value: value['allowed_authoring_roles'].append('gsd-executor'))

    def test_model_override_configuration_refuses(self):
        self.changed(lambda value: value['project_configuration'].update(model_overrides={'gsd-planner': 'anything'}))

    def test_home_defaults_are_explicit_empty_data(self):
        self.changed(lambda value: value.update(global_defaults={'secret': 'synthetic'}))

    def test_emitter_drift_refuses(self):
        self.changed(lambda value: value.update(emitter_sha256='0'*64))

    def test_network_profile_drift_refuses(self):
        self.changed(lambda value: value.update(network_profile_sha256='0'*64))

    def test_owner_lock_drift_refuses(self):
        self.changed(lambda value: value.update(owner_lock_sha256='0'*64))

    def test_role_policy_drift_refuses(self):
        self.changed(lambda value: value.update(owner_role_policy_sha256='0'*64))

    def test_source_dependency_drift_refuses(self):
        self.changed(lambda value: value.update(source_observer_sha256='0'*64))

    def test_publication_cannot_be_enabled_in_contract(self):
        self.changed(lambda value: value.update(native_publication_authorized=True))


class PrivateFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(strict=True)
        self.root.chmod(0o700)

    def test_owned_empty_directory_has_stable_identity(self):
        before = m._private_directory(self.root, empty=True)
        self.assertEqual(before, m._private_directory(self.root))

    def test_nonempty_operation_refuses(self):
        (self.root/'foreign').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'not_private_empty'):
            m._private_directory(self.root, empty=True)
        self.assertEqual((self.root/'foreign').read_bytes(), b'preserve')

    def test_readable_directory_refuses(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'not_private_empty'):
            m._private_directory(self.root)

    def test_root_alias_refuses_before_descendant_read(self):
        real = mkdir(self.root, 'real');alias = self.root/'alias';alias.symlink_to(real)
        with self.assertRaises((ValueError, OSError)):
            m._private_directory(alias)

    @contextlib.contextmanager
    def ignored_nofollow(self):
        original = os.open
        def open_directory(path, flags, *args, **kwargs):
            if flags & os.O_DIRECTORY:
                flags &= ~os.O_NOFOLLOW
            return original(path, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=open_directory):
            yield

    def test_alias_refusals_do_not_depend_on_open_nofollow(self):
        target = mkdir(self.root, 'target')
        alias = self.root/'alias';alias.symlink_to(target)
        (self.root/'gsd-codex-package-cache').symlink_to(target)
        (self.root/'child').symlink_to(target)
        with self.ignored_nofollow(), \
                patch.object(m.source, 'regular_bytes', side_effect=AssertionError('tarball read')) as read:
            for name, operation in (('root', lambda: m._private_directory(alias)),
                                    ('cache', lambda: m._read_cache(self.root)),
                                    ('child', lambda: m._private_child(self.root, 'child'))):
                with self.subTest(operation=name), \
                        self.assertRaisesRegex(ValueError, 'directory_alias_or_special'):
                    operation()
        read.assert_not_called()

    def test_ancestor_alias_refuses_before_descendant_open_without_nofollow(self):
        target = mkdir(self.root, 'target');mkdir(target, 'descendant')
        alias = self.root/'alias';alias.symlink_to(target)
        original = os.open
        def open_directory(path, flags, *args, **kwargs):
            if path == 'descendant':
                raise AssertionError('descendant opened through alias')
            return original(path, flags & ~os.O_NOFOLLOW, *args, **kwargs)
        with patch.object(os, 'open', side_effect=open_directory), \
                self.assertRaisesRegex(ValueError, 'directory_alias_or_special'):
            m._private_directory(alias/'descendant')

    def test_directory_swap_before_open_refuses_and_closes_child_without_nofollow(self):
        target = mkdir(self.root, 'target')
        (target/'preserved').write_bytes(b'preserve')
        original = os.open
        for same_inode in (False, True):
            victim = mkdir(self.root, 'victim-'+str(same_inode))
            kept = self.root/(victim.name+'-kept');opened = []
            def swap_before_open(path, flags, *args, **kwargs):
                if path == victim.name:
                    victim.rename(kept)
                    victim.symlink_to(kept if same_inode else target)
                fd = original(path, flags & ~os.O_NOFOLLOW, *args, **kwargs)
                opened.append(fd)
                return fd
            with self.subTest(same_inode=same_inode), \
                    patch.object(os, 'open', side_effect=swap_before_open), \
                    self.assertRaisesRegex(ValueError, 'directory_changed'):
                m._private_directory(victim)
            for fd in set(opened):
                with self.assertRaises(OSError):
                    os.fstat(fd)
        self.assertEqual((target/'preserved').read_bytes(), b'preserve')

    def test_inventory_reads_owned_binary_bytes(self):
        path = self.root/'fixture';path.write_bytes(b'\xff\x00payload')
        row = m._inventory(self.root)['fixture']
        self.assertEqual(row['sha256'], m.digest(path.read_bytes()))

    def test_accepted_reader_maximum_is_used_without_widening(self):
        (self.root/'fixture').write_bytes(b'x')
        scope = m._scope();real = scope.read_regular;limits = []
        def read(fd, name, *, max_bytes):
            limits.append(max_bytes)
            return real(fd, name, max_bytes=max_bytes)
        with patch.object(scope, 'read_regular', side_effect=read):
            self.assertIn('fixture', m._inventory(self.root))
        self.assertEqual(limits, [scope.MAX_FILE_BYTES])

    def test_symlink_member_refuses_without_reading_target(self):
        outside = mkdir(self.root, 'outside');(outside/'sensitive-fixture').write_bytes(b'preserve')
        inside = mkdir(self.root, 'inside');(inside/'alias').symlink_to(outside, target_is_directory=True)
        scope = m._scope()
        with patch.object(scope, 'read_regular', side_effect=AssertionError('outside read')):
            with self.assertRaisesRegex(ValueError, 'special_member'):
                m._inventory(inside)

    def test_shared_regular_member_refuses(self):
        path = self.root/'one';path.write_bytes(b'preserve');os.link(path, self.root/'two')
        with self.assertRaisesRegex(ValueError, 'special_member'):
            m._inventory(self.root)

    def test_special_member_refuses(self):
        os.mkfifo(self.root/'pipe')
        with self.assertRaisesRegex(ValueError, 'special_member'):
            m._inventory(self.root)

    def test_inventory_is_bounded(self):
        (self.root/'a').write_bytes(b'a');(self.root/'b').write_bytes(b'b')
        with patch.object(m, 'MAX_FILES', 1), self.assertRaisesRegex(ValueError, 'inventory_limit'):
            m._inventory(self.root)

    def test_sealing_restores_only_pinned_executable_modes(self):
        folder = mkdir(self.root, 'bin');script = folder/'tool';script.write_bytes(b'synthetic')
        data = self.root/'data';data.write_bytes(b'bytes')
        value = m._seal(self.root, {'bin/tool': 0o500, 'data': 0o400})
        self.assertEqual((value['bin/tool']['mode'], value['data']['mode']), (0o500, 0o400))
        self.assertEqual(value['bin/tool']['sha256'], m.digest(b'synthetic'))

    def test_sealed_file_mode_drift_refuses(self):
        path = self.root/'file';path.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'file_mode_changed'):
            m._inventory(self.root, sealed=True)

    def test_visible_file_change_during_inventory_refuses(self):
        path = self.root/'fixture';path.write_bytes(b'original')
        scope = m._scope();read = scope.read_regular
        def changed(fd, name, *, max_bytes):
            raw = read(fd, name, max_bytes=max_bytes)
            path.write_bytes(b'foreign edit')
            return raw
        with patch.object(scope, 'read_regular', side_effect=changed), self.assertRaisesRegex(ValueError, 'file_changed'):
            m._inventory(self.root)
        self.assertEqual(path.read_bytes(), b'foreign edit')

    def test_cache_alias_refuses_before_tarball_read(self):
        outside = mkdir(self.root, 'outside');base = mkdir(self.root, 'base')
        (base/'gsd-codex-package-cache').symlink_to(outside)
        with patch.object(m.source, 'regular_bytes', side_effect=AssertionError('tarball read')) as read:
            with self.assertRaises((ValueError, OSError)):
                m._read_cache(base)
        read.assert_not_called()

    def test_cache_permissions_drift_refuses(self):
        parent = mkdir(self.root, 'gsd-codex-package-cache')
        (parent/'gsd-core-1.11.0.tgz').write_bytes(b'public fixture')
        with self.assertRaisesRegex(ValueError, 'cache_permissions_changed'):
            m._read_cache(self.root)

    def test_private_operation_record_permissions_required(self):
        mkdir(self.root, 'package');mkdir(self.root, 'bundle')
        (self.root/'prepared.json').write_bytes(b'{}')
        (self.root/'prepared.json').chmod(0o644)
        with patch.object(m, 'child_environment', return_value={}), \
                self.assertRaisesRegex(ValueError, 'record_permissions_changed'):
            m.verify_into(self.root)

    def test_private_child_does_not_adopt_alias(self):
        target = mkdir(self.root, 'target');(self.root/'child').symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            m._private_child(self.root, 'child')

    def test_materialization_preserves_whole_members_and_records_modes(self):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as archive:
            for name, mode in [('package/scripts/companion.cjs', 0o755), ('package/gsd-core/data', 0o644)]:
                member = tarfile.TarInfo(name);member.size = 1;member.mode = mode
                archive.addfile(member, io.BytesIO(b'x'))
        target = self.root/'package'
        inventory, modes = m._materialize(raw.getvalue(), target, {'package_entries': 2})
        self.assertEqual(set(inventory), {'scripts/companion.cjs', 'gsd-core/data'})
        self.assertEqual(modes, {'scripts/companion.cjs': 0o500, 'gsd-core/data': 0o400})
        self.assertTrue(all(value['mode'] == 0o400 for value in inventory.values()))


class EmissionRefusalTests(unittest.TestCase):
    def refused(self, change, reason):
        value, contract = emission();change(value)
        with self.assertRaisesRegex(ValueError, reason):
            m._validate_bundle(Path('/unused-package'), Path('/unused-bundle'), {}, value, contract)

    def test_unknown_result_key_refuses_before_any_filesystem_access(self):
        self.refused(lambda value: value.update(native_acceptance=True), 'shape_invalid')

    def test_install_main_flag_refuses(self):
        self.refused(lambda value: value.update(package_install_main_invoked=True), 'contract_invalid')

    def test_incomplete_package_flag_refuses(self):
        self.refused(lambda value: value.update(complete_package_companions_preserved=False), 'contract_invalid')

    def test_changed_home_flag_refuses(self):
        self.refused(lambda value: value.update(HOME_preserved=False), 'contract_invalid')

    def test_native_write_flag_refuses(self):
        self.refused(lambda value: value.update(native_roots_changed=True), 'contract_invalid')

    def test_worker_flag_refuses(self):
        self.refused(lambda value: value.update(model_worker_launched=True), 'contract_invalid')

    def test_boolean_role_count_refuses(self):
        self.refused(lambda value: value.update(role_count=True), 'contract_invalid')

    def test_unknown_builtin_refuses(self):
        self.refused(lambda value: value['builtin_imports'].append('https'), 'import_surface_changed')

    def test_failed_or_non_boolean_denial_probe_refuses(self):
        for flag in (False, 1, 'true'):
            with self.subTest(flag=flag):
                self.refused(lambda value: value['guards'].update(network_os_denied=flag), 'guard_unproven')

    def test_extra_probe_cannot_hide_failure(self):
        self.refused(lambda value: value['guards'].update(other=True), 'guards_invalid')

    def test_real_home_configuration_flag_refuses(self):
        self.refused(lambda value: value['configuration_fixture'].update(real_home_configuration_read=True), 'configuration_changed')

    def test_emitter_warning_refuses(self):
        self.refused(lambda value: value['log_call_counts'].update(warn=1), 'emitter_warning')

    def test_incomplete_bundle_count_refuses(self):
        self.refused(lambda value: None, 'file_count_invalid')


class ClosedCLITests(unittest.TestCase):
    def test_unknown_operation_refuses_before_state_or_home(self):
        with patch.object(m, '_state_root', side_effect=AssertionError('home access')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['verify', '--operation-id', '../outside']), 2)

    def test_no_apply_worker_or_arbitrary_root_verbs(self):
        for args in (['apply'], ['run-worker'], ['prepare', '--operation-id', 'x', '--repo', '/outside']):
            with self.subTest(args=args), patch.object(m, '_state_root', side_effect=AssertionError('state access')), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                m.main(args)

    def test_verify_does_not_create_missing_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();root.chmod(0o700)
            with patch.object(m, '_state_root', return_value=root), \
                    patch.object(m, 'child_environment', return_value={}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['verify', '--operation-id', '7a597ea7-b497-4a9e-af69-6f51d6641ba9']), 2)
            self.assertEqual(list(root.iterdir()), [])

    def test_wrong_cache_input_creates_no_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();root.chmod(0o700)
            with patch.object(m, '_state_root', return_value=root), \
                    patch.object(m, 'child_environment', return_value={}), \
                    patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'wrong'))), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['cache']), 2)
            self.assertEqual(list(root.iterdir()), [])

    def test_home_values_preserved_and_execution_options_removed(self):
        actual_home = os.environ['HOME'];actual_codex = os.environ.get('CODEX_HOME')
        with patch.object(m.source.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=actual_home)), \
                patch.dict(os.environ, {'NODE_OPTIONS': '--require untrusted', 'HTTPS_PROXY': 'synthetic-private'}):
            if actual_codex is not None and actual_codex != str(Path(actual_home)/'.codex'):
                with self.assertRaisesRegex(ValueError, 'noncanonical_codex_home'):
                    m.child_environment()
                self.assertEqual(os.environ.get('CODEX_HOME'), actual_codex)
                return
            env = m.child_environment()
            self.assertEqual(env['HOME'], actual_home)
            self.assertEqual(env.get('CODEX_HOME'), actual_codex)
            self.assertEqual(env['GSD_TEST_MODE'], '1')
            self.assertNotIn('NODE_OPTIONS', env);self.assertNotIn('HTTPS_PROXY', env)

    def test_custom_codex_root_is_data_refusal_without_read(self):
        with patch.object(m.source, 'child_environment', return_value={'HOME': '/synthetic-owner', 'CODEX_HOME': '/different-root'}):
            with self.assertRaisesRegex(ValueError, 'noncanonical_codex_home'):
                m.child_environment()

    def test_child_argv_has_only_package_harness_and_bundle_filesystem_grants(self):
        argv = m._child_command(Path('/fixture/package'), Path('/fixture/bundle'), Path('/qualified/node'))
        self.assertEqual(argv[:2], ['/usr/bin/sandbox-exec', '-f'])
        self.assertEqual([arg for arg in argv if arg.startswith('--allow-fs-write=')], ['--allow-fs-write=/fixture/bundle'])
        self.assertFalse(any(arg in argv for arg in ('--allow-child-process', '--allow-worker', '--allow-addons')))


if __name__ == '__main__':
    unittest.main()
