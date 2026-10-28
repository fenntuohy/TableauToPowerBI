"""A generated quick-table-calc measure must address the names the model
actually carries.

Tableau names a column TOTAL_EVENTS; a caption renames it to "Total Events".
``retarget_dax_column_refs()`` rewrites converted DAX onto the produced name,
but it ran *before* ``_create_quick_table_calc_measures()`` generated the
"% of Total" measure.  That measure therefore kept the raw Tableau name,
resolved to nothing, and the self-healer fabricated a hidden ``BLANK()``
placeholder column to hide the breakage -- so the visual rendered blank while
refresh reported success.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'tableau_export'))

from powerbi_import.tmdl_generator import _build_semantic_model

DATASOURCE = {
    'name': 'ds',
    'connection': {'type': 'csv', 'filename': 'sales.csv'},
    'tables': [{
        'name': 'Sales',
        'columns': [
            {'name': 'TOTAL_EVENTS', 'datatype': 'integer',
             'caption': 'Total Events', 'role': 'measure'},
            {'name': 'SOURCE_SYSTEM_NAME', 'datatype': 'string',
             'caption': 'Source System Name', 'role': 'dimension'},
        ],
    }],
    'columns': [
        {'name': 'TOTAL_EVENTS', 'caption': 'Total Events',
         'datatype': 'integer', 'role': 'measure'},
        {'name': 'SOURCE_SYSTEM_NAME', 'caption': 'Source System Name',
         'datatype': 'string', 'role': 'dimension'},
    ],
    'calculations': [],
    'relationships': [],
}

WORKSHEETS = [{
    'name': 'GCID Quality',
    'datasource': 'ds',
    'fields': [{'name': 'TOTAL_EVENTS', 'table_calc': 'pcto',
                'table_calc_agg': 'sum', 'datasource': 'ds'}],
}]


def _percent_measure(model):
    for table in model['model']['tables']:
        for measure in table.get('measures', []):
            if measure['name'].startswith('% of Total'):
                return table, measure
    return None, None


class TestGeneratedMeasureUsesProducedName(unittest.TestCase):

    def test_a_generated_measure_addresses_the_produced_column(self):
        model = _build_semantic_model(
            [DATASOURCE], 'R', {'_worksheets': WORKSHEETS})
        _table, measure = _percent_measure(model)
        self.assertIsNotNone(measure, 'no % of Total measure was generated')
        self.assertIn('Total Events', measure['expression'])
        self.assertNotIn('[TOTAL_EVENTS]', measure['expression'])

    def test_no_placeholder_column_is_fabricated_for_it(self):
        model = _build_semantic_model(
            [DATASOURCE], 'R', {'_worksheets': WORKSHEETS})
        table, _measure = _percent_measure(model)
        names = {c.get('name') for c in table.get('columns', [])}
        self.assertNotIn('TOTAL_EVENTS', names)


if __name__ == '__main__':
    unittest.main()
