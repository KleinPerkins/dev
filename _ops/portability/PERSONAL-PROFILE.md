# Personal runnerless profile and delivery diagnostic

`personal_profile.py` is the explicit personal-only v3 successor for the profile
and delivery portion of a bounded destination doctor. It covers the same twelve
manifest-selected primaries as `personal_baseline.py`. This component does not
change the broad doctor or its legacy compatibility CLI. Complete doctor/caller,
native discovery and migration acceptance remain separate.

The broad doctor's unversioned `profile pr-automation verify|status` calls still
dispatch to the adjacent Phase A implementation. That implementation requires a
closed `pr-automation/v1` config. Current v3 configs therefore fail that legacy
verifier even when their current v3 contracts pass. This successor deliberately
uses the active v3 owner contract and records the legacy incompatibility as
compatibility evidence. It never converts a v3 policy to v1, creates a legacy
enforcement-state record, infers enforcement from a directory, or activates
Actions. A non-v3 profile remains unavailable and requires its separate owner
compatibility workflow; it cannot become a passing v3 observation.

## Qualified source and private export

The authority snapshot is Dev commit
`9ac8369944f45b9e3f5e8d455ee03fad191cfd74`, with v3 `profile.py` blob
`35587bb4afc9b4c75b6bc1c5dbce6f172991363a`. `personal_profile_contract.py`
retains the exact pure owner definitions except for three explicit I/O adapters:
`_render_base_ruleset` takes template text, and `resolve_repository_projection`
and `validate_policy` receive that template and all authority explicitly. No
filesystem, network, writer or lifecycle verb is present in the pure module.
Tests compare all other definition ASTs against the exact owner blob and compare
all ten selected enrolled projections and both fingerprint layers with an
isolated oracle made only from those current pure owner definitions. The full
profile script is never imported or executed by the tests or runtime.

After normal immutable source acceptance, privately export the seven exact
Python modules: the existing scope, Git, worktree, controls and baseline modules,
plus `personal_profile.py` and `personal_profile_contract.py`. Include the three
baseline comparison templates and these four unchanged v3 authority files under
`_ops/baseline/profiles/pr-automation/v3/`:

- `fleet.json`
- `controller.json`
- `coverage-assignments.json`
- `merge-safety.ruleset.json.tmpl`

Every file is hash bound; aliases, shared files and visible changes are refused.
Fleet metadata is declarative input only. It never expands the selected roots or
remote request targets. A changed qualification snapshot requires a new owner
source update and verification; this diagnostic does not claim automatically
current fleet or controller-release acceptance.

## Local behavior and applicability

```text
python3 -I -B personal_profile.py inspect
python3 -I -B personal_profile.py inspect --repository KleinPerkins/skills
python3 -I -B personal_profile.py inspect --responses-stdin < private-responses.json
```

Exact personal origin and the accepted Git/storage fence precede control reads.
Baseline applicability is observed before and after the profile checks; visible
head, branch, eligibility, compliance or worktree changes make the result
unavailable. No ref is moved to make a target eligible.

Local v3 profile checks apply whenever the owned regular profile file is present,
including dirty, detached and non-main baseline exclusions. They preserve the
owner's closed policy and verification manifest, CODEOWNERS block counts and
required ownership strings, and the one-level `*.y*ml` workflow exclusion for
legacy automation text. Controls are bounded no-follow reads with ancestor,
directory-membership and final-edit checks. A missing profile is explicitly
inapplicable. Unsafe or unreadable controls are unavailable, never missing or
compliant. Other malformed but safely observed contract bytes are noncompliant.

Effective human-review rules apply only to an eligible personal baseline target.
The baseline history ruleset check additionally requires local `COMPLIANT` files.
Profile bypass and deployed-fingerprint checks remain independent of those
baseline exclusions. Only the closed personal scope is runnerless-default here;
no native-delivery exception or other target is adopted.

## Connector protocol

The program makes zero network requests. An initial inspection reports exact GET
requests for the required selected repository metadata. Feed personal connector
observations on stdin for another inspection. An exact immutable repository ID,
full name and qualified default branch must match before any dependent request
is emitted. Never execute a dependent request merely because it appeared in an
untrusted response. Requests never contain credentials or arbitrary roots.

```json
{
  "schema": "personal-profile-responses/v1",
  "observed_at": "2026-11-02T23:00:00+00:00",
  "requests": [
    {
      "url": "https://api.github.com/repos/KleinPerkins/skills",
      "outcome": "ok",
      "data": {
        "id": 1275604090,
        "full_name": "KleinPerkins/skills",
        "default_branch": "main"
      }
    }
  ]
}
```

Use the earliest actual UTC capture time in the response bundle, at most five
minutes old and at most thirty seconds in the future. Responses are limited to
one MiB, one hundred exact
selected request URLs, JSON depth 64 and 50,000 nodes. Duplicate JSON keys,
duplicate URLs, nonfinite numbers, foreign targets and unknown fields are
refused. Outcomes are `ok`, `not-found`, `forbidden`, `plan-limit`, `timeout` or
`unavailable`; non-success bodies must be null. A response is observation data,
never authentication, publication, installation or owner approval.

The program then emits only applicable dependent requests: effective branch
rules, baseline rulesets, the exact centrally enrolled merge-safety ruleset ID,
and the qualified default branch. The branch response binds an exact commit and
root tree. Subsequent requests select only `.github` from that exact root tree,
then only `pr-automation.json` from the exact child tree, then that regular
file's exact blob. Both complete, non-truncated trees must reproduce their Git
object hashes from all returned entries. Aliases, Gitlinks, wrong object types,
duplicate names, unknown modes or more than 1,000 entries remain unknown. A
complete proven tree without the selected path establishes `NOT_STAGED`; an HTTP
404 or denied object read does not establish file absence.

Git tree responses use the GitHub REST JSON object. For an exact blob GET, the
connector adapter places its verbatim decoded UTF-8 text in the response's
`data` string. The diagnostic recomputes its size and Git blob object hash against
the proven leaf. It does not rely on the generic contents endpoint, which may
normalize away file provenance. Only dynamic tree/blob URLs reached through the
validated branch/path proof can be consumed or emitted. Unreferenced supplied
Git objects are refused. A trusted parent may call the same pure
`remote_contract` planner using its prior local applicability snapshot to collect
these staged requests efficiently; the final `inspect` re-observes the actual
local checkout and its eligibility on both sides of all checks.

Ruleset identity includes ID, name, target, active enforcement, source type and
exact repository. Effective rule and ruleset lists reaching the fixed 100-entry
page bound remain unknown; no partial page can prove clean status.

Numeric positive human-review counts yield `REVIEW_DRIFT`. Qualified identity
plus a visible `RepositoryRole:5` is positive admin-bypass evidence. An absent or
redacted actor is `UNKNOWN`; App observations cannot establish an owner-visible
negative or grant operator-full attestation. The deployed policy must bind the
exact live repository before its fingerprint can be clean or stale. Its current
closed v3 contract and live App-visible ruleset fingerprint are also checked
against the independently derived owner projection. No full control-plane,
lock-compiler currency, controller configuration, writer or service acceptance
is inferred from these checks.

## Results and limits

Available known contract drift remains a diagnostic: local contract problems or
missing baseline enforcement are advisory; required reviews, stale deployed
fingerprints or live App-visible ruleset drift are `DRIFT`. Unknown observations
and plan-limited history evidence are unavailable and at least advisory. Exact
metadata failure prevents dependent requests. Available diagnostics exit 0;
unavailable observations or refusals exit 2. Neither exit code closes a native
capability or migration gate.

The original legacy state/status records and lifecycle remain separate. This
accepted successor replaces their enforcement claim only within the explicit
personal v3 diagnostic: exact enrolled live identity and policy/ruleset parity
are observed directly. It does not claim legacy state is absent or current.
Linked-worktree classification, documentation governance, full doctor verdict
mapping, native qualification and remediation of existing owner findings still
require their own complete implementations and evidence.

No apply/enforce/repair/rollback, credential refresh, account sign-in, source or
configuration edits, hook execution, service changes, shared links or model
workers are offered by this interface.
