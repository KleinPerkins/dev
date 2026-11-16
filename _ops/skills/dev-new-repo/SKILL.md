---
name: dev-new-repo
description: Scaffold a new personal repo that is born compliant under ~/dev/personal. Use when the user wants to start a new personal/KleinPerkins project, repo, or codebase. Creates a PRIVATE (default) KleinPerkins/<name> repo with an SSH origin, sets the LOCAL canonical noreply identity, installs the identity-guard pre-commit hook, and makes the initial commit through the guard — so the repo can never drift into the @affirm work-email at creation time. The proportional, single-user analog of /cpp-new.
---

# /dev-new-repo

Create a personal repo the right way, by construction. Prevents the most common source of drift
(a new repo cloned/created with the wrong identity).

## Run

```bash
cd ~/dev
bash _ops/bin/dev-new-repo.sh <name> --dry-run     # preview the exact plan (changes nothing)
bash _ops/bin/dev-new-repo.sh <name>               # create PRIVATE KleinPerkins/<name> + push
bash _ops/bin/dev-new-repo.sh <name> --public      # public instead of private
bash _ops/bin/dev-new-repo.sh <name> --no-push     # scaffold + create remote, but don't push yet
bash _ops/bin/dev-new-repo.sh <name> --no-pr-automation # explicit baseline-only compatibility spelling
```

## What it does (born compliant)
1. `~/dev/personal/<name>` + `git init -b main`
2. LOCAL identity: `user.name=KleinPerkins`, `user.email=49759187+KleinPerkins@users.noreply.github.com`
3. SSH origin `git@github.com:KleinPerkins/<name>.git`
4. installs the **identity-guard** pre-commit (so a wrong-email commit is blocked from day one)
5. renders the uniform local-file baseline. Delivery stays pending/unenrolled until
   its repository-owned CI/App admission is complete. Private creation never stages
   or enrolls the retired controller, including resumed operations.
6. initial commit through the guard, then `gh repo create` (private by default) and push.
7. records mandatory test sharding in the first commit and resume state. The initial
   contract is pending: configure at least two nonempty runnable shards covering all
   discovered tests before verification activation. Removing the current files does
   not remove the requirement recorded in bootstrap history.

## Notes
- Always offer `--dry-run` first if the user is unsure; it prints the plan and makes no changes.
- Requires `gh` authenticated as `KleinPerkins`. Refuses if the target path already exists.
- After creating, suggest `/dev-doctor` to confirm the new repo reports **OK**.
- Public visibility alone does not authorize CI/App enrollment. The exact cohort and
  immutable identity govern admission; private/no-CI exceptions remain private and
  unenrolled. The old `--pr-automation` option refuses; PAC mini actions is planned.
- Preserve meaningful nonempty sharding, automatic same-origin-account agent review,
  and App-owned delivery gates. No human technical review is required.
- The destination convention is `personal/src/<git-owner>/<repo>`. This compatibility
  scaffold must report its actual target path; do not infer it implements the later
  repo-platform layout or relocate existing checkouts as a side effect.
