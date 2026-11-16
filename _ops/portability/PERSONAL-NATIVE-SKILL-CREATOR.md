# Personal native Create Skill alternative

The transfer manifest permits a qualified canonical source or a fresh-account
host distribution for installed non-work imports. This contract selects the
enabled OpenAI system `skill-creator` on personal Codex build 23880 for
`imported/create-skill`. It supports creating and updating scoped Codex skills,
optional UI metadata, and useful scripts, references and assets. Source
acceptance adopts this explicit native alternative. It does not assert an
unknown legacy implementation's behavior, UI or slash-menu parity. All other
imports and migration obligations remain independently required.

## Supported provider and runtime

Use the actual native skill catalog and read the selected provider's current
`SKILL.md` before authoring. The observer binds that file, its three canonical
helpers and its UI-metadata reference by hash. The catalog must uniquely select
the enabled system provider at the account-home `.codex/skills/.system/skill-creator`
path, with no plugin substitution or new discovery root. The host's app/CLI
bytes and the five provider files require requalification if changed.

The canonical helpers need PyYAML. The qualified route uses an explicit private
Python 3.13.18 interpreter and PyYAML 6.0.3 arm64 wheel, not an assumed dependency
in the default Python. The wheel SHA-256 is
`2283a07e2c21a2aa78d9c4442724ec1eb15f5e42a723b99cb3d822d48f5f7ad1`.
Authenticate its metadata through the official PyPI version endpoint, verify the
wheel hash and every RECORD entry, retain its MIT license, and refuse unsafe ZIP
paths, symlinks, executable installation entries and unexpected dependencies.
Install only into the owned private environment using offline `--no-index`,
`--no-deps` and `--require-hashes`; no source build or lifecycle scripts.
Bind the resulting interpreter, all 44 installed package files and license.
Keep this environment available for the qualified helper invocations. Do not
modify system/Homebrew Python, native provider instructions or host configuration.
A changed runtime requires requalification rather than an untested fallback.

OpenAI's [Build skills guide](https://learn.chatgpt.com/docs/build-skills) describes
the native authoring route. The actual build's provider instructions and helper
bytes govern this bounded qualification; a moving documentation page alone
does not establish current native behavior.

## Owner and destination sequence

1. Accept this source through normal current-base owner checks and merge. Verify
   the accepted observer blob into a separate private export. Preserve the
   original manifest, engine, journals, pins, indexes, pending approval preimages
   and installed capabilities. Source acceptance grants no installation or
   publication authority.
2. Independently establish the expected personal ChatGPT identity and current
   workspace. Use a bounded native diagnostic with exactly `initialize`,
   `initialized`, `account/read {refreshToken:false}`, and
   `skills/list {cwds:[workspace],forceReload:true}`. Require a complete response,
   the unique enabled provider and an actually terminal diagnostic. Add no root,
   configuration, plugin, thread, worker or token-refresh request. An unexpected
   account/work workspace or authentication decision stops this route. If the OS
   execution sandbox prevents this read-only diagnostic from starting, request
   only its necessary execution permission; never bypass sign-in or native gates.
3. Verify the provider's five file hashes and filesystem identities before and
   after testing, and verify the private runtime. Create a fresh owner-private
   disposable operation outside all skill discovery roots. Do not repurpose HOME
   or CODEX_HOME. Deny network, fork, real-home file bodies outside the exact
   provider/runtime inputs and writes outside the disposable workspace. Allow only
   metadata traversal of exact runtime/provider ancestors when the Python launcher
   requires it. Prove all six actual allow/deny guard cases before helper use.
4. Follow Skill Creator to author an instruction-only seed-summary skill. Use
   `init_skill.py` with an explicit private output path, finish the scoped routing
   instructions, and run `quick_validate.py`. Refuse unfinished scaffolds and
   verify that reinitializing the existing skill refuses without changing files.
   Exercise `generate_openai_yaml.py` with requested UI values. For an existing
   metadata file, update only the intended display field in place, preserving
   unrelated fields and invocation policy; the generator replaces that file.
5. Create a second seed-inventory reporting skill with exactly useful script,
   reference and heading-asset resources. Validate its relative resource routes.
   Execute the real helper on `basil=5,lentil=9,lentil=4`: the sorted Markdown must
   show basil 5, lentil 13 and total 18. Negative counts must refuse with exit 2;
   header-only input must report total 0. Preserve input bytes and identities.
6. Exercise the complete closed 20-case roster, including malformed/missing
   frontmatter, invalid names, unknown metadata, unfinished body, empty/overlong
   initializer names and invalid resources. Bound every actual child below 15
   seconds, require all terminal outcomes and a total below 150 seconds. Keep
   every failed operation and raw log; retries use new owned roots.
7. Record the observed stock-validator limitation: blank name/description values
   pass its structural check. Independently review actual authored metadata for
   nonempty, discriminating scope and absence of placeholders. Actual helper
   behavior and preservation checks remain required. Neither validator success
   nor this simple example establishes arbitrary authored-skill quality.
8. Hash-bind the actual catalog, runtime record, functional result, qualification
   driver and complete fixture inventory into a private observation. Verify the
   raw bytes and links independently before running the accepted read-only
   observer. Supply expected personal email, workspace and account-database home
   separately from the JSON; input data cannot choose that context. The observer
   reads only its owned `0600` regular, single-link, no-follow input, at most 1 MiB.
   It opens no paths from the observation and returns no private identity/paths.
9. Recheck the original and pending records and installed capabilities. Only
   accepted owner source plus fresh actual native/provider/runtime/function and
   preservation evidence can support the one bounded destination record.

The actual assessment command is:

```text
python3 -I -B personal_native_skill_creator.py OBSERVATION.json \
  --expected-personal-email EXPECTED_PERSONAL_EMAIL \
  --expected-workspace ACTUAL_PERSONAL_WORKSPACE \
  --expected-account-home ACCOUNT_DATABASE_HOME
```

`personal_native_skill_creator.py` validates collected observations; it cannot
establish that JSON is authentic evidence, supply source acceptance, consent to
an operation, install anything or publish a skill. Preserve actual traces and
perform the independent checks above. Any later authoring or publication follows
the user's real requested scope and the provider's current instructions; this
qualification adds no shared links, automatic invocation policy or global
configuration. It creates no model workers, services or additional-root access
and connects to no work/Affirm systems or protected component.

## Offline verification

Run `python3 -B _ops/portability/test_personal_native_skill_creator.py -v` on both
qualified Python versions. The required Dev verifier invokes it directly in
both full and runnerless sandbox modes, refusing a missing file rather than an
empty passing test discovery. Coverage includes personal context, exact native
requests, provider/runtime drift, the complete terminal case roster, deadlines,
resource output, validator limitations, effect/approval injection, private-file
permissions and bounded reading. These tests do not contact an account or execute
the native provider. Actual destination evidence remains independent.
