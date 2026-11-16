# Account-bound ready PR creation

After fresh passing review, the authoring agent invokes
`scripts/create_review_pr.py` with the exact source request, raw policy, private
account enrollment, unedited review receipt, title/body files and distinct private
output/journal paths. The adapter requires a public repository, fresh live main
and head refs, clean unchanged source, no existing matching PR, the owning GitHub
principal, and the same qualified Codex account before and after creation.

Repository lookup must resolve the selected closed phase name to immutable ID
`1459458379`. `KleinPerkins/dev-temp` and `KleinPerkins/dev` are the only phases;
they are not simultaneous receipt aliases. The old ID, redirects to a differently
named repository and arbitrary names refuse. Initial private seed admission is a
separate administrative transaction. This helper does not relax public visibility
or create a seed PR.

The adapter reserves private evidence paths, creates a ready PR with a unique
creation nonce, and posts the separately captured `g1-pr-origin/v1` record. The
record binds the actual creation event, account, exact tuple, adapter digests and
GitHub timestamps. Review alone cannot choose or change origin. A failed or
ambiguous operation leaves an incomplete journal and never retries automatically;
reconcile the actual remote result before any continuation.

The operator is not asked to initiate technical review. The coordinator fixes
findings, re-reviews every changed tuple, publishes the exact review receipt and
maintains the PR until the trusted App's exact-head native squash merge is
verified. Agents do not operate merge or auto-merge APIs.
