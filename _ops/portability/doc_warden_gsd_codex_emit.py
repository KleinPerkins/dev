"""Use the owner-pinned emitter with the qualified current Mac Node binary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))

import personal_gsd_codex_bundle as emitter


QUALIFIED_NODE = "2c711dba4c61d710efa4e806dd87c6bf1532aa02afb95515c1c60efa0275ffec"
MAX_TARBALL = 32 * 1024 * 1024


def _verify_node(node: Path) -> None:
    if emitter.digest(emitter.source.regular_bytes(node, 128 * 1024 * 1024)) != QUALIFIED_NODE:
        raise ValueError("native_authoring_emitter_node_unqualified")


def emit(operation: Path, archive: bytes, node: Path) -> dict:
    if sys.platform != "darwin":
        raise ValueError("native_authoring_emitter_requires_mac")
    node = node.resolve(strict=True)
    _verify_node(node)
    contract, source_contract = emitter.load_contract()
    emitter.source.verified_package(archive, source_contract)
    emitter._private_directory(operation, empty=True)
    package, bundle = operation / "package", operation / "bundle"
    reference, modes = emitter._materialize(archive, package, contract)
    bundle.mkdir(mode=0o700)
    code, stdout, stderr = emitter._runner()(emitter._child_command(package, bundle, node), operation)
    if code or stderr:
        raise ValueError("native_authoring_emission_failed")
    emitted = emitter.source.strict_json(stdout)
    emitter._validate_bundle(package, bundle, reference, emitted, contract)
    inventory = emitter._seal(bundle, modes)
    _verify_node(node)
    return {
        "schema": "doc-warden/codex-authoring-bundle/v1",
        "runtime_revision": source_contract["git_commit"],
        "package_sha256": source_contract["package_sha256"],
        "node_sha256": QUALIFIED_NODE,
        "bundle_digest": "sha256:" + emitter.digest(emitter.encode(inventory)),
        "bundle_files": len(inventory),
        "selected_roles": contract["allowed_authoring_roles"],
        "selected_skills": contract["selected_skills"],
    }


def read_bundle(bundle: Path) -> dict:
    inventory = emitter._inventory(bundle, sealed=True)
    return {"bundle_digest": "sha256:" + emitter.digest(emitter.encode(inventory)), "bundle_files": len(inventory)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("emit")
    staging.add_argument("--node", type=Path, required=True)
    staging.add_argument("--operation", type=Path, required=True)
    readback = commands.add_parser("readback")
    readback.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "emit":
            archive = sys.stdin.buffer.read(MAX_TARBALL + 1)
            if len(archive) > MAX_TARBALL:
                raise ValueError("native_authoring_archive_too_large")
            value = emit(args.operation, archive, args.node)
        else:
            value = read_bundle(args.bundle)
    except (OSError, ValueError):
        parser.exit(1, "Native authoring bundle refused.\n")
    sys.stdout.buffer.write(emitter.encode(value))


if __name__ == "__main__":
    main()
