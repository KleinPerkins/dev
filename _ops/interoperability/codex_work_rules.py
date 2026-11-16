"""Personal Codex work-dispatch projection; no launch or activation authority.

Only an owner-listed accepted source/build/profile may be projected. An empty
binding registry is intentionally unavailable. Same-user records are drift
hygiene, not signed attestations. The native_rules transaction owns publication.
"""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = 'codex-work-dispatch'
PROFILE = 'collaboration.spawn_agent'
CHECK = 'CWA-01-collaboration-native-screen'
PREFIX = 'global/rules/subagent-orchestration/'
FILES = tuple(PREFIX + name for name in ('codex_dispatch.py', 'codex-work-policy.json', 'CODEX-DISPATCH.md'))
HOST_INFO = Path('/Applications/ChatGPT.app/Contents/Info.plist')
HOST_CLI = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError('closed work-dispatch contract required')


def read_json(data):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate work-dispatch JSON key')
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=unique)


def regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('linked work-dispatch source refused')
    import stat
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('unshared regular work-dispatch file required')
    return path.read_bytes()


def registry():
    value = read_json(regular(ROOT / '_ops/interoperability/evidence/codex-work-activation-bindings.json'))
    closed(value, 'schema bindings')
    if value['schema'] != 'interoperability/codex-work-activation-bindings/v1' or not isinstance(value['bindings'], list):
        raise ValueError('unknown work-dispatch binding registry')
    seen = set()
    for row in value['bindings']:
        closed(row, 'source_revision payload_sha256 native_tool host_build host_info_sha256 host_cli_sha256 qualification_sha256')
        for key, length in (('source_revision', 40), ('payload_sha256', 64), ('host_info_sha256', 64),
                            ('host_cli_sha256', 64), ('qualification_sha256', 64)):
            if not isinstance(row[key], str) or not re.fullmatch('[0-9a-f]{%d}' % length, row[key]):
                raise ValueError('invalid work-dispatch binding digest')
        if row['native_tool'] != PROFILE or not isinstance(row['host_build'], str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', row['host_build']):
            raise ValueError('unsupported work-dispatch binding profile/build')
        key = (row['source_revision'], row['native_tool'], row['host_build'])
        if key in seen:
            raise ValueError('ambiguous work-dispatch binding')
        seen.add(key)
    return value['bindings']


def prepare(source, build):
    source = Path(source).absolute()
    if not build:
        raise ValueError('current host build required')
    receipt_bytes = regular(source / '.source-export.json')
    receipt = read_json(receipt_bytes)
    closed(receipt, 'schema repository revision accepted files')
    if (receipt['schema'] != 'interoperability/codex-work-source-export/v1' or
            receipt['repository'] != 'KleinPerkins/skills' or receipt['accepted'] is not True or
            not isinstance(receipt['revision'], str) or not re.fullmatch('[0-9a-f]{40}', receipt['revision'])):
        raise ValueError('accepted Skills work-dispatch export required')
    matches = [row for row in registry() if row['source_revision'] == receipt['revision'] and row['host_build'] == build]
    if len(matches) != 1:
        raise ValueError('one accepted source/profile/build binding required; qualification unavailable')
    binding = matches[0]
    if not isinstance(receipt['files'], dict) or set(receipt['files']) != set(FILES):
        raise ValueError('exact work-dispatch source closure required')
    observed = {}
    for name in FILES:
        data = regular(source / name)
        if receipt['files'][name] != sha(data):
            raise ValueError('work-dispatch source export changed')
        observed[Path(name).name] = sha(data)
    if sha(canonical(observed)) != binding['payload_sha256']:
        raise ValueError('work-dispatch payload differs from accepted binding')
    info = regular(HOST_INFO)
    if (str(plistlib.loads(info).get('CFBundleVersion')) != build or sha(info) != binding['host_info_sha256'] or
            sha(regular(HOST_CLI)) != binding['host_cli_sha256']):
        raise ValueError('current native host/build bytes differ from accepted binding')
    template = regular(ROOT / '_ops/rules/hosts/codex-work-dispatch.md')
    interpreter = str(Path(sys.executable).resolve())
    command = shlex.quote(interpreter) + ' ' + shlex.quote(str(source / FILES[0]))
    if any(c in command for c in ('\n', '\r', '`')):
        raise ValueError('unsafe instruction command path')
    body = template.decode('utf-8')
    replacements = {'{{dispatch_command}}': command, '{{source_revision}}': receipt['revision'],
                    '{{payload_sha256}}': binding['payload_sha256']}
    for key, value in replacements.items():
        if body.count(key) != 1:
            raise ValueError('work-dispatch template slot changed')
        body = body.replace(key, value)
    if '{{' in body or '}}' in body:
        raise ValueError('unknown work-dispatch template slot')
    body = body.rstrip() + '\n'
    block = (f'<!-- BEGIN {MARKER} (managed by KleinPerkins/dev) -->\n'
             f'<!-- sha256:{sha(body.encode())} | codex-work-dispatch/v1 -->\n' + body +
             f'<!-- END {MARKER} -->\n')
    return dict(schema='interoperability/codex-work-rule-preparation/v1', host='codex',
                activation='candidate-requires-exact-preview-consent', native_tool=PROFILE,
                resolver=dict(repository='KleinPerkins/skills', revision=receipt['revision'],
                              payload_sha256=binding['payload_sha256']), binding=binding,
                source=str(source), source_export_sha256=sha(receipt_bytes),
                interpreter=interpreter, interpreter_sha256=sha(regular(interpreter)),
                template_sha256=sha(template), blocks={MARKER: block})


def qualified(path, build, prepared, *, validator):
    data = regular(path)
    if sha(data) != prepared['binding']['qualification_sha256']:
        raise ValueError('native qualification differs from accepted owner binding')
    rows = read_json(data)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError('one exact work-dispatch qualification required')
    row = validator.validate(rows[0])
    expected = dict(capability='codex-work-dispatch', owner='KleinPerkins/skills', check=CHECK,
                    host='codex', surface='local-macos-desktop', outcome='pass',
                    source_revision=prepared['resolver']['revision'], adapter_revision=prepared['resolver']['revision'],
                    payload_sha256=prepared['resolver']['payload_sha256'], host_build=build)
    if any(row[key] != value for key, value in expected.items()):
        raise ValueError('current native work-dispatch qualification required')
    forbidden = {'native-not-observed', 'fixture-only', 'host-build-unavailable', 'source-drift',
                 'source-merge-pending', 'owner-decision-required', 'account-unverified'}
    if forbidden.intersection(row['limitations']):
        raise ValueError('qualification has unresolved native/source limitations')
    return sha(data)


def project(existing, blocks):
    """Keep unmanaged bytes. Refuse coexistence with conflicting managed routing."""
    if set(blocks) != {MARKER}:
        raise ValueError('one work-dispatch block required')
    for old in ('cursor-rules-mirror', 'native-entry-routing/v1'):
        if old in existing:
            raise ValueError('existing legacy routing needs a separate owner transition')
    begin = f'<!-- BEGIN {MARKER} (managed by KleinPerkins/dev) -->'
    end = f'<!-- END {MARKER} -->'
    if existing.count(begin) != existing.count(end) or existing.count(begin) > 1:
        raise ValueError('ambiguous work-dispatch markers')
    if begin not in existing:
        return existing + ('\n' if existing and not existing.endswith('\n') else '') + blocks[MARKER]
    start, last = existing.index(begin), existing.index(end)
    if last < start:
        raise ValueError('reversed work-dispatch markers')
    stop = last + len(end)
    if existing[stop:stop + 1] == '\n':
        stop += 1
    return existing[:start] + blocks[MARKER] + existing[stop:]
