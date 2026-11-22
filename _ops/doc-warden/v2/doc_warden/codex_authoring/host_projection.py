"""Plan and reconcile the four project-scoped Codex skill descriptors."""

from __future__ import annotations

from pathlib import Path
import shlex
import stat

from ..canonical import atomic_write, contained_path, digest_ref


SKILL_PURPOSE = {
    "gsd-new-project": "Draft the project brief, requirements, roadmap and state with the operator.",
    "gsd-discuss-phase": "Work through a roadmap phase with the operator and draft its context.",
    "gsd-plan-phase": "Draft a roadmap phase plan and obtain an independent authoring check.",
    "gsd-validate-phase": "Review a phase against its plan and draft its validation record.",
}
PROJECTION_PATHS = tuple(f".agents/skills/{name}/SKILL.md" for name in SKILL_PURPOSE)
FILE_MODE = 0o600


def render_descriptors(entrypoint: Path) -> dict[str, bytes]:
    """Keep discovery as a thin route to the one portable import mechanism."""
    if not entrypoint.is_absolute() or any(ord(char) < 32 for char in str(entrypoint)):
        raise ValueError("native_authoring_entrypoint_invalid")
    executable = shlex.quote(str(entrypoint))
    return {
        f".agents/skills/{name}/SKILL.md": (
            f"---\nname: {name}\ndescription: {purpose}\n---\n"
            f"Use `{executable} runtime author-codex --project . --skill {name}` from this project. "
            "Gather the relevant operator decisions in a private brief outside the project and "
            "pass it with --operator-input. Use --argument=VALUE for each supplied GSD argument. "
            "Preserve the operator's actual decisions and arguments. "
            "Use its admission result to continue the conversation. "
            "Present the returned draft preview and obtain its exact consent before applying it.\n"
        ).encode()
        for name, purpose in SKILL_PURPOSE.items()
    }


def _file_image(path: Path) -> str | None:
    if not path.exists():
        return None
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != FILE_MODE or info.st_size > 16 * 1024):
        raise ValueError("native_authoring_projection_foreign")
    return digest_ref(path.read_bytes())


def observe_descriptors(project: Path) -> dict[str, str | None]:
    return {
        path: _file_image(contained_path(project, path))
        for path in PROJECTION_PATHS
    }


def descriptor_images(descriptors: dict[str, bytes]) -> dict[str, str | None]:
    if descriptors and set(descriptors) != set(PROJECTION_PATHS):
        raise ValueError("native_authoring_projection_invalid")
    return {
        path: digest_ref(descriptors[path]) if path in descriptors else None
        for path in PROJECTION_PATHS
    }


def apply_descriptors(
    project: Path,
    *,
    before: dict[str, str | None],
    descriptors: dict[str, bytes],
) -> None:
    """Reconcile exact preimages/postimages under an already journaled writer."""
    after = descriptor_images(descriptors)
    found = observe_descriptors(project)
    if set(before) != set(found) or any(found[path] not in (before[path], after[path]) for path in found):
        raise ValueError("native_authoring_projection_foreign")
    for path, observed in found.items():
        destination = contained_path(project, path)
        if _file_image(destination) != observed:
            raise ValueError("native_authoring_projection_changed")
        if observed == after[path]:
            continue
        if after[path] is None:
            destination.unlink()
        else:
            atomic_write(project, path, descriptors[path])
    if observe_descriptors(project) != after:
        raise ValueError("native_authoring_projection_readback_failed")
