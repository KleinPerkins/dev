---
name: dev-new-repo
description: Start a new KleinPerkins personal product in the canonical owner checkout directory using Dev’s born-v2 scaffold.
---

# Create a personal product repository

Resolve this installed skill directory to its physical source. From that directory, preview the exact name and visibility the operator selected.

```sh
bash ../../../bin/dev-new-repo.sh --personal-codex <name> --dry-run
```

The preview shows the local checkout under `~/dev/personal/src/KleinPerkins`, the GitHub destination and the delivery gates. A new product defaults to private. For an authorized creation, supply a unique `DEV_SESSION_ID` for this writer and repeat the command without `--dry-run`. Public creation requires the operator’s explicit public foundation decision. `--no-push` still creates the remote.

Use `--resume` on the same checkout after an interruption. Report the operation’s actual commit, Doc-Warden status, sharding requirement and remaining delivery admission. An occupied name with no matching operation requires adoption or owner reconciliation.

For a disposable local exercise, create an empty `personal/src/KleinPerkins` directory inside a new system temporary directory. Pass that temporary directory via `--fixture-root` throughout the exercise. With no fixture repository ID the scaffold stops after the guarded local commit.
