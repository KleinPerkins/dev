"""Deterministic proposal-only routing for the doc-warden operator surface."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


_ACTION_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class IntentSpec:
    intent: str
    example: str
    patterns: tuple[str, ...]
    cli_equivalent: str
    consequence: str
    native_dispatch: str
    priority: int = 0


@dataclass(frozen=True)
class ProposedIntent:
    status: str
    intent: str | None
    cli_equivalent: str | None
    native_dispatch: str | None
    consequence: str | None
    proposal_only: bool
    authorized: bool
    consent_required: bool
    confirmation_binding: dict[str, str] | None
    next_action: str
    candidates: tuple[str, ...]
    repository_writes: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "doc-warden/proposed-intent/v1",
            "status": self.status,
            "intent": self.intent,
            "cli_equivalent": self.cli_equivalent,
            "native_dispatch": self.native_dispatch,
            "consequence": self.consequence,
            "proposal_only": self.proposal_only,
            "authorized": self.authorized,
            "consent_required": self.consent_required,
            "confirmation_binding": self.confirmation_binding,
            "next_action": self.next_action,
            "candidates": list(self.candidates),
            "repository_writes": list(self.repository_writes),
            "message": self.message,
        }


def _spec(
    intent: str,
    example: str,
    patterns: tuple[str, ...],
    cli: str,
    consequence: str,
    *,
    native_dispatch: str = "engine_cli",
    priority: int = 0,
) -> IntentSpec:
    return IntentSpec(
        intent=intent,
        example=example,
        patterns=patterns,
        cli_equivalent=f"bash _ops/bin/doc-warden.sh {cli}",
        consequence=consequence,
        native_dispatch=native_dispatch,
        priority=priority,
    )


INTENT_SPECS: dict[str, IntentSpec] = {
    "view_repo": _spec(
        "view_repo",
        "What are we working on?",
        (r"\bwhat (?:are we|am i) working on\b", r"\bshow (?:the )?repo(?:sitory)? roadmap\b"),
        "view repo",
        "read_only",
    ),
    "view_fleet": _spec(
        "view_fleet",
        "Show everything across repos.",
        (r"\bshow everything across repos(?:itories)?\b", r"\bfleet roadmap\b"),
        "view fleet",
        "read_only",
    ),
    "draft_prd": _spec(
        "draft_prd",
        "Draft the PRD.",
        (r"\bdraft (?:the |a )?prd\b", r"\bcreate (?:the |a )?prd draft\b"),
        "draft prd --title <title> --preview",
        "semantic",
    ),
    "draft_spec": _spec(
        "draft_spec",
        "Draft the spec.",
        (r"\bdraft (?:the |a )?(?:technical )?spec\b",),
        "draft spec --title <title> --preview",
        "semantic",
    ),
    "draft_plan": _spec(
        "draft_plan",
        "Draft the plan.",
        (r"\bdraft (?:the |a )?plan\b",),
        "draft plan --title <title> --preview",
        "semantic",
    ),
    "log_defect": _spec(
        "log_defect",
        "Log this bug.",
        (r"\blog (?:this |the |a )?(?:bug|defect)\b",),
        'v2-preview intent "Log this bug."',
        "semantic",
        native_dispatch="operator_invoke_required",
    ),
    "update_authority": _spec(
        "update_authority",
        "Update the design.",
        (
            r"\bupdate (?:the )?(?:design|requirements?)\b",
            r"\bchange (?:the )?(?:design|requirements?)\b",
        ),
        'v2-preview intent "Update the design."',
        "semantic",
        native_dispatch="operator_invoke_required",
    ),
    "prioritize": _spec(
        "prioritize",
        "Make this P0.",
        (r"\bmake (?:this|it) p[0-3]\b", r"\bchange (?:the )?priority\b"),
        "prioritize <roadmap-id> <P0|P1|P2|P3> --preview",
        "roadmap",
    ),
    "sequence": _spec(
        "sequence",
        "Do this after X.",
        (
            r"\bdo (?:this|it) (?:before|after)\b",
            r"\bchange (?:the )?(?:sequence|dependency)\b",
        ),
        "sequence <roadmap-id> --after <roadmap-id> --preview",
        "roadmap",
    ),
    "reconcile_preview": _spec(
        "reconcile_preview",
        "What drifted?",
        (r"\bwhat drifted\b", r"\breconcile\s+(?:the\s+)?(?:repo|repository|fleet)\b"),
        "reconcile --preview",
        "read_only",
    ),
    "apply_reconciliation": _spec(
        "apply_reconciliation",
        "Apply the safe repairs.",
        (r"\bapply (?:the )?safe repairs?\b", r"\bapply (?:the )?reconciliation\b"),
        (
            "apply --operation-id <operation-id> --action-digest <action-digest> "
            "--consent-envelope <regular-file-path>"
        ),
        "structural",
    ),
    "doctor_repo": _spec(
        "doctor_repo",
        "Is governance healthy?",
        (r"\bis (?:doc-warden |governance )?healthy\b", r"\bdoctor (?:the )?repo\b"),
        "doctor repo",
        "read_only",
        priority=10,
    ),
    "doctor_fleet": _spec(
        "doctor_fleet",
        "Is fleet governance healthy?",
        (r"\bis (?:the )?fleet governance healthy\b", r"\bdoctor (?:the )?fleet\b"),
        "doctor fleet",
        "read_only",
        priority=20,
    ),
    "run": _spec(
        "run",
        "Start the work.",
        (r"\bstart (?:the )?work\b", r"\brun (?:the )?(?:work|phase)\b"),
        'v2-preview intent "Start the work."',
        "execution",
        native_dispatch="operator_invoke_required",
    ),
    "pause": _spec(
        "pause",
        "Pause here.",
        (r"\bpause (?:here|the work)\b",),
        'v2-preview intent "Pause here."',
        "authoring_state",
        native_dispatch="operator_invoke_required",
    ),
    "resume": _spec(
        "resume",
        "Resume the work.",
        (r"\bresume (?:the )?work\b",),
        'v2-preview intent "Resume the work."',
        "execution",
        native_dispatch="operator_invoke_required",
    ),
    "verify": _spec(
        "verify",
        "Verify this.",
        (r"\bverify (?:this|the work|the plan)\b",),
        'v2-preview intent "Verify this."',
        "evidence",
        native_dispatch="operator_invoke_required",
    ),
}


def _valid_confirmation_binding(
    context: Mapping[str, Any],
) -> dict[str, str] | None:
    operation_id = context.get("operation_id")
    action_digest = context.get("action_digest")
    try:
        parsed = uuid.UUID(str(operation_id))
    except (ValueError, TypeError, AttributeError):
        return None
    if str(parsed) != str(operation_id) or _ACTION_DIGEST.fullmatch(
        str(action_digest)
    ) is None:
        return None
    return {
        "operation_id": str(operation_id),
        "action_digest": str(action_digest),
    }


def _matches(utterance: str) -> list[IntentSpec]:
    normalized = " ".join(utterance.strip().lower().split())
    return [
        spec
        for spec in INTENT_SPECS.values()
        if any(re.search(pattern, normalized) for pattern in spec.patterns)
    ]


def _unmatched() -> ProposedIntent:
    return ProposedIntent(
        status="unmatched",
        intent=None,
        cli_equivalent=None,
        native_dispatch=None,
        consequence=None,
        proposal_only=True,
        authorized=False,
        consent_required=False,
        confirmation_binding=None,
        next_action="clarify_intent",
        candidates=(),
        repository_writes=(),
        message=(
            "I checked the closed doc-warden intent map. I am uncertain which "
            "governed action you want. Next action: name one action such as view, "
            "draft, log, update, prioritize, sequence, reconcile, doctor, run, "
            "pause, resume, or verify."
        ),
    )


def map_intent(
    utterance: str,
    context: Mapping[str, Any] | None,
) -> ProposedIntent:
    """Map ordinary language to one proposal without granting authorization."""

    if not isinstance(utterance, str) or not utterance.strip():
        return _unmatched()
    safe_context: Mapping[str, Any] = context if isinstance(context, Mapping) else {}
    matches = _matches(utterance)
    if not matches:
        return _unmatched()

    consequences = {spec.consequence for spec in matches}
    if len(consequences) > 1:
        candidates = tuple(spec.intent for spec in matches)
        return ProposedIntent(
            status="ambiguous",
            intent=None,
            cli_equivalent=None,
            native_dispatch=None,
            consequence=None,
            proposal_only=True,
            authorized=False,
            consent_required=False,
            confirmation_binding=None,
            next_action="choose_one_intent",
            candidates=candidates,
            repository_writes=(),
            message=(
                "I checked the closed doc-warden intent map. The request is "
                "uncertain because it matches routes with different consequences: "
                f"{', '.join(candidates)}. Next action: choose one route before "
                "any preview or action."
            ),
        )

    spec = sorted(matches, key=lambda item: (-item.priority, item.intent))[0]
    consent_required = spec.consequence != "read_only"
    binding = (
        _valid_confirmation_binding(safe_context)
        if consent_required and spec.native_dispatch == "engine_cli"
        else None
    )
    if spec.native_dispatch == "operator_invoke_required":
        next_action = "await_authorized_execution_surface"
        message = (
            "I checked the closed doc-warden intent map. This is a proposal "
            "only; native execution for this route is intentionally unavailable "
            "in M3-T02, and the selected scope remains uncertain. Next action: "
            "retain the proposal for the separately authorized execution "
            "surface."
        )
    elif not consent_required:
        next_action = "run_cli"
        message = (
            "I checked the closed doc-warden intent map. This is a read-only "
            "proposal. Next action: run the explicit CLI equivalent."
        )
    elif binding is None:
        next_action = "run_preview"
        message = (
            "I checked the closed doc-warden intent map. This proposal is not "
            "authorization and no operation-bound preview is available. Next "
            "action: run the explicit preview, review its consequence, then "
            "provide fresh operation-bound explicit confirmation if required."
        )
    else:
        next_action = "review_preview_and_confirm"
        message = (
            "I checked the closed doc-warden intent map. This proposal is not "
            "authorization. Next action: review the exact engine preview and "
            "provide fresh operation-bound explicit confirmation for operation "
            f"{binding['operation_id']}."
        )
    return ProposedIntent(
        status="proposed",
        intent=spec.intent,
        cli_equivalent=spec.cli_equivalent,
        native_dispatch=spec.native_dispatch,
        consequence=spec.consequence,
        proposal_only=True,
        authorized=False,
        consent_required=consent_required,
        confirmation_binding=binding,
        next_action=next_action,
        candidates=(spec.intent,),
        repository_writes=(),
        message=message,
    )
