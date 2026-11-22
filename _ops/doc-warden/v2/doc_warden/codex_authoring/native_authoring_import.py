"""Adapt verified native results to the portable draft transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ..canonical import digest_ref
from ..gsd_adapter import (
    AuthoringImportPreview,
    AuthoringResult,
    ImportPlan,
    authoring_preview_record,
    validate_authoring_result,
)
from ..gsd_plan_check import CHECKER_DESCRIPTOR_DIGEST
from ..transactions import ObservedInput

NATIVE_CHECK_ROLE = "gsd-plan-checker"
MAX_DOCUMENT_BYTES = 512 * 1024


@dataclass(frozen=True)
class VerifiedNativeCheck:
    """In-memory handoff from the owned native worker runner."""

    run_id: str
    observation: dict[str, Any]
    report: bytes
    output_digests: dict[str, str]


def _native_output_paths(allowed: tuple[str, ...], outputs: dict[str, bytes]) -> None:
    if not outputs or len(outputs) > 32:
        raise ValueError("native_authoring_outputs_invalid")
    for relative, raw in outputs.items():
        if type(relative) is not str or type(raw) is not bytes or not 0 < len(raw) <= MAX_DOCUMENT_BYTES:
            raise ValueError("native_authoring_outputs_invalid")
        path = PurePosixPath(relative)
        if path.is_absolute() or path.as_posix() != relative or ".." in path.parts:
            raise ValueError("native_authoring_outputs_invalid")
        if not any(
            len(path.parts) == len(PurePosixPath(pattern).parts)
            and path.match(pattern)
            for pattern in allowed
        ):
            raise ValueError("native_authoring_output_scope_changed")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("native_authoring_outputs_invalid") from exc


def preview_native_draft(
    preview: AuthoringImportPreview,
    *,
    allowed: tuple[str, ...],
    outputs: dict[str, bytes],
    checker: VerifiedNativeCheck | None = None,
    checker_package: Path | None = None,
    checker_node: Path | None = None,
    adapter_inputs: tuple[ObservedInput, ...] = (),
) -> ImportPlan:
    """Validate admitted output bytes without writing them to the target repo."""
    _native_output_paths(allowed, outputs)
    plans = any(relative.endswith("-PLAN.md") for relative in outputs)
    envelope = None
    report = None
    if plans:
        if checker is None:
            raise ValueError("authoring_native_plan_check_required")
        observed = checker.observation
        got = {path: digest_ref(content) for path, content in outputs.items()}
        if (
            type(observed) is not dict
            or observed.get("schema") != "skills/gsd-named-authoring-observation/v1"
            or observed.get("role") != NATIVE_CHECK_ROLE
            or observed.get("verdict") != "VERIFICATION PASSED"
            or type(checker.run_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", checker.run_id)
            or type(checker.report) is not bytes
            or checker.output_digests != got
            or observed.get("report_sha256") != digest_ref(checker.report).removeprefix("sha256:")
        ):
            raise ValueError("native_authoring_checker_evidence_changed")
        report = checker.report
        envelope = {
            "schema": "doc-warden/gsd-native-plan-check/v1",
            "preview_digest": authoring_preview_record(preview)["preview_digest"],
            "changed_file_digests": got,
            "descriptor_digest": CHECKER_DESCRIPTOR_DIGEST,
            "run_id": checker.run_id,
            "verdict": "VERIFICATION PASSED",
            "report_digest": digest_ref(report),
        }
    elif checker is not None:
        raise ValueError("native_authoring_unexpected_checker")
    return validate_authoring_result(preview, AuthoringResult(
        source_revision=preview.source_revision,
        pin_digest=preview.pin_digest,
        outputs=outputs,
        checker_passed=plans,
        native_plan_check=envelope,
        native_report=report,
    ), checker_package=checker_package, checker_node=checker_node, adapter_inputs=adapter_inputs)
