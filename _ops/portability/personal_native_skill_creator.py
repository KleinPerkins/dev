"""Read-only assessment of the exact fresh-account native Skill Creator route.

This assesses agent-collected evidence, not its authenticity. Source acceptance,
fresh destination verification and any later publication remain independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import posixpath
import re
import stat
import sys

SCHEMA = 'personal-portability/native-skill-creator-observation/v1'
MAX_BYTES = 1024 * 1024
HOST = {
    'build': '23880', 'system': 'Darwin', 'machine': 'arm64',
    'app_info_sha256': '7a3920d56d052cdf4bf803a92e2098be015eaf9263589d51e04ac4121f16eed7',
    'cli_sha256': '58a91f6ea19bea477ae3a2ec48d619f0039afe75d3476260747e11d201fa7cea',
}
PROVIDER = {
    'SKILL.md': '6656e54755638e8efcf275a472b9672eaa8a9a1b9e59dc210e275b03b59e1e66',
    'scripts/init_skill.py': 'bf0656a5f9d8d8cdecf0245eaf27e1df8e0e9b6d40ccdda814eb8e3d5f6992c8',
    'scripts/generate_openai_yaml.py': '816df12072d74faf924d802a6599a139997e1441e90bfe4869ec304f2e5e2851',
    'scripts/quick_validate.py': 'ee6dba90f44d37171c5a6edb8095979c54919ff6822c1a907afca2e78c48738c',
    'references/openai_yaml.md': 'ffac39318e408108141d40f820968e59f70434a891694f9bf1d25be8237b150c',
}
RUNTIME = {
    'python': '3.13.18', 'system': 'Darwin', 'machine': 'arm64', 'pyyaml': '6.0.3',
    'interpreter_sha256': '506f8a19083f841c29a3675a05c66a35a070080571064ac98f9b0ec4615d659d',
    'wheel_sha256': '2283a07e2c21a2aa78d9c4442724ec1eb15f5e42a723b99cb3d822d48f5f7ad1',
    'license_sha256': '8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4',
    'installed_package_files_verified': 44, 'offline_hash_locked_install': True,
    'source_build_or_lifecycle_scripts': False, 'global_configuration_changed': False,
    'license_retained': True,
}
INIT, VALIDATE, UI = 'scripts/init_skill.py', 'scripts/quick_validate.py', 'scripts/generate_openai_yaml.py'
RESOURCE = 'authored-resource/scripts/summarize.py'
ROSTER = [
    ('minimal-init', INIT, 0), ('unfinished-scaffold-refused', VALIDATE, 1),
    ('minimal-complete-valid', VALIDATE, 0), ('existing-skill-reinitialization-refused', INIT, 1),
    ('native-ui-generation', UI, 0), ('updated-skill-valid', VALIDATE, 0),
    ('resource-init', INIT, 0), ('resource-complete-valid', VALIDATE, 0),
    ('resource-actual-report', RESOURCE, 0), ('resource-invalid-input-refused', RESOURCE, 2),
    ('resource-empty-inventory', RESOURCE, 0), ('validator-missing-description', VALIDATE, 1),
    ('validator-malformed-yaml', VALIDATE, 1), ('validator-invalid-name', VALIDATE, 1),
    ('validator-unknown-frontmatter', VALIDATE, 1), ('validator-unfinished-body', VALIDATE, 1),
    ('validator-blank-fields-observed', VALIDATE, 0), ('initializer-empty-name', INIT, 1),
    ('initializer-long-name', INIT, 1), ('initializer-unknown-resources', INIT, 1),
]
GUARDS = {'home_read_denied', 'outside_write_denied', 'provider_read_allowed',
          'private_write_allowed', 'network_denied', 'fork_denied'}
CHECKS = {'source_provider_files_preserved', 'runtime_package_files_preserved',
          'real_data_input_files_preserved', 'minimal_skill_created_and_updated',
          'resource_skill_authored_and_executed', 'existing_skill_reinitialization_refused_without_changes',
          'metadata_unrelated_fields_and_invocation_policy_preserved',
          'reference_and_asset_routes_resolve_inside_skill', 'authored_metadata_nonempty_and_placeholder_free'}
ZERO_EFFECTS = {'native_discovery_changes', 'global_configuration_writes', 'new_threads', 'model_workers',
                'services', 'Affirm_connections', 'protected_component_access', 'archive_execution', 'provider_writes'}
LIMIT = 'stock_validator_allows_blank_metadata_independent_scope_and_behavior_review_required'
REPORTS = {
    'resource-actual-report': '# Seed inventory\n\n- basil: 5\n- lentil: 13\n\nTotal: 18\n',
    'resource-empty-inventory': '# Seed inventory\n\n\nTotal: 0\n',
}


class ObservationError(ValueError):
    """A bounded refusal without private path, identity or source content."""


def need(condition, code):
    if not condition:
        raise ObservationError(code)


def closed(value, fields):
    need(type(value) is dict and set(value) == set(fields), 'closed_observation_required')


def canonical(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ObservationError('finite_json_required') from exc
    need(len(raw) <= MAX_BYTES, 'observation_too_large')
    return raw


def digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def path(value):
    return (type(value) is str and 1 < len(value) <= 4096 and value.startswith('/')
            and '\x00' not in value and posixpath.normpath(value) == value
            and not {'affirm', 'chaos-scheduler'}.intersection(s.casefold() for s in value.split('/')))


def assess(value, *, expected_email, expected_workspace, expected_account_home):
    """Observe an exact bounded route; never grant acceptance or publication."""
    raw = canonical(value)
    closed(value, {'schema', 'host', 'identity', 'workspace', 'catalog', 'provider', 'runtime', 'functional', 'evidence', 'safety'})
    need(value['schema'] == SCHEMA and value['host'] == HOST, 'host_or_schema_changed')
    need(type(expected_email) is str and 0 < len(expected_email) <= 254 and '@' in expected_email
         and not expected_email.casefold().endswith('@affirm.com'), 'personal_context_required')
    need(path(expected_workspace) and path(expected_account_home), 'personal_context_required')
    need(value['workspace'] == expected_workspace, 'workspace_binding_changed')
    identity = value['identity']
    closed(identity, {'type', 'email', 'workspace_name'})
    need(identity == {'type': 'chatgpt', 'email': expected_email, 'workspace_name': None}, 'personal_identity_not_established')
    catalog = value['catalog']
    closed(catalog, {'complete_response', 'process_terminal', 'process_exit_code', 'stderr_bytes', 'requests',
                     'extra_roots', 'token_refresh_requested', 'threads_or_turns_created', 'model_workers_started',
                     'plugin_installation_or_configuration_changes'})
    need(catalog['complete_response'] is True and catalog['process_terminal'] is True
         and type(catalog['process_exit_code']) is int and catalog['process_exit_code'] == 0, 'catalog_not_terminal_success')
    need(type(catalog['stderr_bytes']) is int and 0 <= catalog['stderr_bytes'] <= 65536, 'catalog_output_unbounded')
    need(catalog['extra_roots'] == [] and catalog['token_refresh_requested'] is False
         and catalog['plugin_installation_or_configuration_changes'] is False, 'catalog_effect_refused')
    need(all(type(catalog[k]) is int and catalog[k] == 0 for k in ('threads_or_turns_created', 'model_workers_started')), 'catalog_worker_refused')
    need(canonical(catalog['requests']) == canonical([
        {'method': 'initialize', 'params': {'clientInfo': {'name': 'personal_skill_creator_readonly', 'version': '1.0'}, 'capabilities': {'experimentalApi': True}}},
        {'method': 'initialized', 'params': {}}, {'method': 'account/read', 'params': {'refreshToken': False}},
        {'method': 'skills/list', 'params': {'cwds': [expected_workspace], 'forceReload': True}},
    ]), 'native_request_outside_route')
    provider = value['provider']
    closed(provider, {'name', 'scope', 'enabled', 'plugin_id', 'path', 'files_before', 'files_after'})
    need(provider['name'] == 'skill-creator' and provider['scope'] == 'system' and provider['enabled'] is True
         and provider['plugin_id'] is None and provider['path'] == expected_account_home + '/.codex/skills/.system/skill-creator/SKILL.md', 'provider_not_qualified')
    closed(provider['files_before'], PROVIDER)
    need(canonical(provider['files_before']) == canonical(provider['files_after']), 'provider_changed')
    for name, expected in PROVIDER.items():
        facts = provider['files_before'][name]
        closed(facts, {'sha256', 'device', 'inode', 'uid', 'mode', 'mtime_ns', 'ctime_ns'})
        need(facts['sha256'] == expected and type(facts['mode']) is int and facts['mode'] == 0o644, 'provider_bytes_or_mode_changed')
        need(all(type(facts[k]) is int and facts[k] > 0 for k in ('device', 'inode', 'uid', 'mtime_ns', 'ctime_ns')), 'provider_identity_missing')
    need(canonical(value['runtime']) == canonical(RUNTIME), 'private_runtime_changed')
    functional = value['functional']
    closed(functional, {'guards', 'checks', 'steps', 'total_elapsed_seconds', 'validator_limit'})
    for key, fields in (('guards', GUARDS), ('checks', CHECKS)):
        closed(functional[key], fields)
        need(all(v is True for v in functional[key].values()), 'qualification_incomplete')
    need(functional['validator_limit'] == LIMIT, 'validator_limit_unacknowledged')
    seconds = functional['total_elapsed_seconds']
    need(type(seconds) in (int, float) and math.isfinite(seconds) and 0 <= seconds < 150, 'qualification_deadline_failed')
    steps = functional['steps']
    need(type(steps) is list and len(steps) == len(ROSTER), 'case_roster_incomplete')
    elapsed = 0.0
    for step, (label, script, exit_code) in zip(steps, ROSTER):
        closed(step, {'label', 'script', 'exit_code', 'stdout_sha256', 'stderr_sha256', 'elapsed_seconds', 'process_terminal'})
        need(step['label'] == label and step['script'] == script, 'case_identity_changed')
        need(type(step['exit_code']) is int and step['exit_code'] == exit_code and step['process_terminal'] is True, 'case_not_terminal_expected_outcome')
        t = step['elapsed_seconds']
        need(type(t) in (int, float) and math.isfinite(t) and 0 <= t < 15, 'case_deadline_failed')
        elapsed += t
        need(digest(step['stdout_sha256']) and digest(step['stderr_sha256']), 'case_output_binding_missing')
        if label in REPORTS:
            need(step['stdout_sha256'] == hashlib.sha256(REPORTS[label].encode()).hexdigest(), 'resource_behavior_failed')
        if label != 'resource-invalid-input-refused':
            need(step['stderr_sha256'] == hashlib.sha256(b'').hexdigest(), 'unexpected_case_stderr')
    need(elapsed <= seconds, 'qualification_timing_inconsistent')
    evidence = value['evidence']
    closed(evidence, {'native_catalog_sha256', 'private_runtime_record_sha256', 'functional_result_sha256',
                      'qualification_driver_sha256', 'fixture_inventory_sha256'})
    need(all(digest(v) for v in evidence.values()), 'evidence_binding_missing')
    closed(value['safety'], ZERO_EFFECTS)
    need(all(type(v) is int and v == 0 for v in value['safety'].values()), 'effect_outside_route')
    return {'schema': 'personal-portability/native-skill-creator-assessment/v1',
            'eligible_for_bounded_destination_record': ['imported/create-skill'],
            'provider_owner': 'OpenAI', 'source_route': 'fresh-account native host distribution',
            'host_build': HOST['build'], 'observation_sha256': hashlib.sha256(raw).hexdigest(),
            'case_groups_observed': len(ROSTER), 'legacy_implementation_or_UI_parity_proven': False,
            'source_acceptance_supplied_by_data': False, 'installation_or_publication_authority': False,
            'evidence_authenticity_established_by_data': False, 'formal_migration_complete': False}


def load_private(pathname):
    fd = os.open(pathname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
             and stat.S_IMODE(before.st_mode) == 0o600, 'private_observation_required')
        need(0 < before.st_size <= MAX_BYTES, 'observation_size_invalid')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            need(size <= MAX_BYTES, 'observation_too_large')
        after = os.fstat(fd)
        need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
             and size == before.st_size, 'observation_changed_or_incomplete')
    finally:
        os.close(fd)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate_json_field')
            result[key] = value
        return result
    def finite(_):
        raise ObservationError('finite_json_required')
    return json.loads(b''.join(chunks), object_pairs_hook=unique, parse_constant=finite)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observation')
    parser.add_argument('--expected-personal-email', required=True)
    parser.add_argument('--expected-workspace', required=True)
    parser.add_argument('--expected-account-home', required=True)
    args = parser.parse_args(argv)
    try:
        result = assess(load_private(args.observation), expected_email=args.expected_personal_email,
                        expected_workspace=args.expected_workspace, expected_account_home=args.expected_account_home)
    except (ObservationError, OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({'status': 'unavailable', 'reason': str(exc) if isinstance(exc, ObservationError) else 'observation_unreadable'}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
