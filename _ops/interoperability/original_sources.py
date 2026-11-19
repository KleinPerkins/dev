"""Live routing for retained private source histories; never successor admission.

Historical owner labels and object pins remain unchanged. GitHub's immutable ID
selects the live endpoint; its observed name must be an explicitly allowed phase.
Live discovery requires the fixed original ID and allowed endpoint. Established
local consumption stays offline under the owner-approved local Git trust boundary;
its endpoint, object and ancestry checks do not authenticate a GitHub repository ID
against an actor deliberately rewriting that trusted local history or source.
"""
import argparse
import functools
import hashlib
import os
import stat
import tomllib
import json
from pathlib import Path
import subprocess

import inventory

# These existing object pins witness retained history during offline use.
# They are not a general-bootstrap execution-version approval list.
ANCHORS = {
    'KleinPerkins/skills': 'bc58eb77f442307ab4f124ab5aeec3f99571cb21',
    'KleinPerkins/kp-mcp': '7594346fbb09161749d21624b35cf5a173c84958',
}

ORIGINALS = {
    'KleinPerkins/skills': (1275604090, 'KleinPerkins/skills-private-original'),
    'KleinPerkins/kp-mcp': (1271164179, 'KleinPerkins/kp-mcp-private-original'),
}


def source_errors(function):
    """Keep operational failures in the public verifier's fail-closed channel."""
    @functools.wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, subprocess.SubprocessError, UnicodeError, IndexError, RuntimeError):
            raise ValueError('original source verification unavailable; source preserved') from None
    return checked


def git_result(root, *args):
    # Inspect the actual local object graph, without replace refs, grafts,
    # commit-graph shortcuts, caller Git routing, or implicit object fetches.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_GRAFT_FILE=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    return subprocess.run(['git', '--no-replace-objects', '-c', 'core.commitGraph=false',
                           '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                          env=env, capture_output=True, timeout=15)


def local_git(root, *args):
    result = git_result(root, *args)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def endpoint(owner):
    identity, retained = ORIGINALS[owner]
    try:
        # The immutable IDs belong to github.com, irrespective of a caller's
        # enterprise/default-host selection. Existing local reads stay offline.
        env = {key: value for key, value in os.environ.items() if key != 'GH_HOST'}
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com', f'/repositories/{identity}'],
                                env=env, capture_output=True, text=True, timeout=30, check=True)
        row = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('original source identity unavailable') from None
    if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != identity or
            row.get('full_name') not in (owner, retained) or row.get('private') is not True):
        raise ValueError('original source identity mismatched')
    return row['full_name']


def verify_url(remote, owner):
    name = inventory.identity(remote)
    if name not in (owner, ORIGINALS[owner][1]):
        raise ValueError('original source endpoint mismatched')
    if name != endpoint(owner):
        raise ValueError('stale original source endpoint; explicit owner transition required')
    return name


@source_errors
def verify_repository(root, owner, *, revision=None):
    """Check trusted-local endpoint/object continuity, without a remote-ID claim.

    Only endpoint() establishes the live immutable GitHub ID. Existing local Git
    and exact-object exports remain owner-trusted inputs; deliberate local-history
    fabrication is outside this accidental-substitution compatibility boundary.
    """
    name = inventory.identity(local_git(root, 'remote', 'get-url', 'origin'))
    if local_git(root, 'rev-parse', '--show-toplevel') is None or name not in (owner, ORIGINALS[owner][1]):
        raise ValueError('original source identity unavailable, excluded, or mismatched')
    # Inspect every configured fetch and push URL, including multiple values.
    rows = local_git(root, 'config', '--get-regexp', r'remote\..*\.(url|pushurl)') or ''
    urls = [line.split(None, 1)[1] for line in rows.splitlines()]
    if not urls or any(inventory.identity(url) != name for url in urls):
        raise ValueError('original source remote identity mismatched or stale')
    # get-url also applies Git insteadOf/pushInsteadOf rewrites.
    for direction in ((), ('--push',)):
        expanded = local_git(root, 'remote', 'get-url', *direction, '--all', 'origin')
        if not expanded or any(inventory.identity(url) != name for url in expanded.splitlines()):
            raise ValueError('original source effective remote identity mismatched')
    anchor = revision or ANCHORS[owner]
    if local_git(root, 'rev-parse', '--verify', anchor + '^{commit}') != anchor:
        raise ValueError('original source pinned object unavailable')
    return name


# These are the source roots read by the existing Skills bootstrap. MCP's uv
# workspace and per-kit installers can consume arbitrary repository files.
BOOTSTRAP_ROOTS = {'KleinPerkins/skills': ('bootstrap.sh', 'scripts', 'global', 'local'),
                   'KleinPerkins/kp-mcp': ('',)}


# Only these owner-defined local-jobs view artifacts are runtime data rather
# than bootstrap/import source. Other ignored files remain unverified source.
DASHBOARD_TEMPLATE = 'global/skills/local-jobs/canvases/local-jobs-dashboard.template.tsx'
DASHBOARD_LIVE = 'global/skills/local-jobs/canvases/local-jobs-dashboard.generated.canvas.tsx'
DASHBOARD_STATE = frozenset((DASHBOARD_LIVE,
    'global/skills/local-jobs/canvases/local-jobs-dashboard.generated.canvas.data.json',
    'global/skills/local-jobs/canvases/local-jobs-dashboard.canvas.data.json'))


def verify_dashboard_state(path, relative, template_bytes):
    """Accept the existing emitter's exact data envelope, never arbitrary TSX."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o111:
        raise ValueError('dashboard state must be regular non-executable data; source preserved')
    if template_bytes is None:
        raise ValueError('dashboard state lacks its verified tracked template; source preserved')
    try:
        text = path.read_text(encoding='utf-8')
        if relative == DASHBOARD_LIVE:
            template = template_bytes.decode('utf-8')
            marker = '__DASHBOARD_JSON__'
            if template.count(marker) != 1:
                raise ValueError
            prefix, suffix = template.split(marker)
            if not text.startswith(prefix) or not text.endswith(suffix):
                raise ValueError
            end = len(text) - len(suffix) if suffix else len(text)
            payload = json.loads(text[len(prefix):end])
            if not isinstance(payload, dict) or payload.get('schema') != 'dashboard/v1':
                raise ValueError
            expected = template.replace(marker, json.dumps(payload, indent=2, ensure_ascii=True), 1)
            if text != expected:
                raise ValueError
        elif not isinstance(json.loads(text), dict):
            raise ValueError
    except (UnicodeError, ValueError):
        raise ValueError('unverified dashboard state refused; source preserved') from None


def verify_mcp_runtime_contract(root, project_bytes, lock_bytes):
    """Keep the existing uv-owned environment outside Git-source qualification.

    The tracked virtual workspace and unchanged kit installers use only the root
    .venv. Its contents remain host-owned runtime dependencies, not admitted code
    or a new environment-integrity claim from this source verifier.
    """
    try:
        project = tomllib.loads(project_bytes.decode('utf-8'))
        lock = tomllib.loads(lock_bytes.decode('utf-8'))
        uv = project['tool']['uv']
        members = uv['workspace']['members']
        if (uv.get('package') is not False or not isinstance(members, list) or
                any(not isinstance(member, str) or Path(member).is_absolute() or '..' in Path(member).parts
                    for member in members) or type(lock.get('version')) is not int or lock['version'] != 1):
            raise ValueError
    except (AttributeError, KeyError, TypeError, UnicodeError, ValueError):
        raise ValueError('tracked uv workspace contract required; source preserved') from None
    expected = root.resolve()
    for key, target in (('UV_PROJECT_ENVIRONMENT', expected / '.venv'),
                        ('UV_PROJECT', expected), ('UV_WORKING_DIR', expected)):
        if key in os.environ:
            value = Path(os.environ[key])
            candidate = value if value.is_absolute() else expected / value
            if candidate.resolve() != target:
                raise ValueError('uv project/environment redirection refused; runtime preserved')


@source_errors
def verify_checkout(root, owner):
    """Refuse a foreign-history or modified source before executing its checkout.

    General bootstrap consumes the already owner-selected original checkout;
    these anchors witness continuity, not approval of HEAD or activation of an
    older preserved version. Exact-pin consumers retain stronger admission.
    This checks accidental substitution and WIP against trusted local Git, not
    GitHub-ID authenticity against deliberate local-history/source fabrication.
    The caller must honor the existing one-writer rule and keep the checkout/path
    stable through execution. This preflight takes no lock or immutable snapshot
    and does not promise protection from concurrent pathname replacement.
    Exact-object readers use verify_repository instead: their verified bytes are
    read from the fixed commit, never from this mutable working tree.
    """
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError('linked bootstrap root refused; source preserved')
    if local_git(root, 'config', '--get-regexp', r'^(extensions\.partialclone|remote\..*\.promisor)$'):
        raise ValueError('partial source stores cannot qualify offline bootstrap history')
    name = verify_repository(root, owner)
    anchor = ANCHORS[owner]
    # Related original commits include an established older detached checkout.
    # Merely importing an original object into independent clean history is
    # insufficient. Deliberately reparenting trusted local history is outside
    # this offline continuity check; cutover separately reads back live IDs.
    head = local_git(root, 'rev-parse', 'HEAD')
    if not head or (local_git(root, 'merge-base', '--is-ancestor', anchor, head) is None and
                    local_git(root, 'merge-base', '--is-ancestor', head, anchor) is None):
        raise ValueError('bootstrap checkout does not belong to original history')
    prefixes = BOOTSTRAP_ROOTS[owner]
    def selected(path):
        return any(not prefix or path == prefix or path.startswith(prefix + '/') for prefix in prefixes)
    tree = git_result(root, 'ls-tree', '-r', '-z', '--full-tree', head)
    if tree.returncode:
        raise ValueError('bootstrap source tree unavailable')
    raw = tree.stdout
    expected = {}
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, encoded = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        path = os.fsdecode(encoded)
        if selected(path):
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError('bootstrap source must contain regular tracked files only')
            expected[path] = (mode, oid)
    if 'bootstrap.sh' not in expected and owner == 'KleinPerkins/skills':
        raise ValueError('bootstrap source is incomplete')
    actual = set()
    runtime_state = []
    template_bytes = None
    project_bytes = lock_bytes = None
    for directory, dirs, files in os.walk(root, followlinks=False):
        relative = Path(directory).relative_to(root)
        if relative == Path('.'):
            if owner == 'KleinPerkins/kp-mcp' and ('.venv' in dirs or '.venv' in files):
                environment = root / '.venv'
                if environment.is_symlink() or not environment.is_dir():
                    raise ValueError('uv environment root redirection refused; runtime preserved')
                if any(path == '.venv' or path.startswith('.venv/') for path in expected):
                    raise ValueError('uv runtime cannot replace tracked source; source preserved')
                dirs.remove('.venv')
            dirs[:] = [d for d in dirs if d != '.git' and selected(d)]
            files = [f for f in files if f != '.git']
        for dirname in dirs:
            if owner == 'KleinPerkins/skills' and (relative / dirname).as_posix() in DASHBOARD_STATE:
                raise ValueError('dashboard state must be a regular file; source preserved')
        for filename in [*dirs, *files]:
            path = (relative / filename).as_posix()
            target = root / path
            if target.is_symlink() and selected(path):
                raise ValueError('linked bootstrap source refused; source preserved')
        for filename in files:
            path = (relative / filename).as_posix()
            if not selected(path):
                continue
            target = root / path
            if path not in expected and owner == 'KleinPerkins/skills' and path in DASHBOARD_STATE:
                runtime_state.append((path, target))
                continue
            actual.add(path)
            info = target.stat()
            if path not in expected or not stat.S_ISREG(info.st_mode):
                raise ValueError('untracked or ignored bootstrap source refused; source preserved')
            data = target.read_bytes()
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            mode, oid = expected[path]
            if blob != oid or bool(info.st_mode & 0o111) != (mode == '100755'):
                raise ValueError('modified bootstrap source refused; source preserved')
            if path == DASHBOARD_TEMPLATE:
                template_bytes = data
            if path == 'pyproject.toml':
                project_bytes = data
            if path == 'uv.lock':
                lock_bytes = data
    if actual != set(expected):
        raise ValueError('missing bootstrap source refused; source preserved')
    # Staged replacements are preserved rather than silently treated as approval.
    paths = [] if prefixes == ('',) else list(prefixes)
    result = git_result(root, 'diff', '--no-ext-diff', '--no-textconv', '--cached', '--quiet', head, '--', *paths)
    if result.returncode:
        raise ValueError('staged bootstrap source refused; source preserved')
    if owner == 'KleinPerkins/kp-mcp':
        verify_mcp_runtime_contract(root, project_bytes, lock_bytes)
    for relative, path in runtime_state:
        verify_dashboard_state(path, relative, template_bytes)
    if local_git(root, 'rev-parse', 'HEAD') != head:
        raise ValueError('bootstrap source revision changed; source preserved')
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('owner', choices=ORIGINALS)
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--checkout', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--resolve-url')
    args = parser.parse_args()
    try:
        if args.checkout is not None:
            print(verify_checkout(args.checkout, args.owner))
        elif args.repository is not None:
            print(verify_repository(args.repository, args.owner))
        elif args.resolve_url is not None:
            if inventory.identity(args.resolve_url) not in (args.owner, ORIGINALS[args.owner][1]):
                raise ValueError('original source endpoint mismatched')
            print('git@github.com:' + endpoint(args.owner) + '.git')
        elif args.url is not None:
            print(verify_url(args.url, args.owner))
        else:
            print('git@github.com:' + endpoint(args.owner) + '.git')
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
