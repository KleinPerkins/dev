#!/usr/bin/env python3
"""Publish dev-owned ShadowSync policy data without discovering any repositories.

Only the CLI derives account identity. Internal functions accept explicit fixture
dependencies; there is no command-line or environment override for home or pins.
AWA owns lexical matching. This producer projects the documented host YAML subset
and binds the original bytes; it neither classifies candidates nor imports AWA.
"""
from __future__ import annotations

import argparse
import ast
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import sys

MAX_FILE = 262144
POLICY = "dev/_ops/policy/worktree-policy.yml"
OVERLAY = "dev/_ops/policy/shadow-sync-host-overlay.json"
DISPATCHER = "dev/_ops/hooks/pre-commit-dispatcher"
POINTER = ".local/share/awa/release-pointer.json"
RUNTIME = ".local/share/awa/current"
MODULE = RUNTIME + "/kernel/lib/awa_policy.py"
PIN_SOURCE = "dev/_ops/bin/check-awa-release-binding.py"
DESTINATION = "Library/Application Support/ShadowSync"
BINDING = DESTINATION + "/host-policy-binding.json"
HEX64 = r"[0-9a-f]{64}"


class Refusal(ValueError):
    """No publication is authorized for these inputs."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decoded(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refusal("non-finite JSON")))
    except (ValueError, UnicodeError) as error:
        raise Refusal("invalid JSON") from error


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), "unsupported object fields")
    return value


def components(value):
    require(type(value) is str, "invalid relative path")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise Refusal("invalid path encoding") from error
    require(0 < length <= 4096, "invalid relative path")
    parts = value.split("/")
    require(all(part not in ("", ".", "..") and not part.startswith("~")
                and not any(ord(c) < 32 or ord(c) == 127 for c in part)
                and "\\" not in part for part in parts), "ambiguous relative path")
    return parts


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory_ok(info, uid, *, own=False):
    require(stat.S_ISDIR(info.st_mode) and info.st_uid in ((uid,) if own else (0, uid))
            and not info.st_mode & 0o022, "unsafe configuration directory")


def file_ok(info, uid):
    require(stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1
            and not info.st_mode & 0o022 and 0 <= info.st_size <= MAX_FILE,
            "unsafe configuration file")


class Tree:
    """Descriptor-relative access to explicit configuration paths only.

    The caller owns the root descriptor. Production supplies a fully validated
    account-home descriptor; unit tests supply a disposable fixture descriptor.
    """
    def __init__(self, root_fd, uid):
        self.fd, self.uid = root_fd, uid
        directory_ok(os.fstat(root_fd), uid, own=True)

    @contextmanager
    def parent(self, relative, *, create=False):
        parts = components(relative)
        fd = os.dup(self.fd)
        links = []
        try:
            for name in parts[:-1]:
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                links.append((fd, name, child))
                fd = child
                directory_ok(os.fstat(child), self.uid)
            yield fd, parts[-1]
            for parent, name, child in links:
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                opened = os.fstat(child)
                directory_ok(named, self.uid)
                require((named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino),
                        "configuration directory replaced")
        finally:
            for parent, _, _ in links:
                os.close(parent)
            os.close(fd)

    def read(self, relative, *, absent=False):
        try:
            with self.parent(relative) as (parent, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    file_ok(before, self.uid)
                    chunks, length = [], 0
                    while True:
                        chunk = os.read(fd, min(65536, MAX_FILE + 1 - length))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        length += len(chunk)
                        require(length <= MAX_FILE, "configuration exceeds bound")
                    require(identity(before) == identity(os.fstat(fd))
                            == identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                            "configuration changed while reading")
                    return b"".join(chunks)
                finally:
                    os.close(fd)
        except FileNotFoundError:
            if absent:
                return None
            raise Refusal("required configuration is missing") from None
        except OSError as error:
            raise Refusal("configuration cannot be read safely") from error

    def publish(self, relative, raw, *, expected, immutable=False):
        """CAS under the retained publisher lock; no old file is unlinked first."""
        require(type(raw) is bytes and 0 < len(raw) <= MAX_FILE, "invalid output")
        with self.parent(relative, create=True) as (parent, name):
            current = self.read(relative, absent=True)
            require(current == expected, "publication preimage changed")
            if current == raw:
                return
            require(not immutable or current is None, "immutable generation conflicts")
            temporary = ".shadow-sync-policy-" + secrets.token_hex(16)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            try:
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    require(count > 0, "short output write")
                    view = view[count:]
                os.fsync(fd)
                file_ok(os.fstat(fd), self.uid)
                require(self.read(relative, absent=True) == expected, "publication raced")
                os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass


@contextmanager
def account_tree(home, uid):
    require(os.path.isabs(home) and home != "/" and "//" not in home, "invalid account home")
    parts = components(home[1:])
    fds, links = [os.open("/", os.O_RDONLY | os.O_DIRECTORY)], []
    try:
        directory_ok(os.fstat(fds[0]), uid)
        for name in parts:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1])
            links.append((fds[-1], name, child))
            fds.append(child)
            directory_ok(os.fstat(child), uid)
        tree = Tree(fds[-1], uid)
        yield tree
        for parent, name, child in links:
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(child)
            directory_ok(named, uid)
            require((named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino),
                    "account home ancestry changed")
    finally:
        for fd in reversed(fds):
            os.close(fd)


def policy_projection_input(raw):
    """Decode only the version-1 host serialization we can project losslessly.

    This is deliberately not a general YAML parser or hard-no-touch matcher.
    New shapes/keys, YAML directives, aliases and nonempty overrides refuse.
    AWA still validates and interprets the complete original policy at admission.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise Refusal("policy is not UTF-8") from error
    require("\t" not in text and "\r" not in text and "\0" not in text,
            "unsupported policy serialization")
    scalar_keys = {"version", "managed_location", "modes_file", "default"}
    list_keys = {"governed_roots", "include", "exclude"}
    nested_keys = {"hard_no_touch_paths": {"exact_roots", "managed_namespace_prefixes"},
                   "detectors": {"governed_markers", "artifact_paths",
                                 "foreign_hook_frameworks", "read_only_paths"},
                   "overrides": {"include", "exclude"}}
    result, section, target = {}, None, None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        require(raw_line == raw_line.rstrip(), "trailing policy whitespace")
        if indent == 0:
            match = re.fullmatch(r"([a-z_]+):(?: ([^#]+))?", line)
            require(match is not None, "unsupported top-level policy syntax")
            key, value = match.groups()
            require(key not in result, "duplicate policy key")
            require(key in scalar_keys | list_keys | set(nested_keys), "unknown policy key")
            section, target = key, None
            if key in scalar_keys:
                require(value is not None, "missing policy scalar")
                result[key] = value
            elif key in list_keys:
                require(value is None or value == "[]", "unsupported policy list")
                result[key] = []
                target = result[key] if value is None else None
            else:
                require(value is None, "unsupported policy mapping")
                result[key] = {}
        elif indent == 2 and section in nested_keys and not line.startswith("- "):
            match = re.fullmatch(r"([a-z_]+):(?: (\[\]))?", line)
            require(match is not None, "unsupported nested policy syntax")
            key, empty = match.groups()
            require(key in nested_keys[section] and key not in result[section],
                    "unknown or duplicate nested policy key")
            result[section][key] = []
            target = result[section][key] if empty is None else None
        else:
            depth = 4 if section in nested_keys else 2
            require(indent == depth and target is not None and line.startswith("- "),
                    "unsupported policy indentation or entry")
            value = line[2:]
            require(re.fullmatch(r"[A-Za-z0-9_~./*-]+", value) is not None
                    and value not in target and len(target) < 256, "invalid policy entry")
            target.append(value)
    require(set(result) == scalar_keys | list_keys | set(nested_keys), "incomplete policy")
    for section, keys in nested_keys.items():
        require(set(result[section]) == keys, "incomplete nested policy")
    require(result["version"] == "1" and result["default"] == "include"
            and result["overrides"] == {"include": [], "exclude": []}, "unsupported policy behavior")
    require(result["hard_no_touch_paths"]["exact_roots"]
            and result["hard_no_touch_paths"]["managed_namespace_prefixes"], "required host protection absent")
    # A single relative home root is a deliberate v1 product scope limitation.
    require(len(result["governed_roots"]) == 1
            and result["governed_roots"][0].startswith("~/"), "unsupported governed roots")
    components(result["governed_roots"][0][2:])
    return result


def validate_overlay(value):
    exact(value, ("schema", "governed_root_repository_id", "shelves", "writable_paths",
                  "permanent_no_touch_repository_ids", "managed_locations", "awa_evidence"))
    require(value["schema"] == "shadow-sync-host-overlay/v1", "unsupported overlay")

    def sequence(items, maximum=256, empty=True):
        require(type(items) is list and len(items) <= maximum and (empty or items), "invalid list")
        return items

    def parts(items, maximum=16, hidden=True):
        sequence(items, maximum, False)
        require(all(type(item) is str and "/" not in item
                    and (hidden or not item.startswith(".")) for item in items), "invalid components")
        require(components("/".join(items)) == items, "invalid components")
        return tuple(items)

    def repository_id(item):
        require(type(item) is str and len(item) <= 200
                and re.fullmatch(r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*", item),
                "invalid repository identity")

    repository_id(value["governed_root_repository_id"])
    shelves = [parts(item, 3, False) for item in sequence(value["shelves"], 32, False)]
    require(all(not (a[:len(b)] == b or b[:len(a)] == a)
                for i, a in enumerate(shelves) for b in shelves[:i]), "overlapping shelves")
    ids = sequence(value["permanent_no_touch_repository_ids"])
    for item in ids:
        repository_id(item)
    require(len(set(ids)) == len(ids) and value["governed_root_repository_id"] not in ids,
            "conflicting repository roles")
    sequence(value["writable_paths"])
    kinds, locations = set(), []
    for item in sequence(value["managed_locations"], 16):
        exact(item, ("kind", "components", "minimum_depth"))
        require(item["kind"] in ("cursor", "codex", "awa") and item["kind"] not in kinds
                and type(item["minimum_depth"]) is int and 1 <= item["minimum_depth"] <= 16,
                "invalid managed location")
        kinds.add(item["kind"])
        locations.append(parts(item["components"]))
    evidence = value["awa_evidence"]
    if evidence is not None:
        exact(evidence, ("adapter_path", "root_records_path", "lease_components"))
        parts(components(evidence["adapter_path"]))
        parts(components(evidence["root_records_path"]))
        parts(evidence["lease_components"], 4)
    return locations


def project(policy_raw, overlay_raw, dispatcher):
    policy, overlay = policy_projection_input(policy_raw), decoded(overlay_raw)
    locations = validate_overlay(overlay)
    root = components(policy["governed_roots"][0][2:])
    require(len(root) <= 16, "governed root exceeds projection depth")
    locations.append(tuple(root))
    require(all(not (a[:len(b)] == b or b[:len(a)] == a)
                for i, a in enumerate(locations) for b in locations[:i]), "overlapping managed roots")
    require(policy["managed_location"].startswith("~/")
            and any(item["kind"] == "cursor"
                    and item["components"] == components(policy["managed_location"][2:])
                    for item in overlay["managed_locations"]), "managed location binding differs")
    require(set(policy["include"]) <= {"/".join(shelf) + "/*" for shelf in overlay["shelves"]},
            "included shelf has no projection")
    paths = {"excluded": policy["exclude"],
             "read_only": policy["detectors"]["read_only_paths"],
             "artifacts": policy["detectors"]["artifact_paths"],
             "writable": overlay["writable_paths"]}
    for kind, values in paths.items():
        require(len(set(values)) == len(values), "duplicate path role")
        for value in values:
            require(type(value) is str, "invalid path role")
            if value == ".":
                continue
            plain = value[:-2] if value.endswith("/*") and kind != "writable" else value
            require(not any(c in plain for c in "*?[]")
                    and len(components(plain)) <= 16
                    and all(not p.startswith(".") for p in components(plain)), "unsupported path role")
    for writable in paths["writable"]:
        for kind in ("excluded", "read_only", "artifacts"):
            for item in paths[kind]:
                if writable == item == "." and kind == "excluded":
                    continue
                plain = item[:-2] if item.endswith("/*") else item
                require(writable != plain and not writable.startswith(plain + "/"),
                        "writable path overrides restriction")
    markers = policy["detectors"]["foreign_hook_frameworks"]
    require(0 < len(markers) <= 32 and all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", v)
                                          for v in markers), "invalid foreign hook markers")
    require(0 < len(dispatcher) <= 65536 and b"\0" not in dispatcher, "invalid dispatcher")
    source = {"worktree_policy": {"path": POLICY, "sha256": digest(policy_raw)},
              "host_overlay": {"path": OVERLAY, "sha256": digest(overlay_raw)},
              "hook_dispatcher": {"path": DISPATCHER, "sha256": digest(dispatcher)}}
    return {"schema": "shadow-sync-host-policy-projection/v1", "source_inputs": source,
            "governed_root": {"components": root, "display_label": "~/" + "/".join(root),
                              "repository_id": overlay["governed_root_repository_id"]},
            "shelves": overlay["shelves"], "path_policy": paths,
            "permanent_no_touch_repository_ids": overlay["permanent_no_touch_repository_ids"],
            "managed_locations": overlay["managed_locations"],
            "hooks": {"foreign_markers": markers,
                      "dispatcher_base64": base64.b64encode(dispatcher).decode(),
                      "dispatcher_sha256": digest(dispatcher)},
            "awa_evidence": overlay["awa_evidence"]}


def validate_binding(raw):
    value = exact(decoded(raw), ("schema", "policy", "projection", "awa"))
    require(value["schema"] == "shadow-sync-host-policy-binding/v1", "unsupported prior binding")
    for key in ("policy", "projection"):
        item = exact(value[key], ("path", "sha256"))
        components(item["path"])
        require(type(item["sha256"]) is str and re.fullmatch(HEX64, item["sha256"]), "invalid digest")
    awa = exact(value["awa"], ("module_path", "module_sha256", "release_revision"))
    components(awa["module_path"])
    require(type(awa["module_sha256"]) is str and re.fullmatch(HEX64, awa["module_sha256"])
            and type(awa["release_revision"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", awa["release_revision"]), "invalid release identity")
    require(value["policy"]["path"] == POLICY and awa["module_path"] == MODULE
            and value["projection"]["path"] == DESTINATION + "/projections/"
            + value["projection"]["sha256"] + ".json", "unsupported prior binding paths")
    return value


def preview(tree, home, pin):
    source_paths = (POLICY, OVERLAY, DISPATCHER, POINTER, MODULE, PIN_SOURCE)
    inputs = {path: tree.read(path) for path in source_paths}
    require(read_pin(inputs[PIN_SOURCE]) == pin, "release pin source changed")
    pointer = decoded(inputs[POINTER])
    require(type(pointer) is dict and pointer.get("schema") == "awa-release-pointer/v1"
            and pointer.get("version") == pin["version"] and pointer.get("commit") == pin["revision"]
            and pointer.get("runtime") == home + "/" + RUNTIME
            and pointer.get("hook_owner_mode") == "external", "installed AWA release differs")
    require(digest(inputs[MODULE]) == pin["module_sha256"], "installed AWA module differs")
    projection = project(inputs[POLICY], inputs[OVERLAY], inputs[DISPATCHER])
    projection_raw = encoded(projection)
    projection_path = DESTINATION + "/projections/" + digest(projection_raw) + ".json"
    old = tree.read(BINDING, absent=True)
    if old is not None:
        prior = validate_binding(old)
        # Preserve a readable old generation. Stale sources may intentionally be
        # repaired, but never silently replace an unknown/corrupt binding/history.
        previous = tree.read(prior["projection"]["path"])
        require(digest(previous) == prior["projection"]["sha256"], "prior generation is damaged")
    binding = {"schema": "shadow-sync-host-policy-binding/v1",
               "policy": projection["source_inputs"]["worktree_policy"],
               "projection": {"path": projection_path, "sha256": digest(projection_raw)},
               "awa": {"module_path": MODULE, "module_sha256": pin["module_sha256"],
                       "release_revision": pin["revision"]}}
    binding_raw = encoded(binding)
    description = {"schema": "shadow-sync-host-policy-publication/v1",
                   "inputs": {path: digest(raw) for path, raw in inputs.items()},
                   "binding_sha256": digest(binding_raw), "projection_sha256": digest(projection_raw),
                   "prior_binding_sha256": None if old is None else digest(old)}
    # Repeat explicit reads so mixed snapshots refuse; no discovered path is read.
    require(all(tree.read(path) == raw for path, raw in inputs.items()), "source changed during preview")
    require(tree.read(BINDING, absent=True) == old, "binding changed during preview")
    return {"description": description, "action_digest": digest(encoded(description)),
            "binding": binding_raw, "projection": projection_raw, "projection_path": projection_path,
            "old": old}


def read_pin(raw):
    """Read the owner's literal release constants without executing owner tooling."""
    try:
        syntax = ast.parse(raw)
        names = {"VERSION": "version", "PIN": "revision", "POLICY_MODULE_SHA256": "module_sha256"}
        result = {}
        for node in syntax.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        key = names[target.id]
                        require(key not in result, "duplicate release constant")
                        result[key] = ast.literal_eval(node.value)
        require(set(result) == set(names.values()) and all(type(v) is str for v in result.values()),
                "release constants unavailable")
        require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", result["version"])
                and re.fullmatch(r"[0-9a-f]{40}", result["revision"])
                and re.fullmatch(HEX64, result["module_sha256"]), "invalid release constants")
        return result
    except (SyntaxError, ValueError, TypeError) as error:
        raise Refusal("release constants unavailable") from error


@contextmanager
def publisher_lock(tree):
    with tree.parent(DESTINATION + "/policy-publisher.lock", create=True) as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        try:
            file_ok(os.fstat(fd), tree.uid)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Refusal("another policy publisher is active") from error
            require(identity(os.fstat(fd)) == identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                    "publisher lock replaced")
            yield
        finally:
            os.close(fd)  # Never unlink/recreate the coordination inode.


def apply(tree, home, pin, expected):
    require(type(expected) is str and re.fullmatch(HEX64, expected), "invalid expected action digest")
    with publisher_lock(tree):
        plan = preview(tree, home, pin)
        require(plan["action_digest"] == expected, "publication preview is stale")
        tree.publish(plan["projection_path"], plan["projection"],
                     expected=tree.read(plan["projection_path"], absent=True), immutable=True)
        if plan["old"] is not None and plan["old"] != plan["binding"]:
            history = DESTINATION + "/binding-history/" + digest(plan["old"]) + ".json"
            tree.publish(history, plan["old"], expected=tree.read(history, absent=True), immutable=True)
        require(preview(tree, home, pin)["action_digest"] == expected, "source changed before publication")
        tree.publish(BINDING, plan["binding"], expected=plan["old"])
        final = preview(tree, home, pin)
        require(final["old"] == plan["binding"] == final["binding"], "publication did not converge")
        return {"status": "verified", "binding_sha256": digest(plan["binding"]),
                "projection_sha256": digest(plan["projection"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply", "verify"))
    parser.add_argument("--expected", help="exact action digest returned by preview")
    args = parser.parse_args()
    try:
        require((args.operation == "apply") == (args.expected is not None), "expected digest is apply-only")
        uid = os.geteuid()
        require(uid == os.getuid() and uid != 0, "run as the owning account")
        home = pwd.getpwuid(uid).pw_dir.rstrip("/")
        # This deployment tool is executable only from the canonical dev checkout.
        # Source/worktree tests call internal functions with disposable descriptors.
        require(str(Path(__file__).absolute()) == home + "/dev/_ops/bin/shadow-sync-host-policy.py",
                "deploy from the canonical dev checkout")
        with account_tree(home, uid) as tree:
            pin = read_pin(tree.read(PIN_SOURCE))
            if args.operation == "apply":
                result = apply(tree, home, pin, args.expected)
            else:
                plan = preview(tree, home, pin)
                if args.operation == "verify":
                    require(plan["old"] == plan["binding"], "deployed binding is absent or stale")
                result = dict(plan["description"], action_digest=plan["action_digest"],
                              status="verified" if args.operation == "verify" else "preview")
            print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, Refusal, KeyError, TypeError) as error:
        # Never echo policy values, candidate paths or file contents to diagnostics.
        message = str(error) if isinstance(error, Refusal) else "configuration unavailable or malformed"
        print("ShadowSync host policy refused: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
