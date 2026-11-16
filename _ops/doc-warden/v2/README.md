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

## Authoring with a separate authority export

`prepare-authoring` can bind an explicit central owner reference tree without
copying runtime bindings into the target repository:

```sh
bash _ops/bin/doc-warden.sh prepare-authoring --repo /absolute/repository \
  --operation-id OPERATION_UUID --binding-root /absolute/owner-export
```

The repository must already have an enabled v2 profile whose GSD pin and interface
digests match that reference. The reference must contain the policy, schemas,
trigger catalog, approved plan and exact runtime bindings. Missing authority does
not become a zero-digest fallback. This option neither adopts a repository nor
grants permission to read another root; the caller obtains applicable root and
operation approval before using it.

An explicit binding produces a closed `authoring-import-preview/v2` record that
binds the canonical reference root, complete authority digests and repository
profile digest. Ordinary repository-local previews retain their v1 format,
including compatibility with older records lacking `active_plan_id`.

Result validation rechecks the prepared pin and interface bytes. The resulting
transaction also observes runtime bindings, unchanged inputs and frozen files;
central-reference transactions additionally observe policy/schema/catalog/plan
and profile inputs. Changes after validation refuse apply. Co-written inputs use
transaction preimages and postimages so exact receipt replay remains valid.

`validate-authoring` stores its validated transaction in the existing private
operation store and returns its expiry and consent requirement. The existing
generic `apply` route still requires fresh exact consent. Preparing or validating
does not invoke a native workflow, worker, installer or repository write. These
authoring contracts make no autonomous-execution or same-user security-boundary
claim.
