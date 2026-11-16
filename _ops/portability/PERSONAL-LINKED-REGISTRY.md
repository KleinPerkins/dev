# Personal linked-worktree registry discovery

`personal_linked_registry.py` is the discovery dependency for complete bounded
linked-worktree observations. It reads only metadata inside the twelve exact
approved personal primaries. It never opens a proposed target directory, its
`.git` file or checkout contents. A candidate is not an accepted additional-root
binding, an inspected worktree, clean status or native qualification.

Git separates common repository storage from each linked worktree's metadata.
HEAD, index and optional worktree configuration must not be taken from the
primary checkout. Git also gives some refs separate per-worktree behavior.
The installed Git 2.54 layout is the relevant target contract; newer Git manuals
cannot silently expand the qualified format. See the official
[Git 2.54 worktree reference](https://git-scm.com/docs/git-worktree/2.54.0) and
[repository layout reference](https://git-scm.com/docs/gitrepository-layout).

The discovery boundary is deliberately separate from the backend. Ordinary Git
access can update the administrative `gitdir` file's timestamp, as described in
the layout reference. This program invokes only the qualified, isolated
`--no-includes` config parser on stdin. It never runs Git against an actual
primary or linked root. The future linked backend must use private metadata and
index snapshots, preserving correct common and per-worktree ownership.

## Read-only interface

```text
python3 -I -B personal_linked_registry.py inspect
python3 -I -B personal_linked_registry.py inspect --repository KleinPerkins/skills
```

The exact accepted `personal_profile.py` dependency and its dependency chain are
hash bound to Dev `25ac6d21cf85736f6f4315a0fc9d36dc28de5048`. No arbitrary root,
binding, status, repair, prune, cleanup, apply or registration verb exists. After
normal owner source acceptance, export this module alongside the fourteen-file
accepted personal-profile runtime. Existing source pins and exports stay intact.

Common origin/config validation precedes registry or object/ref inventory.
Includes, content filters, remote rewrites, external alternates, unclassified
remotes and unknown formats remain held. The known Git 2.54 relative-linking
extension is validated as metadata syntax; it grants no target access. A primary
masquerading as linked metadata is refused.

Only the selected common directory's bounded `worktrees` children are considered.
There are at most 128 entries, with a twelve-second enumeration budget. All
metadata directories use owned no-follow descriptors; pointers are bounded
owned unshared regular files, at most 4 KiB. Indexes and HEAD are statted as
metadata only. Index/HEAD bodies and lock-reason bodies are never read. Excluded
entry names are held before opening the entry. Absolute or relative pointers are
normalized lexically, never resolved through the target filesystem.

Each proposal binds the selected repository, primary/common/registry/entry
descriptor identities, common config and storage evidence, exact pointer bytes,
proposed target and metadata facts. Wrong common pointers, work/protected,
external, primary or umbrella targets, aliases, shared/special metadata and
unavailable bytes remain visible as held. Registry membership and all observed
entry/file preimages are rechecked after discovery, including after storage
verification. Visible changes make discovery unavailable; this is not a hostile
same-user writer sandbox.

## Results and remaining owner work

`available` describes discovery evidence only. Entries are
`proposed-uninspected` or `held-uninspected`; neither is clean or inspected. Even
an empty registry does not turn this component into a complete doctor. An
available diagnostic exits 0, unavailable scope/metadata exits 2.

The next owner route must review and bind the exact additional path, then verify
the target `.git` backpointer and common identity before checkout reads. Correct
per-worktree HEAD/index/config/ref snapshots, worktree status, identity, hooks,
memory, baseline/profile/documentation and full caller/native qualification
remain required. Missing or held paths cannot disappear from the report or be
counted clean. Discovery creates no such authority and starts no model worker,
service, shared link, account operation or network request.
