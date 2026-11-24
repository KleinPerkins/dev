"""Prepare exact authority changes for an already validated Dev retirement plan."""

from hashlib import sha256
import json
from pathlib import PurePosixPath

from personal_checkout_inventory import Binding, Refused, lexical


def destruction_roots(root, steps):
    lexical(root)
    roots = set()
    for step in steps:
        if step['kind'] == 'delete-checkout':
            relative = step['params']['rel']
            if (not isinstance(relative, str)
                    or any(part in ('', '.', '..') for part in relative.split('/'))):
                raise Refused('the approved checkout path is not relative and canonical')
            path = root + '/' + relative
        elif step['kind'] == 'worktree-remove':
            path = step['params']['path']
        else:
            continue
        lexical(path)
        roots.add(path)
    if not roots:
        raise Refused('the approved retirement plan contains no checkout locations')
    return roots


def bind_retirement(root, steps, inventory_bytes, expected):
    """Return only the inventory changes named by the exact confirmed operation."""
    state = json.loads(inventory_bytes)
    if (state['schema'], state['policy'], state['generation'], sha256(inventory_bytes).hexdigest()) != (
            'dev-checkout-inventory/v1', *expected):
        raise Refused('the approved retirement plan has a different Dev inventory binding')
    roots = destruction_roots(root, steps)
    bindings = {name: Binding(**value) for name, value in state['bindings'].items()}
    if not roots <= bindings.keys():
        raise Refused('the approved plan names a checkout without an exact Dev admission')
    deletions = tuple(PurePosixPath(path) for path in roots)
    for name, binding in bindings.items():
        if name in roots:
            continue
        if any(PurePosixPath(path).is_relative_to(deleted)
               for path in binding.locations() for deleted in deletions):
            raise Refused('another admitted checkout depends on a directory the plan would remove')
    return {name: None for name in sorted(roots)}
