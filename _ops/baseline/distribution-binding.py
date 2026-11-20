#!/usr/bin/env python3
"""Project the approved nonsecret distribution bindings. No release operation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener


AUTHORITY_ID = 1459458379
AUTHORITY_NAME = "KleinPerkins/dev"
GITHUB_API = "https://api.github.com"
BINDINGS_PATH = "_ops/baseline/distribution-bindings.json"
MAX_BYTES = 64 * 1024
FULL_REVISION = re.compile(r"[0-9a-f]{40}")
REPOSITORY_NAME = re.compile(r"KleinPerkins/[A-Za-z0-9_.-]+")
IDENTIFIER = re.compile(r"[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)+")
LABEL = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BINDING_FIELDS = {
    "repository", "repository_id", "source_visibility", "product_audience",
    "application_id", "channels", "outputs", "signing", "state",
}


def unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate JSON key")
        fields[key] = value
    return fields


def parse_document(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Binding document size is invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    if not isinstance(value, dict):
        raise ValueError("Binding document must be a JSON object")
    return value


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def unique_labels(items):
    return (isinstance(items, list) and bool(items)
            and all(isinstance(item, str) and LABEL.fullmatch(item) for item in items)
            and len(set(items)) == len(items))


def matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def validate_binding(binding):
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
        raise ValueError("Unexpected distribution binding fields")
    if (type(binding["repository_id"]) is not int or binding["repository_id"] <= 0
            or not matches(REPOSITORY_NAME, binding["repository"])
            or not matches(IDENTIFIER, binding["application_id"])):
        raise ValueError("Invalid repository or application identity")
    if (binding["source_visibility"] not in ("public", "private")
            or binding["product_audience"] not in ("public", "private", "none")
            or not unique_labels(binding["channels"]) or not unique_labels(binding["outputs"])):
        raise ValueError("Invalid visibility, audience, channel or output binding")
    signing = binding["signing"]
    if (not isinstance(signing, dict) or set(signing) != {"code_identity", "signature"}
            or not all(matches(LABEL, value) for value in signing.values())):
        raise ValueError("Invalid signing contract")
    if binding["state"] != "pending-profile-qualification":
        raise ValueError("Unknown distribution binding state")


def project(authority_bytes, *, repository_id, revision):
    if not matches(FULL_REVISION, revision) or type(repository_id) is not int or repository_id <= 0:
        raise ValueError("Full Dev revision and positive GitHub repository ID required")
    registry = parse_document(authority_bytes)
    if (set(registry) != {"schema", "authority_repository_id", "bindings"}
            or registry["schema"] != "dev-distribution-bindings/v1"
            or type(registry["authority_repository_id"]) is not int
            or registry["authority_repository_id"] != AUTHORITY_ID
            or not isinstance(registry["bindings"], list)):
        raise ValueError("Unexpected Dev authority document")
    by_id = {}
    names = set()
    for binding in registry["bindings"]:
        validate_binding(binding)
        identity = binding["repository_id"]
        name = binding["repository"].casefold()
        if identity in by_id or name in names:
            raise ValueError("Duplicate distribution repository")
        by_id[identity] = binding
        names.add(name)
    if repository_id not in by_id:
        raise ValueError("Distribution repository is unbound")
    return {
        "schema": "dev-distribution-projection/v1",
        "authority_repository_id": AUTHORITY_ID,
        "authority_revision": revision,
        "authority_sha256": hashlib.sha256(authority_bytes).hexdigest(),
        "binding": by_id[repository_id],
    }


def verify_projection(candidate_bytes, authority_bytes, *, repository_id, revision):
    expected = project(authority_bytes, repository_id=repository_id, revision=revision)
    if canonical(parse_document(candidate_bytes)) != canonical(expected):
        raise ValueError("Projection differs from the supplied Dev revision")
    return expected



class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_github(path, accept="application/vnd.github+json"):
    request = Request(
        GITHUB_API + path,
        headers={"Accept": accept, "User-Agent": "dev-distribution-binding"},
    )
    with build_opener(RejectRedirect()).open(request, timeout=10) as response:
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("GitHub response size is invalid")
    return raw


def current_source():
    endpoint = f"/repositories/{AUTHORITY_ID}"
    repository = parse_document(fetch_github(endpoint))
    if (repository.get("id") != AUTHORITY_ID or repository.get("full_name") != AUTHORITY_NAME
            or repository.get("private") is not False or repository.get("default_branch") != "main"):
        raise ValueError("Live Dev authority identity differs")
    ref = parse_document(fetch_github(f"{endpoint}/git/ref/heads/main"))
    target = ref.get("object")
    if (ref.get("ref") != "refs/heads/main" or not isinstance(target, dict)
            or target.get("type") != "commit" or not matches(FULL_REVISION, target.get("sha"))):
        raise ValueError("Live Dev main identity is invalid")
    revision = target["sha"]
    raw = fetch_github(f"{endpoint}/contents/{BINDINGS_PATH}?ref={revision}", "application/vnd.github.raw+json")
    confirmed = parse_document(fetch_github(f"{endpoint}/git/ref/heads/main"))
    if confirmed.get("ref") != ref["ref"] or confirmed.get("object") != target:
        raise ValueError("Dev main changed during binding readback")
    return revision, raw

def read_source(repo, revision):
    if not matches(FULL_REVISION, revision):
        raise ValueError("A full Dev source revision is required")
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{revision}:{BINDINGS_PATH}"],
        timeout=10, stderr=subprocess.DEVNULL,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_id", type=int)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument("--revision", help="Project or check an exact committed local Dev revision")
    origin.add_argument("--current", action="store_true", help="Read and verify the live public Dev main revision")
    parser.add_argument("--verify", type=Path, help="Verify a supplied projection instead of emitting one")
    args = parser.parse_args()
    if args.current:
        revision, source = current_source()
    else:
        revision = args.revision
        source = read_source(Path(__file__).resolve().parents[2], revision)
    selectors = {"repository_id": args.repository_id, "revision": revision}
    if args.verify is None:
        result = project(source, **selectors)
        sys.stdout.buffer.write(canonical(result))
    else:
        with args.verify.open("rb") as candidate:
            verify_projection(candidate.read(MAX_BYTES + 1), source, **selectors)
        print("Projection matches the supplied Dev revision. Profile qualification is pending.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"Distribution binding refused: {error}")
