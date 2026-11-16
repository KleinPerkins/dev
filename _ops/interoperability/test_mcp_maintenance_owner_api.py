"""Opt-in synthetic cross-owner source test; never installs or qualifies a host.

Set INT014_MAINTENANCE_OWNER_ROOT to an explicitly verified kp-mcp source checkout
and use its existing test Python environment. The ordinary dependency-free dev
gate skips this test; delivery records the actual tested owner source separately.
No fixture revision is admitted in production.
"""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dev_int014_maintenance", HERE / "mcp_maintenance.py")
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)
OWNER = os.environ.get("INT014_MAINTENANCE_OWNER_ROOT")


@unittest.skipUnless(OWNER, "explicit source-qualified owner package required")
class OwnerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = Path(OWNER).resolve()
        sys.path.insert(0, str(cls.owner / "kp-mcp-bootstrap/src"))
        import kp_mcp_bootstrap.registrars as api
        from kp_mcp_bootstrap.registrars import maintenance
        from kp_mcp_bootstrap.registrars.contracts import utc_now
        cls.api, cls.maintenance, cls.clock = api, maintenance, staticmethod(utc_now)
        helper = importlib.util.spec_from_file_location("int014_owner_fixture", cls.owner / "kp-mcp-bootstrap/tests/test_registrar_maintenance.py")
        cls.fixture = importlib.util.module_from_spec(helper)
        helper.loader.exec_module(cls.fixture)

    @contextmanager
    def example(self):
        import pytest
        with tempfile.TemporaryDirectory(prefix="dev-owner-maintenance-") as name, pytest.MonkeyPatch.context() as mp:
            base = Path(name).resolve()
            base.chmod(0o700)
            with self.fixture.example(base, mp) as (registrar, definition, context, owner_observer):
                store = dev.MaintenanceStore(base / "dev-state")
                evidence = context.maintenance_evidence.to_record()

                class Observations:
                    def current(self, e, now):
                        if owner_observer.status.get(e["maintenance_id"]) != "acquired":
                            raise dev.MaintenanceError()

                    def mutation(self, request, e):
                        owner_observer.validate(request)

                    def lineage(self, e, parent):
                        raise dev.MaintenanceError("recovery_required")

                    def transition(self, e, before, after, child):
                        raise dev.MaintenanceError("concurrency_unqualified")

                observed = Observations()
                store.acquire(evidence, observed, config_path=context.config_path,
                              state_directory=context.state_directory, now=self.clock())
                validator = dev.MaintenanceValidator(store, self.fixture.REVISION, observed)
                registrar = self.api.CursorRegistrar(maintenance_validator=validator)
                yield registrar, definition, context, owner_observer, validator

    def test_actual_prepare_apply_reload_under_one_outer_barrier(self):
        with self.example() as (registrar, definition, context, observed, validator):
            with self.assertRaises(self.api.RegistrarError):
                registrar.preview(context.config_path, definition, context=context)
            with validator.operation():
                preview = registrar.preview(context.config_path, definition, context=context)
                observed.classify(preview)
                prepared = registrar.prepare(preview)
                approval = observed.approve(prepared)
                result = registrar.apply(prepared, approval)
                self.assertEqual(result.outcome, self.api.Outcome.APPLIED)
                self.assertEqual(result.concurrency_claim, "coordinated")
                rebuilt = self.api.CursorRegistrar(maintenance_validator=validator)
                loaded = rebuilt.load_prepared(prepared.record_id, context=context, definition=definition)
                self.assertEqual(rebuilt.apply(loaded, approval).outcome, self.api.Outcome.NO_CHANGE)
            phases = {r.phase for r in observed.requests}
            self.assertTrue({"prepare_locked", "config_replace", "receipt_replace", "terminal_commit"} <= phases)

    def test_real_registrar_last_check_race_remains_a_lost_update(self):
        from kp_mcp_bootstrap.registrars import state
        with self.example() as (registrar, definition, context, observed, validator):
            with validator.operation():
                preview = registrar.preview(context.config_path, definition, context=context)
                observed.classify(preview)
                prepared = registrar.prepare(preview)
                approval = observed.approve(prepared)
                replace_file = state.os.replace

                def interleave(source, destination):
                    if Path(destination) == context.config_path:
                        context.config_path.write_text('{"unexpected_writer":"synthetic"}')
                    return replace_file(source, destination)

                with patch.object(state.os, "replace", side_effect=interleave):
                    result = registrar.apply(prepared, approval)
                self.assertEqual(result.outcome, self.api.Outcome.APPLIED)
                self.assertNotIn("unexpected_writer", context.config_path.read_text())
                self.assertEqual(result.concurrency_claim, "coordinated")


if __name__ == "__main__":
    unittest.main()
