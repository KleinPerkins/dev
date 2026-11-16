# Context measurement — v1 counting, closed v2 wire contract

A single, stdlib-only, **read-only** and **content-safe** Python CLI that turns raw context
projection bytes into reproducible counts bound to an explicit identity. It implements the
unchanged `kp-context-measurement/v1` counting algorithm behind the closed
`kp-context-measurement-input/v2`, `kp-context-measurement-receipt/v2`, and
`kp-context-measurement-comparison/v2` wire shapes accepted in
[`ADR 0005`](../adr/0005-harden-context-measurement-before-e09.md) and the
[`Context Efficiency Program v2`](../plans/context-efficiency-program-v2.md).

> **Scope:** measurement instrument only. It does **not** freeze the official denominator (E-09),
> run any reduction, or read/classify/mutate operator memory (`~/agent-learnings.md`, generated
> `~/AGENTS.md`, the continual-learning index, or the agent-route index/registry). V1 receipts are
> intentionally unsupported because no authoritative E-09 receipt was frozen.

## Guarantees

- **Deterministic:** identical input bytes + identical identity arguments produce **byte-identical**
  stdout across runs, processes, and working directories (canonical
  `json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)` + trailing newline; no format flag).
- **Content privacy:** never emits source content or marker text. Valid logical paths and identifiers
  are retained; region marker identity is represented only by SHA-256 digests. Invalid keys, values,
  JSON fragments, exception strings, and tracebacks are never echoed.
- **Read-only:** measured inputs are opened `"rb"` and never written, renamed, chmod'd, or touched.
  The only outputs are stdout (JSON) and stderr (diagnostics).
- **No network, no third-party dependency, no subprocess** to external services (stdlib `python3` only).
- **Fail closed:** closed validation precedes measurement/comparison indexing. External-input
  outcomes use only exits `0`, `2`, `3`, and `4`.

## Algorithm (per projection entry, then aggregated)

1. Each entry identifies one **full projected file** or one **exact managed region** (one begin
   marker + one end marker). Every distinct injected projection is counted once, even if two
   projections have identical text.
2. Read raw bytes, record their **SHA-256**, decode **strict UTF-8**. Invalid UTF-8 →
   `BLOCKED_PREREQUISITE` / `INVALID_UTF8` (raw digest + byte count still recorded; other fields null).
3. Normalize `CRLF`→`LF`, then remaining lone `CR`→`LF`. No other transformation (no NFC/NFKC,
   trimming, tab expansion, final-newline insertion/removal, or frontmatter removal).
4. `characters` = number of Unicode scalar values after normalization (astral scalars count as one;
   strict UTF-8 forbids surrogates so every element is a full scalar).
5. `words` = number of maximal runs separated by the **pinned Unicode 15.0 `White_Space` set**
   (`U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000`).
   This is a hard-pinned 25-code-point frozenset — **not** `str.isspace()`/`str.split()`, which also
   treat `U+001C–U+001F` as separators and would drift.
6. Fully validated entries are sorted by unique ASCII-token `projection_id` in ascending byte
   order; caller manifest order is non-semantic. Totals are integer sums.
7. Region matching enumerates overlapping occurrences before newline normalization. Missing beats
   ambiguous, which beats misordered/overlapping; adjacent non-overlapping markers are valid.

Managed-region selection is **inclusive of both marker lines' bytes** (the client receives them).

## Usage

```
kp_context_measure.py measure  --manifest <path.json>
kp_context_measure.py measure  --path <file> --projection-id <id> \
                               --client-root-class <s> --baseline-id <s> \
                               [--region-begin <s> --region-end <s>]
kp_context_measure.py compare  --baseline <receipt.json> --candidate <receipt.json>
```

- `measure --manifest` reads a closed `kp-context-measurement-input/v2` manifest (below).
- `measure --path` is the single-entry convenience form (mutually exclusive with `--manifest`).
  Supplying `--region-begin` + `--region-end` selects a managed region; otherwise the entry is a full
  file. It builds and validates the same in-memory v2 entry.
- `compare` fully validates both receipts before reading totals or projection fields.

### Input manifest — `kp-context-measurement-input/v2`

```json
{
  "schema": "kp-context-measurement-input/v2",
  "client_root_class": "cursor-desktop/dev-primary",
  "baseline_id": "example-2026-08-16",
  "projections": [
    {"projection_id": "home-agents-md", "path": "/abs/or/rel/file", "select": {"kind": "full"}},
    {"projection_id": "some-block", "path": "/abs/or/rel/file2",
     "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}
  ]
}
```

Top-level keys are exactly `schema`, `client_root_class`, `baseline_id`, and `projections`.
Projection keys are exactly `projection_id`, `path`, and `select`; selectors are exactly
`{"kind":"full"}` or `{"kind":"region","begin":"…","end":"…"}`. IDs, root class, and baseline ID
match `^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$`; IDs are unique. Paths are nonempty Unicode-scalar
strings without NUL. Region markers are nonempty, different Unicode-scalar strings.

Absolute paths are opened as written; relative paths are resolved from the process working
directory. Symlinks are followed only when the final opened target is a regular file.

### `measure` receipt — `kp-context-measurement-receipt/v2`

Top-level keys are exactly `schema`, `algorithm`, `tool`, `tool_contract`,
`whitespace_set_version`, `status`, `client_root_class`, `baseline_id`, `projection_order`,
`projections`, and `totals`. Fixed producer identity is:

```text
schema = kp-context-measurement-receipt/v2
algorithm = kp-context-measurement/v1
tool = kp_context_measure
tool_contract = kp-context-measurement-tool/v2
whitespace_set_version = unicode-15.0-White_Space
```

Each `projections[]` entry: `projection_id`, `path`, `select`, `status` (`OK` |
`BLOCKED_PREREQUISITE`), `failure_class` (`null` or a class below), `raw_sha256`, `normalized_sha256`,
`bytes`, `characters`, `words`.

- A full selector is `{"kind":"full"}`.
- A region selector contains exactly `kind`, `begin_sha256`, and `end_sha256`; marker text is never
  copied to a receipt.
- **OK:** all digests/counts populated; `raw_sha256` over the exact selected input bytes (whole file
  for `full`; the exact marker-inclusive region substring re-encoded UTF-8 for `region`);
  `normalized_sha256` over the UTF-8 bytes of the newline-normalized selected text.
- **`INVALID_UTF8`:** `raw_sha256` + `bytes` populated; `normalized_sha256`, `characters`, `words` null.
- **`PATH_UNREADABLE` / `REGION_*`:** all digests/counts null.
- Top-level `status` is `OK` only if every entry is OK; `totals` is `{bytes, characters, words}`
  nonnegative integer sums when OK, else `null`. JSON booleans are never accepted as integers.

### `compare` output — `kp-context-measurement-comparison/v2`

Success repeats the fixed producer identity and emits `baseline_totals`, `candidate_totals`,
integer `delta` (candidate − baseline), and `target_30pct` =
`{max_characters,max_words,meets_characters,meets_words}` using
`floor(baseline * 70 / 100)`.

Refusal is the closed shape
`{"schema":"kp-context-measurement-comparison/v2","status":"COMPARISON_REFUSED","reasons":[…]}`.
Reasons are sorted/deduplicated fixed enums covering side-specific unreadable/invalid receipts,
unsupported schemas/identities, identity mismatches, blocked status, root/baseline/order mismatch,
and `(projection_id,path,select)` descriptor mismatch. V1, open, noncanonical, malformed, or
cross-field-invalid receipts are refused at exit `4`; malformed values are never echoed.

## Exit codes and failure classes

| Exit | Meaning |
|---|---|
| `0` | `OK` — all entries measured; receipt emitted |
| `2` | `BLOCKED_PREREQUISITE` — ≥1 entry failed a prerequisite; receipt emitted with the failing class, no content |
| `3` | `USAGE_ERROR` — bad CLI args or unreadable/malformed/invalid manifest; one fixed stderr line, no receipt |
| `4` | `COMPARISON_REFUSED` — `compare` identities/versions differ or a receipt is not OK; refusal JSON on stdout |

Per-entry `failure_class` ∈ {`INVALID_UTF8`, `PATH_UNREADABLE`, `REGION_NOT_FOUND`,
`REGION_AMBIGUOUS`, `REGION_MISORDERED`}. Usage diagnostics are exactly:

```text
kp_context_measure: USAGE_ERROR: LOCATION: ERROR_CLASS
```

`LOCATION` is `cli`, `manifest`, `projection`, or `select`; `ERROR_CLASS` is a closed class from
ADR 0005. Comparison writes no stderr. Caller-controlled failures never produce a traceback or
exit `1`.

## Examples

Measure a single file as a full projection:

```bash
python3 _ops/context-measurement/kp_context_measure.py measure \
  --path ./some-projection.md --projection-id home-agents-md \
  --client-root-class cursor-desktop/dev-primary --baseline-id example-2026-08-16
```

Measure an exact managed region (marker-inclusive):

```bash
python3 _ops/context-measurement/kp_context_measure.py measure \
  --path ./file.md --projection-id some-block \
  --client-root-class cursor-desktop/dev-primary --baseline-id example-2026-08-16 \
  --region-begin '<!-- BEGIN x -->' --region-end '<!-- END x -->'
```

Compare two receipts (identity-bound; refuses on mismatch):

```bash
python3 _ops/context-measurement/kp_context_measure.py compare \
  --baseline baseline-receipt.json --candidate candidate-receipt.json
```

## Bounded correction dogfood helper

`correction_dogfood.py` owns only ADR 0005's six fixed synthetic fixtures, six-command matrix,
closed evidence schema, and validator:

```text
correction_dogfood.py run --tool PATH --implementation-root PATH --output PATH
correction_dogfood.py validate --evidence PATH --implementation-root PATH
```

`run` requires an absent output, executes the fixed matrix from two working directories, proves
expected exits, canonical duplicate receipts, no source/sentinel echo, and byte-identical fixture
stats, then writes a mode-0600 same-directory temporary file. It validates that candidate,
commit/tree binding, exact nested types, digest equalities, and canonical bytes before an atomic
rename. Any failure removes the temporary candidate. `validate` is read-only, assertion-free, and
returns only `0` or fixed exit `3`, including under `PYTHONOPTIMIZE=1`.

The helper's output is only `CORRECTION_PROVEN_NOT_E09`; it is not E-09, a denominator, or a
seven-payload baseline. Program v2 M-04 may run it only after the corrective implementation is
protected-merged to live `main`.

## E-09 static manifest validator

`validate_static_context_manifest.py` is the read-only preparatory validator for the E-09 freeze
PR. It validates a candidate `static-context-manifest/v1`, the closed v2 measurement input, and
the closed v2 measurement receipt against explicit local owner checkouts:

```text
validate_static_context_manifest.py
  --manifest PATH
  --input PATH
  --receipt PATH
  --owner-checkout REPOSITORY=PATH
  [--owner-checkout REPOSITORY=PATH ...]
```

It requires exactly `KleinPerkins/awa`, `KleinPerkins/dev`, and `KleinPerkins/skills` owner
checkouts. The validator runs only local read-only Git commands, proves the manifest commit/tree/blob
joins, checks canonical JSON bytes, joins the input/receipt/manifest projection rows, and emits only:

```json
{
  "input_sha256": "...",
  "manifest_sha256": "...",
  "receipt_sha256": "...",
  "schema": "static-context-manifest-validation/v1",
  "status": "OK"
}
```

Any validation or usage failure exits `3` with one fixed diagnostic and no source text, path detail,
unknown field name, or Python traceback. This validator does not create the E-09 input, receipt, or
manifest; those remain a later protected freeze PR under the explicit operator gate.

## Release 2 closure record

`release2_closure.py` assembles and validates the single versioned
`context-efficiency-release2-closure/v1` record that closes the program (Release 2 task **C-02**). It
reuses this directory's canonical-JSON + SHA-256 primitives, so the record is byte-deterministic and
**content-safe by construction**.

```text
release2_closure.py assemble --dev-root PATH --skills-root PATH --orch-root PATH \
                             --cpp-root PATH --awa-root PATH \
                             --c01-artifact PATH --out PATH
release2_closure.py validate PATH
```

`assemble` binds the five owner `origin/main` refs, the Release 0/1/1.1 evidence digests, the D-04
CPP/orchestrator landing anchors, the Release-1 30% result, and the C-01 fresh-client projection
matrix drawn from the D-01 inventory artifact, plus verified residuals, rollback refs, and the
per-task built-versus-planned map. It refuses to bind an evidence digest whose on-disk bytes differ
from `origin/main`, and verifies that the C-01 capture commit is the immediate parent of the closure
`origin/main`. Only IDs, exposure/eligibility classes, digests, and normalized counts ever enter the
record — never raw description text, source bytes, or session content. `validate` is read-only and
closed-schema; any schema or content-safety violation exits `3`. `assemble` refuses to overwrite an
existing `--out`; once accepted the record is never edited in place — a successor version supersedes
it. No network, no third-party dependency, no tracked write outside `--out`.

## Tests

Stdlib `unittest`, colocated and wired both into `make verify` / `make verify-ci` and the actual
runnerless Dev entry point `_ops/checks/doc-warden-verify.sh --sandbox`:

```bash
cd _ops/context-measurement
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  test_kp_context_measure.py \
  test_correction_dogfood.py \
  test_validate_static_context_manifest.py \
  test_release2_closure.py
```
