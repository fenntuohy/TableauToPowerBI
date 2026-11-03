"""Tests for the source-vs-output loss report (powerbi_import/loss_report.py)."""

import json
import os
import shutil
import tempfile
import unittest
import zipfile

from powerbi_import.loss_report import (
    build_loss_report,
    count_output,
    count_source,
)

TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook>
  <datasources>
    <datasource name='ds1'>
      <connection class='hyper' />
      <column name='[Calc A]' role='measure'>
        <calculation class='tableau' formula='SUM([x])' />
      </column>
      <column name='[Bin]' role='dimension'>
        <calculation class='categorical-bin' />
      </column>
      <column name='[Param]' param-domain-type='list' />
      <relation type='join' join='inner' name='T1' />
      <relation type='join' join='left' name='T2' />
    </datasource>
  </datasources>
  <worksheets><worksheet name='W1' /><worksheet name='W2' /></worksheets>
  <dashboards><dashboard name='D1' /></dashboards>
  <filter column='[x]' />
</workbook>
"""


def _write_project(root, name, *, measures=0, relations=0, visuals=0,
                   degradations=None, hyper=0, params=0, filters=0):
    proj = os.path.join(root, name)
    sm = os.path.join(proj, f"{name}.SemanticModel", "definition")
    rpt = os.path.join(proj, f"{name}.Report", "definition", "pages", "p1")
    os.makedirs(os.path.join(sm, "tables"))
    os.makedirs(os.path.join(rpt, "visuals"))
    with open(os.path.join(proj, f"{name}.pbip"), "w") as fh:
        fh.write("{}")
    with open(os.path.join(sm, "tables", "T.tmdl"), "w") as fh:
        # Measure names must match a source calc caption to count as a calc.
        names = ["Calc A"] if measures else []
        fh.write("table T\n" + "".join(f"\tmeasure '{n}' = 1\n" for n in names))
    if relations:
        with open(os.path.join(sm, "relationships.tmdl"), "w") as fh:
            fh.write("\n".join(f"relationship r{i}" for i in range(relations)))
    for i in range(visuals):
        vdir = os.path.join(rpt, "visuals", f"v{i}")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "visual.json"), "w") as fh:
            json.dump({"visual": {"visualType": "clusteredBarChart"}}, fh)
    with open(os.path.join(rpt, "page.json"), "w") as fh:
        fh.write("{}")
    meta = {
        "calc_captions": ["Calc A"],
        "objects_converted": {"parameters": params, "filters": filters},
        "hyper_extracts": [f"h{i}" for i in range(hyper)],
        "degradations": degradations or {},
    }
    with open(os.path.join(proj, "migration_metadata.json"), "w") as fh:
        json.dump(meta, fh)
    return proj


class TestCountSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.twb = os.path.join(self.tmp, "wb.twb")
        with open(self.twb, "w") as fh:
            fh.write(TWB)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_match_the_xml(self):
        c = count_source(self.twb)
        self.assertEqual(c["worksheets"], 2)
        self.assertEqual(c["dashboards"], 1)
        self.assertEqual(c["relations"], 2)
        self.assertEqual(c["hyper_extracts"], 1)
        self.assertEqual(c["filters"], 1)

    def test_single_table_binding_is_not_a_relation(self):
        # <relation type='table'> binds one table to a connection; it is not a
        # join. Counting it made single-table workbooks look like they had lost
        # their relationships.
        xml = ("<workbook><datasources><datasource>"
               "<relation type='table' name='Only' table='[s].[t]' />"
               "</datasource></datasources></workbook>")
        path = os.path.join(self.tmp, "single.twb")
        with open(path, "w") as fh:
            fh.write(xml)
        self.assertEqual(count_source(path)["relations"], 0)

    def test_bins_are_not_calculated_fields(self):
        # The categorical bin is a group, not a calc. Only "Calc A" counts.
        self.assertEqual(count_source(self.twb)["calculated_fields"], 1)

    def test_twbx_is_read_through_the_archive(self):
        twbx = os.path.join(self.tmp, "wb.twbx")
        with zipfile.ZipFile(twbx, "w") as zf:
            zf.writestr("wb.twb", TWB)
        report = build_loss_report(twbx, os.path.join(self.tmp, "missing"))
        self.assertNotEqual(report["status"], "not_run")


class TestBuildLossReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.twb = os.path.join(self.tmp, "wb.twb")
        with open(self.twb, "w") as fh:
            fh.write(TWB)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _row(self, report, key):
        return next(r for r in report["rows"] if r["object"] == key)

    def test_unexplained_relation_loss_fails(self):
        proj = _write_project(self.tmp, "wb", relations=0, hyper=1,
                              measures=1, visuals=2, params=1, filters=1)
        report = build_loss_report(self.twb, proj)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(self._row(report, "relations")["status"], "fail")

    def test_drop_explained_by_degradation_is_warn_not_fail(self):
        proj = _write_project(
            self.tmp, "wb", relations=0, hyper=1, measures=1, visuals=2,
            filters=1, params=1,
            degradations={"relations_not_mapped": ["T1", "T2"],
                          "hyper_unread": ["h.hyper"]})
        report = build_loss_report(self.twb, proj)
        self.assertEqual(self._row(report, "relations")["status"], "warn")
        self.assertEqual(report["unexplained_drops"], 0)

    def test_no_loss_passes(self):
        proj = _write_project(self.tmp, "wb", relations=2, hyper=1,
                              measures=1, visuals=2, filters=1, params=1)
        report = build_loss_report(self.twb, proj)
        self.assertEqual(report["unexplained_drops"], 0)

    def test_unreadable_source_is_not_run_not_fail(self):
        report = build_loss_report(os.path.join(self.tmp, "nope.twb"), self.tmp)
        self.assertEqual(report["status"], "not_run")


if __name__ == "__main__":
    unittest.main()


class TestDuplicateCalcsAreCountedOnce(unittest.TestCase):
    """Tableau repeats a calc across datasource views. Entries overstate the source."""

    def test_repeated_calc_counts_as_one(self):
        xml = ("<workbook><datasources><datasource>"
               "<column name='[A]' caption='Avg' role='measure'>"
               "<calculation class='tableau' formula='AVG([x])' /></column>"
               "<column name='[A]' caption='Avg' role='measure'>"
               "<calculation class='tableau' formula='AVG([x])' /></column>"
               "<column name='[B]' caption='Tot' role='measure'>"
               "<calculation class='tableau' formula='SUM([x])' /></column>"
               "</datasource></datasources></workbook>")
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "dup.twb")
            with open(path, "w") as fh:
                fh.write(xml)
            self.assertEqual(count_source(path)["calculated_fields"], 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
