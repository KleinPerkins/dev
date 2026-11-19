#!/usr/bin/env python3
"""Temporary native Canvas Design qualification for the exact personal pin.

One fresh worker and publication require external exact human consent. This
interface never starts that worker, retains a link, or contacts a service.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import types

HERE = Path(__file__).absolute().parent
TRANSACTION_SHA256 = '27cec87c77f7a8e80a69fdd3b5d9ee6d6929f60dc78dae45010896a7e34f2559'
path = HERE / 'selected_skill_canary.py'
if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != TRANSACTION_SHA256:
    raise ValueError('accepted temporary publication transaction changed')
sys.path.insert(0, str(HERE))
import selected_skill_canary as accepted
if Path(accepted.__file__).absolute() != path:
    raise ValueError('temporary publication transaction imported from another root')

# Bind the accepted transaction function bodies to this one closed profile.
# No accepted module globals or prior profile functions are modified. Functions
# share this module's namespace so its fixed paths and independent proof methods
# govern preview, load, apply, verify and exact rollback together.
for name, value in vars(accepted).items():
    if name.startswith('__'):
        continue
    if isinstance(value, types.FunctionType) and value.__module__ == accepted.__name__:
        globals()[name] = types.FunctionType(value.__code__, globals(), name,
            value.__defaults__, value.__closure__)
        globals()[name].__kwdefaults__ = value.__kwdefaults__
    else:
        globals()[name] = value

SKILLS = ('canvas-design',)
PIN = 'f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a'
PAYLOAD = 'e7606384d57bd226a3223096ab3827d37b2de6001eccda26015ed0b7be81215e'
FILE_COUNT = 85
WORKER = dict(WORKER)
HELPERS = dict(HELPERS)
SCHEMA = 'interoperability/canvas-design-canary/v1'
FIXTURE = HERE / 'fixtures/canvas-design-canary'
FIXTURE_FILES = ('fixture.py', 'source-notes.json', 'workload.json')
OUTPUTS = ('philosophy.md', 'artwork.pdf', 'worker-notes.md')


def implementation():
    rows = {'canvas_design_canary.py': sha(regular(Path(__file__).absolute()))}
    if sha(regular(HERE / 'selected_skill_canary.py')) != TRANSACTION_SHA256:
        raise ValueError('accepted temporary publication transaction changed')
    rows['selected_skill_canary.py'] = TRANSACTION_SHA256
    for name, digest in HELPERS.items():
        if sha(regular(HERE / name)) != digest:
            raise ValueError('accepted transaction dependency changed')
        rows[name] = digest
    for name in FIXTURE_FILES:
        rows['fixtures/canvas-design-canary/' + name] = sha(regular(FIXTURE / name))
    return sha(canonical(rows))


def source_proof(home, manifest):
    binding = atom.shared.portability_manifest_proof(manifest)
    primary = atom.shared.pinned_primary_observation(home, binding)
    root = home / 'dev/capabilities/skills'
    prefix = 'global/skills/canvas-design'
    rows = []
    for raw in atom.shared.git_bytes(root, 'ls-tree', '-rz', PIN, '--', prefix).split(b'\0'):
        if not raw:
            continue
        meta, raw_path = raw.split(b'\t', 1)
        mode, kind, blob = meta.decode('ascii').split()
        path = raw_path.decode('utf-8')
        parts = path.split('/')
        if (kind != 'blob' or mode not in {'100644', '100755'}
                or not path.startswith(prefix + '/') or any(p in {'', '.', '..'} for p in parts)):
            raise ValueError('Canvas Design payload escaped its exact regular-file scope')
        data = regular(root / path)
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
            raise ValueError('Canvas Design tracked source changed')
        rows.append({'path': path, 'mode': mode, 'git_blob': blob, 'sha256': sha(data)})
    if len(rows) != FILE_COUNT or sha(canonical(rows)) != PAYLOAD:
        raise ValueError('Canvas Design eighty-five-file payload does not match its exact pin')
    expected_files = {r['path'] for r in rows}
    expected_dirs = {'.'}
    for name in expected_files:
        relative = Path(name).relative_to(prefix)
        expected_dirs.update(str(p) for p in relative.parents)
    found, found_dirs = set(), set()
    for parent, dirs, files in os.walk(root / prefix, followlinks=False):
        parent = Path(parent)
        directory(parent)
        found_dirs.add(str(parent.relative_to(root / prefix)))
        for name in dirs:
            directory(parent / name)
        for name in files:
            regular(parent / name)
            found.add(str((parent / name).relative_to(root)))
    if found != expected_files or found_dirs != expected_dirs:
        raise ValueError('unreviewed Canvas Design file or directory')
    return {'manifest': binding, 'primary': primary, 'payload_sha256': PAYLOAD,
            'file_count': FILE_COUNT, 'desired': {'canvas-design': str(root / prefix)},
            'local_dependencies': local_dependencies(home)}

FONT_FILES = {
    'InstrumentSans-Regular.ttf': 'a22cb26e48fd79bcb01bf2fc92d36785474dce36d9c544ab0a8868c2657c4a87',
    'InstrumentSans-OFL.txt': 'bf4dc6d13a8cccd4807133c77a1ee9619a16b92cb23322258725ab6731c2f6e5',
    'GeistMono-Regular.ttf': 'a55c1b51cda4afeab9e471e7947b85a20f7c8831d7e6b1470c1b7fbdc0f0f15e',
    'GeistMono-OFL.txt': '6a873c900f584109b13ae0aaf81d6e3cf0a68751a216b03f7b6c68d547057bb4',
}

PDF_ROOT = '.cache/codex-runtimes/codex-primary-runtime/dependencies'
PDF_PYTHON = 'python/bin/python3.12'
PDF_PYTHON_SHA256 = '0048df8bc66cbf4cc964f31eb89321e762902aeecf95dfbde306a36601d27034'
PDF_TREES = {'python/lib/python3.12/site-packages/pypdf': {'sha256': '59ad62e4e95beef2c1aa042ddd6ed9437cd3dd4c603ad1cdb753f20588c0ac2e', 'files': 111}, 'python/lib/python3.12/site-packages/reportlab': {'sha256': '458a3925316fdec2c0a698dc2a7b8874c86d24c56f33f6c5aab8ebdb499ce76c', 'files': 350}, 'python/lib/python3.12/site-packages/PIL': {'sha256': '4578a5668502fdd555ca862531dcbe08780945e3c667143ee1998233b50523b0', 'files': 229}, 'python/lib/python3.12/site-packages/pypdfium2': {'sha256': 'b3c13ca79f5cc45b32be87c1a837588a3596e890ed7cd198488838164394ec35', 'files': 43}, 'python/lib/python3.12/site-packages/pypdfium2_raw': {'sha256': '7740c2bc0ca25dca5d2ca32f076736fd2815c2fcdd95a8db6e947555fc464e1d', 'files': 8}}


def dependency_file(path):
    atom.shared.no_symlink_components(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid() or before.st_size > 64 * 1024 * 1024:
            raise ValueError('bounded original public PDF dependency required')
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        data = bytearray()
        while block := os.read(fd, 65536):
            data.extend(block)
            if len(data) > before.st_size:
                raise ValueError('PDF dependency exceeded its observed bound')
        if identity(before) != identity(os.fstat(fd)) or identity(before) != identity(path.lstat()) or len(data) != before.st_size:
            raise ValueError('PDF dependency changed during read')
        return bytes(data)
    finally:
        os.close(fd)


def dependency_tree(root):
    original = directory(root)
    rows = {}
    directories = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        parent = Path(parent)
        directories[str(parent.relative_to(root))] = directory(parent)
        for name in dirs:
            directory(parent / name)
        for name in files:
            path = parent / name
            rows[str(path.relative_to(root))] = sha(dependency_file(path))
    if original != directory(root):
        raise ValueError('PDF package root changed during observation')
    for relative, state in directories.items():
        if state != directory(root / relative):
            raise ValueError('PDF package ancestor changed during observation')
    return sha(canonical(rows)), len(rows), original


def local_dependencies(home):
    root = home / 'dev/capabilities/skills/global/skills/canvas-design/canvas-fonts'
    fonts = {}
    for name, digest in FONT_FILES.items():
        path = root / name
        if sha(regular(path)) != digest:
            raise ValueError('pinned canvas font or full license changed')
        fonts[name] = {'path': str(path), 'state': observation(path)}
    backend = home / PDF_ROOT
    interpreter = backend / PDF_PYTHON
    if sha(dependency_file(interpreter)) != PDF_PYTHON_SHA256:
        raise ValueError('compiled existing PDF interpreter changed')
    packages = {}
    for relative, expected in PDF_TREES.items():
        digest, count, state = dependency_tree(backend / relative)
        if digest != expected['sha256'] or count != expected['files']:
            raise ValueError('compiled existing PDF package tree changed')
        packages[relative] = {'sha256': digest, 'files': count, 'root': state}
    return {'fonts': fonts, 'PDF_interpreter': {'path': str(interpreter), 'state': observation(interpreter)},
            'backend_package_trees': packages, 'PDF_render_backend': 'pypdfium2',
            'downloads_or_system_font_installation_authorized': False,
            'whole_OS_arbitrary_workload_or_native_qualification_proven': False}


def target_rows(home, identifier):
    parent = home / '.codex/skills'
    return [{'name': 'canvas-design', 'target': str(parent / 'canvas-design'),
             'staging': str(parent / ('.canvas-design-canary-' + identifier)),
             'desired': str(home / 'dev/capabilities/skills/global/skills/canvas-design')}]


def workload(operation):
    brief = json.loads(regular(FIXTURE / 'workload.json'))
    protocol = {'native_tool': WORKER['native_tool'], 'worker_count': WORKER['count'],
        'requested_model': WORKER['requested_model'], 'reasoning_effort': WORKER['reasoning_effort'],
        'fork_turns': WORKER['fork_turns'], 'immediate_first_wait_ms': WORKER['first_parent_wait_ms'],
        'interrupt_if_unfinished_after_first_wait': True,
        'strict_actual_worker_deadline_ms': WORKER['hard_deadline_ms'],
        'rollback_after_every_outcome': True, 'retained_installation_authorized': False}
    if (brief.get('schema') != 'interoperability/canvas-design-workload/v1'
            or brief.get('required_skills') != list(SKILLS)
            or canonical(brief.get('parent_protocol')) != canonical(protocol)
            or brief.get('outputs') != list(OUTPUTS)):
        raise ValueError('Canvas Design workload escaped its one-skill/one-worker scope')
    return {'fixture_source_sha256': sha(regular(FIXTURE / 'fixture.py')),
        'brief_sha256': sha(regular(FIXTURE / 'workload.json')),
        'source_notes_sha256': sha(regular(FIXTURE / 'source-notes.json')),
        'private_root': str(operation / 'fixture'), 'outputs': list(OUTPUTS),
        'parent_created_marker': 'fixture-owner.json',
        'semantic_review_required': True, 'automated_shape_checks_are_native_acceptance': False}


if __name__ == '__main__':
    raise SystemExit(main())
