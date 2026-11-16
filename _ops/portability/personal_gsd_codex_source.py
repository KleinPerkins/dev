"""Exact-pin GSD Codex text evidence; no installer or native publication route."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import sys
import tarfile
import tempfile
import types

HERE = Path(__file__).absolute().parent
PACKAGE = '@opengsd/gsd-core'
VERSION = '1.11.0'
COMMIT = '182f60b4c170785d96f1deb87fea8b108e9b985f'
INTEGRITY = 'sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ=='
SKILLS = ('gsd-new-project', 'gsd-discuss-phase', 'gsd-plan-phase', 'gsd-validate-phase')
MAX_COMPRESSED = 8*1024*1024
MAX_EXPANDED = 20*1024*1024
MAX_MEMBER = 2*1024*1024
CONTRACT_NAME = 'personal_gsd_codex_source.json'
HARNESS_NAME = 'personal_gsd_codex_compile.cjs'
GIT_MODULE_SHA = 'eb6eba70b21e0c8c0650b0e940a6290cb500e9bfdb2b638a8e9203f7ceef1d58'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key,value in rows:
            if key in result:
                raise ValueError('gsd_source_duplicate_json_key')
            result[key] = value
        return result
    def reject_number(_value):
        raise ValueError('gsd_source_non_integer_json_number')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
                      parse_float=reject_number,parse_constant=reject_number)


def regular_bytes(path, maximum):
    """No-follow, owned/unshared bounded read, with visible-change detection."""
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_size > maximum):
            raise ValueError('gsd_source_file_unavailable')
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(fd, min(65536, maximum+1-len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        def facts(info):
            return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid,
                    info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        if len(raw) > maximum or facts(os.fstat(fd)) != facts(before) or facts(path.lstat()) != facts(before):
            raise ValueError('gsd_source_file_changed')
        return bytes(raw)
    finally:
        os.close(fd)


def load_contract():
    contract = strict_json(regular_bytes(HERE/CONTRACT_NAME, 65536))
    required = {'schema','package','version','git_commit','npm_integrity','package_sha256',
                'package_entries','converter','harness_sha256','descriptors','scope',
                'owner_pin_sha256','owner_interface_sha256'}
    if (not isinstance(contract,dict) or set(contract) != required or contract['schema'] != 'personal-portability/gsd-codex-source-text/v1'
            or (contract['package'],contract['version'],contract['git_commit'],contract['npm_integrity'])
            != (PACKAGE,VERSION,COMMIT,INTEGRITY)
            or contract['package_entries'] != 943
            or contract['converter'] != 'convertClaudeCommandToCodexSkill'
            or contract['scope'] != 'raw_codex_text_only_not_native_installation'):
        raise ValueError('gsd_source_contract_invalid')
    if not isinstance(contract['descriptors'],dict) or set(contract['descriptors']) != set(SKILLS):
        raise ValueError('gsd_source_skill_set_invalid')
    for record in contract['descriptors'].values():
        if not isinstance(record,dict) or set(record) != {'raw_skill_sha256','command_sha256','converted_sha256'}:
            raise ValueError('gsd_source_descriptor_invalid')
        if any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v) is None for v in record.values()):
            raise ValueError('gsd_source_descriptor_invalid')
    for name in ('package_sha256','harness_sha256','owner_pin_sha256','owner_interface_sha256'):
        if not isinstance(contract[name],str) or re.fullmatch('[0-9a-f]{64}',contract[name]) is None:
            raise ValueError('gsd_source_contract_digest_invalid')
    harness = regular_bytes(HERE/HARNESS_NAME, 32768)
    if digest(harness) != contract['harness_sha256']:
        raise ValueError('gsd_source_harness_changed')
    owner = HERE.parent/'doc-warden/runtime/gsd-core'
    for filename, key in (('gsd-core-pin.json','owner_pin_sha256'),
                          ('runtime-interface.v1.json','owner_interface_sha256')):
        if digest(regular_bytes(owner/filename,65536)) != contract[key]:
            raise ValueError('gsd_source_owner_binding_changed')
    return contract


def validated_members(archive, expected_count):
    members = archive.getmembers()
    if len(members) != expected_count:
        raise ValueError('gsd_package_entry_count')
    seen = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if (not member.isfile() or path.is_absolute() or len(path.parts) < 2
                or path.parts[0] != 'package' or str(path) != member.name
                or any(p in ('','.','..') for p in path.parts) or '\\' in member.name
                or '\x00' in member.name or member.name in seen
                or member.size < 0 or member.size > MAX_MEMBER):
            raise ValueError('gsd_package_member_invalid')
        total += member.size
        if total > MAX_EXPANDED:
            raise ValueError('gsd_package_expanded_limit')
        seen.add(member.name)
    # Every ancestor must be a directory rather than another regular member.
    for member in members:
        if any(str(p) in seen for p in PurePosixPath(member.name).parents):
            raise ValueError('gsd_package_ancestor_collision')
    return members


def verified_package(raw, contract):
    if len(raw) > MAX_COMPRESSED:
        raise ValueError('gsd_package_compressed_limit')
    observed = 'sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode()
    if observed != INTEGRITY or digest(raw) != contract['package_sha256']:
        raise ValueError('gsd_package_integrity')
    return raw


def child_environment():
    # Keep real values; never turn an unrelated fixture into HOME/CODEX_HOME.
    if 'HOME' not in os.environ or os.environ['HOME'] != pwd.getpwuid(os.getuid()).pw_dir:
        raise ValueError('gsd_real_home_unavailable')
    env = {'HOME':os.environ['HOME'],'PATH':'/usr/bin:/bin','LC_ALL':'C','LANG':'C'}
    if 'CODEX_HOME' in os.environ:
        env['CODEX_HOME'] = os.environ['CODEX_HOME']
    return env


def bounded_runner():
    if not sys.dont_write_bytecode:
        raise ValueError('gsd_qualification_requires_python_B')
    if digest(regular_bytes(HERE/'personal_git.py', 65536)) != GIT_MODULE_SHA:
        raise ValueError('gsd_bounded_runner_changed')
    sys.path.insert(0,str(HERE))
    import personal_git as g
    if Path(g.__file__).absolute() != HERE/'personal_git.py':
        raise ValueError('gsd_bounded_runner_root')
    namespace = dict(g.bounded_process.__globals__)
    namespace.update(clean_environment=child_environment, TIMEOUT=12.0, MAX_OUTPUT=1024*1024)
    return types.FunctionType(g.bounded_process.__code__,namespace,
                              argdefs=g.bounded_process.__defaults__)


def validate_conversion(result, contract):
    required = {'descriptors','loaded_modules','imported_builtins','denied_operation_imports',
                'HOME','CODEX_HOME','installer_invoked','guard_probes','node_version'}
    if not isinstance(result,dict) or set(result) != required or result['installer_invoked'] is not False:
        raise ValueError('gsd_conversion_result_invalid')
    if result['HOME'] != os.environ.get('HOME') or result['CODEX_HOME'] != os.environ.get('CODEX_HOME'):
        raise ValueError('gsd_conversion_home_changed')
    expected_probes = {'outside_read_denied','writes_denied','child_calls_denied','network_import_denied'}
    if (not isinstance(result['guard_probes'],dict) or set(result['guard_probes']) != expected_probes
            or not all(v is True for v in result['guard_probes'].values())):
        raise ValueError('gsd_conversion_guards_unproven')
    version = result['node_version']
    if not isinstance(version,str) or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) is None or int(version.split('.')[0]) < 24:
        raise ValueError('gsd_conversion_node_unsupported')
    if result['imported_builtins'] != ['crypto','fs','os','path'] or result['denied_operation_imports'] != ['child_process']:
        raise ValueError('gsd_conversion_import_surface_changed')
    descriptors = result['descriptors']
    if (not isinstance(descriptors,list) or any(not isinstance(r,dict) for r in descriptors)
            or [r.get('id') for r in descriptors] != list(SKILLS)):
        raise ValueError('gsd_conversion_skill_set_changed')
    for row in descriptors:
        if set(row) != {'id','command_sha256','converted_sha256','body'} or not isinstance(row['body'],str):
            raise ValueError('gsd_conversion_descriptor_invalid')
        expected = contract['descriptors'][row['id']]
        if (row['command_sha256'] != expected['command_sha256']
                or row['converted_sha256'] != expected['converted_sha256']
                or digest(row['body'].encode()) != expected['converted_sha256']):
            raise ValueError('gsd_conversion_descriptor_changed')


def conversion_projection(result):
    """Persist only closed non-secret facts after parent-side validation."""
    return {
        'descriptors':[{key:row[key] for key in ('id','command_sha256','converted_sha256')}
                       for row in result['descriptors']],
        'loaded_modules':result['loaded_modules'],
        'imported_builtins':result['imported_builtins'],
        'denied_operation_imports':result['denied_operation_imports'],
        'guard_probes':result['guard_probes'],
        'node_version':result['node_version'],
        'installer_invoked':False,
        'HOME_preserved':True,
        'CODEX_HOME_preserved':True,
    }


def qualify(tarball, node):
    contract = load_contract()
    node = node.resolve(strict=True)
    node_raw = regular_bytes(node, 128*1024*1024)
    raw = verified_package(regular_bytes(tarball, MAX_COMPRESSED),contract)
    runner = bounded_runner()
    parent = '/private/tmp' if sys.platform == 'darwin' else '/tmp'
    with tempfile.TemporaryDirectory(prefix='personal-gsd-text-',dir=parent) as temporary:
        root = Path(temporary)
        inventory = {}
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            for member in validated_members(archive,contract['package_entries']):
                relative = str(PurePosixPath(member.name).relative_to('package'))
                path = root/relative
                missing = []; parent_path = path.parent
                while parent_path != root and not parent_path.exists():
                    missing.append(parent_path); parent_path = parent_path.parent
                for parent_path in reversed(missing):
                    parent_path.mkdir(mode=0o700)
                body = archive.extractfile(member).read()
                if len(body) != member.size:
                    raise ValueError('gsd_package_truncated')
                fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(body)
                inventory[relative] = digest(body)
        for skill in SKILLS:
            expected = contract['descriptors'][skill]
            if (inventory.get(f'skills/{skill}/SKILL.md') != expected['raw_skill_sha256']
                    or inventory.get(f'commands/gsd/{skill[4:]}.md') != expected['command_sha256']):
                raise ValueError('gsd_package_descriptor_changed')
        argv = [str(node),'--permission',f'--allow-fs-read={root}',
                f'--allow-fs-read={HERE/HARNESS_NAME}',str(HERE/HARNESS_NAME),str(root)]
        code, stdout, stderr = runner(argv,root)
        if code != 0 or stderr:
            raise ValueError('gsd_conversion_process_failed')
        result = strict_json(stdout)
        validate_conversion(result,contract)
        loaded = result['loaded_modules']
        if not isinstance(loaded,list) or len(set(loaded)) != len(loaded) or not loaded:
            raise ValueError('gsd_conversion_modules_invalid')
        if any(name not in inventory or name == 'bin/install.js' for name in loaded):
            raise ValueError('gsd_conversion_modules_outside_package')
        if any(digest(regular_bytes(root/name,MAX_MEMBER)) != expected for name,expected in inventory.items()):
            raise ValueError('gsd_package_reference_changed')
        result = conversion_projection(result)
        result['loaded_module_sha256'] = {name:inventory[name] for name in loaded}
        result.update(schema='personal-portability/gsd-codex-text-observation/v1',
            package=PACKAGE,version=VERSION,git_commit=COMMIT,npm_integrity=INTEGRITY,
            node_sha256=digest(node_raw),files_verified=len(inventory),
            source_contract_sha256=digest(regular_bytes(HERE/CONTRACT_NAME,65536)),
            raw_descriptor_texts_verified=True,native_path_rewriting_qualified=False,
            authoring_transaction_or_host_qualified=False,native_publication_authorized=False,
            legacy_M1_record_replaced=False,full_active_v2_accepted=False)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tarball',required=True,type=Path)
    parser.add_argument('--node',required=True,type=Path)
    args = parser.parse_args(argv)
    try:
        result = qualify(args.tarball,args.node)
    except (ValueError,OSError,tarfile.TarError) as exc:
        print(json.dumps({'status':'unavailable','reason':str(exc) if isinstance(exc,ValueError) else 'gsd_source_input_unavailable',
                          'native_publication_authorized':False}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
