"""Visual field coverage must match Tableau names to the names the model uses.

Regression for a checker bug: raw Tableau names (TOTAL_EVENTS, Calculation_123)
never matched the model's humanised columns and captioned measures, so real
bindings were reported as 0% coverage.
"""

import unittest

from powerbi_import.equivalence_tester_v2 import (
    EquivalenceTester,
    _humanise_field,
    _resolve_model_name,
)


class TestHumanise(unittest.TestCase):
    def test_underscores_become_title_case_words(self):
        self.assertEqual(_humanise_field("TOTAL_EVENTS"), "Total Events")
        self.assertEqual(_humanise_field("COMMUNICATION_EVENT_YEAR"),
                         "Communication Event Year")


class TestResolve(unittest.TestCase):
    MODEL = {"Total Events", "GCID rate ", "GCID Drop Rate"}

    def test_humanised_column_resolves(self):
        self.assertEqual(_resolve_model_name("TOTAL_EVENTS", self.MODEL, {}),
                         "Total Events")

    def test_internal_calc_resolves_to_caption_with_trailing_space(self):
        captions = {"Calculation_6572722220192714753": "GCID rate "}
        self.assertEqual(
            _resolve_model_name("Calculation_6572722220192714753",
                                self.MODEL, captions),
            "GCID rate ")

    def test_unknown_field_is_left_unresolved(self):
        self.assertEqual(_resolve_model_name("NOPE", self.MODEL, {}), "NOPE")


class TestCoverageIsNotInflated(unittest.TestCase):
    """Each field counts once. A double-counted denominator understated coverage."""

    def test_full_coverage_reports_100(self):
        fields = {"TOTAL_EVENTS", "SOURCE_SYSTEM_NAME"}
        model = {"Total Events", "Source System Name"}
        resolved = {_resolve_model_name(f, model, {}) for f in fields}
        _, coverage = EquivalenceTester().test_visual_field_coverage(
            resolved, model, "ws")
        self.assertEqual(coverage, 100.0)

    def test_a_genuinely_missing_field_still_fails(self):
        fields = {"TOTAL_EVENTS", "MISSING_COL"}
        model = {"Total Events"}
        resolved = {_resolve_model_name(f, model, {}) for f in fields}
        passed, coverage = EquivalenceTester().test_visual_field_coverage(
            resolved, model, "ws")
        self.assertFalse(passed)
        self.assertEqual(coverage, 50.0)


if __name__ == "__main__":
    unittest.main()
