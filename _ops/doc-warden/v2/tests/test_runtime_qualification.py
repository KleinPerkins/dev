import json
import shutil
import tempfile
import unittest
from pathlib import Path

from doc_warden.runtime_qualification import (
    LOCK_DIGEST,
    RECORD,
    RUNTIME,
    check,
    derive_dependency_licenses,
    refresh,
    render_record,
)
from fixture_factory import ROOT

QUALIFIED_AT = "2026-10-20T12:00:00Z"
TOOLCHAIN = {"node": "v26.4.0", "npm": "11.17.0", "platform": "darwin"}
LOCK_FIELDS = {"dependency_licenses", "digests", "qualified_at", "toolchain"}


def runtime_repository(root: Path) -> Path:
    # All positive qualification evidence is explicitly synthetic and disposable.
    from test_live_install import live_install_repository
    from doc_warden.runtime_qualification import _observed_digests
    repo, qualification = live_install_repository(root)
    shutil.copytree(ROOT / RUNTIME, repo / RUNTIME, dirs_exist_ok=True)
    value = json.loads(qualification.read_bytes())
    value["digests"] = _observed_digests(repo / RUNTIME)
    value["dependency_licenses"] = derive_dependency_licenses(json.loads((repo / RUNTIME / "package-lock.json").read_bytes()))
    qualification.write_bytes(render_record(value))
    return repo



def bump_lock(repo: Path, name: str = "proxy-addr", **overrides) -> str:
    path = repo / RUNTIME / "package-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    entry = lock["packages"][f"node_modules/{name}"]
    previous = entry["version"]
    entry.update(
        {
            "version": "99.0.0",
            "resolved": f"https://registry.npmjs.org/{name}/-/{name}-99.0.0.tgz",
            "integrity": "sha512-" + "A" * 86 + "==",
            **overrides,
        }
    )
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return previous


def record(repo: Path) -> dict:
    return json.loads((repo / RECORD).read_text(encoding="utf-8"))


class RuntimeQualificationTests(unittest.TestCase):
    def test_successor_does_not_claim_omitted_private_runtime_qualification(self):
        self.assertFalse((ROOT / RECORD).exists())
        self.assertTrue(check(ROOT))

    def test_synthetic_record_is_bound_to_runtime_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(check(runtime_repository(Path(temporary))), [])

    def test_inventory_and_rendering_reproduce_the_committed_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = runtime_repository(Path(temporary))
            raw = (repo / RECORD).read_bytes()
            lock = json.loads((repo / RUNTIME / "package-lock.json").read_bytes())
        self.assertEqual(
            derive_dependency_licenses(lock), json.loads(raw)["dependency_licenses"]
        )
        self.assertEqual(render_record(json.loads(raw)), raw)

    def test_unqualified_lock_bump_fails_until_refreshed(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = runtime_repository(Path(temporary))
            before = record(repo)
            previous = bump_lock(repo)

            problems = "\n".join(check(repo))
            self.assertIn(f"{RUNTIME}/package-lock.json changed since qualification", problems)
            self.assertIn(f"proxy-addr {previous} -> 99.0.0", problems)
            self.assertIn("runtime_qualification_digest_mismatch", problems)

            delta = refresh(repo, qualified_at=QUALIFIED_AT, toolchain=TOOLCHAIN)
            self.assertEqual(delta, [f"proxy-addr {previous} -> 99.0.0"])
            self.assertEqual(check(repo), [])
            after = record(repo)
            self.assertEqual(after["qualified_at"], QUALIFIED_AT)
            self.assertNotEqual(after["digests"][LOCK_DIGEST], before["digests"][LOCK_DIGEST])
            self.assertEqual(
                {k: v for k, v in after["digests"].items() if k != LOCK_DIGEST},
                {k: v for k, v in before["digests"].items() if k != LOCK_DIGEST},
            )
            self.assertEqual(
                {k: v for k, v in after.items() if k not in LOCK_FIELDS},
                {k: v for k, v in before.items() if k not in LOCK_FIELDS},
            )
            self.assertEqual(render_record(after), (repo / RECORD).read_bytes())

    def test_refresh_refuses_changes_beyond_the_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = runtime_repository(Path(temporary))
            bump_lock(repo)
            installer = repo / RUNTIME / "install.sh"
            installer.write_text(installer.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            original = (repo / RECORD).read_bytes()
            self.assertIn(f"{RUNTIME}/install.sh changed since qualification", "\n".join(check(repo)))
            with self.assertRaisesRegex(ValueError, "cannot cover changes to .*install.sh"):
                refresh(repo, qualified_at=QUALIFIED_AT, toolchain=TOOLCHAIN)
            self.assertEqual((repo / RECORD).read_bytes(), original)

    def test_refresh_refuses_unreviewable_package_changes(self):
        cases = {
            "declares install scripts": {"hasInstallScript": True},
            "does not resolve from": {"resolved": "https://example.invalid/proxy-addr.tgz"},
        }
        for message, overrides in cases.items():
            with self.subTest(message), tempfile.TemporaryDirectory() as temporary:
                repo = runtime_repository(Path(temporary))
                bump_lock(repo, **overrides)
                original = (repo / RECORD).read_bytes()
                with self.assertRaisesRegex(ValueError, message):
                    refresh(repo, qualified_at=QUALIFIED_AT, toolchain=TOOLCHAIN)
                self.assertEqual((repo / RECORD).read_bytes(), original)

    def test_refresh_refuses_when_nothing_changed(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = runtime_repository(Path(temporary))
            with self.assertRaisesRegex(ValueError, "nothing to re-qualify"):
                refresh(repo, qualified_at=QUALIFIED_AT, toolchain=TOOLCHAIN)

    def test_inventory_requires_license_and_integrity(self):
        lock = json.loads((ROOT / RUNTIME / "package-lock.json").read_bytes())
        del lock["packages"]["node_modules/proxy-addr"]["license"]
        with self.assertRaisesRegex(ValueError, "node_modules/proxy-addr"):
            derive_dependency_licenses(lock)


if __name__ == "__main__":
    unittest.main()
