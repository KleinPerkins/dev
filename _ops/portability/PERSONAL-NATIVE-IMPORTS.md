# Personal fresh-account native goal and shell alternatives

The transfer manifest permits a qualified canonical source or a fresh-account
host distribution for its installed non-work imports. The selected alternative
for `imported/goal` and `imported/shell` on the two measured personal Codex builds is OpenAI's
current native host distribution. This is an explicit owner adoption of the
contracts below, not an inference from matching names. It does not assert the
behavior or UI parity of an unknown legacy implementation. Other imported
utilities and all other migration obligations remain required independently.

## Selected contracts and evidence

| Required import | Native owner interface | Bounded destination evidence |
| --- | --- | --- |
| `imported/goal` | Offered `create_goal`, `get_goal`, `update_goal`; an explicitly requested thread-scoped objective, user-controlled lifecycle/budget, evidence-based completion and native continuation | Two actual reads of the existing user-requested active goal preserve its thread, objective, creation time and remaining budget while usage/update accounting is monotone. The actual migration continues through the native Goal mechanism. No goal is created, paused, cleared, completed, budget-edited or otherwise mutated merely to qualify this route. |
| `imported/shell` | Offered `exec_command` and `write_stdin` under current sandbox/approval policy, with explicit cwd, exit reporting and native interactive sessions | Actual private-cwd file/environment/preservation check; deliberate exit 17 with both output markers; a native PTY stdin roundtrip ending at exit 0; native SIGINT ending at exit 130. Both PTY children enforce a 15-second hard cap. |

These are native APIs, not new home skill links, inherited aliases, a legacy
profile import, or a new MCP service. The shell alternative is the model's
permission-governed execution interface. It does not use the separate
`thread/shellCommand` RPC, which has different user-initiation and sandbox
semantics. User-facing slash menus, shell aliases/completion/profile behavior,
and lifecycle UI actions are not asserted as tested by the API observations.
Future work requiring those surfaces must use their supported interfaces and
their actual authorization; this record grants no policy bypass.

The current native tool declarations are hash-bound in `personal_native_imports.py`.
Goal creation still requires an explicit user request. Only real completion can
justify marking a goal complete; current pause, blocked-audit, budget and model
rules remain authoritative. An active migration must never be paused, cleared,
completed or replaced to manufacture a qualification result.

The canonical sources are OpenAI's current
[Goal guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex),
[developer commands](https://learn.chatgpt.com/docs/developer-commands), and the
[native execution/session description](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide).
The last page is historical documentation of the execution/session shape, not
authority to select its historical model. Actual offered tool declarations and
the recorded build take precedence for the current calling ABI. No model is
selected or overridden by this workflow.

## Owner and destination sequence

1. Accept the exact reviewed source through the normal current-base owner route
   and required checks. Preserve the original transfer manifest, engine, journals,
   checkouts and all unrelated source. Source acceptance selects this bounded
   fresh-account alternative; it does not install or activate anything.
2. Verify the accepted observer and fixture bytes into a separate private export.
   Verify the selected build, its app and CLI hashes, and all five actual native tool declarations.
   A changed/absent offer, provider or host requires requalification, not a silent
   substitute. No extra roots, chats, model workers or shared capability links.
3. Establish the expected personal ChatGPT account through a bounded native
   account/catalog read without requesting a token refresh. Refuse an unexpected
   identity, work workspace, incomplete result, or extra-root/configuration action.
   If the actual command sandbox prevents the verified diagnostic from starting,
   request only the necessary OS execution permission for that read-only diagnostic;
   preserve failed attempts and verify pre/post configuration facts. Never use this
   route to bypass an authentication, app-control or native owner decision.
4. Bind two native reads of the existing explicitly requested goal to this chat and
   its actual user-authorized objective. Preserve the goal lifecycle/budget. Verify
   native continuation from the actual current goal context, separately from merely
   seeing a tool name. Do not create another thread or goal for the test.
5. Create a new private owned disposable cwd and a `0600` synthetic input containing
   exactly `personal-shell-preservation-fixture` plus a newline. Use the accepted
   `native_import_fixture.py` through the actual native command/session tools with
   `login:false`. For `files`, set only the child variable
   `MIGRATION_EXEC_FIXTURE=fixture-v1`; do not repurpose HOME or CODEX_HOME.
6. Run `files`, `nonzero`, `interactive`, and `cancel`. Supply `seed-7` plus newline
   to the observed interactive session immediately; send SIGINT to the observed
   cancellation session immediately. Record actual native session handles and
   terminal outcomes. Each child has a 15-second deadline, and neither may remain
   running. Preserve the old operation rather than overwriting it for a retry.
7. Assess the private `personal-portability/native-goal-shell-observation/v1`
   record with `personal_native_imports.py`. It must contain the real results,
   exact tool/fixture hashes, expected personal identity, current workspace, goal
   bindings and zero-effect observations. Keep raw identity, objective, chat IDs,
   paths and traces private. The CLI requires an owned `0600` regular, unshared,
   non-symlink input no larger than 1 MiB; output excludes the private values.
8. Recheck original records, installed capabilities and any pending exact-preview
   preimages after native execution. Record source acceptance, native availability,
   account identity and the actual bounded functional result separately before a
   destination record for these two imports. Failed or incomplete observations
   remain required. No other utility or full migration completion is established.

`personal_native_imports.py` is a read-only observer. JSON cannot supply approval,
source acceptance, installation or lifecycle authority, and its result explicitly
reports those limits. It never calls a native API, reads a credential store,
installs a provider, writes configuration, starts a service or changes a goal.

## Recorded candidate and checks

The build-23880 candidate used a verified personal account, unchanged native
offers and the existing explicitly requested goal. All four shell groups passed;
the PTY roundtrip and cancellation took approximately 1.13 seconds each. All
children and the diagnostic process were terminal. Initial sandboxed proxy and
stdio diagnostics refused startup; the reviewed read-only diagnostic subsequently
passed under the necessary execution permission, with no requested token refresh.
All 18 pending preimages, original pins/indexes/protected records and retained
capabilities still matched afterward. The private observation is bound by SHA-256
`1898beb97989c2965829ac58890cc3132cce7ae29aa7271c31b4a2a795295440`.

The second measured host uses desktop build 29803 and a revised native shell tool
declaration. Its four shell cases exercised file preservation, exit 17, PTY
input and SIGINT. The latter two sessions ended at exit 0 and 130. Two reads
of the operator-requested migration goal preserved its identity and budget.
The read-only app-server catalog used the enrolled personal account and one
disposable workspace. Each host requires its own exact app, CLI and offered
tool bindings. On either host, a different declared shell contract requires
new qualification. Use the accepted observer against fresh private evidence
before recording either alternative at the destination.

Run the offline contract/refusal suite on both qualified Python versions:

```bash
python3 -B _ops/portability/test_personal_native_imports.py -v
```

The required Dev verifier runs it in both full and runnerless sandbox modes.
Tests include changed scope/identity/tool bytes, goal replacement/status/budget,
output/exit/session/deadline failures, private-file refusal and data-supplied
approval/effect attempts. They use synthetic local JSON and never mutate a goal
or contact an account. Neither passing tests nor the candidate's private hash
replaces actual owner source acceptance and fresh destination revalidation.
