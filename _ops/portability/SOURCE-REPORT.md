# Source preparation evidence

This report distinguishes observed source state from destination qualification. No source host
configuration, credentials, services or existing project work were migrated by the discovery.

## Inventory observations

- The first repository scan found 48 checkout records, including duplicates, transient AWA
  fixtures and a protected-repository record. The installer manifest reconciles 19 named
  repository identities rather than copying checkout directories.
- 61 eligible linked worktrees were observed; 11 had changed/untracked entries. A subsequent
  byte comparison found 10 changed files already covered by live main, 46 differing files
  needing preservation review, and three `.awa/` runtime-state rows that must not be replayed
  as target registration state. Source files and branches were preserved.
- Independent content review classified 39 of the 46 differing files as eligible for an inert
  local recovery snapshot (1,013,023 source bytes). Its extraction/digest comparison passed.
  Seven full files carrying work context or generated memory remain excluded; no checkout was
  overlaid and no protected configuration activated. The separate private snapshot is not in
  the reusable code package.
- 181 installed exposure entries represented 87 distinct names. Preliminary owner/path
  classification found 55 work-source exposures, 66 Skills-owned, 12 dev-owned and 48 imported
  or unresolved exposures. These are exposure counts, not functional-capability counts.
- The live Skills source metadata enumerated 37 capabilities. The host manifest accounts for
  those, imported capabilities, dev utilities, service connections and fresh-account app
  discovery. Source metadata remains the capability authority.
- Thirteen ecosystem LaunchAgents were inventoried by labels and field names only; two were
  explicitly work-only. No schedule or service was activated, stopped or copied.
- Ignored personal media and project outputs exist outside Git. They are required preservation
  items, not disposable caches. No certificate/key transfer has yet been established as needed.
  Metadata-only measurement found approximately 8.6 GB across the two Sterling projects,
  including nine symbolic links in Sterling.io outputs. A separate private archive restored
  2,460 files and those nine internal links with matching bytes. Network delivery, extended
  attributes, ACLs and destination semantic acceptance remain unverified.
- The operator selected personal iCloud Drive as the transfer route. The handoff directory is
  `Personal Mac Migration/2026-11-01-01a195ae`; copied artifact hashes are checked locally.
  Receiving-machine availability and digest checks remain separate evidence.
- A subsequent clean-head audit found 37 unique eligible worktree heads: 35 were covered by
  current remote refs, main ancestry, changed-path tree equivalence, or verified merged-PR
  squash ancestry. Two additional historical/local source units were independently reviewed:
  a 12-file AWA change plus its parent-to-head patch, and a one-file kp-mcp canary. All 13 files
  and the patch are preserved in a separate restore-checked inert snapshot. No protected
  repository or runtime was accessed for that review. This does not establish coverage of
  dormant refs, reflogs or unreachable objects.
- Remote main advanced during discovery for Skills, Operator Voice and Sterling.io. The
  manifest retains its explicitly reviewed snapshot pins; newer remote heads are not silently
  substituted for those pins or treated as qualified native installation revisions.

## Egress boundaries

`KleinPerkins/cpp` archives Affirm source and `KleinPerkins/ai-analytics-context` contains
work-derived analytics context. The ecosystem-orchestrator's distribution edge is work-bound.
They are excluded from the personal installation. The current dev tree contains work-authored
proposal assets, so a normal clone would violate the personal-only data boundary. The package
contains only newly authored portability implementation/instruction blobs and integrity metadata.

Gitleaks scanned available live-main history objects with full redaction. All 287 recorded findings
in dev, Skills, kp-mcp, the PR controller and a doc-warden canary were independently classified
as synthetic test credentials, governance UUID/SHA identifiers, digests, or non-credential Figma
resource keys. This clears the scanner-only blocks on the four otherwise eligible repositories.
Dev and chaos-labs remain blocked for work-derived content in reachable history. A clean scanner result is also not proof of personal
content suitability or absence of every secret. No detected values are in this report.

The initial identity inventory encountered a differently named chaos-scheduler checkout.
Further inspection and every export/install action are excluded by repository identity, not
just directory name. There was no protected repository modification.

## Current completion boundary

The personal entrypoint and package builder are source implementation. Required native capability
qualification, safe source distribution for mixed repositories, local-work/media preservation,
and actual target installation remain separate obligations. The manifest must retain them as
required blocked items until verified; shipping a source kit does not close them.

Source verification results and delivered revisions belong in the PR/package handoff after the
full integrated checks. The destination agent must produce its own report on the actual Mac.
