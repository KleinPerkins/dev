import unittest

from doc_warden.rigor import RigorSignals, compute_rigor, hotfix_exemption


class RigorTests(unittest.TestCase):
    def test_hotfix_exemption_requires_all_five_conditions(self):
        valid = RigorSignals(
            change_kind="defect",
            restores_approved_behavior=True,
            bounded_components=True,
            no_new_journey_or_contract=True,
            complete_defect_record=True,
            reversible=True,
        )
        self.assertTrue(hotfix_exemption(valid))
        for field in (
            "restores_approved_behavior",
            "bounded_components",
            "no_new_journey_or_contract",
            "complete_defect_record",
            "reversible",
        ):
            values = valid.__dict__ | {field: False}
            self.assertFalse(hotfix_exemption(RigorSignals(**values)), field)

    def test_scope_growth_promotes_defect_to_feature(self):
        decision = compute_rigor(
            RigorSignals(
                change_kind="defect",
                repositories=2,
                restores_approved_behavior=True,
            )
        )
        self.assertEqual(decision.base_class, "foundational_cross_repo")
        self.assertFalse(decision.defect_exempt)

    def test_visible_restoration_remains_valid_hotfix_exemption(self):
        decision = compute_rigor(
            RigorSignals(
                change_kind="defect",
                user_visible=True,
                restores_approved_behavior=True,
            )
        )
        self.assertEqual(decision.base_class, "hotfix_defect")
        self.assertTrue(decision.defect_exempt)

    def test_ui_signal_always_requires_ux_design_visual_uat(self):
        decision = compute_rigor(RigorSignals(ui_visual=True))
        self.assertEqual(decision.dimensions, ("ui_visual",))
        self.assertTrue(
            {"uxr", "design", "visual_asset", "accessibility", "responsive", "visual_uat"}
            <= set(decision.required_artifacts)
        )

    def test_sensitive_dimension_stacks_on_base_class(self):
        decision = compute_rigor(RigorSignals(new_user_value=True, sensitive=True))
        self.assertEqual(decision.base_class, "standard_feature")
        self.assertEqual(decision.dimensions, ("sensitive",))
        self.assertIn("security_verification", decision.required_artifacts)

    def test_all_six_base_classes_are_explainable(self):
        cases = (
            (RigorSignals(), "trivial_maintenance"),
            (
                RigorSignals(
                    change_kind="defect",
                    restores_approved_behavior=True,
                ),
                "hotfix_defect",
            ),
            (RigorSignals(user_visible=True), "small_change"),
            (RigorSignals(new_user_value=True), "standard_feature"),
            (RigorSignals(sessions=2), "multi_session_cross_component"),
            (RigorSignals(repositories=2), "foundational_cross_repo"),
        )
        for signals, expected in cases:
            decision = compute_rigor(signals)
            self.assertEqual(decision.base_class, expected)
            self.assertTrue(decision.matched_signals)


if __name__ == "__main__":
    unittest.main()
