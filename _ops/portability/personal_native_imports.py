"""Read-only assessment for two fresh-account native import alternatives.

Data never supplies source acceptance, user consent or lifecycle authority.
This module installs nothing and never invokes a native tool or network API.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = "personal-portability/native-goal-shell-observation/v1"
HOST = {
    "build": "23880", "system": "Darwin", "machine": "arm64",
    "app_info_sha256": "7a3920d56d052cdf4bf803a92e2098be015eaf9263589d51e04ac4121f16eed7",
    "cli_sha256": "58a91f6ea19bea477ae3a2ec48d619f0039afe75d3476260747e11d201fa7cea",
}
OFFERS = {
    "create_goal": "9b02bfad34942149ab952b584a9ed87252219ebe667c73dd3bccdeff68d5a2a7",
    "get_goal": "92459fc509db6684978a60025841f909c6332f25048079915eaddff1d1a5cc49",
    "update_goal": "49f870438dbad017a289eb4beb3ad12cb415557a1bf911b3733848407452f695",
    "exec_command": "e383074c19e29a092b2f6aa501902524916871ba14e4075791e7e043838a9de2",
    "write_stdin": "9479728f956ddacfa4ffad348fb7dde43ea8ba7f612e8f3bc5faea21d4b2d298",
}
# The shell tool declaration changed in build 29803. Keep each host bound to its own offers.
HOST_29803 = {
    "build": "29803", "system": "Darwin", "machine": "arm64",
    "app_info_sha256": "8c6ca4191902a2c22f7bf4c114c0ba4bb18e49b0f02776c1edc5137a99568831",
    "cli_sha256": "3b6d00deea5fabc50ad34be1872b8e4ead1638d23c68fabb7837edc07f0cf1e0",
}
OFFERS_29803 = {
    **OFFERS,
    "exec_command": "e000f1e2e40a3431b97f76c2548cea7332e20d308a68cf168b4812cb1ebaf7f8",
}

ZERO_EFFECTS = {"model_workers", "new_threads", "global_config_writes", "global_links",
                "goal_mutations", "installed_services", "Affirm_connections",
                "protected_component_access", "recovered_archive_execution"}
INPUT_SHA = hashlib.sha256(b"personal-shell-preservation-fixture\n").hexdigest()
STDIN_SHA = hashlib.sha256(b"seed-7").hexdigest()
FIXTURE_SHA = "1597163d3ceedcdd855ee4b6326f6092320766eee94cd3dff647a490f54e126b"


class ObservationError(ValueError):
    """A bounded, non-sensitive refusal code."""


def need(condition: bool, code: str) -> None:
    if not condition:
        raise ObservationError(code)


def canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ObservationError("finite_json_required") from exc
    need(len(raw) <= 1024 * 1024, "observation_too_large")
    return raw


def integer(value: object) -> bool:
    return type(value) is int and value >= 0


def assess(observation: dict) -> dict:
    """Check actual bounded observations; return no installation/acceptance grant."""
    canonical(observation)
    try:
        need(set(observation) == {"schema", "host", "identity", "offers", "catalog", "binding", "goal", "shell", "safety"}, "closed_observation_required")
        host = observation["host"]
        need(observation["schema"] == SCHEMA and host in (HOST, HOST_29803), "host_or_schema_changed")
        expected_offers = OFFERS if host == HOST else OFFERS_29803
        need(observation["offers"] == expected_offers, "native_offer_changed")
        identity = observation["identity"]
        need(set(identity) == {"expected_personal_email", "observed_email", "account_type", "workspace_name"}, "closed_identity_required")
        email = identity["expected_personal_email"]
        need(isinstance(email, str) and "@" in email and identity["observed_email"] == email, "personal_identity_not_established")
        need(identity["account_type"] == "chatgpt" and identity["workspace_name"] is None and not email.lower().endswith("@affirm.com"), "work_identity_refused")
        catalog = observation["catalog"]
        need(catalog["complete_response"] is True and catalog["extra_roots"] == [] and catalog["token_refresh_requested"] is False, "catalog_not_qualified")
        need(all(catalog[k] is False for k in ("plugin_installation", "activation", "source_only_roots_added")), "catalog_activation_refused")
        need(all(type(catalog[k]) is int and catalog[k] == 0 for k in ("threads_or_turns_created", "native_workers_started")), "catalog_worker_refused")
        methods = [r["method"] for r in catalog["requests"]]
        need(methods == ["initialize", "initialized", "account/read", "skills/list", "plugin/installed"], "catalog_request_outside_route")
        need(catalog["requests"][2]["params"] == {"refreshToken": False}, "refresh_refused")
        need(catalog["host_build"] == host["build"] and catalog["cli_sha256"] == host["cli_sha256"], "catalog_host_changed")
        binding = observation["binding"]
        need(set(binding) == {"thread_id", "objective_sha256", "fixture_sha256", "workspace"}, "closed_binding_required")
        need(isinstance(binding["thread_id"], str) and 0 < len(binding["thread_id"]) <= 128, "thread_binding_required")
        workspace = binding["workspace"]
        need(isinstance(workspace, str) and workspace.startswith("/") and "\x00" not in workspace and not any(p.lower() in {"affirm", "chaos-scheduler", ".."} for p in workspace.split("/")), "personal_workspace_required")
        need(catalog["requests"][3]["params"] == {"cwds": [workspace], "forceReload": True} and catalog["requests"][4]["params"] == {"cwds": [workspace]}, "catalog_cwd_changed")
        need(all(isinstance(binding[k], str) and re.fullmatch(r"[0-9a-f]{64}", binding[k]) for k in ("objective_sha256", "fixture_sha256")), "digest_binding_required")
        need(binding["fixture_sha256"] == FIXTURE_SHA, "fixture_source_changed")
        before, after = observation["goal"]["before"], observation["goal"]["after"]
        for row in (before, after):
            goal = row["goal"]
            need(goal["threadId"] == binding["thread_id"] and goal["status"] == "active", "goal_scope_or_status_changed")
            need(isinstance(goal["objective"], str) and 0 < len(goal["objective"]) <= 4000, "goal_objective_invalid")
            need(hashlib.sha256(goal["objective"].encode()).hexdigest() == binding["objective_sha256"], "goal_objective_changed")
            need(all(integer(goal[k]) for k in ("createdAt", "updatedAt", "tokensUsed", "timeUsedSeconds")), "goal_accounting_invalid")
        need(before["goal"]["createdAt"] == after["goal"]["createdAt"], "goal_replaced")
        need(all(after["goal"][k] >= before["goal"][k] for k in ("updatedAt", "tokensUsed", "timeUsedSeconds")), "goal_accounting_rewound")
        remaining = [r["remainingTokens"] for r in (before, after)]
        need(remaining == [None, None] or all(integer(v) for v in remaining) and remaining[1] <= remaining[0], "goal_budget_changed")
        shell = observation["shell"]
        need(set(shell) == {"files", "nonzero", "interactive_start", "interactive_finish", "cancel_start", "cancel_finish"}, "closed_shell_trace_required")
        need(shell["files"]["exit_code"] == 0, "shell_file_check_failed")
        files = json.loads(shell["files"]["output"])
        need(files["cwd_matches"] is True and files["child_scoped_env_matches"] is True and files["native_system"] == host["system"] and files["native_architecture"] == host["machine"], "shell_destination_changed")
        need(files["preserved_input_sha256"] == INPUT_SHA and files["preserved_input_mode"] == 0o600 and integer(files["preserved_input_inode"]) and files["preserved_input_inode"] > 0, "shell_input_not_preserved")
        need(shell["nonzero"]["exit_code"] == 17 and all(s in shell["nonzero"]["output"] for s in ("synthetic-stdout-before-error", "synthetic-stderr-before-error")), "shell_nonzero_not_observed")
        for prefix, marker, code in (("interactive", "READY-FOR-SYNTHETIC-INPUT", 0), ("cancel", "READY-FOR-SCOPED-CANCEL", 130)):
            start, finish = shell[prefix + "_start"], shell[prefix + "_finish"]
            need(type(start.get("session_id")) is int and start["session_id"] > 0 and start.get("exit_code") is None and marker in start["output"], "native_session_not_observed")
            need(finish.get("exit_code") == code and finish.get("session_id") is None, "native_session_not_terminal")
            lines = finish["output"].replace("\r", "").splitlines()
            raw = next((line[line.index("{"):] for line in lines if "{" in line), "")
            payload = json.loads(raw)
            seconds = payload["elapsed_seconds"]
            need(type(seconds) in (float, int) and math.isfinite(seconds) and 0 <= seconds < 15, "native_session_deadline_failed")
            if prefix == "interactive":
                need(payload["stdin_roundtrip_passed"] is True and payload["stdin_sha256"] == STDIN_SHA, "native_stdin_failed")
            else:
                need(payload["native_sigint_received"] is True, "native_cancel_failed")
        safety = observation["safety"]
        need(set(safety) == ZERO_EFFECTS and all(type(v) is int and v == 0 for v in safety.values()), "effect_outside_route")
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as exc:
        raise ObservationError("incomplete_or_malformed_observation") from exc
    return {"schema": "personal-portability/native-import-assessment/v1",
            "eligible_for_bounded_destination_record": ["imported/goal", "imported/shell"],
            "provider_owner": "OpenAI", "source_route": "fresh-account native host distribution",
            "host_build": host["build"], "observation_sha256": hashlib.sha256(canonical(observation)).hexdigest(),
            "legacy_implementation_or_UI_parity_proven": False, "source_acceptance_supplied_by_data": False,
            "installation_or_lifecycle_authority": False, "formal_migration_complete": False}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: personal_native_imports.py OBSERVATION.json", file=sys.stderr)
        return 2
    try:
        path = Path(args[0])
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, "private_observation_required")
            need(before.st_size <= 1024 * 1024, "observation_too_large")
            raw = os.read(fd, 1024 * 1024 + 1)
            after = os.fstat(fd)
            need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "observation_changed_during_read")
        finally:
            os.close(fd)
        need(len(raw) <= 1024 * 1024, "observation_too_large")
        need(len(raw) == before.st_size, "observation_read_incomplete")
        result = assess(json.loads(raw))
    except (ObservationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc) if isinstance(exc, ObservationError) else "observation_unreadable"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
