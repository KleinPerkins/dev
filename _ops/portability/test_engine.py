from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("portability_engine", HERE / "engine.py")
assert SPEC and SPEC.loader
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"},
    )
    if result.returncode:
        raise AssertionError(f"fixture Git command failed: {arguments!r}")
    return result.stdout.strip()


def make_source(parent: Path, name: str, *, ignored: bool = False) -> tuple[Path, str]:
    source = parent / name
    source.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", os.fspath(source)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run_git(source, "config", "user.name", "Fixture")
    run_git(source, "config", "user.email", "fixture@example.invalid")
    (source / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    if ignored:
        (source / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    run_git(source, "add", ".")
    run_git(source, "commit", "-q", "-m", "fixture")
    return source, run_git(source, "rev-parse", "HEAD")


class FixtureGit(engine.GitRunner):
    """In-process transport mapping canonical remotes to local Git fixtures."""

    def __init__(self, mappings: dict[str, Path]):
        super().__init__()
        self.mappings = mappings
        self.probes: list[str] = []
        self.clones: list[str] = []
        self.denied: set[str] = set()
        self.interrupt_once: set[str] = set()
        self.available = True

    def check_available(self) -> None:
        if not self.available:
            raise engine.GitError("availability check")
        super().check_available()

    def probe(self, remote: str) -> str:
        self.probes.append(remote)
        if remote in self.denied:
            raise engine.GitError("access probe", 128)
        source = self.mappings.get(remote)
        if source is None:
            raise engine.GitError("access probe", 128)
        self._run([*self._safe_options(), "ls-remote", "--symref", os.fspath(source), "HEAD"], operation="access probe")
        return run_git(source, "rev-parse", "refs/heads/main")

    def clone(self, remote: str, destination: Path) -> None:
        self.clones.append(remote)
        source = self.mappings.get(remote)
        if source is None:
            raise engine.GitError("clone", 128)
        super().clone(os.fspath(source), destination)
        self._run(
            [*self._safe_options(), "-C", os.fspath(destination), "config", "--local", "remote.origin.url", remote],
            operation="fixture transport rewrite",
        )
        if remote in self.interrupt_once:
            self.interrupt_once.remove(remote)
            raise engine.GitError("simulated interrupted clone", 75)


def repository(
    repository_id: str,
    path: str,
    revision: str | None,
    disposition: str,
    *,
    required: bool = True,
    reason: str = "fixture disposition",
) -> dict[str, object]:
    return {
        "id": repository_id,
        "path": path,
        "revision": revision,
        "disposition": disposition,
        "reason": reason,
        "required": required,
    }


def manifest(
    repositories: list[dict[str, object]],
    *,
    capabilities: list[dict[str, object]] | None = None,
    local_state: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema": engine.MANIFEST_SCHEMA,
        "profile": engine.PROFILE,
        "platform": {"os": "Darwin", "architecture": "arm64"},
        "repositories": repositories,
        "capabilities": capabilities or [],
        "local_state": local_state or [],
    }


def write_manifest(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class ManifestContractTests(unittest.TestCase):
    def test_closed_schema_and_revision_rules(self) -> None:
        active = manifest([repository("KleinPerkins/tool", "personal/tool", "a" * 40, "clone")])
        self.assertIs(engine.validate_manifest(active), active)

        blocked_null = manifest([repository("KleinPerkins/dev", ".", None, "blocked-review")])
        engine.validate_manifest(blocked_null)
        blocked_known = manifest([repository("KleinPerkins/dev", ".", "b" * 40, "blocked-review")])
        engine.validate_manifest(blocked_known)

        for revision in (None, "A" * 40, "0" * 39):
            invalid = manifest([repository("KleinPerkins/tool", "personal/tool", revision, "clone")])
            with self.assertRaises(engine.ManifestError):
                engine.validate_manifest(invalid)

        unknown = manifest([repository("KleinPerkins/tool", "personal/tool", "a" * 40, "clone")])
        unknown["command"] = "anything"
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(unknown)

    def test_duplicate_json_keys_and_path_collisions_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            with self.assertRaises(engine.ManifestError):
                engine.load_manifest(path)

        collision = manifest(
            [
                repository("KleinPerkins/one", "personal/Tool", "a" * 40, "clone"),
                repository("KleinPerkins/two", "personal/tool", "b" * 40, "clone"),
            ]
        )
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(collision)

        traversal = manifest([repository("KleinPerkins/tool", "../tool", "a" * 40, "clone")])
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(traversal)

        overlap = manifest(
            [
                repository("KleinPerkins/one", "Personal", "a" * 40, "clone"),
                repository("KleinPerkins/two", "personal/tool", "b" * 40, "clone"),
            ]
        )
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(overlap)
        for reserved in ("personal/.git/config", "personal/.portability-stage-x"):
            with self.assertRaises(engine.ManifestError):
                engine.validate_manifest(
                    manifest([repository("KleinPerkins/tool", reserved, "a" * 40, "clone")])
                )

    def test_protected_and_work_identities_cannot_be_active(self) -> None:
        active_protected = manifest(
            [repository("KleinPerkins/chaos_scheduler", "personal/tool", "a" * 40, "source-only")]
        )
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(active_protected)

        path_alias = manifest(
            [repository("KleinPerkins/tool", "personal/chaos-scheduler", "a" * 40, "clone")]
        )
        with self.assertRaises(engine.ManifestError):
            engine.validate_manifest(path_alias)

        for name in ("cpp", "ai-analytics-context"):
            active_work = manifest(
                [repository(f"KleinPerkins/{name}", f"personal/{name}", "a" * 40, "clone")]
            )
            with self.assertRaises(engine.ManifestError):
                engine.validate_manifest(active_work)
            engine.validate_manifest(
                manifest([repository(f"KleinPerkins/{name}", f"personal/{name}", None, "excluded-work")])
            )
            with self.assertRaises(engine.ManifestError):
                engine.validate_manifest(
                    manifest([repository("KleinPerkins/tool", f"personal/{name}", "a" * 40, "clone")])
                )

        fixed_dispositions = {
            "ecosystem-orchestrator": "excluded-work",
            "dev": "blocked-review",
            "chaos-labs": "blocked-review",
        }
        for name, required_disposition in fixed_dispositions.items():
            active = manifest(
                [repository(f"KleinPerkins/{name}", "." if name == "dev" else f"personal/{name}", "a" * 40, "clone")]
            )
            with self.assertRaises(engine.ManifestError):
                engine.validate_manifest(active)
            engine.validate_manifest(
                manifest(
                    [
                        repository(
                            f"KleinPerkins/{name}",
                            "." if name == "dev" else f"personal/{name}",
                            "b" * 40,
                            required_disposition,
                        )
                    ]
                )
            )

        engine.validate_manifest(
            manifest(
                [repository("KleinPerkins/chaos-scheduler", "personal/chaos-scheduler", None, "blocked-protected")]
            )
        )


class EngineFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.sources = self.base / "sources"
        self.sources.mkdir()
        self.root = self.base / "target"
        self.state = self.base / "state"
        self.manifest_path = self.base / "manifest.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build_engine(
        self,
        document: dict[str, object],
        transport: FixtureGit,
        *,
        platform_value: tuple[str, str] = ("Darwin", "arm64"),
        report: Path | None = None,
    ) -> engine.Engine:
        write_manifest(self.manifest_path, document)
        return engine.Engine(
            self.manifest_path,
            self.root,
            self.state,
            report,
            git=transport,
            platform_probe=lambda: platform_value,
        )

    def one_active_manifest(
        self,
        revision: str,
        *,
        disposition: str = "clone",
        required: bool = True,
        capabilities: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return manifest(
            [
                repository("KleinPerkins/dev", ".", "d" * 40, "blocked-review", required=False),
                repository("KleinPerkins/tool", "personal/tool", revision, disposition, required=required),
            ],
            capabilities=capabilities,
        )


class PlanningAndApplyTests(EngineFixture):
    def test_plan_is_nonmutating_and_blocked_rows_are_never_accessed(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = manifest(
            [
                repository("KleinPerkins/dev", ".", "d" * 40, "blocked-review", required=False),
                repository(
                    "KleinPerkins/chaos-scheduler",
                    "personal/chaos-scheduler",
                    None,
                    "blocked-protected",
                    required=False,
                ),
                repository("KleinPerkins/tool", "personal/tool", revision, "clone"),
            ]
        )
        remote = engine.canonical_remote("KleinPerkins/tool")
        transport = FixtureGit({remote: tool})
        report = self.build_engine(document, transport).plan()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(transport.probes, [remote])
        self.assertEqual(transport.clones, [])
        self.assertEqual(
            [row["status"] for row in report["repositories"]],
            ["blocked_review", "blocked_protected", "planned_clone"],
        )

    def test_fresh_apply_report_and_rerun_are_idempotent(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        transport = FixtureGit({remote: tool})
        subject = self.build_engine(document, transport)

        first = subject.apply()
        target = self.root / "personal" / "tool"
        self.assertTrue(target.is_dir())
        self.assertFalse((self.root / ".git").exists(), "blocked root must remain a plain container")
        self.assertEqual(run_git(target, "rev-parse", "HEAD"), revision)
        self.assertEqual(run_git(target, "config", "--local", "user.name"), engine.PERSONAL_NAME)
        self.assertEqual(run_git(target, "config", "--local", "user.email"), engine.PERSONAL_EMAIL)
        self.assertTrue(first["source_ready"])
        self.assertTrue(first["operational_complete"])
        self.assertEqual(transport.clones, [remote])

        report_document = json.loads((self.state / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report_document["manifest"], document)
        self.assertEqual(stat.S_IMODE((self.state / "report.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)

        second = subject.apply()
        self.assertTrue(second["source_ready"])
        self.assertEqual(transport.clones, [remote])

    def test_explicit_plan_report_is_the_only_plan_write(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        transport = FixtureGit({remote: tool})
        report_path = self.state / "plan.json"
        subject = self.build_engine(document, transport, report=report_path)
        subject.plan()
        self.assertTrue(report_path.is_file())
        self.assertFalse((self.state / "journal.json").exists())
        owner_path = self.state / ".report-owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["state"] = "pending"
        owner_path.write_text(json.dumps(owner), encoding="utf-8")
        report_path.unlink()
        applied = subject.apply()
        self.assertEqual(applied["repositories"][1]["status"], "verified")

    def test_unmerged_remote_commit_is_not_an_eligible_pin(self) -> None:
        tool, _ = make_source(self.sources, "tool")
        run_git(tool, "checkout", "-q", "-b", "feature")
        (tool / "feature.txt").write_text("unmerged\n", encoding="utf-8")
        run_git(tool, "add", "feature.txt")
        run_git(tool, "commit", "-q", "-m", "unmerged")
        unmerged = run_git(tool, "rev-parse", "HEAD")
        run_git(tool, "checkout", "-q", "main")
        remote = engine.canonical_remote("KleinPerkins/tool")
        result = self.build_engine(self.one_active_manifest(unmerged), FixtureGit({remote: tool})).apply()
        self.assertEqual(result["repositories"][1]["status"], "failed")
        self.assertFalse((self.root / "personal" / "tool").exists())

    def test_source_only_repository_and_capability_are_not_operational(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        capability = {
            "id": "example-capability",
            "owner": "KleinPerkins/skills",
            "disposition": "source-only",
            "reason": "owner activation is separate",
            "required": True,
        }
        document = self.one_active_manifest(revision, disposition="source-only", capabilities=[capability])
        remote = engine.canonical_remote("KleinPerkins/tool")
        result = self.build_engine(document, FixtureGit({remote: tool})).apply()
        self.assertTrue((self.root / "personal" / "tool").is_dir())
        self.assertFalse(result["operational_complete"])
        self.assertEqual({blocker["kind"] for blocker in result["required_blockers"]}, {"repository", "capability"})

    def test_interrupted_clone_resumes_only_owned_staging(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        transport = FixtureGit({remote: tool})
        transport.interrupt_once.add(remote)
        subject = self.build_engine(document, transport)

        failed = subject.apply()
        self.assertEqual(failed["repositories"][1]["status"], "failed")
        self.assertFalse((self.root / "personal" / "tool").exists())
        stages = list((self.root / "personal").glob(".portability-stage-*"))
        self.assertEqual(len(stages), 1)

        resumed = subject.resume()
        self.assertEqual(resumed["repositories"][1]["status"], "verified")
        self.assertTrue((self.root / "personal" / "tool").is_dir())
        self.assertEqual(list((self.root / "personal").glob(".portability-stage-*")), [])
        self.assertEqual(transport.clones, [remote, remote])

    def test_installed_crash_with_empty_owned_staging_recovers(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        journal_path = self.state / "journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        nonce = "a" * 32
        container = subject.root / "personal" / f".portability-stage-crash-{nonce}"
        container.mkdir()
        journal["actions"]["KleinPerkins/tool"]["staging"] = {
            "container": os.fspath(container),
            "nonce": nonce,
            "device": None,
            "inode": None,
        }
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
        result = subject.resume()
        self.assertEqual(result["repositories"][1]["status"], "verified")
        self.assertFalse(container.exists())

    def test_empty_root_created_before_binding_can_resume(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject._ensure_state_dir()
        subject._load_or_create_journal()
        subject.root.mkdir()
        result = subject.resume()
        self.assertEqual(result["repositories"][1]["status"], "verified")


class ConflictAndPrerequisiteTests(EngineFixture):
    def _clone_existing(self, source: Path, target: Path, remote: str, revision: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", os.fspath(source), os.fspath(target)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        run_git(target, "remote", "set-url", "origin", remote)
        run_git(target, "checkout", "-q", "--detach", revision)
        run_git(target, "config", "--local", "user.name", engine.PERSONAL_NAME)
        run_git(target, "config", "--local", "user.email", engine.PERSONAL_EMAIL)

    def test_wrong_remote_dirty_and_wrong_head_are_preserved(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        expected_remote = engine.canonical_remote("KleinPerkins/tool")
        target = self.root / "personal" / "tool"
        self._clone_existing(tool, target, engine.canonical_remote("KleinPerkins/other"), revision)
        result = self.build_engine(document, FixtureGit({expected_remote: tool})).apply()
        self.assertEqual(result["repositories"][1]["status"], "conflict")
        self.assertEqual(run_git(target, "remote", "get-url", "origin"), engine.canonical_remote("KleinPerkins/other"))

        run_git(target, "remote", "set-url", "origin", expected_remote)
        (target / "README.md").write_text("changed\n", encoding="utf-8")
        dirty = self.build_engine(document, FixtureGit({expected_remote: tool})).verify()
        self.assertEqual(dirty["repositories"][1]["status"], "conflict")
        self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "changed\n")

        (target / "README.md").write_text("# tool\n", encoding="utf-8")
        (tool / "next.txt").write_text("next\n", encoding="utf-8")
        run_git(tool, "add", "next.txt")
        run_git(tool, "commit", "-q", "-m", "next")
        later = run_git(tool, "rev-parse", "HEAD")
        run_git(target, "fetch", "-q", os.fspath(tool), later)
        run_git(target, "checkout", "-q", "--detach", later)
        wrong_head = self.build_engine(document, FixtureGit({expected_remote: tool})).verify()
        self.assertEqual(wrong_head["repositories"][1]["status"], "conflict")
        self.assertEqual(run_git(target, "rev-parse", "HEAD"), later)

    def test_existing_identity_and_push_routing_must_be_personal_and_closed(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        target = self.root / "personal" / "tool"
        self._clone_existing(tool, target, remote, revision)
        run_git(target, "config", "--local", "user.email", "person@affirm.com")
        result = self.build_engine(document, FixtureGit({remote: tool})).apply()
        self.assertEqual(result["repositories"][1]["status"], "conflict")
        self.assertEqual(run_git(target, "config", "--local", "user.email"), "person@affirm.com")

        run_git(target, "config", "--local", "user.email", engine.PERSONAL_EMAIL)
        run_git(target, "config", "--local", "remote.origin.pushurl", "git@github.com:Affirm/work.git")
        result = self.build_engine(document, FixtureGit({remote: tool})).verify()
        self.assertEqual(result["repositories"][1]["status"], "conflict")

    def test_blocked_root_git_checkout_and_git_backed_state_are_refused(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        self.root.mkdir()
        subprocess.run(
            ["git", "init", "-q", os.fspath(self.root)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        marker = self.root / "existing.txt"
        marker.write_text("preserve\n", encoding="utf-8")
        result = self.build_engine(document, FixtureGit({remote: tool})).apply()
        self.assertEqual(result["repositories"][1]["status"], "failed")
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse((self.root / "personal").exists())

        state_repo = self.base / "state-repo"
        state_repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", os.fspath(state_repo)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_manifest(self.manifest_path, document)
        with self.assertRaises(engine.SafetyError):
            engine.Engine(
                self.manifest_path,
                self.base / "other-target",
                state_repo / "private-state",
                git=FixtureGit({remote: tool}),
                platform_probe=lambda: ("Darwin", "arm64"),
            )

    def test_platform_git_and_access_failures_do_not_block_independent_rows(self) -> None:
        one, one_revision = make_source(self.sources, "one")
        two, two_revision = make_source(self.sources, "two")
        document = manifest(
            [
                repository("KleinPerkins/dev", ".", None, "blocked-review", required=False),
                repository("KleinPerkins/one", "personal/one", one_revision, "clone"),
                repository("KleinPerkins/two", "personal/two", two_revision, "clone"),
            ]
        )
        one_remote = engine.canonical_remote("KleinPerkins/one")
        two_remote = engine.canonical_remote("KleinPerkins/two")

        wrong_platform = FixtureGit({one_remote: one, two_remote: two})
        result = self.build_engine(document, wrong_platform, platform_value=("Linux", "x86_64")).apply()
        self.assertTrue(result["errors"])
        self.assertEqual(wrong_platform.clones, [])

        shutil_state = self.state
        if shutil_state.exists():
            import shutil

            shutil.rmtree(shutil_state)
        missing_git = FixtureGit({one_remote: one, two_remote: two})
        missing_git.available = False
        result = self.build_engine(document, missing_git).apply()
        self.assertTrue(result["errors"])
        self.assertEqual(missing_git.clones, [])

        import shutil

        shutil.rmtree(self.state)
        access = FixtureGit({one_remote: one, two_remote: two})
        access.denied.add(one_remote)
        result = self.build_engine(document, access).apply()
        statuses = {row["id"]: row["status"] for row in result["repositories"]}
        self.assertEqual(statuses["KleinPerkins/one"], "blocked_access")
        self.assertEqual(statuses["KleinPerkins/two"], "verified")
        self.assertFalse((self.root / "personal" / "one").exists())
        self.assertTrue((self.root / "personal" / "two").is_dir())

    def test_symlink_escape_refuses_without_touching_destination(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        outside = self.base / "outside"
        outside.mkdir()
        self.root.mkdir()
        (self.root / "personal").symlink_to(outside, target_is_directory=True)
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        result = subject.apply()
        self.assertEqual(result["repositories"][1]["status"], "failed")
        self.assertEqual(list(outside.iterdir()), [])


class RollbackTests(EngineFixture):
    def test_journal_action_engine_binding_and_symlink_tamper_refuse(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        journal_path = self.state / "journal.json"
        original = json.loads(journal_path.read_text(encoding="utf-8"))

        malformed_type = json.loads(json.dumps(original))
        malformed_type["actions"]["KleinPerkins/tool"]["status"] = []
        journal_path.write_text(json.dumps(malformed_type), encoding="utf-8")
        result = subject.rollback()
        self.assertIn("journal action record is invalid", " ".join(result["errors"]))

        malformed_root = json.loads(json.dumps(original))
        malformed_root["root_binding"]["current"]["state"] = []
        journal_path.write_text(json.dumps(malformed_root), encoding="utf-8")
        result = subject.rollback()
        self.assertIn("root observation is invalid", " ".join(result["errors"]))

        malformed_inventory = json.loads(json.dumps(original))
        malformed_inventory["actions"]["KleinPerkins/tool"]["postimage"]["git_inventory"]["sha256"] = []
        journal_path.write_text(json.dumps(malformed_inventory), encoding="utf-8")
        result = subject.rollback()
        self.assertIn("postimage record is invalid", " ".join(result["errors"]))

        malformed = json.loads(json.dumps(original))
        malformed["actions"]["KleinPerkins/tool"]["path"] = "personal/other"
        journal_path.write_text(json.dumps(malformed), encoding="utf-8")
        result = subject.rollback()
        self.assertIn("journal action record is invalid", " ".join(result["errors"]))

        wrong_engine = json.loads(json.dumps(original))
        wrong_engine["engine_digest"] = "sha256:" + "0" * 64
        journal_path.write_text(json.dumps(wrong_engine), encoding="utf-8")
        result = subject.rollback()
        self.assertIn("different engine", " ".join(result["errors"]))

        outside = self.base / "outside-journal"
        outside.write_text("{}", encoding="utf-8")
        journal_path.unlink()
        journal_path.symlink_to(outside)
        result = subject.verify()
        self.assertTrue(result["errors"])
        self.assertEqual(outside.read_text(encoding="utf-8"), "{}")

    def test_verify_postimage_drift_is_operationally_blocking(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        target = self.root / "personal" / "tool"
        run_git(target, "branch", "local-only")
        result = subject.verify()
        tool_row = next(row for row in result["repositories"] if row["id"] == "KleinPerkins/tool")
        self.assertFalse(tool_row["postimage_intact"])
        self.assertFalse(tool_row["operational_complete"])
        self.assertTrue(result["errors"])

    def test_detached_commit_and_git_only_work_block_rollback(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        target = self.root / "personal" / "tool"
        (target / "README.md").write_text("detached work\n", encoding="utf-8")
        run_git(target, "add", "README.md")
        run_git(target, "commit", "-q", "-m", "detached user work")
        run_git(target, "checkout", "-q", "--detach", revision)
        self.assertEqual(run_git(target, "status", "--porcelain"), "")

        result = subject.rollback()
        self.assertTrue(target.exists())
        self.assertIn("Git metadata changed", " ".join(result["errors"]))

    def test_tampered_owned_directory_record_cannot_escape_root(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        outside = self.base / "unrelated-empty-directory"
        outside.mkdir()
        info = outside.stat()
        journal_path = self.state / "journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal["owned_directories"].append(
            {"path": os.fspath(outside), "device": info.st_dev, "inode": info.st_ino}
        )
        journal_path.write_text(json.dumps(journal), encoding="utf-8")

        result = subject.rollback()
        self.assertTrue(outside.is_dir())
        self.assertIn("owned-directory record escapes", " ".join(result["errors"]))

    def test_rollback_refuses_ignored_data_new_refs_and_dirty_files(self) -> None:
        tool, revision = make_source(self.sources, "tool", ignored=True)
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        target = self.root / "personal" / "tool"

        ignored = target / "ignored" / "state.db"
        ignored.parent.mkdir()
        ignored.write_text("user state\n", encoding="utf-8")
        result = subject.rollback()
        self.assertTrue(target.exists())
        self.assertIn("repository content changed", " ".join(result["errors"]))

        ignored.unlink()
        ignored.parent.rmdir()
        run_git(target, "branch", "user-branch")
        result = subject.rollback()
        self.assertTrue(target.exists())
        self.assertIn("Git metadata changed", " ".join(result["errors"]))

        run_git(target, "branch", "-D", "user-branch")
        (target / "README.md").write_text("tamper\n", encoding="utf-8")
        result = subject.rollback()
        self.assertTrue(target.exists())
        self.assertIn("content changed", " ".join(result["errors"]))

        (target / "README.md").write_text("# tool\n", encoding="utf-8")
        result = subject.rollback()
        self.assertFalse(target.exists())
        self.assertTrue(self.root.exists(), "rollback never removes the root container")
        self.assertIn("removed_owned_clone", {row["status"] for row in result["repositories"]})
        second = subject.rollback()
        tool_row = next(row for row in second["repositories"] if row["id"] == "KleinPerkins/tool")
        self.assertEqual(tool_row["status"], "already_rolled_back")
        self.assertFalse(tool_row["source_ready"])
        self.assertFalse(tool_row["operational_complete"])

    def test_preexisting_repository_is_never_removed(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        target = self.root / "personal" / "tool"
        target.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "-q", os.fspath(tool), os.fspath(target)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        run_git(target, "remote", "set-url", "origin", remote)
        run_git(target, "checkout", "-q", "--detach", revision)
        run_git(target, "config", "--local", "user.name", engine.PERSONAL_NAME)
        run_git(target, "config", "--local", "user.email", engine.PERSONAL_EMAIL)
        subject = self.build_engine(document, FixtureGit({remote: tool}))
        subject.apply()
        result = subject.rollback()
        self.assertTrue(target.exists())
        self.assertIn("preserved_preexisting", {row["status"] for row in result["repositories"]})

    def test_new_root_repository_is_never_removed(self) -> None:
        home, revision = make_source(self.sources, "home-root")
        document = manifest([repository("KleinPerkins/home-root", ".", revision, "clone")])
        remote = engine.canonical_remote("KleinPerkins/home-root")
        subject = self.build_engine(document, FixtureGit({remote: home}))
        subject.apply()
        result = subject.rollback()
        self.assertTrue((self.root / ".git").is_dir())
        self.assertIn("rollback never removes root", " ".join(result["errors"]))


class InterfaceSafetyTests(EngineFixture):
    def test_root_and_state_binding_refuse_broad_or_overlapping_paths(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        transport = FixtureGit({engine.canonical_remote("KleinPerkins/tool"): tool})
        write_manifest(self.manifest_path, document)
        with self.assertRaises(engine.SafetyError):
            engine.Engine(self.manifest_path, "relative", self.state, git=transport)
        with self.assertRaises(engine.SafetyError):
            engine.Engine(self.manifest_path, self.root, self.root / "state", git=transport)
        with self.assertRaises(engine.SafetyError):
            engine.Engine(self.manifest_path, Path(self.root.anchor), self.state, git=transport)
        with mock.patch.object(engine.Path, "home", return_value=self.root):
            with self.assertRaises(engine.SafetyError):
                engine.Engine(self.manifest_path, self.root, self.state, git=transport)

    def test_no_legacy_or_shell_execution_surface_exists(self) -> None:
        source = (HERE / "engine.py").read_text(encoding="utf-8")
        self.assertNotIn("bootstrap.sh", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("url.insteadOf", source)
        parser = engine._parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["apply", "--manifest", "x"])

    def test_timeout_strict_ssh_reserved_report_and_lock_symlink(self) -> None:
        runner = engine.GitRunner()
        environment = runner._environment()
        self.assertIn("-F /dev/null", environment["GIT_SSH_COMMAND"])
        self.assertIn("StrictHostKeyChecking=yes", environment["GIT_SSH_COMMAND"])
        with mock.patch.object(
            engine.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["git"], 1),
        ):
            with self.assertRaises(engine.GitError):
                runner._run(["--version"], operation="timeout fixture", timeout=1)

        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        write_manifest(self.manifest_path, document)
        with self.assertRaises(engine.SafetyError):
            engine.Engine(
                self.manifest_path,
                self.root,
                self.state,
                self.state / "journal.json",
                git=FixtureGit({remote: tool}),
            )

        self.state.mkdir(mode=0o700)
        unrelated = self.base / "unrelated-lock-target"
        unrelated.write_text("preserve\n", encoding="utf-8")
        (self.state / "operation.lock").symlink_to(unrelated)
        subject = engine.Engine(
            self.manifest_path,
            self.root,
            self.state,
            git=FixtureGit({remote: tool}),
            platform_probe=lambda: ("Darwin", "arm64"),
        )
        with self.assertRaises(engine.SafetyError):
            subject.apply()
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "preserve\n")

    def test_missing_private_state_parent_chain_is_created(self) -> None:
        tool, revision = make_source(self.sources, "tool")
        document = self.one_active_manifest(revision)
        remote = engine.canonical_remote("KleinPerkins/tool")
        write_manifest(self.manifest_path, document)
        nested_state = self.base / "missing" / "xdg" / "state" / "portability"
        subject = engine.Engine(
            self.manifest_path,
            self.root,
            nested_state,
            git=FixtureGit({remote: tool}),
            platform_probe=lambda: ("Darwin", "arm64"),
        )
        subject.apply()
        self.assertTrue(nested_state.is_dir())
        self.assertEqual(stat.S_IMODE(nested_state.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
