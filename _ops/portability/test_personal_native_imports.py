"""Offline contract/refusal tests; no account, native process or goal mutation."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("personal_native_imports_contract", Path(__file__).with_name("personal_native_imports.py"))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def observation():
    workspace = "/Users/synthetic/Codex/native-import-fixture"
    goal = {"threadId": "synthetic-personal-thread", "objective": "Complete the synthetic garden check.",
            "status": "active", "tokensUsed": 100, "timeUsedSeconds": 5, "createdAt": 1, "updatedAt": 2}
    before = {"goal": goal, "remainingTokens": None, "completionBudgetReport": None}
    after = copy.deepcopy(before); after["goal"].update(tokensUsed=120, timeUsedSeconds=7, updatedAt=3)
    catalog = {"complete_response": True, "extra_roots": [], "token_refresh_requested": False,
        "plugin_installation": False, "activation": False, "source_only_roots_added": False,
        "threads_or_turns_created": 0, "native_workers_started": 0,
        "host_build": observer.HOST["build"], "cli_sha256": observer.HOST["cli_sha256"],
        "requests": [{"method": "initialize", "params": {}}, {"method": "initialized", "params": {}},
            {"method": "account/read", "params": {"refreshToken": False}},
            {"method": "skills/list", "params": {"cwds": [workspace], "forceReload": True}},
            {"method": "plugin/installed", "params": {"cwds": [workspace]}}]}
    files = {"cwd_matches": True, "child_scoped_env_matches": True, "native_system": "Darwin",
        "native_architecture": "arm64", "preserved_input_sha256": observer.INPUT_SHA,
        "preserved_input_inode": 1, "preserved_input_mode": 0o600}
    return {"schema": observer.SCHEMA, "host": copy.deepcopy(observer.HOST),
        "identity": {"expected_personal_email": "person@example.invalid", "observed_email": "person@example.invalid",
                     "account_type": "chatgpt", "workspace_name": None},
        "offers": copy.deepcopy(observer.OFFERS), "catalog": catalog,
        "binding": {"thread_id": goal["threadId"], "objective_sha256": hashlib.sha256(goal["objective"].encode()).hexdigest(),
                    "fixture_sha256": observer.FIXTURE_SHA, "workspace": workspace},
        "goal": {"before": before, "after": after},
        "shell": {"files": {"exit_code": 0, "output": json.dumps(files)},
            "nonzero": {"exit_code": 17, "output": "synthetic-stdout-before-error\nsynthetic-stderr-before-error\n"},
            "interactive_start": {"session_id": 1, "output": "READY-FOR-SYNTHETIC-INPUT\r\n"},
            "interactive_finish": {"exit_code": 0, "output": "seed-7\r\n" + json.dumps({"stdin_sha256": observer.STDIN_SHA, "stdin_roundtrip_passed": True, "elapsed_seconds": 1.0}) + "\r\n"},
            "cancel_start": {"session_id": 2, "output": "READY-FOR-SCOPED-CANCEL\r\n"},
            "cancel_finish": {"exit_code": 130, "output": "^C" + json.dumps({"native_sigint_received": True, "elapsed_seconds": 1.0}) + "\r\n"}},
        "safety": {key: 0 for key in observer.ZERO_EFFECTS}}


class NativeImportContract(unittest.TestCase):
    def test_fixture_source_is_bound(self):
        self.assertEqual(hashlib.sha256(Path(__file__).with_name("native_import_fixture.py").read_bytes()).hexdigest(),observer.FIXTURE_SHA)
    def reject(self, modify):
        value = observation(); modify(value)
        with self.assertRaises(observer.ObservationError): observer.assess(value)

    def test_exact_complete_observation_has_no_authority(self):
        value = observation(); before = copy.deepcopy(value); result = observer.assess(value)
        self.assertEqual(result["eligible_for_bounded_destination_record"], ["imported/goal", "imported/shell"])
        self.assertFalse(result["installation_or_lifecycle_authority"])
        self.assertFalse(result["source_acceptance_supplied_by_data"])
        self.assertFalse(result["legacy_implementation_or_UI_parity_proven"])
        self.assertFalse(result["formal_migration_complete"])
        self.assertEqual(value, before)

    def test_second_build_requires_its_observed_shell_contract(self):
        value = observation()
        value["host"] = observer.HOST_29803.copy()
        value["offers"] = observer.OFFERS_29803.copy()
        value["catalog"].update(host_build=value["host"]["build"], cli_sha256=value["host"]["cli_sha256"])
        self.assertEqual(observer.assess(value)["host_build"], "29803")

        for host, offers, reason in (
            (observer.HOST_29803, observer.OFFERS, "native_offer_changed"),
            (observer.HOST, observer.OFFERS_29803, "native_offer_changed"),
            ({**observer.HOST_29803, "cli_sha256": "0" * 64}, observer.OFFERS_29803, "host_or_schema_changed"),
        ):
            with self.subTest(reason=reason, build=host["build"]):
                with self.assertRaisesRegex(observer.ObservationError, reason):
                    observer.assess({**value, "host": host, "offers": offers})

    def test_unknown_fields_cannot_supply_approval(self): self.reject(lambda v:v.update(approved=True))
    def test_different_build(self): self.reject(lambda v:v["host"].update(build="other"))
    def test_different_binary(self): self.reject(lambda v:v["host"].update(cli_sha256="0"*64))
    def test_missing_native_offer(self): self.reject(lambda v:v["offers"].pop("write_stdin"))
    def test_changed_native_contract(self): self.reject(lambda v:v["offers"].update(get_goal="0"*64))
    def test_wrong_account(self): self.reject(lambda v:v["identity"].update(observed_email="other@example.invalid"))
    def test_work_account_even_if_expected(self): self.reject(lambda v:v["identity"].update(expected_personal_email="person@affirm.com",observed_email="person@affirm.com"))
    def test_workspace_identity(self): self.reject(lambda v:v["identity"].update(workspace_name="Company"))
    def test_incomplete_catalog(self): self.reject(lambda v:v["catalog"].update(complete_response=False))
    def test_extra_root(self): self.reject(lambda v:v["catalog"].update(extra_roots=["/elsewhere"]))
    def test_token_refresh(self): self.reject(lambda v:v["catalog"].update(token_refresh_requested=True))
    def test_native_worker(self): self.reject(lambda v:v["catalog"].update(native_workers_started=1))
    def test_activation(self): self.reject(lambda v:v["catalog"].update(activation=True))
    def test_extra_catalog_request(self): self.reject(lambda v:v["catalog"]["requests"].append({"method":"thread/start"}))
    def test_refresh_in_request(self): self.reject(lambda v:v["catalog"]["requests"][2]["params"].update(refreshToken=True))
    def test_changed_cwd(self): self.reject(lambda v:v["catalog"]["requests"][3]["params"].update(cwds=["/elsewhere"]))
    def test_work_cwd(self): self.reject(lambda v:v["binding"].update(workspace="/Users/synthetic/dev/affirm/project"))
    def test_foreign_goal(self): self.reject(lambda v:v["goal"]["after"]["goal"].update(threadId="another-thread"))
    def test_objective_change(self): self.reject(lambda v:v["goal"]["after"]["goal"].update(objective="easier"))
    def test_goal_replaced(self): self.reject(lambda v:v["goal"]["after"]["goal"].update(createdAt=2))
    def test_goal_paused(self): self.reject(lambda v:v["goal"]["after"]["goal"].update(status="paused"))
    def test_usage_rewinds(self): self.reject(lambda v:v["goal"]["after"]["goal"].update(tokensUsed=10))
    def test_boolean_accounting(self): self.reject(lambda v:v["goal"]["before"]["goal"].update(tokensUsed=True))
    def test_budget_replaced(self): self.reject(lambda v:v["goal"]["after"].update(remainingTokens=100))
    def test_budget_can_decrease(self):
        v=observation();v["goal"]["before"]["remainingTokens"]=100;v["goal"]["after"]["remainingTokens"]=80;observer.assess(v)
    def test_changed_fixture(self): self.reject(lambda v:v["binding"].update(fixture_sha256="0"*64))
    def test_file_execution_failure(self): self.reject(lambda v:v["shell"]["files"].update(exit_code=1))
    def test_invalid_preserved_inode(self):
        def alter(value):
            data=json.loads(value["shell"]["files"]["output"]);data["preserved_input_inode"]=-1
            value["shell"]["files"]["output"]=json.dumps(data)
        self.reject(alter)
    def test_nonzero_lost(self): self.reject(lambda v:v["shell"]["nonzero"].update(exit_code=0))
    def test_stderr_lost(self): self.reject(lambda v:v["shell"]["nonzero"].update(output="synthetic-stdout-before-error"))
    def test_missing_session(self): self.reject(lambda v:v["shell"]["interactive_start"].pop("session_id"))
    def test_unfinished_session(self): self.reject(lambda v:v["shell"]["interactive_finish"].update(session_id=1))
    def test_wrong_stdin(self): self.reject(lambda v:v["shell"]["interactive_finish"].update(output=json.dumps({"stdin_sha256":"0"*64,"stdin_roundtrip_passed":True,"elapsed_seconds":1})))
    def test_missed_deadline(self): self.reject(lambda v:v["shell"]["cancel_finish"].update(output=json.dumps({"native_sigint_received":True,"elapsed_seconds":15})))
    def test_wrong_cancel_outcome(self): self.reject(lambda v:v["shell"]["cancel_finish"].update(exit_code=124))
    def test_goal_mutation_cannot_hide_in_effects(self): self.reject(lambda v:v["safety"].update(goal_mutations=1))
    def test_effect_boolean_is_not_zero(self): self.reject(lambda v:v["safety"].update(model_workers=False))
    def test_nonfinite_data(self): self.reject(lambda v:v["shell"]["files"].update(wall_time_seconds=float("nan")))
    def test_oversized_data(self): self.reject(lambda v:v["goal"]["before"]["goal"].update(objective="x"*(1024*1024)))
    def test_private_cli_observation_and_no_sensitive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"observation.json";p.write_text(json.dumps(observation()));p.chmod(0o600)
            output=io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(observer.main([str(p)]),0)
            self.assertNotIn("person@example.invalid",output.getvalue())
            self.assertNotIn("Complete the synthetic",output.getvalue())
    def test_cli_refuses_symlink_and_shared_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"observation.json";p.write_text(json.dumps(observation()));p.chmod(0o600)
            link=Path(directory)/"alias.json";link.symlink_to(p)
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(observer.main([str(link)]),2)
            p.chmod(0o644)
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(observer.main([str(p)]),2)


if __name__ == "__main__": unittest.main()
