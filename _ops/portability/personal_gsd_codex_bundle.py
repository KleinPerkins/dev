"""Prepare and verify a whole pinned GSD bundle in a private operation.

The CLI has no target-repository, native installation, worker or service verb.
It preserves the exact package layout and delegates conversion to upstream.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import types
import uuid

HERE = Path(__file__).absolute().parent
SOURCE_SHA256 = '42ef7e3bcdc30e4e60f5cfcf189401cd2810aa1f1042da7585e0be5e6ca1a9cb'
if not sys.dont_write_bytecode:
    raise ValueError('gsd_bundle_requires_python_B')
source_path = HERE/'personal_gsd_codex_source.py'
if source_path.is_symlink() or hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA256:
    raise ValueError('gsd_bundle_source_dependency_changed')
sys.path.insert(0, str(HERE))
import personal_gsd_codex_source as source
if Path(source.__file__).absolute() != source_path:
    raise ValueError('gsd_bundle_source_import_changed')

CONTRACT = 'personal_gsd_codex_bundle.json'
EMITTER = 'personal_gsd_codex_emit.cjs'
NETWORK_PROFILE = 'personal_gsd_codex_network_deny.sb'
NODE = Path('/opt/homebrew/bin/node')
OWNER = HERE.parent/'doc-warden/runtime/gsd-core'
MAX_FILES = 1024
MAX_METADATA = 2*1024*1024
GUARDS = {'source_write_denied', 'outside_read_denied', 'outside_write_denied',
          'network_os_denied', 'child_call_denied'}
SKILLS = list(source.SKILLS)
ROLES = ['gsd-advisor-researcher', 'gsd-nyquist-auditor', 'gsd-pattern-mapper',
         'gsd-phase-researcher', 'gsd-plan-checker', 'gsd-planner',
         'gsd-project-researcher', 'gsd-research-synthesizer', 'gsd-roadmapper']
SCOPE_SHA256 = 'f00252220fbeb4ff1784af22407354a0e5a60aa645427b8c27eb1412098f1c69'


def _scope():
    path = HERE/'personal_scope.py'
    if path.is_symlink() or digest(path.read_bytes()) != SCOPE_SHA256:
        raise ValueError('gsd_bundle_scope_dependency_changed')
    import personal_scope as scope
    if Path(scope.__file__).absolute() != path:
        raise ValueError('gsd_bundle_scope_import_changed')
    return scope


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')


def _toml(raw):
    # Offline contract/cache imports do not require a runtime TOML parser.
    # Real role/config validation still requires the unchanged stdlib parser.
    try:
        import tomllib
    except ModuleNotFoundError:
        raise ValueError('gsd_bundle_TOML_parser_unavailable') from None
    return tomllib.loads(raw.decode('utf-8'))


def _closed(value, keys, reason):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(reason)
    return value


def _operation_id(value):
    if not isinstance(value, str):
        raise ValueError('gsd_bundle_operation_id_invalid')
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ValueError('gsd_bundle_operation_id_invalid') from None
    return value


def load_contract():
    source_contract = source.load_contract()
    value = source.strict_json(source.regular_bytes(HERE/CONTRACT, 65536))
    expected = {'schema', 'source_observer_sha256', 'emitter_sha256',
                'network_profile_sha256', 'node_sha256', 'owner_lock_sha256',
                'owner_role_policy_sha256', 'package_entries', 'bundle_entries',
                'runtime_entries', 'rewritten_runtime_markdown_entries',
                'emitter_modules', 'role_entries', 'selected_skills',
                'allowed_authoring_roles', 'project_configuration',
                'global_defaults', 'native_publication_authorized'}
    _closed(value, expected, 'gsd_bundle_contract_invalid')
    counts = {'package_entries': 943, 'bundle_entries': 979, 'runtime_entries': 556,
              'rewritten_runtime_markdown_entries': 221, 'emitter_modules': 66,
              'role_entries': 34}
    if (value['schema'] != 'personal-portability/gsd-codex-private-bundle-contract/v1'
            or value['source_observer_sha256'] != SOURCE_SHA256
            or any(type(value[key]) is not int or value[key] != count for key, count in counts.items())
            or value['selected_skills'] != SKILLS or value['allowed_authoring_roles'] != ROLES
            or value['project_configuration'] != {'runtime': 'codex', 'model_profile': 'inherit'}
            or value['global_defaults'] != {} or value['native_publication_authorized'] is not False):
        raise ValueError('gsd_bundle_contract_invalid')
    for key in ('source_observer_sha256', 'emitter_sha256', 'network_profile_sha256',
                'node_sha256', 'owner_lock_sha256', 'owner_role_policy_sha256'):
        if not isinstance(value[key], str) or re.fullmatch('[0-9a-f]{64}', value[key]) is None:
            raise ValueError('gsd_bundle_contract_digest_invalid')
    for path, key in ((HERE/EMITTER, 'emitter_sha256'),
                      (HERE/NETWORK_PROFILE, 'network_profile_sha256'),
                      (OWNER/'package-lock.json', 'owner_lock_sha256'),
                      (OWNER/'install.sh', 'owner_role_policy_sha256')):
        if digest(source.regular_bytes(path, MAX_METADATA)) != value[key]:
            raise ValueError('gsd_bundle_dependency_changed')
    if source.regular_bytes(HERE/NETWORK_PROFILE, 1024) != b'(version 1)\n(allow default)\n(deny network*)\n':
        raise ValueError('gsd_bundle_network_profile_invalid')
    return value, source_contract


def child_environment():
    env = source.child_environment()
    canonical = str(Path(env['HOME'])/'.codex')
    if 'CODEX_HOME' in env and env['CODEX_HOME'] != canonical:
        raise ValueError('gsd_bundle_noncanonical_codex_home')
    env['GSD_TEST_MODE'] = '1'
    return env


def _runner():
    original = source.bounded_runner()
    namespace = dict(original.__globals__)
    namespace['clean_environment'] = child_environment
    return types.FunctionType(original.__code__, namespace, argdefs=original.__defaults__)


def _directory_fd(path):
    if (not path.is_absolute() or '..' in path.parts
            or str(path) != os.path.normpath(str(path))):
        raise ValueError('gsd_bundle_directory_invalid')
    flags = _scope().DIR_FLAGS
    fd = os.open('/', flags)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_mode)
    try:
        for part in path.parts[1:]:
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError('gsd_bundle_directory_alias_or_special')
            child = os.open(part, flags, dir_fd=fd)
            try:
                opened = os.fstat(child)
                current = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if identity(before) != identity(opened) or identity(opened) != identity(current):
                    raise ValueError('gsd_bundle_directory_changed')
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_directory(path, *, empty=False):
    # Check each lexical component and opened identity as well as O_NOFOLLOW.
    fd = _directory_fd(path)
    try:
        info = os.fstat(fd)
        if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                or empty and os.listdir(fd)):
            raise ValueError('gsd_bundle_directory_not_private_empty')
        return {'device': info.st_dev, 'inode': info.st_ino}
    finally:
        os.close(fd)


def _write(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _inventory(root, *, sealed=False):
    identity = _private_directory(root)
    scope = _scope()
    root_fd = _directory_fd(root)
    rows = {}
    total = 0
    entries = 0
    def walk(fd, prefix):
        nonlocal total, entries
        before = os.fstat(fd)
        names = []
        with os.scandir(fd) as iterator:
            for entry in iterator:
                names.append(entry.name)
                entries += 1
                if entries > MAX_FILES*4:
                    raise ValueError('gsd_bundle_inventory_limit')
        for name in sorted(names):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            relative = '/'.join((*prefix, name))
            if info.st_uid != os.getuid():
                raise ValueError('gsd_bundle_foreign_member')
            if stat.S_ISDIR(info.st_mode):
                if sealed and stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('gsd_bundle_directory_mode_changed')
                child = os.open(name, scope.DIR_FLAGS, dir_fd=fd)
                try:
                    current = os.fstat(child)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError('gsd_bundle_directory_changed')
                    walk(child, (*prefix, name))
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('gsd_bundle_special_member')
            raw = scope.read_regular(fd, name, max_bytes=min(source.MAX_MEMBER, scope.MAX_FILE_BYTES))
            current = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns) != (
                    current.st_dev, current.st_ino, current.st_mode, current.st_nlink, current.st_size,
                    current.st_mtime_ns, current.st_ctime_ns):
                raise ValueError('gsd_bundle_file_changed')
            mode = stat.S_IMODE(info.st_mode)
            if sealed and mode not in (0o400, 0o500):
                raise ValueError('gsd_bundle_file_mode_changed')
            total += len(raw)
            if total > source.MAX_EXPANDED or len(rows) >= MAX_FILES:
                raise ValueError('gsd_bundle_inventory_limit')
            rows[relative] = {'sha256': digest(raw), 'bytes': len(raw), 'mode': mode}
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns) or set(names) != set(os.listdir(fd)):
            raise ValueError('gsd_bundle_directory_changed')
    try:
        walk(root_fd, ())
    finally:
        os.close(root_fd)
    if _private_directory(root) != identity:
        raise ValueError('gsd_bundle_root_changed')
    return rows


def _materialize(raw, root, contract):
    root.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        members = source.validated_members(archive, contract['package_entries'])
        modes = {}
        for member in members:
            relative = str(PurePosixPath(member.name).relative_to('package'))
            path = root/relative
            cursor = root
            for part in PurePosixPath(relative).parts[:-1]:
                cursor = cursor/part
                if not cursor.exists():
                    cursor.mkdir(mode=0o700)
            body = archive.extractfile(member).read()
            if len(body) != member.size:
                raise ValueError('gsd_bundle_archive_truncated')
            _write(path, body, 0o400)
            modes[relative] = 0o500 if member.mode & 0o111 else 0o400
    return _inventory(root, sealed=True), modes


def _child_command(package, bundle, node):
    return ['/usr/bin/sandbox-exec', '-f', str(HERE/NETWORK_PROFILE), str(node),
            '--permission', '--max-old-space-size=512',
            '--allow-fs-read='+str(package), '--allow-fs-read='+str(HERE/EMITTER),
            '--allow-fs-read='+str(bundle), '--allow-fs-write='+str(bundle),
            str(HERE/EMITTER), str(package), str(bundle)]


def _validate_bundle(package, bundle, reference, result, contract):
    keys = {'schema', 'node_version', 'guards', 'files', 'modules', 'builtin_imports',
            'denied_child_imports', 'package_module_initialized',
            'package_install_main_invoked', 'complete_package_companions_preserved',
            'public_emitters', 'role_count', 'native_skill_ids', 'HOME_preserved',
            'CODEX_HOME_preserved', 'native_roots_changed', 'model_worker_launched',
            'log_call_counts', 'configuration_fixture'}
    _closed(result, keys, 'gsd_bundle_emitter_shape_invalid')
    if (result['schema'] != 'personal-portability/gsd-codex-bundle-emission/v1'
            or result['package_module_initialized'] is not True
            or result['package_install_main_invoked'] is not False
            or result['complete_package_companions_preserved'] is not True
            or result['HOME_preserved'] is not True or result['CODEX_HOME_preserved'] is not True
            or result['native_roots_changed'] is not False or result['model_worker_launched'] is not False
            or result['native_skill_ids'] != SKILLS
            or type(result['role_count']) is not int or result['role_count'] != contract['role_entries']
            or result['public_emitters'] != ['copyWithPathReplacement', 'installCodexConfig']
            or not isinstance(result['node_version'], str)
            or re.fullmatch(r'24\.[0-9]+\.[0-9]+', result['node_version']) is None):
        raise ValueError('gsd_bundle_emitter_contract_invalid')
    _closed(result['guards'], GUARDS, 'gsd_bundle_guards_invalid')
    if any(flag is not True for flag in result['guards'].values()):
        raise ValueError('gsd_bundle_guard_unproven')
    if (result['builtin_imports'] != ['crypto', 'fs', 'os', 'path', 'readline', 'vm']
            or result['denied_child_imports'] != ['child_process']):
        raise ValueError('gsd_bundle_import_surface_changed')
    configuration = {'upstream_public_fs_seam': True, 'project': contract['project_configuration'],
                     'global_defaults_sha256': digest(b'{}\n'),
                     'virtual_global_default_reads': 102, 'real_home_configuration_read': False}
    if result['configuration_fixture'] != configuration:
        raise ValueError('gsd_bundle_configuration_changed')
    logs = _closed(result['log_call_counts'], ('log', 'info', 'warn', 'error', 'debug'), 'gsd_bundle_logs_invalid')
    if any(type(count) is not int or not 0 <= count <= 128 for count in logs.values()) or any(logs[key] for key in ('warn', 'error')):
        raise ValueError('gsd_bundle_emitter_warning')
    files = result['files']
    if not isinstance(files, list) or len(files) != contract['bundle_entries']:
        raise ValueError('gsd_bundle_file_count_invalid')
    claimed = {}
    for row in files:
        _closed(row, ('path', 'sha256', 'bytes'), 'gsd_bundle_file_record_invalid')
        name = row['path']
        if (not isinstance(name, str) or str(PurePosixPath(name)) != name
                or name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts
                or name in claimed or type(row['bytes']) is not int or row['bytes'] < 0
                or not isinstance(row['sha256'], str) or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None):
            raise ValueError('gsd_bundle_file_record_invalid')
        claimed[name] = {'sha256': row['sha256'], 'bytes': row['bytes']}
    actual = _inventory(bundle)
    if ({name: {key: row[key] for key in ('sha256', 'bytes')} for name, row in actual.items()} != claimed
            or not set(reference) <= set(actual)):
        raise ValueError('gsd_bundle_inventory_changed')
    selected = {'skills/'+skill+'/SKILL.md' for skill in SKILLS}
    changed = {name for name in reference if reference[name]['sha256'] != actual[name]['sha256']}
    runtime = {name for name in reference if name.startswith('gsd-core/')}
    if (len(runtime) != contract['runtime_entries']
            or {name for name in actual if name.startswith('gsd-core/')} != runtime
            or changed - runtime != selected
            or len(changed & runtime) != contract['rewritten_runtime_markdown_entries']
            or any(not name.endswith('.md') for name in changed)
            or set(actual)-set(reference) != {'config.toml', '.planning/config.json'} | {
                'agents/'+path.stem+'.toml' for path in (package/'agents').glob('gsd-*.md')}):
        raise ValueError('gsd_bundle_package_closure_changed')
    modules = result['modules']
    if not isinstance(modules, list) or len(modules) != contract['emitter_modules']:
        raise ValueError('gsd_bundle_modules_invalid')
    names = set()
    for row in modules:
        _closed(row, ('path', 'sha256'), 'gsd_bundle_modules_invalid')
        if row['path'] in names or row['path'] not in reference or row['sha256'] != reference[row['path']]['sha256']:
            raise ValueError('gsd_bundle_modules_changed')
        names.add(row['path'])
    installer = source.regular_bytes(package/'bin/install.js', source.MAX_MEMBER).decode('utf-8')
    block = re.search(r'const CODEX_AGENT_SANDBOX = \{(.*?)\n\};', installer, re.S)
    if block is None:
        raise ValueError('gsd_bundle_role_policy_unavailable')
    sandbox_map = dict(re.findall(r"'([^']+)': '([^']+)'", block.group(1)))
    roles = {}
    for path in (bundle/'agents').glob('*.toml'):
        role = _toml(source.regular_bytes(path, source.MAX_MEMBER))
        required = {'name', 'description', 'sandbox_mode', 'developer_instructions'}
        if (not required <= set(role) <= required | {'service_tier', 'model_verbosity'}
                or role['name'] != path.stem or role['sandbox_mode'] != sandbox_map.get(path.stem, 'read-only')
                or not isinstance(role['description'], str) or not role['description']
                or not isinstance(role['developer_instructions'], str) or len(role['developer_instructions']) < 100
                or ('service_tier' in role or 'model_verbosity' in role)
                and (role.get('service_tier'), role.get('model_verbosity')) != ('flex', 'low')):
            raise ValueError('gsd_bundle_role_contract_changed')
        roles[path.stem] = role
    if len(roles) != contract['role_entries'] or not set(ROLES) <= set(roles):
        raise ValueError('gsd_bundle_roles_missing')
    if _toml(source.regular_bytes(bundle/'config.toml', 65536)) != {'agents': {'max_depth': 1}}:
        raise ValueError('gsd_bundle_dispatch_configuration_changed')
    if source.strict_json(source.regular_bytes(bundle/'.planning/config.json', 65536)) != contract['project_configuration']:
        raise ValueError('gsd_bundle_project_configuration_changed')
    if _inventory(package, sealed=True) != reference:
        raise ValueError('gsd_bundle_reference_changed')
    return actual


def _seal(bundle, source_modes):
    identity = _private_directory(bundle)
    scope = _scope()
    root_fd = _directory_fd(bundle)
    def walk(fd, prefix):
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if info.st_uid != os.getuid():
                raise ValueError('gsd_bundle_foreign_member')
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, scope.DIR_FLAGS, dir_fd=fd)
                try:
                    current = os.fstat(child)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError('gsd_bundle_directory_changed')
                    os.fchmod(child, 0o700)
                    walk(child, (*prefix, name))
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                child = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=fd)
                try:
                    current = os.fstat(child)
                    if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                            or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                            or current.st_uid != os.getuid()):
                        raise ValueError('gsd_bundle_file_changed')
                    os.fchmod(child, source_modes.get('/'.join((*prefix, name)), 0o400))
                finally:
                    os.close(child)
            else:
                raise ValueError('gsd_bundle_special_member')
    try:
        walk(root_fd, ())
    finally:
        os.close(root_fd)
    if _private_directory(bundle) != identity:
        raise ValueError('gsd_bundle_root_changed')
    return _inventory(bundle, sealed=True)


def prepare_into(operation, raw, node):
    """Private fixture/owner API; caller supplies an already-owned empty directory.

    This grants no target-root or publication authority. Production CLI paths are
    selected separately and cannot select a fixture or arbitrary output root.
    """
    contract, source_contract = load_contract()
    child_environment()
    if sys.platform != 'darwin':
        raise ValueError('gsd_bundle_OS_network_fence_unavailable')
    source.verified_package(raw, source_contract)
    node = node.resolve(strict=True)
    if digest(source.regular_bytes(node, 128*1024*1024)) != contract['node_sha256']:
        raise ValueError('gsd_bundle_node_changed')
    identity = _private_directory(operation, empty=True)
    package, bundle = operation/'package', operation/'bundle'
    reference, modes = _materialize(raw, package, contract)
    bundle.mkdir(mode=0o700)
    code, stdout, stderr = _runner()(_child_command(package, bundle, node), operation)
    if code or stderr:
        raise ValueError('gsd_bundle_emission_failed')
    result = source.strict_json(stdout)
    _validate_bundle(package, bundle, reference, result, contract)
    inventory = _seal(bundle, modes)
    bindings = {name: digest(source.regular_bytes(HERE/name, MAX_METADATA))
                for name in (Path(__file__).name, CONTRACT, EMITTER, NETWORK_PROFILE,
                             'personal_gsd_codex_source.py', 'personal_gsd_codex_source.json',
                             'personal_gsd_codex_compile.cjs', 'personal_git.py', 'personal_scope.py')}
    value = {'schema': 'personal-portability/gsd-codex-private-bundle/v1',
             'operation_root': str(operation), 'root_identity': identity,
             'package': source.PACKAGE, 'version': source.VERSION, 'git_commit': source.COMMIT,
             'package_sha256': digest(raw), 'node_sha256': contract['node_sha256'],
             'implementation_bindings': bindings, 'owner_lock_sha256': contract['owner_lock_sha256'],
             'reference': reference, 'bundle': inventory,
             'emission': result, 'bundle_root_identity': _private_directory(bundle),
             'source_executable_bits_restored_in_read_only_bundle': True,
             'status': 'prepared_for_owner_native_qualification',
             'dependency_lock_installation_qualified': False,
             'native_role_ABI_qualified': False, 'native_publication_authorized': False,
             'worker_or_service_authorized': False, 'full_active_v2_accepted': False}
    value['record_digest'] = digest(encode(value))
    _write(operation/'prepared.json', encode(value))
    return verify_into(operation)


def verify_into(operation):
    contract, source_contract = load_contract()
    child_environment()
    identity = _private_directory(operation)
    if set(os.listdir(operation)) != {'package', 'bundle', 'prepared.json'}:
        raise ValueError('gsd_bundle_operation_members_changed')
    if stat.S_IMODE((operation/'prepared.json').lstat().st_mode) != 0o600:
        raise ValueError('gsd_bundle_record_permissions_changed')
    value = source.strict_json(source.regular_bytes(operation/'prepared.json', MAX_METADATA))
    keys = {'schema', 'operation_root', 'root_identity', 'package', 'version', 'git_commit',
            'package_sha256', 'node_sha256', 'implementation_bindings', 'owner_lock_sha256',
            'reference', 'bundle', 'emission', 'bundle_root_identity',
            'source_executable_bits_restored_in_read_only_bundle', 'status',
            'dependency_lock_installation_qualified', 'native_role_ABI_qualified',
            'native_publication_authorized', 'worker_or_service_authorized',
            'full_active_v2_accepted', 'record_digest'}
    _closed(value, keys, 'gsd_bundle_record_invalid')
    old_digest = value['record_digest']
    unsigned = dict(value);del unsigned['record_digest']
    if (old_digest != digest(encode(unsigned)) or value['operation_root'] != str(operation)
            or value['root_identity'] != identity
            or value['schema'] != 'personal-portability/gsd-codex-private-bundle/v1'
            or (value['package'], value['version'], value['git_commit']) != (source.PACKAGE, source.VERSION, source.COMMIT)
            or value['status'] != 'prepared_for_owner_native_qualification'
            or any(value[name] is not False for name in ('dependency_lock_installation_qualified',
                'native_role_ABI_qualified', 'native_publication_authorized',
                'worker_or_service_authorized', 'full_active_v2_accepted'))
            or value['source_executable_bits_restored_in_read_only_bundle'] is not True
            or value['node_sha256'] != contract['node_sha256']
            or value['package_sha256'] != source_contract['package_sha256']
            or value['owner_lock_sha256'] != contract['owner_lock_sha256']):
        raise ValueError('gsd_bundle_record_changed')
    bindings = value['implementation_bindings']
    names = (Path(__file__).name, CONTRACT, EMITTER, NETWORK_PROFILE,
             'personal_gsd_codex_source.py', 'personal_gsd_codex_source.json',
             'personal_gsd_codex_compile.cjs', 'personal_git.py', 'personal_scope.py')
    _closed(bindings, names, 'gsd_bundle_implementation_bindings_invalid')
    if any(digest(source.regular_bytes(HERE/name, MAX_METADATA)) != bindings[name] for name in names):
        raise ValueError('gsd_bundle_implementation_changed')
    if (_inventory(operation/'package', sealed=True) != value['reference']
            or _inventory(operation/'bundle', sealed=True) != value['bundle']
            or _private_directory(operation/'bundle') != value['bundle_root_identity']):
        raise ValueError('gsd_bundle_sealed_bytes_or_identity_changed')
    _validate_bundle(operation/'package', operation/'bundle', value['reference'], value['emission'], contract)
    return {'schema': value['schema'], 'status': value['status'],
            'record_digest': old_digest, 'reference_files': len(value['reference']),
            'bundle_files': len(value['bundle']), 'native_publication_authorized': False,
            'native_role_ABI_qualified': False, 'worker_or_service_authorized': False,
            'dependency_lock_installation_qualified': False, 'full_active_v2_accepted': False}


def _state_root():
    # No XDG override, caller path, HOME substitution or directory discovery.
    home = _scope().operator_home()
    base = home/'.local/share/personal-portability'
    _private_directory(base)
    return base


def _private_child(parent, name):
    _private_directory(parent)
    path = parent/name
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _private_directory(path)
    return path


def _read_cache(base):
    parent = base/'gsd-codex-package-cache'
    _private_directory(parent)
    path = parent/'gsd-core-1.11.0.tgz'
    raw = source.regular_bytes(path, source.MAX_COMPRESSED)
    if stat.S_IMODE(path.lstat().st_mode) != 0o400:
        raise ValueError('gsd_bundle_cache_permissions_changed')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('cache', help='Accept only the exact public pinned tarball on stdin.')
    for name in ('prepare', 'verify'):
        verbs.add_parser(name).add_argument('--operation-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.verb != 'cache':
            _operation_id(args.operation_id)  # Refuse before home or state access.
        contract, source_contract = load_contract()
        child_environment()
        base = _state_root()
        if args.verb == 'cache':
            raw = sys.stdin.buffer.read(source.MAX_COMPRESSED+1)
            source.verified_package(raw, source_contract)
            cache = _private_child(base, 'gsd-codex-package-cache')/'gsd-core-1.11.0.tgz'
            try:
                cache.lstat()
            except FileNotFoundError:
                _write(cache, raw, 0o400)
            else:
                if source.regular_bytes(cache, source.MAX_COMPRESSED) != raw or stat.S_IMODE(cache.lstat().st_mode) != 0o400:
                    raise ValueError('gsd_bundle_existing_cache_held')
            result = {'status': 'exact_pinned_package_cached', 'sha256': digest(raw),
                      'native_publication_authorized': False}
        else:
            parent = base/'gsd-codex-bundles'
            if args.verb == 'verify':
                _private_directory(parent)
            else:
                parent = _private_child(base, 'gsd-codex-bundles')
            operation = parent/args.operation_id
            if args.verb == 'verify':
                result = verify_into(operation)
            else:
                raw = _read_cache(base)
                source.verified_package(raw, source_contract)
                operation.mkdir(mode=0o700)  # Never adopt or reuse an operation.
                result = prepare_into(operation, raw, NODE)
    except (ValueError, OSError, tarfile.TarError, UnicodeError, RecursionError):
        print(json.dumps({'status': 'unavailable', 'reason': 'gsd_bundle_precondition_or_qualification_failed',
                          'native_publication_authorized': False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
