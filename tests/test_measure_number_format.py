"""A measure must carry the number format Tableau gave its calculation.

Tableau stores a calculation's display format on its declaring column as
``default-format``.  The converter ignored it for measures and used the
datatype default instead, so a rate declared ``p0.0%`` shipped as ``#,0.00``
and Power BI rendered 0.0534 instead of 5.3%.

``p`` and ``n`` are Tableau's own format-category prefixes, not Power BI
specifiers; passing them through unchanged yields an invalid format string.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tableau_export'))

from powerbi_import.tmdl_generator import (_convert_tableau_format_to_pbi,
                                           _build_table)

CSV_CONNECTION = {'type': 'csv', 'filename': 'sales.csv'}


class TestTableauFormatTranslation(unittest.TestCase):

    def test_a_percent_prefix_is_dropped(self):
        self.assertEqual(_convert_tableau_format_to_pbi('p0.0%'), '0.0%')

    def test_a_percent_prefix_without_decimals(self):
        self.assertEqual(_convert_tableau_format_to_pbi('p0%'), '0%')

    def test_a_negative_section_carries_the_prefix_too(self):
        self.assertEqual(_convert_tableau_format_to_pbi('p0.0%;-p0.0%'),
                         '0.0%;-0.0%')

    def test_a_thousands_prefix_is_dropped(self):
        self.assertEqual(_convert_tableau_format_to_pbi('n#,##0,.0K'),
                         '#,0,.0K')

    def test_an_already_valid_pbi_format_is_unchanged(self):
        for fmt in ('0.0%', '#,0.00', '0', '$#,0'):
            with self.subTest(fmt=fmt):
                self.assertEqual(_convert_tableau_format_to_pbi(fmt), fmt)


def _table_with_rate(default_format):
    calculations = [{
        'name': '[Calculation_1]',
        'caption': 'GCID Drop Rate',
        'formula': 'SUM([NON_NULL_GCID_EVENTS]) / SUM([TOTAL_EVENTS])',
        'datatype': 'real',
        'role': 'measure',
    }]
    columns = [{'name': 'NON_NULL_GCID_EVENTS', 'datatype': 'integer'},
               {'name': 'TOTAL_EVENTS', 'datatype': 'integer'}]
    # Datasource column metadata is keyed by the Tableau declaration name,
    # brackets included.
    metadata = {
        'NON_NULL_GCID_EVENTS': {'datatype': 'integer'},
        'TOTAL_EVENTS': {'datatype': 'integer'},
        '[Calculation_1]': {'datatype': 'real',
                            'default_format': default_format},
    }
    return _build_table({'name': 'Sales', 'columns': columns}, CSV_CONNECTION,
                        calculations, [], {}, metadata, {})


def _measure(table, name):
    return next(m for m in table['measures'] if m['name'] == name)


class TestMeasureCarriesTableauFormat(unittest.TestCase):

    def test_a_percent_calculation_keeps_its_percent_format(self):
        table = _table_with_rate('p0.0%')
        self.assertEqual(_measure(table, 'GCID Drop Rate')['formatString'],
                         '0.0%')

    def test_without_a_tableau_format_the_datatype_default_applies(self):
        table = _table_with_rate('')
        self.assertEqual(_measure(table, 'GCID Drop Rate')['formatString'],
                         '#,0.00')


if __name__ == '__main__':
    unittest.main()
