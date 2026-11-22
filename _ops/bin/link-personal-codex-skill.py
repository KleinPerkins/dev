"""Link one source-owned personal skill to its selected Codex slot."""

import os
from pathlib import Path
import sys


def link_skill(source: Path, slot: Path) -> None:
    if not (source / "SKILL.md").is_file():
        raise ValueError("personal skill descriptor is missing")
    slot.parent.mkdir(parents=True, exist_ok=True)
    try:
        slot.symlink_to(source, target_is_directory=True)
    except FileExistsError:
        if not slot.is_symlink() or os.readlink(slot) != str(source):
            raise ValueError("personal Codex skill slot is already occupied") from None


if __name__ == "__main__":
    source, slot = map(Path, sys.argv[1:])
    try:
        link_skill(source, slot)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f"personal Codex skill: {slot} -> {source}")
