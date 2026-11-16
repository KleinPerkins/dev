"""Closed, non-secret qualification observations for interoperability evidence v1.

Records describe evidence, never permission. Text bodies/configuration are not accepted.
"""
import json
from pathlib import Path
import re

SCHEMA = "interoperability/qualification/v1"
FIELDS = {"schema", "capability", "owner", "source_revision", "payload_sha256", "host", "surface",
          "host_build", "adapter_revision", "check", "outcome", "observed_at", "evidence_ref",
          "limitations", "rollback_revision"}
OUTCOMES = {"pass", "fail", "unknown", "not-applicable", "unsupported"}
LIMITATIONS = {"native-not-observed", "host-build-unavailable", "model-execution-unverified",
              "source-drift", "fixture-only", "owner-decision-required", "not-activation",
              "not-awa-registration", "not-security-isolation", "account-unverified",
              "metrics-unavailable", "source-merge-pending", "cursor-unavailable",
              "registration-owner-unresolved"}


def validate(row):
    if not isinstance(row, dict) or set(row) != FIELDS or row["schema"] != SCHEMA:
        raise ValueError("closed qualification schema required")
    for key in ("capability", "owner", "check"):
        if not isinstance(row[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,127}", row[key]):
            raise ValueError("invalid identifier")
    for key, length in (("source_revision", 40), ("adapter_revision", 40),
                        ("rollback_revision", 40), ("payload_sha256", 64)):
        if row[key] is not None and not re.fullmatch(r"[0-9a-f]{%d}" % length, row[key]):
            raise ValueError("invalid revision/digest")
    if row["host"] not in {"codex", "cursor", "claude", "fixture"}:
        raise ValueError("unknown host")
    if row["surface"] not in {"local-macos-desktop", "fixture", "cli", "cloud", "remote"}:
        raise ValueError("unknown surface")
    if row["host_build"] is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", row["host_build"]):
        raise ValueError("invalid host build")
    if row["outcome"] not in OUTCOMES:
        raise ValueError("unknown outcome")
    if not isinstance(row["limitations"], list) or any(x not in LIMITATIONS for x in row["limitations"]):
        raise ValueError("unknown limitation")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)", row["observed_at"]):
        raise ValueError("UTC observation time required")
    ref = row["evidence_ref"]
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_./#:-]{1,240}", ref):
        raise ValueError("invalid evidence reference")
    if ref.startswith(("/", "http:", "https:")) or ".." in ref.split("/"):
        raise ValueError("evidence must be repository-relative")
    if row["outcome"] == "pass" and (not row["source_revision"] or not row["payload_sha256"]):
        raise ValueError("passing evidence requires exact source and payload")
    if row["host_build"] is None and "host-build-unavailable" not in row["limitations"]:
        raise ValueError("missing build must remain explicit")
    return row


def current(row, *, source_revision, payload_sha256, host_build, adapter_revision):
    validate(row)
    if row["host"] != "fixture" and host_build is None:
        return False
    expected = dict(source_revision=source_revision, payload_sha256=payload_sha256,
                    host_build=host_build, adapter_revision=adapter_revision)
    return all(row[key] == value for key, value in expected.items())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.path.read_text())
    if not isinstance(rows, list):
        parser.error("expected observation array")
    for row in rows:
        validate(row)
    print(f"Validated {len(rows)} qualification observations; no authorization inferred.")
