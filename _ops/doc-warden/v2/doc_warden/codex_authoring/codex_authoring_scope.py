"""Resolve bounded Codex authoring routes before starting a native worker."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from ..canonical import contained_path, digest_ref


PHASE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){0,2}")
PHASE_DIRECTORY = re.compile(r"([0-9]{1,3}(?:\.[0-9]{1,3}){0,2})-[a-z0-9]+(?:-[a-z0-9]+)*")
PROJECT_OUTPUTS = (
    ".planning/PROJECT.md",
    ".planning/config.json",
    ".planning/REQUIREMENTS.md",
    ".planning/ROADMAP.md",
    ".planning/STATE.md",
)
PHASE_OUTPUTS = {
    "gsd-discuss-phase": "CONTEXT",
    "gsd-plan-phase": "PLAN",
    "gsd-validate-phase": "VALIDATION",
}
PROJECT_ROLES = ("gsd-project-researcher", "gsd-research-synthesizer", "gsd-roadmapper")
MAX_INPUT_FILES = 32
MAX_INPUT_BYTES = 512 * 1024


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("native_authoring_arguments_invalid")


@dataclass(frozen=True)
class NativeAuthoringScope:
    skill: str
    phase: str | None
    mode: str
    input_digests: tuple[tuple[str, str], ...]
    output_paths: tuple[str, ...]
    roles: tuple[str, ...]


def _phase(value: str) -> tuple[int, ...]:
    if not PHASE.fullmatch(value) or any(int(part) == 0 for part in value.split(".")):
        raise ValueError("native_authoring_phase_invalid")
    return tuple(map(int, value.split(".")))


def _selected_phase(repo: Path, requested: str | None) -> tuple[str, str]:
    marker = contained_path(repo, ".planning/phases/.doc-warden-scope")
    if not marker.parent.is_dir():
        raise ValueError("native_authoring_phase_unavailable")
    choices = {}
    for path in marker.parent.iterdir():
        match = PHASE_DIRECTORY.fullmatch(path.name)
        if match and path.is_dir() and not path.is_symlink():
            number = _phase(match[1])
            if number in choices:
                raise ValueError("native_authoring_phase_ambiguous")
            choices[number] = (match[1], path.relative_to(repo).as_posix())
    if not choices:
        raise ValueError("native_authoring_phase_unavailable")
    if requested is None:
        if len(choices) != 1:
            raise ValueError("native_authoring_phase_required")
        return next(iter(choices.values()))
    if _phase(requested) not in choices:
        raise ValueError("native_authoring_phase_unavailable")
    return choices[_phase(requested)]


def _bound_inputs(repo: Path, selector: str, *, allow_glob: bool) -> tuple[tuple[str, str], ...]:
    path = PurePosixPath(selector)
    if (path.is_absolute() or selector != path.as_posix() or ".." in path.parts
            or len(selector) > 240 or not re.fullmatch(r"[-a-zA-Z0-9_.,/\[\]*? ]+", selector)
            or "**" in selector or any(char in str(path.parent) for char in "*?[]")
            or (not allow_glob and any(char in selector for char in "*?[]"))):
        raise ValueError("native_authoring_input_invalid")
    parent_name = path.parent.as_posix()
    parent = repo if parent_name == "." else contained_path(repo, parent_name + "/.doc-warden-scope").parent
    if not parent.is_dir():
        raise ValueError("native_authoring_input_missing")
    matches = []
    for candidate in parent.glob(path.name):
        if len(matches) == MAX_INPUT_FILES:
            raise ValueError("native_authoring_input_bound_exceeded")
        if candidate.is_symlink() or candidate.suffix != ".md":
            raise ValueError("native_authoring_input_invalid")
        relative = candidate.relative_to(repo).as_posix()
        admitted = contained_path(repo, relative)
        if not admitted.is_file() or admitted.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("native_authoring_input_invalid")
        data = admitted.read_bytes()
        if len(data) > MAX_INPUT_BYTES:
            raise ValueError("native_authoring_input_bound_exceeded")
        matches.append((relative, digest_ref(data)))
    if not matches:
        raise ValueError("native_authoring_input_missing")
    return tuple(sorted(matches))


def scope(repo: Path, skill: str, arguments: list[str]) -> NativeAuthoringScope:
    repo = repo.resolve(strict=True)
    if skill not in PHASE_OUTPUTS and skill != "gsd-new-project":
        raise ValueError("native_authoring_skill_unavailable")
    if len(arguments) > 4 or any(type(arg) is not str or len(arg) > 240 for arg in arguments):
        raise ValueError("native_authoring_arguments_invalid")
    parser = _Parser(add_help=False, allow_abbrev=False)
    if skill != "gsd-new-project":
        parser.add_argument("phase", nargs="?")
    if skill != "gsd-validate-phase":
        parser.add_argument("--auto", action="store_true")
    if skill == "gsd-plan-phase":
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--research", action="store_true")
        mode.add_argument("--skip-research", action="store_true")
        mode.add_argument("--prd")
        mode.add_argument("--ingest")
    parsed = parser.parse_args(arguments)
    if getattr(parsed, "auto", False):
        raise ValueError("native_authoring_auto_advance_refused")
    if skill == "gsd-new-project":
        return NativeAuthoringScope(skill, None, "guided", (), PROJECT_OUTPUTS, PROJECT_ROLES)
    phase, directory = _selected_phase(repo, parsed.phase)
    if skill == "gsd-discuss-phase":
        return NativeAuthoringScope(skill, phase, "guided", (),
                                    (f"{directory}/{phase}-CONTEXT.md",), ())
    if skill == "gsd-validate-phase":
        return NativeAuthoringScope(skill, phase, "guided", (),
                                    (f"{directory}/{phase}-VALIDATION.md",), ("gsd-nyquist-auditor",))
    selected = "research" if parsed.research else "skip-research" if parsed.skip_research else "guided"
    inputs = ()
    if parsed.prd is not None:
        selected, inputs = "prd", _bound_inputs(repo, parsed.prd, allow_glob=False)
    elif parsed.ingest is not None:
        selected, inputs = "ingest", _bound_inputs(repo, parsed.ingest, allow_glob=True)
    roles = ("gsd-planner", "gsd-plan-checker")
    if selected != "skip-research":
        roles = ("gsd-phase-researcher",) + roles
    return NativeAuthoringScope(skill, phase, selected, inputs, (f"{directory}/{phase}-*-PLAN.md",), roles)
