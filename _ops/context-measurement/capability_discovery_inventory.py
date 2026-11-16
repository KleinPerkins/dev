#!/usr/bin/env python3
"""Produce and validate D-01 capability-discovery inventory evidence."""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import kp_context_measure as kpcm


SCHEMA = "capability-discovery-inventory/v1"
STATUS = "PASS"
REPOSITORY = "KleinPerkins/dev"
ENVIRONMENT_CLASS = "macos-local-client-installed-catalog"
METHOD = "capability-discovery-inventory-method/v1"
CURSOR_CATALOG_SCHEMA = "cursor-session-catalog/v1"
CURSOR_SOURCE_SCHEMA = "cursor-session-context-source/v1"
CLIENT_SCOPE = ["cursor"]

ROW_KEYS = {
    "capability_id",
    "client",
    "root_scope",
    "owner_source_repo",
    "exposure_class",
    "installed_path",
    "installed_sha256",
    "installed_kind",
    "description_chars",
    "description_words",
    "eligibility",
}
ROOT_KEYS = {
    "root_id",
    "client",
    "root_scope",
    "root_path",
    "required",
    "exists",
    "discovery_source_class",
    "discovery_source_sha256",
    "installed_count",
    "exposed_count",
    "installed_only_count",
    "classification_rule",
}
CATALOG_KEYS = {
    "client",
    "complete",
    "source_sections",
    "canonical_entries",
    "emitted_rows",
    "dropped_entries",
    "canonical_catalog_sha256_by_root",
}
SOURCE_SECTION_KEYS = {
    "section",
    "source_sha256",
    "source_entry_count",
    "canonical_entry_count",
}
TOP_KEYS = {
    "schema",
    "status",
    "captured_at_utc",
    "repository",
    "dev_commit",
    "dev_tree",
    "client_scope",
    "environment_class",
    "method",
    "catalog_completeness",
    "roots",
    "rows",
    "totals",
}
ENTRY_KEYS = {
    "client",
    "catalog_kind",
    "capability_id",
    "root_scope",
    "declared_name",
    "installed_path",
    "exposure_class",
    "description_sha256",
    "description_chars",
    "description_words",
}

OWNER_REPOS = {
    "KleinPerkins/skills",
    "Affirm/card-platform-product",
    "KleinPerkins/awa",
    "KleinPerkins/dev",
    "cursor-client",
    "anthropic-plugin",
    "openai-codex",
    "third-party-plugin",
    "foreign-preserved-install",
}
EXPOSURES = {
    "cursor-rule-always-applied",
    "cursor-rule-requestable",
    "cursor-home-full-context",
    "cursor-workspace-full-context",
    "cursor-skill-description",
    "cursor-plugin-skill-description",
    "cursor-global-runtime-config",
    "cursor-workspace-runtime-config",
    "claude-skill-description",
    "claude-plugin-skill-description",
    "codex-skill-description",
    "codex-system-skill-description",
    "installed-not-client-exposed",
    "client-injected-no-installed-file",
}
ELIGIBILITIES = {
    "eligible-skills-d02",
    "eligible-cpp-d03",
    "eligible-dev-host-only",
    "eligible-awa-host-only",
    "ineligible-client-owned",
    "ineligible-full-context-rule",
    "ineligible-runtime-config",
    "ineligible-no-description",
    "ineligible-not-client-exposed",
    "ineligible-injection-only",
}
ZERO_COUNT_EXPOSURES = {
    "installed-not-client-exposed",
    "cursor-rule-always-applied",
    "cursor-home-full-context",
    "cursor-workspace-full-context",
    "cursor-global-runtime-config",
    "cursor-workspace-runtime-config",
    "client-injected-no-installed-file",
}
DESCRIPTION_EXPOSURES = {
    "cursor-skill-description",
    "cursor-plugin-skill-description",
    "cursor-rule-requestable",
}
DESCRIPTION_ELIGIBLE_EXPOSURES = {
    "cursor-skill-description",
    "cursor-plugin-skill-description",
    "claude-skill-description",
    "claude-plugin-skill-description",
    "codex-skill-description",
    "codex-system-skill-description",
    "cursor-rule-requestable",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
NAME_PATTERN = re.compile(r"<(?P<tag>always_applied_workspace_rule|agent_requestable_workspace_rule|agent_skill)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>", re.S)
EMPTY_PATTERN = re.compile(r"<(?P<tag>always_applied_workspace_rule|agent_requestable_workspace_rule|agent_skill)\b(?P<attrs>[^>]*)\s*/>", re.S)
ATTR_PATTERN = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)="([^"]*)"')


class InventoryError(Exception):
    """Closed, path-safe inventory failure."""


def _fail(message: str) -> None:
    raise InventoryError(message)


def _ascii_sort_key(value: str) -> bytes:
    try:
        return value.encode("ascii")
    except UnicodeEncodeError:
        _fail(f"non-ASCII identifier unsupported: {value!r}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        _fail(f"invalid JSON: {path}: {error}")


def _emit(value: Any) -> str:
    if hasattr(kpcm, "emit"):
        return kpcm.emit(value)
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_emit(value).encode("ascii")).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_file_bytes(path: Path) -> bytes:
    try:
        before = os.stat(path, follow_symlinks=True)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"not a regular file: {path}")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                _fail(f"not a regular file: {path}")
            return handle.read()
    except OSError as error:
        _fail(f"unreadable file: {path}: {error}")


def _strict_text(raw: bytes, path: Path) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        _fail(f"invalid UTF-8: {path}: {error}")


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        _fail(f"git unavailable for {repo}: {error}")
    if completed.returncode != 0:
        _fail(f"git failed for {repo}: {' '.join(args)}")
    return completed.stdout.strip()


def _normalize_github_remote(value: str) -> str:
    for suffix in (".git",):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    ssh = re.fullmatch(r"git@github\.com:([^/]+/[^/]+)", value)
    if ssh:
        return ssh.group(1)
    https = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)", value)
    if https:
        return https.group(1)
    return value


def _verify_owner_checkout(root: Path, expected_remote: str, *, require_clean: bool = True) -> None:
    if not root.exists():
        _fail(f"owner root missing: {root}")
    if require_clean and _git(root, "status", "--porcelain=v1"):
        _fail(f"owner root dirty: {root}")
    remote = _normalize_github_remote(_git(root, "remote", "get-url", "origin"))
    if remote != expected_remote:
        _fail(f"owner root remote mismatch: {root}: {remote}")
    default_branch_ref = _git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
    default_branch = default_branch_ref.rsplit("/", 1)[-1]
    head = _git(root, "rev-parse", "HEAD")
    origin = _git(root, "rev-parse", f"origin/{default_branch}")
    base = _git(root, "merge-base", "HEAD", f"origin/{default_branch}")
    if base not in {head, origin}:
        _fail(f"owner root diverged from owner main: {root}")
    if not HEX40.fullmatch(origin):
        _fail(f"owner root origin invalid: {root}")


def _verify_inputs(dev_root: Path, skills_root: Path, cpp_root: Path, awa_root: Path) -> tuple[str, str]:
    _verify_owner_checkout(dev_root, "KleinPerkins/dev", require_clean=False)
    _verify_owner_checkout(skills_root, "KleinPerkins/skills")
    _verify_owner_checkout(cpp_root, "Affirm/card-platform-product")
    _verify_owner_checkout(awa_root, "KleinPerkins/awa")
    return _git(dev_root, "rev-parse", "HEAD"), _git(dev_root, "rev-parse", "HEAD^{tree}")


def _load_e03(skills_root: Path) -> Any:
    script = skills_root / "scripts" / "skill-description-inventory.py"
    if not script.exists():
        _fail("E-03 parser missing")
    spec = importlib.util.spec_from_file_location("skill_description_inventory_e03", script)
    if spec is None or spec.loader is None:
        _fail("E-03 parser load failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "NORMALIZATION_CONTRACT", None) != "skill-description-normalization/v1":
        _fail("E-03 normalization contract mismatch")
    if getattr(module, "PARSER_PROFILE", None) != "skills-yaml12-core-profile/v1":
        _fail("E-03 parser profile mismatch")
    if not hasattr(module, "parse_frontmatter") or not hasattr(module, "normalize_description"):
        _fail("E-03 parser functions missing")
    return module


def _parse_xmlish(source_text: str, expected_tag: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for match in NAME_PATTERN.finditer(source_text):
        if match.group("tag") != expected_tag:
            continue
        attrs = {key: html.unescape(value) for key, value in ATTR_PATTERN.findall(match.group("attrs"))}
        attrs["body"] = html.unescape(match.group("body"))
        entries.append(attrs)
    for match in EMPTY_PATTERN.finditer(source_text):
        if match.group("tag") != expected_tag:
            continue
        attrs = {key: html.unescape(value) for key, value in ATTR_PATTERN.findall(match.group("attrs"))}
        attrs["body"] = ""
        entries.append(attrs)
    entries.sort(key=lambda item: (item.get("name") or item.get("fullPath") or "", item.get("body") or ""))
    return entries


def _section_map(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if set(source) != {"schema", "workspace_root", "captured_at_utc", "sections"}:
        _fail("cursor source top-level keys mismatch")
    if source["schema"] != CURSOR_SOURCE_SCHEMA:
        _fail("cursor source schema mismatch")
    if not UTC_TIMESTAMP.fullmatch(source["captured_at_utc"]):
        _fail("cursor source timestamp invalid")
    sections = source["sections"]
    if type(sections) is not list:
        _fail("cursor source sections invalid")
    result: dict[str, dict[str, Any]] = {}
    for section in sections:
        if type(section) is not dict or set(section) != {"section", "source_text", "source_sha256"}:
            _fail("cursor source section keys mismatch")
        name = section["section"]
        if name in result:
            _fail("duplicate cursor source section")
        text = section["source_text"]
        digest = section["source_sha256"]
        if type(text) is not str or type(digest) is not str:
            _fail("cursor source section types invalid")
        if _sha256_bytes(text.encode("utf-8")) != digest:
            _fail(f"cursor source digest mismatch: {name}")
        result[name] = section
    expected = {
        "always_applied_workspace_rules",
        "agent_requestable_workspace_rules",
        "agent_skills",
    }
    if set(result) != expected:
        _fail("cursor source sections incomplete")
    return result


def _path_name(path: Path) -> str:
    if path.name == "SKILL.md":
        return path.parent.name
    return path.name


def _root_for_rule(path: Path, dev_root: Path) -> tuple[str, Path, str, bool]:
    if path == Path.home() / "AGENTS.md":
        return "cursor-home-agents-context", path, "cursor-home-full-context/v1", True
    if path == dev_root / "AGENTS.md":
        return "dev-workspace-agents-context", path, "cursor-workspace-full-context/v1", True
    if path.is_relative_to(dev_root / ".cursor" / "rules"):
        return "dev-workspace-cursor-rules", dev_root / ".cursor" / "rules", "cursor-rules-session-catalog/v1", False
    if path.is_relative_to(Path.home() / ".cursor" / "rules"):
        return "cursor-global-rules", Path.home() / ".cursor" / "rules", "cursor-rules-session-catalog/v1", True
    _fail(f"unlisted cursor rule/context root: {path}")


def _root_for_skill(path: Path) -> tuple[str, Path, str]:
    home = Path.home()
    if path.is_relative_to(home / ".cursor" / "skills-cursor"):
        return "cursor-built-in-skills", home / ".cursor" / "skills-cursor", "cursor-skills-agent-catalog/v1"
    if path.is_relative_to(home / ".cursor" / "skills"):
        return "cursor-user-skills", home / ".cursor" / "skills", "cursor-skills-agent-catalog/v1"
    plugin_cache = home / ".cursor" / "plugins" / "cache"
    if path.is_relative_to(plugin_cache):
        rel = path.relative_to(plugin_cache)
        parts = rel.parts
        if len(parts) < 5 or parts[3] != "skills":
            _fail(f"unlisted cursor plugin skill root: {path}")
        publisher, plugin, version = parts[0], parts[1], parts[2]
        return (
            f"cursor-plugin/{publisher}/{plugin}/{version}",
            plugin_cache / publisher / plugin / version / "skills",
            "cursor-skills-agent-catalog/v1",
        )
    if path.is_relative_to(home / ".claude" / "skills"):
        return "cursor-shared-claude-skills", home / ".claude" / "skills", "cursor-skills-agent-catalog/v1"
    claude_plugin_cache = home / ".claude" / "plugins" / "cache"
    if path.is_relative_to(claude_plugin_cache):
        rel = path.relative_to(claude_plugin_cache)
        parts = rel.parts
        if len(parts) < 5 or parts[3] != "skills":
            _fail(f"unlisted shared plugin skill root: {path}")
        publisher, plugin, version = parts[0], parts[1], parts[2]
        return (
            f"cursor-shared-plugin/{publisher}/{plugin}/{version}",
            claude_plugin_cache / publisher / plugin / version / "skills",
            "cursor-skills-agent-catalog/v1",
        )
    _fail(f"unlisted cursor skill root: {path}")


def _installed_kind(path: Path) -> str:
    try:
        if path.is_symlink() or path.resolve(strict=True) != path.absolute():
            return "symlink"
        return "regular-file"
    except OSError:
        _fail(f"installed path resolution failed: {path}")


def _owner_for_path(path: Path, dev_root: Path, skills_root: Path, cpp_root: Path, awa_root: Path) -> str:
    try:
        real = path.resolve(strict=True)
    except OSError:
        _fail(f"installed path missing: {path}")
    if real.is_relative_to(skills_root.resolve(strict=True)):
        return "KleinPerkins/skills"
    if real.is_relative_to(cpp_root.resolve(strict=True)):
        return "Affirm/card-platform-product"
    if real.is_relative_to(awa_root.resolve(strict=True)):
        return "KleinPerkins/awa"
    if real.is_relative_to(dev_root.resolve(strict=True)):
        return "KleinPerkins/dev"
    home = Path.home()
    if path == home / "AGENTS.md":
        return "KleinPerkins/skills"
    if path.is_relative_to(home / ".cursor" / "skills-cursor"):
        return "cursor-client"
    if path.is_relative_to(home / ".cursor" / "plugins" / "cache"):
        return "cursor-client"
    if path.is_relative_to(home / ".claude" / "plugins" / "cache"):
        return "anthropic-plugin"
    return "foreign-preserved-install"


def _normalize_rule_description(value: str, source_path: Path) -> str:
    if type(value) is not str:
        _fail(f"rule description must be string: {source_path}")
    return re.sub(r"[\t\n\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+", " ", value).strip(" ")


def _parse_rule_frontmatter(path: Path) -> dict[str, Any]:
    raw = _read_file_bytes(path)
    text = _strict_text(raw, path).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        _fail(f"rule frontmatter missing: {path}")
    try:
        close = lines.index("---", 1)
    except ValueError:
        _fail(f"rule frontmatter closing delimiter missing: {path}")
    result: dict[str, Any] = {}
    for line in lines[1:close]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            _fail(f"malformed rule frontmatter: {path}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in result:
            _fail(f"duplicate rule frontmatter key: {path}")
        if key == "description" and value in {"[]", "{}"}:
            _fail(f"rule description must be string: {path}")
        if value in {"true", "false"}:
            result[key] = value == "true"
        elif value == "":
            result[key] = ""
        else:
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            result[key] = value
    if "description" not in result:
        _fail(f"rule description missing: {path}")
    if type(result["description"]) is not str:
        _fail(f"rule description must be string: {path}")
    return result


def _fallback_skill_description(raw: bytes, path: Path) -> str | None:
    text = _strict_text(raw, path).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        _fail(f"skill frontmatter missing: {path}")
    try:
        close = lines.index("---", 1)
    except ValueError:
        _fail(f"skill frontmatter closing delimiter missing: {path}")
    frontmatter = lines[1:close]
    for index, line in enumerate(frontmatter):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value == "":
            return ""
        if value in {"[]", "{}"}:
            _fail(f"skill description must be string: {path}")
        if value in {">-", ">", "|", "|-"}:
            block: list[str] = []
            for child in frontmatter[index + 1:]:
                if child and not child.startswith(" "):
                    break
                block.append(child.strip())
            return "\n".join(block).strip()
        if value.startswith('"'):
            parts = [value[1:]]
            for child in frontmatter[index + 1:]:
                if parts[-1].endswith('"') and not parts[-1].endswith('\\"'):
                    break
                parts.append(child.strip())
            joined = "\n".join(parts)
            if joined.endswith('"') and not joined.endswith('\\"'):
                return joined[:-1]
            _fail(f"skill description quoted scalar unterminated: {path}")
        if value.startswith("'"):
            if not value.endswith("'") or len(value) == 1:
                _fail(f"skill description quoted scalar unterminated: {path}")
            return value[1:-1]
        return value
    return None


def _skill_counts(path: Path, e03: Any) -> tuple[int, int, str | None]:
    raw = _read_file_bytes(path)
    try:
        frontmatter = e03.parse_frontmatter(raw, str(path))
    except Exception as error:
        failures = getattr(error, "failures", None)
        if failures is None:
            _fail(f"E-03 parser raised unexpected error for {path}: {error}")
        if any(reason == "description is missing" for _path, reason in failures):
            return 0, 0, None
        description = _fallback_skill_description(raw, path)
        if description is None:
            return 0, 0, None
        normalized = e03.normalize_description(description)
        return len(normalized), kpcm.count_words(normalized), _sha256_bytes(normalized.encode("utf-8"))
    description = frontmatter.get("description")
    if type(description) is not str:
        _fail(f"skill description must be string: {path}")
    normalized = e03.normalize_description(description)
    return len(normalized), kpcm.count_words(normalized), _sha256_bytes(normalized.encode("utf-8"))


def _rule_counts(path: Path) -> tuple[int, int, str | None]:
    frontmatter = _parse_rule_frontmatter(path)
    normalized = _normalize_rule_description(frontmatter["description"], path)
    return len(normalized), kpcm.count_words(normalized), _sha256_bytes(normalized.encode("utf-8"))


def _eligibility(owner: str, exposure: str, chars: int) -> str:
    if exposure == "installed-not-client-exposed":
        return "ineligible-not-client-exposed"
    if exposure in {"cursor-global-runtime-config", "cursor-workspace-runtime-config"}:
        return "ineligible-runtime-config"
    if exposure == "client-injected-no-installed-file":
        return "ineligible-injection-only"
    if exposure in {"cursor-rule-always-applied", "cursor-home-full-context", "cursor-workspace-full-context"}:
        return "ineligible-full-context-rule"
    if chars == 0:
        return "ineligible-no-description"
    if owner in {"cursor-client", "anthropic-plugin", "openai-codex", "third-party-plugin", "foreign-preserved-install"}:
        return "ineligible-client-owned"
    if exposure in DESCRIPTION_ELIGIBLE_EXPOSURES:
        if owner == "KleinPerkins/skills":
            return "eligible-skills-d02"
        if owner == "Affirm/card-platform-product":
            return "eligible-cpp-d03"
        if owner == "KleinPerkins/dev":
            return "eligible-dev-host-only"
        if owner == "KleinPerkins/awa":
            return "eligible-awa-host-only"
    _fail(f"eligibility unresolved: {owner} {exposure}")


def _row(
    *,
    client: str,
    root_scope: str,
    declared_name: str,
    installed_path: Path | None,
    owner: str,
    exposure: str,
    installed_kind: str,
    description_chars: int,
    description_words: int,
) -> dict[str, Any]:
    capability_id = f"{client}/{root_scope}/{declared_name}"
    if installed_path is None:
        installed_sha = None
    else:
        installed_sha = _sha256_bytes(_read_file_bytes(installed_path.resolve(strict=True)))
    if exposure in ZERO_COUNT_EXPOSURES:
        description_chars = 0
        description_words = 0
    return {
        "capability_id": capability_id,
        "client": client,
        "root_scope": root_scope,
        "owner_source_repo": owner,
        "exposure_class": exposure,
        "installed_path": str(installed_path) if installed_path is not None else None,
        "installed_sha256": installed_sha,
        "installed_kind": installed_kind,
        "description_chars": description_chars,
        "description_words": description_words,
        "eligibility": _eligibility(owner, exposure, description_chars),
    }


def _catalog_entry(
    *,
    client: str,
    catalog_kind: str,
    root_scope: str,
    declared_name: str,
    installed_path: Path | None,
    exposure_class: str,
    description_sha256: str | None,
    description_chars: int,
    description_words: int,
) -> dict[str, Any]:
    return {
        "client": client,
        "catalog_kind": catalog_kind,
        "capability_id": f"{client}/{root_scope}/{declared_name}",
        "root_scope": root_scope,
        "declared_name": declared_name,
        "installed_path": str(installed_path) if installed_path is not None else None,
        "exposure_class": exposure_class,
        "description_sha256": description_sha256,
        "description_chars": description_chars,
        "description_words": description_words,
    }


def _descriptor_name(path: Path) -> str:
    if path.name == "SKILL.md":
        parent = path.parent
        if parent.parent.name == "sub-skills":
            return f"{parent.parent.parent.name}/{parent.name}"
        return parent.name
    return path.name


def _descriptor_root_specs(dev_root: Path, catalog_entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    home = Path.home()
    specs: dict[str, dict[str, Any]] = {}

    def add(root_scope: str, root_path: Path, required: bool, classification: str) -> None:
        root_id = f"cursor/{root_scope}"
        specs[root_id] = {
            "root_id": root_id,
            "client": "cursor",
            "root_scope": root_scope,
            "root_path": str(root_path),
            "required": required,
            "exists": root_path.exists(),
            "discovery_source_class": "cursor-session-context",
            "classification_rule": classification,
        }

    standard_roots = [
        ("cursor-global-rules", home / ".cursor" / "rules", True, "cursor-rules-session-catalog/v1"),
        ("dev-workspace-cursor-rules", dev_root / ".cursor" / "rules", False, "cursor-rules-session-catalog/v1"),
        ("cursor-user-skills", home / ".cursor" / "skills", True, "cursor-skills-agent-catalog/v1"),
        ("cursor-built-in-skills", home / ".cursor" / "skills-cursor", False, "cursor-skills-agent-catalog/v1"),
        ("cursor-shared-claude-skills", home / ".claude" / "skills", False, "cursor-skills-agent-catalog/v1"),
    ]
    catalog_root_ids = {f"{entry['client']}/{entry['root_scope']}" for entry in catalog_entries}
    for root_scope, root_path, required, classification in standard_roots:
        root_id = f"cursor/{root_scope}"
        if root_path.exists() or root_id in catalog_root_ids:
            add(root_scope, root_path, required, classification)

    plugin_roots: set[Path] = set()
    for cache_root in (home / ".cursor" / "plugins" / "cache", home / ".claude" / "plugins" / "cache"):
        if cache_root.exists():
            for path in sorted(cache_root.glob("*/*/*/skills")):
                if path.is_dir():
                    plugin_roots.add(path)
    for entry in catalog_entries:
        installed = entry["installed_path"]
        if installed is None:
            continue
        path = Path(installed)
        root_scope = entry["root_scope"]
        if root_scope.startswith("cursor-plugin/") or root_scope.startswith("cursor-shared-plugin/"):
            _scope, root_path, _classification = _root_for_skill(path)
            plugin_roots.add(root_path)

    for root_path in sorted(plugin_roots, key=lambda item: str(item).encode("utf-8")):
        try:
            root_scope, expected_root, classification = _root_for_skill(root_path / "_placeholder" / "SKILL.md")
        except InventoryError:
            continue
        if expected_root != root_path:
            _fail(f"plugin root mismatch: {root_path}")
        add(root_scope, root_path, False, classification)

    return dict(sorted(specs.items()))


def _catalog_paths_by_root(catalog_entries: list[dict[str, Any]], root_specs: dict[str, dict[str, Any]]) -> dict[str, set[Path]]:
    result: dict[str, set[Path]] = {root_id: set() for root_id in root_specs}
    for entry in catalog_entries:
        installed = entry["installed_path"]
        if installed is None:
            continue
        root_id = f"{entry['client']}/{entry['root_scope']}"
        if root_id in result:
            result[root_id].add(Path(installed))
    return result


def _scan_descriptor_root(spec: dict[str, Any], catalog_paths: set[Path]) -> list[Path]:
    root_path = Path(spec["root_path"])
    if not root_path.exists():
        if catalog_paths:
            _fail(f"catalog path assigned to absent root: {root_path}")
        return []
    if not root_path.is_dir():
        _fail(f"descriptor root is not a directory: {root_path}")

    scanned: set[Path] = set()
    classification = spec["classification_rule"]
    if classification == "cursor-rules-session-catalog/v1":
        for path in sorted(root_path.glob("*.mdc")):
            if path.is_file():
                scanned.add(path)
        for path in catalog_paths:
            if path.parent != root_path or path.suffix != ".mdc":
                _fail(f"catalog rule path outside scanned root: {path}")
            if not path.exists():
                _fail(f"catalog rule path missing on disk: {path}")
            scanned.add(path)
    else:
        for child in sorted(root_path.iterdir()):
            skill_path = child / "SKILL.md"
            if skill_path.exists():
                scanned.add(skill_path)
            if child.is_dir():
                for sub_skill in sorted(child.glob("sub-skills/*/SKILL.md")):
                    if sub_skill.is_file():
                        scanned.add(sub_skill)
        for path in catalog_paths:
            if path.name != "SKILL.md" or not path.is_relative_to(root_path):
                _fail(f"catalog skill path outside scanned root: {path}")
            if not path.exists():
                _fail(f"catalog skill path missing on disk: {path}")
            scanned.add(path)

    names: dict[str, Path] = {}
    for path in sorted(scanned, key=lambda item: str(item).encode("utf-8")):
        _strict_text(_read_file_bytes(path), path)
        name = _descriptor_name(path)
        if name in names:
            _fail(f"duplicate declared name in root {spec['root_scope']}: {name}: {names[name]} and {path}")
        names[name] = path
    return sorted(scanned, key=lambda item: str(item).encode("utf-8"))


def _append_installed_only_rows(
    rows: list[dict[str, Any]],
    root_specs: dict[str, dict[str, Any]],
    scanned_by_root: dict[str, list[Path]],
    catalog_paths: dict[str, set[Path]],
    dev_root: Path,
    skills_root: Path,
    cpp_root: Path,
    awa_root: Path,
) -> None:
    for root_id, paths in sorted(scanned_by_root.items()):
        spec = root_specs[root_id]
        for path in paths:
            if path in catalog_paths.get(root_id, set()):
                continue
            owner = _owner_for_path(path, dev_root, skills_root, cpp_root, awa_root)
            rows.append(_row(
                client=spec["client"],
                root_scope=spec["root_scope"],
                declared_name=_descriptor_name(path),
                installed_path=path,
                owner=owner,
                exposure="installed-not-client-exposed",
                installed_kind=_installed_kind(path),
                description_chars=0,
                description_words=0,
            ))


def _build_roots(
    rows: list[dict[str, Any]],
    catalog_entries: list[dict[str, Any]],
    root_specs: dict[str, dict[str, Any]],
    scanned_by_root: dict[str, list[Path]],
    catalog_sha_by_root: dict[str, str],
    dev_root: Path,
) -> list[dict[str, Any]]:
    roots: dict[str, dict[str, Any]] = {}
    catalog_count_by_root: dict[str, int] = {}
    for entry in catalog_entries:
        root_id = f"{entry['client']}/{entry['root_scope']}"
        catalog_count_by_root[root_id] = catalog_count_by_root.get(root_id, 0) + 1
    installed_only_count_by_root: dict[str, int] = {}
    for row in rows:
        if row["exposure_class"] == "installed-not-client-exposed":
            root_id = f"{row['client']}/{row['root_scope']}"
            installed_only_count_by_root[root_id] = installed_only_count_by_root.get(root_id, 0) + 1

    for root_id, spec in root_specs.items():
        installed_count = len(scanned_by_root.get(root_id, []))
        exposed_count = catalog_count_by_root.get(root_id, 0)
        roots[root_id] = {
            "root_id": root_id,
            "client": spec["client"],
            "root_scope": spec["root_scope"],
            "root_path": spec["root_path"],
            "required": spec["required"],
            "exists": spec["exists"],
            "discovery_source_class": spec["discovery_source_class"],
            "discovery_source_sha256": catalog_sha_by_root.get(root_id),
            "installed_count": installed_count,
            "exposed_count": exposed_count,
            "installed_only_count": installed_only_count_by_root.get(root_id, 0),
            "classification_rule": spec["classification_rule"],
        }

    for entry in catalog_entries:
        root_id = f"{entry['client']}/{entry['root_scope']}"
        if root_id in roots:
            continue
        root_scope = entry["root_scope"]
        path_value = entry["installed_path"]
        if root_scope == "cursor-home-agents-context":
            root_path = path_value
            required = True
            exists = Path(path_value).exists() if path_value is not None else False
            classification = "cursor-home-full-context/v1"
        elif root_scope == "dev-workspace-agents-context":
            root_path = path_value
            required = True
            exists = Path(path_value).exists() if path_value is not None else False
            classification = "cursor-workspace-full-context/v1"
        elif path_value is None:
            root_path = None
            required = False
            exists = False
            classification = "client-injected-catalog/v1"
        else:
            path = Path(path_value)
            if entry["exposure_class"] in {"cursor-rule-always-applied", "cursor-rule-requestable"}:
                _scope, root_path_obj, classification, required = _root_for_rule(path, dev_root)
            else:
                _scope, root_path_obj, classification = _root_for_skill(path)
                required = _scope == "cursor-user-skills"
            root_path = str(root_path_obj)
            exists = root_path_obj.exists()
        roots[root_id] = {
            "root_id": root_id,
            "client": entry["client"],
            "root_scope": root_scope,
            "root_path": root_path,
            "required": required,
            "exists": exists,
            "discovery_source_class": "cursor-session-context",
            "discovery_source_sha256": catalog_sha_by_root.get(root_id),
            "installed_count": catalog_count_by_root.get(root_id, 0),
            "exposed_count": catalog_count_by_root.get(root_id, 0),
            "installed_only_count": installed_only_count_by_root.get(root_id, 0),
            "classification_rule": classification,
        }

    return sorted(roots.values(), key=lambda item: _ascii_sort_key(item["root_id"]))


def _build_inventory(args: argparse.Namespace) -> dict[str, Any]:
    dev_root = Path(args.dev_root).resolve(strict=True)
    skills_root = Path(args.skills_root).resolve(strict=True)
    cpp_root = Path(args.cpp_root).resolve(strict=True)
    awa_root = Path(args.awa_root).resolve(strict=True)
    dev_commit, dev_tree = _verify_inputs(dev_root, skills_root, cpp_root, awa_root)
    e03 = _load_e03(skills_root)
    source_path = Path(args.cursor_session_source)
    source = _load_json(source_path)
    sections = _section_map(source)
    if Path(source["workspace_root"]).resolve(strict=True) != dev_root:
        _fail("workspace-root mismatch")

    rows: list[dict[str, Any]] = []
    catalog_entries: list[dict[str, Any]] = []
    source_section_rows: list[dict[str, Any]] = []

    always = _parse_xmlish(sections["always_applied_workspace_rules"]["source_text"], "always_applied_workspace_rule")
    for item in always:
        name_attr = item.get("name")
        if not name_attr:
            _fail("always-applied rule missing name")
        path = Path(name_attr).expanduser()
        if not path.exists():
            _fail(f"always-applied path missing: {path}")
        root_scope, _root_path, _rule, _required = _root_for_rule(path, dev_root)
        if root_scope == "cursor-home-agents-context":
            exposure = "cursor-home-full-context"
        elif root_scope == "dev-workspace-agents-context":
            exposure = "cursor-workspace-full-context"
        else:
            exposure = "cursor-rule-always-applied"
        owner = _owner_for_path(path, dev_root, skills_root, cpp_root, awa_root)
        rows.append(_row(
            client="cursor",
            root_scope=root_scope,
            declared_name=_path_name(path),
            installed_path=path,
            owner=owner,
            exposure=exposure,
            installed_kind=_installed_kind(path),
            description_chars=0,
            description_words=0,
        ))
        catalog_entries.append(_catalog_entry(
            client="cursor",
            catalog_kind=exposure,
            root_scope=root_scope,
            declared_name=_path_name(path),
            installed_path=path,
            exposure_class=exposure,
            description_sha256=None,
            description_chars=0,
            description_words=0,
        ))
    source_section_rows.append({
        "section": "always_applied_workspace_rules",
        "source_sha256": sections["always_applied_workspace_rules"]["source_sha256"],
        "source_entry_count": len(always),
        "canonical_entry_count": len(always),
    })

    requestable = _parse_xmlish(sections["agent_requestable_workspace_rules"]["source_text"], "agent_requestable_workspace_rule")
    for item in requestable:
        full_path = item.get("fullPath")
        if not full_path:
            _fail("requestable rule missing fullPath")
        path = Path(full_path).expanduser()
        if not path.exists():
            _fail(f"requestable rule path missing: {path}")
        chars, words, desc_sha = _rule_counts(path)
        root_scope, _root_path, _rule, _required = _root_for_rule(path, dev_root)
        owner = _owner_for_path(path, dev_root, skills_root, cpp_root, awa_root)
        rows.append(_row(
            client="cursor",
            root_scope=root_scope,
            declared_name=_path_name(path),
            installed_path=path,
            owner=owner,
            exposure="cursor-rule-requestable",
            installed_kind=_installed_kind(path),
            description_chars=chars,
            description_words=words,
        ))
        catalog_entries.append(_catalog_entry(
            client="cursor",
            catalog_kind="cursor-rule-requestable",
            root_scope=root_scope,
            declared_name=_path_name(path),
            installed_path=path,
            exposure_class="cursor-rule-requestable",
            description_sha256=desc_sha,
            description_chars=chars,
            description_words=words,
        ))
    source_section_rows.append({
        "section": "agent_requestable_workspace_rules",
        "source_sha256": sections["agent_requestable_workspace_rules"]["source_sha256"],
        "source_entry_count": len(requestable),
        "canonical_entry_count": len(requestable),
    })

    skills = _parse_xmlish(sections["agent_skills"]["source_text"], "agent_skill")
    for item in skills:
        full_path = item.get("fullPath")
        if not full_path:
            _fail("agent skill missing fullPath")
        path = Path(full_path).expanduser()
        if not path.exists():
            _fail(f"agent skill path missing: {path}")
        root_scope, _root_path, _rule = _root_for_skill(path)
        chars, words, desc_sha = _skill_counts(path, e03)
        exposure = "cursor-plugin-skill-description" if "plugin" in root_scope else "cursor-skill-description"
        owner = _owner_for_path(path, dev_root, skills_root, cpp_root, awa_root)
        rows.append(_row(
            client="cursor",
            root_scope=root_scope,
            declared_name=_descriptor_name(path),
            installed_path=path,
            owner=owner,
            exposure=exposure,
            installed_kind=_installed_kind(path),
            description_chars=chars,
            description_words=words,
        ))
        catalog_entries.append(_catalog_entry(
            client="cursor",
            catalog_kind=exposure,
            root_scope=root_scope,
            declared_name=_descriptor_name(path),
            installed_path=path,
            exposure_class=exposure,
            description_sha256=desc_sha,
            description_chars=chars,
            description_words=words,
        ))
    source_section_rows.append({
        "section": "agent_skills",
        "source_sha256": sections["agent_skills"]["source_sha256"],
        "source_entry_count": len(skills),
        "canonical_entry_count": len(skills),
    })

    root_specs = _descriptor_root_specs(dev_root, catalog_entries)
    catalog_paths = _catalog_paths_by_root(catalog_entries, root_specs)
    scanned_by_root = {
        root_id: _scan_descriptor_root(spec, catalog_paths.get(root_id, set()))
        for root_id, spec in root_specs.items()
    }
    scanned_paths_by_root = {root_id: set(paths) for root_id, paths in scanned_by_root.items()}
    for root_id, paths in catalog_paths.items():
        missing = paths - scanned_paths_by_root.get(root_id, set())
        if missing:
            _fail(f"catalog fullPath not found in scanned files for {root_id}: {sorted(str(path) for path in missing)}")
    _append_installed_only_rows(rows, root_specs, scanned_by_root, catalog_paths, dev_root, skills_root, cpp_root, awa_root)

    rows.sort(key=lambda item: _ascii_sort_key(item["capability_id"]))
    catalog_entries.sort(key=lambda item: _ascii_sort_key(item["capability_id"]))
    if len({row["capability_id"] for row in rows}) != len(rows):
        _fail("duplicate capability_id")

    by_root_entries: dict[str, list[dict[str, Any]]] = {}
    for entry in catalog_entries:
        by_root_entries.setdefault(f"{entry['client']}/{entry['root_scope']}", []).append(entry)
    for root_id in root_specs:
        by_root_entries.setdefault(root_id, [])
    catalog_sha_by_root = {
        root_id: _canonical_sha256(entries)
        for root_id, entries in sorted(by_root_entries.items())
    }
    roots = _build_roots(rows, catalog_entries, root_specs, scanned_by_root, catalog_sha_by_root, dev_root)

    totals = {
        "by_client": _count_by(rows, "client"),
        "by_owner_source_repo": _count_by(rows, "owner_source_repo"),
        "by_exposure_class": _count_by(rows, "exposure_class"),
        "by_eligibility": _count_by(rows, "eligibility"),
    }
    catalog_completeness = [{
        "client": "cursor",
        "complete": True,
        "source_sections": sorted(source_section_rows, key=lambda item: _ascii_sort_key(item["section"])),
        "canonical_entries": len(catalog_entries),
        "emitted_rows": len([entry for entry in catalog_entries if entry["client"] == "cursor"]),
        "dropped_entries": 0,
        "canonical_catalog_sha256_by_root": catalog_sha_by_root,
    }]
    artifact = {
        "schema": SCHEMA,
        "status": STATUS,
        "captured_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": REPOSITORY,
        "dev_commit": dev_commit,
        "dev_tree": dev_tree,
        "client_scope": CLIENT_SCOPE,
        "environment_class": ENVIRONMENT_CLASS,
        "method": METHOD,
        "catalog_completeness": catalog_completeness,
        "roots": roots,
        "rows": rows,
        "totals": totals,
    }
    validate_object(artifact)
    return artifact


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = row[field]
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _validate_digest(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise InventoryError("invalid digest")


def _validate_nonnegative_int(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise InventoryError("invalid nonnegative integer")


def validate_cursor_catalog(catalog: dict[str, Any]) -> None:
    if set(catalog) != {"schema", "client", "workspace_root", "captured_at_utc", "source_sections", "entries"}:
        raise InventoryError("cursor catalog keys mismatch")
    if catalog["schema"] != CURSOR_CATALOG_SCHEMA or catalog["client"] != "cursor":
        raise InventoryError("cursor catalog identity mismatch")
    if not UTC_TIMESTAMP.fullmatch(catalog["captured_at_utc"]):
        raise InventoryError("cursor catalog timestamp invalid")
    entries = catalog["entries"]
    if type(entries) is not list:
        raise InventoryError("cursor catalog entries invalid")
    if entries != sorted(entries, key=lambda item: _ascii_sort_key(item["capability_id"])):
        raise InventoryError("cursor catalog entries unsorted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != ENTRY_KEYS:
            raise InventoryError("cursor catalog entry keys mismatch")
        if entry["client"] != "cursor" or entry["exposure_class"] not in EXPOSURES:
            raise InventoryError("cursor catalog entry invalid")
        _validate_digest(entry["description_sha256"], nullable=True)
        _validate_nonnegative_int(entry["description_chars"])
        _validate_nonnegative_int(entry["description_words"])


def validate_object(value: dict[str, Any]) -> None:
    if type(value) is not dict or set(value) != TOP_KEYS:
        raise InventoryError("top-level keys mismatch")
    if value["schema"] != SCHEMA or value["status"] != STATUS:
        raise InventoryError("schema/status mismatch")
    if value["repository"] != REPOSITORY or value["environment_class"] != ENVIRONMENT_CLASS or value["method"] != METHOD:
        raise InventoryError("fixed metadata mismatch")
    if value["client_scope"] != CLIENT_SCOPE:
        raise InventoryError("client_scope mismatch")
    if not UTC_TIMESTAMP.fullmatch(value["captured_at_utc"]):
        raise InventoryError("captured_at_utc invalid")
    if not HEX40.fullmatch(value["dev_commit"]) or not HEX40.fullmatch(value["dev_tree"]):
        raise InventoryError("dev refs invalid")

    rows = value["rows"]
    roots = value["roots"]
    completeness = value["catalog_completeness"]
    totals = value["totals"]
    if type(rows) is not list or type(roots) is not list or type(completeness) is not list:
        raise InventoryError("array fields invalid")
    if rows != sorted(rows, key=lambda item: _ascii_sort_key(item["capability_id"])):
        raise InventoryError("rows unsorted")
    if roots != sorted(roots, key=lambda item: _ascii_sort_key(item["root_id"])):
        raise InventoryError("roots unsorted")
    if len({row["capability_id"] for row in rows}) != len(rows):
        raise InventoryError("duplicate row capability_id")
    root_ids = {root["root_id"] for root in roots}
    rows_by_root: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if type(row) is not dict or set(row) != ROW_KEYS:
            raise InventoryError("row keys mismatch")
        if row["client"] not in CLIENT_SCOPE:
            raise InventoryError("row client outside scope")
        if row["owner_source_repo"] not in OWNER_REPOS:
            raise InventoryError("row owner invalid")
        if row["exposure_class"] not in EXPOSURES:
            raise InventoryError("row exposure invalid")
        if row["eligibility"] not in ELIGIBILITIES:
            raise InventoryError("row eligibility invalid")
        _validate_nonnegative_int(row["description_chars"])
        _validate_nonnegative_int(row["description_words"])
        if row["exposure_class"] in ZERO_COUNT_EXPOSURES and (row["description_chars"] != 0 or row["description_words"] != 0):
            raise InventoryError("zero-count exposure has description counts")
        if row["installed_path"] is None:
            if row["installed_kind"] != "injection-only" or row["installed_sha256"] is not None:
                raise InventoryError("injection-only path fields invalid")
        else:
            if type(row["installed_path"]) is not str or row["installed_kind"] not in {"regular-file", "symlink"}:
                raise InventoryError("installed path fields invalid")
            _validate_digest(row["installed_sha256"])
        if f"{row['client']}/{row['root_scope']}" not in root_ids:
            raise InventoryError("row root missing")
        rows_by_root.setdefault(f"{row['client']}/{row['root_scope']}", []).append(row)
    for root in roots:
        if type(root) is not dict or set(root) != ROOT_KEYS:
            raise InventoryError("root keys mismatch")
        if root["client"] not in CLIENT_SCOPE:
            raise InventoryError("root client outside scope")
        if root["root_id"] != f"{root['client']}/{root['root_scope']}":
            raise InventoryError("root_id mismatch")
        if type(root["required"]) is not bool or type(root["exists"]) is not bool:
            raise InventoryError("root bool fields invalid")
        if root["root_path"] is not None and type(root["root_path"]) is not str:
            raise InventoryError("root_path invalid")
        if root["discovery_source_class"] not in {"cursor-session-context", "filesystem-runtime-config", "absent-required-root", "absent-optional-root"}:
            raise InventoryError("root discovery source invalid")
        _validate_digest(root["discovery_source_sha256"], nullable=True)
        for key in ("installed_count", "exposed_count", "installed_only_count"):
            _validate_nonnegative_int(root[key])
        root_rows = rows_by_root.get(root["root_id"], [])
        installed_only_rows = [
            row for row in root_rows
            if row["exposure_class"] == "installed-not-client-exposed"
        ]
        exposed_rows = [
            row for row in root_rows
            if row["exposure_class"] != "installed-not-client-exposed"
        ]
        if root["installed_count"] != root["exposed_count"] + root["installed_only_count"]:
            raise InventoryError("root installed count invariant mismatch")
        if root["installed_only_count"] != len(installed_only_rows):
            raise InventoryError("root installed_only_count rows mismatch")
        if root["exposed_count"] != len(exposed_rows):
            raise InventoryError("root exposed_count rows mismatch")
    if type(totals) is not dict or set(totals) != {"by_client", "by_owner_source_repo", "by_exposure_class", "by_eligibility"}:
        raise InventoryError("totals keys mismatch")
    expected_totals = {
        "by_client": _count_by(rows, "client"),
        "by_owner_source_repo": _count_by(rows, "owner_source_repo"),
        "by_exposure_class": _count_by(rows, "exposure_class"),
        "by_eligibility": _count_by(rows, "eligibility"),
    }
    if totals != expected_totals:
        raise InventoryError("totals mismatch")
    if len(completeness) != 1:
        raise InventoryError("catalog completeness cardinality mismatch")
    proof = completeness[0]
    if type(proof) is not dict or set(proof) != CATALOG_KEYS:
        raise InventoryError("catalog completeness keys mismatch")
    if proof["client"] != "cursor" or proof["complete"] is not True:
        raise InventoryError("catalog completeness identity mismatch")
    catalog_backed_rows = [
        row for row in rows
        if row["client"] == "cursor" and row["exposure_class"] != "installed-not-client-exposed"
    ]
    if proof["emitted_rows"] != len(catalog_backed_rows):
        raise InventoryError("catalog completeness emitted_rows mismatch")
    if proof["dropped_entries"] != 0:
        raise InventoryError("catalog completeness dropped entries")
    sections = proof["source_sections"]
    if type(sections) is not list or sections != sorted(sections, key=lambda item: _ascii_sort_key(item["section"])):
        raise InventoryError("catalog completeness source sections invalid")
    section_total = 0
    for section in sections:
        if type(section) is not dict or set(section) != SOURCE_SECTION_KEYS:
            raise InventoryError("source section keys mismatch")
        _validate_digest(section["source_sha256"])
        _validate_nonnegative_int(section["source_entry_count"])
        _validate_nonnegative_int(section["canonical_entry_count"])
        section_total += section["canonical_entry_count"]
    if proof["canonical_entries"] != section_total:
        raise InventoryError("catalog completeness canonical_entries mismatch")
    if proof["canonical_entries"] != proof["emitted_rows"]:
        raise InventoryError("catalog completeness emitted rows mismatch catalog")
    if type(proof["canonical_catalog_sha256_by_root"]) is not dict:
        raise InventoryError("catalog root hash map invalid")
    for root_id, digest in proof["canonical_catalog_sha256_by_root"].items():
        if root_id not in root_ids:
            raise InventoryError("catalog root hash for unknown root")
        _validate_digest(digest)


def capture(args: argparse.Namespace) -> int:
    artifact = _build_inventory(args)
    out = Path(args.out)
    if out.exists() and out.is_dir():
        _fail(f"output path is a directory: {out}")
    old_umask = os.umask(0o077)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_emit(artifact), encoding="ascii", newline="\n")
    finally:
        os.umask(old_umask)
    validate_path(out)
    return 0


def validate_path(path: Path) -> None:
    value = _load_json(path)
    validate_object(value)
    canonical = _emit(value).encode("ascii")
    try:
        raw = path.read_bytes()
    except OSError as error:
        _fail(f"artifact unreadable: {path}: {error}")
    if raw != canonical:
        _fail("artifact is not canonical JSON")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capability_discovery_inventory.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--dev-root", required=True)
    capture_parser.add_argument("--skills-root", required=True)
    capture_parser.add_argument("--cpp-root", required=True)
    capture_parser.add_argument("--awa-root", required=True)
    capture_parser.add_argument("--cursor-session-source", required=True)
    capture_parser.add_argument("--out", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "capture":
            return capture(args)
        if args.command == "validate":
            validate_path(Path(args.path))
            print("PASS")
            return 0
        raise AssertionError(args.command)
    except InventoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
