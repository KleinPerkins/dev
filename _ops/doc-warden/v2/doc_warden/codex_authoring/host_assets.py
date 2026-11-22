"""Qualify the source-pinned native authoring package in owner-private state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import urllib.request

from ..canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from ..gsd_plan_check import GSD_REVISION, _verified_package_files
from ..live_install import GSD_UPSTREAM_TARBALL
from ..operation_store import private_state_root
from ..runtime_host import installation_context
from ..scm import _fixture_github_cli, github_json
from .host_projection import PROJECTION_PATHS, observe_descriptors, render_descriptors
from .host_transaction import SOURCE_ENTRY, _project_identity
from .native_client import client_identity, observe_skills
from .native_runtime_stage import LOCK_DIGEST, PACKAGE_PATH, stage_runtime


SCHEMA = "doc-warden/codex-authoring-host-qualification/v1"
MAX_AGE = timedelta(hours=24)
RUNTIME = "_ops/doc-warden/runtime/gsd-core"
PACKAGE_SHA256 = "sha256:b7ed2186d397b270a52db5e9816a9fd88a240466b356b1f4a28823f93cb8fd9d"
MAX_ARCHIVE = 32 * 1024 * 1024
EMITTER = "_ops/portability/doc_warden_gsd_codex_emit.py"
OWNER_PIN_PATH = RUNTIME + "/codex-authoring-skills-pin.json"
OWNER_MODULE_PATH = "global/rules/subagent-orchestration/named_authoring.py"
SOURCE_PATHS = (
    SOURCE_ENTRY, "_ops/doc-warden/v2/doc_warden", "_ops/doc-warden/schemas/v2", RUNTIME,
    EMITTER, "_ops/portability/personal_gsd_codex_bundle.py", "_ops/portability/personal_gsd_codex_bundle.json",
    "_ops/portability/personal_gsd_codex_source.py", "_ops/portability/personal_gsd_codex_source.json",
    "_ops/portability/personal_gsd_codex_emit.cjs", "_ops/portability/personal_gsd_codex_compile.cjs",
    "_ops/portability/personal_gsd_codex_network_deny.sb", "_ops/portability/personal_git.py",
    "_ops/portability/personal_scope.py",
)


def client_environment(home: Path, *, path: str | None = None) -> dict[str, str]:
    return {"HOME": str(home), "PATH": path or os.environ.get("PATH", os.defpath),
            "CODEX_HOME": str(home / ".codex"), "LANG": "en_US.UTF-8"}


def _protected_source(root: Path, home: Path, data: Path) -> dict:
    context = installation_context(root, home, data)
    remote = github_json(
        "repos/KleinPerkins/dev/git/ref/heads/main", github_cli=_fixture_github_cli(root),
        unavailable="native_authoring_source_not_on_protected_main",
    )
    if not isinstance(remote, dict) or remote.get("object", {}).get("sha") != context["source_revision"]:
        raise ValueError("native_authoring_source_not_on_protected_main")
    return context


def _export_source(context: dict, destination: Path) -> str:
    root, revision = context["canonical_root"], context["source_revision"]
    git = ["git", "--no-replace-objects", "-C", root]
    output = subprocess.check_output(git + ["ls-tree", "-rz", revision, "--", *SOURCE_PATHS], timeout=15)
    images = {}
    for row in output.split(b"\0"):
        if not row:
            continue
        meta, relative = row.split(b"\t", 1)
        mode, kind, object_id = meta.decode("ascii").split()
        path = relative.decode()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("native_authoring_release_source_invalid")
        blob = subprocess.check_output(git + ["cat-file", "blob", object_id], timeout=10)
        executable = mode == "100755"
        target = atomic_write(destination, path, blob)
        target.chmod(0o500 if executable else 0o400)
        images[path] = {"digest": digest_ref(blob), "executable": executable}
    if not {EMITTER, SOURCE_ENTRY, OWNER_PIN_PATH}.issubset(images):
        raise ValueError("native_authoring_release_source_incomplete")
    return digest_ref(canonical_json(images))


def _release_digest(source: Path) -> str:
    if not source.is_dir() or source.resolve(strict=True) != source:
        raise ValueError("native_authoring_release_source_invalid")
    images = {}
    for path in source.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        mode = stat.S_IMODE(info.st_mode)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or mode not in (0o400, 0o500)):
            raise ValueError("native_authoring_release_source_invalid")
        images[path.relative_to(source).as_posix()] = {"digest": digest_ref(path.read_bytes()),
                                                        "executable": mode == 0o500}
    return digest_ref(canonical_json(images))


def _download(url: str, expected: str, *, limit: int) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError("native_authoring_download_redirected")
        raw = response.read(limit + 1)
    if len(raw) > limit or digest_ref(raw) != expected:
        raise ValueError("native_authoring_download_pin_changed")
    return raw


def _owner_pin(source: Path) -> dict:
    raw = contained_path(source, OWNER_PIN_PATH).read_bytes()
    pin = parse_json_object(raw)
    if (set(pin) != {"schema", "revision", "module_digest", "repository_id"}
            or pin["schema"] != "doc-warden/skills-named-authoring-pin/v1" or pin["repository_id"] != 1461925043
            or not isinstance(pin["revision"], str) or not re.fullmatch("[0-9a-f]{40}", pin["revision"])
            or not isinstance(pin["module_digest"], str)
            or not re.fullmatch("sha256:[0-9a-f]{64}", pin["module_digest"])):
        raise ValueError("native_authoring_owner_pin_invalid")
    return pin


def _bundle_command(source: Path, python: Path, environment: dict, *args: str, archive: bytes | None = None) -> dict:
    completed = subprocess.run(
        [str(python), "-I", "-B", str(contained_path(source, EMITTER)), *args],
        env=environment, input=archive, capture_output=True, timeout=90, check=False,
    )
    if completed.returncode or len(completed.stdout) > 128 * 1024:
        raise ValueError("native_authoring_bundle_unqualified")
    return parse_json_object(completed.stdout)


def _target_path(state: Path, project: Path) -> Path:
    project_digest = digest_ref(str(project).encode()).removeprefix("sha256:")
    return contained_path(state, f"runtime/codex/qualifications/{project_digest}.json")


def _tool_path(bindings: dict, name: str) -> Path:
    record = bindings["toolchain"][name]
    path = Path(record["path"])
    if path.resolve(strict=True) != path or digest_ref(path.read_bytes()) != record["digest"]:
        raise ValueError("native_authoring_toolchain_changed")
    return path


def verify_assets(binding: dict) -> None:
    if binding.get("schema") != SCHEMA or binding.get("host_digest") != digest_ref(socket.gethostname().encode()):
        raise ValueError("native_authoring_qualification_destination_changed")
    source = Path(binding["source_root"])
    home = Path(binding["home"])
    environment = client_environment(home)
    for name in ("node", "npm", "python3"):
        _tool_path(binding, name)
    if _release_digest(source) != binding["source_digest"] or _owner_pin(source) != binding["owner_pin"]:
        raise ValueError("native_authoring_release_source_changed")
    client = client_identity(Path(binding["client"]["binary"]), cwd=source, environment=environment)
    if client != binding["client"]:
        raise ValueError("native_authoring_client_changed")
    owner = contained_path(source.parent, "named_authoring.py")
    if digest_ref(owner.read_bytes()) != binding["owner_pin"]["module_digest"]:
        raise ValueError("native_authoring_owner_module_changed")
    locked = contained_path(source.parent, "locked/" + PACKAGE_PATH).parent
    if digest_ref(canonical_json(_verified_package_files(locked))) != binding["locked_package_digest"]:
        raise ValueError("native_authoring_locked_package_changed")
    bundle = source.parent / "emitted/bundle"
    readback = _bundle_command(source, _tool_path(binding, "python3"), environment, "readback", "--bundle", str(bundle))
    if readback != {key: binding["bundle"][key] for key in ("bundle_digest", "bundle_files")}:
        raise ValueError("native_authoring_bundle_changed")


def _remove_stage(root: Path) -> None:
    # Emission seals its own files. Create no recursive cleanup authority beyond
    # the newly created, unique directory that failed qualification.
    for path in (root, *(path for path in root.rglob("*") if not path.is_symlink())):
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))
    shutil.rmtree(root)


def qualify_host(authority: Path, project: Path, *, home: Path, data: Path, client: Path) -> dict:
    authority, project, home, data = (part.expanduser().resolve() for part in (authority, project, home, data))
    project_identity = _project_identity(project)
    context = _protected_source(authority, home, data)
    toolchain = context["toolchain"]["executables"]
    environment = client_environment(home)
    client_record = client_identity(client, cwd=project, environment=environment)
    state = private_state_root()
    assets = contained_path(state, "runtime/codex/releases/.keep").parent
    if any(re.fullmatch(r"[A-Za-z0-9._-]+", part) is None for part in assets.parts[1:]):
        raise ValueError("native_authoring_bundle_root_invalid")
    assets.mkdir(parents=True, mode=0o700, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=context["source_revision"] + "-", dir=assets))
    source = stage / "source"
    source.mkdir(mode=0o700)
    published = False
    try:
        source_digest = _export_source(context, source)
        pin = _owner_pin(source)
        owner_url = f"https://raw.githubusercontent.com/KleinPerkins/skills/{pin['revision']}/{OWNER_MODULE_PATH}"
        atomic_write(stage, "named_authoring.py", _download(owner_url, pin["module_digest"], limit=128 * 1024))
        archive = _download(GSD_UPSTREAM_TARBALL, PACKAGE_SHA256, limit=MAX_ARCHIVE)
        node, npm, python = (Path(toolchain[name]["path"]) for name in ("node", "npm", "python3"))
        locked = stage / "locked"
        emitted = stage / "emitted"
        locked.mkdir(mode=0o700)
        emitted.mkdir(mode=0o700)
        runtime = stage_runtime(
            source=source / RUNTIME, staging=locked, node=node, npm=npm,
            tool_digests={name: toolchain[name]["digest"] for name in ("node", "npm")},
        )
        if runtime.lock_digest != LOCK_DIGEST or runtime.source_revision != GSD_REVISION:
            raise ValueError("native_authoring_locked_package_changed")
        bundle = _bundle_command(source, python, environment, "emit", "--node", str(node),
                                 "--operation", str(emitted), archive=archive)
        with tempfile.TemporaryDirectory(prefix="doc-warden-codex-discovery-") as disposable:
            fixture_root = Path(disposable).resolve()
            fixture, fixture_home = fixture_root / "project", fixture_root / "home"
            fixture.mkdir()
            fixture_home.mkdir()
            (fixture_home / ".codex").mkdir(mode=0o700)
            subprocess.run(["git", "init", "-q", str(fixture)], timeout=10, check=True)
            for relative, content in render_descriptors(source / SOURCE_ENTRY).items():
                atomic_write(fixture, relative, content)
            discovery = observe_skills(
                fixture, client=client_record, environment=client_environment(fixture_home),
            )
            if set(discovery.values()) != set(observe_descriptors(fixture).values()) or len(discovery) != len(PROJECTION_PATHS):
                raise ValueError("native_authoring_discovery_incomplete")
        qualification = {
            "schema": SCHEMA, "source_revision": context["source_revision"], "source_root": str(source),
            "source_digest": source_digest, "authority_root": str(authority), "project_identity": project_identity,
            "home": str(home), "data_home": str(data), "host_digest": context["host_digest"],
            "toolchain": toolchain, "client": client_record, "owner_pin": pin, "bundle": bundle,
            "locked_package_digest": digest_ref(canonical_json(runtime.installed_files)),
            "qualified_at": datetime.now(timezone.utc).isoformat(),
        }
        verify_assets(qualification)
        if _protected_source(authority, home, data) != context or _project_identity(project) != project_identity:
            raise ValueError("native_authoring_qualification_destination_changed")
        path = _target_path(state, project)
        raw = canonical_json(qualification)
        atomic_write(state, path.relative_to(state).as_posix(), raw)
        published = True
        return {
            "schema": SCHEMA, "status": "qualified", "target": "codex", "project": str(project),
            "source_revision": context["source_revision"], "qualification_digest": digest_ref(raw),
            "skills": sorted(discovery), "runtime_revision": GSD_REVISION,
        }
    finally:
        if not published:
            _remove_stage(stage)


def read_qualification(authority: Path, project: Path, *, home: Path, data: Path) -> tuple[dict, dict]:
    authority, project, home, data = (part.expanduser().resolve() for part in (authority, project, home, data))
    path = _target_path(private_state_root(), project)
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("native_authoring_qualification_required")
    raw = path.read_bytes()
    binding = parse_json_object(raw)
    context = _protected_source(authority, home, data)
    timestamp = datetime.fromisoformat(binding["qualified_at"])
    if (raw != canonical_json(binding) or timestamp.tzinfo is None
            or not timedelta() <= datetime.now(timezone.utc) - timestamp <= MAX_AGE
            or binding["source_revision"] != context["source_revision"]
            or binding["authority_root"] != str(authority) or binding["project_identity"] != _project_identity(project)
            or binding["home"] != str(home) or binding["data_home"] != str(data)
            or binding["toolchain"] != context["toolchain"]["executables"]):
        raise ValueError("native_authoring_qualification_changed")
    verify_assets(binding)
    return context, binding
