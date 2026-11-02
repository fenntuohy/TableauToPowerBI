"""An Automatic sheet whose measures all sit on one shelf is a Tableau crosstab.

Tableau draws "Drop Rates" and "Relative Volumes" as text tables: the
dimension is on Rows and every measure is on Rows beside it, separated by
``/``.  The extractor called them ``clusteredBarChart`` because
``_infer_automatic_chart_type`` only asks "are there fields on both shelves?"
and never looks at what the shelves carry -- a dimension plus three
aggregates on Rows and an empty Columns shelf fell through to a bar chart.

What separates a crosstab from a bar chart here is the column-instance type:
a measure placed as ``ordinal`` is printed as text, while the same measure
as ``quantitative`` is drawn on an axis.
"""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tableau_export'))

from extract_tableau_data import TableauExtractor


def _make_extractor():
    d = tempfile.mkdtemp()
    dummy = os.path.join(d, 'dummy.twb')
    with open(dummy, 'w') as f:
        f.write('<workbook/>')
    return TableauExtractor(dummy, output_dir=d)


#: Drop Rates: dimension on Rows, three measures beside it on Rows, no
#: Columns shelf. Measures are ordinal -> Tableau prints them as text.
MEASURE_VALUES_ROWS = '''<worksheet><table>
  <view><datasource-dependencies datasource="ds">
    <column name="[SOURCE_SYSTEM_NAME]" datatype="string"/>
    <column name="[TOTAL_EVENTS]" datatype="integer"/>
    <column name="[Calculation_1]" datatype="real"/>
    <column-instance name="[none:SOURCE_SYSTEM_NAME:nk]" column="[SOURCE_SYSTEM_NAME]" type="nominal"/>
    <column-instance name="[sum:TOTAL_EVENTS:ok]" column="[TOTAL_EVENTS]" type="ordinal"/>
    <column-instance name="[usr:Calculation_1:ok]" column="[Calculation_1]" type="ordinal"/>
  </datasource-dependencies></view>
  <rows>([ds].[none:SOURCE_SYSTEM_NAME:nk] / ([ds].[sum:TOTAL_EVENTS:ok] / [ds].[usr:Calculation_1:ok]))</rows>
  <cols></cols>
  <panes><pane><mark class="Automatic"/></pane></panes>
</table></worksheet>'''


def _chart_type(xml):
    return _make_extractor().determine_chart_type(ET.fromstring(xml))


class TestMeasureValuesOnOneShelfIsACrosstab(unittest.TestCase):

    def test_ordinal_measures_on_rows_with_no_columns_shelf_is_a_table(self):
        self.assertEqual(_chart_type(MEASURE_VALUES_ROWS), 'tableEx')

    def test_quantitative_measure_on_rows_is_still_a_bar_chart(self):
        # Total Events in Tableau is a Bar chart: the measure is quantitative
        # (drawn on an axis) even though it also sits on Rows.
        xml = MEASURE_VALUES_ROWS.replace(
            '[sum:TOTAL_EVENTS:ok]" column="[TOTAL_EVENTS]" type="ordinal"',
            '[sum:TOTAL_EVENTS:qk]" column="[TOTAL_EVENTS]" type="quantitative"'
        ).replace('[ds].[sum:TOTAL_EVENTS:ok]', '[ds].[sum:TOTAL_EVENTS:qk]')
        self.assertEqual(_chart_type(xml), 'clusteredBarChart')

    def test_a_single_ordinal_measure_beside_a_dimension_is_still_a_crosstab(self):
        xml = MEASURE_VALUES_ROWS.replace(
            ' / [ds].[usr:Calculation_1:ok]', '')
        self.assertEqual(_chart_type(xml), 'tableEx')


#: "Default Rec. - Graph" in the Lease Defaults workbook: an explicit Bar
#: mark that also carries a ``Multiple Values`` text encoding (the label on
#: each bar).  The crosstab guard matched the text encoding and demoted a
#: real bar chart to ``tableEx``.
EXPLICIT_BAR_WITH_TEXT_ENCODING = '''<worksheet><table>
  <view><datasource-dependencies datasource="ds">
    <column name="[STATUS_ENTRY_MONTH]" datatype="date"/>
    <column name="[ORDER_NUMBER]" datatype="string"/>
    <column name="[CATEGORISATION]" datatype="string"/>
    <column-instance name="[none:STATUS_ENTRY_MONTH:qk]" column="[STATUS_ENTRY_MONTH]" type="quantitative"/>
    <column-instance name="[none:ORDER_NUMBER:nk]" column="[ORDER_NUMBER]" type="nominal"/>
    <column-instance name="[none:CATEGORISATION:nk]" column="[CATEGORISATION]" type="nominal"/>
  </datasource-dependencies></view>
  <rows>[ds].[none:ORDER_NUMBER:nk]</rows>
  <cols>[ds].[none:STATUS_ENTRY_MONTH:qk]</cols>
  <panes><pane><mark class="Bar"/>
    <encodings>
      <color column="[ds].[none:CATEGORISATION:nk]"/>
      <text column="[ds].[Multiple Values]"/>
    </encodings>
  </pane></panes>
</table></worksheet>'''


class TestExplicitMarkOutranksCrosstabGuards(unittest.TestCase):
    """A non-Automatic mark is Tableau's own statement of the chart family.

    The ``Multiple Values`` text encoding also appears on bar charts (it is
    the label), and ``_has_ordinal_measure_values_signature`` fires whenever
    a measure is printed rather than plotted.  Running those Automatic-only
    guards before the explicit-mark branch turned real bar charts into
    crosstabs.
    """

    def test_explicit_bar_with_multiple_values_encoding_is_not_a_table(self):
        self.assertNotEqual(_chart_type(EXPLICIT_BAR_WITH_TEXT_ENCODING), 'tableEx')

    def test_explicit_bar_keeps_its_bar_family(self):
        # The crosstab guard no longer fires; the dimension sits on Rows, so
        # this stays a horizontal bar chart rather than becoming a table.
        self.assertEqual(_chart_type(EXPLICIT_BAR_WITH_TEXT_ENCODING), 'barChart')

    def test_automatic_with_multiple_values_encoding_is_still_a_crosstab(self):
        xml = EXPLICIT_BAR_WITH_TEXT_ENCODING.replace(
            '<mark class="Bar"/>', '<mark class="Automatic"/>')
        self.assertEqual(_chart_type(xml), 'tableEx')


if __name__ == '__main__':
    unittest.main()
