# Personal Mac reconstruction kit

This opt-in entrypoint reconstructs explicitly classified personal repository sources on
Apple-silicon macOS. It preserves the existing work-machine bootstrap. It does not claim a
fully installed personal ecosystem while required capability, local-state, or owner gates remain.

The manifest accounts for repository identities, installed capability families and local state.
It is a host reconstruction plan, not a replacement for capability enrollment metadata.
Repository availability, runtime installation, native discovery and functional qualification are
different outcomes. The installer does not execute code from cloned repositories or write host
MCP/skill/hook configuration.

## Fresh-account native utilities

The bounded build-23880 route for `imported/goal` and `imported/shell` is specified
in [PERSONAL-NATIVE-IMPORTS.md](PERSONAL-NATIVE-IMPORTS.md). It selects OpenAI's
fresh-account native interfaces without copying old profiles or creating home
skill links. The read-only observer cannot grant installation, goal lifecycle or
source acceptance authority. Actual personal identity, offered interfaces,
functional observations and unchanged destination preimages remain separate
checks; no other required import inherits this route.

[PERSONAL-NATIVE-SKILL-CREATOR.md](PERSONAL-NATIVE-SKILL-CREATOR.md) separately
selects and qualifies the enabled system Skill Creator for `imported/create-skill`.
It requires the exact provider/private runtime, actual authoring and behavioral
evidence, independent metadata review and preserved destination state.

[PERSONAL-INTERNAL-COMMS-CANARY.md](PERSONAL-INTERNAL-COMMS-CANARY.md) defines
a separate temporary Codex qualification for the exact pinned Internal Comms
skill. It preserves all four writing guidelines, requires exact publication and
one-worker consent, and always rolls back before local output and semantic
review. It grants no retained installation or other skill authority.

## Personal Plan Refine temporary qualification

[PERSONAL-PLAN-REFINE-CANARY.md](PERSONAL-PLAN-REFINE-CANARY.md) defines a
Codex-only temporary owner profile for the complete pinned Plan Refine skill.
It preserves the accepted transaction, narrow governed plan surface, ordered
four-test doctrine, all eight fixture states and separate source/native/model/
retention gates. The registered source suite has 37 profile/source/fixture
methods; the unchanged eleven canonical doctrine tests are separately verified
against the pinned Skills payload. Synthetic reports prove no model behavior.

## Personal Theme Factory temporary qualification

[PERSONAL-THEME-FACTORY-CANARY.md](PERSONAL-THEME-FACTORY-CANARY.md) defines the
exact-pin, one-link Codex-only profile and selected/unselected/custom-review fixture.
Source acceptance and fresh exact publication/worker consent are prerequisites;
asset checks grant no native exposure or retention. Other skill profiles are unchanged.

[PERSONAL-THEME-FACTORY-RETAINED.md](PERSONAL-THEME-FACTORY-RETAINED.md) defines the
separate exact-evidence retained operation: one Codex link, no model worker and
one bounded local catalog process. Source acceptance and fresh exact retained
consent remain separate from the temporary canary and its evidence decision.

## Personal active-v2 documentation reads

[PERSONAL-DOC-V2-READ.md](PERSONAL-DOC-V2-READ.md) describes the manifest-selected
active-v2 doctor/view and proposal dependency. It preserves current owner semantics
on fenced private file snapshots and binds all 23 canonical schemas. It does not
adopt old state or close the separate full active-v2/native/retained requirements.

## Personal Codex GSD source text

[PERSONAL-GSD-CODEX-SOURCE.md](PERSONAL-GSD-CODEX-SOURCE.md) describes the exact-pin
package/text observer. It binds four raw Codex conversions without invoking the
installer, publishing skills or redirecting home variables. Native paths, the
authoring transaction boundary and retained installation still require their
complete owner workflow; raw descriptor hashes are not installed hashes.

## Usage

### Configure the standard Personal Codex skills

On a new machine with a Dev checkout and Personal Codex, run this from the
Dev root as part of configuring the machine:

```sh
bash bootstrap.sh --profile personal-codex configure
bash bootstrap.sh --profile personal-codex configure --check
```

The first command exposes eleven user skills. `capability` uses the three
hash-verified files from its pinned public Skills release. Frontend Design and
Web Artifacts Builder include their complete pinned skill directories, licenses
and the third-party notice from Skills. The [design package manifest](personal-design-skills.json)
identifies each source file. Setup verifies these files before publishing the
discovery links. Web Artifacts Builder uses pnpm and its documented project
dependencies when you build an artifact.

Plan Refine checks and hardens plans before implementation. It follows the selected
project’s authoring policy and preserves accepted plans through the successor workflow.
Prompt Architect includes its framework references, templates, analyzer and evaluator.
Verification Before Completion supplies the evidence-checking instructions. The
[authoring skill manifest](personal-authoring-skills.json) pins the three complete
skill directories. When the Codex link already points into the corresponding
`~/dev/capabilities/skills/global/skills` checkout, setup checks the selected
files there. Withdrawal preserves that checkout and its link.

IsoKit includes the figure library, examples and browser checker. On first setup,
install Node.js 20 or later and npm. Dev verifies the selected public Skills files,
then runs the Skills installer in a temporary home to provision Playwright Core
1.64.1 from the owner’s lockfile. Setup checks the installed dependency files and
imports the browser API. The browser executable has a separate operator-approved
download when you use the checker. If Codex already links to the matching IsoKit
checkout under `~/dev/capabilities/skills/local/skills`, configuration verifies it
in place and withdrawal preserves its link. [IsoKit release manifest](personal-isokit.json).

Save-Game saves a private checkpoint and resumes it in a fresh session. Dev
installs the complete Skills release pinned by Doc-Warden. If the Codex entry
already points to that release under `~/.local/share/save-game/source`, Dev
verifies its contents in place. Withdrawing the profile preserves that
independent entry and the private checkpoint data. The standard profile can
upgrade its owned predecessor after it verifies the new package. If publication
is interrupted, repeat the same configuration command. Dev retains the old
release and its ownership witness. To revert a managed profile, withdraw it
from the new source and configure it from the earlier source. Coordinate the
Save-Game package change and any rollback with the matching Doc-Warden release
before using governed authoring. An independently installed matching predecessor is verified in place and
reported as an update pending until the coordinated owner upgrade.
[Save-Game release manifest](personal-save-game.json).

Local Jobs runs on-demand commands and schedules explicitly configured jobs.
Setup installs the global Skills release and a private Python fallback with
PyYAML 6.0.3. It uses the system Python supplied with the Mac developer tools.
The generated dashboard has one owner-writable file alongside the read-only
source. Job definitions, history and launch agents retain their existing owners.
Setup exposes the Codex skill without scheduling any jobs. Withdrawal preserves
the private job state and an existing matching independent installation under
`~/.local/share/local-jobs/releases`. Setup verifies a new release before
withdrawing a profile-owned predecessor. A verified independent predecessor
stays on its original link, and the profile reports its revision and pending
update. Its owner can then replace that link through a scoped update. The
predecessor package, generated dashboard and private job state remain available
for recovery. [Local Jobs release manifest](personal-local-jobs.json).

`dev-doctor` uses the Dev release from PR 38. Its `inspect-created` command
reads local Git state for a Dev-created Personal checkout selected by its exact
owner and repository name. `dev-new-repo` uses the sealed creator release from PR 31.
`dev-remove-repo` uses the versioned Personal retirement view to report what needs
preserving in one explicitly selected, Dev-created checkout. The Git inspection
uses temporary scratch space. Canonical removal and recovery require a
separately qualified Dev retirement operation.
The [release manifest](personal-dev-skills.json) lists each Dev file’s Git
mode, length and SHA-256. Setup stages only these runtime files in the working
directory of each release. The creator keeps a read-only Git object store
for Doc-Warden. Setup checks the pinned commit, the entire object store and
the permitted Git metadata before accepting that authority. A full Dev clone supplies the source objects
locally. A shallow clone can fetch a missing pinned revision over public HTTPS.

Open a fresh Personal Codex session after configuration. The check verifies the
published files and their discovery links. Existing installations pointing to
the verified releases retain their original ownership. An occupied slot
pointing elsewhere is reported and preserved. Repeating setup can use the
verified releases offline. Plugin installation stays with the operator, and
Ecosystem Orchestrator governs downstream distribution.

Setup verifies the new doctor package before withdrawing any profile-owned
previous entry. The previous package and ownership record support offline
rollback using the prior profile. An independently installed previous doctor
requires a separate replacement through its installing owner's recovery record.

If setup reports that an earlier creator needs a sealed Dev authority directory,
its discovery link and release stay in place. Use the installing owner's
recovery record to qualify a replacement before switching the existing release.

To withdraw profile-owned discovery links, run
`bash bootstrap.sh --profile personal-codex configure --withdraw`. Earlier
matching installations remain in place. The versioned files remain available
for reconfiguration. Each skill has its own ownership record and recovery
history. When a link to the independent Skills checkout replaces an installed
authoring skill, withdrawal leaves that checkout in place and checks the
earlier ownership record and cached release. Once the user vacates the slot,
configuration can restore the cached release offline. Interrupted setup can be retried. An interrupted withdrawal can be
resumed using the same command. The source reconstruction report below tracks
the selected transfer manifest separately.

If another writer replaces the entry during withdrawal, the installer restores
that entry when the slot is vacant. If a second entry already occupies the slot,
the command reports both paths and preserves the displaced entry. Each withdrawal
keeps its own recovery directory under the skill’s control directory in the selected Codex home. The core
capability retains its existing `dev-personal-core/withdrawals` history. Once
the operator has preserved the new occupant and vacated the slot, another
`configure --withdraw` restores the displaced entry.

### Enter repo-platform

When a Dev release pins a repo-platform runtime, the Personal configure command
installs and verifies its profile-owned runtime link alongside the Skills index.
The runtime link stays outside the Codex skill picker. The Dev owner publishes
the selected checkout authority separately.

Use the native CLI catalog's project ID and an explicit checkout path. Supply the
native thread ID for a linked checkout.

```sh
bash ~/dev/bootstrap.sh --profile personal-codex repo-platform adopt "$checkout" --project-id "$project_id"
```

The launcher verifies the installed package, its profile-owned link, and the
qualified native client on each call. It runs from a private verified copy of
the client's executable and the signed companion files for macOS app bundles.
It reads public GitHub identity without credentials and resolves Dev's delivery
classification for the selected checkout. Private checkout adoption requires
a separately qualified provider binding.

Use `configure --repo-platform-only --check` for the installed launcher and
`configure --repo-platform-only --withdraw` to park that owned launcher. To
restore it, select the Dev release that pins the intended runtime and run
`configure --repo-platform-only`. The profile preserves other entries and
keeps the pinned runtime and its withdrawal record for offline recovery.

The Desktop caller uses `run_desktop` with live native project and chat readers.
It uses the same installed Personal package and checkout authority. The
standalone bootstrap command continues to use the CLI catalog.

The normal Personal configure withdrawal saves the runtime pointer and leaves the
cached release and separately installed owner session available for recovery.
Run configure again with the same Dev release to restore the verified runtime
from the local cache. When a successor pin names a previously installed release,
setup verifies the successor before withdrawing the profile-owned predecessor.
A replacement managed by another installer is preserved and refused. Repeat
configure after an interruption. To restore the predecessor, withdraw from the
successor source and configure from the earlier Dev release.

### Reconstruct sources

From a curated package, run `python3 engine.py --help`. From a safe development checkout, use:

```sh
bash bootstrap.sh --profile personal-codex plan --manifest _ops/portability/manifest.json --root "$HOME/dev" --state-dir "$HOME/.local/state/personal-portability"
```

Prerequisites are Python 3.10 or newer, Git, and personal GitHub access over SSH. A connector/CLI session
does not itself configure SSH. The destination agent should establish new personal machine
credentials through the authenticated account when needed; no old private key transfer is assumed.

Use `preflight`, `plan`, `apply`, `resume`, `verify`, or `rollback` as the operation. Keep the
same manifest, target root, and private state directory when resuming. An explicit `--report`
writes a private report; plan/preflight otherwise avoid filesystem mutation. Read the report after
every operation: a nonzero status may mean eligible source reconstruction finished while required
capability or preservation items remain blocked. Never relabel that as complete.

`apply`/`resume` create only allowed new clones, verify pinned revisions, and set local personal
Git identity. Existing mismatched repositories and files are preserved. Rollback refuses changed
repositories, new refs, and user-created files; it cannot remove pre-existing repositories.

## Why the whole dev repository is not in the package

The source repository contains work-authored planning content and historical mixed state.
The package builder exports only the six named portability implementation/instruction blobs,
plus generated integrity metadata. It exports neither source Git history nor host configuration.
The manifest keeps the full dev repository and other unresolved mixed sources blocked.
Source preparation evidence is retained in the source repository's
`_ops/portability/SOURCE-REPORT.md`; it is not part of this six-file payload. The manifest carries
the dispositions and blockers needed by the destination agent.

This safe subset is a reconstruction kit, not a new canonical Git repository or an accepted
history migration. Publishing a separate personal source repository/branch requires an explicit
owner architecture decision if needed to meet the remaining repository requirement. Source
history is never rewritten by the kit.

## Package creation

After verified source merge:

```sh
python3 _ops/portability/package.py --revision FULL_MERGED_SHA --output /private/tmp/personal-bootstrap.zip
```

The builder fetches canonical main into a private temporary bare repository, checks the source
revision's ancestry, and removes that temporary repository afterward. This source-machine build
step may fetch mixed history locally; only the allowlisted blobs enter the package. The builder
reads bounded immutable Git blobs, refuses existing output, produces a deterministic archive, and resolves the source
revision in the destination prompt. A checksum detects changed bytes; authenticate the checksum
and source through the personal repository or the operator-provided handoff before executing.

## Separate personal Canvas Design canary

The proposed Codex-only temporary workflow is documented in
[PERSONAL-CANVAS-DESIGN-CANARY.md](PERSONAL-CANVAS-DESIGN-CANARY.md).
Source checks and synthetic PDF fixtures do not authorize native publication, a
model worker, evidence acceptance or retained installation. Each remains governed
by the documented exact source, operation, native and owner gates.

## Remaining qualification

- Resolve mixed-content exports before changing blocked repository rows. Scanner-only findings were classified in SOURCE-REPORT.md; this does not prove every source is free of sensitive content.
- Preserve classified dirty worktrees and ignored personal media/state with restore evidence.
- Use owner-qualified native installation and capability checks. The broad Skills reconciler,
  legacy MCP mirror, AWA overlay, and work distribution jobs are not substitutes.
- Discover the new personal account's plugins, entitlements and tools there. Do not copy account
  caches, OAuth sessions, chats, generated memories or work-derived profile data.
- Record actual destination verification separately from source unit/clean-room tests.

Tests: `python3 -m unittest discover -s _ops/portability -p 'test_*.py'`.

## Explicit read-only device attestation for the 17e962df destination

A recorded `st_dev` value can differ from the currently observed value. The legacy engine
correctly refuses that mismatch; matching inode numbers alone do not prove volume continuity.
The legacy package and journals must remain unchanged. `device_attestation.py` is a separate,
opt-in verification interface for this exact approved manifest, immutable engine and accepted
INT-008 two-skill operation. It cannot resume reconstruction, roll back, adopt directories,
rebind journals, alter native links, or weaken the default entrypoint.

After source acceptance, the destination agent prepares a private preview with `preview`,
passing `--kit`, `--root`, `--state-dir`, `--skills-runtime`, `--skills-operation`, and
`--attestation <new-private-preview.json>`. The preview checks all legacy repository
postimages, including Git metadata inventories, config, refs, identity, ancestry, clean tracked
source and unchanged directory inodes. It validates the original approved skill action and
receipt, source proof, relevant policy, preserved paths and complete retained postimages.
It resolves each target's current backing filesystem through `df` and `diskutil` and requires
one internal APFS UUID. It does not fetch or execute repository code.

The old journal did not record a stable UUID. These checks therefore do not establish old-volume
continuity. The operator must explicitly accept the complete preview as fresh attestation of
the present **read-only** observations. Source acceptance alone is not that acceptance; a digest
alone is not consent. The preview binds the implementation bytes, APFS UUID, exact original
record hashes, root/state/operation paths, original source postimages and inodes. The current
device number is informational: subsequent observations may translate that number in memory
only while every approved stable identity and content/config/ref check still matches. Changed
UUIDs, inodes, metadata, records, policies, partial installations or skill links refuse.

After that exact acceptance, invoke the same accepted implementation with `verify`, the same
arguments and `--approve <preview-action-sha256>`. It invokes the unchanged legacy validators
on private in-memory copies with the current device number. Original engine/manifest/journal
and native operation/receipt bytes are not written. Only the already bound verification report
and report-owner record are refreshed. The report labels this explicit verification extension
and grants no mutation authority. Legacy `apply`/`resume`/`rollback` continue to refuse their
old identity mismatch; any future writer recovery needs its own reviewed contract.

Tests include actual disposable Git repositories with the unchanged legacy engine, preservation
of original journal bytes, report generation, Git metadata drift, default refusal, exact consent,
volume/inode/mode changes, symlink/hardlink refusal, partial-state refusal and mutation denial.

## Whole pinned Codex GSD bundle dependency

[`personal_gsd_codex_bundle.py`](personal_gsd_codex_bundle.py) adds a fixed-path
private cache/prepare/verify route for the complete unchanged GSD pin. It retains
all package companions and whole runtime workflows, uses upstream public emitters
with explicit configuration inputs, and seals a hash-bound private artifact. It
does not publish skills, launch workers, adopt profiles or install native config.
See [the complete contract and remaining owner gates](PERSONAL-GSD-CODEX-BUNDLE.md).

