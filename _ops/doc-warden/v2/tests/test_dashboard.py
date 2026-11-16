import subprocess
import tempfile
import unittest
from pathlib import Path

from doc_warden.dashboard import (
    canvas_refresh_contract,
    generate_canvas,
    refresh_canvas,
    render_fleet_snapshot,
    render_repo_snapshot,
)
from doc_warden.inventory import CheckoutObservation, deduplicate_observations
from fixture_factory import FixtureFactory, ROOT


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    def test_canvas_snapshot_is_deterministic_and_contains_source_revision(self):
        first = render_repo_snapshot(self.fixture.repo)
        second = render_repo_snapshot(self.fixture.repo)
        revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"], text=True
        ).strip()
        self.assertEqual(first, second)
        self.assertEqual(first["source_revision"], revision)
        self.assertIn("generated_at", first)
        self.assertIn("source_observed_at", first)

    def test_fleet_canvas_rows_are_read_only(self):
        rows = deduplicate_observations(
            [
                CheckoutObservation(
                    "KleinPerkins/example",
                    123,
                    "/example",
                    True,
                    None,
                    "KleinPerkins",
                    "inspect",
                )
            ]
        )
        snapshot = render_fleet_snapshot(rows, source_revision="a" * 40)
        self.assertTrue(snapshot["read_only"])
        self.assertTrue(all("mutation" not in row for row in snapshot["repositories"]))

    def test_tracked_canvas_seed_has_no_network_or_live_data(self):
        source = (ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx").read_text()
        self.assertNotIn("fetch(", source)
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)
        self.assertIn("contains no repository data", source)

    def test_generated_canvas_inlines_one_revision_bound_snapshot(self):
        snapshot = render_repo_snapshot(
            self.fixture.repo,
            generated_at="2026-09-02T12:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "roadmap.canvas.tsx"
            seed = ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
            first = generate_canvas(seed, target, snapshot)
            second = generate_canvas(seed, target, snapshot)
            self.assertEqual(first, second)
            self.assertIn(snapshot["source_revision"].encode(), first)
            self.assertIn(snapshot["generated_at"].encode(), first)
            self.assertNotIn(b"fetch(", first)

    def test_canvas_refresh_invokes_read_only_engine_or_chat_fallback(self):
        generated_at = "2026-09-02T12:00:00Z"
        calls = []

        def bridge(scope, repo, observed_at):
            calls.append((scope, repo, observed_at))
            return render_repo_snapshot(
                repo,
                generated_at=observed_at,
            )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "roadmap.canvas.tsx"
            seed = ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
            refreshed = refresh_canvas(
                seed,
                target,
                scope="repo",
                repo=self.fixture.repo,
                generated_at=generated_at,
                bridge=bridge,
            )
            self.assertEqual(
                calls,
                [("repo", self.fixture.repo, generated_at)],
            )
            self.assertEqual(refreshed["status"], "refreshed")
            self.assertEqual(refreshed["mode"], "read_only_bridge")
            self.assertEqual(refreshed["repository_writes"], [])
            self.assertIn(generated_at, target.read_text(encoding="utf-8"))

            fallback_target = Path(directory) / "fallback.canvas.tsx"
            fallback = refresh_canvas(
                seed,
                fallback_target,
                scope="fleet",
                repo=self.fixture.repo,
                generated_at=generated_at,
                bridge=None,
            )
            self.assertEqual(fallback["status"], "chat_fallback")
            self.assertEqual(
                fallback["chat_action"]["type"],
                "newComposerChat",
            )
            self.assertIn(
                "refresh the read-only doc-warden fleet roadmap",
                fallback["chat_action"]["userPrompt"].lower(),
            )
            self.assertFalse(fallback_target.exists())

    def test_canvas_refresh_contract_is_read_only_and_cli_bound(self):
        bridged = canvas_refresh_contract("repo", bridge_available=True)
        self.assertTrue(bridged["read_only"])
        self.assertEqual(bridged["repository_writes"], [])
        self.assertEqual(bridged["mode"], "read_only_bridge")
        self.assertIn("view repo", bridged["command"])
        self.assertNotIn("apply", bridged["command"])

        fallback = canvas_refresh_contract("fleet", bridge_available=False)
        self.assertEqual(fallback["mode"], "chat_fallback")
        self.assertEqual(
            fallback["chat_action"]["type"],
            "newComposerChat",
        )

    def test_tracked_canvas_refresh_dispatches_supported_chat_action(self):
        source = (
            ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
        ).read_text(encoding="utf-8")
        refresh_handler = source.split(
            "const requestRefresh", 1
        )[1].split("const managePrompt", 1)[0]
        self.assertNotIn("docWarden.refreshRequest", source)
        self.assertNotIn("setRefreshRequest", refresh_handler)
        self.assertNotIn("refresh_bridge_available", refresh_handler)
        self.assertNotIn("refresh_bridge_available", source)
        self.assertIn("dispatch({", refresh_handler)
        self.assertIn('type: "newComposerChat"', refresh_handler)
        self.assertIn("bash _ops/bin/doc-warden.sh view", source)
        self.assertIn("report that refresh is unavailable", source)
        for forbidden in ("fetch(", "XMLHttpRequest", "child_process", "writeFile("):
            self.assertNotIn(forbidden, source)

    def test_fleet_canvas_seed_designated_path_allows_null(self):
        """Regression: FleetRepository.designated_path must be string|null.

        inventory.py designates None when a checkout is unavailable; render.py
        serialises that as JSON null.  The Canvas seed TypeScript type must
        therefore declare ``designated_path?: string | null`` so that generated
        fleet snapshots type-check without TS2322 errors.
        """
        import re

        source = (ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx").read_text(
            encoding="utf-8"
        )
        match = re.search(r"type FleetRepository = \{([^}]+)\}", source)
        self.assertIsNotNone(match, "FleetRepository type not found in canvas seed")
        block = match.group(0)
        dp_line = next(
            (l.strip() for l in block.splitlines() if "designated_path" in l),
            None,
        )
        self.assertIsNotNone(dp_line, "designated_path field not found in FleetRepository")
        self.assertIn(
            "| null",
            dp_line,
            f"designated_path must allow null (fleet rows with unavailable checkouts "
            f"serialise null); got: {dp_line!r}",
        )

    def test_fleet_canvas_generation_accepts_null_designated_path(self):
        """Regression: generate_canvas must succeed and preserve null designated_path.

        Valid fleet rows have designated_path=null when a checkout is unavailable.
        The generated Canvas file must contain the JSON null literal so the IDE
        type-checker resolves it against the ``string | null`` union without TS2322.
        """
        from doc_warden.inventory import CheckoutObservation, deduplicate_observations

        rows = deduplicate_observations(
            [
                CheckoutObservation(
                    "KleinPerkins/example",
                    42,
                    None,
                    False,
                    "checkout_unavailable_from_selected_worktree",
                    "KleinPerkins",
                    "open_or_locate_checkout",
                )
            ]
        )
        self.assertIsNone(
            rows[0].designated_path,
            "Test pre-condition: unavailable row must have null designated_path",
        )
        snapshot = render_fleet_snapshot(
            rows,
            source_revision="b" * 40,
            source_observed_at="2026-09-04T00:00:00Z",
            generated_at="2026-09-04T00:00:00Z",
        )
        self.assertIsNone(snapshot["repositories"][0]["designated_path"])
        with tempfile.TemporaryDirectory() as directory:
            seed = ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
            target = Path(directory) / "fleet-roadmap.canvas.tsx"
            output = generate_canvas(seed, target, snapshot)
            # The serialised null must appear verbatim in the generated canvas
            self.assertIn(
                b'"designated_path":null',
                output,
                "null designated_path must be preserved verbatim in generated canvas",
            )

    def test_malformed_roadmap_renders_blocked_snapshot(self):
        (self.fixture.repo / ".planning/ROADMAP.md").write_text("not a roadmap")
        snapshot = render_repo_snapshot(self.fixture.repo)
        self.assertEqual(snapshot["migration_status"], "blocked")
        self.assertEqual(snapshot["items"], [])

    def test_snapshot_preserves_config_and_roadmap_failures(self):
        (self.fixture.repo / ".planning/doc-warden.json").write_text("{invalid")
        (self.fixture.repo / ".planning/ROADMAP.md").write_text("not a roadmap")
        snapshot = render_repo_snapshot(self.fixture.repo)
        self.assertIn("repository_key_unreadable", snapshot["reason"])
        self.assertIn("roadmap markers invalid", snapshot["reason"])


class FleetCanvasTruthfulnessTests(unittest.TestCase):
    """M3-T02 adjudicated narrow remediation: fleet Canvas truthfulness / plain language.

    Each test maps to one of the seven adjudicated invariants. Written red-first; the
    Canvas seed was then corrected to make them pass. They exist to prevent regression.
    """

    SEED = ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"

    @classmethod
    def setUpClass(cls):
        cls.source = cls.SEED.read_text(encoding="utf-8")
        cls.lower = cls.source.lower()

    def _fleet_rows_block(self) -> str:
        """Return the content of the fleetRows variable definition."""
        parts = self.source.split("const fleetRows", 1)
        self.assertEqual(len(parts), 2, "Canvas must define a fleetRows variable")
        return parts[1].split("]);", 1)[0]

    def test_fleet_canvas_identifies_as_registry_catalog_scoped(self):
        """Invariant 1: Canvas plainly identifies itself as registry/catalog-scoped."""
        self.assertIn(
            "registry",
            self.lower,
            "Canvas must contain 'registry' to identify the catalog source authority",
        )
        self.assertIn(
            "catalog",
            self.lower,
            "Canvas must contain 'catalog' to label the fleet projection scope",
        )
        self.assertIn(
            "not live checkout discovery",
            self.lower,
            "Canvas must explicitly state it is not live checkout discovery",
        )

    def test_fleet_canvas_available_not_labeled_existentially(self):
        """Invariant 2: available must be session-observed language, not existential."""
        self.assertNotIn(
            '"Available"',
            self.source,
            "Existential 'Available' label must not appear in Canvas source",
        )
        self.assertNotIn(
            '"Unavailable"',
            self.source,
            "Existential 'Unavailable' label must not appear in Canvas source",
        )
        self.assertIn(
            "observed in this session",
            self.lower,
            "Canvas must use session-scoped 'observed in this session' language",
        )

    def test_fleet_canvas_reason_codes_are_translated_to_prose(self):
        """Invariant 3: Internal snake_case reason codes converted to operator prose."""
        # Known codes must appear as translation-map keys, not raw rendered values.
        self.assertIn(
            "checkout_unavailable_from_selected_worktree",
            self.source,
            "Seed must contain a label-mapping entry for checkout_unavailable reason code",
        )
        self.assertIn(
            "open_or_locate_checkout",
            self.source,
            "Seed must contain a label-mapping entry for open_or_locate_checkout action code",
        )
        rows_def = self._fleet_rows_block()
        self.assertNotIn(
            "repository.reason,",
            rows_def,
            "fleetRows must not pass repository.reason directly as a raw cell value",
        )
        self.assertRegex(
            rows_def,
            r"label\w*\(\s*repository\.reason",
            "fleetRows must call a translation function on repository.reason",
        )

    def test_fleet_canvas_renders_reason_and_next_action_in_separate_columns(self):
        """Invariant 4: Reason and Next action are separate columns; next_action in latter."""
        self.assertIn(
            '"Reason"',
            self.source,
            "Fleet table must have a 'Reason' column header",
        )
        rows_def = self._fleet_rows_block()
        self.assertNotIn(
            "reason ??",
            rows_def,
            "fleetRows must not use reason ?? next_action conflated anti-pattern",
        )
        self.assertRegex(
            rows_def,
            r"next_action",
            "fleetRows must reference next_action for the Next action column",
        )

    def test_fleet_canvas_does_not_present_checkout_as_live_observation(self):
        """Invariant 5: Synthetic checkout_count must not be implied as live topology."""
        rows_def = self._fleet_rows_block()
        self.assertNotIn(
            "checkout_count",
            rows_def,
            "fleetRows must not render checkout_count as a cell value",
        )
        self.assertNotIn(
            '"Checkout"',
            self.source,
            "Fleet table must not use 'Checkout' as a column header (implies live observation)",
        )

    def test_fleet_canvas_distinguishes_catalog_targets_from_exclusions(self):
        """Invariant 6: Active catalog targets and explicit exclusions are visually distinct."""
        self.assertIn(
            "explicit exclusion",
            self.lower,
            "Canvas must use 'explicit exclusion' label to distinguish excluded repos",
        )
        rows_def = self._fleet_rows_block()
        self.assertTrue(
            "repository_id" in rows_def or "catalogScope" in rows_def,
            "fleetRows must distinguish catalog targets from exclusions via repository_id",
        )

    def test_fleet_canvas_uses_catalog_scoped_revision_labels(self):
        """Invariant 7: Fleet revision/time labels convey catalog scope, not live data."""
        self.assertTrue(
            any(pat in self.lower for pat in ("catalog at", "catalog observed")),
            "Canvas must use catalog-qualified time/revision labels for fleet mode "
            "(expected 'catalog at' or 'catalog observed')",
        )

    def test_generated_fleet_canvas_has_no_existential_availability_labels(self):
        """End-to-end: generated Canvas output proves no misleading availability strings."""
        rows = deduplicate_observations(
            [
                CheckoutObservation(
                    "KleinPerkins/example",
                    42,
                    None,
                    False,
                    "checkout_unavailable_from_selected_worktree",
                    "KleinPerkins",
                    "open_or_locate_checkout",
                )
            ]
        )
        snapshot = render_fleet_snapshot(
            rows,
            source_revision="d" * 40,
            source_observed_at="2026-09-04T00:00:00Z",
            generated_at="2026-09-04T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            seed = ROOT / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
            target = Path(directory) / "fleet.canvas.tsx"
            output = generate_canvas(seed, target, snapshot)
            text = output.decode("utf-8")
            self.assertNotIn(
                '"Available"',
                text,
                "Generated Canvas must not contain existential 'Available' string literal",
            )
            self.assertNotIn(
                '"Unavailable"',
                text,
                "Generated Canvas must not contain existential 'Unavailable' string literal",
            )
            self.assertNotIn(
                '? "Available"',
                text,
                "Generated Canvas must not contain ternary 'Available' label expression",
            )


    def test_governance_column_does_not_derive_from_mutation_eligible(self):
        """M3-T02 fix: Governance column must not use mutation_eligible (a session-observation axis).

        mutation_eligible reflects whether this agent session can mutate the repo.
        That is independent of whether the repo is a genuine governed registry target.
        An unobserved/unavailable genuine target must still be labeled 'Governance target'.
        """
        rows_def = self._fleet_rows_block()
        self.assertNotIn(
            "mutation_eligible",
            rows_def,
            "Governance column must not derive from mutation_eligible; "
            "session mutation eligibility is orthogonal to catalog governance status",
        )

    def test_genuine_registry_target_is_labeled_governance_target(self):
        """M3-T02 fix: Genuine registry target (repository_id != null) must show 'Governance target'.

        A repo in the governed fleet catalog must show 'Governance target' in the Governance
        column regardless of session availability or mutation eligibility.  'Observe only'
        must not appear as a governance classification in fleetRows.
        """
        self.assertIn(
            '"Governance target"',
            self.source,
            "Canvas must contain 'Governance target' label string for genuine registry targets",
        )
        rows_def = self._fleet_rows_block()
        self.assertNotIn(
            '"Observe only"',
            rows_def,
            "'Observe only' must not appear as a governance classification in fleetRows; "
            "it conflated session observation with catalog governance status",
        )

    def test_explicit_exclusion_governance_label_preserved_in_fleet_rows(self):
        """M3-T02 fix: Non-catalog repos (repository_id == null) remain labeled 'Explicit exclusion'.

        Exclusions are visibly distinct from genuine governance targets.  The distinction
        must appear in the fleetRows block, not only in the catalogScope helper.
        """
        rows_def = self._fleet_rows_block()
        self.assertIn(
            '"Explicit exclusion"',
            rows_def,
            "Governance column must label repository_id==null non-docs entries as "
            "'Explicit exclusion' directly in the fleetRows mapping",
        )

    # --- M3-T02 UAT legend tests ---

    def test_legend_section_present_in_canvas(self):
        """M3-T02 UAT: 'How to read this view' legend is visible in the Canvas artifact.

        The legend must appear in the tracked Canvas source so a non-technical operator
        can read governance nomenclature directly from the canvas — not only in chat.
        """
        self.assertIn(
            "How to read this view",
            self.source,
            "Canvas must contain a 'How to read this view' legend section",
        )

    def test_governance_target_definition_excludes_authorization_claim(self):
        """M3-T02 UAT: Governance target legend entry must include not-proof/not-authorization caveat.

        Being a governance target in the registry does NOT mean the repo is checked out
        locally and does NOT authorize the agent to write to it.
        """
        self.assertTrue(
            "not proof" in self.lower or "not permission" in self.lower,
            "Legend must include a 'not proof' or 'not permission' caveat in the "
            "Governance target definition",
        )

    def test_legend_session_observation_is_not_live_inventory(self):
        """M3-T02 UAT: Legend must state session observation is not a fleet-wide live inventory.

        The canvas is a session-level snapshot, not a live topology view. M5 is
        deferred; the legend must not over-claim live fleet discovery.
        """
        self.assertTrue(
            "session-level snapshot" in self.lower
            or "not a fleet-wide" in self.lower,
            "Legend must state 'session-level snapshot' or 'not a fleet-wide live inventory' "
            "to distinguish session observation from M5 live inventory",
        )

    def test_legend_next_action_is_proposal_not_executed(self):
        """M3-T02 UAT: Next action legend entry must say it is a proposal, not an executed action.

        Next action is a routing recommendation back through chat / validated CLI.
        It must not imply the action has already been taken or is auto-authorized.
        """
        self.assertIn(
            "proposal",
            self.lower,
            "Legend must define Next action as a proposal",
        )
        self.assertTrue(
            "not an action already" in self.lower
            or "not automatic authorization" in self.lower,
            "Legend must clarify Next action is 'not an action already taken' or "
            "'not automatic authorization to execute'",
        )


if __name__ == "__main__":
    unittest.main()
