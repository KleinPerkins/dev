"""Current-owner active-v2 read-only view and proposal definitions.

Exact owner AST definitions; writers, live dispatch and fleet discovery omitted.
Use only through observation_contract with a fenced disposable snapshot.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from types import FunctionType
import re
import uuid

OWNER_REF = '8603bc7c697077a87fbfa24796b77a4424e8d995'
OWNER_SOURCES = {'cli.py': '7d40fd84dffe0cba715e396c15c3a3934f7e88c1', 'dashboard.py': '6e60c64e1c3e8f6cbe9415927e0a86fdec1071e0', 'intents.py': '200b7fdd6859b9d6bb4c40a75d95ee4b231a3c37', 'inventory.py': '2964cd249d6e0cab198a870e6cfb491a14408ba9', 'render.py': '93d030c9e535c4319847285f6715b32d3c8af9f3', 'roadmap.py': '77c87c644ef563dbcefb14fe11418e37545d8a2d'}
OWNER_AST_SHA256 = {'roadmap.py:BEGIN': '80352e515b31577093adda063d120db6f251f2f19cb948da06c863026b3e1e05', 'roadmap.py:END': '0ebbc9444044c03e88aaa3067602658a30a2e3703b2d162f314d2bc3a10fe829', 'roadmap.py:RoadmapView': '1916e372c106278c09164fa28ec856e4c7fc71a13aeda3cb135bf7f1c0c78ac8', 'roadmap.py:_head': 'b29d49f92005f971ea849938cf2bbc0548af2063fde6524def6e49ff83a84c3b', 'roadmap.py:parse_roadmap': '73dc669684ed81faf2ec560e4504bff1a84f275ef2179e95bf55edb74805b686', 'roadmap.py:roadmap_view': '4dace342afd7e79f1335fa7bd6fed4c4d8430eb08fb6870700d4bc32515a1f08', 'cli.py:_repo_status': '42c91bd358f3a11516f9980c943026557f597f054ddc6ecf7b97b3f321124e18', 'inventory.py:CheckoutObservation': '70d7a53ff760fee22faa7bf24d98ab4b9e4d9616833c16470d6f9fba84356d2c', 'inventory.py:LogicalRepository': '8793493018cbb0b28794b564605d59f130ec6432e88ead38bb8a85dfa2cabd5a', 'inventory.py:deduplicate_observations': '793bc9bb70884e0c13ecfdec519b3809a1e8824dd136e3ced7f646411e86f6f9', 'render.py:render_logical_repository': '33ec00ff1b8e2163226397b06708bd5900c0e7042baf0dcbd18e5215f9a5aca5', 'dashboard.py:render_fleet_snapshot': '0d00a73f7e515dc86eeae7c5478dce79c35e1c8aae85903ac089e1413631911c', 'intents.py:_ACTION_DIGEST': '978ef85ee78cf5140b73843a94e159ca45c3ecf523000fa3234b021d349b49be', 'intents.py:IntentSpec': '66ed24b6d72f94bb47943ed2dfeb1cc0aff1ce71e91a5e00b33a6c64627f4053', 'intents.py:ProposedIntent': 'd9fa7fa6ec6c8f2097506006b9e89bfc75126dd3330bf19ba4ceb722704ee11d', 'intents.py:_spec': '742258b8d17130a4907637861e60d05dca247a3f67e71d8fb935a2b0f78b108e', 'intents.py:INTENT_SPECS': '897187d07c937f0a02bef35fd2be3e8367fa4685bfd0e21215d7776b6c031c28', 'intents.py:_valid_confirmation_binding': 'daccdfd387d554ff7fc4b971449766545277a39bde830fe01683d2659711679d', 'intents.py:_matches': 'f05a051835f84e3217e3740ae5eb190287f77a37c577949d80673b33581a6e69', 'intents.py:_unmatched': 'da16780f436468d53092c9fcebea078ea28becb92d79f40c2aef3599953a6339', 'intents.py:map_intent': '12e9e944c327949897b69990a6cb1b1f94cf075c7e8ddaf4a7bbfcfa5bbacd9b'}
VIEW_FUNCTIONS = ('_head', 'parse_roadmap', 'roadmap_view', '_repo_status', 'deduplicate_observations', 'render_logical_repository', 'render_fleet_snapshot')

BEGIN = "<!-- doc-warden:roadmap-json:begin -->\n"

END = "<!-- doc-warden:roadmap-json:end -->\n"

@dataclass(frozen=True)
class RoadmapView:
    repository_key: str
    source_revision: str
    items: tuple[dict[str, Any], ...]
    projection: bool = False

def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

def parse_roadmap(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text()
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("roadmap markers invalid")
    payload = text.split(BEGIN, 1)[1].split(END, 1)[0]
    parsed = parse_json_object(payload.encode("utf-8"))
    if parsed.get("schema") != "doc-warden/roadmap/v2" or not isinstance(
        parsed.get("items"), list
    ):
        raise ValueError("roadmap payload invalid")
    for item in parsed["items"]:
        require_valid("roadmap", item)
    return parsed["items"]

def roadmap_view(repo: Path, repository_key: str, *, projection: bool = False) -> RoadmapView:
    repo = repo.resolve(strict=True)
    relative = ".planning/generated/fleet-roadmap.md" if projection else ".planning/ROADMAP.md"
    return RoadmapView(
        repository_key=repository_key,
        source_revision=_head(repo),
        items=tuple(parse_roadmap(repo / relative)),
        projection=projection,
    )

def _repo_status(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    try:
        config = read_repository_config(repo)
    except ValueError as exc:
        return {
            "schema": "doc-warden/repo-view/v2",
            "repository": str(repo),
            "source_revision": head,
            "central_activation": "active",
            "profile": "invalid",
            "migration_status": "blocked",
            "write_enabled": False,
            "repository_key": None,
            "read_only": True,
            "repository_writes": [],
            "reason": str(exc),
        }
    return {
        "schema": "doc-warden/repo-view/v2",
        "repository": str(repo),
        "source_revision": head,
        "central_activation": "active",
        "profile": "v2" if config else "v1",
        "migration_status": (
            "active"
            if config and config["enabled"]
            else ("write_disabled" if config else "migration_required")
        ),
        "write_enabled": bool(config and config["enabled"]),
        "repository_key": config["repository_key"] if config else None,
        "read_only": True,
        "repository_writes": [],
    }

@dataclass(frozen=True)
class CheckoutObservation:
    repository: str
    repository_id: int | None
    path: str | None
    available: bool
    reason: str | None
    owner: str
    next_action: str
    docs_only: bool = False
    repository_key: str | None = None

@dataclass(frozen=True)
class LogicalRepository:
    repository: str
    repository_id: int | None
    designated_path: str | None
    observations: tuple[CheckoutObservation, ...]
    available: bool
    reason: str | None
    owner: str
    next_action: str
    mutation_eligible: bool
    docs_only: bool
    repository_key: str | None = None

def deduplicate_observations(
    observations: Iterable[CheckoutObservation],
) -> list[LogicalRepository]:
    grouped: dict[tuple[str, str], list[CheckoutObservation]] = {}
    for observation in observations:
        key = (
            ("local", observation.repository_key)
            if observation.repository_key is not None
            else (
                ("id", str(observation.repository_id))
                if observation.repository_id is not None
                else ("repo", observation.repository.lower())
            )
        )
        grouped.setdefault(key, []).append(observation)
    logical: list[LogicalRepository] = []
    for rows in grouped.values():
        ordered = tuple(sorted(rows, key=lambda row: (not row.available, row.path or "")))
        current = next((row for row in ordered if row.available), ordered[0])
        docs_only = any(row.docs_only for row in ordered)
        conflict = len({row.repository.lower() for row in ordered}) > 1
        logical.append(
            LogicalRepository(
                repository=current.repository,
                repository_id=current.repository_id,
                designated_path=current.path if current.available else None,
                observations=ordered,
                available=any(row.available for row in ordered),
                reason=(
                    "identity_conflict"
                    if conflict
                    else (None if any(row.available for row in ordered) else current.reason)
                ),
                owner=current.owner,
                next_action=current.next_action,
                mutation_eligible=(
                    any(row.available for row in ordered) and not docs_only and not conflict
                ),
                docs_only=docs_only,
                repository_key=current.repository_key,
            )
        )
    return sorted(logical, key=lambda row: row.repository.lower())

def render_logical_repository(repository: LogicalRepository) -> dict[str, Any]:
    return {
        "repository": repository.repository,
        "repository_key": repository.repository_key,
        "repository_id": repository.repository_id,
        "designated_path": repository.designated_path,
        "available": repository.available,
        "reason": repository.reason,
        "owner": repository.owner,
        "next_action": repository.next_action,
        "mutation_eligible": repository.mutation_eligible,
        "docs_only": repository.docs_only,
        "checkout_count": len(repository.observations),
    }

def render_fleet_snapshot(
    repos: Iterable[LogicalRepository],
    *,
    source_revision: str,
    generated_at: str | None = None,
    source_observed_at: str | None = None,
) -> dict[str, Any]:
    observed = source_observed_at or "1970-01-01T00:00:00Z"
    return {
        "schema": "doc-warden/canvas-data/v2",
        "mode": "fleet",
        "source_revision": source_revision,
        "source_observed_at": observed,
        "generated_at": generated_at or observed,
        "repositories": [render_logical_repository(repo) for repo in repos],
        "read_only": True,
        "repository_writes": [],
        "refresh_action": (
            "bash _ops/bin/doc-warden.sh view fleet "
            "--canvas <managed-canvas-path>"
        ),
        "manage_action": "Manage doc-warden governance in chat.",
    }

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

def observation_contract(base, head_process):
    """Clone each view definition into one observation's private namespace."""
    namespace = dict(base)
    for name in ('RoadmapView', 'CheckoutObservation', 'LogicalRepository', 'BEGIN', 'END'):
        namespace[name] = globals()[name]
    namespace['subprocess'] = head_process
    for name in VIEW_FUNCTIONS:
        source = globals()[name]
        function = FunctionType(source.__code__, namespace, name, source.__defaults__, source.__closure__)
        function.__kwdefaults__ = source.__kwdefaults__
        function.__annotations__ = source.__annotations__
        namespace[name] = function
    return namespace
