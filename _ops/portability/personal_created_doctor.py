"""Read local Git health for one explicitly selected Dev-created Personal product."""
import hashlib
import os
from pathlib import Path
import re

import personal_scaffold as creator
import personal_worktree as worktree

g = worktree.g
scope = worktree.s

# The historical Personal doctor uses a separately qualified cohort, including
# multi-remote repositories. A newly created product has a single known origin.
CORE_KEYS = {
    'core.repositoryformatversion', 'core.filemode', 'core.bare', 'core.logallrefupdates',
    'core.ignorecase', 'core.precomposeunicode', 'core.symlinks', 'core.hookspath',
    'core.autocrlf', 'core.eol', 'core.safecrlf', 'core.trustctime', 'core.checkstat',
    'core.excludesfile', 'core.attributesfile', 'core.fsmonitor', 'core.untrackedcache',
}


class CreatedGit(g.PersonalGit):
    """Use the common private Git snapshot with the scaffold's own origin policy."""

    def __init__(self, repo, tool):
        self.repo, self.tool = repo, tool
        self.config_fact = g.file_fact(repo, '.git/config', required=True, limit=scope.MAX_FILE_BYTES)
        self.config_raw = repo.read_file('.git/config')
        self.base_config = self.config = tool.parse_config(self.config_raw)
        self.overlay_config = {}
        if self.config.get('remote.origin.url') != ['git@github.com:' + repo.row['id'] + '.git']:
            raise g.Refusal('created-checkout-origin-changed')
        for key, values in self.config.items():
            if key == 'remote.origin.pushurl':
                if not all(g.personal_remote(value, repo.row['id']) for value in values):
                    raise g.Refusal('created-checkout-other-remote')
            elif (key not in CORE_KEYS and key not in {'user.name', 'user.email', 'remote.origin.url',
                    'remote.origin.fetch', 'remote.origin.tagopt'}
                    and not re.fullmatch(r'branch\..+\.(remote|merge|description)', key)):
                raise g.Refusal('created-checkout-unsupported-local-config')
        if (g.last(self.config, 'core.repositoryformatversion', '0') != '0'
                or g.git_bool(g.last(self.config, 'core.bare', 'false'))):
            raise g.Refusal('created-checkout-unsupported-git-layout')
        self.worktree_raw = self.worktree_fact = None
        self.unused_metadata = ('.git/commondir', '.git/gitdir', '.git/config.worktree', '.git/info/grafts')
        self.unchanged_config()
        self.files = {name: g.file_fact(repo, name, required=name in {'.git/HEAD', '.git/index'})
                      for name in ('.git/HEAD', '.git/index', '.git/packed-refs', '.git/shallow')}
        self.storage = g.storage_inventory(repo)
        self.shared_indexes = self.shared_index_facts()
        self._active_gitdir = None
        self.probes = []

    def unchanged_config(self):
        super().unchanged_config()
        if any(g.file_fact(self.repo, name) is not None for name in self.unused_metadata):
            raise g.Refusal('created-checkout-unsupported-git-metadata')


class CreatedWorktree(worktree.PersonalWorktree):
    def __init__(self, repo, tool):
        self.repo, self.tool = repo, tool
        self.git = CreatedGit(repo, tool)
        self.probes = []
        self.controls = {}
        self.tree_ready = self.ignore_ready = False
        self.exclude_path = '/dev/null'
        self.shared_indexes = self.shared_index_facts()


def registration_snapshot(repo):
    """Inspect only the primary's registration files. Do not follow their target paths."""
    try:
        table = scope.child_directory(repo._fd, ('.git', 'worktrees'))
    except FileNotFoundError:
        return None
    try:
        names = sorted(os.listdir(table))
        if len(names) > 1024:
            raise g.Refusal('created-checkout-registration-limit')
        entries = {}
        for name in names:
            entry = scope.child_directory(table, (name,))
            try:
                text = scope.read_regular(entry, 'gitdir', max_bytes=4096)
                if b'\x00' in text or os.path.basename(text.removesuffix(b'\n')) != b'.git':
                    raise g.Refusal('created-checkout-invalid-registration')
                entries[name] = (scope.identity(os.fstat(entry)), text)
            finally:
                os.close(entry)
        if names != sorted(os.listdir(table)):
            raise g.Refusal('created-checkout-registrations-changed')
        return (scope.identity(os.fstat(table)), entries)
    finally:
        os.close(table)


def diagnose(repository, fixture=None, fixture_id=None):
    owner, sep, name = repository.partition('/')
    if owner != 'KleinPerkins' or not sep:
        raise ValueError('select the exact KleinPerkins repository name')
    with creator.open_created_checkout(name, fixture, fixture_id) as (path, fd, saved, provider_id):
        row = {'id': repository, 'path': str(Path(*creator.LAYOUT, name)), 'revision': None}
        repo = scope.RepositoryView(fd, row, path)
        reader = CreatedWorktree(repo, g.GitTool())
        registrations = registration_snapshot(repo)
        git = reader.observe()
        if registration_snapshot(repo) != registrations:
            raise g.Refusal('created-checkout-registrations-changed')
        if not git['local_identity_canonical'] or not git['effective_personal_identity_canonical']:
            verdict = 'VIOLATION'
        elif not git['clean_under_personal_policy'] or git['ahead'] or git['behind'] or git['detached']:
            verdict = 'ADVISORY'
        else:
            verdict = 'OK'
        result = {key: git[key] for key in ('head', 'branch', 'detached', 'local_identity_canonical',
                  'effective_personal_identity_canonical', 'clean_under_personal_policy', 'codes',
                  'reported_change_items', 'reported_untracked_items', 'upstream', 'ahead', 'behind')}
        result.update(schema='dev-personal/created-checkout-diagnosis/v1', repository=repository,
                      path=str(path), creation_record_sha256=hashlib.sha256(saved).hexdigest(),
                      linked_registrations=len(registrations[1]) if registrations else 0,
                      recorded_repository_id=provider_id, local_git_verdict=verdict,
                      sync_evidence='local tracking refs', hosted_identity_verified=False)
    return result
