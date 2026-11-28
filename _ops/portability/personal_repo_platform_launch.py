"""Launch a sealed repo-platform release through an installed Dev owner profile."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import PortabilityError
from personal_package_files import physical_path, seal_directories, verified_executable_copy, verify_skill_tree

_RUNTIME_IMPORTS = threading.RLock()


@contextmanager
def _runtime_imports(package):
    """Limit the selected release and its modules to one launcher invocation."""
    path = str(package)
    with _RUNTIME_IMPORTS:
        previous = {name: module for name, module in tuple(sys.modules.items())
                    if name.partition(".")[0] == "repo_platform"}
        for name in previous:
            del sys.modules[name]
        sys.path.insert(0, path)
        try:
            yield
        finally:
            for name in tuple(sys.modules):
                if name.partition(".")[0] == "repo_platform":
                    del sys.modules[name]
            sys.modules.update(previous)
            sys.path.remove(path)


@dataclass(frozen=True)
class RepoPlatformRelease:
    """Exact immutable package installed by the Dev profile owner."""

    revision: str
    files: dict[str, tuple[str, int, str]]
    previous: "RepoPlatformRelease | None" = None

    def directory(self, home):
        if not re.fullmatch("[0-9a-f]{40}", self.revision):
            raise ValueError("repo-platform requires an exact owner-pinned release revision")
        if not self.files or any(not re.fullmatch(r"repo_platform/[a-z_][a-z_0-9]*\.py", relative)
                                or mode != "100644" for relative, (mode, _, _) in self.files.items()):
            raise ValueError("repo-platform requires a closed runtime source manifest")
        return home / ".local/share/personal-portability/releases" / f"repo-platform-{self.revision}"

    def _runtime_files(self):
        return {relative.removeprefix("repo_platform/"): item for relative, item in self.files.items()}

    def _verify(self, runtime):
        physical_path(runtime.parent)
        if {path.name for path in runtime.parent.iterdir()} != {"repo_platform"}:
            raise ValueError("unexpected entries in the pinned repo-platform release")
        verify_skill_tree(runtime, self._runtime_files())

    def open(self, home):
        package = self.directory(home)
        self._verify(package / "repo_platform")
        return package

    def prepare(self, home, *, get=None):
        from personal_core import prepare_release, read_url

        get = read_url if get is None else get
        package = self.directory(home)
        source = f"https://raw.githubusercontent.com/KleinPerkins/repo-platform/{self.revision}"

        def populate(runtime):
            for relative, (_, length, expected) in self.files.items():
                payload = get(f"{source}/{relative}", length)
                if len(payload) != length or sha256(payload).hexdigest() != expected:
                    raise ValueError(f"downloaded repo-platform bytes differ for {relative}")
                target = runtime / relative.removeprefix("repo_platform/")
                target.write_bytes(payload)
                target.chmod(0o400)
            seal_directories(runtime, self._runtime_files())

        prepare_release(package / "repo_platform", populate, self._verify)
        return self.open(home)


@dataclass(frozen=True)
class CodexClient:
    """The executable selected and measured by the installed host owner."""

    binary: Path
    length: int
    digest: str
    bundle_files: dict[str, tuple[int, str]] | None = None

    @contextmanager
    def connect(self, home, codex_home, private_working_directory):
        from native_checkout_project import NativeProjectReader

        environment = {"HOME": str(home), "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                       "LANG": "en_US.UTF-8"}
        with (verified_executable_copy(self.binary, self.length, self.digest, bundle_files=self.bundle_files) as binary,
              subprocess.Popen(
                  [str(binary), "-c", "features.plugins=false", "app-server", "--stdio"],
                  cwd=private_working_directory, env=environment, stdin=subprocess.PIPE,
                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
              ) as server):
            try:
                yield NativeProjectReader(server.stdout.fileno(), server.stdin.fileno())
            finally:
                try:
                    server.stdin.close()
                finally:
                    try:
                        server.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(server.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        server.wait(timeout=2)


def _executable_pin(client, description):
    if (not isinstance(client, dict) or set(client) != {"binary", "length", "sha256"}
            or not isinstance(client["binary"], str) or not Path(client["binary"]).is_absolute()
            or type(client["length"]) is not int or client["length"] <= 0
            or not isinstance(client["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", client["sha256"])):
        raise ValueError(f"invalid Dev repo-platform {description} pin")
    return Path(client["binary"]), client["length"], client["sha256"]


def _codex_client_pin(client):
    if not isinstance(client, dict):
        raise ValueError("invalid Dev repo-platform Codex client pin")
    executable = dict(client)
    bundle = executable.pop("bundle_files", None)
    binary, length, digest = _executable_pin(executable, "Codex client")
    bundled = (binary.parent.name == "MacOS" and binary.parents[1].name == "Contents"
               and binary.parents[2].suffix == ".app")
    if bundle is None and not bundled:
        return CodexClient(binary, length, digest)
    expected = {"Contents/Info.plist", "Contents/CodeResources", "Contents/_CodeSignature/CodeResources",
                "Contents/embedded.provisionprofile"}
    if not bundled or not isinstance(bundle, dict) or set(bundle) != expected:
        raise ValueError("invalid Dev repo-platform Codex bundle pin")
    for row in bundle.values():
        if (not isinstance(row, list) or len(row) != 2 or type(row[0]) is not int or row[0] <= 0
                or not isinstance(row[1], str) or not re.fullmatch(r"[0-9a-f]{64}", row[1])):
            raise ValueError("invalid Dev repo-platform Codex bundle file pin")
    return CodexClient(binary, length, digest, {name: tuple(row) for name, row in bundle.items()})


def _runtime_release(revision, files, previous=None):
    if (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not isinstance(files, dict)
            or not {"repo_platform/command.py", "repo_platform/host.py", "repo_platform/recovery.py"} <= files.keys()):
        raise ValueError("invalid Dev repo-platform release pin")
    for relative, entry in files.items():
        if (not re.fullmatch(r"repo_platform/[a-z_][a-z_0-9]*\.py", relative)
                or not isinstance(entry, list) or len(entry) != 3 or entry[0] != "100644"
                or type(entry[1]) is not int or entry[1] <= 0 or not isinstance(entry[2], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry[2])):
            raise ValueError("invalid Dev repo-platform runtime file pin")
    return RepoPlatformRelease(revision, {name: tuple(row) for name, row in files.items()}, previous)


def profile_release():
    """Read only the release and native client pinned by the owning Dev source."""
    path = Path(__file__).with_name("personal-repo-platform-runtime.json")
    try:
        pin = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    fields = {"schema", "repository_id", "revision", "files", "codex"}
    if (not isinstance(pin, dict) or not fields <= pin.keys() <= fields | {"previous"}
            or pin["schema"] != "dev-repo-platform-runtime/v1" or pin["repository_id"] != 1472074383):
        raise ValueError("invalid Dev repo-platform release pin")
    previous = None
    if "previous" in pin:
        prior = pin["previous"]
        if (not isinstance(prior, dict) or set(prior) != {"revision", "files"}
                or prior["revision"] == pin["revision"]):
            raise ValueError("invalid Dev repo-platform predecessor pin")
        previous = _runtime_release(prior["revision"], prior["files"])
    release = _runtime_release(pin["revision"], pin["files"], previous)
    codex = _codex_client_pin(pin["codex"])
    return release, codex


def _admitted_linked_primary(owner, project_id, checkout, thread_id, deadline):
    from lib.contracts import INPUT_MAX, json_load
    from native_checkout_project import selection_digest
    from personal_checkout_inventory import Refused, lexical

    scope = owner.inventory.current_owner_evidence(owner.operation, deadline=min(deadline, time.monotonic() + 2))
    bound = [binding for binding in scope.bindings if binding.checkout == checkout and binding.linked_metadata()]
    if scope.record is None or len(bound) != 1 or not bound[0].common_directory.endswith("/.git"):
        raise Refused("the Dev owner has not bound the linked checkout to an in-place primary")
    candidates = json_load(scope.record, INPUT_MAX)["observations"]
    selected = selection_digest(project_id, checkout, thread_id)
    if sum(row["checkout"] == checkout and row["native_selection_digest"] == selected for row in candidates) != 1:
        raise Refused("the selected native thread differs from the committed Dev evidence")
    return lexical(bound[0].common_directory.removesuffix("/.git"))


def _run_owner(argv, *, home, codex_home, release, observe, read_hosting, read_delivery,
               output=None, errors=None):
    """Open one installed owner session after verifying its profile and package."""
    from personal_core import bind_personal_index, configure_entry, repo_platform_runtime_entry

    destination = errors if errors is not None else sys.stderr
    try:
        entry = repo_platform_runtime_entry(home, codex_home, release)
        configure_entry(entry, "check")
        package = entry.release
    except (OSError, ValueError, PortabilityError) as error:
        print(f"Repo-platform could not open the installed Dev profile. {error}", file=destination)
        return 1

    with _runtime_imports(package):
        try:
            bind_personal_index(home, codex_home, reuse=True)
        except (OSError, ValueError, PortabilityError) as error:
            print(f"Repo-platform could not bind the installed Skills index. {error}", file=destination)
            return 1
        from lib.contracts import Refusal as IndexRefusal
        from personal_checkout_inventory import Refused
        from personal_repo_platform import installed_owner_root

        try:
            owner_state = installed_owner_root(home, codex_home)
        except (OSError, ValueError, PortabilityError, IndexRefusal) as error:
            print(f"Repo-platform could not open the installed owner session. {error}", file=destination)
            return 1

        spec = importlib.util.find_spec("repo_platform")
        if (spec is None or spec.submodule_search_locations is None
                or list(spec.submodule_search_locations) != [str(package / "repo_platform")]):
            print("Repo-platform could not select the pinned runtime package.", file=destination)
            return 1
        from repo_platform.command import run
        from repo_platform.host import read_owner_session

        def read_native(project_id, checkout, *, thread_id=None, deadline):
            return observe(owner, owner_state, project_id, checkout, thread_id=thread_id, deadline=deadline)

        try:
            owner = read_owner_session(owner_state, read_native=read_native, read_hosting=read_hosting,
                                       read_delivery=read_delivery)
        except Refused as error:
            print(f"Repo-platform could not open its owner session. {error}", file=destination)
            return 1
        return run(argv, owner=owner, output=output, errors=destination)


def run_cli(argv, *, home, codex_home, release, client, read_hosting, read_delivery,
            output=None, errors=None):
    """Adopt via the standalone Codex CLI catalog bound by the Dev owner."""
    def observe(owner, owner_state, project_id, checkout, *, thread_id, deadline):
        from personal_checkout_inventory import Refused
        from repo_platform.recovery import TransientNativeRead

        primary = None
        if thread_id is not None:
            primary = _admitted_linked_primary(owner, project_id, checkout, thread_id, deadline)
        try:
            with client.connect(home, codex_home, owner_state) as native:
                return native.read(project_id, checkout, thread_id=thread_id,
                                   primary_checkout=primary, deadline=deadline)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TransientNativeRead("Codex CLI could not finish the native project read.") from error
        except ValueError as error:
            raise Refused("the installed Codex CLI differs from the Dev owner binding") from error

    return _run_owner(argv, home=home, codex_home=codex_home, release=release, observe=observe,
                      read_hosting=read_hosting, read_delivery=read_delivery, output=output, errors=errors)


def run_desktop(argv, *, home, codex_home, list_projects, read_linked_thread, output=None, errors=None):
    """Adopt through live native callbacks supplied by the trusted Desktop caller."""
    destination = errors if errors is not None else sys.stderr
    try:
        if not callable(list_projects) or not callable(read_linked_thread):
            raise ValueError("the Dev owner needs a live Codex Desktop connection")
        pinned = profile_release()
        if pinned is None:
            raise ValueError("the Dev owner has not pinned a repo-platform runtime release")
        release, _ = pinned
        read_hosting, read_delivery = _owner_readers()

        def observe(_owner, _owner_state, project_id, checkout, *, thread_id, deadline):
            from repo_platform.desktop import DesktopReader

            return DesktopReader(list_projects, read_linked_thread)(
                project_id, checkout, thread_id=thread_id, deadline=deadline,
            )

        return _run_owner(argv, home=home, codex_home=codex_home, release=release, observe=observe,
                          read_hosting=read_hosting, read_delivery=read_delivery, output=output, errors=destination)
    except (OSError, ValueError, PortabilityError) as error:
        print(f"Repo-platform could not open the Dev Desktop launcher. {error}", file=destination)
        return 1


def _owner_readers():
    from github_checkout_provider import read_github_repository
    from personal_checkout_inventory import Refused

    path = Path(__file__).resolve().parents[1] / "baseline/delivery-policy.py"
    config = path.with_suffix(".json")
    raw = config.read_bytes()
    owner = runpy.run_path(str(path))
    policy = owner["load_policy"]()
    if config.read_bytes() != raw:
        raise ValueError("Dev delivery policy changed while being read")
    revision = sha256(raw).hexdigest()
    private = {row["repository_id"] for row in policy["repositories"]
               if row["disposition"] == "private-no-ci"}

    def check_policy(deadline):
        if time.monotonic() >= deadline or config.read_bytes() != raw:
            raise Refused("Dev delivery policy expired or changed during checkout adoption")

    def read_hosting(repository_id, *, deadline):
        check_policy(deadline)
        if repository_id in private:
            raise Refused("the Dev owner has not qualified private checkout adoption for this profile")
        return read_github_repository(repository_id, deadline=deadline)

    def read_delivery(hosted, *, deadline):
        from repo_platform.adoption import DeliveryClassification

        check_policy(deadline)
        name = hosted.full_name
        canonical = "KleinPerkins/dev" if name == "KleinPerkins/dev-temp" else name
        matches = [row for row in policy["repositories"] if
                   row["repository"] == canonical or row["repository_id"] == hosted.repository_id]
        if matches and (len(matches) != 1 or matches[0]["repository"] != canonical
                        or matches[0]["repository_id"] != hosted.repository_id):
            raise Refused("the observed repository identity differs from Dev's delivery policy")
        disposition = owner["classify"](name, policy)
        return DeliveryClassification(hosted.repository_id, name, disposition, revision)

    return read_hosting, read_delivery


def main():
    try:
        pinned = profile_release()
        if pinned is None:
            raise ValueError("the Dev owner has not pinned a repo-platform runtime release")
        home = Path.home()
        codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
        release, client = pinned
        read_hosting, read_delivery = _owner_readers()
        return run_cli(sys.argv[1:], home=home, codex_home=codex_home, release=release, client=client,
                       read_hosting=read_hosting, read_delivery=read_delivery)
    except (OSError, ValueError, PortabilityError) as error:
        print(f"Repo-platform could not open the Dev launcher. {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
