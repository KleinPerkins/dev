"""Safe discovery of canonical artifacts in planning and owner ADR roots."""
from __future__ import annotations

import re
from pathlib import Path
from .canonical import contained_path

ADR_NAME = re.compile(r"(?P<number>[0-9]{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md")


def adr_directory(repo: Path) -> str:
    """Read the existing flat local override format without a YAML dependency.

    Only flat scalar pairs are supported. Reject YAML collections, aliases,
    duplicate keys and indentation rather than silently interpreting them.
    """
    path = contained_path(repo, ".doc-warden.yml")
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([a-z_]+):\s*(.*?)\s*", line)
            if not match or match[1] in values:
                raise ValueError("adr_config_invalid")
            value = match[2]
            if value.startswith(('"', "'")):
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise ValueError("adr_config_invalid")
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].rstrip()
            if not value or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None:
                raise ValueError("adr_config_invalid")
            values[match[1]] = value
    relative = values.get("adr_dir", "docs/adr")
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or Path(relative).as_posix() != relative or relative in {".", ""}):
        raise ValueError("adr_directory_invalid")
    # contained_path expects a regular-file leaf; a synthetic leaf validates
    # the directory itself and every existing ancestor without creating it.
    contained_path(repo, relative + "/.adr-probe")
    return relative


def artifact_paths(repo: Path):
    """Yield canonical records; legacy ADR prose is never parsed as metadata."""
    repo = repo.resolve(strict=True)
    owner = adr_directory(repo)
    seen = set()
    for relative in (".planning/artifacts", owner):
        contained_path(repo, relative + "/.artifact-probe")
        root = repo / relative
        if not root.exists():
            continue
        for path in sorted(root.glob("*.md")):
            contained_path(repo, path.relative_to(repo).as_posix())
            if path in seen:
                continue
            seen.add(path)
            if relative == owner:
                if path.name == "README.md":
                    continue
                raw = path.read_text(encoding="utf-8")
                # Metadata-bearing ADRs must parse, even if their metadata is
                # malformed; legacy numbered prose remains untouched.
                if not raw.startswith("---"):
                    if "doc-warden/artifact/" in raw:
                        raise ValueError("artifact_state_invalid")
                    continue
                if ADR_NAME.fullmatch(path.name) is None:
                    raise ValueError("adr_filename_invalid")
            yield path
