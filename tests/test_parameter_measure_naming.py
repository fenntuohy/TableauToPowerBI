"""A date parameter must not produce a measure named "X (X)".

Tableau date parameters (``Current Period`` / ``Previous Period``) reach PBI
as a What-If table *and* a SELECTEDVALUE measure, both named after the
caption.  The cross-table dedupe appended the owning table's name to the
colliding measure, which for these parameters is the same string — yielding
the degenerate ``Current Period (Current Period)``.  That name then leaks
into every DAX reference the Tableau calc emitted.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from powerbi_import.tmdl_generator import _apply_semantic_enrichments


def _model(tables, relationships=None):
    return {"model": {"tables": tables, "relationships": relationships or []},
            "_measure_rename_map": {}}


def _run(model):
    _apply_semantic_enrichments(
        model,
        {"worksheets": [], "calculations": [], "parameters": []},
        "Extract", {}, [])
    return {(t["name"], m["name"]): m["expression"]
            for t in model["model"]["tables"]
            for m in t.get("measures", [])}


class TestParameterMeasureNaming(unittest.TestCase):

    def test_same_named_parameter_table_does_not_produce_x_x(self):
        model = _model([
            {"name": "Extract", "measures": [
                {"name": "Current Period", "expression": "DATE(2026, 10, 28)"},
            ]},
            {"name": "Current Period",
             "columns": [{"name": "Value", "dataType": "dateTime"}],
             "measures": [{
                 "name": "Current Period",
                 "expression": "SELECTEDVALUE('Current Period'[Value], DATE(2026, 10, 28))",
             }]},
        ])
        names = set(_run(model))
        self.assertNotIn(("Current Period", "Current Period (Current Period)"), names)
        self.assertIn(("Current Period", "Current Period (Parameter)"), names)

    def test_distinct_table_collision_still_uses_table_namespace(self):
        # Two genuinely different tables keep the table-name suffix; only the
        # same-name degenerate case switches to the role suffix.
        model = _model([
            {"name": "Sales", "measures": [
                {"name": "Total", "expression": "SUM(Sales[Amount])"},
            ]},
            {"name": "Budget", "measures": [
                {"name": "Total", "expression": "SUM(Budget[Amount])"},
            ]},
        ])
        names = set(_run(model))
        self.assertIn(("Budget", "Total (Budget)"), names)
        self.assertIn(("Sales", "Total"), names)


if __name__ == "__main__":
    unittest.main()
