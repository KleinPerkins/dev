#!/usr/bin/env python3
"""Temporary native Theme Factory qualification for the exact personal pin.

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
TRANSACTION_SHA256 = 'a4dbdd3f7fef1ea431c56fa0d0db79a74796962cd1fad4f971d4c2c10cbc6bb4'
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

SKILLS = ('theme-factory',)
PIN = 'f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a'
PAYLOAD = '8e2f1086a517b71c91beb0ddfb8f788c1164928b2113e33c9464ba4341bfd211'
FILE_COUNT = 15
WORKER = dict(WORKER)
HELPERS = dict(HELPERS)
SCHEMA = 'interoperability/theme-factory-canary/v1'
FIXTURE = HERE / 'fixtures/theme-factory-canary'
FIXTURE_FILES = ('fixture.py', 'source-notes.json', 'workload.json')
OUTPUTS = ('botanical.html', 'awaiting-selection.md', 'custom-theme.json', 'worker-notes.md')


def implementation():
    rows = {'theme_factory_canary.py': sha(regular(Path(__file__).absolute()))}
    if sha(regular(HERE / 'selected_skill_canary.py')) != TRANSACTION_SHA256:
        raise ValueError('accepted temporary publication transaction changed')
    rows['selected_skill_canary.py'] = TRANSACTION_SHA256
    for name, digest in HELPERS.items():
        if sha(regular(HERE / name)) != digest:
            raise ValueError('accepted transaction dependency changed')
        rows[name] = digest
    for name in FIXTURE_FILES:
        rows['fixtures/theme-factory-canary/' + name] = sha(regular(FIXTURE / name))
    return sha(canonical(rows))


def source_proof(home, manifest):
    binding = atom.shared.portability_manifest_proof(manifest)
    primary = atom.shared.pinned_primary_observation(home, binding)
    root = home / 'dev/capabilities/skills'
    prefix = 'global/skills/theme-factory'
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
            raise ValueError('Theme Factory payload escaped its exact regular-file scope')
        data = regular(root / path)
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
            raise ValueError('Theme Factory tracked source changed')
        rows.append({'path': path, 'mode': mode, 'git_blob': blob, 'sha256': sha(data)})
    if len(rows) != FILE_COUNT or sha(canonical(rows)) != PAYLOAD:
        raise ValueError('Theme Factory fifteen-file payload does not match its exact pin')
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
        raise ValueError('unreviewed Theme Factory file or directory')
    return {'manifest': binding, 'primary': primary, 'payload_sha256': PAYLOAD,
            'file_count': FILE_COUNT, 'desired': {'theme-factory': str(root / prefix)},
            'local_dependencies': local_dependencies(home)}

FONT_ROOT = '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources'
FONT_FILES = {
    'fonts/truetype/DejaVuSerif-Bold.ttf': 'c47b5527bcdc8dcf9ea8c77054454c5a884beaca2f44851a2a823ee639cbf07f',
    'fonts/truetype/DejaVuSans.ttf': '7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954',
    'LICENSE': '7b3fed10089170d8e68811e59458d421e11d287c988a2bb58aac9cedf488dbbc',
}


def local_dependencies(home):
    fonts = {}
    for relative, digest in FONT_FILES.items():
        path = home / FONT_ROOT / relative
        if sha(regular(path)) != digest:
            raise ValueError('qualified private font input changed')
        fonts[relative] = {'path': str(path), 'state': observation(path)}
    runtime = home / 'dev/capabilities/skills/local/skills/isokit/node_modules/playwright-core'
    digest, count = atom.tree_digest(runtime)
    if digest != atom.RUNTIME or count != 115:
        raise ValueError('existing local browser runtime changed')
    browser_root = home / '.local/share/personal-portability/playwright-browsers'
    directory(browser_root)
    for relative, digest in atom.BROWSER_FILES.items():
        if sha(regular(browser_root / relative)) != digest:
            raise ValueError('existing approved browser helper changed')
    return {'fonts': fonts, 'browser_runtime': str(runtime),
            'browser_runtime_sha256': atom.RUNTIME, 'browser_runtime_files': count,
            'browser_root': str(browser_root), 'browser_files': dict(atom.BROWSER_FILES),
            'downloads_or_system_font_installation_authorized': False}


def target_rows(home, identifier):
    parent = home / '.codex/skills'
    return [{'name': 'theme-factory', 'target': str(parent / 'theme-factory'),
             'staging': str(parent / ('.theme-factory-canary-' + identifier)),
             'desired': str(home / 'dev/capabilities/skills/global/skills/theme-factory')}]


def workload(operation):
    brief = json.loads(regular(FIXTURE / 'workload.json'))
    protocol = {'native_tool': WORKER['native_tool'], 'worker_count': WORKER['count'],
        'requested_model': WORKER['requested_model'], 'reasoning_effort': WORKER['reasoning_effort'],
        'fork_turns': WORKER['fork_turns'], 'immediate_first_wait_ms': WORKER['first_parent_wait_ms'],
        'interrupt_if_unfinished_after_first_wait': True,
        'strict_actual_worker_deadline_ms': WORKER['hard_deadline_ms'],
        'rollback_after_every_outcome': True, 'retained_installation_authorized': False}
    if (brief.get('schema') != 'interoperability/theme-factory-workload/v1'
            or brief.get('required_skills') != list(SKILLS)
            or canonical(brief.get('parent_protocol')) != canonical(protocol)
            or brief.get('outputs') != list(OUTPUTS)):
        raise ValueError('Theme Factory workload escaped its one-skill/one-worker scope')
    return {'fixture_source_sha256': sha(regular(FIXTURE / 'fixture.py')),
        'brief_sha256': sha(regular(FIXTURE / 'workload.json')),
        'source_notes_sha256': sha(regular(FIXTURE / 'source-notes.json')),
        'private_root': str(operation / 'fixture'), 'outputs': list(OUTPUTS),
        'parent_created_marker': 'fixture-owner.json',
        'semantic_review_required': True, 'automated_shape_checks_are_native_acceptance': False}


if __name__ == '__main__':
    raise SystemExit(main())
