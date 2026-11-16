# kp-context-measurement/v1 tooling — deterministic Dev-local measurement CLI

**Version:** v1
**Status:** ACCEPTED — 2026-08-16
**Date:** 2026-08-16
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** agentic-execution
**Review provenance:** Authored under explicit operator authorization — "Authorize a Dev-owned plan for kp-context-measurement/v1 tooling only. Afterward, continue autonomously." Self-reviewed with `plan-refine` standalone Mode A (single subsystem, 4 files touched, one protected root `_ops/`, read-only CLI, reversible, one specialist domain) against live Dev `origin/main` `bddf406918d830af9bfafefcaf7c3fc0a85606f8`. Facts re-verified at that tip: program-plan blob `f6de269c9c2f88e78e58abd9c247405cb506a123`, ADR-0004 blob `0578f7d7b4ace6c233d5f56c9d20fc43ad979450`.
**Governing decision:** accepted [ADR-0004](../adr/0004-optimize-context-projections-without-moving-authority.md); parent program [Context Efficiency Program v1](context-efficiency-program-v1.md) §4.2, work item E-09 dependency (denominator freeze — **out of scope here**).

**Goal:** Build the single deterministic, read-only, content-safe CLI that implements the `kp-context-measurement/v1` counting algorithm exactly as accepted, so any later baseline/reduction work has an executable measurement instrument.
**Architecture:** One stdlib-only Python module under `_ops/context-measurement/` exposing a `measure` verb (raw bytes → strict UTF-8 → newline-normalized Unicode-scalar/word counts + digests, per projection, ordered, identity-bound) and a `compare` verb that enforces the §4.2.6 identity/version refusal rule. No runtime, registry, manifest freeze, or memory mutation. Tests are stdlib `unittest`, colocated and wired into the existing verify harness.
**Tech stack:** Python 3 standard library only (`argparse`, `json`, `hashlib`, `pathlib`, `sys`, `unittest`); Bash (`verify-operating-model.sh` wiring); Markdown (plan/README).

> **Pre-implementation gate:** this plan builds ONLY the measurement tool. It does not freeze the official `static-context-manifest/v1` denominator (E-09), complete E-09, run any reduction (Release 1+), mutate generated memory, change E-01–E-08, or create any executable registry/ledger. Those remain gated by the parent program.

---

## Changelog

- v1 (2026-08-16) — Initial accepted plan. Bounds a Dev-local CLI to the accepted `kp-context-measurement/v1` algorithm (program §4.2), with explicit non-goals excluding baseline freeze, E-09 completion, and generated-memory mutation.

---

## Global Constraints

- Implement the `kp-context-measurement/v1` algorithm EXACTLY as accepted in program §4.2 and ADR-0004 §6; never invent, relax, or extend the counting rules.
- Standard library only. No third-party dependency, no network, no subprocess to external services. The controller verifies dev in a `network:none` `buildpack-deps` VM, so the tool and its tests must pass with stdlib `python3` alone.
- Read-only with respect to every measured input: open inputs `"rb"`, never write/rename/chmod/touch a measured file. The only outputs are stdout (JSON) and stderr (diagnostics).
- Content privacy is absolute: NEVER emit source content — no snippets, no lines, no surrounding bytes, no decoded text. Only digests, integer counts, caller-provided identifiers (paths, projection IDs, marker strings), and fixed enum/status strings may appear in output.
- Deterministic output: identical input bytes + identical identity arguments MUST produce byte-identical stdout across runs, processes, and working directories.
- Fail closed: any prerequisite failure (invalid UTF-8, unreadable path, region markers absent/ambiguous/misordered) yields a stable `BLOCKED_PREREQUISITE` classification and a non-zero exit; it never emits counts derived from unusable input and never emits content.
- Do not add a comparison mode beyond the §4.2.6 identity/version refusal rule; do not add managed-region matching beyond a single exact begin/end marker pair per entry (no regex/fuzzy/multi-region). No speculative generality.

## 1. Purpose

The parent Context Efficiency Program (§4.2) defines `kp-context-measurement/v1` as the binding static counting algorithm for every context-size claim, but no executable implementation of it exists in the repository. Every size figure in the program today is a hand-computed preflight. E-09 (freeze the official denominator) and all Release-1 reduction claims depend on a deterministic, content-safe instrument that turns raw projection bytes into reproducible counts bound to an explicit identity. This plan delivers exactly that instrument — nothing more.

## 2. Scope and non-goals

### In scope

- A single Dev-local CLI implementing `kp-context-measurement/v1` (program §4.2 steps 1–6) over one or more projection entries.
- Entry input types accepted by v1 of the tool: a **full projected file** and a **single exact managed region** (one begin marker + one end marker), per §4.2.1.
- A `measure` verb emitting a deterministic, content-safe JSON receipt (`kp-context-measurement/v1`) bound to algorithm version, whitespace-set version, ordered projection identity, client/root class, and baseline ID.
- A `compare` verb whose sole job is the §4.2.6 refusal rule: refuse two receipts whose algorithm version, ordered projection identity, client/root class, or baseline ID differ (or that are themselves not OK); otherwise report integer totals, delta, and the program's 30% target check.
- A stdlib `unittest` suite covering every algorithm edge the parent plan enumerates, wired into `make verify`/`verify-ci`.
- A README documenting the CLI, JSON contract, exit/failure classes, and invocation.

### Out of scope (explicit non-goals)

- Freezing the official `static-context-manifest/v1` denominator, or completing E-09 in any form.
- Any Release 1/1.1/2 reduction, or asserting the program is complete.
- Reading, classifying, repairing, generating, or mutating operator-owned `~/agent-learnings.md`, workspace `agent-learnings.md`, generated `~/AGENTS.md`, the continual-learning index, or the agent-route index/registry.
- Any change to E-01–E-08 owner work, hooks, installers, rules, skills, exposure lists, or the AWA/Skills/CPP surfaces.
- A central context manager, runtime, metadata/executable registry, evidence ledger, or a second capability-delivery channel.
- Managed-region matching beyond one exact begin/end marker pair per entry; regex, fuzzy, or multi-region selection.
- YAML/`skill-description-normalization/v1` (a separate contract in program §4.2, not part of this tool).
- Modifying the pr-automation control plane (`.github/pr-recipe.json`, rulesets, controller config).

## 3. Background and context

Verified live at Dev `origin/main` `bddf406918d830af9bfafefcaf7c3fc0a85606f8` (2026-08-16):

- **Algorithm authority (immutable).** Program plan `_ops/plans/context-efficiency-program-v1.md` (blob `f6de269c9c2f88e78e58abd9c247405cb506a123`) §4.2 and ADR-0004 `_ops/adr/0004-optimize-context-projections-without-moving-authority.md` (blob `0578f7d7b4ace6c233d5f56c9d20fc43ad979450`) §6 pin the six algorithm rules reproduced verbatim in §4.1 below. Both are ACCEPTED/byte-immutable and are NOT edited by this plan.
- **Owner classification.** Program §5 (A-02 table) requires a Dev implementation to be an `_ops/plans/` plan with `**Plan-type:** agentic-execution`. This plan follows that classification; it is the repo's first agentic-execution plan.
- **Language/convention.** Python is repository-native (`_ops/bin/awa-dashboard-data.py`, `_ops/baseline/profiles/pr-automation/*.py`). The test convention is stdlib `unittest` loaded via `importlib` and invoked by `_ops/checks/verify-operating-model.sh`, which runs each subsystem's suite (doc-warden, pr-automation legacy + v3, worktree, snow-kit). Subsystems live under `_ops/<name>/`.
- **doc-warden governance.** `_ops/doc-warden/POLICY.md` §10 rule 10 requires an agentic-execution plan to carry a `**Files:**` block, an `**Interfaces:**` block, and at least one `- [ ]` checkbox step across `## 5. Work items`. Plans are byte-immutable once ACCEPTED (§9); the index `_ops/plans/README.md` carries the status row.
- **Remote gate.** dev is enrolled in runnerless PR-automation v3 (`repo.dev.m3-verify`); the required `pr-automation / verify` check runs a canned repository contract plus `bash _ops/checks/doc-warden-verify.sh --sandbox` in a `network:none` `buildpack-deps` VM (`.github/pr-recipe.json`, `.github/pr-verification.json`). `/_ops/` is a protected path (`.github/CODEOWNERS`, `.github/pr-automation.json`), so both PRs are reviewer-App-governed; the App owns merge.

## 4. Approach

### 4.1 The `kp-context-measurement/v1` algorithm (verbatim from program §4.2, ADR-0004 §6)

Applied per projection entry, then aggregated:

1. Each entry identifies either one **full projected file** or one **exact managed region**. Count every distinct injected projection once, even when two projections have identical text.
2. Read raw bytes, record their SHA-256, and decode strict UTF-8. Invalid UTF-8 is `BLOCKED_PREREQUISITE`.
3. Normalize `CRLF`→`LF`, then remaining `CR`→`LF`. Preserve every other Unicode scalar exactly (no NFC/NFKC, trimming, final-newline insertion/removal, tab expansion, or frontmatter removal).
4. `characters` = number of Unicode scalar values after newline normalization. Frontmatter, delimiters, and managed-region boundaries count when the client receives them.
5. `words` = number of maximal runs separated by the pinned Unicode 15.0 `White_Space` set: `U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000`.
6. Order entries by the manifest's unique projection ID; totals are integer sums. Comparison refuses different algorithm versions, projection identities/order, client/root classes, or baseline IDs.

Determinism corollaries this tool enforces: the whitespace set is a hard-pinned literal frozenset (NOT `str.isspace()`/`str.split()`, which include `U+001C–U+001F` and would drift); `characters` is `len(str)` of the strict-UTF-8-decoded, newline-normalized text (valid because strict UTF-8 forbids surrogates, so every element is a full scalar and astral scalars count as one); managed-region selection is inclusive of both marker lines' bytes (they are received by the client).

### 4.2 CLI contract

```
kp_context_measure.py measure  --manifest <path.json>
kp_context_measure.py measure  --path <file> --projection-id <id> --client-root-class <s> --baseline-id <s>
                                [--region-begin <s> --region-end <s>]
kp_context_measure.py compare  --baseline <receipt.json> --candidate <receipt.json>
```

- `measure --manifest` reads an ordered `kp-context-measurement-input/v1` manifest (below). `measure --path` is the single-entry convenience form (mutually exclusive with `--manifest`); `--region-begin`+`--region-end` together select a managed region, otherwise the entry is a full file.
- Output is always a single deterministic JSON document to stdout: `json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)` + one trailing `"\n"`. There is no formatting flag (one canonical form guarantees byte-identical repeats).

Input manifest (`kp-context-measurement-input/v1`):

```json
{
  "schema": "kp-context-measurement-input/v1",
  "client_root_class": "cursor-desktop/dev-primary",
  "baseline_id": "example-2026-08-16",
  "projections": [
    {"projection_id": "home-agents-md", "path": "/abs/or/rel/file", "select": {"kind": "full"}},
    {"projection_id": "some-block", "path": "/abs/or/rel/file2",
     "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}
  ]
}
```

Validation (else exit 3 `USAGE_ERROR`): `schema` equals the literal above; `projections` is a non-empty list; every `projection_id` is a unique non-empty string; each `select.kind` ∈ {`full`,`region`}; a `region` entry has non-empty `begin` and `end`.

### 4.3 Output contract — `measure` receipt (`kp-context-measurement/v1`)

Object keys (emitted sorted): `schema`, `algorithm`, `whitespace_set_version`, `tool`, `status`, `client_root_class`, `baseline_id`, `projection_order` (ordered list of IDs), `projections` (ordered list), `totals`.

Each `projections[]` entry: `projection_id`, `path`, `select`, `status` (`OK`|`BLOCKED_PREREQUISITE`), `failure_class` (`null` or one of the classes in §4.4), `raw_sha256`, `normalized_sha256`, `bytes`, `characters`, `words`.

- OK entry: all digests/counts populated; `raw_sha256` over the exact selected input bytes (whole file for `full`; the exact marker-inclusive region substring re-encoded UTF-8 for `region`); `normalized_sha256` over the UTF-8 bytes of the newline-normalized selected text.
- `INVALID_UTF8` entry: `raw_sha256` and `bytes` populated (recorded before decode per §4.1 step 2); `normalized_sha256`, `characters`, `words` are `null`.
- `PATH_UNREADABLE` / `REGION_*` entry: all digests/counts `null`.
- Top-level `status` is `OK` only if every entry is OK; `totals` is `{bytes,characters,words}` integer sums when OK, else `null`.

### 4.4 Exit codes and failure classes (stable)

| Exit | Meaning |
|---|---|
| `0` | `OK` — all entries measured; receipt emitted |
| `2` | `BLOCKED_PREREQUISITE` — ≥1 entry failed a prerequisite; receipt emitted with the failing class, no content |
| `3` | `USAGE_ERROR` — bad CLI args or malformed/invalid manifest; stderr message, no receipt |
| `4` | `COMPARISON_REFUSED` — `compare` identities/versions differ or a receipt is not OK; refusal JSON on stdout |

Per-entry `failure_class` ∈ {`INVALID_UTF8`, `PATH_UNREADABLE`, `REGION_NOT_FOUND`, `REGION_AMBIGUOUS`, `REGION_MISORDERED`}. Diagnostics name only the class, the projection ID, and caller-provided identifiers — never file content.

### 4.5 `compare` contract (§4.2.6 refusal rule)

Reads two `measure` receipts. Refuses (exit 4, `status:"COMPARISON_REFUSED"`, `reasons` list) if any of: `algorithm` differs, `projection_order` differs (as an ordered tuple), `client_root_class` differs, `baseline_id` differs, baseline not OK, candidate not OK. Otherwise emits `kp-context-measurement-comparison/v1` with `baseline_totals`, `candidate_totals`, integer `delta` (candidate − baseline), and `target_30pct` = `{max_characters:(b*70)//100, max_words:(b*70)//100, meets_characters:bool, meets_words:bool}` (integer/boolean only; the program's `after <= floor(0.70*baseline)` formula). No floats; content-safe by construction (operates on already content-free receipts).

### 4.6 Verification integration

`_ops/checks/verify-operating-model.sh` gains (a) the three new files in its structure-presence list and (b) a stanza that runs `python3 -m unittest` on the suite, mirroring the doc-warden/pr-automation stanzas. This runs under `make verify` and `make verify-ci` (and the local pre-commit `--ci` gate). The remote controller gate (`doc-warden-verify.sh --sandbox` + canned contract) is unchanged and untouched.

## 5. Work items

Executed task-by-task under TDD (write failing test → prove red → minimal implementation → prove green). All paths are repo-root-relative. The implementer commits per task; the whole set ships as one implementation PR after full-suite green.

### Task 1: Measurement core (`kp-context-measurement/v1` counting primitives)

**Files:**
- Create: `_ops/context-measurement/kp_context_measure.py`
- Test: `_ops/context-measurement/test_kp_context_measure.py`

**Interfaces:**
- Consumes: nothing (leaf module; stdlib only).
- Produces: module constants `ALGORITHM = "kp-context-measurement/v1"`, `WHITESPACE_SET_VERSION = "unicode-15.0-White_Space"`, `WHITE_SPACE: frozenset[int]`; and pure functions `normalize_newlines(text: str) -> str`, `count_characters(normalized: str) -> int`, `count_words(normalized: str) -> int`, `decode_strict_utf8(raw: bytes) -> str` (raises `UnicodeDecodeError` on invalid), `sha256_hex(data: bytes) -> str`.

- [ ] **Step 1 — Write the failing tests**

```python
import importlib.util, hashlib, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("kpcm", HERE / "kp_context_measure.py")
kpcm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(kpcm)

class TestCore(unittest.TestCase):
    def test_whitespace_set_is_exact_unicode_15_property(self):
        expected = ({0x09,0x0A,0x0B,0x0C,0x0D,0x20,0x85,0xA0,0x1680,
                     0x2028,0x2029,0x202F,0x205F,0x3000} | set(range(0x2000,0x200A+1)))
        self.assertEqual(set(kpcm.WHITE_SPACE), expected)
        self.assertEqual(len(kpcm.WHITE_SPACE), 25)
    def test_newline_normalization_crlf_then_cr_only(self):
        self.assertEqual(kpcm.normalize_newlines("a\r\nb\rc\nd"), "a\nb\nc\nd")
        self.assertEqual(kpcm.normalize_newlines("x\u2028y"), "x\u2028y")  # LS untouched
    def test_astral_scalar_counts_as_one_character(self):
        self.assertEqual(kpcm.count_characters("A\U0001F600B"), 3)
    def test_word_runs_use_pinned_set_not_python_isspace(self):
        # U+001C is whitespace to str.split() but NOT in Unicode White_Space
        self.assertEqual("a\x1cb".split().__len__(), 2)       # documents the drift we avoid
        self.assertEqual(kpcm.count_words("a\x1cb"), 1)        # pinned set: one run
        self.assertEqual(kpcm.count_words("a\u200bb"), 1)      # ZWSP not in set
        self.assertEqual(kpcm.count_words("a\u00a0b"), 2)      # NBSP in set
        self.assertEqual(kpcm.count_words("  a\t\n b  "), 2)   # runs + leading/trailing
        self.assertEqual(kpcm.count_words(""), 0)
    def test_strict_utf8_rejects_lone_surrogate_and_invalid(self):
        for bad in (b"\xed\xa0\x80", b"\xff", b"\xc3\x28"):
            with self.assertRaises(UnicodeDecodeError):
                kpcm.decode_strict_utf8(bad)
        self.assertEqual(kpcm.decode_strict_utf8(b"A\xf0\x9f\x98\x80B"), "A\U0001F600B")
    def test_sha256_hex_matches_hashlib(self):
        self.assertEqual(kpcm.sha256_hex(b""), hashlib.sha256(b"").hexdigest())
if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 — Run the test, verify it FAILS**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFoundError` (module absent) or `AttributeError` (symbols undefined).

- [ ] **Step 3 — Write the minimal implementation**

```python
#!/usr/bin/env python3
"""kp-context-measurement/v1 — deterministic, read-only, content-safe context measurement.
Implements the algorithm accepted in KleinPerkins/dev _ops/plans/context-efficiency-program-v1.md
§4.2 and _ops/adr/0004-*.md §6. Standard library only. Never emits source content."""
from __future__ import annotations
import hashlib

ALGORITHM = "kp-context-measurement/v1"
WHITESPACE_SET_VERSION = "unicode-15.0-White_Space"
# Pinned Unicode 15.0 White_Space property (25 code points). NOT str.isspace()/str.split(),
# which also treat U+001C-U+001F as separators and would drift from the accepted contract.
WHITE_SPACE = frozenset(
    {0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
     0x2028, 0x2029, 0x202F, 0x205F, 0x3000} | set(range(0x2000, 0x200A + 1))
)

def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")

def count_characters(normalized: str) -> int:
    return len(normalized)

def count_words(normalized: str) -> int:
    count = 0
    in_run = False
    for ch in normalized:
        if ord(ch) in WHITE_SPACE:
            in_run = False
        elif not in_run:
            count += 1
            in_run = True
    return count

def decode_strict_utf8(raw: bytes) -> str:
    return raw.decode("utf-8", errors="strict")

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

- [ ] **Step 4 — Run the test, verify it PASSES**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: PASS (all `TestCore` cases).

- [ ] **Step 5 — Commit**

```bash
git add _ops/context-measurement/kp_context_measure.py _ops/context-measurement/test_kp_context_measure.py
git commit -m "feat(context-measurement): kp-context-measurement/v1 counting core (TDD)"
```

**Definition of done:** the six `TestCore` cases pass; the whitespace set is the exact 25-code-point pinned property; astral scalars count as one; strict UTF-8 rejects lone surrogates; word runs use the pinned set, not `isspace()`.

### Task 2: Projection selection + receipt assembly (full file + one exact region; fail-closed)

**Files:**
- Modify: `_ops/context-measurement/kp_context_measure.py`
- Test: `_ops/context-measurement/test_kp_context_measure.py`

**Interfaces:**
- Consumes: Task 1 primitives.
- Produces: `class RegionError(Exception)` with a `.failure_class` attribute; `select_region(full_text: str, begin: str, end: str) -> str` (inclusive of both marker substrings; raises `RegionError(REGION_NOT_FOUND|REGION_AMBIGUOUS|REGION_MISORDERED)`); `measure_entry(entry: dict) -> dict` (returns one content-safe `projections[]` object, reading `entry["path"]` in `"rb"` mode, mapping failures to per-entry `status`/`failure_class`); `build_receipt(client_root_class: str, baseline_id: str, entries: list[dict]) -> tuple[dict, int]` (returns the receipt object and the process exit code 0/2).

- [ ] **Step 1 — Write the failing tests**

```python
import json, os, tempfile
class TestSelectionAndReceipt(unittest.TestCase):
    def _tmp(self, data: bytes) -> str:
        fd, p = tempfile.mkstemp(); os.write(fd, data); os.close(fd); self.addCleanup(os.remove, p); return p
    def test_full_file_counts_and_digests(self):
        p = self._tmp(b"alpha beta\r\ngamma\n")
        rec, code = kpcm.build_receipt("c/r", "b1",
            [{"projection_id": "f", "path": p, "select": {"kind": "full"}}])
        self.assertEqual(code, 0)
        e = rec["projections"][0]
        self.assertEqual(e["status"], "OK")
        self.assertEqual(e["characters"], len("alpha beta\ngamma\n"))
        self.assertEqual(e["words"], 3)
        self.assertEqual(e["raw_sha256"], kpcm.sha256_hex(b"alpha beta\r\ngamma\n"))
        self.assertEqual(rec["totals"], {"bytes": 18, "characters": 17, "words": 3})
    def test_region_inclusive_of_markers(self):
        body = b"pre\n<!-- BEGIN x -->\nmid one\n<!-- END x -->\npost\n"
        p = self._tmp(body)
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "r", "path": p,
            "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}])
        self.assertEqual(code, 0)
        region = "<!-- BEGIN x -->\nmid one\n<!-- END x -->"
        self.assertEqual(rec["projections"][0]["raw_sha256"], kpcm.sha256_hex(region.encode()))
        # maximal non-whitespace runs, marker-inclusive:
        # <!-- BEGIN x --> mid one <!-- END x -->  => 10 runs
        self.assertEqual(rec["projections"][0]["words"], 10)
    def test_invalid_utf8_blocks_with_raw_digest_only(self):
        p = self._tmp(b"\xff\xfe")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "b", "path": p, "select": {"kind": "full"}}])
        self.assertEqual(code, 2)
        e = rec["projections"][0]
        self.assertEqual((e["status"], e["failure_class"]), ("BLOCKED_PREREQUISITE", "INVALID_UTF8"))
        self.assertEqual(e["raw_sha256"], kpcm.sha256_hex(b"\xff\xfe"))
        self.assertIsNone(e["characters"]); self.assertIsNone(rec["totals"])
    def test_region_not_found_blocks(self):
        p = self._tmp(b"no markers here\n")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "r", "path": p,
            "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}])
        self.assertEqual(code, 2)
        self.assertEqual(rec["projections"][0]["failure_class"], "REGION_NOT_FOUND")
    def test_empty_file(self):
        p = self._tmp(b"")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "e", "path": p, "select": {"kind": "full"}}])
        self.assertEqual((code, rec["projections"][0]["characters"], rec["projections"][0]["words"]), (0, 0, 0))
        self.assertEqual(rec["projections"][0]["raw_sha256"], kpcm.sha256_hex(b""))
    def test_content_never_disclosed(self):
        p = self._tmp(b"TOKEN_SENTINEL_SECRET stuff\n")
        rec, _ = kpcm.build_receipt("c/r", "b1", [{"projection_id": "s", "path": p, "select": {"kind": "full"}}])
        self.assertNotIn("SENTINEL", json.dumps(rec))
```

- [ ] **Step 2 — Run the test, verify it FAILS**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: FAIL — `AttributeError: module 'kpcm' has no attribute 'build_receipt'`.

- [ ] **Step 3 — Write the minimal implementation**

```python
class RegionError(Exception):
    def __init__(self, failure_class: str):
        super().__init__(failure_class)
        self.failure_class = failure_class

def select_region(full_text: str, begin: str, end: str) -> str:
    first_b, last_b = full_text.find(begin), full_text.rfind(begin)
    first_e, last_e = full_text.find(end), full_text.rfind(end)
    if first_b == -1 or first_e == -1:
        raise RegionError("REGION_NOT_FOUND")
    if first_b != last_b or first_e != last_e:
        raise RegionError("REGION_AMBIGUOUS")
    if first_e < first_b:
        raise RegionError("REGION_MISORDERED")
    return full_text[first_b:first_e + len(end)]

def _blank_entry(entry: dict) -> dict:
    return {"projection_id": entry["projection_id"], "path": entry["path"],
            "select": entry["select"], "status": "OK", "failure_class": None,
            "raw_sha256": None, "normalized_sha256": None,
            "bytes": None, "characters": None, "words": None}

def measure_entry(entry: dict) -> dict:
    out = _blank_entry(entry)
    try:
        with open(entry["path"], "rb") as fh:
            raw = fh.read()
    except OSError:
        out.update(status="BLOCKED_PREREQUISITE", failure_class="PATH_UNREADABLE"); return out
    try:
        full_text = decode_strict_utf8(raw)
    except UnicodeDecodeError:
        out.update(status="BLOCKED_PREREQUISITE", failure_class="INVALID_UTF8",
                   raw_sha256=sha256_hex(raw), bytes=len(raw)); return out
    sel = entry["select"]
    if sel["kind"] == "region":
        try:
            selected = select_region(full_text, sel["begin"], sel["end"])
        except RegionError as err:
            out.update(status="BLOCKED_PREREQUISITE", failure_class=err.failure_class); return out
        raw_selected = selected.encode("utf-8")
    else:
        selected, raw_selected = full_text, raw
    normalized = normalize_newlines(selected)
    norm_bytes = normalized.encode("utf-8")
    out.update(raw_sha256=sha256_hex(raw_selected), normalized_sha256=sha256_hex(norm_bytes),
               bytes=len(raw_selected), characters=count_characters(normalized),
               words=count_words(normalized))
    return out

def build_receipt(client_root_class: str, baseline_id: str, entries: list) -> tuple:
    measured = [measure_entry(e) for e in entries]
    ok = all(m["status"] == "OK" for m in measured)
    totals = None
    if ok:
        totals = {"bytes": sum(m["bytes"] for m in measured),
                  "characters": sum(m["characters"] for m in measured),
                  "words": sum(m["words"] for m in measured)}
    receipt = {"schema": ALGORITHM, "algorithm": ALGORITHM,
               "whitespace_set_version": WHITESPACE_SET_VERSION, "tool": "kp_context_measure",
               "status": "OK" if ok else "BLOCKED_PREREQUISITE",
               "client_root_class": client_root_class, "baseline_id": baseline_id,
               "projection_order": [m["projection_id"] for m in measured],
               "projections": measured, "totals": totals}
    return receipt, (0 if ok else 2)
```

- [ ] **Step 4 — Run the test, verify it PASSES**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: PASS (`TestCore` + `TestSelectionAndReceipt`).

- [ ] **Step 5 — Commit**

```bash
git add _ops/context-measurement/kp_context_measure.py _ops/context-measurement/test_kp_context_measure.py
git commit -m "feat(context-measurement): projection selection + content-safe receipt (TDD)"
```

**Definition of done:** full-file and marker-inclusive region measurement produce correct digests/counts; invalid UTF-8, unreadable path, and region-not-found fail closed (exit 2) with no content; empty file yields zero counts; a sentinel string never appears in the JSON.

### Task 3: CLI verbs (`measure`, `compare`) with deterministic JSON + stable exit codes

**Files:**
- Modify: `_ops/context-measurement/kp_context_measure.py`
- Test: `_ops/context-measurement/test_kp_context_measure.py`

**Interfaces:**
- Consumes: Task 1–2 functions.
- Produces: `load_manifest(path: str) -> tuple[str,str,list]` (validates `kp-context-measurement-input/v1`, raising `SystemExit(3)` on violation); `compare_receipts(baseline: dict, candidate: dict) -> tuple[dict,int]`; `emit(obj: dict) -> str` (`json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"`); `main(argv: list[str]) -> int` (argparse; `measure`/`compare` subcommands; prints `emit(...)` to stdout; returns the exit code). Module ends with `if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))`.

- [ ] **Step 1 — Write the failing tests**

```python
import io, contextlib
class TestCli(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = kpcm.main(argv)
        return code, buf.getvalue()
    def test_measure_path_is_deterministic_byte_identical(self):
        p = self._tmp_named(b"one two three\n")
        a = self._run(["measure", "--path", p, "--projection-id", "x",
                       "--client-root-class", "c/r", "--baseline-id", "b1"])
        b = self._run(["measure", "--path", p, "--projection-id", "x",
                       "--client-root-class", "c/r", "--baseline-id", "b1"])
        self.assertEqual(a, b)                       # byte-identical output + exit
        self.assertEqual(a[0], 0)
        self.assertEqual(json.loads(a[1])["totals"]["words"], 3)
    def test_compare_ok_and_target(self):
        base = {"algorithm": kpcm.ALGORITHM, "status": "OK", "client_root_class": "c/r",
                "baseline_id": "b1", "projection_order": ["x"],
                "totals": {"bytes": 100, "characters": 100, "words": 20}}
        cand = dict(base); cand["totals"] = {"bytes": 60, "characters": 60, "words": 12}
        out, code = kpcm.compare_receipts(base, cand)
        self.assertEqual(code, 0)
        self.assertTrue(out["target_30pct"]["meets_characters"])
        self.assertEqual(out["delta"]["characters"], -40)
    def test_compare_refuses_identity_mismatch(self):
        base = {"algorithm": kpcm.ALGORITHM, "status": "OK", "client_root_class": "c/r",
                "baseline_id": "b1", "projection_order": ["x"], "totals": {"bytes":1,"characters":1,"words":1}}
        cand = dict(base); cand["projection_order"] = ["y"]; cand["baseline_id"] = "b2"
        out, code = kpcm.compare_receipts(base, cand)
        self.assertEqual(code, 4)
        self.assertEqual(out["status"], "COMPARISON_REFUSED")
        self.assertIn("projection_order_mismatch", out["reasons"])
        self.assertIn("baseline_id_mismatch", out["reasons"])
    def test_bad_manifest_is_usage_error(self):
        p = self._tmp_named(b'{"schema":"wrong"}')
        with self.assertRaises(SystemExit) as ctx:
            kpcm.load_manifest(p)
        self.assertEqual(ctx.exception.code, 3)
```

(`_tmp_named` writes a NamedTemporaryFile and registers cleanup, like `_tmp` but returns a stable path.)

- [ ] **Step 2 — Run the test, verify it FAILS**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: FAIL — `AttributeError` on `main`/`compare_receipts`/`load_manifest`.

- [ ] **Step 3 — Write the minimal implementation**

```python
import argparse, json, sys

def emit(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

def load_manifest(path: str):
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as err:
        raise SystemExit(3) from err
    if not isinstance(doc, dict) or doc.get("schema") != "kp-context-measurement-input/v1":
        raise SystemExit(3)
    projs = doc.get("projections")
    if not isinstance(projs, list) or not projs:
        raise SystemExit(3)
    seen = set()
    for p in projs:
        pid, sel = p.get("projection_id"), p.get("select")
        if not isinstance(pid, str) or not pid or pid in seen or not isinstance(p.get("path"), str):
            raise SystemExit(3)
        seen.add(pid)
        if not isinstance(sel, dict) or sel.get("kind") not in ("full", "region"):
            raise SystemExit(3)
        if sel["kind"] == "region" and not (sel.get("begin") and sel.get("end")):
            raise SystemExit(3)
    crc, bid = doc.get("client_root_class"), doc.get("baseline_id")
    if not isinstance(crc, str) or not isinstance(bid, str):
        raise SystemExit(3)
    return crc, bid, projs

def compare_receipts(baseline: dict, candidate: dict):
    reasons = []
    if baseline.get("algorithm") != candidate.get("algorithm"): reasons.append("algorithm_mismatch")
    if baseline.get("projection_order") != candidate.get("projection_order"): reasons.append("projection_order_mismatch")
    if baseline.get("client_root_class") != candidate.get("client_root_class"): reasons.append("client_root_class_mismatch")
    if baseline.get("baseline_id") != candidate.get("baseline_id"): reasons.append("baseline_id_mismatch")
    if baseline.get("status") != "OK": reasons.append("baseline_not_ok")
    if candidate.get("status") != "OK": reasons.append("candidate_not_ok")
    if reasons:
        return {"schema": "kp-context-measurement-comparison/v1", "status": "COMPARISON_REFUSED",
                "reasons": sorted(set(reasons))}, 4
    b, c = baseline["totals"], candidate["totals"]
    out = {"schema": "kp-context-measurement-comparison/v1", "algorithm": baseline["algorithm"],
           "status": "OK", "baseline_id": baseline["baseline_id"],
           "client_root_class": baseline["client_root_class"],
           "projection_order": baseline["projection_order"],
           "baseline_totals": b, "candidate_totals": c,
           "delta": {k: c[k] - b[k] for k in ("bytes", "characters", "words")},
           "target_30pct": {"max_characters": (b["characters"] * 70) // 100,
                            "max_words": (b["words"] * 70) // 100,
                            "meets_characters": c["characters"] <= (b["characters"] * 70) // 100,
                            "meets_words": c["words"] <= (b["words"] * 70) // 100}}
    return out, 0

def main(argv):
    ap = argparse.ArgumentParser(prog="kp_context_measure")
    sub = ap.add_subparsers(dest="verb", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--manifest"); m.add_argument("--path"); m.add_argument("--projection-id")
    m.add_argument("--client-root-class"); m.add_argument("--baseline-id")
    m.add_argument("--region-begin"); m.add_argument("--region-end")
    c = sub.add_parser("compare")
    c.add_argument("--baseline", required=True); c.add_argument("--candidate", required=True)
    args = ap.parse_args(argv)
    if args.verb == "measure":
        if bool(args.manifest) == bool(args.path):
            raise SystemExit(3)  # exactly one of --manifest / --path
        if args.manifest:
            crc, bid, entries = load_manifest(args.manifest)
        else:
            if not (args.projection_id and args.client_root_class and args.baseline_id):
                raise SystemExit(3)
            sel = ({"kind": "region", "begin": args.region_begin, "end": args.region_end}
                   if (args.region_begin or args.region_end) else {"kind": "full"})
            if sel["kind"] == "region" and not (args.region_begin and args.region_end):
                raise SystemExit(3)
            crc, bid = args.client_root_class, args.baseline_id
            entries = [{"projection_id": args.projection_id, "path": args.path, "select": sel}]
        receipt, code = build_receipt(crc, bid, entries)
        sys.stdout.write(emit(receipt)); return code
    with open(args.baseline, "rb") as fb, open(args.candidate, "rb") as fc:
        base = json.loads(fb.read().decode("utf-8")); cand = json.loads(fc.read().decode("utf-8"))
    out, code = compare_receipts(base, cand)
    sys.stdout.write(emit(out)); return code

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4 — Run the test, verify it PASSES**

Run: `cd _ops/context-measurement && python3 -m unittest -v test_kp_context_measure.py`
Expected: PASS (all classes).

- [ ] **Step 5 — Commit**

```bash
git add _ops/context-measurement/kp_context_measure.py _ops/context-measurement/test_kp_context_measure.py
git commit -m "feat(context-measurement): measure/compare CLI, deterministic JSON, exit codes (TDD)"
```

**Definition of done:** `measure --path` emits byte-identical JSON on repeat; `compare` reports delta + 30% target on OK, and refuses (exit 4) on any identity/version/order/class/baseline mismatch or non-OK receipt; malformed manifest is exit 3.

### Task 4: Governance wiring + operator documentation

**Files:**
- Create: `_ops/context-measurement/README.md`
- Modify: `_ops/checks/verify-operating-model.sh` (add the three files to the structure-presence loop; add a "context-measurement" stanza running `python3 -m unittest`)
- Test: reuse `_ops/context-measurement/test_kp_context_measure.py` (run by the new stanza)

**Interfaces:**
- Consumes: the Task 3 test suite (`python3 -m unittest`), the existing `pass`/`bad` helpers and `$ROOT` in `verify-operating-model.sh`.
- Produces: a new verify stanza whose failure sets `fail=1`; README documenting CLI/JSON/exit contract and invocation.

- [ ] **Step 1 — Write the failing check**

Run: `bash _ops/checks/verify-operating-model.sh --ci`
Expected: BEFORE wiring, verify PASSES but does not exercise the tool (grep shows no `context-measurement` stanza). The "failing" signal for this task is the absence of coverage; after wiring, `verify-operating-model.sh --ci` must run and pass the suite. Prove red by temporarily pointing the stanza at a deliberately failing assertion (see Step 2).

- [ ] **Step 2 — Prove the stanza actually gates**

Temporarily add a failing test (e.g. `self.assertEqual(kpcm.count_words("a b"), 999)`), run `bash _ops/checks/verify-operating-model.sh --ci`, and confirm it now reports `FAIL context-measurement unittest suite` and exits non-zero. Then remove the temporary assertion.

- [ ] **Step 3 — Add the stanza + presence entries + README**

Append the three paths (`_ops/context-measurement/kp_context_measure.py`, `test_kp_context_measure.py`, `README.md`) to the structure-presence `for rel in … ; do` list, and add after the snow-kit stanza:

```bash
echo "== context-measurement (kp-context-measurement/v1) tool =="
cm_out="$(mktemp)"; trap 'rm -f "$cm_out"' EXIT
if ( cd "$ROOT/_ops/context-measurement" && python3 -m unittest test_kp_context_measure.py ) >"$cm_out" 2>&1; then
  pass "context-measurement unittest suite"
else
  bad "context-measurement unittest suite failed"; sed 's/^/        /' "$cm_out"
fi
rm -f "$cm_out"; trap - EXIT
```

Author `_ops/context-measurement/README.md` documenting: algorithm summary (link to program §4.2), the three verbs and flags, the input manifest schema, the receipt/comparison JSON shapes, exit codes/failure classes, determinism/read-only/no-network/content-safety guarantees, and example invocations.

- [ ] **Step 4 — Run full verification, verify it PASSES**

Run: `make verify-ci` (and `bash _ops/checks/doc-warden-verify.sh --sandbox` to mirror the remote gate)
Expected: PASS — new stanza runs the suite green; doc-warden sandbox unaffected.

- [ ] **Step 5 — Commit**

```bash
git add _ops/context-measurement/README.md _ops/checks/verify-operating-model.sh
git commit -m "chore(context-measurement): wire suite into verify + operator README"
```

**Definition of done:** `make verify-ci` runs and passes the measurement suite; the three files are presence-checked; the remote controller gate (`doc-warden-verify.sh --sandbox`) is unchanged; README documents the full contract.

## 6. Acceptance criteria

1. `_ops/context-measurement/kp_context_measure.py` implements the six §4.1 rules exactly, stdlib-only, with a hard-pinned 25-code-point whitespace frozenset (not `isspace()`/`split()`).
2. `measure` emits a deterministic (`sort_keys`, fixed format), content-safe JSON receipt bound to algorithm version, whitespace-set version, ordered projection identity, client/root class, and baseline ID; repeats are byte-identical.
3. Raw SHA-256 is over the exact selected input bytes; strict UTF-8 decode with invalid bytes → `BLOCKED_PREREQUISITE`/`INVALID_UTF8` and no content; CRLF/CR→LF only; astral scalars count as one character; managed-region selection is marker-inclusive; empty input yields zero counts.
4. `compare` refuses (exit 4) differing algorithm version, projection order, client/root class, baseline ID, or a non-OK receipt; otherwise reports integer delta and the 30% target check.
5. Exit codes are stable (0/2/3/4); no measured input is written; no network is used.
6. The `unittest` suite covers every edge in §5 (UTF-8 failure, newline normalization, astral scalar, surrogate impossibility, all pinned whitespace members + the `U+001C`/`U+200B` nonmembers, run grouping, empty input, region selection + region-not-found, identity-mismatch refusal, determinism, content non-disclosure) and runs green under `make verify-ci`.
7. The tool ships behind Dev's governed PR path; `/_ops/` protected-path review is satisfied by the reviewer App.

## 7. Rollback

- Pre-merge: close/abandon the branch; no runtime state changes (read-only tool, no installer, no hook).
- Post-merge: `git revert` the implementation commit(s) on a fresh branch through the same governed PR path. Removing `_ops/context-measurement/` and its `verify-operating-model.sh` stanza fully retires the tool; nothing else consumes it (no baseline was frozen, no memory was touched). Reverting is proven in Stage 2 in an isolated disposable copy (apply revert → `make verify-ci` green → discard) so the live branch never holds destructive state.
