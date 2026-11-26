"""Prepare exact authority changes for an already validated Dev retirement plan."""

from hashlib import sha256
import json

from personal_checkout_inventory import Binding, Refused, check_retirement_dependencies, lexical


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
    malformed = 'the approved retirement plan has a malformed Dev admission'
    if not isinstance(inventory_bytes, (bytes, bytearray)):
        raise Refused(malformed)
    try:
        state = json.loads(inventory_bytes)
    except (ValueError, RecursionError) as error:
        raise Refused(malformed) from error
    if not isinstance(state, dict) or not isinstance(state.get('bindings'), dict):
        raise Refused(malformed)
    if (not isinstance(expected, (tuple, list))
            or (state.get('schema'), state.get('policy'), state.get('generation'),
                sha256(inventory_bytes).hexdigest()) != ('dev-checkout-inventory/v1', *expected)):
        raise Refused('the approved retirement plan has a different Dev inventory binding')
    roots = destruction_roots(root, steps)
    try:
        bindings = {name: Binding(**value) for name, value in state['bindings'].items()}
        for name, binding in bindings.items():
            binding.validate()
            if binding.checkout != name:
                raise Refused('the admission path differs from its inventory key')
    except (Refused, TypeError) as error:
        raise Refused(malformed) from error
    if not roots <= bindings.keys():
        raise Refused('the approved plan names a checkout without an exact Dev admission')
    check_retirement_dependencies(roots, (binding for name, binding in bindings.items() if name not in roots))
    return {name: None for name in sorted(roots)}
