"""Source-owned rule preparation with an explicit INT-007B Codex candidate mode.

Inputs are explicit owner source roots. Installed Cursor files are never inputs.
This pure renderer never installs; legacy preparation keeps activation withheld.
"""
import argparse
import hashlib
import json
from pathlib import Path

MARKERS = ('dev-operating-model', 'cursor-rules-mirror', 'cursor-mcp-safety-mirror')
SERVICES = ('Notion', 'jira', 'slack', 'snowflake')

# This closed source slot is intentionally exact: an owner edit requires a
# coordinated renderer/test update, never a best-effort translation.
HOST_ENTRY_EXCLUSIONS = 'Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks).'
HOST_ENTRY = (
    '- For Codex, inspect native attachments and create/attach the appropriate worktree; '
    'verify the returned root, branch, Git directories and writer before mutation. '
    'A printed helper path is not native attachment or AWA protection. '
    + HOST_ENTRY_EXCLUSIONS + ' Preserve owner exclusions and separate indexes.'
)


def rule(path):
    return parse_rule(path.read_text())


def parse_rule(text):
    if not text.startswith('---\n'):
        raise ValueError('rule requires source frontmatter')
    header, body = text[4:].split('\n---\n', 1)
    metadata = {}
    for line in header.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            if key.strip() in metadata:
                raise ValueError('duplicate source metadata')
            metadata[key.strip()] = value.strip()
    return metadata, body.strip() + '\n'


def block(name, body):
    sha = hashlib.sha256(body.encode()).hexdigest()
    return (f'<!-- BEGIN {name} (managed by KleinPerkins/dev) -->\n'
            f'<!-- sha256:{sha} | prepared from owner sources; INT-007B activation required -->\n'
            + body + f'<!-- END {name} -->\n')


def prepare(dev, skills, awa, host, *, native_codex=False):
    if host not in ('cursor', 'codex', 'claude'):
        raise ValueError('unsupported host')
    if native_codex and host != 'codex':
        raise ValueError('native entry is Codex-only')
    expected = {'terse-output.mdc', 'worktree-default.mdc', *(name + '-mcp-safety.mdc' for name in SERVICES)}
    if {p.name for p in (dev / '_ops/rules/global').glob('*.mdc')} != expected:
        raise ValueError('unclassified or missing owner rule source')
    if {str(p.relative_to(skills / 'global/rules')) for p in (skills / 'global/rules').rglob('*.mdc')} != {'subagent-orchestration/subagent-orchestration.mdc'}:
        raise ValueError('unclassified or missing reusable rule source')
    sources = []
    def read(path, owner, applicability):
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing or linked owner source')
        data = path.read_bytes()
        sources.append(dict(owner=owner, path=str(path), sha256=hashlib.sha256(data).hexdigest(), applicability=applicability))
        return data.decode('utf-8')
    context = read(dev / '_ops/rules/agent-context.md', 'KleinPerkins/dev', 'shared-with-host-entry-slot')
    pending = []
    if host == 'codex':
        lines = context.splitlines(keepends=True)
        found = [i for i, line in enumerate(lines)
                 if line.startswith(('- For Codex, ', '- Start governed repo mutation from the Cursor '))]
        if len(found) != 1 or lines[found[0]].rstrip('\n') != HOST_ENTRY:
            raise ValueError('host entry source preimage changed')
        # Native preparation retains the current owner instruction verbatim.
        # Preview still withholds entry/routing, including for native-worded SOT.
        if not native_codex:
            lines[found[0]] = ('- Native Codex entry is withheld in this preparation preview. '
                               'INT-007B requires qualified routing, writer isolation, and the native workspace canary. '
                               'Only the accepted scoped bootstrap is currently authorized. '
                               + HOST_ENTRY_EXCLUSIONS + '\n')
            context = ''.join(lines)
            pending += ['native-entry:INT-007B', 'native-routing:INT-009']
    behavioral = []
    operator = read(awa / 'consumer/operator-skill.md', 'KleinPerkins/awa', 'owner-qualified-operation-only')
    if host == 'codex':
        operator = ('AWA registration is unsupported under the current accepted identity contract. Native attachment is not AWA registration or protection. The following owner rules preserve authorization boundaries; their presence does not qualify an operation.\n\n' + operator)
    behavioral.append(('awa-operator', operator.strip() + '\n'))
    for name, path, owner, applicability in [
        ('terse-output', dev / '_ops/rules/global/terse-output.mdc', 'KleinPerkins/dev', 'shared'),
        ('worktree-default', dev / '_ops/rules/global/worktree-default.mdc', 'KleinPerkins/dev', 'host-specific'),
        ('subagent-orchestration', skills / 'global/rules/subagent-orchestration/subagent-orchestration.mdc', 'KleinPerkins/skills', 'host-specific'),
    ]:
        metadata, body = parse_rule(read(path, owner, applicability))
        if metadata.get('alwaysApply') != 'true':
            raise ValueError('behavioral source applicability changed')
        if host == 'codex' and applicability == 'host-specific':
            if not native_codex:
                continue  # Never translate a Cursor command by renaming its product.
            if name == 'worktree-default':
                start, end = '## Required behavior\n', '\nThe helper cannot move the current Cursor agent.'
                if body.count(start) != 1 or body.count(end) != 1 or body.index(start) >= body.index(end):
                    raise ValueError('shared worktree section contract changed')
                shared = body[body.index(start):body.index(end)].rstrip()
                native = read(dev / '_ops/rules/hosts/codex-entry.md', 'KleinPerkins/dev', 'codex-native-entry')
                if native.count('{{shared_worktree_behavior}}') != 1:
                    raise ValueError('shared worktree slot changed')
                body = native.replace('{{shared_worktree_behavior}}', shared)
            else:
                start, end = '## Model Choice\n', '## Sync Or Async\n'
                if body.count(start) != 1 or body.count(end) != 1 or body.index(start) >= body.index(end):
                    raise ValueError('shared orchestration section contract changed')
                native = read(dev / '_ops/rules/hosts/codex-routing.md', 'KleinPerkins/dev', 'codex-native-resolver-reference')
                body = body[:body.index(start)] + native.rstrip() + '\n\n' + body[body.index(end):]
        behavioral.append((name, body))
    behavior = ''.join(f'### {name}\n\n{body}\n' for name, body in sorted(behavioral))
    conditional = ''
    for service in SERVICES:
        path = dev / f'_ops/rules/global/{service}-mcp-safety.mdc'
        metadata, body = parse_rule(read(path, 'KleinPerkins/dev', 'conditional-service-policy'))
        if metadata.get('alwaysApply') != 'false' or not metadata.get('description'):
            raise ValueError('conditional source applicability changed')
        conditional += f'### {service}-mcp-safety\n\n**Apply only when:** {metadata["description"]}\n\n{body}\n'
    blocks = {MARKERS[0]: block(MARKERS[0], context),
              MARKERS[1]: block(MARKERS[1], behavior),
              MARKERS[2]: block(MARKERS[2], conditional)}
    if native_codex:
        blocks = {key: value.replace('prepared from owner sources; INT-007B activation required',
                  'native-entry-routing/v1; generated from owner sources') for key, value in blocks.items()}
    return dict(schema='interoperability/rule-preparation/v1', host=host,
                activation='native-candidate' if native_codex else 'withheld-INT-007B', pending=pending, sources=sources, blocks=blocks)


def project(existing, blocks):
    """Pure managed-block preview; preserve every byte outside owned blocks."""
    if not set(blocks) <= set(MARKERS):
        raise ValueError('unknown managed block')
    intervals = []
    absent = []
    for name in MARKERS:
        begin = f'<!-- BEGIN {name} (managed by KleinPerkins/dev) -->'
        end = f'<!-- END {name} -->'
        if existing.count(begin) != existing.count(end) or existing.count(begin) > 1:
            raise ValueError('ambiguous existing managed blocks')
        if begin not in existing:
            if name in blocks:
                absent.append(name)
            continue
        start, last = existing.index(begin), existing.index(end)
        if last < start:
            raise ValueError('reversed managed block')
        stop = last + len(end)
        if existing[stop:stop+1] == '\n':
            stop += 1
        intervals.append((start, stop, name))
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError('overlapping managed blocks')
    result = existing
    for start, stop, name in reversed(intervals):
        if name in blocks:
            result = result[:start] + blocks[name] + result[stop:]
    for name in absent:
        result += ('\n' if result and not result.endswith('\n') else '') + blocks[name]

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dev', 'skills', 'awa'):
        parser.add_argument('--' + name + '-source', type=Path, required=True)
    parser.add_argument('--host', choices=('cursor', 'codex', 'claude'), required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.dev_source, args.skills_source, args.awa_source, args.host), indent=2))
