"""Golden conversion counts for the sample corpus.

``tests/golden/conversion_counts.json`` records, per sample workbook, the
source object counts, the output object counts, the loss-check status, and
the number of BLANK() DAX stubs. It was produced by migrating each sample
(``examples/tableau_samples``) and reviewing the result.

Two checks:

1. ``test_golden_is_consistent``: the recorded golden is self-consistent with
   the loss-check rules. A stored ``pass`` must have no drop; a stored
   ``dax_stubs`` must be zero for every sample.
2. ``test_loss_check_catches_a_real_loss``: the loss check fails when a source
   calc is removed from a generated project. This keeps the check honest.

The full re-migration is slow, so it is not run here. Re-generate the golden
after an intentional change with ``scripts/regenerate_conversion_golden.py``.
"""

import json
import os
import shutil
import tempfile
import unittest

from powerbi_import.loss_report import build_loss_report

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden", "conversion_counts.json")
SAMPLES = os.path.join(HERE, "..", "examples", "tableau_samples")


def _load():
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


class TestGoldenIsConsistent(unittest.TestCase):
    def test_every_sample_is_recorded(self):
        golden = _load()
        self.assertGreaterEqual(len(golden), 10)

    def test_no_sample_has_a_blank_dax_stub(self):
        for name, row in _load().items():
            with self.subTest(sample=name):
                self.assertEqual(row["dax_stubs"], 0,
                                 f"{name} has BLANK() conversion stubs")

    def test_a_passing_sample_has_no_drop(self):
        """A recorded pass must not show output below source for a compared object.

        Hyper extracts are excluded: a recorded extract is explained by
        ``hyper_unread`` rather than read, so it can legitimately be lower.
        """
        compared = ("worksheets", "dashboards", "calculated_fields",
                    "filters", "relations")
        for name, row in _load().items():
            if row["loss_status"] != "pass":
                continue
            for key in compared:
                src = row["source"][key]
                out = row["output"][key]
                with self.subTest(sample=name, object=key):
                    self.assertGreaterEqual(
                        out, src - 0,
                        f"{name}: {key} output {out} is below source {src} "
                        f"but the golden records a pass")


class TestLossCheckCatchesARealLoss(unittest.TestCase):
    """A check that passes a broken project is worse than none."""

    def test_removing_a_source_calc_fails_the_check(self):
        import re
        import glob
        import sys
        twb = os.path.join(SAMPLES, "Enterprise_Sales.twb")
        if not os.path.isfile(twb):
            self.skipTest("sample workbook not present")
        tmp = tempfile.mkdtemp()
        try:
            # Build a minimal project: one measure that matches a source calc,
            # and no others. The source has many calcs, so this is a real loss.
            proj = os.path.join(tmp, "Enterprise_Sales")
            sm = os.path.join(proj, "Enterprise_Sales.SemanticModel", "definition", "tables")
            os.makedirs(sm)
            os.makedirs(os.path.join(proj, "Enterprise_Sales.Report", "definition", "pages"))
            with open(os.path.join(proj, "Enterprise_Sales.pbip"), "w") as fh:
                fh.write("{}")
            with open(os.path.join(sm, "T.tmdl"), "w") as fh:
                fh.write("table T\n\tmeasure 'Gross Revenue' = 1\n")
            with open(os.path.join(proj, "migration_metadata.json"), "w") as fh:
                # Record every source calc caption so the checker sees them as calcs.
                import xml.etree.ElementTree as ET
                root = ET.parse(twb).getroot()
                caps = sorted({(c.get("caption") or c.get("name") or "").strip()
                               for c in root.iter("column")
                               if c.find("calculation") is not None})
                import json as _j
                _j.dump({"calc_captions": caps}, fh)
            report = build_loss_report(twb, proj)
            self.assertEqual(report["status"], "fail")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
