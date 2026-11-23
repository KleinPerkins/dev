#!/usr/bin/env bash
# Hermetic tests for _ops/bin/dev-remove-repo.sh (the /dev-remove-repo backend).
#
# Every case runs against an isolated temporary fixture root (a throwaway "dev" tree, "home" and
# adapter shims under the system temp dir) through the tool's fixture seam. Offline; never reads or
# writes the real ~/dev, HOME, GitHub, PAC, Cloudflare, launchd or any live subsystem state, and never
# deletes a real repository. Includes the sanitized Milestone 1 replay and its coverage proof.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

python3 - "$ROOT" "$@" <<'PY'
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve()
SCRIPT = ROOT / "_ops" / "bin" / "dev-remove-repo.sh"
REPLAY = ROOT / "_ops" / "tests" / "fixtures" / "dev-remove-repo" / "m1-replay.sanitized.jsonl"
POLICY_MARKER = "policy:dev-remove-repo-affirm-exception/v1"
ORIGIN = "https://github.com/KleinPerkins/%s.git"
SECRET_LOOKING = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
SECRET_LOOKING_RE = r"(ghp_|gho_|ghs_|github_pat_|xox[abprs]-|AKIA[0-9A-Z]{12}|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer [A-Za-z0-9._-]{20,})"

LSOF_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$d/lsof.rc" ]; then echo "lsof: simulated failure" >&2; exit "$(cat "$d/lsof.rc")"; fi
if [ -f "$d/lsof.out" ]; then cat "$d/lsof.out"; else printf 'p1\ncinit\nftxt\nn/sbin/init\n'; fi
"""

GIT_SHIM = r"""#!/usr/bin/env bash
# Logs every subcommand, then runs the real git. Used to prove the tool never touches the network.
d="$(cd "$(dirname "$0")/.." && pwd)"
real="$(cat "$d/real-git")"
printf '%s\n' "$*" >> "$d/git.calls"
exec "$real" "$@"
"""

# Scripts that stand in for the owning subsystems' own verbs.
LOCAL_JOBS_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' "$*" >> "$d/local-jobs.calls"
case "$1" in
  view-jobs) cat "$d/jobs.json" 2>/dev/null || echo '{"instances": []}' ;;
  delete-fetch-if-current)
    if [ -f "$d/local-jobs.fail" ]; then echo "simulated failure" >&2; exit 3; fi
    [ "$#" = 6 ] && [ "$2" = "--id" ] && [ "$4" = "--if-revision" ] && [ "$6" = "--confirm" ] || exit 2
    id="$3"; revision="$5"
    python3 - "$d/jobs.json" "$id" "$revision" <<'INNER'
import json, sys
path, ident, revision = sys.argv[1:]
data = json.load(open(path))
rows = [row for row in data["instances"] if row.get("id") == ident]
if len(rows) != 1 or rows[0].get("removal_revision") != revision:
    sys.exit("fetch record changed; nothing removed")
data["instances"].remove(rows[0])
json.dump(data, open(path, "w"))
INNER
    ;;
  doctor) cat "$d/doctor-local-jobs.txt" 2>/dev/null; exit "$(cat "$d/doctor-local-jobs.rc" 2>/dev/null || echo 0)" ;;
esac
"""

DOCTOR_SHIM = r"""#!/usr/bin/env bash
# Generic health shim: prints $FIXTURE/doctor-<name>.txt and exits with $FIXTURE/doctor-<name>.rc.
d="$(cd "$(dirname "$0")/.." && pwd)"
name="$(basename "$0")"
cat "$d/doctor-$name.txt" 2>/dev/null
exit "$(cat "$d/doctor-$name.rc" 2>/dev/null || echo 0)"
"""

WORKTREE_SHIM = r"""#!/usr/bin/env bash
# Stands in for dev-worktree.sh. `clean --path P` honours $FIXTURE/worktree.mode: remove | refuse.
d="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' "$*" >> "$d/worktree.calls"
case "$1" in
  clean)
    path=""; while [ $# -gt 0 ]; do [ "$1" = "--path" ] && path="$2"; shift; done
    if [ "$(cat "$d/worktree.mode" 2>/dev/null || echo remove)" = "remove" ]; then
      main="$(git -C "$path" rev-parse --git-common-dir)"
      git -C "$(dirname "$main")" worktree remove --force "$path" && exit 0
    fi
    echo "AWA: refusing to clean $path" >&2; exit 4 ;;
  doctor) cat "$d/doctor-worktree.txt" 2>/dev/null; exit "$(cat "$d/doctor-worktree.rc" 2>/dev/null || echo 0)" ;;
esac
"""


# Idle machine until a checkout has been set aside under its removal marker; then a program is "using" it.
LSOF_AFTER_RENAME_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
for m in "$d"/dev/personal/.drr-*.removing; do
  if [ -d "$m" ]; then printf 'p424242\ncnode\nfcwd\nn%s\n' "$m"; fi
done
exit 0
"""

# The same program, but reported under the checkout's ORIGINAL path once it has been set aside.
LSOF_ORIGINAL_SPELLING_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
for m in "$d"/dev/personal/.drr-*.removing; do
  if [ -d "$m" ]; then printf 'p424243\ncnode\nfcwd\nn%s\n' "$d/dev/personal/alpha"; fi
done
exit 0
"""

# Idle machine, except that once the first checkout is gone a client config begins to name the second one.
LSOF_ADDS_REFERENCE_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
if [ ! -d "$d/dev/personal/first" ] && [ ! -f "$d/home/.reference-added" ]; then
  mkdir -p "$d/home/.cursor"
  printf '{"mcpServers": {"second": {"command": "%s/dev/personal/second/bin/serve"}}}\n' "$d" > "$d/home/.cursor/mcp.json"
  : > "$d/home/.reference-added"
fi
exit 0
"""

# Idle machine, except that once the first checkout is gone a symbolic link begins to point into the second one.
LSOF_ADDS_LINK_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
if [ ! -d "$d/dev/personal/first" ] && [ ! -f "$d/home/.link-added" ]; then
  ln -s "$d/dev/personal/second/sub" "$d/dev/personal/keep/late-link"
  : > "$d/home/.link-added"
fi
exit 0
"""

# Idle machine, except that once the first checkout is gone a scheduler entry begins to name the second one.
LSOF_ADDS_JOB_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
if [ ! -d "$d/dev/personal/first" ] && [ ! -f "$d/home/.job-added" ]; then
  printf '{"instances": [{"id": "late-job", "role": "job", "command": "%s/dev/personal/second/run.sh"}]}\n' "$d" > "$d/jobs.json"
  : > "$d/home/.job-added"
fi
exit 0
"""

# Idle machine, except that once the Cursor cache folder named in $FIXTURE/watch-cache is gone, a program is
# "using" the linked worktree named in $FIXTURE/watch-wt (its cache removal is a step that runs first).
LSOF_WORKTREE_AFTER_CACHE_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
if [ ! -e "$(cat "$d/watch-cache")" ]; then printf 'p424242\ncnode\nfcwd\nn%s\n' "$(cat "$d/watch-wt")"; fi
exit 0
"""

# Idle machine, except that the moment a checkout has been set aside under its removal marker (once), something
# adds a linked worktree to it: the add finished after the last check and before the set-aside look.
LSOF_ADDS_WORKTREE_AFTER_RENAME_SHIM = r"""#!/usr/bin/env bash
d="$(cd "$(dirname "$0")/.." && pwd)"
printf 'p1\ncinit\nftxt\nn/sbin/init\n'
for m in "$d"/dev/personal/.drr-*.removing; do
  if [ -d "$m" ] && [ ! -f "$d/home/.worktree-added" ]; then
    : > "$d/home/.worktree-added"
    git -C "$m" worktree add -q --detach "$d/home/.cursor/worktrees/alpha/late" >/dev/null 2>&1
  fi
done
exit 0
"""

# An owning verb that deletes the job and then stops answering, so the result cannot be checked.
LOCAL_JOBS_QUIET_SHIM = LOCAL_JOBS_SHIM.replace(
    "INNER\n    ;;",
    'INNER\n    : > "$d/local-jobs.quiet"\n    ;;',
).replace(
    "view-jobs) cat",
    'view-jobs) if [ -f "$d/local-jobs.quiet" ]; then echo "not answering" >&2; exit 5; fi; cat',
)

# An owning verb that does the work and then reports an error anyway.
LOCAL_JOBS_FLAKY_SHIM = LOCAL_JOBS_SHIM.replace(
    "INNER\n    ;;",
    'INNER\n    if [ -f "$d/local-jobs.flaky" ]; then echo "late failure" >&2; exit 3; fi\n    ;;',
)


def clear_readonly(func, path, _exc):
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError:
        pass


def digest_tree(path):
    """Content-and-structure digest that never follows a symlink."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(str(path), followlinks=False):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, str(path))
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                h.update(("L:%s>%s\n" % (rel, os.readlink(full))).encode())
            elif stat.S_ISDIR(st.st_mode):
                h.update(("D:%s\n" % rel).encode())
            elif stat.S_ISREG(st.st_mode):
                with open(full, "rb") as fh:
                    h.update(("F:%s:%s\n" % (rel, hashlib.sha256(fh.read()).hexdigest())).encode())
            else:
                h.update(("S:%s\n" % rel).encode())
    return h.hexdigest()


def ids(items):
    return sorted(i["id"] for i in items)


class Out(object):
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    @property
    def data(self):
        return json.loads(self.out)

    @property
    def text(self):
        return self.out + self.err


class Fx(object):
    """One throwaway dev tree + home + adapters. Nothing outside self.tmp is ever read or written."""

    def __init__(self, case):
        self.tmp = Path(tempfile.mkdtemp(prefix="drr-test-")).resolve()
        case.addCleanup(shutil.rmtree, str(self.tmp), onerror=clear_readonly)
        self.dev = self.tmp / "dev"
        self.home = self.tmp / "home"
        self.ad = self.tmp / "adapters"
        self.sentinel = self.tmp / "sentinel-home"
        self.outside = self.tmp / "outside"
        for d in (
            self.dev / "_ops",
            self.dev / "personal",
            self.dev / "capabilities",
            self.dev / "affirm" / "src",
            self.dev / "affirm" / "vendor",
            self.home,
            self.ad,
            self.sentinel,
            self.outside,
        ):
            d.mkdir(parents=True, exist_ok=True)
        (self.dev / "_ops" / "POLICY.md").write_text("# fixture policy\n")
        self.fleet([])
        self.adapter("lsof", LSOF_SHIM)
        self.git_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.sentinel),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }

    # ----- building fixtures
    def adapter(self, name, body):
        path = self.ad / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def git(self, path, *args, check=True):
        proc = subprocess.run(["git", "-C", str(path)] + [str(a) for a in args], env=self.git_env, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(map(str, args)), proc.stderr))
        return proc.stdout

    def repo(self, rel, origin=True, files=None):
        path = self.dev / rel
        path.mkdir(parents=True)
        self.git(path, "init", "-q", "-b", "main")
        for name, text in (files or {"README.md": "hello\n", "sub/a.txt": "a\n", "sub/deeper/b.txt": "b\n"}).items():
            f = path / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        self.git(path, "add", "-A")
        self.git(path, "commit", "-q", "-m", "init")
        if origin:
            self.git(path, "remote", "add", "origin", ORIGIN % path.name)
            self.git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
            self.git(path, "branch", "--set-upstream-to=origin/main", "main")
        return path

    def push_state(self, path):
        self.git(path, "update-ref", "refs/remotes/origin/main", "HEAD")

    def commit(self, path, name="more.txt", text="more\n"):
        (path / name).write_text(text)
        self.git(path, "add", "-A")
        self.git(path, "commit", "-q", "-m", "more " + name)

    def lsof(self, rows):
        """rows: (pid, command, fd, path). Replaces the process table the tool sees."""
        lines = []
        for pid, command, fd, name in rows:
            lines += ["p%d" % pid, "c%s" % command, "f%s" % fd, "n%s" % name]
        (self.tmp / "lsof.out").write_text("\n".join(lines) + "\n")

    def lsof_off(self):
        (self.tmp / "lsof.rc").write_text("1")

    def lsof_on(self):
        for name in ("lsof.rc", "lsof.out"):
            try:
                (self.tmp / name).unlink()
            except FileNotFoundError:
                pass

    def policy(self, on=True):
        text = "# fixture policy\n"
        if on:
            text += "<!-- %s -->\n" % POLICY_MARKER
        (self.dev / "_ops" / "POLICY.md").write_text(text)

    def fleet(self, slugs):
        d = self.dev / "_ops" / "baseline" / "profiles" / "pr-automation" / "v3"
        d.mkdir(parents=True, exist_ok=True)
        (d / "fleet.json").write_text(json.dumps({"targets": [{"repo": s} for s in slugs], "excluded": []}))

    def fetch_job(self, repo, ident="alpha-nightly"):
        revision = hashlib.sha256((ident + str(repo)).encode()).hexdigest()
        return {"id": ident, "type": "incremental-git-fetch", "role": "instance",
                "path": str(repo), "schedule": "inherit", "removal_revision": revision}

    def jobs(self, instances):
        (self.tmp / "jobs.json").write_text(json.dumps({"instances": instances}))
        self.adapter("local-jobs", LOCAL_JOBS_SHIM)

    def linked_worktree(self, repo, where, branch="wt-branch"):
        self.git(repo, "worktree", "add", "-q", "-b", branch, str(where))
        return Path(where)

    def health(self, name, text, rc=0):
        self.adapter(name, DOCTOR_SHIM)
        (self.tmp / ("doctor-%s.txt" % name)).write_text(text)
        (self.tmp / ("doctor-%s.rc" % name)).write_text(str(rc))

    @property
    def state(self):
        return self.home / ".local" / "state" / "dev-repo-removal"

    def journal(self, op):
        return self.state / op / "events.jsonl"

    def events(self, op, lenient=False):
        out = []
        for line in self.journal(op).read_text().splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                if not lenient:
                    raise
        return out

    def kinds(self, op):
        return [e["kind"] for e in self.events(op)]

    def state_snapshot(self):
        return digest_tree(self.state) if self.state.exists() else None

    # ----- running the tool
    def run(self, *args, interrupt=None, now=None, cwd=None, env=None, timeout=300):
        environ = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.sentinel),
            "LC_ALL": "C",
            "TERM": "dumb",
            "TMPDIR": tempfile.gettempdir(),
            "DEV_REMOVE_REPO_FIXTURE_ROOT": str(self.tmp),
        }
        if interrupt:
            environ["DEV_REMOVE_REPO_FIXTURE_INTERRUPT"] = interrupt
        if now is not None:
            environ["DEV_REMOVE_REPO_FIXTURE_NOW"] = repr(float(now))
        if env:
            environ.update(env)
        proc = subprocess.run(
            ["bash", str(SCRIPT)] + [str(a) for a in args],
            cwd=str(cwd or self.tmp),
            env=environ,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return Out(proc.returncode, proc.stdout, proc.stderr)

    def preview(self, *paths, extra=(), **kw):
        out = self.run("remove", *(list(paths) + ["--json"] + list(extra)), **kw)
        return out, out.data

    def confirm_args(self, data, waive=None, attest=None, token=None):
        args = ["remove", "--operation", data["operation"], "--confirm", token or data["confirm_token"]]
        w = data["required_waivers"] if waive is None else waive
        if w:
            args += ["--waive", ",".join(w)]
        a = data["required_attests"] if attest is None else attest
        if a:
            args += ["--attest", ",".join(a)]
        return args + ["--json"]

    def confirm(self, data, waive=None, attest=None, token=None, **kw):
        return self.run(*self.confirm_args(data, waive, attest, token), **kw)

    def run_all(self, *paths, waive=None, attest=None, cohort_size=None, **kw):
        extra = ["--cohort-size", str(cohort_size)] if cohort_size else []
        out, data = self.preview(*paths, extra=extra, **{k: v for k, v in kw.items() if k == "env"})
        assert out.rc == 0, out.text
        return data, self.confirm(data, waive=waive, attest=attest, **kw)

    def step_ids(self, data, kind):
        return [s["id"] for s in data["steps"] if s["kind"] == kind]


class DevRemoveRepoTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.fx = Fx(self)

    def test_personal_view_recognises_original_scaffold_after_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            checkout = owner / "sample.product"
            env = {**os.environ, "DEV_SESSION_ID": "retirement-fixture-" + root.name,
                   "XDG_STATE_HOME": str(root / "state")}
            created = subprocess.run([str(ROOT / "_ops/bin/dev-new-repo.sh"), "--personal-codex",
                                      checkout.name, "--fixture-root", str(root)],
                                     env=env, text=True, capture_output=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            command = [str(SCRIPT), "view", "--personal-codex", "--fixture-root", str(root), "--json"]

            def view(*paths):
                result = subprocess.run([*command, *map(str, paths)], env=env, text=True, capture_output=True)
                data = json.loads(result.stdout)
                self.assertEqual(result.returncode, data["exit"])
                return data

            relative = checkout.relative_to(root)
            observed = view(relative)
            self.assertTrue(observed["ok"], observed)
            self.assertTrue(observed["creation_binding_matches"])
            self.assertEqual(observed["linked_registrations"], 0)
            self.assertIsNone(observed["recorded_repository_id"])
            self.assertFalse(observed["removal_ready"])
            self.assertFalse(view(relative, "unselected")["ok"])
            self.assertFalse(view(Path("personal") / checkout.name)["ok"])
            registration = checkout / ".git/worktrees/disconnected"
            registration.mkdir(parents=True)
            (registration / "gitdir").write_text(str(root / "unavailable/.git") + "\n")
            self.assertEqual(view(checkout)["linked_registrations"], 1)
            (registration / "gitdir").unlink()
            self.assertFalse(view(checkout)["ok"])
            registration.rmdir()
            original = root / "original"
            checkout.rename(original)
            shutil.copytree(original, checkout, symlinks=True)
            self.assertIn("does not match", view(checkout)["refused"])
            checkout.rename(root / "byte-copy")
            original.rename(checkout)
            self.assertEqual(view(checkout), observed)
            self.assertFalse((root / "state/dev-repo-removal").exists())

    def test_personal_view_observes_selected_peers_and_configured_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            target, peer = owner / "sample.source", owner / "sample.reader"
            env = {**os.environ, "DEV_SESSION_ID": "retirement-fixture-" + root.name,
                   "XDG_STATE_HOME": str(root / "state")}
            for checkout in (target, peer):
                created = subprocess.run([str(ROOT / "_ops/bin/dev-new-repo.sh"), "--personal-codex",
                                checkout.name, "--fixture-root", str(root)],
                               env=env, text=True, capture_output=True)
                self.assertEqual(created.returncode, 0, created.stderr)
            slots = peer / ".agents/skills"
            slots.mkdir(parents=True)
            (slots / "whole").symlink_to(os.path.relpath(target / "catalog", slots))
            local = slots / "local"
            local.mkdir()
            resource = local / "table"
            resource.symlink_to(os.path.relpath(target / "data", local))
            (slots / "elsewhere").symlink_to(str(target) + "-old/missing")
            def fetch(name, path, declared_root=str(owner), source="global.dev_root"):
                return dict(id=name, type="incremental-git-fetch", declared_path=path,
                            declared_root=declared_root, declared_root_source=source)
            jobs = dict(schema="local-jobs/configured-jobs/v1", scope="base-configured-instances", complete=True,
                        instances=[fetch("target", target.name), fetch("peer", str(peer)),
                                   fetch("ambiguous", target.name, ".", "working-directory"),
                                   {"id": "other", "type": "custom-job"}])
            cmd = [str(SCRIPT), "view", "--personal-codex", "--fixture-root", str(root), "--json", str(target)]
            def view(*args, report=jobs):
                result = subprocess.run([*cmd, *args], input=json.dumps(report), env=env, capture_output=True, text=True)
                data = json.loads(result.stdout)
                self.assertEqual(result.returncode, data["exit"])
                return data
            selected = ["--retained-scaffold", peer.name]
            observed = view(*selected, "--jobs-stdin")
            self.assertTrue(observed["ok"], observed)
            self.assertFalse(observed["removal_ready"])
            self.assertEqual([(row["id"], row["relation"]) for row in observed["configured_jobs"]["instances"]],
                             [("target", "selected-path"), ("peer", "other-spelling"),
                              ("ambiguous", "unresolved"), ("other", "unresolved")])
            def links(data):
                return {r["entry"]: r["relation"] for r in data["retained_scaffold_skills"][peer.name]["links"]}
            self.assertEqual(links(observed), {".agents/skills/local/table": "selected-path",
                                              ".agents/skills/whole": "selected-path",
                                              ".agents/skills/elsewhere": "other-spelling"})
            self.assertNotIn("configured_jobs", view(*selected))
            self.assertNotIn("retained_scaffold_skills", view("--jobs-stdin"))
            self.assertFalse(view("--jobs-stdin", report={**jobs, "complete": False})["ok"])
            self.assertFalse(view("--jobs-stdin", report={**jobs, "instances": jobs["instances"] * 2})["ok"])
            for name in (target.name.upper(), "chaos-scheduler", "../sample.reader"):
                self.assertFalse(view("--retained-scaffold", name)["ok"])
            self.assertFalse(view(*selected, *selected)["ok"])
            saved = peer / ".agents/saved"
            slots.rename(saved)
            slots.symlink_to(target / "missing")
            self.assertEqual(links(view(*selected)), {".agents/skills": "selected-path"})
            slots.unlink()
            saved.rename(slots)
            (local / ".git").touch()
            self.assertFalse(view(*selected)["ok"])
            # A copied peer's recorded inode binding belongs to its original directory.
            peer.rename(root / "original-reader")
            shutil.copytree(root / "original-reader", peer, symlinks=True)
            self.assertFalse(view(*selected)["ok"])

    def test_personal_view_before_the_fixture_provider_id_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            checkout = owner / "interrupted.sample"
            fixture_cli = root / "unused-provider"
            fixture_cli.write_text("#!/bin/sh\nexit 90\n")
            fixture_cli.chmod(0o700)
            env = {**os.environ, "DEV_SESSION_ID": "retirement-fixture-" + root.name,
                   "DOC_WARDEN_FIXTURE_GH_SOURCE": str(fixture_cli)}
            created = subprocess.run([str(ROOT / "_ops/bin/dev-new-repo.sh"), "--personal-codex",
                                      checkout.name, "--fixture-root", str(root), "--fixture-repository-id",
                                      "081357", "--fixture-interrupt-after", "initial-committed"],
                                     env=env, text=True, capture_output=True)
            self.assertEqual(created.returncode, 75, created.stderr)
            view = [str(SCRIPT), "view", "--personal-codex", "--json", str(checkout)]
            selected = [*view, "--fixture-root", str(root)]
            observed = json.loads(subprocess.check_output([*selected, "--fixture-repository-id", "081357"]))
            self.assertTrue(observed["creation_binding_matches"])
            self.assertIsNone(observed["recorded_repository_id"])
            for args, code in ((selected, 1), ([*selected, "--fixture-repository-id", "81357"], 1),
                               ([*view, "--fixture-repository-id", "081357"], 2)):
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, code)
                self.assertFalse(json.loads(result.stdout)["ok"])

            target = owner / "local.only"
            subprocess.run([str(ROOT / "_ops/bin/dev-new-repo.sh"), "--personal-codex", target.name,
                            "--fixture-root", str(root)], env=env, check=True, capture_output=True)
            retained = [str(SCRIPT), "view", "--personal-codex", "--json", str(target),
                        "--fixture-root", str(root), "--retained-scaffold"]
            match = json.loads(subprocess.check_output([*retained, checkout.name + "=081357"]))
            self.assertIsNone(match["recorded_repository_id"])
            self.assertEqual(match["retained_scaffold_skills"][checkout.name]["creation_record_sha256"],
                             observed["creation_record_sha256"])
            for selector, expected in [(checkout.name, 1), (checkout.name + "=81357", 1),
                                       (checkout.name + "=0", 2), (checkout.name + "=", 2)]:
                refused = subprocess.run([*retained, selector], capture_output=True)
                self.assertEqual(refused.returncode, expected)
                self.assertFalse(json.loads(refused.stdout)["ok"])

    # ------------------------------------------------------------------ preview / confirm basics
    def test_clean_checkout_end_to_end(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        outcome, data = fx.preview("personal/alpha")
        self.assertEqual(outcome.rc, 0, outcome.text)
        self.assertEqual(data["stage"], "preview")
        self.assertEqual(data["required_waivers"], [])
        self.assertEqual(data["required_attests"], [])
        self.assertTrue(repo.exists(), "a preview must not remove anything")
        op = data["operation"]
        self.assertEqual(fx.kinds(op), ["open", "preview"])
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual(done.data["outcome"], "executed")
        self.assertFalse(repo.exists())
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [], "no tombstone is left behind")
        verified = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(verified.rc, 0, verified.text)
        self.assertEqual(verified.data["stage"], "closed")
        self.assertEqual([c["status"] for c in verified.data["checks"]], ["pass"] * len(verified.data["checks"]))
        journal = fx.run("doctor", "--journal", fx.journal(op), "--json")
        self.assertEqual(journal.rc, 0, journal.text)
        report = journal.data
        self.assertTrue(report["chain_ok"] and report["contiguous"] and report["closed"] and report["close_digest_ok"])
        kinds = fx.kinds(op)
        self.assertEqual(kinds[:2], ["open", "preview"])
        self.assertEqual(kinds[-2:], ["verify", "close"])
        self.assertIn("baseline", kinds)
        self.assertIn("confirm", kinds)
        self.assertEqual(kinds.count("intent"), kinds.count("complete"))

    def test_preview_changes_nothing_except_its_own_state(self):
        fx = self.fx
        fx.repo("personal/alpha")
        fx.repo("personal/keep")
        before = {"dev": digest_tree(fx.dev), "outside": digest_tree(fx.outside), "sentinel": digest_tree(fx.sentinel)}
        out, data = fx.preview("personal/alpha")
        self.assertEqual(out.rc, 0, out.text)
        self.assertEqual(before, {"dev": digest_tree(fx.dev), "outside": digest_tree(fx.outside), "sentinel": digest_tree(fx.sentinel)})
        self.assertEqual(sorted(p.name for p in fx.home.rglob("*") if p.is_file()), sorted(["events.jsonl", "operation.json", ".writer.lock"]))

    def test_view_is_read_only_and_creates_no_state(self):
        fx = self.fx
        fx.repo("personal/alpha")
        before = digest_tree(fx.tmp)
        out = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(out.rc, 0, out.text)
        self.assertTrue(out.data["readonly"])
        self.assertEqual(digest_tree(fx.tmp), before)
        self.assertFalse(fx.state.exists())
        listing = fx.run("view", "--json")
        self.assertEqual(listing.rc, 0)
        self.assertEqual(listing.data["operations"], [])
        self.assertFalse(fx.state.exists(), "listing operations must not create the state folder")

    def test_confirmation_is_exact_and_boolean_tokens_are_invalid(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        other = fx.repo("personal/beta")
        _o, first = fx.preview("personal/alpha")
        _o, second = fx.preview("personal/beta")
        good = first["confirm_token"]
        bad = ["", "yes", "true", "1", "confirm", good[:-1], good + "0", good.upper(), second["confirm_token"], good.replace("confirm-", "confirmed-")]
        for token in bad:
            with self.subTest(token=token[:30]):
                args = ["remove", "--operation", first["operation"], "--json"]
                if token:
                    args += ["--confirm", token]
                out = fx.run(*args)
                self.assertEqual(out.rc, 1, out.text)
                self.assertIn("refused", out.data)
                self.assertTrue(repo.exists())
        crossed = fx.confirm(second, token=first["confirm_token"])
        self.assertEqual(crossed.rc, 1)
        self.assertTrue(repo.exists() and other.exists())
        self.assertEqual(fx.confirm(first).rc, 0)
        self.assertFalse(repo.exists())
        self.assertTrue(other.exists(), "confirming one operation never touches another's target")

    def test_double_confirm_and_closed_operations_are_refused(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0)
        again = fx.confirm(data)
        self.assertEqual(again.rc, 1)
        self.assertIn("already confirmed", again.data["refused"])
        self.assertEqual(fx.run("verify", "--operation", data["operation"]).rc, 0)
        closed = fx.confirm(data)
        self.assertEqual(closed.rc, 1)
        self.assertIn("closed", closed.data["refused"])
        self.assertEqual(fx.run("resume", "--operation", data["operation"]).rc, 1)

    def test_previews_expire_and_unused_previews_can_be_closed(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        late = fx.confirm(data, now=time.time() + 3601)
        self.assertEqual(late.rc, 1, late.text)
        self.assertIn("expired", late.data["refused"])
        self.assertTrue(repo.exists())
        unconfirmed = fx.run("verify", "--operation", data["operation"], "--json")
        self.assertEqual(unconfirmed.rc, 1)
        self.assertEqual(unconfirmed.data["stage"], "not-confirmed")
        closed = fx.run("verify", "--operation", data["operation"], "--discard-preview", "--json")
        self.assertEqual(closed.rc, 0, closed.text)
        self.assertEqual(closed.data["outcome"], "unused-preview")
        self.assertIn("closed", fx.confirm(data).data["refused"])
        self.assertTrue(repo.exists())

    # ------------------------------------------------------------------ risks and waivers
    def make_risky(self, name="risky"):
        fx = self.fx
        repo = fx.repo("personal/" + name)
        (repo / "README.md").write_text("stashed change\n")
        fx.git(repo, "stash", "push", "-q")
        (repo / "README.md").write_text("dirty change\n")
        (repo / "untracked.txt").write_text("only here\n")
        (repo / ".gitignore").write_text("*.dat\n")
        fx.git(repo, "add", ".gitignore")
        fx.git(repo, "commit", "-q", "-m", "local only")
        (repo / "cache.dat").write_text("ignored data\n")
        return repo

    def test_every_risk_needs_its_own_named_waiver(self):
        fx = self.fx
        repo = self.make_risky()
        _o, data = fx.preview("personal/risky")
        expected = ["dirty-tracked", "ignored-data", "stashes", "unpushed-commits", "untracked-files"]
        self.assertEqual(data["required_waivers"], expected)
        self.assertEqual(sorted(r["id"] for r in data["targets"][0]["risks"]), expected)
        digest = digest_tree(repo)
        attempts = {
            "none": [],
            "partial": expected[:-1],
            "extra-name": expected + ["linked-worktree-work"],
            "unknown-name": expected + ["everything"],
        }
        for label, waive in attempts.items():
            with self.subTest(waive=label):
                out = fx.confirm(data, waive=waive)
                self.assertEqual(out.rc, 1, out.text)
                self.assertEqual(digest_tree(repo), digest)
        generic = fx.run("remove", "--operation", data["operation"], "--confirm", data["confirm_token"], "--waive", "all", "--json")
        self.assertEqual(generic.rc, 1)
        self.assertEqual(digest_tree(repo), digest)
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(repo.exists())
        confirm = [e for e in fx.events(data["operation"]) if e["kind"] == "confirm"][0]
        self.assertEqual(confirm["waived"], expected)

    def test_no_remote_means_every_commit_is_unpushed(self):
        fx = self.fx
        fx.repo("personal/lonely", origin=False)
        _o, data = fx.preview("personal/lonely")
        target = data["targets"][0]
        self.assertEqual(data["required_waivers"], ["unpushed-commits"])
        detail = [r for r in target["risks"] if r["id"] == "unpushed-commits"][0]["detail"]
        self.assertTrue(detail["no_remote_configured"])

    def test_duplicate_origins_are_never_confused(self):
        fx = self.fx
        a = fx.repo("personal/dup-a")
        b = fx.repo("capabilities/dup-b")
        keep = fx.repo("personal/keep")
        for path in (a, b, keep):
            fx.git(path, "remote", "set-url", "origin", ORIGIN % "shared-name")
        keep_digest = digest_tree(keep)
        _o, data = fx.preview("personal/dup-a", "capabilities/dup-b")
        notes = " ".join(" ".join(t["notes"]) for t in data["targets"])
        self.assertIn("another local clone of kleinperkins/shared-name remains at personal/keep", notes)
        self.assertEqual(fx.confirm(data).rc, 0)
        self.assertFalse(a.exists() or b.exists())
        self.assertEqual(digest_tree(keep), keep_digest)
        twice = fx.run("remove", "personal/keep", "personal/keep", "--json")
        self.assertEqual(twice.rc, 1)
        self.assertIn("duplicate-target", [b["id"] for t in twice.data["targets"] for b in t["blockers"]])

    def test_nested_repositories_and_unfinished_operations_are_risks(self):
        fx = self.fx
        repo = fx.repo("personal/nest")
        inner = repo / "vendored"
        inner.mkdir()
        fx.git(inner, "init", "-q", "-b", "main")
        (inner / "x").write_text("x")
        (repo / ".git" / "MERGE_HEAD").write_text(fx.git(repo, "rev-parse", "HEAD"))
        _o, data = fx.preview("personal/nest")
        self.assertIn("nested-repos", data["required_waivers"])
        self.assertIn("operation-in-progress", data["required_waivers"])
        self.assertIn("untracked-files", data["required_waivers"])

    # ------------------------------------------------------------------ linked worktrees
    def test_clean_linked_worktree_is_removed_before_its_checkout(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.home / ".cursor" / "worktrees" / "alpha" / "wt-clean")
        _o, data = fx.preview("personal/alpha")
        kinds = [s["kind"] for s in data["steps"]]
        self.assertLess(kinds.index("worktree-remove"), kinds.index("delete-checkout"))
        self.assertEqual(data["required_waivers"], [])
        self.assertEqual(fx.confirm(data).rc, 0)
        self.assertFalse(wt.exists() or repo.exists())

    def test_a_locked_linked_worktree_blocks_removal_until_its_owner_unlocks_it(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.home / ".cursor" / "worktrees" / "alpha" / "wt-locked")
        fx.git(repo, "worktree", "lock", str(wt))
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(self.blockers(out), ["linked-worktree-locked"])
        self.assertFalse(fx.state.exists(), "a blocked preview creates nothing")
        self.assertTrue(wt.exists() and repo.exists())
        fx.git(repo, "worktree", "unlock", str(wt))
        _o, data = fx.preview("personal/alpha")
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(wt.exists() or repo.exists())

    def test_a_program_that_starts_using_a_linked_worktree_after_confirmation_stops_its_removal(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.home / ".cursor" / "worktrees" / "alpha" / "wt-clean")
        project = fx.home / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(repo)).strip("-")
        (project / "canvases").mkdir(parents=True)
        (project / "canvases" / "f.txt").write_text("x")
        (fx.tmp / "watch-cache").write_text(str(project / "canvases"))
        (fx.tmp / "watch-wt").write_text(str(wt))
        fx.adapter("lsof", LSOF_WORKTREE_AFTER_CACHE_SHIM)
        _o, data = fx.preview("personal/alpha")
        kinds = [s["kind"] for s in data["steps"]]
        self.assertLess(kinds.index("cache-remove"), kinds.index("worktree-remove"), "the cache step runs first, so the program appears mid-run")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(wt.exists() and repo.exists(), "nothing is removed once someone is using the worktree")
        refusal = [e for e in fx.events(data["operation"]) if e["kind"] == "refusal"][-1]
        self.assertIn("is in use by", refusal["reason"])
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(wt.exists() or repo.exists())

    def test_a_live_session_lock_inside_a_linked_worktrees_own_git_directory_blocks(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.home / ".cursor" / "worktrees" / "alpha" / "wt-clean")
        gitdir = Path(fx.git(wt, "rev-parse", "--absolute-git-dir").strip())
        self.assertNotEqual(gitdir, repo / ".git", "a linked worktree keeps its own bookkeeping directory")
        lock = gitdir / "cursor-session.lock"
        lock.write_text("pid=%d\nts=%d\ntoken=agent:test\n" % (os.getpid(), int(time.time())))
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(self.blockers(out), ["active-writer"])
        self.assertTrue(wt.exists() and repo.exists())
        lock.unlink()
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), [])

    def test_dirty_linked_worktree_needs_its_own_waiver(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.home / ".cursor" / "worktrees" / "alpha" / "wt-dirty")
        (wt / "scratch.txt").write_text("only in the worktree\n")
        _o, data = fx.preview("personal/alpha")
        self.assertEqual(data["required_waivers"], ["linked-worktree-work"])
        refused = fx.confirm(data, waive=[])
        self.assertEqual(refused.rc, 1)
        self.assertTrue(wt.exists() and repo.exists())
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(wt.exists() or repo.exists())

    def test_a_linked_worktree_in_an_unknown_place_blocks_removal(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.tmp / "elsewhere" / "wt-unknown")
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(self.blockers(out), ["worktree-unsafe-location"])
        self.assertTrue(wt.exists() and repo.exists())

    def test_git_metadata_cannot_point_removal_at_another_repository(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        other = fx.repo("personal/keep")
        admin = repo / ".git" / "worktrees" / "evil"
        admin.mkdir(parents=True)
        (admin / "gitdir").write_text(str(other / ".git") + "\n")
        (admin / "HEAD").write_text("ref: refs/heads/main\n")
        (admin / "commondir").write_text("../..\n")
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertIn("worktree-unsafe-location", self.blockers(out))
        self.assertTrue((other / ".git").is_dir() and (other / "README.md").exists() and repo.exists())

    def test_awa_managed_worktrees_use_the_owning_verb(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        awa_root = fx.home / ".local" / "share" / "awa" / "worktrees"
        wt = fx.linked_worktree(repo, awa_root / "alpha-1")
        fx.adapter("worktree", WORKTREE_SHIM)
        (fx.tmp / "worktree.mode").write_text("remove")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        calls = (fx.tmp / "worktree.calls").read_text()
        self.assertIn("clean --path %s" % wt, calls)
        self.assertFalse(wt.exists() or repo.exists())

    def test_awa_refusal_on_a_clean_worktree_falls_back_to_plain_git(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        awa_root = fx.home / ".local" / "share" / "awa" / "worktrees"
        wt = fx.linked_worktree(repo, awa_root / "alpha-1")
        fx.adapter("worktree", WORKTREE_SHIM)
        (fx.tmp / "worktree.mode").write_text("refuse")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(wt.exists() or repo.exists())

    def test_awa_refusal_with_waived_work_is_forced_through_git(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        awa_root = fx.home / ".local" / "share" / "awa" / "worktrees"
        wt = fx.linked_worktree(repo, awa_root / "alpha-1")
        (wt / "scratch.txt").write_text("only here\n")
        fx.adapter("worktree", WORKTREE_SHIM)
        (fx.tmp / "worktree.mode").write_text("refuse")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(data["required_waivers"], ["linked-worktree-work"])
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(wt.exists() or repo.exists())

    # ------------------------------------------------------------------ writers and concurrent agents
    def blockers(self, out):
        return sorted(b["id"] for t in out.data["targets"] for b in t["blockers"])

    def test_active_writers_and_self_inside_are_blocking_and_not_waivable(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.lsof([(424242, "node", "cwd", str(repo))])
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1)
        self.assertEqual(out.data["stage"], "blocked")
        self.assertEqual(self.blockers(out), ["active-writer"])
        self.assertFalse(fx.state.exists(), "a blocked preview creates no operation")
        fx.lsof([(os.getpid(), "python", "cwd", str(repo / "sub"))])
        mine = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(self.blockers(mine), ["self-inside"])
        fx.lsof_on()
        inside = fx.run("view", "personal/alpha", "--json", cwd=repo / "sub")
        self.assertEqual(self.blockers(inside), ["self-inside"])
        self.assertTrue(fx.run("view", "personal/alpha", "--json").rc == 0)
        self.assertEqual(fx.run("remove", "personal/alpha", "--waive", "active-writer", "--json").rc, 2)

    def test_session_locks_awa_leases_and_git_locks_block(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        lock = repo / ".git" / "cursor-session.lock"
        now = int(time.time())
        lock.write_text("pid=%d\nts=%d\ntoken=agent:test\n" % (os.getpid(), now))
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), ["active-writer"])
        finished = subprocess.Popen(["true"])
        finished.wait()
        lock.write_text("pid=%d\nts=%d\ntoken=agent:test\n" % (finished.pid, now))
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), [], "a dead owner's lock is stale")
        lock.write_text("pid=%d\nts=%d\ntoken=agent:test\n" % (os.getpid(), now - 10 * 86400))
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), [], "an expired lock is stale")
        lock.unlink()
        (repo / ".awa").mkdir()
        (repo / ".awa" / "lease.json").write_text("{}")
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), ["awa-lease-present"])
        (repo / ".awa" / "lease.json").unlink()
        (repo / ".awa").rmdir()
        (repo / ".git" / "index.lock").write_text("")
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), ["git-index-locked"])
        (repo / ".git" / "index.lock").unlink()
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), [])

    def test_a_writer_appearing_after_the_preview_stops_the_confirmation(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        fx.lsof([(424242, "node", "cwd", str(repo))])
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertIn("blocker appeared", out.data["refused"])
        self.assertTrue(repo.exists())
        fx.lsof_on()
        self.assertEqual(fx.confirm(data).rc, 0)

    def test_real_process_table_catches_a_running_program(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        (fx.ad / "lsof").unlink()
        real = shutil.which("lsof")
        if not real:
            self.skipTest("lsof is not installed")
        proc = subprocess.Popen(["sleep", "60"], cwd=str(repo))
        self.addCleanup(proc.kill)
        out = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(out.rc, 0, out.text)
        self.assertEqual(self.blockers(out), ["active-writer"])
        proc.kill()
        proc.wait()
        clean = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(self.blockers(clean), [])

    # ------------------------------------------------------------------ affirm/ policy gate
    def test_affirm_checkouts_are_an_operator_gate_until_policy_and_proof_exist(self):
        fx = self.fx
        src = fx.repo("affirm/src/work-one")
        vendor = fx.repo("affirm/vendor/ref-one")
        out = fx.run("remove", "affirm/src/work-one", "affirm/vendor/ref-one", "--json")
        self.assertEqual(out.rc, 1)
        self.assertEqual(self.blockers(out), ["affirm-policy-gate", "affirm-policy-gate"])
        self.assertTrue(src.exists() and vendor.exists())
        self.assertFalse(fx.state.exists())
        fx.policy(True)
        fx.lsof_off()
        proofless = fx.run("remove", "affirm/vendor/ref-one", "--json")
        self.assertEqual(self.blockers(proofless), ["affirm-writer-proof"])
        fx.lsof_on()
        fx.lsof([(424242, "node", "cwd", str(vendor))])
        busy = fx.run("remove", "affirm/vendor/ref-one", "--json")
        self.assertEqual(self.blockers(busy), ["active-writer"])
        fx.lsof_on()
        data, done = fx.run_all("affirm/vendor/ref-one")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(vendor.exists())
        self.assertTrue(src.exists(), "only the named checkout is removed")

    def test_the_policy_marker_must_be_exact(self):
        fx = self.fx
        fx.repo("affirm/vendor/ref-one")
        policy = fx.dev / "_ops" / "POLICY.md"
        for text in (
            "<!-- policy:dev-remove-repo-affirm-exception/v2 -->\n",
            "the marker policy:dev-remove-repo-affirm-exception/v1 is mentioned in prose only\n",
            "<!-- policy:dev-remove-repo-affirm-exception/v1 --> trailing words\n",
        ):
            policy.write_text(text)
            self.assertEqual(self.blockers(fx.run("view", "affirm/vendor/ref-one", "--json")), ["affirm-policy-gate"], text)
        policy.write_text("intro\n  <!-- policy:dev-remove-repo-affirm-exception/v1 -->  \noutro\n")
        self.assertNotIn("affirm-policy-gate", self.blockers(fx.run("view", "affirm/vendor/ref-one", "--json")))

    # ------------------------------------------------------------------ path safety
    def test_protected_targets_and_malformed_paths_are_refused_and_create_nothing(self):
        fx = self.fx
        fx.repo("personal/alpha")
        for protected in ("affirm/src/card-platform-product", "capabilities/skills", "capabilities/mcp", "personal/chaos-scheduler"):
            fx.repo(protected)
        before = digest_tree(fx.dev)
        cases = {
            "affirm/src/card-platform-product": "protected-target",
            "capabilities/skills": "protected-target",
            "capabilities/mcp": "protected-target",
            "personal/chaos-scheduler": "protected-target",
            "alpha": "path-invalid",
            "personal": "path-invalid",
            "affirm": "path-invalid",
            "affirm/src": "path-invalid",
            ".": "path-invalid",
            "..": "path-invalid",
            "personal/../personal/alpha": "path-invalid",
            "personal//alpha": "path-invalid",
            "personal/alpha/": "path-invalid",
            "personal/alpha/sub": "path-invalid",
            "personal/al\x01pha": "path-invalid",
            "/etc": "path-invalid",
            "/tmp": "path-invalid",
            str(fx.dev): "path-invalid",
            str(fx.home): "path-invalid",
            "": "path-invalid",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                out = fx.run("remove", raw, "--json")
                self.assertEqual(out.rc, 1, out.text)
                got = [b["id"] for t in out.data["targets"] for b in t["blockers"]]
                self.assertEqual(got, [expected])
        self.assertEqual(fx.run("remove", "-rf", "--json").rc, 2, "an option-like word is a usage error")
        smuggled = fx.run("remove", "--json", "--", "-rf")
        self.assertEqual(smuggled.rc, 1, smuggled.text)
        self.assertEqual([b["id"] for t in smuggled.data["targets"] for b in t["blockers"]], ["path-invalid"])
        self.assertEqual(digest_tree(fx.dev), before)
        self.assertFalse(fx.state.exists())

    def test_rejected_targets_do_not_start_repository_or_host_observation(self):
        engine = self.load_engine()
        class LexicalContext:
            root = str(self.fx.dev)

        def unexpected(*args, **kwargs):
            self.fail("lexically rejected targets must stop before any observation")

        for observer in ("fleet_slugs", "slug_index_for", "inspect_fs", "attach_wiring"):
            engine[observer] = unexpected
        targets, scan = engine["assess_targets"](LexicalContext(), [
            "personal/chaos-scheduler", "capabilities/skills", "personal/../personal/alpha",
        ])
        self.assertEqual([t["blockers"][0]["id"] for t in targets],
                         ["protected-target", "protected-target", "path-invalid"])
        self.assertEqual(scan, {"engine": "none", "note": ""})

    def test_a_protected_checkout_is_protected_whatever_its_letter_case(self):
        fx = self.fx
        spellings = ("personal/Chaos-Scheduler", "capabilities/SKILLS", "capabilities/Mcp", "affirm/src/Card-Platform-Product")
        for spelled in spellings:
            fx.repo(spelled)
        before = digest_tree(fx.dev)
        for spelled in spellings:
            with self.subTest(spelled=spelled):
                out = fx.run("remove", spelled, "--json")
                self.assertEqual(out.rc, 1, out.text)
                self.assertEqual([b["id"] for t in out.data["targets"] for b in t["blockers"]], ["protected-target"])
        self.assertEqual(digest_tree(fx.dev), before)
        self.assertFalse(fx.state.exists())

    def test_a_mixed_batch_with_one_bad_path_does_nothing(self):
        fx = self.fx
        alpha = fx.repo("personal/alpha")
        fx.repo("capabilities/skills")
        out = fx.run("remove", "personal/alpha", "capabilities/skills", "--json")
        self.assertEqual(out.rc, 1)
        self.assertTrue(alpha.exists())
        self.assertFalse(fx.state.exists())

    def test_symlinked_targets_and_parents_are_never_followed(self):
        fx = self.fx
        decoy = fx.repo("personal/decoy")
        decoy_digest = digest_tree(decoy)
        decoy_real = fx.outside / "real-repo"
        shutil.copytree(str(decoy), str(decoy_real), symlinks=True)
        os.symlink(str(decoy_real), str(fx.dev / "personal" / "linked"))
        out = fx.run("remove", "personal/linked", "--json")
        self.assertEqual(out.rc, 1)
        self.assertEqual(self.blockers(out), ["path-unsafe"])
        # a symlinked parent
        shutil.rmtree(str(fx.dev / "capabilities"))
        (fx.outside / "caps").mkdir()
        shutil.copytree(str(decoy), str(fx.outside / "caps" / "victim"), symlinks=True)
        os.symlink(str(fx.outside / "caps"), str(fx.dev / "capabilities"))
        parent = fx.run("remove", "capabilities/victim", "--json")
        self.assertEqual(parent.rc, 1)
        self.assertEqual(self.blockers(parent), ["path-unsafe"])
        self.assertEqual(digest_tree(decoy_real), decoy_digest)
        self.assertEqual(digest_tree(fx.outside / "caps" / "victim"), decoy_digest)

    def test_symlinks_inside_a_checkout_are_removed_not_followed(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        decoy = fx.outside / "precious"
        (decoy / "deep").mkdir(parents=True)
        (decoy / "deep" / "keep.txt").write_text("precious\n")
        (decoy / "top.txt").write_text("precious\n")
        decoy_digest = digest_tree(decoy)
        os.symlink(str(decoy), str(repo / "link-to-dir"))
        os.symlink(str(decoy / "top.txt"), str(repo / "link-to-file"))
        os.symlink("does-not-exist", str(repo / "dangling"))
        data, done = fx.run_all("personal/alpha", waive=["untracked-files"])
        self.assertEqual(data["required_waivers"], ["untracked-files"])
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(repo.exists())
        self.assertEqual(digest_tree(decoy), decoy_digest, "nothing behind a link was touched")

    def test_swapping_the_target_for_a_link_after_the_preview_is_refused(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        decoy = fx.repo("personal/decoy")
        decoy_digest = digest_tree(decoy)
        _o, data = fx.preview("personal/alpha")
        moved = fx.dev / "personal" / "alpha.moved"
        repo.rename(moved)
        os.symlink(str(decoy), str(repo))
        moved_digest = digest_tree(moved)
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(digest_tree(decoy), decoy_digest)
        self.assertEqual(digest_tree(moved), moved_digest)
        self.assertTrue(repo.is_symlink())

    def test_special_files_make_a_checkout_unremovable(self):
        fx = self.fx
        fifo_repo = fx.repo("personal/with-fifo")
        os.mkfifo(str(fifo_repo / "pipe"))
        sock_repo = fx.repo("personal/with-socket")
        short = Path(tempfile.mkdtemp(prefix="drrs", dir="/tmp"))
        self.addCleanup(shutil.rmtree, str(short), ignore_errors=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(short / "s"))
        os.rename(str(short / "s"), str(sock_repo / "s"))
        for rel in ("personal/with-fifo", "personal/with-socket"):
            with self.subTest(rel=rel):
                out = fx.run("remove", rel, "--json")
                self.assertEqual(out.rc, 1)
                self.assertIn("special-files", self.blockers(out))

    def test_plain_directories_and_linked_checkouts_are_not_removable(self):
        fx = self.fx
        (fx.dev / "personal" / "plain-dir").mkdir()
        (fx.dev / "personal" / "plain-dir" / "notes.txt").write_text("not a repo\n")
        out = fx.run("remove", "personal/plain-dir", "--json")
        self.assertEqual(self.blockers(out), ["not-a-checkout"])
        repo = fx.repo("personal/alpha")
        wt = fx.linked_worktree(repo, fx.dev / "personal" / "alpha-wt")
        gitfile = fx.run("remove", "personal/alpha-wt", "--json")
        self.assertEqual(self.blockers(gitfile), ["gitfile-checkout"])
        self.assertTrue(wt.exists())

    # ------------------------------------------------------------------ state changed after the preview
    def test_any_change_after_the_preview_forces_a_new_preview(self):
        fx = self.fx

        def new_file(repo):
            (repo / "late.txt").write_text("late\n")

        def edit_file(repo):
            (repo / "README.md").write_text("late edit\n")

        def new_commit(repo):
            fx.commit(repo, "late-commit.txt", "late\n")

        def stash(repo):
            (repo / "README.md").write_text("to stash\n")
            fx.git(repo, "stash", "push", "-q")

        def delete_file(repo):
            (repo / "sub" / "a.txt").unlink()

        for name, mutate in (
            ("new-file", new_file),
            ("edit-file", edit_file),
            ("new-commit", new_commit),
            ("stash", stash),
            ("delete-file", delete_file),
        ):
            with self.subTest(change=name):
                repo = fx.repo("personal/c-" + name)
                _o, data = fx.preview("personal/c-" + name)
                mutate(repo)
                digest = digest_tree(repo)
                out = fx.confirm(data)
                self.assertEqual(out.rc, 1, out.text)
                self.assertTrue(repo.exists())
                self.assertEqual(digest_tree(repo), digest)
                events = fx.kinds(data["operation"])
                self.assertNotIn("intent", events)

    def test_a_replaced_directory_with_identical_contents_is_not_the_previewed_one(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        copy = fx.dev / "personal" / "alpha.copy"
        shutil.copytree(str(repo), str(copy), symlinks=True)
        shutil.rmtree(str(repo))
        copy.rename(repo)
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(repo.exists())

    def test_restoring_the_previewed_state_makes_the_same_confirmation_valid_again(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        before = os.stat(str(repo))
        (repo / "late.txt").write_text("late\n")
        self.assertEqual(fx.confirm(data).rc, 1)
        (repo / "late.txt").unlink()
        os.utime(str(repo), ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(fx.confirm(data).rc, 0)

    # ------------------------------------------------------------------ interruption and resume
    def interrupted_run(self, point_kind, **kw):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="%s:%s" % (point_kind, sid), **kw)
        return repo, data, sid, out

    def test_interruption_at_every_point_resumes_idempotently(self):
        for point in ("after-intent", "after-rename", "mid-delete", "after-action", "after-complete"):
            with self.subTest(point=point):
                fx = Fx(self)
                self.fx = fx
                repo, data, sid, out = self.interrupted_run(point)
                self.assertEqual(out.rc, 75, out.text)
                op = data["operation"]
                status = fx.run("view", "--operation", op, "--json")
                if point == "after-intent":
                    self.assertTrue(repo.exists())
                    self.assertEqual(status.data["status"], "interrupted")
                if point in ("after-rename", "mid-delete"):
                    self.assertFalse(repo.exists(), "the real path disappears at the first moment")
                    self.assertEqual(status.data["status"], "interrupted")
                    leftover = [p.name for p in (fx.dev / "personal").iterdir()]
                    self.assertEqual(len(leftover), 1)
                    self.assertTrue(re.match(r"^\.drr-[0-9a-f]{16}\.removing$", leftover[0]))
                    doctor = fx.run("doctor", "--json")
                    self.assertIn("leftover-removals", [c["id"] for c in doctor.data["checks"] if c["status"] == "warn"])
                if point == "after-complete":
                    self.assertEqual(status.data["status"], "executed")
                    self.assertEqual(fx.run("resume", "--operation", op, "--json").rc, 1, "nothing is left to resume")
                else:
                    resumed = fx.run("resume", "--operation", op, "--json")
                    self.assertEqual(resumed.rc, 0, resumed.text)
                    self.assertEqual(resumed.data["outcome"], "executed")
                self.assertFalse(repo.exists())
                self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [])
                again = fx.run("resume", "--operation", op, "--json")
                self.assertEqual(again.rc, 1, "a finished operation has nothing to resume")
                self.assertEqual(fx.run("verify", "--operation", op, "--json").rc, 0)
                events = fx.events(op)
                intents = [e for e in events if e["kind"] == "intent" and e.get("step") == sid]
                completes = [e for e in events if e["kind"] == "complete" and e.get("step") == sid]
                self.assertEqual(len(intents), 1, "an interrupted step is never re-announced")
                self.assertEqual(len(completes), 1)

    def test_resume_distinguishes_a_moved_checkout_from_a_finished_removal(self):
        fx = self.fx
        repo, data, sid, stopped = self.interrupted_run("after-intent")
        self.assertEqual(stopped.rc, 75)
        preserved = fx.outside / "temporarily-moved"
        repo.rename(preserved)
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertFalse(any(e["kind"] == "complete" and e.get("step") == sid for e in fx.events(data["operation"])))
        self.assertTrue((preserved / "README.md").is_file())
        preserved.rename(repo)
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)

    def test_resume_preserves_new_work_in_an_already_emptied_checkout(self):
        fx = self.fx
        repo, data, sid, stopped = self.interrupted_run("after-empty")
        self.assertEqual(stopped.rc, 75, stopped.text)
        marker, = repo.parent.glob(".drr-*.removing")
        self.assertEqual(list(marker.iterdir()), [])
        late = marker / "new-work.txt"
        late.write_text("unfinished work\n")
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertEqual(late.read_text(), "unfinished work\n")
        late.rename(fx.outside / late.name)
        resumed = fx.run("resume", "--operation", data["operation"], "--json", interrupt="after-action:" + sid)
        self.assertEqual(resumed.rc, 75, resumed.text)
        self.assertFalse(marker.exists())
        self.assertEqual(fx.run("resume", "--operation", data["operation"], "--json").rc, 0)
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)
        self.assertEqual(sum(e["kind"] == "checkout-empty" and e.get("step") == sid for e in fx.events(data["operation"])), 1)
        self.assertEqual(sum(e["kind"] == "checkout-unlinked" and e.get("step") == sid for e in fx.events(data["operation"])), 1)

    def test_resume_keeps_the_operation_open_if_final_unlink_evidence_was_lost(self):
        fx = self.fx
        repo, data, sid, stopped = self.interrupted_run("before-unlink-receipt")
        self.assertEqual(stopped.rc, 75, stopped.text)
        self.assertFalse(repo.exists())
        self.assertEqual(list(repo.parent.glob(".drr-*.removing")), [])
        op = data["operation"]
        before = fx.journal(op).read_bytes()
        self.assertEqual(fx.run("resume", "--operation", op, "--json").rc, 1)
        self.assertEqual(fx.run("verify", "--operation", op, "--json").rc, 1)
        self.assertTrue(fx.journal(op).read_bytes().startswith(before))
        self.assertFalse(any(e["kind"] in ("complete", "checkout-unlinked") and e.get("step") == sid for e in fx.events(op)))
        self.assertNotIn("close", fx.kinds(op))

    def test_final_absence_requires_the_parent_that_held_the_emptied_checkout(self):
        fx = self.fx
        repo, data, sid, stopped = self.interrupted_run("after-action")
        self.assertEqual(stopped.rc, 75, stopped.text)
        parent = repo.parent
        saved = fx.outside / "original-parent"
        parent.rename(saved)
        parent.mkdir()
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertFalse(any(e["kind"] == "complete" and e.get("step") == sid for e in fx.events(data["operation"])))
        parent.rmdir()
        saved.rename(parent)
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)

    def test_a_resume_re_proves_nothing_is_using_the_partly_removed_checkout(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        fx.lsof([(424242, "node", "cwd", str(marker))])
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(marker.exists(), "nothing is deleted while a program is using it")
        fx.lsof_on()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(marker.exists())

    def test_a_resume_run_from_inside_the_partly_removed_checkout_is_refused(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        refused = fx.run("resume", "--operation", data["operation"], "--json", cwd=marker)
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(marker.exists())
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)

    def test_remote_names_and_slugs_come_from_git_config_z_output(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.git(repo, "remote", "add", "upstream", "https://token-user:not-a-real-credential@example.com/Other/alpha-fork.git")
        fx.fleet(["other/alpha-fork"])
        out = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(sorted(r["name"] for r in out.data["targets"][0]["git"]["remotes"]), ["origin", "upstream"])
        self.assertNotIn("not-a-real-credential", out.text)
        self.assertEqual(self.blockers(out), ["pac-fleet-enrolled"])

    def test_a_program_that_was_inside_before_the_rename_is_still_found_by_the_resume(self):
        fx = self.fx
        if not shutil.which("lsof"):
            self.skipTest("lsof is not installed")
        repo = fx.repo("personal/alpha")
        proc = subprocess.Popen(["sleep", "60"], cwd=str(repo))  # the fixture lsof shim does not report it
        self.addCleanup(proc.kill)
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        (fx.ad / "lsof").unlink()  # from here on the real process table is consulted
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(marker.exists(), "the renamed directory is still reported under its new path")
        proc.kill()
        proc.wait()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(marker.exists())

    def test_writer_check_outage_after_rename_preserves_personal_checkout_until_recovery(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        before = digest_tree(repo)
        fx.adapter("lsof", """#!/bin/sh
test -d "$DEV_REMOVE_REPO_FIXTURE_ROOT/dev/personal/alpha" || exit 2
printf 'p1\\ncinit\\nftxt\\nn/sbin/init\\n'
""")
        preview, data = fx.preview("personal/alpha")
        self.assertEqual(preview.rc, 0, preview.text)
        self.assertNotIn("writer-proof-unavailable", data["required_waivers"])
        first = fx.confirm(data)
        self.assertEqual(first.rc, 1, first.text)
        marker, = repo.parent.glob(".drr-*.removing")
        self.assertEqual(digest_tree(marker), before)
        operation = data["operation"]
        failure = [e for e in fx.events(operation) if e["kind"] == "failure"][-1]
        self.assertIn("writer-proof-unavailable", failure["reason"])
        retry = fx.run("resume", "--operation", operation, "--json")
        self.assertEqual(retry.rc, 1, retry.text)
        self.assertEqual(digest_tree(marker), before)
        self.assertNotIn("purge-start", fx.kinds(operation))
        fx.adapter("lsof", LSOF_SHIM)
        recovered = fx.run("resume", "--operation", operation, "--json")
        self.assertEqual(recovered.rc, 0, recovered.text)
        self.assertFalse(marker.exists())

    def test_previewed_writer_check_outage_remains_waivable_on_personal_resume(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.lsof_off()
        preview, data = fx.preview("personal/alpha")
        self.assertEqual(preview.rc, 0, preview.text)
        self.assertIn("writer-proof-unavailable", data["required_waivers"])
        step, = fx.step_ids(data, "delete-checkout")
        stopped = fx.confirm(data, interrupt="after-rename:" + step)
        self.assertEqual(stopped.rc, 75, stopped.text)
        marker, = repo.parent.glob(".drr-*.removing")
        fx.lsof_on()
        fx.lsof([(424242, "editor", "cwd", str(marker))])
        blocked = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(blocked.rc, 1, blocked.text)
        self.assertTrue(marker.is_dir())
        fx.lsof_off()
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertFalse(marker.exists())

    def test_an_affirm_resume_without_writer_proof_stops_and_leaves_the_marker(self):
        fx = self.fx
        fx.policy(True)
        repo = fx.repo("affirm/vendor/ref-one")
        _o, data = fx.preview("affirm/vendor/ref-one")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        marker = [p for p in (fx.dev / "affirm" / "vendor").iterdir()][0]
        fx.lsof_off()
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(marker.exists())
        fx.lsof_on()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(marker.exists())

    def test_an_unfinished_removal_is_never_mistaken_for_an_absent_checkout(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        op = data["operation"]
        early = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(early.rc, 1, early.text)
        self.assertIn("paths-absent", [c["id"] for c in early.data["checks"] if c["status"] == "fail"])
        again = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(again.rc, 1, again.text)
        self.assertEqual(self.blockers(again), ["removal-marker-present"])
        self.assertNotEqual(again.data["stage"], "nothing-to-do")
        self.assertTrue(marker.exists())
        self.assertEqual(fx.run("resume", "--operation", op, "--json").rc, 0)
        clean = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(clean.data["stage"], "nothing-to-do", clean.text)

    def test_a_removal_marker_that_belongs_to_another_checkout_does_not_block_an_unrelated_absent_path(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75)
        unrelated = fx.run("view", "personal/never-existed", "--json")
        self.assertEqual(self.blockers(unrelated), [], unrelated.text)
        own = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(self.blockers(own), ["removal-marker-present"], "the checkout the marker belongs to is still never reported as gone")
        (fx.dev / "personal" / ".drr-0123456789abcdef.removing").mkdir()
        unexplained = fx.run("view", "personal/never-existed", "--json")
        self.assertEqual(self.blockers(unexplained), ["removal-marker-present"], "a marker that no recorded operation made is not trusted to be harmless")

    def test_resume_re_checks_every_pending_target_before_continuing(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-intent")
        self.assertEqual(out.rc, 75)
        cfg = fx.home / ".cursor" / "mcp.json"
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text('{"servers": {"x": {"command": "%s/run.sh"}}}\n' % repo)
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(repo.exists(), "a blocker that appeared after the interruption stops the resume")
        last = fx.events(data["operation"])[-1]
        self.assertEqual((last["kind"], last["result"]), ("rescan", "changed"))
        self.assertTrue(any("client" in c or "mcp" in c for c in last["changed"]), last)
        cfg.unlink()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(repo.exists())

    def test_a_resumed_partial_deletion_never_follows_a_swapped_marker(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("mid-delete")
        self.assertEqual(out.rc, 75)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        shutil.rmtree(str(marker), onerror=clear_readonly)
        decoy = fx.outside / "decoy"
        (decoy / "x").mkdir(parents=True)
        (decoy / "x" / "keep.txt").write_text("keep\n")
        digest = digest_tree(decoy)
        os.symlink(str(decoy), str(marker))
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 1, resumed.text)
        self.assertEqual(digest_tree(decoy), digest)

    def test_a_new_checkout_at_the_same_path_is_never_deleted_by_a_resume(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75)
        fresh = fx.repo("personal/alpha")
        (fresh / "precious.txt").write_text("new work\n")
        digest = digest_tree(fresh)
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertNotEqual(resumed.data.get("outcome"), "executed")
        self.assertEqual(digest_tree(fresh), digest, "the unrelated new checkout is untouched")

    def test_resume_refuses_when_the_state_changed_before_any_deletion_started(self):
        fx = self.fx
        repo, data, sid, out = self.interrupted_run("after-intent")
        self.assertEqual(out.rc, 75)
        (repo / "late.txt").write_text("late\n")
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 1, resumed.text)
        self.assertTrue(repo.exists())
        self.assertTrue((repo / "late.txt").exists())

    def test_removing_an_already_absent_checkout_is_a_clean_no_op(self):
        fx = self.fx
        out = fx.run("remove", "personal/never-existed", "--json")
        self.assertEqual(out.rc, 0, out.text)
        self.assertEqual(out.data["stage"], "nothing-to-do")
        self.assertFalse(fx.state.exists())
        gone = fx.repo("personal/alpha")
        keep = fx.repo("personal/beta")
        _o, data = fx.preview("personal/alpha", "personal/beta")
        shutil.rmtree(str(gone))
        self.assertEqual(fx.confirm(data).rc, 1, "a vanished target changes the plan; preview again")
        self.assertTrue(keep.exists())

    # ------------------------------------------------------------------ cohorts and rescans
    def test_cohorts_are_bounded_ordered_and_rescanned(self):
        fx = self.fx
        paths = ["personal/p%d" % i for i in range(1, 4)] + ["capabilities/c1", "affirm/vendor/v1"]
        fx.policy(True)
        repos = [fx.repo(p) for p in paths]
        _o, data = fx.preview(*paths, extra=["--cohort-size", "2"])
        classes = [c["root_class"] for c in data["cohorts"]]
        self.assertEqual(classes, sorted(classes, key=["affirm-vendor", "affirm-src", "personal", "capabilities"].index))
        self.assertTrue(all(len(c["targets"]) <= 2 for c in data["cohorts"]))
        self.assertGreaterEqual(len(data["cohorts"]), 3)
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([r.exists() for r in repos], [False] * 5)
        kinds = fx.kinds(data["operation"])
        self.assertGreaterEqual(kinds.count("rescan"), len(data["cohorts"]) - 1)
        bad = fx.run("remove", *paths, "--cohort-size", "0", "--json")
        self.assertEqual(bad.rc, 2)
        self.assertEqual(fx.run("remove", *paths, "--cohort-size", "6", "--json").rc, 2)

    def test_a_writer_that_appears_between_cohorts_pauses_the_rest(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        _o, data = fx.preview("personal/first", "personal/second", extra=["--cohort-size", "1"])
        first_step = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-complete:" + first_step)
        self.assertEqual(out.rc, 75)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        fx.lsof([(424242, "node", "cwd", str(second))])
        paused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(paused.rc, 1, paused.text)
        self.assertEqual(paused.data["outcome"], "paused")
        self.assertTrue(second.exists())
        status = fx.run("view", "--operation", data["operation"], "--json")
        self.assertEqual(status.data["status"], "paused")
        fx.lsof_on()
        finished = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(finished.rc, 0, finished.text)
        self.assertFalse(second.exists())

    def test_too_many_targets_are_refused(self):
        fx = self.fx
        for i in range(26):
            (fx.dev / "personal" / ("r%02d" % i)).mkdir()
        out = fx.run("remove", *["personal/r%02d" % i for i in range(26)] + ["--json"])
        self.assertEqual(out.rc, 1)
        self.assertIn("too-many-targets", self.blockers(out))

    # ------------------------------------------------------------------ verify and the exception ledger
    def executed(self, *paths, waive=None):
        data, done = self.fx.run_all(*paths, waive=waive)
        self.assertEqual(done.rc, 0, done.text)
        return data["operation"]

    def test_verify_requires_every_remaining_mention_to_map_to_an_exception(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keeper = fx.repo("personal/keep")
        (keeper / "notes.md").write_text("see personal/alpha for the old tool\n")
        fx.git(keeper, "add", "-A")
        fx.git(keeper, "commit", "-q", "-m", "notes")
        fx.push_state(keeper)
        _o, preview = fx.preview("personal/alpha")
        self.assertEqual(preview["required_waivers"], ["consumer-mentions"])
        self.assertEqual(fx.confirm(preview).rc, 0)
        op = preview["operation"]
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1)
        self.assertEqual([c["id"] for c in failed.data["checks"] if c["status"] == "fail"], ["mentions"])
        self.assertEqual(failed.data["stage"], "open")
        self.assertNotIn("close", fx.kinds(op))
        passed = fx.run("verify", "--operation", op, "--exception", "retained-reference:personal/keep/notes.md:left on purpose; owner updates next release", "--json")
        self.assertEqual(passed.rc, 0, passed.text)
        self.assertEqual(passed.data["stage"], "closed")
        close = fx.events(op)[-1]
        self.assertEqual(close["kind"], "close")
        self.assertEqual(close["outcome"], "verified-with-exceptions")
        self.assertEqual(close["exceptions"], 1)

    def test_verify_finds_a_mixed_case_remote_mention_and_needs_an_exception(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keeper = fx.repo("personal/keep")
        (keeper / "notes.md").write_text("origin was https://github.com/KleinPerkins/Alpha.git\n")
        fx.git(keeper, "add", "-A")
        fx.git(keeper, "commit", "-q", "-m", "notes")
        fx.push_state(keeper)
        op = self.executed("personal/alpha")
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        self.assertEqual([c["id"] for c in failed.data["checks"] if c["status"] == "fail"], ["mentions"])
        passed = fx.run("verify", "--operation", op, "--exception", "historical-record:personal/keep/notes.md:records where the tool once lived", "--json")
        self.assertEqual(passed.rc, 0, passed.text)

    def test_a_home_folder_mention_is_excepted_with_a_tilde_scope(self):
        fx = self.fx
        fx.repo("personal/alpha")
        op = self.executed("personal/alpha")
        (fx.home / ".cursor").mkdir(exist_ok=True)
        (fx.home / ".cursor" / "mcp.json").write_text('{"note": "personal/alpha"}\n')
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        self.assertEqual([c["id"] for c in failed.data["checks"] if c["status"] == "fail"], ["mentions"])
        for bad in ("~", "~/", "~other/.cursor/mcp.json"):
            refused = fx.run("verify", "--operation", op, "--exception", "retained-reference:%s:left on purpose, owner decides" % bad, "--json")
            self.assertEqual(refused.rc, 2, "%s: %s" % (bad, refused.text))
        passed = fx.run("verify", "--operation", op, "--exception", "retained-reference:~/.cursor/mcp.json:left on purpose; the client owner updates it", "--json")
        self.assertEqual(passed.rc, 0, passed.text)

    def test_exception_ledger_rejects_dishonest_or_dangerous_entries(self):
        fx = self.fx
        fx.repo("personal/alpha")
        op = self.executed("personal/alpha")
        bad = [
            "made-up-class:personal/x:long enough reason here",
            "retained-reference:personal/x:short",
            "retained-reference::long enough reason here",
            "retained-reference:../escape:long enough reason here",
            "retained-reference:/etc/passwd:long enough reason here",
            "retained-reference:personal/x:token %s inside" % SECRET_LOOKING,
            "retained-reference:personal/x",
        ]
        for spec in bad:
            with self.subTest(spec=spec[:40]):
                out = fx.run("verify", "--operation", op, "--exception", spec, "--json")
                self.assertEqual(out.rc, 2, out.text)
        self.assertNotIn("exception", fx.kinds(op))
        self.assertNotIn(SECRET_LOOKING, fx.journal(op).read_text())
        pending = fx.run(
            "verify", "--operation", op,
            "--exception", "external-pending:registrar-domain:the registrar completes the deletion after its redemption period",
            "--json",
        )
        self.assertEqual(pending.rc, 0, pending.text)
        self.assertEqual(pending.data["exceptions"][0]["class"], "external-pending")
        self.assertEqual(fx.events(op)[-1]["outcome"], "verified-with-exceptions")

    def test_verify_cannot_close_an_incomplete_operation(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-intent:" + sid)
        self.assertEqual(out.rc, 75)
        verify = fx.run("verify", "--operation", data["operation"], "--json")
        self.assertEqual(verify.rc, 1)
        self.assertEqual([c["id"] for c in verify.data["checks"] if c["status"] == "fail"][:1], ["steps"])
        self.assertNotIn("close", fx.kinds(data["operation"]))
        self.assertTrue(repo.exists())

    def test_verify_notices_a_removed_worktree_a_retained_repo_still_lists(self):
        fx = self.fx
        keep = fx.repo("personal/keep")
        victim = fx.repo("personal/alpha")
        fx.linked_worktree(keep, victim / "inner-wt", "inner-branch")
        _o, preview = fx.preview("personal/alpha")
        self.assertTrue(preview["required_waivers"], "a worktree directory inside the checkout is unshared work")
        done = fx.confirm(preview)
        self.assertEqual(done.rc, 0, done.text)
        op = preview["operation"]
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1)
        self.assertIn("worktrees-absent", [c["id"] for c in failed.data["checks"] if c["status"] == "fail"])
        fx.git(keep, "worktree", "prune")
        passed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(passed.rc, 0, passed.text)

    def test_health_is_compared_with_the_baseline_taken_before_the_first_change(self):
        fx = self.fx
        fx.repo("personal/alpha")
        fx.health("dev-doctor", "Summary: 12 repos — OK 9 · ADVISORY 1 · DRIFT 1 · VIOLATION 1\n", rc=1)
        fx.health("shadowsync", "stale authority records for removed repositories\n", rc=1)
        fx.adapter("local-jobs", LOCAL_JOBS_SHIM)
        (fx.tmp / "doctor-local-jobs.txt").write_text("all jobs healthy\n")
        (fx.tmp / "doctor-local-jobs.rc").write_text("0")
        op = self.executed("personal/alpha")
        base = [e for e in fx.events(op) if e["kind"] == "baseline"][0]["health"]
        self.assertEqual(base["dev-doctor"]["metrics"]["violation"], 1)
        self.assertEqual(base["local-jobs"]["status"], "ok")
        unchanged = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(unchanged.rc, 0, "a pre-existing, unchanged problem is not a regression: " + unchanged.text)
        # a regression: violations rise and a healthy subsystem breaks
        fx2 = Fx(self)
        self.fx = fx2
        fx2.repo("personal/alpha")
        fx2.health("dev-doctor", "Summary: 12 repos — OK 9 · ADVISORY 1 · DRIFT 1 · VIOLATION 1\n", rc=1)
        fx2.adapter("local-jobs", LOCAL_JOBS_SHIM)
        (fx2.tmp / "doctor-local-jobs.rc").write_text("0")
        op2 = self.executed("personal/alpha")
        fx2.health("dev-doctor", "Summary: 12 repos — OK 8 · ADVISORY 1 · DRIFT 1 · VIOLATION 2\n", rc=1)
        (fx2.tmp / "doctor-local-jobs.rc").write_text("1")
        (fx2.tmp / "doctor-local-jobs.txt").write_text("a job is broken\n")
        regressed = fx2.run("verify", "--operation", op2, "--json")
        self.assertEqual(regressed.rc, 1)
        health = [c for c in regressed.data["checks"] if c["id"] == "health"][0]
        self.assertEqual(health["status"], "fail")
        self.assertEqual(len(health["items"]), 2)
        excused = fx2.run(
            "verify", "--operation", op2,
            "--exception", "subsystem-stale:local-jobs:its own doctor needs a repair outside this removal",
            "--exception", "subsystem-stale:dev-doctor:violations are being fixed in a separate change",
            "--json",
        )
        self.assertEqual(excused.rc, 0, excused.text)
        self.assertEqual(excused.data["stage"], "closed")

    def test_a_tool_that_was_missing_at_the_baseline_and_reports_a_problem_later_is_not_a_pass(self):
        fx = self.fx
        fx.repo("personal/alpha")
        op = self.executed("personal/alpha")
        base = [e for e in fx.events(op) if e["kind"] == "baseline"][0]["health"]
        self.assertEqual(base["local-jobs"]["status"], "unavailable")
        fx.health("local-jobs", "a job is broken\n", rc=1)
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        health = [c for c in failed.data["checks"] if c["id"] == "health"][0]
        self.assertEqual(health["status"], "fail")
        self.assertTrue(any("no baseline" in item for item in health["items"]), health)
        excused = fx.run("verify", "--operation", op, "--exception", "subsystem-stale:local-jobs:it was not installed when this started and is being repaired separately", "--json")
        self.assertEqual(excused.rc, 0, excused.text)

    def test_incomplete_job_inventory_refuses_retirement_before_deletion(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([])
        report = fx.tmp / "jobs.json"
        for raw in (
            '{"instances": [], "overlay_errors": {"fixture": "duplicate type"}}',
            '{"instances": [{"role": "error", "type": "fixture"}]}',
            '{"instances": [{"id": "ok"}, null]}',
            '{"instances": {}}',
            'not JSON',
        ):
            with self.subTest(report=raw):
                report.write_text(raw)
                refused = fx.run("remove", "personal/alpha", "--json")
                self.assertEqual(refused.rc, 1, refused.text)
                self.assertIn("Local Jobs", refused.data["refused"])
                self.assertNotIn("confirm_token", refused.data)
                self.assertTrue(repo.is_dir())
        # The legacy array and the current owner envelope both represent an empty inventory.
        for raw in ("[]", '{"instances": [], "overlay_errors": {}}'):
            report.write_text(raw)
            viewed = fx.run("view", "personal/alpha", "--json")
            self.assertEqual(viewed.rc, 0, viewed.text)

    def test_a_reported_success_that_did_not_happen_is_a_failure_not_a_completion(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([fx.fetch_job(repo)])
        # an owning verb that claims success without doing anything
        shim = LOCAL_JOBS_SHIM.replace('python3 - "$d/jobs.json" "$id" "$revision" <<\'INNER\'', 'true <<\'INNER\'')
        fx.adapter("local-jobs", shim)
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 1, done.text)
        self.assertEqual(done.data["outcome"], "failed")
        events = fx.events(data["operation"])
        failure = [e for e in events if e["kind"] == "failure"][-1]
        self.assertIn("not observed", failure["reason"])
        self.assertFalse([e for e in events if e["kind"] == "complete" and e.get("subsystem") == "local-job-delete"])
        self.assertTrue(repo.exists())

    def test_a_result_that_cannot_be_checked_right_now_is_not_called_a_missing_result(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([fx.fetch_job(repo)])
        fx.adapter("local-jobs", LOCAL_JOBS_QUIET_SHIM)
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 1, done.text)
        self.assertEqual(done.data["outcome"], "failed")
        failure = [e for e in fx.events(data["operation"]) if e["kind"] == "failure"][-1]
        self.assertIn("could not be observed", failure["reason"])
        self.assertNotIn("was not observed", failure["reason"])
        self.assertTrue(repo.exists(), "nothing else happens while a step is unconfirmed")
        (fx.tmp / "local-jobs.quiet").unlink()
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertFalse(repo.exists())
        completes = [e for e in fx.events(data["operation"]) if e["kind"] == "complete" and e.get("subsystem") == "local-job-delete"]
        self.assertEqual(len(completes), 1)
        self.assertTrue(completes[0].get("reconciled"), "the earlier deletion was recognised, not repeated")

    def test_verify_notices_a_completed_step_that_no_longer_holds(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        skills = fx.home / ".cursor" / "skills"
        skills.mkdir(parents=True)
        os.symlink(str(repo / "sub"), str(skills / "alpha-skill"))
        op = self.executed("personal/alpha")
        os.symlink(str(fx.outside), str(skills / "alpha-skill"))
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        self.assertIn("effects", [c["id"] for c in failed.data["checks"] if c["status"] == "fail"])
        os.unlink(str(skills / "alpha-skill"))
        self.assertEqual(fx.run("verify", "--operation", op, "--json").rc, 0)

    def test_the_generated_index_is_refreshed_through_its_owning_verb(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.adapter("agent-route", "#!/usr/bin/env bash\nd=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\nprintf '%s\\n' \"$*\" >> \"$d/agent-route.calls\"\nexit 0\n")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([s["kind"] for s in data["steps"]][-1], "refresh-index")
        self.assertIn("discover --full", (fx.tmp / "agent-route.calls").read_text())
        self.assertFalse(repo.exists())

    def test_generated_memory_mentions_are_reported_and_must_be_excepted_at_verify(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / "agent-learnings.md").write_text("- the alpha tool at personal/alpha was retired\n")
        out = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(out.data["required_waivers"], [])
        self.assertTrue(any("generated-memory" in n for n in out.data["targets"][0]["notes"]))
        op = self.executed("personal/alpha")
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1)
        self.assertIn("generated-memory", " ".join([c for c in failed.data["checks"] if c["id"] == "mentions"][0]["items"]))
        passed = fx.run(
            "verify", "--operation", op,
            "--exception", "historical-record:personal/keep/agent-learnings.md:generated memory is rewritten by its own updater",
            "--json",
        )
        self.assertEqual(passed.rc, 0, passed.text)

    def test_two_previews_of_the_same_target_can_only_run_once(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, first = fx.preview("personal/alpha")
        _o, second = fx.preview("personal/alpha")
        self.assertNotEqual(first["operation"], second["operation"])
        self.assertEqual(fx.confirm(first).rc, 0)
        late = fx.confirm(second)
        self.assertEqual(late.rc, 1, late.text)
        self.assertFalse(repo.exists())

    def test_case_aliases_are_refused_on_case_insensitive_filesystems(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        if not (fx.dev / "personal" / "ALPHA").exists():
            self.skipTest("this filesystem is case-sensitive")
        out = fx.run("remove", "personal/ALPHA", "--json")
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(self.blockers(out), ["path-unsafe"])
        self.assertTrue(repo.exists())

    # ------------------------------------------------------------------ wiring: links, jobs, caches
    def test_client_links_and_cursor_caches_are_cleaned_but_transcripts_are_kept(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        for client in (".cursor", ".claude", ".codex"):
            skills = fx.home / client / "skills"
            skills.mkdir(parents=True)
            os.symlink(str(repo / "sub"), str(skills / "alpha-skill"))
        unrelated = fx.outside / "unrelated-skill"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text("unrelated\n")
        unrelated_digest = digest_tree(unrelated)
        os.symlink(str(unrelated), str(fx.home / ".cursor" / "skills" / "other-skill"))
        project = fx.home / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(repo)).strip("-")
        for name in ("agent-tools", "canvases", "mcps", "agent-transcripts", "custom-notes"):
            (project / name).mkdir(parents=True)
            (project / name / "f.txt").write_text(name)
        _o, data = fx.preview("personal/alpha")
        links = data["targets"][0]["wiring"]["client_links"]
        self.assertEqual(len(links), 3)
        self.assertEqual(data["targets"][0]["wiring"]["project_dirs"][0]["kept"], ["agent-transcripts"])
        self.assertEqual(fx.confirm(data).rc, 0)
        self.assertFalse(repo.exists())
        for client in (".cursor", ".claude", ".codex"):
            self.assertFalse((fx.home / client / "skills" / "alpha-skill").is_symlink())
        self.assertTrue((fx.home / ".cursor" / "skills" / "other-skill").is_symlink())
        self.assertTrue((project / "agent-transcripts" / "f.txt").exists(), "chat history is never deleted")
        self.assertTrue((project / "custom-notes" / "f.txt").exists(), "unrecognised entries are left alone")
        for name in ("agent-tools", "canvases", "mcps"):
            self.assertFalse((project / name).exists())
        self.assertEqual(digest_tree(unrelated), unrelated_digest)

    def test_a_cursor_project_folder_that_a_checkout_staying_in_place_also_maps_to_keeps_its_caches(self):
        fx = self.fx
        target = fx.repo("personal/foo-bar")
        lookalike = fx.repo("personal/foo_bar")
        encode = lambda path: re.sub(r"[^A-Za-z0-9]+", "-", str(path)).strip("-")
        project = fx.home / ".cursor" / "projects" / encode(target)
        self.assertEqual(project.name, encode(lookalike), "Cursor spells both paths the same way")
        for name in ("canvases", "terminals", "agent-transcripts"):
            (project / name).mkdir(parents=True)
            (project / name / "f.txt").write_text(name)
        _o, data = fx.preview("personal/foo-bar")
        row = data["targets"][0]
        self.assertEqual(row["wiring"]["project_dirs"][0]["shared_with"], ["personal/foo_bar"])
        self.assertEqual(row["wiring"]["project_dirs"][0]["caches"], [])
        self.assertEqual(fx.step_ids(data, "cache-remove"), [])
        self.assertTrue(any("also the one for personal/foo_bar" in note for note in row["notes"]), row["notes"])
        self.assertEqual(fx.confirm(data).rc, 0)
        self.assertFalse(target.exists())
        self.assertTrue(lookalike.exists())
        for name in ("canvases", "terminals", "agent-transcripts"):
            self.assertTrue((project / name / "f.txt").exists(), name)

    def test_a_lookalike_checkout_that_appears_after_the_preview_forces_a_new_preview(self):
        fx = self.fx
        target = fx.repo("personal/foo-bar")
        project = fx.home / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(target)).strip("-")
        (project / "canvases").mkdir(parents=True)
        (project / "canvases" / "f.txt").write_text("canvas")
        _o, data = fx.preview("personal/foo-bar")
        self.assertEqual(len(fx.step_ids(data, "cache-remove")), 1)
        fx.repo("personal/foo_bar")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(target.exists())
        self.assertTrue((project / "canvases" / "f.txt").exists())
        self.assertNotIn("intent", fx.kinds(data["operation"]))

    def test_two_checkouts_removed_together_that_share_a_cursor_project_folder_clean_it_once(self):
        fx = self.fx
        first, second = fx.repo("personal/foo-bar"), fx.repo("personal/foo_bar")
        project = fx.home / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(first)).strip("-")
        for name in ("canvases", "terminals"):
            (project / name).mkdir(parents=True)
            (project / name / "f.txt").write_text(name)
        _o, data = fx.preview("personal/foo-bar", "personal/foo_bar")
        self.assertEqual(len(fx.step_ids(data, "cache-remove")), 2, "one step per cache folder, not one per checkout")
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(first.exists() or second.exists())
        self.assertFalse((project / "canvases").exists() or (project / "terminals").exists())

    def test_a_client_link_retargeted_after_the_preview_is_refused(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        skills = fx.home / ".cursor" / "skills"
        skills.mkdir(parents=True)
        link = skills / "alpha-skill"
        os.symlink(str(repo / "sub"), str(link))
        _o, data = fx.preview("personal/alpha")
        link.unlink()
        os.symlink(str(repo / "sub" / "deeper"), str(link))
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(repo.exists())

    def test_links_from_retained_repos_into_a_target_block(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        os.symlink(str(repo / "sub"), str(keep / "points-into-alpha"))
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(self.blockers(out), ["retained-link"])

    def test_a_link_deep_inside_a_retained_repo_into_a_target_blocks_and_vendor_clones_are_not_walked(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        deep = keep / "a" / "b" / "c" / "d" / "e" / "f"
        deep.mkdir(parents=True)
        os.symlink(str(repo / "sub"), str(deep / "points-into-alpha"))
        reference = fx.repo("affirm/vendor/reference")
        os.symlink(str(repo / "sub"), str(reference / "points-into-alpha"))
        out = fx.run("remove", "personal/alpha", "--json")
        blockers = [b for b in out.data["targets"][0]["blockers"] if b["id"] == "retained-link"]
        self.assertEqual(len(blockers), 1, out.text)
        self.assertIn(str(deep.name), blockers[0]["message"])
        self.assertNotIn("reference", blockers[0]["message"], "the reference-only vendor clone is not walked")

    def test_a_client_config_that_is_a_symlink_is_still_searched_by_both_engines(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        kept = fx.home / "dotfiles"
        kept.mkdir()
        real = kept / "mcp.json"
        real.write_text(json.dumps({"mcpServers": {"alpha": {"command": str(repo / "bin" / "serve")}}}))
        (fx.home / ".cursor").mkdir()
        os.symlink(str(real), str(fx.home / ".cursor" / "mcp.json"))
        for engine in ["python"] + (["rg"] if shutil.which("rg") else []):
            out = fx.run("view", "personal/alpha", "--scan-engine", engine, "--json")
            self.assertEqual(self.blockers(out), ["client-config-reference"], engine)

    def test_a_startup_file_that_is_a_symlink_into_a_target_blocks(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        (repo / "zprofile").write_text("# nothing in here names the checkout\n")
        os.symlink(str(repo / "zprofile"), str(fx.home / ".zprofile"))
        out = fx.run("view", "personal/alpha", "--json")
        found = [b for b in out.data["targets"][0]["blockers"] if b["id"] == "retained-link"]
        self.assertEqual(len(found), 1, out.text)
        self.assertIn(".zprofile", found[0]["message"])

    def test_a_surface_folder_that_is_a_symlink_is_reported_as_not_searched(self):
        fx = self.fx
        fx.repo("personal/alpha")
        elsewhere = fx.home / "elsewhere"
        elsewhere.mkdir()
        link = fx.home / ".local-jobs"
        os.symlink(str(elsewhere), str(link))
        for engine in ["python"] + (["rg"] if shutil.which("rg") else []):
            out = fx.run("view", "personal/alpha", "--scan-engine", engine, "--json")
            self.assertEqual([r["id"] for r in out.data["targets"][0]["risks"]], ["scan-incomplete"], engine)
            self.assertEqual(out.data["scan"]["coverage"]["unreadable_paths"], [str(link)], engine)

    def test_scheduled_jobs_are_deleted_through_the_owning_verb(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([
            fx.fetch_job(repo),
            {"id": "unrelated", "role": "job", "command": "/usr/bin/true"},
        ])
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        calls = (fx.tmp / "local-jobs.calls").read_text()
        self.assertIn("delete-fetch-if-current --id alpha-nightly --if-revision %s --confirm" % fx.fetch_job(repo)["removal_revision"], calls)
        self.assertNotIn("unrelated --confirm", calls)
        remaining = json.loads((fx.tmp / "jobs.json").read_text())["instances"]
        self.assertEqual([j["id"] for j in remaining], ["unrelated"])

    def test_only_an_exclusive_owner_target_can_schedule_job_deletion(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        path = str(repo)
        jobs = [
            {"id": "descriptive", "role": "instance", "type": "command", "program": "/bin/echo",
             "description": "Monitor personal/alpha in the team report."},
            {"id": "several", "role": "instance", "type": "command", "program": path + "/report",
             "args": [path, "personal/beta"]},
            {"id": "indirect", "role": "instance", "type": "incremental-git-fetch",
             "path": path + "/../other", "description": "Formerly personal/alpha"},
            {"id": "legacy-shell", "role": "job", "command": path + "/tool && echo more"},
            {"id": "legacy-direct", "role": "job", "command": path + "/tool"},
            {"id": "no-token", "role": "instance", "type": "incremental-git-fetch", "path": path, "schedule": "inherit"},
            {**fx.fetch_job(repo, "custom"), "schedule": {"hour": 10, "minute": 30}},
            fx.fetch_job(repo, "fetch-alpha"),
        ]
        fx.jobs(jobs)
        refused = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(repo.is_dir())
        wiring = refused.data["targets"][0]["wiring"]
        self.assertEqual([j["id"] for j in wiring["jobs"]], ["fetch-alpha"])
        self.assertCountEqual([j["id"] for j in wiring["job_rows"]], [j["id"] for j in jobs[:-1]])
        self.assertNotIn("delete-fetch-if-current", (fx.tmp / "local-jobs.calls").read_text())
        fx.jobs(jobs[-1:])
        _, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        self.assertIn("delete-fetch-if-current --id fetch-alpha --if-revision %s --confirm" % jobs[-1]["removal_revision"], (fx.tmp / "local-jobs.calls").read_text())

    def test_same_id_reassigned_by_the_owner_immediately_before_delete_is_preserved(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        other = fx.repo("personal/beta")
        fx.jobs([fx.fetch_job(repo)])
        replacement = {"instances": [fx.fetch_job(other)]}
        (fx.tmp / "reassigned.json").write_text(json.dumps(replacement))
        shim = LOCAL_JOBS_SHIM.replace('    id="$3"', '    cp "$d/reassigned.json" "$d/jobs.json"\n    id="$3"')
        fx.adapter("local-jobs", shim)
        _, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 1, done.text)
        self.assertTrue(repo.exists() and other.exists())
        self.assertEqual(json.loads((fx.tmp / "jobs.json").read_text()), replacement)
        calls = (fx.tmp / "local-jobs.calls").read_text()
        self.assertIn("delete-fetch-if-current", calls)
        self.assertNotIn("delete-job", calls)

    def test_ambiguous_job_id_refuses_before_any_removal(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([{"role": "instance", "type": "incremental-git-fetch", "id": "nightly", "path": str(repo)},
                 {"role": "instance", "type": "command", "id": "nightly", "program": "/bin/echo"}])
        result = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(result.rc, 1, result.text)
        self.assertIn("ambiguous instance id", result.data["refused"])
        self.assertNotIn("delete-fetch-if-current", (fx.tmp / "local-jobs.calls").read_text())
        self.assertTrue(repo.is_dir())

    def test_a_shared_scheduler_row_blocks_until_it_is_removed_by_its_own_verbs(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([{"id": "global", "role": "global_scheduler", "targets": ["personal/alpha"]}])
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1)
        self.assertEqual(self.blockers(out), ["local-jobs-row"])
        self.assertTrue(repo.exists())

    def test_a_failing_job_deletion_stops_safely_and_resumes_once_fixed(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([fx.fetch_job(repo)])
        (fx.tmp / "local-jobs.fail").write_text("1")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 1, done.text)
        self.assertEqual(done.data["outcome"], "failed")
        self.assertTrue(repo.exists(), "the checkout is never removed before its wiring is gone")
        (fx.tmp / "local-jobs.fail").unlink()
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertFalse(repo.exists())

    def test_verify_says_so_when_a_completed_effect_cannot_be_re_checked(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([fx.fetch_job(repo)])
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        (fx.ad / "local-jobs").unlink()
        failed = fx.run("verify", "--operation", data["operation"], "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        effects = [c for c in failed.data["checks"] if c["id"] == "effects"][0]
        self.assertEqual(effects["status"], "fail")
        self.assertIn("could not re-check", effects["message"])
        fx.adapter("local-jobs", LOCAL_JOBS_SHIM)
        again = fx.run("verify", "--operation", data["operation"], "--json")
        self.assertEqual(again.rc, 0, again.text)

    # ------------------------------------------------------------------ operator gates
    def test_config_surfaces_and_the_fleet_are_operator_gates(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        (fx.home / ".cursor").mkdir()
        (fx.home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"alpha": {"command": str(repo / "bin" / "serve")}}}))
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(self.blockers(out), ["client-config-reference"])
        (fx.home / ".cursor" / "mcp.json").write_text("{}")
        (fx.home / ".zshrc").write_text("export PATH=\"%s/bin:$PATH\"\n" % repo)
        self.assertEqual(self.blockers(fx.run("remove", "personal/alpha", "--json")), ["launchd-shell-reference"])
        (fx.home / ".zshrc").write_text("# clean\n")
        fx.fleet(["KleinPerkins/alpha"])
        self.assertEqual(self.blockers(fx.run("remove", "personal/alpha", "--json")), ["pac-fleet-enrolled"])
        fx.fleet(["KleinPerkins/something-else"])
        self.assertEqual(self.blockers(fx.run("remove", "personal/alpha", "--json")), [])
        self.assertTrue(repo.exists())

    def test_an_unreadable_fleet_list_blocks_removal_of_fleet_eligible_remotes(self):
        fx = self.fx
        fx.repo("personal/alpha")
        fx.repo("personal/offline", origin=False)
        other = fx.repo("personal/other", origin=False)
        fx.git(other, "remote", "add", "origin", "https://github.com/Affirm/other.git")
        fleet = fx.dev / "_ops" / "baseline" / "profiles" / "pr-automation" / "v3" / "fleet.json"
        for breakage in (None, "{not json", "{}", "[]", '{"targets":null}',
                         '{"targets":"KleinPerkins/other"}', '{"targets":[{}]}',
                         '{"targets":[{"repo":"KleinPerkins/other"},{"repo":"missing-owner"}]}'):
            if breakage is None:
                fleet.unlink()
            else:
                fleet.write_text(breakage)
            self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), ["pac-fleet-unknown"], breakage)
            self.assertEqual(self.blockers(fx.run("view", "personal/offline", "--json")), [], "no remote, nothing to enrol")
            self.assertEqual(self.blockers(fx.run("view", "personal/other", "--json")), [], "not a fleet-eligible owner")
        fx.fleet([])
        self.assertEqual(self.blockers(fx.run("view", "personal/alpha", "--json")), [])

    def test_remote_only_mentions_are_reported_but_neither_block_nor_need_a_waiver(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / "notes.md").write_text("see https://github.com/KleinPerkins/alpha for the remote\n")
        fx.git(keep, "add", "-A")
        fx.git(keep, "commit", "-q", "-m", "notes")
        fx.push_state(keep)
        data = fx.run("view", "personal/alpha", "--json").data
        self.assertEqual(data["required_waivers"], [])
        target = data["targets"][0]
        self.assertEqual(target["blockers"], [])
        self.assertEqual(target["mentions"], {}, "only path references can dangle")
        self.assertEqual(target["remote_mentions"], 1)
        self.assertTrue(any("remote rather than a path" in note for note in target["notes"]), target["notes"])

    def test_name_only_mentions_are_counted_at_preview_so_verify_holds_no_surprises(self):
        fx = self.fx
        fx.repo("personal/old-thing")
        fx.repo("personal/tool")
        keep = fx.repo("personal/keep")
        (keep / "history.md").write_text("The old-thing project was retired last quarter, and the tool with it.\n")
        fx.git(keep, "add", "-A")
        fx.git(keep, "commit", "-q", "-m", "history")
        fx.push_state(keep)
        data = fx.run("view", "personal/old-thing", "personal/tool", "--json").data
        self.assertEqual(data["required_waivers"], [])
        old, generic = data["targets"]
        self.assertEqual(old["blockers"], [])
        self.assertEqual(old["mentions"], {}, "only path references can dangle")
        self.assertEqual(old["name_mentions"], 1)
        self.assertTrue(any("by its name only" in note for note in old["notes"]), old["notes"])
        self.assertEqual(generic["name_mentions"], 0, "a short one-word name is never searched alone")
        _o, preview = fx.preview("personal/old-thing")
        self.assertEqual(fx.confirm(preview).rc, 0)
        failed = fx.run("verify", "--operation", preview["operation"], "--json")
        self.assertEqual([c["id"] for c in failed.data["checks"] if c["status"] == "fail"], ["mentions"], "verify lists exactly what the preview counted")

    def test_pages_and_domains_require_an_explicit_attestation(self):
        fx = self.fx
        repo = fx.repo("personal/site", files={"README.md": "site\n", "CNAME": "www.example.invalid\n"})
        _o, data = fx.preview("personal/site")
        self.assertEqual(data["required_attests"], ["github-pages"])
        for attest in ([], ["github-pages", "dns"], ["dns"]):
            with self.subTest(attest=attest):
                out = fx.confirm(data, attest=attest)
                self.assertEqual(out.rc, 1, out.text)
                self.assertTrue(repo.exists())
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        confirm = [e for e in fx.events(data["operation"]) if e["kind"] == "confirm"][0]
        self.assertEqual(confirm["attested"], ["github-pages"])

    def test_consumers_in_retained_repos_are_a_waivable_risk_not_a_blocker(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / "config.yml").write_text("source: personal/alpha\n")
        fx.git(keep, "add", "-A")
        fx.git(keep, "commit", "-q", "-m", "config")
        fx.push_state(keep)
        out = fx.run("view", "personal/alpha", "--json")
        self.assertEqual(out.data["required_waivers"], ["consumer-mentions"])
        self.assertEqual(out.data["targets"][0]["mentions"], {"retained-repo": 1})

    # ------------------------------------------------------------------ journal integrity and state hygiene
    def test_tampering_with_the_journal_or_operation_is_detected(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        op = data["operation"]
        journal = fx.journal(op)
        original = journal.read_text()
        lines = original.splitlines()
        self.assertIn('"subsystem":"journal"', lines[0])
        journal.write_text("\n".join([lines[0].replace('"subsystem":"journal"', '"subsystem":"journaI"'), lines[1]]) + "\n")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(repo.exists())
        journal.write_text(original)
        opfile = fx.state / op / "operation.json"
        text = opfile.read_text()
        opfile.write_text(text.replace("personal/alpha", "personal/other"))
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertTrue(repo.exists())
        opfile.write_text(text)
        self.assertEqual(fx.confirm(data).rc, 0)

    def test_a_torn_journal_tail_is_recovered_and_recorded(self):
        fx = self.fx
        fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        op = data["operation"]
        with open(str(fx.journal(op)), "a") as fh:
            fh.write('{"kind": "intent", "partial')
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        events = fx.events(op, lenient=True)
        self.assertEqual(len(fx.journal(op).read_text().splitlines()) - len(events), 1, "the torn fragment is kept as one inert line")
        self.assertTrue(any(e.get("torn_recovered") for e in events))
        report = fx.run("doctor", "--journal", fx.journal(op), "--json")
        self.assertTrue(report.data["chain_ok"])

    def test_state_is_private_and_free_of_secrets(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.git(repo, "remote", "set-url", "origin", "https://user:%s@github.com/KleinPerkins/alpha.git" % SECRET_LOOKING)
        (repo / "creds.txt").write_text("token=%s\n" % SECRET_LOOKING)
        env = {"GITHUB_TOKEN": SECRET_LOOKING, "SNOWFLAKE_PASSWORD": SECRET_LOOKING}
        out, data = fx.preview("personal/alpha", env=env)
        self.assertEqual(out.rc, 0, out.text)
        done = fx.confirm(data, env=env)
        self.assertEqual(done.rc, 0, done.text)
        op = data["operation"]
        verified = fx.run("verify", "--operation", op, env=env)
        for root, _dirs, files in os.walk(str(fx.state)):
            for name in files:
                full = os.path.join(root, name)
                self.assertEqual(stat.S_IMODE(os.stat(full).st_mode), 0o600, full)
                self.assertNotIn(SECRET_LOOKING, open(full).read(), full)
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700, root)
        for output in (out, done, verified):
            self.assertNotIn(SECRET_LOOKING, output.text)
        remotes = data["targets"][0]["git"]["remotes"]
        self.assertEqual(remotes, [{"name": "origin", "url": "github.com/KleinPerkins/alpha"}])
        self.assertNotIn(data["confirm_token"], fx.journal(op).read_text(), "only a hash of the token is journaled")

    def test_one_writer_at_a_time(self):
        import fcntl

        fx = self.fx
        fx.repo("personal/alpha")
        fx.state.mkdir(parents=True, mode=0o700)
        fd = os.open(str(fx.state / ".writer.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1, out.text)
        self.assertIn("another dev-remove-repo run is writing", out.data["refused"])
        doctor = fx.run("doctor", "--json")
        self.assertIn("writer-lock", [c["id"] for c in doctor.data["checks"] if c["status"] == "warn"])
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(fx.run("remove", "personal/alpha", "--json").rc, 0)

    def test_an_unsafe_state_folder_is_refused(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        redirected = fx.outside / "redirected-state"
        redirected.mkdir()
        fx.state.parent.mkdir(parents=True)
        os.symlink(str(redirected), str(fx.state))
        out = fx.run("remove", "personal/alpha", "--json")
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(list(redirected.iterdir()), [])
        self.assertTrue(repo.exists())

    # ------------------------------------------------------------------ engine behaviour
    def test_both_scan_engines_find_the_same_mentions(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / "a.md").write_text("alpha lives at personal/alpha\n")
        (keep / "b.md").write_text("unrelated\n")
        (keep / "c.md").write_text("remote: https://github.com/KleinPerkins/Alpha.git\n")
        (fx.home / ".zshrc").write_text("# personal/alpha\n")
        results = {}
        for engine in ("rg", "python"):
            out = fx.run("view", "personal/alpha", "--scan-engine", engine, "--json")
            self.assertEqual(out.rc, 0, out.text)
            target = out.data["targets"][0]
            results[engine] = (target["mentions"], target["blockers"], target["remote_mentions"])
        self.assertEqual(results["rg"], results["python"])
        self.assertEqual(results["rg"][0].get("retained-repo"), 1)
        self.assertEqual(results["rg"][2], 1, "a remote written in mixed case is still found by both engines")
        self.assertEqual([b["id"] for b in results["rg"][1]], ["launchd-shell-reference"])

    def test_both_scan_engines_search_git_ignored_files_and_skip_the_same_folders(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / ".gitignore").write_text("local.env\nbuild/\nnode_modules/\n.venv/\n")
        fx.git(keep, "add", "-A")
        fx.git(keep, "commit", "-q", "-m", "ignore local files")
        said = "alpha lives at personal/alpha\n"
        counted = [keep / "local.env", keep / "build" / "out.txt", keep / ".hidden-notes" / "n.txt"]
        skipped = [
            keep / "node_modules" / "pkg" / "index.js",
            keep / "pkg" / "node_modules" / "deep.js",
            keep / ".venv" / "pyvenv.cfg",
            keep / "__pycache__" / "m.txt",
        ]
        for path in counted + skipped:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(said)
        pointer = fx.dev / "personal" / "pointer"
        pointer.mkdir()
        (pointer / ".git").write_text("gitdir: %s\n" % (fx.dev / "personal" / "alpha" / ".git" / "worktrees" / "pointer"))
        results = {}
        for engine in ("rg", "python"):
            if engine == "rg" and not shutil.which("rg"):
                continue
            out = fx.run("view", "personal/alpha", "--scan-engine", engine, "--json")
            self.assertEqual(out.rc, 0, out.text)
            self.assertTrue(out.data["scan"]["coverage"]["complete"], out.text)
            target = out.data["targets"][0]
            results[engine] = target["mentions"]
            self.assertEqual(
                target["mentions"].get("retained-repo"),
                len(counted) + 1,
                "%s: git-ignored files, hidden folders and a worktree's .git pointer file are searched; dependency and cache folders are not" % engine,
            )
            self.assertIn("consumer-mentions", [r["id"] for r in target["risks"]], engine)
        if len(results) == 2:
            self.assertEqual(results["rg"], results["python"])

    def test_it_runs_without_ripgrep_and_on_the_system_python(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        (keep / "a.md").write_text("alpha lives at personal/alpha\n")
        system = "/usr/bin/python3"
        if not os.path.exists(system):
            self.skipTest("no system python")
        if shutil.which("rg", path="/usr/bin:/bin"):
            self.skipTest("ripgrep is installed in a system directory, so a short PATH cannot hide it")
        bare = fx.run("view", "personal/alpha", "--json", env={"PATH": "/usr/bin:/bin", "DEV_REMOVE_REPO_PYTHON": system})
        self.assertEqual(bare.rc, 0, bare.text)
        self.assertEqual(bare.data["scan"]["engine"], "python")
        self.assertEqual(bare.data["targets"][0]["mentions"], {"retained-repo": 1})
        data, done = fx.run_all("personal/alpha", env={"PATH": "/usr/bin:/bin", "DEV_REMOVE_REPO_PYTHON": system}, waive=["consumer-mentions"])
        self.assertEqual(done.rc, 0, done.text)

    def test_the_tool_never_touches_the_network_or_the_real_home(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        real_git = shutil.which("git")
        (fx.tmp / "real-git").write_text(real_git)
        fx.adapter("git", GIT_SHIM)
        before_home = sorted(os.listdir(str(fx.sentinel)))
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual(fx.run("verify", "--operation", data["operation"]).rc, 0)
        calls = (fx.tmp / "git.calls").read_text().splitlines()
        self.assertTrue(calls, "the shim saw the tool's git use")
        network = re.compile(r"(^|\s)(fetch|pull|push|clone|ls-remote|remote update|remote show|submodule update)(\s|$)")
        self.assertEqual([c for c in calls if network.search(c)], [])
        self.assertTrue(all("core.hooksPath=/dev/null" in c for c in calls if " status" in c or "status " in c), "hooks are never run")
        self.assertEqual(sorted(os.listdir(str(fx.sentinel))), before_home, "the real home directory is never used")

    def test_fixture_mode_only_runs_under_the_system_temp_dir(self):
        fx = self.fx
        for bad in (str(ROOT), "/etc", "/", str(Path(tempfile.gettempdir()).resolve()), str(fx.tmp / "missing")):
            with self.subTest(root=bad):
                out = fx.run("doctor", env={"DEV_REMOVE_REPO_FIXTURE_ROOT": bad})
                self.assertEqual(out.rc, 2, out.text)

    def test_usage_errors_exit_two(self):
        fx = self.fx
        cases = [
            (),
            ("bogus",),
            ("remove",),
            ("remove", "--confirm", "x"),
            ("remove", "personal/a", "--confirm", "x"),
            ("resume",),
            ("verify",),
            ("view", "--bogus"),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(fx.run(*args).rc, 2)
        for bad_id in ("../../etc", "ret-..", "x", "ret-20261023-2210/../../x"):
            with self.subTest(op=bad_id):
                out = fx.run("view", "--operation", bad_id, "--json")
                self.assertIn(out.rc, (1, 2), out.text)
        self.assertEqual(fx.run("view", "--operation", "ret-20990101-0000", "--json").rc, 1)

    def test_doctor_reports_a_healthy_tool(self):
        fx = self.fx
        out = fx.run("doctor", "--json")
        self.assertEqual(out.rc, 0, out.text)
        checks = {c["id"]: c["status"] for c in out.data["checks"]}
        self.assertEqual(checks["python"], "ok")
        self.assertEqual(checks["git"], "ok")
        self.assertEqual(checks["affirm-policy"], "info")
        fx.policy(True)
        self.assertEqual({c["id"]: c["status"] for c in fx.run("doctor", "--json").data["checks"]}["affirm-policy"], "ok")

    # ------------------------------------------------------------------ records from before the tool, and quiet runs
    def old_record(self, op_id="ret-20260101-0000", closed=True, honest_digest=True):
        """A journal in the older hand-run format (no integrity chain, no operation.json), like the Milestone 1 one."""
        folder = self.fx.state / op_id
        folder.mkdir(parents=True)
        os.chmod(str(self.fx.state), 0o700)
        os.chmod(str(folder), 0o700)
        rows = [
            {"seq": n, "ts": "2026-01-01T00:00:0%dZ" % n, "kind": kind, "operation_id": op_id, "plan_step": "step-%d" % n, "subsystem": "fixture", "target": "none"}
            for n, kind in enumerate(["open", "baseline", "complete"], 1)
        ]
        lines = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        if closed:
            digest = hashlib.sha256(lines.encode()).hexdigest() if honest_digest else "0" * 64
            close = {"seq": 4, "ts": "2026-01-01T00:00:09Z", "kind": "close", "operation_id": op_id, "plan_step": "end", "subsystem": "fixture", "target": "none", "events": 3, "events_sha256": digest}
            lines += json.dumps(close, sort_keys=True) + "\n"
        (folder / "events.jsonl").write_text(lines)
        (folder / "notes.txt").write_text("hand-kept note\n")
        return folder

    def test_doctor_treats_a_record_from_before_the_tool_as_history_not_a_failure(self):
        fx = self.fx
        self.old_record()
        before = fx.state_snapshot()
        out = fx.run("doctor", "--json")
        self.assertEqual(out.rc, 0, out.text)
        row = {c["id"]: c for c in out.data["checks"]}["operation:ret-20260101-0000"]
        self.assertEqual(row["status"], "ok")
        self.assertIn("before this tool", row["message"])
        listing = fx.run("view", "--json")
        self.assertEqual(listing.rc, 0, listing.text)
        entry = listing.data["operations"][0]
        self.assertEqual((entry["operation"], entry["status"], entry["events"], entry["closed"]), ("ret-20260101-0000", "legacy-record", 4, True))
        shown = fx.run("view")
        self.assertIn("legacy-record", shown.out)
        self.assertNotIn("unreadable", shown.out)
        replay = fx.run("doctor", "--journal", fx.journal("ret-20260101-0000"), "--json")
        self.assertEqual(replay.rc, 0, replay.text)
        self.assertEqual(replay.data["format"], "legacy")
        self.assertEqual(fx.state_snapshot(), before, "reading a record never changes it")

    def test_a_record_from_before_the_tool_that_is_open_or_does_not_replay_is_a_warning_not_a_failure(self):
        fx = self.fx
        self.old_record("ret-20260101-0001", closed=False)
        self.old_record("ret-20260101-0002", honest_digest=False)
        out = fx.run("doctor", "--json")
        self.assertEqual(out.rc, 0, out.text)
        rows = {c["id"]: c for c in out.data["checks"]}
        self.assertEqual(rows["operation:ret-20260101-0001"]["status"], "warn")
        self.assertIn("never closed", rows["operation:ret-20260101-0001"]["message"])
        self.assertEqual(rows["operation:ret-20260101-0002"]["status"], "warn")
        self.assertIn("no longer replays cleanly", rows["operation:ret-20260101-0002"]["message"])

    def test_acting_on_a_record_from_before_the_tool_is_refused_in_plain_words_and_changes_nothing(self):
        fx = self.fx
        op = "ret-20260101-0000"
        self.old_record(op)
        before = fx.state_snapshot()
        attempts = (
            ["view", "--operation", op],
            ["verify", "--operation", op],
            ["verify", "--operation", op, "--discard-preview"],
            ["resume", "--operation", op],
            ["remove", "--operation", op, "--confirm", "confirm-anything"],
        )
        for args in attempts:
            with self.subTest(verb=args[0], extra=args[3:4]):
                out = fx.run(*(args + ["--json"]))
                self.assertEqual(out.rc, 1, out.text)
                self.assertIn("before this tool existed", out.text)
                self.assertIn("doctor --journal", out.text)
                self.assertNotIn("was found in", out.text)
        self.assertEqual(fx.state_snapshot(), before)

    def test_a_native_operation_that_lost_its_record_is_still_a_failure_not_a_record_from_before_the_tool(self):
        fx = self.fx
        fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        op = data["operation"]
        (fx.state / op / "operation.json").unlink()
        out = fx.run("doctor", "--json")
        self.assertEqual(out.rc, 1, out.text)
        row = {c["id"]: c for c in out.data["checks"]}["operation:" + op]
        self.assertEqual(row["status"], "fail")
        self.assertNotIn("before this tool", row["message"])
        listing = fx.run("view", "--json")
        self.assertEqual(listing.data["operations"][0]["status"], "unreadable")
        self.assertNotIn("before this tool existed", fx.run("view", "--operation", op).text)

    def test_a_record_from_before_the_tool_never_gets_in_the_way_of_new_work_and_is_never_touched(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        folder = self.old_record()
        before = digest_tree(folder)
        out, data = fx.preview("personal/alpha")
        self.assertEqual(out.rc, 0, out.text)
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(repo.exists())
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)
        self.assertEqual(digest_tree(folder), before)
        self.assertEqual(fx.run("doctor", "--json").rc, 0)

    def test_the_usual_verbs_print_nothing_on_the_error_stream(self):
        """Python 3.13 and later warn when a function is given a count by position; the engine runs in isolated mode,
        so the only honest check is that a normal run, on whichever interpreter is installed, stays silent."""
        fx = self.fx
        fx.repo("personal/alpha")
        for args in (["view", "personal/alpha", "--json"], ["doctor", "--json"], ["view", "--json"], ["remove", "personal/alpha", "--json"]):
            with self.subTest(verb=args[0]):
                out = fx.run(*args)
                self.assertEqual(out.rc, 0, out.text)
                self.assertEqual(out.err.strip(), "", out.err)

    # ------------------------------------------------------------------ independent-review hardening
    def load_engine(self):
        """The embedded engine, loaded without running it, for unit tests of its safety primitives."""
        text = SCRIPT.read_text()
        body = text.split("<<'PY_ENGINE'\n", 1)[1].rsplit("\nPY_ENGINE", 1)[0]
        namespace = {"__name__": "drr_engine_under_test"}
        exec(compile(body, "dev-remove-repo.sh(engine)", "exec"), namespace)
        return namespace

    def test_worktree_registry_preserves_relative_and_absolute_records(self):
        ns = self.load_engine()
        checkout = self.fx.repo("personal/alpha")
        admin = checkout / ".git" / "worktrees"
        for name, pointer in [("abs", str(self.fx.outside / "example" / ".git")), ("rel", "../../../../peer/.git")]:
            (admin / name).mkdir(parents=True)
            (admin / name / "gitdir").write_text(pointer + "\n")
        fd = os.open(checkout, os.O_RDONLY)
        try:
            records = ns["registration_records"](fd)
            paths = ns["registration_paths"](records, str(admin))
            self.assertEqual(set(paths), {str(self.fx.outside / "example"), str(checkout.parent / "peer")})
        finally:
            os.close(fd)

    def test_incomplete_registration_refuses_preview_and_preserves_checkouts(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        peer = fx.repo("personal/peer")
        entry = repo / ".git" / "worktrees" / "unfinished"
        entry.mkdir(parents=True)
        record = entry / "gitdir"
        for case in ("missing", "empty", "not-gitdir", "link"):
            with self.subTest(case=case):
                if case == "empty":
                    record.write_bytes(b"")
                elif case == "not-gitdir":
                    record.write_text("unresolved\n")
                elif case == "link":
                    record.symlink_to(peer / "README.md")
                result, preview = fx.preview("personal/alpha")
                self.assertEqual(result.rc, 1, result.text)
                self.assertNotIn("operation", preview)
                self.assertTrue(repo.exists() and peer.exists())
                if os.path.lexists(record):
                    record.unlink()

    def test_incomplete_registration_in_marker_refuses_then_resumes_after_repair(self):
        fx = self.fx
        repo, data, _sid, out = self.interrupted_run("after-rename")
        self.assertEqual(out.rc, 75, out.text)
        marker, = repo.parent.glob(".drr-*.removing")
        missing = marker / ".git/worktrees/unfinished"
        missing.mkdir(parents=True)
        before = digest_tree(marker)
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertEqual(digest_tree(marker), before)
        self.assertNotIn("purge-start", fx.kinds(data["operation"]))
        missing.rmdir()
        self.assertEqual(fx.run("resume", "--operation", data["operation"], "--json").rc, 0)
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)

    def test_moved_registered_worktree_requires_reconciliation_before_preview(self):
        fx = self.fx
        primary = fx.repo("personal/alpha")
        alias = fx.linked_worktree(primary, fx.home / ".cursor/worktrees/alpha/example")
        moved = fx.outside / "moved-example"
        alias.rename(moved)
        result, preview = fx.preview("personal/alpha")
        self.assertEqual(result.rc, 1, result.text)
        self.assertIn("worktree-unavailable", self.blockers(result))
        self.assertNotIn("operation", preview)
        self.assertTrue(moved.is_dir() and primary.is_dir())

    def test_partial_purge_uses_only_its_recorded_internal_registration(self):
        fx = self.fx
        primary = fx.repo("personal/alpha")
        fx.linked_worktree(primary, primary / "internal")
        result, preview = fx.preview("personal/alpha")
        self.assertEqual(result.rc, 0, result.text)
        sid, = fx.step_ids(preview, "delete-checkout")
        interrupted = fx.confirm(preview, interrupt="after-registration-check:" + sid)
        self.assertEqual(interrupted.rc, 75, interrupted.text)
        marker, = primary.parent.glob(".drr-*.removing")
        table = marker / ".git/worktrees"
        known, = table.iterdir()
        (known / "gitdir").unlink()  # a directory left partway through authorized cleanup
        unknown = table / "different"
        unknown.mkdir()
        before = digest_tree(marker)
        refused = fx.run("resume", "--operation", preview["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertEqual(digest_tree(marker), before)
        unknown.rmdir()
        resumed = fx.run("resume", "--operation", preview["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertEqual(fx.kinds(preview["operation"]).count("purge-start"), 1)
        self.assertEqual(fx.run("verify", "--operation", preview["operation"], "--json").rc, 0)

    def test_incomplete_retained_repository_registration_keeps_verification_open(self):
        fx = self.fx
        fx.repo("personal/alpha")
        peer = fx.repo("personal/peer")
        data, result = fx.run_all("personal/alpha")
        self.assertEqual(result.rc, 0, result.text)
        missing = peer / ".git/worktrees/unfinished"
        missing.mkdir(parents=True)
        checked = fx.run("verify", "--operation", data["operation"], "--json")
        self.assertEqual(checked.rc, 1, checked.text)
        self.assertIn("worktrees-absent", [c["id"] for c in checked.data["checks"] if c["status"] == "fail"])
        self.assertNotIn("close", fx.kinds(data["operation"]))
        missing.rmdir()
        self.assertEqual(fx.run("verify", "--operation", data["operation"], "--json").rc, 0)

    def test_the_search_size_limit_is_reported_and_skipped_files_are_counted_only_where_measured(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        with open(str(keep / "big.dat"), "wb") as fh:
            fh.truncate(8 * 1024 * 1024 + 1)
        built_in = fx.run("view", "personal/alpha", "--scan-engine", "python", "--json")
        self.assertEqual(built_in.rc, 0, built_in.text)
        cov = built_in.data["scan"]["coverage"]
        self.assertEqual(cov["size_limit_bytes"], 8 * 1024 * 1024)
        self.assertEqual(cov["oversized_skipped"], 1)
        self.assertTrue(cov["complete"], "a file over the limit is a documented limit, not an unreadable file")
        if shutil.which("rg"):
            fast = fx.run("view", "personal/alpha", "--scan-engine", "rg", "--json")
            self.assertEqual(fast.rc, 0, fast.text)
            cov = fast.data["scan"]["coverage"]
            self.assertEqual(cov["size_limit_bytes"], 8 * 1024 * 1024)
            self.assertIsNone(cov["oversized_skipped"], "ripgrep skips big files without counting them, so no count is claimed")

    def test_a_same_size_same_mtime_rewrite_is_still_a_change(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        (repo / ".gitignore").write_text("*.log\n")
        fx.git(repo, "add", "-A")
        fx.git(repo, "commit", "-q", "-m", "ignore logs")
        fx.push_state(repo)
        log = repo / "build.log"
        log.write_text("run-1\n")
        before = os.stat(str(log))
        _o, data = fx.preview("personal/alpha")
        self.assertEqual(data["required_waivers"], ["ignored-data"])
        log.write_text("run-2\n")
        os.utime(str(log), ns=(before.st_atime_ns, before.st_mtime_ns))
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertIn("changed", out.data["refused"])
        self.assertTrue(repo.exists())
        self.assertNotIn("intent", fx.kinds(data["operation"]))

    def test_a_change_to_the_repositorys_own_settings_or_hooks_is_a_change(self):
        for variant in ("hook-added", "config-edited", "exclude-edited"):
            with self.subTest(variant=variant):
                fx = Fx(self)
                self.fx = fx
                repo = fx.repo("personal/alpha")
                _o, data = fx.preview("personal/alpha")
                git_dir = repo / ".git"
                if variant == "hook-added":
                    (git_dir / "hooks").mkdir(exist_ok=True)
                    (git_dir / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
                elif variant == "config-edited":
                    with open(str(git_dir / "config"), "a") as fh:
                        fh.write("[core]\n\tabbrev = 12\n")
                else:
                    (git_dir / "info").mkdir(exist_ok=True)
                    with open(str(git_dir / "info" / "exclude"), "a") as fh:
                        fh.write("local-only-notes/\n")
                out = fx.confirm(data)
                self.assertEqual(out.rc, 1, out.text)
                self.assertIn("changed", out.data["refused"])
                self.assertTrue(repo.exists())
                self.assertNotIn("intent", fx.kinds(data["operation"]))
                _o2, again = fx.preview("personal/alpha")
                self.assertEqual(fx.confirm(again).rc, 0)
                self.assertFalse(repo.exists())

    def test_a_symlinked_cursor_projects_folder_is_never_followed(self):
        for variant in ("projects-link", "cursor-link"):
            with self.subTest(variant=variant):
                fx = Fx(self)
                self.fx = fx
                repo = fx.repo("personal/alpha")
                encoded = re.sub(r"[^A-Za-z0-9]+", "-", str(repo)).strip("-")
                if variant == "projects-link":
                    elsewhere = fx.outside / "projects"
                    (fx.home / ".cursor").mkdir()
                    os.symlink(str(elsewhere), str(fx.home / ".cursor" / "projects"))
                else:
                    elsewhere = fx.outside / "dotcursor"
                    os.symlink(str(elsewhere), str(fx.home / ".cursor"))
                    (elsewhere / "projects").mkdir(parents=True)
                held = (elsewhere / encoded if variant == "projects-link" else elsewhere / "projects" / encoded) / "canvases"
                held.mkdir(parents=True)
                (held / "keep.txt").write_text("not this tool's to delete")
                before = digest_tree(fx.outside)
                _o, data = fx.preview("personal/alpha")
                self.assertEqual(data["targets"][0]["wiring"]["project_dirs"], [])
                self.assertEqual([s["kind"] for s in data["steps"]], ["delete-checkout"])
                done = fx.confirm(data)
                self.assertEqual(done.rc, 0, done.text)
                self.assertFalse(repo.exists())
                self.assertEqual(digest_tree(fx.outside), before)

    def test_a_linked_worktree_that_appears_after_the_preview_is_not_part_of_the_plan(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        late = fx.home / ".cursor" / "worktrees" / "alpha" / "late"
        fx.git(repo, "worktree", "add", "-q", "--detach", str(late))
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertIn("linked worktree appeared", out.data["refused"])
        self.assertTrue(repo.exists() and late.exists())
        self.assertNotIn("intent", fx.kinds(data["operation"]))
        _o2, fresh = fx.preview("personal/alpha")
        self.assertIn("worktree-remove", [s["kind"] for s in fresh["steps"]], "a new preview plans it")
        self.assertEqual(fx.confirm(fresh).rc, 0)
        self.assertFalse(repo.exists() or late.exists())

    def test_a_linked_worktree_that_appears_between_cohorts_pauses_the_rest(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        _o, data = fx.preview("personal/first", "personal/second", extra=["--cohort-size", "1"])
        first_step = fx.step_ids(data, "delete-checkout")[0]
        self.assertEqual(fx.confirm(data, interrupt="after-complete:" + first_step).rc, 75)
        late = fx.home / ".cursor" / "worktrees" / "second" / "late"
        fx.git(second, "worktree", "add", "-q", "--detach", str(late))
        paused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(paused.rc, 1, paused.text)
        self.assertEqual(paused.data["outcome"], "paused")
        self.assertTrue(second.exists() and late.exists())
        fx.git(second, "worktree", "remove", "--force", str(late))
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(second.exists())

    def test_a_linked_worktree_added_just_before_the_set_aside_stops_the_deletion(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.adapter("lsof", LSOF_ADDS_WORKTREE_AFTER_RENAME_SHIM)
        _o, data = fx.preview("personal/alpha")
        late = fx.home / ".cursor" / "worktrees" / "alpha" / "late"
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(out.data["outcome"], "failed")
        failure = [e for e in fx.events(data["operation"]) if e["kind"] == "failure"][-1]
        self.assertIn("linked worktree was added", failure["reason"])
        self.assertFalse(repo.exists(), "it was set aside under its marker name")
        markers = list((fx.dev / "personal").iterdir())
        self.assertEqual(len(markers), 1)
        self.assertTrue((markers[0] / "sub" / "deeper" / "b.txt").exists(), "nothing inside was deleted")
        self.assertTrue((late / ".git").exists(), "the new worktree was left alone")
        again = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(again.rc, 1, again.text)
        self.assertTrue(markers[0].exists() and late.exists())
        fx.git(markers[0], "worktree", "remove", "--force", str(late))
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [])

    def test_a_linked_worktree_added_while_a_removal_is_interrupted_stops_the_resume(self):
        fx = self.fx
        fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        late = fx.home / ".cursor" / "worktrees" / "alpha" / "late"
        fx.git(marker, "worktree", "add", "-q", "--detach", str(late))
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertTrue(marker.exists() and late.exists())
        self.assertTrue((marker / "sub" / "deeper" / "b.txt").exists(), "nothing inside was deleted")
        fx.git(marker, "worktree", "remove", "--force", str(late))
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(marker.exists())

    def test_something_new_at_the_original_path_stops_the_resume_before_any_more_is_deleted(self):
        fx = self.fx
        fx.repo("personal/alpha")
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        marker = [p for p in (fx.dev / "personal").iterdir()][0]
        before = digest_tree(marker)
        newer = fx.dev / "personal" / "alpha"
        newer.mkdir()
        (newer / "fresh.txt").write_text("a new clone that has nothing to do with the old one\n")
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertNotEqual(refused.data["outcome"], "executed", refused.text)
        self.assertEqual(digest_tree(marker), before, "nothing inside the old checkout was deleted")
        self.assertEqual([p.name for p in newer.iterdir()], ["fresh.txt"], "the new item was left exactly as it was")
        last = [e for e in fx.events(data["operation"]) if e["kind"] in ("refusal", "failure")][-1]
        self.assertEqual(last["kind"], "refusal")
        self.assertIn("something new now exists at personal/alpha", last["reason"])
        again = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(again.rc, 1, "still refused while the new item is there")
        self.assertEqual(digest_tree(marker), before)
        shutil.rmtree(str(newer))
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual(done.data["outcome"], "executed")
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [])

    def test_a_new_reference_to_a_checkout_that_is_set_aside_stops_the_resume_before_more_is_deleted(self):
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        _o, data = fx.preview("personal/alpha")
        sid = fx.step_ids(data, "delete-checkout")[0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        marker = [p for p in (fx.dev / "personal").iterdir() if p.name.startswith(".drr-")][0]
        before = digest_tree(marker)
        link = keep / "wants-alpha-back"
        os.symlink(str(fx.dev / "personal" / "alpha" / "sub"), str(link))
        refused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertEqual(digest_tree(marker), before, "nothing inside the set-aside checkout was deleted")
        last = [e for e in fx.events(data["operation"]) if e["kind"] in ("refusal", "failure")][-1]
        self.assertEqual(last["kind"], "refusal")
        self.assertIn("points into personal/alpha", last["reason"])
        self.assertIn("nothing more was deleted", last["reason"])
        link.unlink()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], ["keep"])

    def test_links_and_mentions_inside_a_set_aside_checkout_never_block_the_checkouts_still_to_remove(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        os.symlink(str(second / "sub"), str(first / "points-into-second"))
        (first / "NOTES.md").write_text("The sibling lives at personal/second and is retired with this one.\n")
        _o, data = fx.preview("personal/first", "personal/second")
        sid = [s["id"] for s in data["steps"] if s["kind"] == "delete-checkout" and s["target"] == "personal/first"][0]
        out = fx.confirm(data, interrupt="after-rename:%s" % sid)
        self.assertEqual(out.rc, 75, out.text)
        self.assertTrue(second.exists())
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual(list((fx.dev / "personal").iterdir()), [], "the old checkout's own links and notes are part of what was approved")

    def test_a_program_that_starts_using_the_checkout_after_it_is_set_aside_stops_the_deletion(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.adapter("lsof", LSOF_AFTER_RENAME_SHIM)
        _o, data = fx.preview("personal/alpha")
        before = digest_tree(repo)
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(out.data["outcome"], "failed")
        self.assertFalse(repo.exists(), "it was set aside under its marker name")
        markers = list((fx.dev / "personal").iterdir())
        self.assertEqual(len(markers), 1)
        self.assertEqual(digest_tree(markers[0]), before, "nothing inside was deleted")
        failure = [e for e in fx.events(data["operation"]) if e["kind"] == "failure"][-1]
        self.assertIn("after it was set aside", failure["reason"])
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [])

    def test_a_program_reported_under_the_original_path_after_the_set_aside_is_found_too(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.adapter("lsof", LSOF_ORIGINAL_SPELLING_SHIM)
        _o, data = fx.preview("personal/alpha")
        before = digest_tree(repo)
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertEqual(out.data["outcome"], "failed")
        markers = list((fx.dev / "personal").iterdir())
        self.assertEqual(len(markers), 1)
        self.assertEqual(digest_tree(markers[0]), before, "nothing inside was deleted")
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertEqual([p.name for p in (fx.dev / "personal").iterdir()], [])

    def test_a_config_that_starts_pointing_at_a_checkout_during_the_run_stops_that_deletion(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        fx.adapter("lsof", LSOF_ADDS_REFERENCE_SHIM)
        _o, data = fx.preview("personal/first", "personal/second")
        self.assertEqual(len(fx.step_ids(data, "delete-checkout")), 2)
        self.assertEqual(len({s["cohort"] for s in data["steps"] if s["kind"] == "delete-checkout"}), 1, "both are in one group, so no group-boundary search runs between them")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists(), "the checkout that just gained a reference is left alone")
        refusal = [e for e in fx.events(data["operation"]) if e["kind"] == "refusal"][-1]
        self.assertIn("AI-client config", refusal["reason"])
        (fx.home / ".cursor" / "mcp.json").write_text("{}")
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(second.exists())

    def test_a_link_that_starts_pointing_at_a_checkout_during_the_run_stops_that_deletion(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        keep = fx.repo("personal/keep")
        fx.adapter("lsof", LSOF_ADDS_LINK_SHIM)
        _o, data = fx.preview("personal/first", "personal/second")
        self.assertEqual(len({s["cohort"] for s in data["steps"] if s["kind"] == "delete-checkout"}), 1, "one group, so no group-boundary search runs between them")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists(), "the checkout that just gained a link is left alone")
        refusal = [e for e in fx.events(data["operation"]) if e["kind"] == "refusal"][-1]
        self.assertIn("symbolic link", refusal["reason"])
        self.assertIn("late-link", refusal["reason"])
        os.unlink(str(keep / "late-link"))
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(second.exists())

    def test_a_link_between_two_checkouts_of_the_same_operation_does_not_stop_the_run(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        os.symlink(str(second / "sub"), str(first / "points-into-second"))
        _o, data = fx.preview("personal/first", "personal/second")
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(first.exists() or second.exists())

    def test_a_scheduler_entry_that_starts_naming_a_checkout_during_the_run_stops_that_deletion(self):
        fx = self.fx
        first, second = fx.repo("personal/first"), fx.repo("personal/second")
        fx.jobs([])
        fx.adapter("lsof", LSOF_ADDS_JOB_SHIM)
        _o, data = fx.preview("personal/first", "personal/second")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists(), "the checkout that a job now names is left alone")
        refusal = [e for e in fx.events(data["operation"]) if e["kind"] == "refusal"][-1]
        self.assertIn("scheduler entry 'late-job'", refusal["reason"])
        fx.jobs([])
        fx.adapter("lsof", LSOF_SHIM)
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(second.exists())

    def test_a_partly_finished_cache_removal_resumes_without_a_new_preview(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        project = fx.home / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(repo)).strip("-")
        for name in ("canvases", "mcps"):
            (project / name).mkdir(parents=True)
            (project / name / "f.txt").write_text(name)
        fifo = project / "mcps" / "pipe"
        os.mkfifo(str(fifo))
        _o, data = fx.preview("personal/alpha")
        self.assertEqual(len(fx.step_ids(data, "cache-remove")), 2, "one step per cache folder, so each is judged and resumed on its own")
        out = fx.confirm(data)
        self.assertEqual(out.rc, 1, out.text)
        self.assertFalse((project / "canvases").exists())
        self.assertTrue((project / "mcps").exists())
        self.assertTrue(repo.exists())
        fifo.unlink()
        done = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(done.rc, 0, done.text)
        self.assertFalse(repo.exists() or (project / "mcps").exists())

    def test_a_journal_that_changed_after_it_closed_is_not_trusted(self):
        fx = self.fx
        fx.repo("personal/alpha")
        op = self.executed("personal/alpha")
        self.assertEqual(fx.run("verify", "--operation", op, "--json").rc, 0)
        journal = fx.journal(op)
        original = journal.read_text()
        calm = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(calm.data["stage"], "already-closed")
        lines = original.splitlines()
        idx = next(i for i, line in enumerate(lines) if '"kind":"complete"' in line)
        edited = list(lines)
        edited[idx] = edited[idx].replace('"kind":"complete"', '"kind":"complete","note":"edited"')
        journal.write_text("\n".join(edited) + "\n")
        refused = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(refused.rc, 1, refused.text)
        self.assertIn("integrity", refused.data["refused"])
        self.assertEqual(fx.run("resume", "--operation", op, "--json").rc, 1)
        shown = fx.run("view", "--operation", op, "--json")
        self.assertTrue(shown.data["journal_problems"])
        doctor = fx.run("doctor", "--json")
        self.assertEqual(doctor.rc, 1, doctor.text)
        self.assertIn("operation:" + op, [c["id"] for c in doctor.data["checks"] if c["status"] == "fail"])
        journal.write_text("\n".join(lines[:idx] + lines[idx + 1:]) + "\n")
        self.assertEqual(fx.run("verify", "--operation", op, "--json").rc, 1, "a removed record is just as visible")
        journal.write_text(original)
        self.assertEqual(fx.run("verify", "--operation", op, "--json").data["stage"], "already-closed")

    @staticmethod
    def doctor_text(stamp, *violations):
        rows = "\n".join("VIOLATION  %s  repo  KleinPerkins/%s  t@t.t  main  0/5  note %s" % (v, v.split("/")[-1], stamp) for v in violations)
        return "root: x   date: %s   mode: local\nVERDICT  PATH  CLASS  OWNER/REPO\n%s\nSummary: 5 repos — OK 3 · ADVISORY 0 · DRIFT 1 · VIOLATION %d\n" % (stamp, rows, len(violations))

    def test_a_pre_existing_problem_may_move_with_the_clock_but_not_change(self):
        # the same problem, only the time moved: still fine
        fx = self.fx
        fx.repo("personal/alpha")
        fx.health("shadowsync", "[install] FAIL: stale authority records: 3\nchecked 2026-10-24 23:03:38\n", rc=1)
        fx.health("dev-doctor", self.doctor_text("2026-10-24 23:03", "personal/old-a"), rc=1)
        op = self.executed("personal/alpha")
        fx.health("shadowsync", "[install] FAIL: stale authority records: 3\nchecked 2026-10-25 02:19:00\n", rc=1)
        fx.health("dev-doctor", self.doctor_text("2026-10-25 02:19", "personal/old-a"), rc=1)
        calm = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(calm.rc, 0, calm.text)
        # a pre-existing problem that changed needs a person (or an honest exception)
        fx2 = Fx(self)
        self.fx = fx2
        fx2.repo("personal/alpha")
        fx2.health("shadowsync", "[install] FAIL: stale authority records: 3\n", rc=1)
        op2 = self.executed("personal/alpha")
        fx2.health("shadowsync", "[install] FAIL: stale authority records: 2\n", rc=1)
        changed = fx2.run("verify", "--operation", op2, "--json")
        self.assertEqual(changed.rc, 1, changed.text)
        health = [c for c in changed.data["checks"] if c["id"] == "health"][0]
        self.assertEqual(health["status"], "fail")
        self.assertIn("shadowsync", health["items"][0])
        excused = fx2.run("verify", "--operation", op2, "--exception", "subsystem-stale:shadowsync:its stale records are repaired through its own installer", "--json")
        self.assertEqual(excused.rc, 0, excused.text)
        # the same number of violations is not the same violations
        fx3 = Fx(self)
        self.fx = fx3
        fx3.repo("personal/alpha")
        fx3.health("dev-doctor", self.doctor_text("2026-10-24 23:03", "personal/old-a"), rc=1)
        op3 = self.executed("personal/alpha")
        fx3.health("dev-doctor", self.doctor_text("2026-10-25 02:19", "personal/old-b"), rc=1)
        swapped = fx3.run("verify", "--operation", op3, "--json")
        self.assertEqual(swapped.rc, 1, swapped.text)
        self.assertIn("appeared", [c for c in swapped.data["checks"] if c["id"] == "health"][0]["items"][0])

    def test_a_step_that_reported_failure_but_took_effect_is_reconciled_not_repeated(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.jobs([fx.fetch_job(repo)])
        fx.adapter("local-jobs", LOCAL_JOBS_FLAKY_SHIM)
        (fx.tmp / "local-jobs.flaky").write_text("1")
        data, done = fx.run_all("personal/alpha")
        self.assertEqual(done.rc, 1, done.text)
        self.assertEqual(done.data["outcome"], "failed")
        self.assertTrue(repo.exists())
        calls = (fx.tmp / "local-jobs.calls").read_text().count("delete-fetch-if-current")
        (fx.tmp / "local-jobs.flaky").unlink()
        resumed = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(resumed.rc, 0, resumed.text)
        self.assertEqual((fx.tmp / "local-jobs.calls").read_text().count("delete-fetch-if-current"), calls, "the job that is already gone is not deleted again")
        completes = [e for e in fx.events(data["operation"]) if e["kind"] == "complete" and e.get("subsystem") == "local-job-delete"]
        self.assertTrue(completes and completes[-1].get("reconciled"))
        self.assertFalse(repo.exists())

    def test_a_removed_checkout_that_comes_back_pauses_the_rest(self):
        fx = self.fx
        first, second, third = fx.repo("personal/first"), fx.repo("personal/second"), fx.repo("personal/third")
        _o, data = fx.preview("personal/first", "personal/second", "personal/third", extra=["--cohort-size", "1"])
        steps = fx.step_ids(data, "delete-checkout")
        self.assertEqual(len(steps), 3)
        # stop after the SECOND cohort, then bring back a checkout from the FIRST (an older cohort)
        self.assertEqual(fx.confirm(data, interrupt="after-complete:" + steps[1]).rc, 75)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        first.mkdir()
        (first / "new.txt").write_text("someone re-created this\n")
        paused = fx.run("resume", "--operation", data["operation"], "--json")
        self.assertEqual(paused.rc, 1, paused.text)
        self.assertEqual(paused.data["outcome"], "paused")
        self.assertTrue(third.exists(), "the next checkout is not touched while the situation is unclear")
        self.assertEqual((first / "new.txt").read_text(), "someone re-created this\n", "what came back is never touched")
        shutil.rmtree(str(first))
        self.assertEqual(fx.run("resume", "--operation", data["operation"], "--json").rc, 0)
        self.assertFalse(third.exists())

    def test_a_search_that_could_not_read_everything_is_never_reported_as_clean(self):
        if os.geteuid() == 0:
            self.skipTest("root can read everything")
        fx = self.fx
        fx.repo("personal/alpha")
        keep = fx.repo("personal/keep")
        locked = keep / "private-notes"
        locked.mkdir()
        (locked / "n.md").write_text("see personal/alpha\n")
        os.chmod(str(locked), 0o000)
        self.addCleanup(os.chmod, str(locked), 0o700)
        engines = ["python"] + (["rg"] if shutil.which("rg") else [])
        for engine in engines:
            with self.subTest(engine=engine):
                out = fx.run("view", "personal/alpha", "--scan-engine", engine, "--json")
                self.assertEqual(out.rc, 0, out.text)
                self.assertEqual([r["id"] for r in out.data["targets"][0]["risks"]], ["scan-incomplete"])
                self.assertFalse(out.data["scan"]["coverage"]["complete"])
                self.assertEqual(out.data["scan"]["coverage"]["unreadable"], 1, "one folder is counted once, however many parts of the search met it")
                self.assertEqual(out.data["scan"]["coverage"]["unreadable_paths"], [os.path.realpath(str(locked))])
        _o, data = fx.preview("personal/alpha")
        self.assertEqual(data["required_waivers"], ["scan-incomplete"])
        self.assertEqual(fx.confirm(data, waive=[]).rc, 1)
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        op = data["operation"]
        failed = fx.run("verify", "--operation", op, "--json")
        self.assertEqual(failed.rc, 1, failed.text)
        mentions = [c for c in failed.data["checks"] if c["id"] == "mentions"][0]
        self.assertEqual(mentions["status"], "fail")
        self.assertTrue(any("could not be searched" in item for item in mentions["items"]))
        passed = fx.run("verify", "--operation", op, "--exception", "retained-reference:personal/keep/private-notes:this folder is unreadable by design here", "--json")
        self.assertEqual(passed.rc, 0, passed.text)

    def test_exceptions_cannot_be_blanket_unmatched_or_secret_shaped(self):
        fx = self.fx
        fx.repo("personal/alpha")
        op = self.executed("personal/alpha")
        reason = "left on purpose; the owner decides later"
        pem = "-----BEGIN " + "PRIVATE KEY-----"
        for spec in (
            "retained-reference:.:" + reason,
            "retained-reference:personal:" + reason,
            "retained-reference:affirm/src:" + reason,
            "retained-reference:capabilities:" + reason,
            "retained-reference:~/.cursor:" + reason,
            "retained-reference:./personal/x:" + reason,
            "retained-reference:personal/x/:" + reason,
            "retained-reference:dev-doctor:" + reason,
            "subsystem-stale:personal/x:" + reason,
            "retained-reference:personal/x:rotated key " + "a1b2c3d4" * 6,
            "retained-reference:personal/x:" + pem,
            "retained-reference:personal/x:two\nlines of reason here",
            "retained-reference:personal/%s:%s" % (SECRET_LOOKING, reason),
        ):
            with self.subTest(spec=spec[:48]):
                self.assertEqual(fx.run("verify", "--operation", op, "--exception", spec, "--json").rc, 2)
        nothing = fx.run("verify", "--operation", op, "--exception", "retained-reference:personal/keep/notes.md:" + reason, "--json")
        self.assertEqual(nothing.rc, 1, nothing.text)
        self.assertIn("match nothing", nothing.data["refused"])
        self.assertNotIn("exception", fx.kinds(op), "an exception that matches nothing is never recorded")
        declared = fx.run("verify", "--operation", op, "--exception", "external-pending:registrar-domain:the registrar completes the deletion after its redemption period", "--json")
        self.assertEqual(declared.rc, 0, declared.text)

    def test_credential_shapes_never_reach_output_or_state_even_from_odd_places(self):
        fx = self.fx
        repo = fx.repo("personal/alpha")
        fx.git(repo, "remote", "set-url", "origin", "https://github.com/KleinPerkins/alpha.git?access_token=%s#frag" % SECRET_LOOKING)
        fx.git(repo, "checkout", "-q", "-b", SECRET_LOOKING)
        out, data = fx.preview("personal/alpha")
        self.assertEqual(out.rc, 0, out.text)
        self.assertEqual(data["targets"][0]["git"]["remotes"], [{"name": "origin", "url": "github.com/KleinPerkins/alpha"}])
        done = fx.confirm(data)
        self.assertEqual(done.rc, 0, done.text)
        verified = fx.run("verify", "--operation", data["operation"])
        shown = fx.run("view", "--operation", data["operation"])
        for output in (out, done, verified, shown):
            self.assertNotIn(SECRET_LOOKING, output.text)
        for root, _dirs, files in os.walk(str(fx.state)):
            for name in files:
                self.assertNotIn(SECRET_LOOKING, open(os.path.join(root, name)).read(), name)

    def test_a_refusal_before_the_tool_has_a_context_still_honours_json(self):
        fx = self.fx
        out = fx.run("doctor", "--json", env={"DEV_REMOVE_REPO_FIXTURE_ROOT": "/etc"})
        self.assertEqual(out.rc, 2, out.text)
        self.assertFalse(out.data["ok"])
        self.assertIn("fixture mode", out.data["refused"])
        plain = fx.run("doctor", env={"DEV_REMOVE_REPO_FIXTURE_ROOT": "/etc"})
        self.assertEqual(plain.rc, 2)
        self.assertIn("fixture mode", plain.err)

    def test_unlinking_a_client_link_never_follows_a_swapped_parent(self):
        engine = self.load_engine()
        self.assertIn("unlink_link_nofollow", engine, "links are removed through a no-follow descriptor chain")
        fx = self.fx

        class Context(object):
            pass

        ctx = Context()
        ctx.home, ctx.root = str(fx.home), str(fx.dev)
        unlink, Refusal = engine["unlink_link_nofollow"], engine["Refusal"]
        target = fx.outside / "real-target"
        target.mkdir()
        skills = fx.home / ".claude" / "skills"
        skills.mkdir(parents=True)
        link = skills / "alpha-skill"
        os.symlink(str(target), str(link))
        with self.assertRaises(Refusal):
            unlink(ctx, str(link), "/somewhere/else")
        self.assertTrue(link.is_symlink(), "a link that is not the previewed one is left alone")
        elsewhere = fx.outside / "elsewhere"
        elsewhere.mkdir()
        os.symlink(str(target), str(elsewhere / "alpha-skill"))
        link.unlink()
        skills.rmdir()
        os.symlink(str(elsewhere), str(skills))
        with self.assertRaises(Refusal):
            unlink(ctx, str(skills / "alpha-skill"), str(target))
        self.assertTrue((elsewhere / "alpha-skill").is_symlink(), "a swapped parent is never followed")
        os.unlink(str(skills))
        skills.mkdir()
        os.symlink(str(target), str(skills / "alpha-skill"))
        self.assertTrue(unlink(ctx, str(skills / "alpha-skill"), str(target)))
        self.assertFalse((skills / "alpha-skill").is_symlink())
        self.assertFalse(unlink(ctx, str(skills / "alpha-skill"), str(target)), "already gone is a clean no-op")
        self.assertTrue(target.exists())

    # ------------------------------------------------------------------ the sanitized Milestone 1 replay
    CASE_TESTS = {
        "risk-waivers": "test_every_risk_needs_its_own_named_waiver",
        "operator-gates-listed": "test_config_surfaces_and_the_fleet_are_operator_gates",
        "concurrent-writer": "test_active_writers_and_self_inside_are_blocking_and_not_waivable",
        "operator-gate-github-rules": "test_config_surfaces_and_the_fleet_are_operator_gates",
        "local-jobs-composed": "test_scheduled_jobs_are_deleted_through_the_owning_verb",
        "invalid-complete-corrected": "test_a_reported_success_that_did_not_happen_is_a_failure_not_a_completion",
        "preimage-digest-recorded": "test_any_change_after_the_preview_forces_a_new_preview",
        "governed-repo-detachment-gate": "test_consumers_in_retained_repos_are_a_waivable_risk_not_a_blocker",
        "guard-mode-restore": "test_awa_managed_worktrees_use_the_owning_verb",
        "linked-worktree-waiver": "test_dirty_linked_worktree_needs_its_own_waiver",
        "cohort-reference-clones": "test_cohorts_are_bounded_ordered_and_rescanned",
        "cohort-with-destruction-waiver": "test_every_risk_needs_its_own_named_waiver",
        "cohort-personal": "test_cohorts_are_bounded_ordered_and_rescanned",
        "cache-removal-keep-transcripts": "test_client_links_and_cursor_caches_are_cleaned_but_transcripts_are_kept",
        "operator-gate-reopen-then-complete": "test_a_writer_that_appears_between_cohorts_pauses_the_rest",
        "permission-boundary-failure": "test_a_failing_job_deletion_stops_safely_and_resumes_once_fixed",
        "pages-dns-attestation": "test_pages_and_domains_require_an_explicit_attestation",
        "ordered-cohort-after-external-gates": "test_cohorts_are_bounded_ordered_and_rescanned",
        "external-pending-exception": "test_exception_ledger_rejects_dishonest_or_dangerous_entries",
        "subsystem-stale-exception": "test_health_is_compared_with_the_baseline_taken_before_the_first_change",
        "generated-index-refresh": "test_the_generated_index_is_refreshed_through_its_owning_verb",
        "generated-memory-mentions": "test_generated_memory_mentions_are_reported_and_must_be_excepted_at_verify",
        "health-vs-baseline": "test_health_is_compared_with_the_baseline_taken_before_the_first_change",
        "secret-handling-cleanup": "test_state_is_private_and_free_of_secrets",
        "close-with-exceptions": "test_verify_requires_every_remaining_mention_to_map_to_an_exception",
    }
    CONSEQUENTIAL_KINDS = ("intent",)

    def replay_events(self):
        return [json.loads(line) for line in REPLAY.read_text().splitlines() if line.strip()]

    def test_replay_fixture_is_sanitized_and_traceable_to_the_closed_journal(self):
        events = self.replay_events()
        self.assertEqual([e["seq"] for e in events], list(range(1, 57)))
        source = events[0]["source"]
        self.assertEqual(source["operation"], "ret-20261023-2210")
        self.assertEqual(source["close_prefix_events"], 55)
        self.assertEqual(source["close_prefix_sha256"], "45d156a2e9a8613c82a075d1ceb717b787a208eb5692a43dd15b0d6082b89738")
        self.assertEqual(source["plan_body_sha256"], "2ce6764fbeba0e1e0e3f299986e1f5522792532dd928d904faf36c4d44324a1f")
        text = REPLAY.read_text()
        banned = [
            r"https?://", r"\b\d{1,3}(\.\d{1,3}){3}\b", r"ghp_", r"github_pat_", r"Bearer ", r"ssh-", r"/Users/", r"/home/",
            r"\.com\b", r"\.io\b", r"@[A-Za-z0-9-]+\.", r"\bPR #?\d+", r"\b[0-9a-f]{40}\b",
        ]
        for pattern in banned:
            self.assertIsNone(re.search(pattern, text), "the replay must not contain %s" % pattern)

    def test_replay_pairs_every_consequential_intent_with_its_outcome(self):
        events = self.replay_events()
        out = subprocess.run(
            ["bash", str(SCRIPT), "doctor", "--journal", str(REPLAY), "--json"],
            env=dict(os.environ, TMPDIR=tempfile.gettempdir(), DEV_REMOVE_REPO_FIXTURE_ROOT=str(self.fx.tmp), HOME=str(self.fx.sentinel)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        report = json.loads(out.stdout)
        self.assertEqual(report["format"], "replay")
        self.assertTrue(report["contiguous"] and report["closed"])
        intents = [e for e in events if e["kind"] in self.CONSEQUENTIAL_KINDS]
        self.assertEqual(len(intents), 16)
        pairs = {p["intent"]: p for p in report["pairs"]}
        self.assertEqual(sorted(pairs), sorted(e["seq"] for e in intents))
        for intent in intents:
            pair = pairs[intent["seq"]]
            expect = intent["expect"]
            self.assertEqual(pair["status"], expect["status"], "intent %d" % intent["seq"])
            self.assertEqual(pair["corrected"], expect["corrected"], "intent %d" % intent["seq"])
            self.assertEqual(pair["reopened"], expect["reopened"], "intent %d" % intent["seq"])
        self.assertEqual(report["unpaired_completes"], 7)

    def test_replay_cases_map_to_implemented_acceptance_tests(self):
        events = self.replay_events()
        cases = sorted({e["case"] for e in events if e.get("case")})
        self.assertEqual(cases, sorted(self.CASE_TESTS), "every case in the replay needs an acceptance test, and no case may be dropped")
        for case, test in sorted(self.CASE_TESTS.items()):
            self.assertTrue(callable(getattr(type(self), test, None)), "case %s -> missing test %s" % (case, test))
        consequential = [e for e in events if e["kind"] == "intent"]
        self.assertTrue(all(e.get("case") in self.CASE_TESTS for e in consequential), "every consequential intent maps to a test")
        for e in events:
            if e["kind"] in ("baseline", "preflight", "drift", "manifest", "surprise", "complete", "close") and e.get("case"):
                self.assertIn(e["case"], self.CASE_TESTS)

    def test_replay_cross_checks_the_real_closed_journal_when_present(self):
        real = Path.home() / ".local" / "state" / "dev-repo-removal" / "ret-20261023-2210" / "events.jsonl"
        if not real.is_file():
            self.skipTest("the original journal is not on this machine")
        out = subprocess.run(
            ["bash", str(SCRIPT), "doctor", "--journal", str(real), "--json"],
            env=dict(os.environ, TMPDIR=tempfile.gettempdir(), DEV_REMOVE_REPO_FIXTURE_ROOT=str(self.fx.tmp), HOME=str(self.fx.sentinel)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        original = json.loads(out.stdout)
        self.assertEqual(original["events"], 56)
        self.assertTrue(original["close_digest_ok"])
        self.assertEqual(original["intents"], 16)
        real_kinds = [json.loads(line)["kind"] for line in real.read_text().splitlines() if line.strip()]
        fixture_kinds = [e["kind"] for e in self.replay_events()]
        self.assertEqual(len(real_kinds), len(fixture_kinds))
        differing = [i + 1 for i, (a, b) in enumerate(zip(real_kinds, fixture_kinds)) if a != b]
        self.assertEqual(differing, [37], "only the forbidden-API step differs: the original wrote a surprise, the fixture the explicit failure")
        self.assertEqual((real_kinds[36], fixture_kinds[36]), ("surprise", "failure"))

    # ------------------------------------------------------------------ repository wiring (present on a full tree)
    def test_skill_runbook_and_installer_are_wired(self):
        skill = ROOT / "_ops" / "skills" / "dev-remove-repo" / "SKILL.md"
        runbook = ROOT / "docs" / "runbooks" / "dev-repo-removal.md"
        installer = (ROOT / "_ops" / "bin" / "install-skills.sh")
        if not skill.exists():
            self.skipTest("the skill is not part of this tree")
        text = skill.read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertRegex(text, r"(?m)^name: dev-remove-repo$")
        for verb in ("view", "remove", "resume", "verify", "doctor"):
            self.assertIn(verb, text)
        self.assertTrue(runbook.exists())
        body = runbook.read_text()
        headings = " | ".join(line[3:].lower() for line in body.splitlines() if line.startswith("## "))
        for topic in ("preflight", "content risk", "consumers", "remote automation", "local wiring", "worktrees",
                      "pages, dns and registrar", "cohorts", "verify", "exception ledger", "rollback", "failure modes", "secret handling"):
            self.assertIn(topic, headings, "the runbook must cover: " + topic)
        self.assertNotRegex(body, SECRET_LOOKING_RE, "no credential-shaped text in the runbook")
        self.assertEqual(installer.read_text().count("dev-remove-repo"), 4, "exposed to the dev, Cursor, Claude and Codex skill sets")
        self.assertTrue(os.access(str(SCRIPT), os.X_OK))
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "docs/runbooks/dev-repo-removal.md"])
        self.assertEqual(ignored.returncode, 1, "the runbook must be admitted by the allow-list .gitignore")

    def test_the_installer_exposes_the_skill_idempotently_and_never_clobbers(self):
        installer = ROOT / "_ops" / "bin" / "install-skills.sh"
        skill = ROOT / "_ops" / "skills" / "dev-remove-repo"
        if not (skill / "SKILL.md").exists():
            self.skipTest("the skill is not part of this tree")
        self.assertTrue(installer.exists())
        with tempfile.TemporaryDirectory(prefix="drr-install-") as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": tempfile.gettempdir()}

            def run():
                return subprocess.run(["bash", str(installer)], env=env, cwd=str(home), capture_output=True, text=True, timeout=120)

            first = run()
            self.assertEqual(first.returncode, 0, first.stderr)
            for tool in (".cursor", ".claude", ".codex"):
                link = home / tool / "skills" / "dev-remove-repo"
                self.assertTrue(link.is_symlink(), tool)
                self.assertEqual(os.readlink(str(link)), str(skill))
                self.assertTrue((link / "SKILL.md").is_file())
            second = run()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotIn("linked ", second.stdout, "a second run changes nothing")
            link = home / ".claude" / "skills" / "dev-remove-repo"
            link.unlink()
            link.mkdir()
            (link / "mine.txt").write_text("keep")
            third = run()
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertIn("not clobbering", third.stdout)
            self.assertFalse(link.is_symlink())
            self.assertEqual((link / "mine.txt").read_text(), "keep")
            self.assertTrue((home / ".cursor" / "skills" / "dev-remove-repo").is_symlink())


# The fast tier that verify-operating-model.sh runs (about a minute); `make dev-remove-repo-verify` runs everything.
SMOKE = (
    "test_personal_view_recognises_original_scaffold_after_restore",
    "test_personal_view_observes_selected_peers_and_configured_jobs",
    "test_skill_runbook_and_installer_are_wired",
    "test_the_installer_exposes_the_skill_idempotently_and_never_clobbers",
    "test_view_is_read_only_and_creates_no_state",
    "test_clean_checkout_end_to_end",
    "test_protected_targets_and_malformed_paths_are_refused_and_create_nothing",
    "test_confirmation_is_exact_and_boolean_tokens_are_invalid",
    "test_symlinked_targets_and_parents_are_never_followed",
    "test_the_policy_marker_must_be_exact",
    "test_replay_fixture_is_sanitized_and_traceable_to_the_closed_journal",
    "test_replay_pairs_every_consequential_intent_with_its_outcome",
    "test_state_is_private_and_free_of_secrets",
    "test_doctor_reports_a_healthy_tool",
)


if __name__ == "__main__":
    extra = sys.argv[2:]
    if extra not in ([], ["--smoke"]):
        raise SystemExit("usage: dev-remove-repo.sh [--smoke]")
    if extra:
        missing = [n for n in SMOKE if not hasattr(DevRemoveRepoTests, n)]
        if missing:
            raise SystemExit("smoke tier names a test that no longer exists: %s" % ", ".join(missing))
        suite = unittest.TestSuite(DevRemoveRepoTests(n) for n in SMOKE)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(DevRemoveRepoTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("dev-remove-repo%s: OK" % (" (smoke)" if extra else ""))
PY
