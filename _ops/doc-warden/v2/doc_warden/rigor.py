"""Deterministic, explainable documentation rigor selection."""

from __future__ import annotations

from dataclasses import dataclass


BASE_ORDER = (
    "trivial_maintenance",
    "hotfix_defect",
    "small_change",
    "standard_feature",
    "multi_session_cross_component",
    "foundational_cross_repo",
)

BASE_ARTIFACTS = {
    "trivial_maintenance": ("roadmap", "verification"),
    "hotfix_defect": ("defect", "verification"),
    "small_change": ("prd", "spec", "plan", "verification"),
    "standard_feature": ("prd", "spec", "plan", "roadmap", "verification", "uat"),
    "multi_session_cross_component": (
        "prd",
        "spec",
        "context",
        "plan",
        "dependency_graph",
        "verification",
        "uat",
    ),
    "foundational_cross_repo": (
        "prd",
        "spec",
        "adr",
        "plan",
        "dependency_graph",
        "migration",
        "rollback",
        "verification",
        "release",
    ),
}


@dataclass(frozen=True)
class RigorSignals:
    change_kind: str = "maintenance"
    repositories: int = 1
    components: int = 1
    sessions: int = 1
    milestones: int = 1
    behavior_change: bool = False
    user_visible: bool = False
    contract_affecting: bool = False
    new_user_value: bool = False
    foundational: bool = False
    migration: bool = False
    public_contract: bool = False
    restores_approved_behavior: bool = False
    bounded_components: bool = True
    no_new_journey_or_contract: bool = True
    complete_defect_record: bool = True
    reversible: bool = True
    ui_visual: bool = False
    sensitive: bool = False


@dataclass(frozen=True)
class RigorDecision:
    base_class: str
    dimensions: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    matched_signals: tuple[str, ...]
    defect_exempt: bool


AUTHORING_SIGNALS = {
    "repositories": int, "components": int, "sessions": int, "milestones": int,
    "behavior_change": bool, "user_visible": bool, "contract_affecting": bool,
    "new_user_value": bool, "foundational": bool, "migration": bool, "public_contract": bool,
    "ui_visual": bool, "sensitive": bool,
}


def authoring_rigor_signals(value: object) -> dict[str, int | bool]:
    """Validate recorded authoring facts without treating unknown as false."""
    if not isinstance(value, dict) or set(value) - AUTHORING_SIGNALS.keys():
        raise ValueError("rigor_signals_invalid")
    for name, observed in value.items():
        expected = AUTHORING_SIGNALS[name]
        if type(observed) is not expected or (expected is int and observed < 1):
            raise ValueError(f"rigor_signal_invalid:{name}")
    return value


def hotfix_exemption(signals: RigorSignals) -> bool:
    return all(
        (
            signals.restores_approved_behavior,
            signals.repositories == 1 and signals.components <= 2 and signals.bounded_components,
            signals.no_new_journey_or_contract,
            signals.complete_defect_record,
            signals.reversible,
        )
    )


def compute_rigor(signals: RigorSignals) -> RigorDecision:
    matched: list[str] = []
    exempt = signals.change_kind == "defect" and hotfix_exemption(signals)
    if signals.repositories > 1 or signals.foundational or signals.migration or signals.public_contract:
        base = "foundational_cross_repo"
        matched.append("cross_repo_or_foundational")
    elif signals.sessions >= 2 or signals.components > 2 or signals.milestones > 1:
        base = "multi_session_cross_component"
        matched.append("multi_session_or_cross_component")
    elif signals.new_user_value or (signals.behavior_change and not exempt):
        base = "standard_feature"
        matched.append("new_or_material_behavior")
    elif exempt:
        base = "hotfix_defect"
        matched.append("all_hotfix_exemption_conditions")
    elif signals.user_visible or signals.contract_affecting:
        base = "small_change"
        matched.append("bounded_visible_or_contract_change")
    else:
        base = "trivial_maintenance"
        matched.append("bounded_non_behavioral_maintenance")

    dimensions: list[str] = []
    artifacts = list(BASE_ARTIFACTS[base])
    if signals.sensitive:
        dimensions.append("sensitive")
        matched.append("sensitive")
        artifacts.extend(("threat_or_privacy_decision", "security_verification"))
    if signals.ui_visual:
        dimensions.append("ui_visual")
        matched.append("ui_visual")
        artifacts.extend(("uxr", "design", "visual_asset", "accessibility", "responsive", "visual_uat"))
    return RigorDecision(
        base_class=base,
        dimensions=tuple(dimensions),
        required_artifacts=tuple(dict.fromkeys(artifacts)),
        matched_signals=tuple(matched),
        defect_exempt=exempt,
    )
