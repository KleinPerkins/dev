# ADR 0005: Harden context measurement before E-09
Status: accepted — 2026-08-16

**Decider:** Laurence Duggan
**Owning repository:** `KleinPerkins/dev`
**Supersedes:** [ADR 0004](0004-optimize-context-projections-without-moving-authority.md) as the active Context Efficiency Program decision. ADR 0004 remains an immutable historical record.
**Related plan:** [Context Efficiency Program v2](../plans/context-efficiency-program-v2.md)
**Operator decision:** “Proceed with recommended plan, first step being the corrected ADR and updated plan … Put all important findings and instructions on disk within the context of an accepted doc-warden artifact.” This accepts this decision and the related plan as documentation; it does not authorize implementation, machine-local mutation, a release, or E-09.

## Context

ADR 0004 and Context Efficiency Program v1 were accepted by
[`KleinPerkins/dev` PR #264](https://github.com/KleinPerkins/dev/pull/264),
squash merge `0818be2f3beb0bfafaa17abd6250e780f87a19a1`. ADR 0004
correctly chose projection-first optimization, distributed source authority,
deterministic evidence, and a separate private operator gate for learned data.
Those decisions remain sound. The separate
`kp-context-measurement-v1-tooling-v1.md` plan was accepted by
[`KleinPerkins/dev` PR #269](https://github.com/KleinPerkins/dev/pull/269),
squash merge `47308080f9a6fb82275a557434638b9d4bf3c8e2`. Its implementation
then merged in
[`KleinPerkins/dev` PR #270](https://github.com/KleinPerkins/dev/pull/270),
squash merge `28bfd06093d4fed84d2862f52aac2be8a3fa812b`.

The implementation is useful but not safe enough to produce the authoritative E-09 denominator:

- the binding parent program says entries are ordered by unique projection ID, while the accepted child tooling plan and implementation preserve caller manifest order;
- malformed projection entries and malformed receipts can raise Python tracebacks and exit `1`;
- `argparse` exits `2`, colliding with the documented `BLOCKED_PREREQUISITE` class;
- unknown `select` fields are copied into receipts, so an unrecognized value can escape into supposedly content-safe evidence;
- equal or overlapping region markers are accepted as successful regions;
- receipt validation is open and shallow, so comparison can accept or crash on structurally invalid evidence; and
- the runnerless PR recipe executes the repository contract plus
  `bash _ops/checks/doc-warden-verify.sh --sandbox`, not the focused measurement suite. The five green Check Runs on PR #270 therefore do not prove the measurement tests ran remotely.

Fresh exact-head verification of PR #270’s head
`39f217939598af6583cba65cbce415eed5a1ac99` produced:

- `16/16` focused unit tests passing;
- byte-identical output across processes and working directories;
- unchanged measured-file inode, mode, size, mtime, and digest;
- projection order `["z", "a"]` for an input whose canonical ID order is `["a", "z"]`;
- exit `1` plus traceback for a `null` projection;
- successful receipt output containing an unknown-field sentinel;
- exit `1` plus traceback for malformed receipts;
- exit `2` for missing compare arguments; and
- successful measurement for equal and overlapping marker pairs.

No authoritative `static-context-manifest/v1` receipt exists. E-09 remains unfrozen, so there is no valid compatibility reason to preserve unsafe v1 wire receipts.

ADR 0004 and the accepted program plan also contain stale “draft” / “acceptance outstanding” wording after their 2026-08-15 acceptance. Their bytes remain immutable; this successor records current governance instead of rewriting history.

## Decision

Carry forward ADR 0004’s distributed authority, projection-first optimization, privacy boundary, and two-layer verification model. Replace its measurement and execution-governance clauses with the decisions below.

### 1. Authority hierarchy is explicit

For this program, conflicts resolve in this order:

1. current repository policy and doc-warden lifecycle rules;
2. this accepted ADR;
3. the accepted Context Efficiency Program v2 plan;
4. accepted owner-repository child plans, which may refine but not contradict the parent contract;
5. current implementation, tests, and READMEs as evidence of built behavior; and
6. historical accepted ADR 0004 and plan v1.

A narrower child plan cannot reverse parent ordering, privacy, schema, or gate semantics. If a future need requires that change, it must supersede this ADR and the active program plan.

### 2. The counting algorithm remains `kp-context-measurement/v1`

The accepted counting rules do not change:

- read raw bytes and record SHA-256;
- decode strict UTF-8;
- normalize `CRLF` to `LF`, then remaining `CR` to `LF`, with no other Unicode or whitespace normalization;
- count Unicode scalar values as characters;
- count maximal non-whitespace runs using the pinned Unicode 15.0 `White_Space` set; and
- include projected frontmatter, delimiters, and region boundaries.

The defect is in ordering, input validation, receipt identity, and error handling—not in these counting primitives.

### 3. Projection order is canonical, not caller-controlled

`projections[]` input order is non-semantic. After full validation, entries are sorted by unique `projection_id` in ascending UTF-8 byte order. Projection IDs use the ASCII token grammar
`^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$`, so UTF-8 byte order and Unicode-scalar order are identical.

The canonical order controls measurement, `projection_order`, per-projection receipt rows, totals, receipt identity, and comparison. Duplicate IDs are a usage error. This implements the binding parent authority and supersedes the child-plan/code behavior that preserved manifest order.

### 4. Input and output schemas are closed and versioned independently

The counting algorithm stays v1; unsafe wire shapes do not.

#### Input manifest

The only accepted manifest schema is `kp-context-measurement-input/v2`.

Top-level keys are exactly:

- `schema`;
- `client_root_class`;
- `baseline_id`; and
- `projections`.

Each projection has exactly:

- `projection_id`;
- `path`; and
- `select`.

`select` is exactly one of:

```json
{"kind": "full"}
```

or:

```json
{"kind": "region", "begin": "nonempty marker", "end": "different nonempty marker"}
```

Unknown keys are rejected at every level. `client_root_class` and `baseline_id` use the same ASCII token grammar as `projection_id`. `projections` is nonempty. `path` is a nonempty Unicode-scalar string without NUL and is retained byte-for-byte as the logical receipt descriptor.

Absolute paths are opened as written; relative paths are opened relative to the process working directory. The implementation follows symlinks only when the final open target is a regular file; a missing, unreadable, or non-regular target is `PATH_UNREADABLE`. This tool does not assert a security root. An E-09 caller therefore uses stable logical paths from one controlled working directory and separately proves owner/source identity in the static manifest.

Marker strings are nonempty Unicode-scalar strings and must differ. They are matched against strict-UTF-8-decoded text **before** newline normalization. Marker SHA-256 values use the exact marker string encoded as UTF-8.

The CLI remains:

```text
kp_context_measure.py measure --manifest PATH
kp_context_measure.py measure --path FILE --projection-id ID \
  --client-root-class CLASS --baseline-id ID \
  [--region-begin TEXT --region-end TEXT]
kp_context_measure.py compare --baseline RECEIPT --candidate RECEIPT
```

`measure` requires exactly one of `--manifest` and `--path`. The two region flags are an all-or-none pair. Single-path mode builds and validates the same v2 in-memory entry as manifest mode. There is no output-file flag; JSON goes to stdout and a caller may redirect it. `--help` exits `0`. No network, write, root, migration, or permissive-mode flag exists.

#### Measurement receipt

Successful and blocked measurements emit only
`kp-context-measurement-receipt/v2`. Its top-level keys are exactly:

- `schema`;
- `algorithm`;
- `tool`;
- `tool_contract`;
- `whitespace_set_version`;
- `status`;
- `client_root_class`;
- `baseline_id`;
- `projection_order`;
- `projections`; and
- `totals`.

The v2 producer always emits:

```text
schema = kp-context-measurement-receipt/v2
algorithm = kp-context-measurement/v1
tool = kp_context_measure
tool_contract = kp-context-measurement-tool/v2
whitespace_set_version = unicode-15.0-White_Space
```

For comparison only, closed structural validation accepts nonempty ASCII-token strings in `algorithm`, `tool_contract`, and `whitespace_set_version` so incompatibility can be classified without indexing unsafe fields. This does not make an alternate identity supported: each side is separately checked against the producer values and refused when unsupported. `schema` and `tool` remain exact constants.

Each projection row has exactly:

- `projection_id`;
- `path`;
- `select`;
- `status`;
- `failure_class`;
- `raw_sha256`;
- `normalized_sha256`;
- `bytes`;
- `characters`; and
- `words`.

Receipt `select` never repeats marker text. A full selection emits only
`{"kind":"full"}`. A region emits
`{"kind":"region","begin_sha256":"...","end_sha256":"..."}`.
The digests bind marker identity without copying marker values into evidence.

Closed status/failure rules are:

- receipt and entry `status` are only `OK` or `BLOCKED_PREREQUISITE`;
- `failure_class` is `null` for `OK`, otherwise exactly one of
  `PATH_UNREADABLE`, `INVALID_UTF8`, `REGION_NOT_FOUND`,
  `REGION_AMBIGUOUS`, or `REGION_MISORDERED`;
- an `OK` row has two lowercase 64-hex digests and nonnegative integer
  `bytes`, `characters`, and `words`;
- `PATH_UNREADABLE` and every region failure have all digests/counts `null`;
- `INVALID_UTF8` has `raw_sha256` and `bytes` for the raw file and has
  `normalized_sha256`, `characters`, and `words` `null`;
- the receipt is `OK` only when every row is `OK`; then `totals` is exactly
  `{"bytes":N,"characters":N,"words":N}` and equals the row sums;
- if any row is blocked, measurement still evaluates every canonical row,
  receipt status is `BLOCKED_PREREQUISITE`, and `totals` is `null`; and
- JSON integers exclude booleans.

The implementation validates every cross-field invariant, digest format, canonical order, unique ID, exact total, and exact key set.

Wire JSON is UTF-8 text produced by
`json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"`.
This pretty, ASCII-escaped, LF-terminated form is canonical for v2.

#### Comparison receipt

Comparison emits only `kp-context-measurement-comparison/v2`.

Success has exactly:

- `schema`, `algorithm`, `tool`, `tool_contract`,
  `whitespace_set_version`, and `status`;
- `baseline_id`, `client_root_class`, and `projection_order`;
- `baseline_totals`, `candidate_totals`, and `delta`; and
- `target_30pct`.

Fixed values match the measurement receipt and `status` is `OK`. The three totals objects each have exactly `bytes`, `characters`, and `words`; delta is candidate minus baseline. `target_30pct` has exactly
`max_characters`, `max_words`, `meets_characters`, and `meets_words`, using `floor(baseline * 70 / 100)` integer arithmetic.

Refusal has exactly:

```json
{
  "reasons": ["FIXED_ENUM"],
  "schema": "kp-context-measurement-comparison/v2",
  "status": "COMPARISON_REFUSED"
}
```

The nonempty, sorted, deduplicated reason list uses only:

- `BASELINE_RECEIPT_UNREADABLE`;
- `CANDIDATE_RECEIPT_UNREADABLE`;
- `BASELINE_RECEIPT_INVALID`;
- `CANDIDATE_RECEIPT_INVALID`;
- `UNSUPPORTED_RECEIPT_SCHEMA`;
- `BASELINE_ALGORITHM_UNSUPPORTED`;
- `CANDIDATE_ALGORITHM_UNSUPPORTED`;
- `BASELINE_TOOL_CONTRACT_UNSUPPORTED`;
- `CANDIDATE_TOOL_CONTRACT_UNSUPPORTED`;
- `BASELINE_WHITESPACE_SET_UNSUPPORTED`;
- `CANDIDATE_WHITESPACE_SET_UNSUPPORTED`;
- `ALGORITHM_MISMATCH`;
- `TOOL_CONTRACT_MISMATCH`;
- `WHITESPACE_SET_MISMATCH`;
- `BASELINE_NOT_OK`;
- `CANDIDATE_NOT_OK`;
- `CLIENT_ROOT_CLASS_MISMATCH`;
- `BASELINE_ID_MISMATCH`;
- `PROJECTION_ORDER_MISMATCH`; and
- `PROJECTION_DESCRIPTOR_MISMATCH`.

Neither shape copies malformed input values.

### 5. Invalid or unknown fields never echo their values

Manifest and receipt validators report only fixed error classes and bounded structural locations such as `manifest`, `projection`, `select`, `baseline_receipt`, or `candidate_receipt`. They do not print unknown key names, unknown values, decoded source text, marker text, JSON fragments, Python exception strings, or tracebacks.

Valid caller identifiers and paths may appear in a valid measurement receipt as specified above. Invalid values never do.

Usage failures write exactly one LF-terminated stderr line and no stdout:

```text
kp_context_measure: USAGE_ERROR: LOCATION: ERROR_CLASS
```

`LOCATION` is one of `cli`, `manifest`, `projection`, or `select`.
`ERROR_CLASS` is one of `CLI_ARGUMENTS`, `MANIFEST_UNREADABLE`,
`MANIFEST_INVALID_UTF8`, `MANIFEST_INVALID_JSON`, `MANIFEST_SCHEMA`, or
`MANIFEST_VALUE`. Help is not a failure. Successful/blocked measurement and every comparison write no stderr.

### 6. Region selection has one unambiguous interpretation

Count every occurrence start, including overlapping occurrences, for each marker.

1. Equal begin/end marker values are a manifest usage error.
2. If either marker occurs zero times, return `REGION_NOT_FOUND`.
3. If either marker occurs more than once, return `REGION_AMBIGUOUS`.
4. With one occurrence each, require
   `end_start >= begin_start + len(begin)`.
   End-before-begin and overlapping intervals return `REGION_MISORDERED`.
5. Adjacent, non-overlapping markers are valid.
6. The selected region starts at the begin marker and ends after the end marker, so both markers are included.

The failure precedence above is fixed and tested.

### 7. Caller-controlled failures use only exits `0`, `2`, `3`, and `4`

| Exit | Meaning |
|---|---|
| `0` | Measurement or comparison succeeded. |
| `2` | A valid measurement request hit a content/path/region prerequisite; a closed blocked receipt is emitted. |
| `3` | CLI grammar, manifest file, JSON, UTF-8, schema, or value validation failed; fixed stderr diagnostic, no receipt. |
| `4` | Comparison could not safely proceed; a closed refusal receipt is emitted. |

`argparse` is wrapped so parser errors exit `3`. Unreadable, invalid-UTF-8, invalid-JSON, legacy, open-schema, or cross-field-invalid comparison receipts all exit `4`, not `1`. No caller-controlled input may produce a traceback or another exit.

### 8. Comparison validates before indexing and refuses unsafe identity

Both receipts are fully validated before any totals or projection field is read. Comparison refuses on:

- unreadable or malformed receipt;
- unsupported receipt schema, including every v1 receipt;
- algorithm, tool-contract, or whitespace-set mismatch;
- non-`OK` measurement status;
- client/root class or baseline ID mismatch;
- canonical projection-order mismatch;
- projection descriptor mismatch across ordered
  `(projection_id, path, select)` tuples; or
- invalid totals, digests, status/nullability, or cross-field arithmetic.

Content digests and counts may differ—that is what comparison measures. Identity descriptors may not.

Reason derivation is deterministic:

1. classify each OS read failure as side-specific `*_RECEIPT_UNREADABLE`;
2. classify invalid UTF-8/JSON/non-object/missing-schema as side-specific
   `*_RECEIPT_INVALID`;
3. classify a present non-v2 schema as `UNSUPPORTED_RECEIPT_SCHEMA`;
4. when both sides are closed structurally valid v2 receipts, classify each non-current identity with its side-specific `*_UNSUPPORTED` reason and classify differences with the corresponding `*_MISMATCH` reason;
5. evaluate status/workload mismatches only after structural validity; and
6. sort/deduplicate the resulting fixed enums.

An earlier class prevents later field indexing for that side. Refusal still reports independent failures from both sides.

There is no v1 receipt migration or permissive compatibility flag. A caller must remeasure with the v2 contract. This is safe because E-09 has not frozen a receipt.

### 9. Correction dogfood uses one durable content-safe record

Post-merge synthetic dogfood is a prerequisite for owner-repository work, so
its successful result cannot live only in chat, a local file, or an optional PR
comment. Dev owns one bounded evidence artifact:

```text
_ops/evidence/context-efficiency/correction-dogfood-v1.json
```

Its exact top-level keys are:

- `schema`, `status`, `classification`, and `captured_at_utc`;
- `implementation_commit`, `implementation_tree`, `algorithm`, and
  `tool_contract`;
- `environment_class` and `command_set`;
- `fixture_manifest_sha256`, `run_a_receipt_sha256`,
  `run_b_receipt_sha256`, `pre_stats_sha256`, and `post_stats_sha256`;
- `observed_exits`; and
- `content_safety`.

Fixed values are:

```text
schema = kp-context-measurement-correction-evidence/v1
status = PASS
classification = CORRECTION_PROVEN_NOT_E09
algorithm = kp-context-measurement/v1
tool_contract = kp-context-measurement-tool/v2
environment_class = macos-bash3-stdlib
command_set = kp-context-measurement-correction-dogfood/v1
```

The timestamp uses UTC `YYYY-MM-DDTHH:MM:SSZ`; Git IDs are lowercase 40-hex;
all digest fields are lowercase 64-hex. `observed_exits` has exactly
`measure_a`, `measure_b`, `compare_compatible`, `compare_incompatible`,
`blocked`, and `usage`, with values `0`, `0`, `0`, `4`, `2`, and `3`.
`content_safety` has exactly `sentinel_absent`, `source_content_present`,
`input_immutable`, and `receipts_byte_identical`; the required values are
`true`, `false`, `true`, and `true`.

This closed shape admits no path, command text, source text, marker text,
fixture content, exception text, or free-form notes. It uses the same canonical
pretty JSON encoding as measurement receipts. A bounded, independently tested
stdlib helper at
`_ops/context-measurement/correction_dogfood.py` owns only this fixed synthetic
fixture/run/validation contract. Its `run` mode writes a candidate only after
all expected exits, duplicate receipts, content-safety probes, and pre/post
stats pass; its `validate` mode rejects malformed types, contradictory digests,
noncanonical bytes, and commit/tree mismatch without relying on Python
assertions. A separate protected Dev PR containing only the resulting JSON
records a passing run after the implementation merge. Protected merge makes it
the discoverable handoff for later tasks. It is never edited in place; invalid
or superseded evidence uses a governed revert before consumption or a new
versioned filename and schema after consumption. This is one program artifact,
not a registry or ledger.

### 10. E-09 uses one closed evidence envelope

The official denominator remains the parent-authorized
`static-context-manifest/v1` artifact. It is not a second runtime or registry. Its future tracked path is:

```text
_ops/evidence/context-efficiency/static-context-manifest-v1.json
```

Its exact top-level keys are:

- `schema`, `status`, `captured_at_utc`, `baseline_id`,
  `client_root_class`;
- `algorithm`, `tool_contract`, `whitespace_set_version`;
- `projection_order`, `projections`, `totals`, `target_30pct`;
- `measurement_input_sha256`, `measurement_receipt_sha256`; and
- `owner_refs`.

Fixed values use the v2 measurement identities; `schema` is
`static-context-manifest/v1` and `status` is `FROZEN`. Timestamps are
UTC `YYYY-MM-DDTHH:MM:SSZ`. The digest fields are lowercase SHA-256 over canonical input/receipt bytes.

`owner_refs` is a nonempty object keyed by owner repository slug. Each value has exactly `default_branch`, `commit`, and `tree`; commit/tree are lowercase 40-hex Git object IDs.
For this seven-payload denominator its key set is exactly
`KleinPerkins/awa`, `KleinPerkins/dev`, and `KleinPerkins/skills`.

The seven canonically sorted projection IDs are exactly:

```text
awa-operator
dev-operating-model
generated-home-agents
subagent-orchestration
terse-output
workspace-agents
worktree-default
```

Each static projection row has exactly:

- `projection_id`, `logical_path`, `category`, `owner_repository`;
- `owner_commit`, `source_path`, `source_blob`, `source_sha256`;
- `installed_raw_sha256`, `normalized_sha256`;
- `bytes`, `characters`, `words`; and
- `generated_inputs`.

`category` is `rules` or `generated-memory`. Git IDs are lowercase 40-hex; SHA-256 values are lowercase 64-hex; counts are nonnegative integers excluding booleans. `generated_inputs` is `null` for rules. For `generated-memory` it has exactly `source_count`, `source_digests`, and `output_sha256`; source digests are sorted unique lowercase SHA-256 strings and never source content.

Every join is exact:

- the unique row `owner_repository` set equals the `owner_refs` key set;
- each row `owner_commit` equals its `owner_refs.commit`;
- `owner_refs.tree` equals the Git tree of that commit in the named repository;
- `source_blob` equals the blob at `source_path` in that tree;
- `source_sha256` equals SHA-256 over that blob’s raw bytes;
- `logical_path` equals the matching input entry `path` and receipt row `path`;
- projection IDs/orders and region descriptor digests agree across input, receipt, and static manifest;
- installed/normalized digests and all counts equal the receipt row;
- generated-memory `output_sha256` equals its installed raw SHA-256; and
- rules have `generated_inputs:null`.

`totals` exactly match the measurement receipt. `target_30pct` has the same four fields/formula as comparison. Unknown keys are invalid. The static manifest uses the same canonical pretty JSON encoding as the receipt.

An independently tested stdlib validator must prove these joins from explicit local owner checkouts before the freeze PR; manual inspection alone is insufficient. The artifact is created only by a separate E-09 freeze PR after explicit operator GO. Protected merge makes it authoritative. It is never edited in place: a later invalidation uses a new successor manifest filename/schema and plan/ADR as required, while a governed revert may remove an erroneous unaccepted candidate.

### 11. The actual remote Dev entry point must execute the focused suite

Local `make verify-ci` wiring is necessary but not evidence that the runnerless
controller executed the focused suite. Live main’s `.github/pr-recipe.json` and
`.github/pr-automation.lock.json` bind the custom job `repo.dev.m3-verify` to:

```bash
bash _ops/checks/doc-warden-verify.sh --sandbox
```

`_ops/baseline/profiles/pr-automation/v3/test.sh` is a local control-plane
profile regression suite and is not invoked by that job. The smallest
policy-compliant correction is to retain the locked recipe/lock and make the
existing sandbox entry point run the focused suite after its doc-warden
assertions:

```bash
(
  cd "$DEV_ROOT/_ops/context-measurement"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
    test_kp_context_measure.py test_correction_dogfood.py
)
```

The corrective implementation PR therefore changes the sandbox branch of
`_ops/checks/doc-warden-verify.sh`, not the runnerless profile test script or
the recipe/lock/control-plane files. Before writing, it must prove the live
recipe and lock still bind the command above; drift stops implementation and
requires a successor plan.

GitHub’s Check API currently returns `output.text:null` for this controller, so
test stdout and a remote test count are not observable and must never be
claimed. Remote proof is instead the conjunction of:

1. the exact-head sandbox script blob contains the unconditional focused-suite
   invocation above;
2. the unchanged recipe and validated lock bind
   `bash _ops/checks/doc-warden-verify.sh --sandbox`;
3. the exact-head Checks named
   `pr-automation / job:repo.dev.m3-verify` and
   `pr-automation / verify` both succeed with matching `head_sha`; and
4. the PR body records the separately observed local exact-head focused command,
   exit, and test count.

The remote Check proves the bound exact-head script exited successfully. It
does not expose the script’s stdout. A green Check without the script/recipe/
lock bindings is insufficient.

### 12. Program status and language are corrected prospectively

- ADR 0004 and Context Efficiency Program v1 were accepted on 2026-08-15.
- The v1 measurement tool was merged on 2026-08-16, but its contract is not E-09-safe.
- E-09 remains deliberately unfrozen and has no authoritative dogfood receipt.
- Context Efficiency Program v2 is the active execution authority.
- E-09 is the Release 0 denominator gate, not the end of the program.
- Releases 1, 1.1, and 2 from accepted Program v1 remain in scope after E-09.
- Historical “Stage 1/2/3” wording is non-authoritative. Execution uses the
  accepted releases and task IDs.

## Why

This is the smallest correction that protects the program’s evidence boundary:

- canonical sorting follows the binding parent contract and eliminates caller-order drift;
- closed v2 schemas make unknown-field leakage and malformed-receipt crashes mechanically testable;
- keeping the counting algorithm at v1 avoids falsely claiming changed character/word semantics;
- refusing legacy receipts is simpler and safer than migration because no authoritative receipt exists;
- marker digests preserve comparison identity without repeating marker text;
- the 0/2/3/4 partition keeps operational meaning stable and removes `argparse`/traceback collisions; and
- the actual locked Dev entry point proves the exact code under review without
  inventing inaccessible controller stdout.

Alternatives rejected:

- **Preserve manifest order.** Rejected because it contradicts the binding parent authority and makes identity caller-order-dependent.
- **Silently sort while still emitting v1 receipts.** Rejected because old and new producers could emit the same schema with different ordering and validation semantics.
- **Accept unknown fields but omit them from output.** Rejected because open inputs hide typos and weaken receipt reproducibility.
- **Sanitize exception text.** Rejected because exception strings are unstable and can contain caller values; fixed enums are safer.
- **Treat equal/overlapping markers as an empty or one-marker region.** Rejected because that interpretation is not evident from the manifest and can silently count the wrong projection.
- **Rely on local verification plus generic remote Check labels.** Rejected because PR #270 demonstrated that green labels can coexist with no focused remote execution.
- **Add the suite to runnerless profile `test.sh`.** Rejected because the live
  recipe does not invoke that script.
- **Claim remote test counts from Check output.** Rejected because the live
  Check API exposes no test stdout.
- **Freeze E-09 now and correct later.** Rejected because the resulting denominator would be contract-ambiguous and unsafe to compare.

## Consequences

### Positive

- E-09 receives one deterministic ordering and one closed, content-safe evidence shape.
- Every external-input failure has a stable process class and no traceback.
- Unknown fields cannot enter receipts.
- Region equality/overlap is fail-closed.
- Algorithm identity and wire-contract identity can evolve independently.
- Exact-head remote evidence becomes explicit.
- Accepted historical artifacts remain byte-identical.

### Costs

- Existing v1 receipts must be discarded and remeasured.
- The existing remote Dev job becomes slightly longer because it also runs the focused measurement suite.
- Tests and README must be updated together with code.
- Comparison becomes stricter about projection descriptors, so callers must keep valid identity inputs stable.

### Required follow-up

1. Land the documentation-only Context Efficiency Program v2 PR through the protected owner/admin gate.
2. Add focused-suite execution to the sandbox branch of the actual locked Dev
   job entry point.
3. Implement the closed v2 wire contract test-first in the same Dev corrective PR.
4. Run bounded synthetic dogfood and protected-merge its closed correction
   evidence record.
5. Resume E-01/E-03, E-02, and E-04 under their accepted owner plans; continue the E-04 → E-05 → E-06 lane, then the explicit E-07 gate and conditional E-08.
6. Freeze E-09 only after every applicable prerequisite is green.
7. Execute Releases 1, 1.1, and 2 under separately accepted owner plans; E-09
   does not cancel the accepted reduction and closure roadmap.

### Rollback and supersession

Before implementation, reverting this ADR/plan documentation PR changes no runtime state. After implementation, rollback uses a governed revert PR to the last good Dev commit and treats measurement as unavailable; it never re-authorizes v1 receipts for E-09.

Any future change to counting semantics, source-authority distribution, the learned-data boundary, or the two-layer verification model requires a new ADR. A wire-only successor must still use a new receipt schema and explicitly state compatibility.
