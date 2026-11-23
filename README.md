# KleinPerkins/dev — home operating model

This repository owns the shared policy, bootstrap tools, agent instructions and
verification for `~/dev`. Nested capability, personal and work repositories keep
their own contents and Git history. Work material, private profiles, credentials,
client configuration and machine-state evidence do not belong in this source.

Start with [AGENTS.md](AGENTS.md), the [operating manual](OPERATING-MANUAL.md), and
[the enforced policy](_ops/POLICY.md).

## Successor preparation and delivery

This source is prepared for a new repository identity, initially
`KleinPerkins/dev-temp` and finally `KleinPerkins/dev`. Only immutable GitHub ID
`1459458379` identifies the successor. Name reuse does not transfer old repository
history, PRs, approvals or runtime qualifications.

The installed PR controller is retired. PAC mini actions is planned development,
not an operational dependency. The lasting delivery standard is substantive,
sharded GitHub Actions CI plus automatically initiated independent agent review
from the PR's originating Codex account. The qualified Chaos Scheduler App owns
approval and native squash delivery. No human technical review is required.
See [delivery](docs/github-delivery.md), [review](docs/local-review.md),
[bootstrap review](docs/bootstrap-review.md), and
[successor adoption](docs/runbooks/dev-successor-adoption.md).

Source preparation does not establish hosted CI, App readiness, installation or
migration. The exact seed, publication, settings, name transition and host cutover
require their separate administrative release. Keep the empty staging repository
private with Actions disabled until that release. Never upload predecessor Git
objects, private preservation packages or work material.

## Layout

```text
~/dev/                         master operating-model repository
├── capabilities/             reusable or ecosystem-maintenance repositories
├── personal/
│   ├── src/<git-owner>/<repo>
│   └── vendor/<git-owner>/<repo>
└── <work-container>/          employer-specific; currently affirm
    ├── src/<git-owner>/<repo>
    └── vendor/<git-owner>/<repo>
```

`src` is contribution-enabled; `vendor` is read-only reference. Capability
repositories may support local use or governed transport to another repository.
Existing work-Mac paths remain usable until separately migrated. Establish the
functional mac-mini first; broad work-Mac reorganization follows later.

## Verification and installation

```bash
make verify-ci       # source checks in an isolated checkout
make gen             # regenerate source instruction mirror only
make verify          # source plus installed-machine verification
make help
```

`make verify` is not a source-only test. Installers affect the host and require the
applicable installation release. In particular, do not copy `.git` into a populated
`~/dev`, reset it, or replace linked-worktree metadata using a generic bootstrap.
The reviewed host transaction must preserve nested repositories and unfinished work.

After the released clean repository is active, a genuinely new empty host can use
the repository's bootstrap procedure. A personal-only host uses the bounded
personal reconstruction route in [_ops/portability](_ops/portability/README.md);
it must not fall back to work integration or broad host installation.
Run `bash bootstrap.sh --profile personal-codex configure` to install the core
capability playbook, personal repository doctor, product creator, Frontend Design,
Web Artifacts Builder, Prompt Architect, Verification Before Completion, IsoKit
and Save-Game. Its `--check` option verifies the nine versioned
packages and their Personal Codex user entries.

The allow-list `.gitignore` tracks only reviewed operating-model source. Local
identity remains `KleinPerkins <49759187+KleinPerkins@users.noreply.github.com>`;
work repository identity follows its own owner policy.
