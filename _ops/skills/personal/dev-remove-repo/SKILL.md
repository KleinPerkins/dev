---
name: dev-remove-repo
description: Inspect what needs preserving before retiring a Dev-created Personal checkout. Use for an explicitly selected checkout under ~/dev/personal/src/KleinPerkins.
---

# Inspect a Personal checkout before retirement

Select one exact checkout path under `~/dev/personal/src/KleinPerkins`. If the operator gives only a name, establish the checkout path before inspecting it. Resolve this skill directory to its physical source and run the Dev tool from there.

```sh
bash ../../../bin/dev-remove-repo.sh view --personal-codex --git-state --json <checkout>
```

Report the creation binding, staged, unstaged and untracked state, linked registration count, and local Git verdict. Keep linked registrations and running writers separate. If a writer check is relevant, add `--open-files` to the same command and describe its point-in-time coverage. A repository ID in the creation record is local evidence.

Keep canonical Personal checkout work in inspection mode. If the operator requests actual retirement or recovery, give the observed preservation needs to the owning Dev workflow. The canonical view reports `removal_ready: false`; carry that result forward. If the view refuses the selection, report the reason and preserve the checkout.
