"""Numbered ADR authoring through the existing preview/consent transaction route."""
from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from .artifact_authority import APPROVED_PARENTS_SCHEMA, approved_parent_relations
from .artifact_discovery import ADR_NAME, adr_directory, artifact_paths
from .artifacts import ArtifactPreview, _bindings
from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .transactions import MutationAction, MutationRequest, ObservedInput, directory_input_digest, preview_transaction
from .validators import parse_validated_artifact, read_repository_config, require_valid


def frozen_semantic_postimages(receipt: dict[str, Any]) -> dict[str, str]:
    """Index projections co-written at acceptance do not become authorities."""
    if receipt.get("transition") != "accepted_freeze":
        return {}
    adr_parents = {Path(path).parent for path in receipt["postimages"]
                   if ADR_NAME.fullmatch(Path(path).name)}
    return {path: digest for path, digest in receipt["postimages"].items()
            if not (Path(path).name == "README.md" and Path(path).parent in adr_parents)}


def _validate_freeze_receipt(repo: Path, path: Path, receipt: dict[str, Any]) -> None:
    event_path = contained_path(repo, f"_ops/doc-warden/state/v2/events/{receipt['event_id']}.json")
    event = parse_json_object(event_path.read_bytes())
    require_valid("operation-event", event)
    # Original consent was root-bound at apply; the portable receipt omits
    # that original root, so its digest cannot be recomputed after relocation.
    paths = [action["path"] for action in receipt["actions"]]
    if (path.read_bytes() != canonical_json(receipt)
            or event_path.read_bytes() != canonical_json(event)
            or path.name != f"{receipt['operation_id']}.json"
            or receipt["repository_key"] != read_repository_config(repo)["repository_key"]
            or receipt["outcome"] != "applied"
            or len(paths) != len(set(paths))
            or set(receipt["preimages"]) != set(receipt["postimages"])
            or {action["path"]: action["content_digest"] for action in receipt["actions"]} != receipt["postimages"]
            or receipt["confirmation_digest"] is None
            or any(event[key] != receipt[key] for key in (
                "operation_id", "event_id", "transition", "action_digest", "source_revision", "prior_event_digest", "outcome"))
            or event["details"] != {"postimages": receipt["postimages"]}
            or receipt["result_tree_digest"] != digest_ref(canonical_json({"event": event, "postimages": receipt["postimages"]}))):
        raise ValueError("adr_freeze_receipt_invalid")


def _frozen(repo: Path, relative: str, evidence: list[Path] | None = None) -> bool:
    root = repo / "_ops/doc-warden/state/v2/receipts"
    contained_path(repo, "_ops/doc-warden/state/v2/receipts/.probe")
    for path in sorted(root.glob("*.json")):
        contained_path(repo, path.relative_to(repo).as_posix())
        receipt = parse_json_object(path.read_bytes())
        require_valid("receipt", receipt)
        frozen = frozen_semantic_postimages(receipt)
        if relative in frozen:
            _validate_freeze_receipt(repo, path, receipt)
            if evidence is not None:
                evidence.extend((path, repo / f"_ops/doc-warden/state/v2/events/{receipt['event_id']}.json"))
            destination = contained_path(repo, relative)
            if not destination.is_file() or digest_ref(destination.read_bytes()) != frozen[relative]:
                raise ValueError("adr_frozen_bytes_changed")
            return True
    return False


def _records(repo: Path):
    rows = []
    identifiers = set()
    numbers = set()
    owner = adr_directory(repo)
    root = repo / owner
    if root.exists():
        for path in root.iterdir():
            if path.name == "README.md":
                continue
            match = re.match(r"([0-9]{4})-.*\.md$", path.name)
            if match:
                contained_path(repo, path.relative_to(repo).as_posix())
                number = int(match[1])
                if number in numbers:
                    raise ValueError("adr_number_duplicate")
                numbers.add(number)
    for path in artifact_paths(repo):
        metadata = parse_validated_artifact(path, repo=repo)
        if metadata["repository_key"] != read_repository_config(repo)["repository_key"]:
            raise ValueError("repository_key_mismatch")
        if metadata["id"] in identifiers:
            raise ValueError("artifact_identity_duplicate")
        identifiers.add(metadata["id"])
        if metadata["type"] == "adr":
            if path.parent != root or ADR_NAME.fullmatch(path.name) is None:
                raise ValueError("adr_owner_path_invalid")
            if not metadata["id"].startswith(f"ADR-{metadata['repository_key']}-"):
                raise ValueError("adr_identity_invalid")
            rows.append((path, metadata))
    return rows, numbers


def validate_adr_record(repo: Path, path: Path) -> bool:
    """Validate v2 bytes; return False only for legacy prose after freeze checks."""
    repo = repo.resolve(strict=True)
    relative = path.absolute().relative_to(repo).as_posix()
    target = contained_path(repo, relative)
    frozen = _frozen(repo, relative)
    raw = target.read_text(encoding="utf-8")
    if not raw.startswith("---") and "doc-warden/artifact/" not in raw:
        return False
    rows, _ = _records(repo)
    metadata = next((meta for candidate, meta in rows if candidate == target), None)
    if metadata is None:
        raise ValueError("adr_not_found")
    if metadata["lifecycle"] == "approved" and not frozen:
        raise ValueError("adr_acceptance_receipt_required")
    return True


def _index_delta(repo: Path, relative: str, filename: str, title: str,
                 status: str, predecessor: str | None = None, *,
                 legacy_inputs: list[ObservedInput] | None = None) -> bytes:
    path = contained_path(repo, relative)
    text = path.read_bytes().decode("utf-8") if path.exists() else (
        "# Architecture decision records\n\n| ADR | Status | One-line decision |\n|---|---|---|\n")
    lines = text.splitlines(keepends=True)

    def fields(line):
        # Escaped pipes are cell content; retain the exact raw fragments so
        # validation and replacement agree without re-rendering Markdown.
        result, beginning, backslashes = [], 0, 0
        for offset, char in enumerate(line):
            if char == "|" and backslashes % 2 == 0:
                result.append(line[beginning:offset])
                beginning = offset + 1
            backslashes = backslashes + 1 if char == "\\" else 0
        result.append(line[beginning:])
        return result

    def cells(line):
        parts = fields(line.rstrip("\r\n"))
        if len(parts) < 3 or parts[0].strip() or parts[-1].strip():
            raise ValueError("adr_index_ambiguous")
        return [field.strip() for field in parts[1:-1]]

    # Count ADR headers of either layout, including unsupported/partial headers.
    headers = [i for i, line in enumerate(lines)
               if re.match(r"^[ \t]*\|[ \t]*ADR[ \t]*\|", line)]
    if len(headers) != 1:
        raise ValueError("adr_index_ambiguous")
    start = headers[0]
    layouts = {("ADR", "Status", "One-line decision"): (2, 1),
               ("ADR", "Title", "Status", "Date"): (1, 2)}
    header = tuple(cells(lines[start]))
    if header not in layouts or start + 1 >= len(lines):
        raise ValueError("adr_index_ambiguous")
    title_column, status_column = layouts[header]
    separator = cells(lines[start + 1])
    if len(separator) != len(header) or any(re.fullmatch(r":?-+:?", cell) is None for cell in separator):
        raise ValueError("adr_index_ambiguous")
    end = start + 2
    while end < len(lines) and lines[end].lstrip(" \t").startswith("|"):
        end += 1

    def identity(cell, *, existing=False):
        def valid_name(name):
            if ADR_NAME.fullmatch(name) is not None:
                return True
            # Read compatibility for an existing legacy record only. New and
            # metadata-bearing ADR names retain the closed canonical grammar.
            if not existing or re.fullmatch(r"[0-9]{4}-[a-z0-9]+(?:[.-][a-z0-9]+)*\.md", name) is None:
                return False
            candidate = contained_path(repo, (Path(relative).parent / name).as_posix())
            if not candidate.is_file():
                return False
            raw = candidate.read_bytes()
            if raw.startswith(b"---") or b"doc-warden/artifact/" in raw:
                return False
            if legacy_inputs is not None:
                legacy_inputs.append(ObservedInput(str(candidate), digest_ref(raw)))
            return True

        name = cell
        if not valid_name(name):
            link = re.fullmatch(r"\[([^\[\]]+)\]\(([^()]+)\)", cell)
            if link is None or not valid_name(link[2]):
                raise ValueError("adr_index_ambiguous")
            name = link[2]
            if link[1] not in {name, name[:4]}:
                raise ValueError("adr_index_ambiguous")
        contained_path(repo, (Path(relative).parent / name).as_posix())
        return name

    rows = {}
    numbers = {}
    placeholder_seen = False
    for i in range(start + 2, end):
        row = cells(lines[i])
        if len(row) != len(header):
            raise ValueError("adr_index_ambiguous")
        if row[0] == "<!-- TODO: doc-warden will populate rows here via repair -->":
            if placeholder_seen or any(row[1:]):
                raise ValueError("adr_index_ambiguous")
            placeholder_seen = True
            continue
        name = identity(row[0], existing=True)
        if name in rows or name[:4] in numbers:
            raise ValueError("adr_index_ambiguous")
        rows[name] = i
        numbers[name[:4]] = name
    identity(filename)
    if filename[:4] in numbers and numbers[filename[:4]] != filename:
        raise ValueError("adr_index_ambiguous")
    if predecessor and (predecessor not in rows or predecessor == filename):
        raise ValueError("adr_predecessor_index_missing")

    def replace_cell(i, column, value):
        parts = fields(lines[i])
        cell = parts[column + 1]
        if cell.strip() != value:
            spacing = re.fullmatch(r"([ \t]*)(.*?)([ \t]*)", cell)
            if spacing is None:
                raise ValueError("adr_index_ambiguous")
            trailing = spacing[3]
            if not trailing and (len(value) - len(value.rstrip("\\"))) % 2:
                # A compact cell still needs an unescaped following delimiter.
                trailing = " "
            parts[column + 1] = spacing[1] + value + trailing
            lines[i] = "|".join(parts)

    # Update original row positions before inserting, including a final predecessor.
    if predecessor:
        replace_cell(rows[predecessor], status_column,
                     f"Superseded by [{filename[:4]}]({filename})")
    if filename in rows:
        replace_cell(rows[filename], title_column, title)
        replace_cell(rows[filename], status_column, status)
    else:
        newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
        if not lines[end - 1].endswith("\n"):
            lines[end - 1] += newline
        row = [f"[{filename[:4]}]({filename})"] + [""] * (len(header) - 1)
        row[title_column], row[status_column] = title, status
        lines.insert(end, "| " + " | ".join(row) + " |" + newline)
    return "".join(lines).encode("utf-8")


def _exact_body(path: Path) -> str:
    """Decode without universal-newline translation after metadata validation."""
    parse_validated_artifact(path)
    raw = path.read_bytes()
    boundary = raw.find(b"\n---\n", 4)
    if not raw.startswith(b"---\n") or boundary < 0:
        raise ValueError("adr_metadata_invalid")
    return raw[boundary + 5:].decode("utf-8")


def _approval_evidence(approval: object, reviewed: bytes) -> dict[str, Any]:
    if (not isinstance(approval, dict) or not isinstance(approval.get("actor"), str)
            or not approval["actor"].strip() or not isinstance(approval.get("date"), str)
            or approval.get("review_sha256") != digest_ref(reviewed)[7:]):
        raise ValueError("adr_approval_evidence_required")
    try:
        date.fromisoformat(approval["date"])
    except ValueError as exc:
        raise ValueError("adr_approval_evidence_required") from exc
    return approval


def _bind_numbered_adr_parents(repo: Path, inputs: dict[str, Any], metadata: dict[str, Any]) -> tuple[ObservedInput, ...]:
    existing = [record for record in metadata["provenance"] if record.get("schema") == APPROVED_PARENTS_SCHEMA]
    if len(existing) > 1:
        raise ValueError("approved_parents_invalid")
    if "parents" not in inputs and not existing:
        return ()
    if "parents" in inputs:
        requested = inputs["parents"]
        if not existing and metadata["relations"]:
            raise ValueError("approved_parent_relations_conflict")
    else:
        requested = {key: value for key, value in existing[0].items() if key != "schema"}
    relations, observed = approved_parent_relations(repo, metadata, requested)
    if "parents" not in inputs and metadata["relations"] != relations:
        raise ValueError("approved_parent_relations_conflict")
    if "parents" in inputs:
        metadata["relations"] = relations
        metadata["provenance"] = [record for record in metadata["provenance"] if record not in existing]
        metadata["provenance"].append({"schema": APPROVED_PARENTS_SCHEMA, **requested})
    return observed


def _preview(mode: str, inputs: dict[str, Any], *, repo: Path,
             operation_id: str | None = None, binding_root: Path | None = None,
             artifact_id: str | None = None) -> ArtifactPreview:
    repo = repo.resolve(strict=True)
    profile = read_repository_config(repo)
    if profile is None or not profile["enabled"]:
        raise ValueError("v2_repository_profile_required")
    owner = adr_directory(repo)
    rows, numbers = _records(repo)
    operation = operation_id or str(uuid.uuid4())
    uuid.UUID(operation)
    current = next(((path, meta) for path, meta in rows if meta["id"] == artifact_id), None)
    if mode != "draft" and current is None:
        raise ValueError("adr_not_found")
    title = inputs.get("title")
    if mode in {"draft", "successor", "update"}:
        if not isinstance(title, str) or not title.strip() or any(c in title for c in "|\n\r[]"):
            raise ValueError("adr_title_invalid")
        title = title.strip()
    predecessor = None
    freeze_evidence = []
    if mode in {"draft", "successor"}:
        number = max(numbers, default=0) + 1
        if number > 9999:
            raise ValueError("adr_number_exhausted")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not slug:
            raise ValueError("adr_title_invalid")
        relative = f"{owner}/{number:04d}-{slug}.md"
        metadata = {"schema": "doc-warden/artifact/v2",
                    "id": f"ADR-{profile['repository_key']}-{uuid.uuid5(uuid.UUID(operation), 'adr')}",
                    "type": "adr", "version": 1, "repository_key": profile["repository_key"],
                    "github_repository_id": profile["github_repository_id"], "authority": "semantic",
                    "mutability": "frozen_after_approval", "lifecycle": "draft", "supersedes": None,
                    "relations": [], "provenance": [], "approval": None}
        if any(meta["id"] == metadata["id"] for _, meta in rows):
            raise ValueError("artifact_identity_duplicate")
        if mode == "successor":
            path, previous = current
            if previous["lifecycle"] != "approved" or not _frozen(repo, path.relative_to(repo).as_posix(), freeze_evidence):
                raise ValueError("adr_accepted_predecessor_required")
            if any(meta["supersedes"] == artifact_id for _, meta in rows):
                raise ValueError("adr_successor_exists")
            metadata["supersedes"] = artifact_id
        body = inputs.get("body", f"# ADR {number:04d}: {title}\n\n## Decision\n\n## Why\n\n## Consequences")
        transition = "creation_snapshot"
        kind = "create"
    else:
        path, metadata = current
        metadata = dict(metadata)
        relative = path.relative_to(repo).as_posix()
        if _frozen(repo, relative) or metadata["lifecycle"] not in {"draft", "in_review"}:
            raise ValueError("adr_frozen_successor_required")
        body = inputs.get("body", _exact_body(path))
        kind = "replace"
        transition = "draft_update"
        if mode == "accept":
            approval = _approval_evidence(inputs.get("approval"), path.read_bytes())
            metadata.update(lifecycle="approved", approval=approval)
            transition = "accepted_freeze"
            # Acceptance cannot sneak in an unreviewed body edit.
            body = _exact_body(path)
            title_match = re.search(r"^# (?:ADR [0-9]{4}: )?(.+)$", body, re.M)
            if title_match is None:
                raise ValueError("adr_title_invalid")
            title = title_match[1].removesuffix("\r")
            if not title.strip() or any(c in title for c in "|\n\r[]"):
                raise ValueError("adr_title_invalid")
            if metadata["supersedes"]:
                previous = next(((p, m) for p, m in rows if m["id"] == metadata["supersedes"]), None)
                if (previous is None or previous[1]["lifecycle"] != "approved"
                        or not _frozen(repo, previous[0].relative_to(repo).as_posix(), freeze_evidence)):
                    raise ValueError("adr_accepted_predecessor_required")
                predecessor = previous[0].name
    if not isinstance(body, str) or not body.strip():
        raise ValueError("adr_body_required")
    if mode == "draft" and "approval" in inputs:
        approval = _approval_evidence(inputs["approval"], body.encode("utf-8"))
        metadata.update(lifecycle="approved", approval=approval)
        transition = "accepted_freeze"
    parent_inputs = _bind_numbered_adr_parents(repo, inputs, metadata)
    require_valid("artifact", metadata)
    index = f"{owner}/README.md"
    legacy_inputs: list[ObservedInput] = []
    actions = (MutationAction(relative, b"---\n" + canonical_json(metadata) + b"---\n" + body.encode("utf-8"), kind),
               MutationAction(index, _index_delta(repo, index, Path(relative).name, title,
                   "Accepted" if metadata["lifecycle"] == "approved" else "Draft", predecessor,
                   legacy_inputs=legacy_inputs)))
    authority = binding_root.resolve(strict=True) if binding_root else repo
    observed = {item.path: item for item in legacy_inputs}
    def observe(path):
        if path.is_symlink():
            raise ValueError("observed_input_invalid")
        path = path.resolve(strict=True)
        observed[str(path)] = ObservedInput(str(path), directory_input_digest(path)
                                           if path.is_dir() else digest_ref(path.read_bytes()))
    # Root listing binds absent override; nearest existing owner ancestor binds
    # absent owner/index. Action preimages bind co-written ADR and index bytes.
    observe(repo)
    parent = repo / owner
    while not parent.exists():
        parent = parent.parent
    observe(parent)
    for name in (".planning/doc-warden.json", ".doc-warden.yml"):
        path = contained_path(repo, name)
        if path.exists():
            observe(path)
    for relative_authority in ("_ops/doc-warden", "_ops/doc-warden/schemas/v2",
                               "_ops/doc-warden/runtime/gsd-core", "_ops/plans"):
        parent = authority / relative_authority
        while not parent.exists():
            parent = parent.parent
        observe(parent)
    plan = authority / "_ops/plans/doc-warden-execution-plan-v2.md"
    if plan.is_file():
        observe(plan)
    for path in (authority / "_ops/doc-warden").rglob("*"):
        if (path.is_file() and (path.name in {"POLICY.md", "triggers.v2.json", "gsd-core-pin.json"}
                              or path.name.endswith(".schema.json"))):
            observe(path)
    for path in freeze_evidence:
        observe(path)
    for path, meta in rows:
        if path.relative_to(repo).as_posix() != relative:
            observe(path)
    for item in parent_inputs:
        # The transaction already binds both preimage and postimage of its own
        # ADR/index. Recording those as parent inputs would reject exact replay.
        if item.path in {str(repo / relative), str(repo / index)}:
            continue
        if observed.setdefault(item.path, item) != item:
            raise ValueError("observed_input_drift")
    transaction = preview_transaction(MutationRequest(repo=repo, repository_key=profile["repository_key"],
        github_repository_id=profile["github_repository_id"], transition=transition,
        actions=actions, bindings=_bindings(authority), operation_id=operation,
        observed_inputs=tuple(observed.values()), require_write_enabled=True))
    return ArtifactPreview(transaction, metadata["id"], relative, profile["repository_key"])


def preview_adr_draft(inputs, **kwargs):
    return _preview("draft", inputs, **kwargs)


def preview_adr_update(artifact_id, inputs, **kwargs):
    return _preview("update", inputs, artifact_id=artifact_id, **kwargs)


def preview_adr_accept(artifact_id, approval, **kwargs):
    return _preview("accept", {"approval": approval}, artifact_id=artifact_id, **kwargs)


def preview_adr_successor(artifact_id, inputs, **kwargs):
    return _preview("successor", inputs, artifact_id=artifact_id, **kwargs)
