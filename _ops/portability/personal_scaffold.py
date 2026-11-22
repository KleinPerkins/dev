"""Select the destination of a new personal product and bind its replay journal."""
import fcntl
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
from personal_scope import absolute_directory, child_directory, operator_home

LAYOUT = ("personal", "src", "KleinPerkins")


def target(name, fixture, resume, *, acquire=False):
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
    identity = [str(checkout), "fixture" if fixture else "personal", repository_id]
    for path in (checkout, gitdir):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("expected an operator-owned checkout")
        identity.extend((info.st_dev, info.st_ino))
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


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
