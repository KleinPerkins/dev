# Personal baseline diagnostic

`personal_baseline.py` adds read-only personal baseline eligibility and all five
canonical file checks to the scoped doctor dependencies. This is a component
diagnostic; complete doctor/native and migration acceptance remain separate.

After immutable owner source acceptance, export the five exact Python modules
(`personal_scope.py`, `personal_git.py`, `personal_worktree.py`,
`personal_controls.py`, `personal_baseline.py`) and the three compared templates
under `_ops/baseline/template/`: `SECURITY.md`, `dependabot.yml` and
`gitignore-block.txt`. Verify every accepted blob and compiled template digest.

```text
python3 -I -B personal_baseline.py inspect
python3 -I -B personal_baseline.py inspect --repository KleinPerkins/skills
```

Only the twelve manifest-selected personal primary checkouts are admitted.
Verified origin and scoped worktree evidence precede eligibility. Dirty,
detached and non-`main` checkouts remain `EXCLUDED` with the original reason.
Refused origin/status evidence remains `UNAVAILABLE`. Exclusions have no
file-compliance verdict and never move a ref to make a checkout eligible.
Approved source pin and personal identity evidence remain separate.

For an eligible clean `main`, the five checks retain their canonical semantics:

| File | Observation |
| --- | --- |
| `SECURITY.md` | `MISSING`, `CURRENT`, `STALE` or `CUSTOM` from the owner marker and exact template bytes. |
| `.github/dependabot.yml` | The same marker-and-byte states against its exact owner template. |
| `.gitignore` | `MISSING`, `CURRENT` or `STALE` for the managed region, preserving LF records, substring markers, multiple blocks and shell trailing-newline behavior. |
| `.github/CODEOWNERS` | Create-only `MISSING` or owned regular-file `PRESENT`; contents are not read or compared with a scaffold. |
| `README.md` | The same create-only presence check; project-owned contents remain untouched. |

All three core files absent means `MISSING`, even if the two auxiliary files
exist. Current core files plus both present auxiliary files means `COMPLIANT`.
Other defined file combinations are `PARTIAL`. Unavailable evidence never
becomes missing or compliant. The qualified Mac comparison retains BSD awk's
NUL string termination; other-host CI text fixtures do not assert that host's
binary-control-file equivalence.

Controls use bounded no-follow reads, parent identities and visible-edit
checks. Aliases, nested checkout boundaries, shared/special/foreign controls or
unavailable bytes remain unknown. A second eligible-worktree observation
rechecks clean status around file inspection. Later edits are preserved and
the observation refuses. This is not a hostile same-user writer sandbox.

All Git probes use disposable private metadata/index views. Copies preserve
the source mtime so Git still detects racy same-stat content changes. A new
timestamp on a private index could otherwise suppress Git's content comparison.
Deterministic plain- and split-index fixtures reproduce the old false-clean
result and verify the correction against Git on the original synthetic index.
Only private copies receive timestamp writes; source index facts stay intact.

The test oracle extracts only exact accepted pure read-only functions from
the owner baseline library into an isolated synthetic harness. It never sources
the full library, broad doctor, profile/remote verbs or archived recovery code.
All 192 defined aggregation combinations and the five file-state comparisons
are checked, including eligible real-Git fixtures and visible later edits.

Successor preparation retains the historical `OWNER_REF`/`OWNER_LIBRARY_BLOB`
provenance for those unchanged pure algorithms. The current library-container
SHA-256/blob test bindings and `TEMPLATE_HASHES` separately identify the reviewed
successor bytes. The security template removes the assumption that every repo is
private and directs fixes through governed verification, review and delivery;
it no longer promises direct pushes to `main`. The delivery-policy functions
outside the extracted oracle change independently. No full-library execution is
added to the oracle. Tampered templates, substituted aliases, the old security
template and a modified library container remain rejected. Rebinding this source
is not personal adoption, source publication or runtime qualification.

Baseline findings remain advisory. Available exclusions or `MISSING`/`PARTIAL`
diagnostics exit 0; unavailable evidence exits 2. Exit 0 is not complete doctor
or migration acceptance. Runnerless profile checks outside baseline eligibility,
personal delivery rules, structural documentation, classified linked worktrees
and complete caller/native qualification remain required. This interface grants
no apply/enforce/install, source/config/hook changes, shared publication, model
worker, service or remote authority.
