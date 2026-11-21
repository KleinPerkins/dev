---
name: doc-warden
description: Route documentation governance and authoring continuity requests to Doc-Warden views, validated previews, and the confirmation-bound CLI.
---

# /doc-warden

Use this thin operator layer when someone asks about plans, ADRs, runbooks,
documentation ownership, roadmap priority or sequence, governance health, drift, or
safe repair. Ordinary language and explicit CLI use the same closed intent map.
The implementation and policy remain in `_ops/doc-warden/`; this skill does not
restate or decide them.

Resolve this installed skill to its source directory. Use the absolute path to
`_ops/bin/doc-warden.sh` from that same source tree and run it from the target
repository. The examples use the short path from a Dev checkout.

## Ordinary-language routes

| Say this | Exact CLI equivalent |
|---|---|
| `What are we working on?` | `bash _ops/bin/doc-warden.sh view repo` |
| `Show everything across repos.` | `bash _ops/bin/doc-warden.sh view fleet` |
| `Draft the PRD.` | `bash _ops/bin/doc-warden.sh draft prd --title <title> --preview` |
| `Draft the spec.` | `bash _ops/bin/doc-warden.sh draft spec --title <title> --preview` |
| `Draft the plan.` | `bash _ops/bin/doc-warden.sh draft plan --title <title> --preview` |
| `Log this bug.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Log this bug."` |
| `Update the design.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Update the design."` |
| `Make this P0.` | `bash _ops/bin/doc-warden.sh prioritize <roadmap-id> <P0\|P1\|P2\|P3> --preview` |
| `Do this after X.` | `bash _ops/bin/doc-warden.sh sequence <roadmap-id> --after <roadmap-id> --preview` |
| `What drifted?` | `bash _ops/bin/doc-warden.sh reconcile --preview` |
| `Apply the safe repairs.` | `bash _ops/bin/doc-warden.sh apply --operation-id <operation-id> --action-digest <action-digest> --consent-envelope <regular-file-path>` |
| `Is governance healthy?` | `bash _ops/bin/doc-warden.sh doctor repo` |
| `Is fleet governance healthy?` | `bash _ops/bin/doc-warden.sh doctor fleet` |
| `Start the work.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Start the work."` |
| `Pause here.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Pause here."` |
| `Resume the work.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Resume the work."` |
| `Verify this.` | `bash _ops/bin/doc-warden.sh v2-preview intent "Verify this."` |

For an explicit authoring checkpoint, handoff, pause with continuity, or resume,
run `bash _ops/bin/doc-warden.sh intent "<request>"` and use its exact CLI
equivalent. Bind the current authoring state and event files to a new operation
ID. Apply only after exact consent, and use the engine's returned state.
Ordinary drafting, views, and a plain pause require no Save-Game call.

## Routing boundary

- The intent router returns a **proposal**, never authorization.
- Read-only routes run without a confirmation nag.
- Consequential routes first produce a validated preview. Any later consent must be
  fresh, explicit, and operation-bound to the preview's operation ID and action digest.
- If one utterance matches routes with different consequences, do not choose. State
  the alternatives and ask for one route.
- Semantic and structural changes stay on the validated engine/CLI path; the skill
  never edits governance artifacts directly.

## Failure and escalation copy

Use plain language with all three facts:

> I checked `<observed sources>`. `<missing or unavailable facts>` are uncertain.
> Next action: `<one concrete recovery step>`.

Never report a failure without saying what was **checked**, what remains **uncertain**,
and the **next action**. Never turn uncertainty into authorization.

## Explicit structural compatibility

The historical structural checker remains available:

```bash
bash _ops/bin/doc-warden.sh check <repo>
bash _ops/bin/doc-warden.sh repair <repo> --dry-run
```

Use the dry-run output and the active policy for any subsequent approved repair. Do
not infer approval from this skill.
