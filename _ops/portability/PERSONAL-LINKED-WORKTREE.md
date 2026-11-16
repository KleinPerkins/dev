# Personal linked checkout status

The primary-only status implementation does not represent a linked checkout's
own HEAD, index, sparse settings or per-worktree references. This component adds
an explicit read-binding route and a separate linked backend. It does not install
or publish skills, supply human consent, or complete doctor/native qualification.

`preview` starts with one of the twelve manifest-selected personal primary
repositories and an exact current registry proposal digest. It reads only the
accepted primary/common registry metadata and returns a closed binding document
and the SHA-256 of its canonical serialized bytes. It opens no proposed target.
An owner caller must review that exact repository, path, proposal and operation,
and enforce any required human gate before invoking `inspect`. A digest supplied
by an agent is input integrity evidence; it is not proof of a human decision.

`inspect --binding-sha256 DIGEST` consumes only that exact binding document on
stdin. Unknown IDs, extra fields, duplicate keys, old manifest/source bindings,
changed proposals and missing preimages refuse. No arbitrary root parameter or
writer route exists. The accepted registry is reread before target access and its
proposal must match completely. Nested primary roots, excluded names, aliases,
wrong/missing/shared/special gitfiles and mismatched backpointers remain held.
Only after this sequence does the backend read the additionally bound checkout.

The disposable Git view has a common directory and a correctly nested
`common/worktrees/<original-id>` admin directory. Common HEAD, ordinary refs,
packed refs, shallow metadata, exclude/attribute rules and objects come from the
bound common repository. Own HEAD, index, shared indexes, sparse-checkout and
per-worktree refs come from the bound registry entry. The private `commondir` is
synthesized; the real gitdir backpointer is never copied or rewritten. This
preserves main-worktree and own-worktree ref aliases. Other unbound worktree
tracking references remain held.

Common personal origin/config validation precedes overlay and object/index
access. Only the own enabled `config.worktree` overlay is combined. Main-only
`core.bare`/`core.worktree` settings are ignored for the linked checkout when
worktree config is disabled; an enabled effective worktree path must identify
the exact bound target, with relative paths interpreted from its real admin
directory. Includes, filters, unknown extensions, remote rewrites, work remotes,
external alternates, helpers and global/system configuration remain excluded.
Canonical local and effective personal identity are reported separately.

The shared primary inspector also receives a preservation correction. Qualified
Git can write tree objects or refresh existing loose-object timestamps while
expanding a staged sparse index, despite disabled optional locks. Both an object
directory symlink and a read alternate reproduce source changes in disposable
fixtures. Therefore both backends copy the already audited personal object store
into the private view. They use no object links or alternates. The whole snapshot
has a 256 MiB byte budget, individual files a 128 MiB limit, enumeration a 50,000
entry bound and copying a four-second deadline. Exceeding these limits remains
unavailable, with no fallback to a writable source store. Copying performs no
network request or transfer from an unselected repository. Index timestamps are
preserved only on disposable copies to retain Git's racy-clean checks.

Status uses the existing scoped body fence, repository-local ignore policy and
closed qualified Git commands. Dirty/untracked, detached/no-upstream and locally
tracked divergence stay visible; no fetch or remote freshness is asserted.
Generated-memory bodies and nested repositories remain unread. Known excluded
index names refuse before status. Every outcome rechecks target/common/admin
identities, pointer bytes, metadata facts, registry membership and the body fence.
Later edits are held without cleanup or source timestamp restoration. This is
bounded evidence, not protection from a hostile same-user writer.

Synthetic tests cover plain/split/sparse distinct HEAD/index/ref layouts,
absolute/relative linking, own overlays, local divergence, ignore rules, malformed
bindings, aliases/backpointers, missing/locked metadata, late changes, generated
memory refusal and strict bounds. Qualified-Mac red controls reproduce both
unsafe object strategies; green tests preserve source object bytes, inode and
timestamps for both primary and linked sparse layouts. Relative-link fixtures
and qualified-Mac red controls explicitly skip on incompatible test Git; such
fixtures do not establish native equivalence there.

Complete linked hook/memory verdicts, baseline/profile/documentation integration,
the bounded doctor caller, additional-root owner acceptance and native
qualification remain required. No real operator linked checkout is admitted by
these synthetic tests or by source acceptance alone. Existing exports and
observations remain preserved; use the corrected accepted runtime for future
status inspection once its source and exact binding gates are satisfied.
