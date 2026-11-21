# doc-warden v2 operator authoring interface

## Numbered architecture decisions

An adopted, enabled `.planning/doc-warden.json` repository profile is required.
The owner directory is `docs/adr`, or the flat scalar `adr_dir` value in
`.doc-warden.yml` (for this repository, `_ops/adr`). The override parser accepts
flat scalar key/value pairs and comments; collections, aliases, duplicate keys,
malformed lines, unsafe paths and symlinked targets fail closed.

Every ADR command produces a stored, reviewable preview. The existing generic
`apply` command is the only write route. These commands never implicitly apply:

```sh
bash _ops/bin/doc-warden.sh adr draft --repo /absolute/repo \
  --title 'Use the selected architecture' --body-file /absolute/body.md --preview
bash _ops/bin/doc-warden.sh adr update --repo /absolute/repo \
  --artifact-id ADR-REPOSITORY_UUID-ARTIFACT_UUID \
  --title 'Use the selected architecture' --body-file /absolute/revised-body.md --preview
bash _ops/bin/doc-warden.sh adr accept --repo /absolute/repo \
  --artifact-id ADR-REPOSITORY_UUID-ARTIFACT_UUID \
  --approval /absolute/approval.json --preview
bash _ops/bin/doc-warden.sh adr successor --repo /absolute/repo \
  --artifact-id ADR-REPOSITORY_UUID-PREDECESSOR_UUID \
  --title 'Replace the earlier decision' --body-file /absolute/replacement.md --preview
```

`approval.json` is an object with a nonempty `actor`, an ISO calendar `date`, and
`review_sha256`: the lowercase SHA-256 of the exact current draft file bytes,
without the `sha256:` prefix. Capture actual operator approval of those bytes;
creating this evidence object does not supply approval or authorize apply.
Acceptance preserves the reviewed body and freezes the semantic record.

For a new ADR whose body is already approved, `adr draft` also accepts
`--approval-file /absolute/approval.json`. In this route `review_sha256` binds the
exact UTF-8 body file bytes, before generated metadata. Explicit valid evidence
produces an `accepted_freeze` preview immediately. Omitting evidence creates an
ordinary draft with a `creation_snapshot` receipt. The resulting preview still
requires review and exact operation-bound consent.

After reviewing the preview, use its operation ID and action digest with the
existing exact consent envelope:

```sh
bash _ops/bin/doc-warden.sh apply --operation-id OPERATION_UUID \
  --action-digest sha256:PREVIEW_DIGEST --consent-envelope /absolute/consent.json
```

Draft revisions retain the UUID identity, version and filename. New decisions
allocate the next unused four-digit number across legacy and canonical files.
Accepted changes require a new successor number and UUID. A draft successor
leaves its predecessor active; accepting it changes the mutable index status,
while preserving predecessor bytes. The index remains a projection even when
co-written in an `accepted_freeze` transaction. Receipt consumers must exclude
the co-written ADR directory's `README.md` index entry when deriving frozen semantic paths; the ADR module's
`frozen_semantic_postimages` helper supplies this projection.

Preview inputs bind configuration, authorities, source revision, exact file
preimages and directory inventories. New entries can conservatively stale a
preview. Re-preview after unrelated directory changes. Interrupted apply and
replay reconstruct only exact outputs of the same operation; foreign files,
empty directories and changed output bytes are refused. Legacy prose and
receipts are read without rewriting them.

Draft, update and successor previews accept `--parents-file` for an ADR that
depends on existing approved artifacts. The JSON file contains `observed_at`
as an ISO timestamp with timezone and `parents` as a list of exact `kind`, `id`,
`version` and `digest` objects. Supported kinds are ADR, asset, design, plan,
PRD, specification and UX requirements, using their artifact type codes. The writer
resolves each active parent, verifies its freeze receipt and event, and binds
their bytes and the candidate inventory to the operation. It preserves those
typed relations on acceptance and checks the parents again. Use a draft update
to select a different parent before acceptance.

The mutable index supports exactly one `ADR | Status | One-line decision` table
or one legacy `ADR | Title | Status | Date` table. Identity cells must be exact
safe ADR basenames or same-directory Markdown links whose labels are the same
basename or four-digit number. Existing identity/date cells, unrelated rows,
the standard empty repair placeholder and surrounding prose are preserved.
Updates change only the intended title/status cells; successor acceptance
changes only its predecessor's status. New four-column rows leave Date empty
deterministically. Malformed rows/separators, multiple ADR tables, duplicate
identities/numbers, conflicting labels, unsafe links and symlinks are refused.

Python APIs mirror the CLI: `preview_adr_draft(inputs, repo=...)`,
`preview_adr_update(id, inputs, repo=...)`, `preview_adr_accept(id, approval,
repo=...)`, and `preview_adr_successor(id, inputs, repo=...)`. Inputs use `title`,
optional `body`, and (for approved creation only) optional `approval`.

## Defects without an available known-good revision

`known_good_revision` retains its existing revision string contract. When an
investigation cannot identify a working revision in the available history, the
defect may instead record an object with exactly `status: "unavailable"`, a
nonblank `reason`, and nonempty `history`. Each history entry has exactly a full
lowercase 40-character Git `revision` and a nonblank `finding`; inspected
revisions must be unique. This records investigative evidence, not proof of an
exhaustive history search. `no-head` retains its unversioned-source meaning.

An empty string can still be logged in an incomplete report, but cannot pass
triage or READY. Supply the explicit unavailable object at creation or complete
the report through the supported triage transition before symptoms freeze. The
object is bound by the existing symptom and event digests. Known-bad revision,
reproduction, acceptance, evidence and verification requirements still apply;
existing string-valued records require no migration or rewriting.

## Typed plan authority and acceptance

[ADR 0016](../../adr/0016-canonical-typed-plan-authority-and-acceptance.md),
C1–C4 (including C2a), defines the canonical typed PLAN record, its matching
governance sidecar, and the acceptance gates for new typed publications. Use that
accepted decision as authority; this section is navigation only.

The same decision preserves native phase authoring/import and native checker
obligations, frozen historical records, and consumer-owned convention decisions.
It does not qualify native execution or override a consumer's conflicting local
plan convention.

Feature spec and plan previews require a current approved PRD with matching
freeze evidence. Use `--prd-id` when more than one applies. The preview derives
its requirement IDs from that PRD. Use `--defect-id` on a plan to select the
existing READY defect route. A newly expanded defect needs feature planning.

For visual work, select `--uxr-id` and `--design-binding ID@VERSION`. Each
design must cover the applicable requirements and reference approved, immutable
assets. Use `--ui-requirement-id` to name the visual subset when the PRD also
covers nonvisual behavior. `--rigor-file` takes recorded JSON change signals
such as `sessions`, `components`, `ui_visual` and `sensitive`. A sensitive
scope requires `--sensitive-adr-id` to identify its approved decision.

Use `draft verification` and `draft uat` with an evidence file to bind outcomes
to the current approved plan, source revision, and every required ID. A visual
plan also requires exact evidence for comparison, states, accessibility,
responsive layout, copy, recovery, and assets against the approved design.
Each evidence row carries a repository-relative path, SHA-256 digest, and
result. `draft release` binds the accepted verification and UAT records to the
same plan and source revision. An approved release verifies that its pull
request delivered the declared commit to the repository’s live default branch.
Dev releases also require the enrolled originating-account review at App
approval time, App-owned merge provenance, and successful required CI for the
final PR head. The verifier reads the protected helper from the verified
squash parent on GitHub. The retained logs of the pinned Reviewer App workflow
must show admission and either a direct squash or an App-owned auto-merge
request confirmed by the PR timeline. Apply rechecks this evidence before recording an
approved release. Repositories with a different required Reviewer App policy
need a qualified owner verification route before Doc-Warden can record an
approved release. For acceptance via `--approval-file`, the
review hash covers the canonical JSON object with `kind`, `title`, `body`, and
`evidence`. Apply the resulting preview with separate exact consent.

## Authoring with a separate authority export

`prepare-authoring` can bind an explicit central owner reference tree without
copying runtime bindings into the target repository:

```sh
bash _ops/bin/doc-warden.sh prepare-authoring --repo /absolute/repository \
  --operation-id OPERATION_UUID --binding-root /absolute/owner-export
```

The repository must already have an enabled v2 profile whose GSD pin and interface
digests match that reference. The Dev reference contains the policy, schemas,
trigger catalog and exact runtime bindings. Its current plan selector binds the
approved PLAN, its governance sidecar, their accepted-freeze evidence and the
approved ADR that authorizes the selection. The caller obtains applicable root
and operation approval before using the reference.

An explicit binding produces a closed `authoring-import-preview/v2` record that
binds the canonical reference root, authority digests, observed authority inputs
and repository profile digest. Ordinary repository-local previews retain their v1 format,
including compatibility with older records lacking `active_plan_id`.

Result validation rechecks the prepared pin and interface bytes. The resulting
transaction also observes runtime bindings, unchanged inputs and frozen files;
central-reference transactions additionally observe policy/schema/catalog/plan
and profile inputs. Changes after validation refuse apply. Co-written inputs use
transaction preimages and postimages so exact receipt replay remains valid.

`validate-authoring` stores its validated transaction in the existing private
operation store and returns its expiry and consent requirement. The existing
generic `apply` route still requires fresh exact consent.

For native `*-PLAN.md` drafts, run the installed `gsd-plan-checker` role from the
exact pinned GSD package in the supported authoring client and keep its final
report private. Pass that report to `validate-authoring --native-check-report`.
Include `native_plan_check` in the result envelope with schema
`doc-warden/gsd-native-plan-check/v1`, the prepare record’s `preview_digest`,
the full `changed_file_digests` map, the role’s `descriptor_digest`, the client’s
`run_id`, the `verdict` of `VERIFICATION PASSED`, and the report’s `report_digest`.
Doc-Warden verifies the report bytes and exact bindings, then runs the installed
GSD plan-structure utility on isolated copies of the draft PLAN files. Only the
proof digest is bound to the transaction. Native authoring and review are
operator-invoked. Doc-Warden validates the supplied role evidence without
attesting the client account or launching its workflow. Drafts without native
PLAN files use the ordinary import route.

## Governed authoring continuity

Use `checkpoint`, `handoff`, `pause-with-continuity` or `resume-authoring` with
`--state`, `--event`, a fresh `--operation-id` and `--preview`. Apply the exact
operation through `apply` with its lifecycle consent envelope. An exact replay
can read that operation's committed result after expiry and after later
transitions while the live authority still matches. The first apply requires a
fresh preview and consent. Use the current closed authoring state for each new
request in the same session. Doc-Warden keeps current state and completed
receipts together in the machine-local XDG state directory. Each
checkpoint request has a typed Save-Game scope that stays stable on exact retry.

Checkpoint, handoff and pause require a qualified, enabled Save-Game owner
installation and matching Flush, Index and observation evidence. Resume
observes the saved pointer and live authority without triggering owner repair.
An incomplete result reports its recovery action and retains the prior state.
Views, normal drafting and plain pause work independently.

## Current runtime installation

Use the verified merged Dev source and its observed repository identity.
Use the Doc-Warden CLI for destination qualification and live changes. The
retained shell helper provides the pinned Cursor integration and its isolated
verification harness.
`runtime qualify-gsd` runs the existing isolated binding verifier for the
selected `--home` and `--data-home`. It binds the result to the source revision,
runtime files, toolchain and destination. Qualified operations launch the
measured Bash and expose the measured Node, npm and Python to child commands.
Then use `runtime install-gsd --preview`
for those same destinations and apply the exact consent envelope. Apply verifies
the resulting install and restores its preimage if verification fails. The
historical runtime record remains available for isolated compatibility checks.
For later removal, use `runtime uninstall-gsd --preview` for the same
destinations and apply its own exact consent envelope. A recorded removal can
replay without invoking the uninstaller again. If completion cannot be verified,
Doc-Warden reports `live_uninstall_recovery_required` and retains its private
pending operation and any available preimage record for recovery.

From the pinned source checkout, `bash _ops/bin/install-skills.sh --only doc-warden`
selects the Doc-Warden skill for the existing client discovery paths. Confirm
discovery and invocation in a fresh supported client before reporting client
qualification.
