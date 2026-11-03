"""Placeholder M partitions are detected by content markers, never by length.

A length rule ("76 chars or less is a stub") flags legitimate short queries and
misses a long placeholder. These tests pin the marker behaviour.
"""

import unittest

from powerbi_import.openability import _m_stub_problems


class TestStubMarkers(unittest.TestCase):
    def test_todo_marker_is_a_stub(self):
        m = ('let\n    // TODO: Replace with actual data source or imported CSV.\n'
             '    Source = #table({"a"}, {{1}})\nin\n    Source')
        self.assertTrue(_m_stub_problems(m))

    def test_empty_row_table_is_a_stub(self):
        m = 'let\n    Source = #table({"a", "b"}, {})\nin\n    Source'
        self.assertTrue(_m_stub_problems(m))

    def test_real_source_is_not_a_stub(self):
        m = ('let\n    Source = Snowflake.Databases("h", "w"),\n'
             '    Data = Source{[Name="DB"]}[Data]\nin\n    Data')
        self.assertEqual(_m_stub_problems(m), [])

    def test_short_real_table_is_not_a_stub(self):
        # Short on purpose: a length rule would wrongly flag this.
        m = 'let\n    Source = #table({"v"}, {{"On"}, {"Off"}})\nin\n    Source'
        self.assertLess(len(m), 80)
        self.assertEqual(_m_stub_problems(m), [])

    def test_long_placeholder_is_still_a_stub(self):
        # Long, so a length rule would miss it. The marker still catches it.
        filler = "".join(f'    step{i} = Text.From({i}),\n' for i in range(30))
        m = ('let\n    // TODO: Replace with actual data source\n' + filler +
             '    Source = #table({"a"}, {})\nin\n    Source')
        self.assertGreater(len(m), 500)
        self.assertTrue(_m_stub_problems(m))


if __name__ == "__main__":
    unittest.main()
