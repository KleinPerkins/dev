#!/usr/bin/env python3
"""Bounded successor routing and source observation; no platform mutation authority."""
import json
from pathlib import Path
import subprocess
import sys

POLICY = Path(__file__).with_name('delivery-policy.json')


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


def load_policy():
    policy = json.loads(POLICY.read_text(), object_pairs_hook=unique)
    if set(policy) != {'schema', 'controller', 'pac_mini', 'default_disposition',
                       'repositories', 'dev_names', 'rejected_repository_ids',
                       'excluded', 'live_mutation_authorized'}:
        raise ValueError('unknown policy fields')
    if (policy['schema'] != 'dev-delivery-policy/v1'
            or policy['controller'] != 'retired-down-abandoned'
            or policy['pac_mini'] != 'planned-not-operational'
            or policy['default_disposition'] != 'unenrolled'
            or policy['live_mutation_authorized'] is not False
            or policy['dev_names'] != ['KleinPerkins/dev-temp', 'KleinPerkins/dev']
            or policy['rejected_repository_ids'] != [1278387789]
            or policy['excluded'] != ['KleinPerkins/chaos-scheduler']):
        raise ValueError('policy authority mismatch')
    rows = policy['repositories']
    if not isinstance(rows, list) or len(rows) != 20:
        raise ValueError('cohort size mismatch')
    seen, ids, counts = set(), set(), {}
    for row in rows:
        if set(row) != {'repository', 'repository_id', 'disposition'}:
            raise ValueError('unknown repository fields')
        name, identity, disposition = row['repository'], row['repository_id'], row['disposition']
        if (not isinstance(name, str) or not name.startswith('KleinPerkins/')
                or name in seen or type(identity) is not int or identity <= 0
                or identity in ids or identity in policy['rejected_repository_ids']
                or disposition not in {'actions-app', 'private-no-ci', 'retired'}):
            raise ValueError('invalid cohort identity')
        seen.add(name); ids.add(identity)
        counts[disposition] = counts.get(disposition, 0) + 1
    if counts != {'actions-app': 13, 'private-no-ci': 6, 'retired': 1}:
        raise ValueError('cohort disposition mismatch')
    dev = next(row for row in rows if row['repository'] == 'KleinPerkins/dev')
    if dev != {'repository': 'KleinPerkins/dev', 'repository_id': 1459458379,
               'disposition': 'actions-app'}:
        raise ValueError('successor identity mismatch')
    return policy


def classify(repository, policy):
    if repository in policy['excluded']:
        return 'excluded'
    key = 'KleinPerkins/dev' if repository == 'KleinPerkins/dev-temp' else repository
    for row in policy['repositories']:
        if key == row['repository']:
            # Preserve these two existing product scaffold routes; this is routing only.
            return ('native-github' if key in {'KleinPerkins/shadow-sync', 'KleinPerkins/machine-monitor'}
                    else row['disposition'])
    names = [row['repository'] for row in policy['repositories']] + policy['dev_names'] + policy['excluded']
    if repository.lower() in {name.lower() for name in names}:
        return 'identity-unverified'
    return 'unenrolled'


def observe(root, policy):
    root = Path(root)
    old = ('.github/pr-automation.json', '.github/pr-verification.json',
           '.github/pr-recipe.json', '.github/pr-automation.lock.json')
    if any((root / item).exists() or (root / item).is_symlink() for item in old):
        return 'DELIVERY_DRIFT', 'Retired controller contracts present; preserve for investigation, never restore or reconcile.'
    run = subprocess.run(['git', '-C', str(root), 'config', '--get-all', 'remote.origin.url'],
                         text=True, capture_output=True, timeout=10, check=False)
    origins = run.stdout.splitlines()
    if len(origins) != 1:
        return 'DELIVERY_UNKNOWN', 'Exactly one canonical origin is required; no readiness claimed.'
    origin = origins[0]
    repository = None
    for row in policy['repositories']:
        for name in ([row['repository']] + (['KleinPerkins/dev-temp'] if row['repository'] == 'KleinPerkins/dev' else [])):
            if origin in {f'git@github.com:{name}.git', f'https://github.com/{name}',
                          f'https://github.com/{name}.git', f'ssh://git@github.com/{name}.git'}:
                repository = name
    if repository is None:
        return 'DELIVERY_UNKNOWN', 'Unenrolled or ambiguous identity; no automatic CI or controller enrollment.'
    disposition = classify(repository, policy)
    if disposition == 'private-no-ci':
        workflows = root / '.github/workflows'
        if workflows.exists() and any(workflows.iterdir()):
            return 'DELIVERY_DRIFT', 'Private/no-CI target contains workflows; preserve and investigate.'
        return 'PRIVATE_NO_CI_UNVERIFIED', 'Source has no workflows; live immutable identity and Actions-OFF observation remain required.'
    if disposition == 'retired':
        return 'RETIRED', 'Retired product; no enrollment or restoration.'
    required = ['.github/ci-contract.json', '.github/workflows/ci.yml',
                '.github/workflows/reviewer-app.yml', '.github/review-enrollments.json']
    missing = [name for name in required if not (root / name).is_file() or (root / name).is_symlink()]
    if missing:
        return 'SUCCESSOR_NOT_READY', 'Missing successor source: ' + ', '.join(missing)
    return 'SUCCESSOR_UNVERIFIED', 'Source files present only; exact-run CI, originating-account review, live ID/settings and App qualification unverified.'


def main(argv):
    policy = load_policy()
    if len(argv) != 2 or argv[0] not in {'classify', 'observe'}:
        raise ValueError('usage: delivery-policy.py classify <owner/name> | observe <repo>')
    if argv[0] == 'classify':
        print(classify(argv[1], policy))
    else:
        print('\t'.join(observe(argv[1], policy)))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (OSError, ValueError, TypeError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        print('delivery policy refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
