---
name: dev-doctor
description: Diagnose identity, placement, Git status and local controls for a selected personal repository using Dev’s read-only portability doctor.
---

# Personal repository diagnosis

For a Personal product created by `dev-new-repo --personal-codex`, select the exact owner/repository
name and run the following command from this skill's physical directory.

```sh
cd -P ../../../portability && python3 -I -B personal_doctor.py inspect-created --repository KleinPerkins/example-product
```

Report the local Git verdict, branch, pending changes, author identity and linked registration count.
Ahead and behind use local tracking refs. A null upstream leaves remote sync unknown. A recorded
GitHub repository ID describes the creator's record. Adopting the checkout needs separate live evidence.

For a checkout in the Personal migration manifest, resolve this installed skill directory to its physical source. From that directory run the owning Dev command with each selected repository named explicitly.

```sh
cd -P ../../../portability && python3 -I -B personal_doctor.py inspect-codex --repository KleinPerkins/intent-router --quiet
```

Substitute the selected repository name for the example. Omit `--quiet` for the component evidence behind a verdict.

Report the observed verdict, unavailable components and repository coverage. The portable inspector knows the source manifest’s fixed checkout locations. A moved repository can require owner reconciliation. Missing connector evidence leaves live remote parity unknown. Keep the diagnosis read-only.
