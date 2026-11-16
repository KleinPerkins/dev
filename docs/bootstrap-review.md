# Full-tree seed review capture

`scripts/bootstrap_review.py` implements a separate, bounded source-only capture
procedure. Its implementation and actual originating-account runtime must be
independently qualified before its output can support a seed release. Unit tests
use disposable Git roots and synthetic runtime events; they are not a real review.

Inputs bind the exact new ID/name, seed commit/tree, independent empty genesis,
reviewed file classification, raw successor/enrollment bytes, public object
inventory, validation-result manifest and private qualified account enrollment.
The publication repository must contain exactly the seed and its empty genesis
ancestor. Its only ref is the direct active publication branch pointing to the
seed; tags, other branches, remote refs and symbolic aliases are rejected. The
complete object store must equal the closure of the exact seed commit, never
the union of all refs. Alternates (including HTTP alternates), grafts, shallow
ancestry, replace refs, old ancestry, unreachable imported objects, dirty source, unsupported modes, symlinks, hardlinks, binary files or
unclassified bytes. Executable bits on approved Dev scripts are retained.

The closed manifest records every tracked regular UTF-8 file's path, mode, byte
length, SHA-256 and Git blob ID. Bounds are 4,096 files, 64 MiB total, 4 MiB per
file, 512 KiB per review packet and 128 packets. Stable line-aligned intervals
cover every byte exactly once. Coverage and static relationship review are separate
obligations within the same operation. Coverage packets inspect local bytes and explicitly list their deferred static
relationships;
interface packets repeat the complete actual source and target bodies for each
listed relationship. Deterministic packing seeds each interface packet with the
largest remaining complete endpoint pair (source byte lengths), then selects a
fitting edge by greatest already-present endpoint bytes, smallest exact incremental
canonical JSON bytes, and lexical edge order. Final edges and contexts are sorted;
identical endpoint bodies are shared only within that packet. Exact encoded sizes
and bindings are recomputed; the byte/count caps are unchanged.
Critical source is supplied together to final synthesis, not repeated in every
packet. This avoids forcing an entire declared test inventory into one packet.

The static graph distinguishes local imports, declared references (JSON literals)
and other literal references, including workflow and documentation paths. A
declaration is not an assertion that all listed targets execute together. Conservative module matches,
relative Python imports, applicable ancestor-package initializers and sibling literals are accounted
explicitly. Exact manifest-backed path tokens are also extracted from raw
backticks, unquoted shell/Makefile commands and workflow bodies, plus decoded JSON
string values (including escaped multiline commands). Only whole tokens bounded
by characters outside `[A-Za-z0-9_./-]` match; longer paths do not create substring
aliases. Lexical repository-relative and source-relative paths support `.` and
`..` without escaping the source root. No shell evaluation, variable expansion,
external lookup or guessed dynamic targets occurs. Whole quoted literals retain
their original edges. Loading a dotted child or a relative module also accounts for existing
ancestor `__init__.py` files; absent initializers can be namespace packages and do
not terminate that walk. Unknown literal roles are left for the reviewer. Every discovered edge
is reviewed with both actual endpoint bodies, including inventory edges. Nothing
is replaced by an author-written interface summary. An individual endpoint pair
that exceeds 512 KiB, excessive packet count or oversized synthesis fails rather
than truncating or increasing bounds.

Every payload has a closed, body-bound `packet_kind` (`coverage`, `interface`
or `synthesis`) and exact `review_scope`. A coverage pass means every assigned
local byte was statically examined; it is not a verdict on deferred endpoint
behavior or whole-tree correctness. The absence of bodies for explicitly listed
`deferred_dependencies` alone does not negate local byte coverage. Their edge
judgments remain mandatory separate obligations. No additional dependency can be
implicitly deferred: unlisted dependencies, indispensable dynamic assumptions,
missing same-file context, or unknown semantics needed to judge local bytes still
require incomplete. Genuine defects must always be reported.

An interface pass requires review of every assigned edge using complete actual
endpoint bodies. Unknown executable roles must be examined, and necessary absent
interfaces or dynamic context require incomplete. Reports preserve cross-edge
assumptions for fresh final synthesis. The graph is conservative static accounting,
not proof of complete dynamic dependency discovery. No endpoint summary substitutes
for actual bytes. Binary inspection has no qualified route and blocks capture.

Synthesis has a whole-operation obligation: examine all unedited direct reports,
critical source, byte and edge accounting, cross-edge assumptions and contradictions.
Its lossless obligation map includes packet kinds in packet/report order. Every
incomplete, failed, missing or unresolved obligation remains a veto. Later reports
cannot override an earlier incomplete verdict. Local passes do not establish global
correctness; the fresh synthesis must independently judge that consistency.

Review is static technical source review. Future GitHub settings, App installation,
secrets/variables and actual run state belong to separately gated execution; their
absence alone is not a source defect. Each turn examines implementation of exact
evidence gates within its assigned scope, without inferring platform success.

Each finding has a unique ID. `unresolved_findings` must exactly repeat every
`findings[].id` in order, with no prose, omissions, extras or duplicates. The
strict parser is unchanged. Missing-context-only reports use `verdict=incomplete`,
`coverage=incomplete`, `findings=[]` and `unresolved_findings=[]`, with the missing
context described in `summary`. Genuine source defects remain structured findings
whose IDs are repeated. Such incomplete reports parse but cannot pass closure;
reports are never normalized or rewritten to satisfy the contract.

The capture launches fresh no-tool turns with frozen instructions, ignores
candidate/user rules, checks the account before and after and uses the enrolled
CLI/store/profile. It captures direct event bytes, validates fresh thread/turn
ordering, exact packet/tuple/coverage binding and final-report agreement, and
rejects tools, unknown runtime notices, failures or incomplete output. Each
packet has a 30-minute bound and combined stdout/stderr is limited to 2 MiB;
synthesis has a single 60-minute attempt. Process groups and temporary directories
are cleaned up. It accepts no author-written report or prior completed thread.

A fresh synthesis consumes every unedited direct report, the exact source manifest,
actual critical interfaces and a lossless indexed table mapping each coverage
interval and static relationship to its packet. Indexes name manifest files,
relationship kinds and packet/report order; they are not summaries. Manifest rows
use a lossless columnar encoding: `file_columns` names every original field and
each `files` row supplies its exact values. The full original manifest hash remains
in the source tuple. Runtime event and timestamp metadata stays in the receipt and deterministic closure rather than
being repeated in synthesis. Reports are never truncated to make synthesis fit;
an oversized real report set remains incomplete even if a dry-run plan fits.

Packet bindings hash packet kind, exact review scope, coverage, actual context, relationship obligations, source
tuple and instructions. Closure regenerates the deterministic complete packet plan
and rejects altered or omitted context/edges, even if a caller rehashes them.
Final synthesis derives its critical source directly from frozen contents and binds
the complete canonical body: manifest, obligation map, unedited reports and their
provenance digest, criteria, source tuple and actual critical interfaces. Runtime
capture validates the closed per-kind shape, exact scope/criteria and input-body binding before launch and records its exact payload
hash. Closure reconstructs the full expected synthesis and requires both its binding
and captured payload hash. Removed or altered synthesis context cannot reuse a
report, even with a rehashed deficient payload.
Deterministic closure also rejects missing/extra/duplicate
reports, reused threads, changed tuples, coverage gaps/overlaps, altered bytes,
truncation, unresolved findings and nonpassing synthesis. Changed source requires
new packets and a new whole-tree operation. Both actual producer enrollments and
current capture/creation adapter digests must be present before capture starts.
The closed registry requires exactly two unique producer IDs and two unique opaque
origin accounts. Every row has an enabled flag, the ordinary GitHub principal,
nonempty enrolled CLI version, supported `file`/`keyring` store, current ordinary
instruction and helper hashes, and a closed list of recognized startup-notice
hashes. Both rows are checked before account or review-runtime access. This
validates ordinary admission compatibility; matching hashes do **not** establish
independent real qualification. The release packet still needs actual independent
qualification for both routes and the bootstrap helper itself.

Only completed closure produces a private `dev-bootstrap-review/v1` record. It
is disjoint from `g1-local-review/v1` and `g1-pr-origin/v1`: no PR number, invented
base, comment marker, Check, approval or merge action is synthesized. The later
exact administrative release must name the reviewed seed and manifests. Capture
never uploads source or authorizes publication. If required review context cannot
fit these bounds, report incomplete and qualify a different bounded procedure.

## Measured local source checks

`dev-source-check-manifest/v2` replaces the old three-field success marker, which
is rejected. It binds the exact seed commit, tree, full source-manifest hash and
combined raw CI contract/sharding hash. All eight declared shards must occur
once in contract order, with the full command and test-module union. The current
contract includes 105 modules; inventory discovery remains owned by `verify.py`.
Each result names its command or module, success, zero exit status, SHA-256 of
the actual bounded output, executed case IDs and exact skips. The validator
reconstructs the existing CI measurement from those rows and runs
`verify.validate_measurement`. Missing/extra/duplicate/failed results, empty or
all-skipped modules, unknown/duplicate skips, required runtime skips, inconsistent
counts/digests, and stale source or contract bindings refuse capture. Allowed
partial skips retain their explicit host-not-qualified reasons.

After the final independent seed exists, the coordinator can explicitly execute
the local union and retain its raw evidence outside the source repository:

```sh
python3 -I -B scripts/bootstrap_review.py --measure-checks \
  --repo /isolated/publication --request /private/request.json \
  --policy /private/dev-successor.json --enrollments /private/enrollments.json \
  --publication /private/objects.json --evidence /private/new-check-evidence \
  --output /private/source-checks.json
```

The evidence directory must be new and outside the seed. Commands and module
runners use the existing bounded dispatcher; the source tuple and object store
are frozen again after execution. Only the completed full union yields a manifest.
Raw logs and module results remain in that private directory for inspection;
a failed run may leave partial logs there but yields no passing manifest. Reuse
the resulting manifest as `--checks` for the ordinary bootstrap capture command.
No GitHub run IDs, producer identity, hosted job receipts or platform success are
invented. Source checks execute candidate tests locally and therefore require the
existing source-execution authorization; this option is separate from no-tool
review capture.

These local records remain operationally trusted evidence. A same-user actor can
fabricate inputs or change code; self-hashes are neither provider signatures nor
proof of independent execution. Unit-test synthetic manifests exercise refusal
and schema compatibility, while the collector's disposable Python fixture proves
measured command execution and log binding. Neither proves the full production
source union, hosted CI, both real accounts, App readiness or publication clearance.
