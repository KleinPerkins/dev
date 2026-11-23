"""Select the destination of a new personal product and bind its replay journal."""
import fcntl
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from personal_scope import absolute_directory, child_directory, operator_home, read_regular

LAYOUT = ("personal", "src", "KleinPerkins")


def check_product_name(name):
    if (not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}", name)
            or name.endswith(".") or name.lower().endswith(".git")
            or name.casefold() in {"repo-platform", "dev-main-sync"}):
        raise ValueError("expected a new personal product name")
    # Direct calls to the acquisition helper must honor Dev's excluded and enrolled names.
    policy = Path(__file__).resolve().parents[1] / "baseline/delivery-policy.py"
    disposition = subprocess.check_output(
        [sys.executable, "-I", "-B", str(policy), "classify", f"KleinPerkins/{name}"],
        text=True,
    ).strip()
    if disposition != "unenrolled":
        raise ValueError("Dev policy allows personal creation only for an unenrolled product")


def owner_location(fixture):
    # Resolve only the system temp alias. Never follow a fixture child link.
    if fixture:
        bases = [Path("/tmp")]
        if sys.platform == "darwin":
            bases.append(Path(subprocess.check_output(
                ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], text=True).strip()))
        supplied = Path(fixture)
        for base in bases:
            physical = base.resolve(strict=True)
            for prefix in (base, physical):
                if supplied != prefix and supplied.is_relative_to(prefix) and ".." not in supplied.parts:
                    root = physical / supplied.relative_to(prefix)
                    break
            else:
                continue
            break
        else:
            raise ValueError("expected a disposable child of the system temporary directory")
        parts = LAYOUT
    else:
        root = operator_home()
        parts = ("dev", *LAYOUT)
    return root, parts


def target(name, fixture, resume, *, acquire=False):
    check_product_name(name)
    root, parts = owner_location(fixture)
    if any(key in os.environ for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
            "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE", "GIT_QUARANTINE_PATH")):
        raise ValueError("redirected Git storage")
    fd = absolute_directory(root)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise ValueError("operator-owned root required")
        owner = child_directory(fd, parts)
        try:
            if acquire:
                if not os.path.samestat(os.stat("."), os.fstat(owner)):
                    raise ValueError("selected owner directory changed")
                if not resume:
                    os.mkdir(name, mode=0o700, dir_fd=owner)
                selected = child_directory(owner, (name,))
                try:
                    if not resume and os.listdir(selected):
                        raise ValueError("new checkout is no longer empty")
                    return node_id(os.fstat(selected))
                finally:
                    os.close(selected)
            if resume:
                checkout = child_directory(owner, (name, ".git"))
                os.close(checkout)
            else:
                try:
                    os.stat(name, dir_fd=owner, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError("target already occupied")
        finally:
            os.close(owner)
    finally:
        os.close(fd)
    return root.joinpath(*parts, name)


def node_id(info):
    return f"{info.st_dev}:{info.st_ino}"


def check_checkout(path, expected, *, lock=False):
    selected = absolute_directory(path)
    try:
        info = os.fstat(selected)
        if (node_id(info) != expected or not os.path.samestat(info, os.fstat(9))
                or not os.path.samestat(info, os.stat("."))):
            raise ValueError("selected checkout location changed")
        if lock:
            fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(selected)


def binding(checkout, fixture, repository_id):
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    if checkout != Path.cwd() or not os.path.samestat(os.fstat(9), checkout.lstat()):
        raise ValueError("pinned checkout location changed")
    gitdir = checkout / ".git"
    if (git("rev-parse", "--show-toplevel") != str(checkout)
            or git("rev-parse", "--absolute-git-dir") != str(gitdir)
            or git("rev-parse", "--path-format=absolute", "--git-common-dir") != str(gitdir)
            or git("rev-parse", "--path-format=absolute", "--git-path", "hooks") != str(gitdir / "hooks")
            or git("symbolic-ref", "--short", "HEAD") != "main"):
        raise ValueError("expected a primary main checkout with repository-local hooks")
    return checkout_binding(checkout, fixture, repository_id, checkout.lstat(), gitdir.lstat())


def checkout_binding(checkout, fixture, repository_id, checkout_info, git_info):
    """Identity recorded when the personal scaffold first acquires the checkout."""
    identity = [str(checkout), "fixture" if fixture else "personal", repository_id]
    for info in (checkout_info, git_info):
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("expected an operator-owned checkout")
        identity.extend((info.st_dev, info.st_ino))
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


class ScaffoldMismatch(ValueError):
    """A selected checkout no longer matches the creator’s recorded identity."""


@contextmanager
def open_created_checkout(name, fixture=None, supplied_id=None):
    """Keep the checkout pinned and compare its creator and Git records again on exit."""
    check_product_name(name)
    if fixture == "" or (supplied_id is not None and
            (not fixture or not re.fullmatch(r"[0-9]+", supplied_id) or not supplied_id.strip("0"))):
        raise ScaffoldMismatch("an explicit fixture repository ID requires a positive ID and --fixture-root")
    root, parts = owner_location(fixture)
    checkout = root.joinpath(*parts, name)
    with ExitStack() as stack:
        def hold(fd):
            stack.callback(os.close, fd)
            return fd

        base = hold(absolute_directory(root))
        if os.fstat(base).st_uid != os.getuid():
            raise ScaffoldMismatch("operator-owned root required")
        selected = hold(child_directory(base, (*parts, name)))
        fcntl.flock(selected, fcntl.LOCK_SH | fcntl.LOCK_NB)
        git = hold(child_directory(selected, (".git",)))
        state_name = "doc-warden-new-repo.json"
        saved = read_regular(git, state_name)
        state = json.loads(saved)
        slug = "KleinPerkins/" + name
        if (not isinstance(state, dict) or state.get("schema") != "dev-new-repo-operation/v2"
                or state.get("repository") != slug or state.get("test_sharding_required") is not True
                or "github_repository_id" not in state):
            raise ScaffoldMismatch("the creation record does not identify the selected personal product")
        recorded_id = state.get("github_repository_id")
        if recorded_id is not None and (type(recorded_id) is not int or recorded_id <= 0):
            raise ScaffoldMismatch("the creation record has an invalid repository ID")
        # The creator binds the exact fixture argument before a provider ID is recorded.
        # A live checkout always binds the empty fixture argument.
        fixture_id = supplied_id or ""
        if fixture and recorded_id is not None:
            if supplied_id is not None and supplied_id.lstrip("0") != str(recorded_id):
                raise ScaffoldMismatch("the supplied fixture ID differs from the recorded repository ID")
            fixture_id = supplied_id or str(recorded_id)
        expected = checkout_binding(checkout, fixture, fixture_id, os.fstat(selected), os.fstat(git))
        if state.get("personal_checkout") != expected:
            if fixture and supplied_id is None:
                raise ScaffoldMismatch("creation binding does not match. Supply the original --fixture-repository-id if one was used")
            raise ScaffoldMismatch("the creation record does not match this checkout and Git directory")
        config = read_regular(git, "config")
        origin = subprocess.run(
            ["/usr/bin/git", "config", "--no-includes", "--file", "-", "--null", "--get-all", "remote.origin.url"],
            input=config, capture_output=True, timeout=5, cwd="/",
            env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        )
        if origin.returncode or origin.stdout != ("git@github.com:" + slug + ".git\0").encode():
            raise ScaffoldMismatch("the selected Git config must contain the single original scaffold origin")
        yield checkout, selected, saved, recorded_id
        current = hold(absolute_directory(checkout))
        current_git = hold(child_directory(current, (".git",)))
        if (not os.path.samestat(os.fstat(current), os.fstat(selected))
                or not os.path.samestat(os.fstat(current_git), os.fstat(git))
                or read_regular(current_git, state_name) != saved or read_regular(current_git, "config") != config):
            raise ScaffoldMismatch("the selected checkout changed during inspection")


def stage(checkout, operation, phase):
    # Share the owner's baseline inventory and the applied transaction's exact write set.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doc-warden/v2"))
    from doc_warden.scaffold import REQUIRED_BASELINE

    state = Path("_ops/doc-warden/state/v2")
    receipt_path = state / "receipts" / f"{uuid.UUID(operation)}.json"
    receipt = json.loads((checkout / receipt_path).read_bytes())
    if receipt["operation_id"] != operation or phase not in {"initial", "remote"}:
        raise ValueError("scaffold operation identity changed")
    event_path = state / "events" / f"{uuid.UUID(receipt['event_id'])}.json"
    owned = {str(receipt_path), str(event_path), *receipt["postimages"]}
    if phase == "initial":
        owned.update((*REQUIRED_BASELINE, ".github/test-sharding-required.json", ".github/test-shards.json"))
    git = ["git", "-C", str(checkout)]
    paths = subprocess.check_output([*git, "ls-files", "-z", "-m", "-o", "--exclude-standard"])
    paths += subprocess.check_output([*git, "diff", "--cached", "--name-only", "--no-renames", "-z"])
    if {os.fsdecode(p) for p in paths.split(b"\0") if p} - owned:
        raise ValueError("checkout contains unrelated work; preserve it before resuming")
    for path, expected in receipt["postimages"].items():
        location = checkout / path
        if (not location.is_file() or location.is_symlink()
                or "sha256:" + hashlib.sha256(location.read_bytes()).hexdigest() != expected):
            raise ValueError("scaffold transaction content changed")
    subprocess.run([*git, "--literal-pathspecs", "add", "--", *sorted(owned)], check=True)


if __name__ == "__main__":
    action, name, fixture, option = sys.argv[1:]
    try:
        if action in {"target", "acquire"}:
            print(target(name, fixture, option == "1", acquire=action == "acquire"))
        elif action in {"check", "lock"}:
            check_checkout(Path(name), fixture, lock=action == "lock")
        elif action == "binding":
            print(binding(Path(name), fixture, option))
        elif action == "stage":
            stage(Path(name), fixture, option)
        else:
            raise ValueError("unknown personal scaffold action")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"dev-new-repo: {error}")
