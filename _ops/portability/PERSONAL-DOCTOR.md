# Scoped personal doctor

`personal_doctor.py inspect` composes the accepted personal scope, Git/worktree,
hook/memory controls, baseline, personal v3 profile, linked registry/diagnostics
and primary structural documentation components. Use Python `-I -B`. The
dependency closure rejects bytecode-writing mode and verifies its pinned source
bytes. The caller is a read-only successor to the current doctor's diagnostic
route, not an installation, repair, lifecycle or native publication command.

The default cohort is exactly the twelve personal repository IDs and paths in
the original hash-bound migration manifest. Repeated `--repository` options
select a subset of that cohort. There is no arbitrary `--root`, mixed-fleet
discovery, fetch, authentication, push, recipe execution, hook installation,
memory reconstruction, service or model-worker option. The process makes no
network requests. It does not read generated-memory bodies or adopt old global
documentation/profile/enforcement state. Primary pins and all source/configuration
bytes, indexes, object stores and existing shared links remain unchanged.

## Composition and verdicts

Each primary keeps independent identity, placement, local status, controls,
baseline and v3 profile results. The canonical repository ladder is
`OK < ADVISORY < DRIFT < VIOLATION`. Noncanonical personal email and tracked
generated memory remain violations. An unavailable component cannot erase a
separately observed violation. Documentation classifications and remote fleet
parity remain advisory observations outside that ladder, as in the owning
doctor. A dirty/detached/non-main baseline exclusion is an applicability fact,
never a claim that the five baseline files or documentation conform.

Documentation preserves the canonical primary-only loop. A linked root's
documentation is `NOT_APPLICABLE`, without opening its documentation bodies.
Linked status uses its own HEAD/index/refs, and controls use the accepted common
metadata and explicit literal-hook contracts. The canonical hook contribution
retains the owner's lexical `~/dev/personal/` and `~/dev/capabilities/` scope.
An admitted target elsewhere has class `repo`; the common-hook helper verdict
is still reported separately, while memory/AGENTS continue contributing to its
canonical controls verdict. Baseline eligibility does not acquire an invented
outside-root exclusion.

Component readers and identity/configuration facts remain fenced through the
join. Late changes hold the affected component or invalidate the joined row.
Unproven staged object responses are held and cannot restore late-invalidated
status. Explicit unknown availability is separate from known advisory/drift
results. CLI exit codes are **0** for an available report without violations,
**1** for a known violation even beside unknown evidence, and **2** for refused
or unavailable evidence otherwise. The unavailable code is an explicit safety
extension to the legacy doctor's violation-only exit policy.

Default output is the full JSON report. `--quiet` emits bounded summary JSON:
verdict counts, unavailable components and registry/boundary observations,
unresolved linked-target count, documentation/fleet classifications and distinct
pending GET count. It preserves the same availability and exit semantics. It
does not suppress unknowns or assert native or formal migration acceptance.

## Staged input and additional-root authority

`--input-stdin` accepts only this closed envelope (all five keys are required):

```json
{
  "schema": "personal-doctor-input/v1",
  "responses": null,
  "legacy_receipts": null,
  "linked": [],
  "remote": null
}
```

`responses` uses `personal-profile-responses/v1` from PERSONAL-PROFILE.md;
`legacy_receipts` uses `personal-doc-receipt-observations/v1` from
PERSONAL-DOCUMENTATION.md. Their source classification, completeness and permitted
handling remain separate owner responsibilities. Missing evidence stays unknown
when applicable; supplied empty evidence is not proof of source completeness.

Each `linked` entry has exactly `binding_text`, `binding_sha256`, `responses`.
The first is the canonical binding document described in
PERSONAL-LINKED-WORKTREE.md, encoded as a JSON string; the second is its bare
SHA-256. At most sixteen selected, nonduplicate current registry bindings are
accepted. Integrity checks and data never manufacture human consent. Before
supplying an actual extra-root binding, the owning workflow must obtain the
actual exact additional-root decision. Without that decision the migration
workflow supplies no binding and opens no target. Registry discovery alone reads
only primary/common administrative metadata and reports proposed/held targets.

Unresolved targets distinguish `proposed-uninspected`, `held-uninspected`,
`inspection-attempt-unavailable` and `partially-inspected-unavailable`.
An unavailable attempt or partial observation is never counted clean. A current
binding identifies the permitted read, not acceptance of the linked revision,
primary-pin movement, source editing or a native capability.

## Optional remote sync and selected-cohort fleet parity

`--remote` consumes staged read-only connector observations. Supplying non-null
remote input without that mode refuses before repository roots open. The remote
envelope is exactly:

```json
{
  "schema": "personal-doctor-remote-observations/v1",
  "observed_at": "2026-11-03T00:00:00+00:00",
  "requests": [
    {
      "url": "https://api.github.com/repos/KleinPerkins/skills",
      "outcome": "ok",
      "data": {"id": 0, "full_name": "KleinPerkins/skills", "default_branch": "main"}
    }
  ]
}
```

The illustrative ID is deliberately invalid; use the actual independently
observed selected-repository ID. Snapshots must be within 300 seconds, with at
most five seconds future skew, 512 requests and 16 MiB. Each entry has exactly
`url`, `outcome`, `data`; non-OK outcomes from the accepted profile protocol have
null data. Duplicate URLs, other accounts/repositories, contents/general URLs,
unqualified paths, arbitrary query strings and unused dynamic objects refuse or
hold the observation. Nothing in supplied JSON grants account access.

The parent performs only the emitted scoped GET requests through its qualified
personal connection. The process itself never authenticates or calls GitHub.
Exact repository ID/name/default-branch evidence precedes dependent reads. The
only dynamic URLs are canonically encoded observed branch names and lowercase
40-hex Git commit/tree/blob objects. Immutable tree and decoded UTF-8 blob bodies
must match their Git object hashes. No remote object becomes agent context.

For the current named branch, equal live tip projects canonical `0/0`, different
tip projects `live≠`, and inconclusive evidence retains last-fetch local tracking
with unavailable remote status. Stale local tracking notes and unpushed risk are
retained under explicit local fields; equality clears the current live unpushed
advisory. Detached HEAD falls back to local tracking without a branch request.
No local tracking result or source pin is relabeled live parity.

Fleet parity covers only the selected enrolled personal cohort: ten original
repositories are enrolled; Sterling.io and doc-warden-canary are not applicable.
It does not expand into the whole mixed or held owner fleet. The route verifies
the current merged policy, complete bounded ruleset metadata pagination, exact
central managed ruleset identity, both supplied fingerprint projections and the
current v2/epoch-1 lock contract. It requires current recipe binding, immutable
historical recipe provenance, direct controller/profile/image authority and the
exact qualified Rust validator's byte-for-byte lock recompilation. JSON metadata
comparison alone never proves lock currency. Observed full-projection equality
does not attest operator-full account visibility.

The only compiler location is
`~/.local/share/personal-portability/qualified-lock-compilers/<qualified SHA-256>/lock-compiler`,
bound by the immutable controller release. The artifact must be owned, unshared,
regular, non-aliased, mode 0500 and at most 64 MiB. It is verified before and
after use, copied to a private temporary directory, and invoked only with the
closed `validate` argument vector, clean environment and existing four-second
process/output bounds. Its only inputs are private recipe/lock copies; input
mutation holds the result. No arbitrary binary/command, download, rebuild,
platform substitution, qualification waiver or controller change is supported.
An absent or unusable exact compiler leaves lock currency `UNAVAILABLE`; an
actual owner-contract rejection is known `DRIFT`. Source acceptance of this
adapter does not qualify or install a release artifact.

The report remains bounded diagnostic evidence. Native caller qualification,
additional-root decisions, actual hook/context remediation, active-v2
documentation, full greenfield/removal lifecycle, curated distributions and all
other original required migration outcomes remain separate. Synthetic tests,
passed source checks and detached inapplicability cannot satisfy those gates.
