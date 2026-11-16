from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from doc_warden.canonical import atomic_write, canonical_json


ROOT = Path(__file__).resolve().parents[4]


@dataclass
class FixtureContext:
    temporary: tempfile.TemporaryDirectory[str]
    repo: Path
    repository_key: str

    def id_for(self, label: str) -> str:
        return str(uuid.uuid5(uuid.UUID(self.repository_key), label))

    def cleanup(self) -> None:
        self.temporary.cleanup()


class FixtureFactory:
    @staticmethod
    def create(scenario: str = "configured") -> FixtureContext:
        temporary = tempfile.TemporaryDirectory(prefix=f"doc-warden-v2-{scenario}-")
        repo = Path(temporary.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "fixture@example.invalid"], check=True
        )
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        for name in ("gsd-core-pin.json", "runtime-interface.v1.json"):
            source = ROOT / "_ops/doc-warden/runtime/gsd-core" / name
            destination = repo / "_ops/doc-warden/runtime/gsd-core" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        subprocess.run(["git", "-C", str(repo), "add", "README.md", "_ops"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"doc-warden-v2-fixture:{scenario}"))
        if scenario != "unconfigured":
            config = {
                "schema": "doc-warden/config/v2",
                "schema_version": 2,
                "repository_key": key,
                "github_repository_id": None,
                "enabled": True,
                "dynamic_defaults": {"rigor": "auto"},
                "legacy_roots": [],
                "gsd_pin_digest": "sha256:" + "1" * 64,
                "gsd_interface_digest": "sha256:" + "2" * 64,
                "maintenance": {"status": "current", "last_checked_revision": None},
            }
            atomic_write(repo, ".planning/doc-warden.json", canonical_json(config))
            subprocess.run(["git", "-C", str(repo), "add", ".planning/doc-warden.json"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "configure"], check=True)
        return FixtureContext(temporary=temporary, repo=repo, repository_key=key)
