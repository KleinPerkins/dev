"""Live routing for retained private source histories; never successor admission.

Historical owner labels and object pins remain unchanged. GitHub's immutable ID
selects the live endpoint; its observed name must be an explicitly allowed phase.
Live discovery accepts no redirects or clean successor IDs. Local consumption
remains offline and requires the original pinned Git object as well as its endpoint.
"""
import argparse
import json
from pathlib import Path
import subprocess

import inventory

# These existing object pins identify the retained history during offline use.
ANCHORS = {
    'KleinPerkins/skills': 'bc58eb77f442307ab4f124ab5aeec3f99571cb21',
    'KleinPerkins/kp-mcp': '7594346fbb09161749d21624b35cf5a173c84958',
}

ORIGINALS = {
    'KleinPerkins/skills': (1275604090, 'KleinPerkins/skills-private-original'),
    'KleinPerkins/kp-mcp': (1271164179, 'KleinPerkins/kp-mcp-private-original'),
}


def endpoint(owner):
    identity, retained = ORIGINALS[owner]
    try:
        result = subprocess.run(['gh', 'api', f'/repositories/{identity}'],
                                capture_output=True, text=True, timeout=30, check=True)
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


def verify_repository(root, owner, *, revision=None):
    name, reason = inventory.repository(root)
    if reason is not None or name not in (owner, ORIGINALS[owner][1]):
        raise ValueError('original source identity unavailable, excluded, or mismatched')
    # Inspect every configured fetch and push URL, including multiple values.
    rows = inventory.git(root, 'config', '--get-regexp', r'remote\..*\.(url|pushurl)') or ''
    urls = [line.split(None, 1)[1] for line in rows.splitlines()]
    if not urls or any(inventory.identity(url) != name for url in urls):
        raise ValueError('original source remote identity mismatched or stale')
    # get-url also applies Git insteadOf/pushInsteadOf rewrites.
    for direction in ((), ('--push',)):
        expanded = inventory.git(root, 'remote', 'get-url', *direction, '--all', 'origin')
        if not expanded or any(inventory.identity(url) != name for url in expanded.splitlines()):
            raise ValueError('original source effective remote identity mismatched')
    anchor = revision or ANCHORS[owner]
    if inventory.git(root, 'rev-parse', '--verify', anchor + '^{commit}') != anchor:
        raise ValueError('original source pinned object unavailable')
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('owner', choices=ORIGINALS)
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--revision')
    parser.add_argument('--url')
    parser.add_argument('--resolve-url')
    args = parser.parse_args()
    try:
        if args.repository is not None:
            print(verify_repository(args.repository, args.owner, revision=args.revision))
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
