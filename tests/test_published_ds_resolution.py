"""
Tests for Published Datasource Resolution (datasource_extractor — Sprint 167 caching).
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tableau_export'))

from tableau_export.datasource_extractor import (
    resolve_published_datasource,
    cache_published_datasource,
    load_cached_datasource,
    clear_ds_cache,
    resolve_published_datasource_cached,
    resolve_all_published,
    _ds_cache_key,
)


# ── Fixtures ────────────────────────────────────────────────────────

def _sqlproxy_ds(name='SalesDB'):
    """Create a minimal published (sqlproxy) datasource dict."""
    return {
        'name': name,
        'connection': {
            'type': 'Tableau Server',
            'details': {
                'server_ds_name': name,
            },
        },
        'tables': [],
        'columns': [],
    }


def _regular_ds():
    """Create a non-published datasource dict."""
    return {
        'name': 'LocalDB',
        'connection': {
            'type': 'sqlserver',
            'details': {'server': 'localhost'},
        },
        'tables': [{'name': 'Orders'}],
        'columns': [{'name': 'OrderID', 'datatype': 'integer'}],
    }


class TestDsCacheKey(unittest.TestCase):

    def test_produces_string(self):
        key = _ds_cache_key('Sales Data')
        self.assertIsInstance(key, str)
        self.assertIn('Sales_Data', key)

    def test_consistent(self):
        k1 = _ds_cache_key('Test')
        k2 = _ds_cache_key('Test')
        self.assertEqual(k1, k2)

    def test_different_for_different_names(self):
        k1 = _ds_cache_key('Alpha')
        k2 = _ds_cache_key('Beta')
        self.assertNotEqual(k1, k2)


class TestCachePublishedDatasource(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_caches_datasource(self):
        ds = _sqlproxy_ds()
        ds['tables'] = [{'name': 'Sales'}]
        ds['columns'] = [{'name': 'Revenue'}]
        path = cache_published_datasource(ds, self.tmpdir)
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            cached = json.load(f)
        self.assertEqual(cached['name'], 'SalesDB')
        self.assertEqual(len(cached['tables']), 1)


class TestLoadCachedDatasource(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_loads_cached(self):
        ds = _sqlproxy_ds()
        ds['tables'] = [{'name': 'T1'}]
        cache_published_datasource(ds, self.tmpdir)
        loaded = load_cached_datasource('SalesDB', self.tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['name'], 'SalesDB')

    def test_returns_none_if_not_cached(self):
        loaded = load_cached_datasource('NonExistent', self.tmpdir)
        self.assertIsNone(loaded)


class TestClearDsCache(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clears_cache(self):
        ds = _sqlproxy_ds()
        cache_published_datasource(ds, self.tmpdir)
        count = clear_ds_cache(self.tmpdir)
        self.assertEqual(count, 1)
        # Verify it's gone
        loaded = load_cached_datasource('SalesDB', self.tmpdir)
        self.assertIsNone(loaded)

    def test_empty_dir(self):
        count = clear_ds_cache(self.tmpdir)
        self.assertEqual(count, 0)

    def test_nonexistent_dir(self):
        count = clear_ds_cache('/nonexistent_path_for_test')
        self.assertEqual(count, 0)


class TestResolvePublishedDatasourceCached(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_skips_non_sqlproxy(self):
        ds = _regular_ds()
        result = resolve_published_datasource_cached(ds, cache_dir=self.tmpdir)
        self.assertEqual(result['connection']['type'], 'sqlserver')
        self.assertNotIn('_published_unresolved', result)

    def test_uses_cache(self):
        # Pre-populate cache
        cached_ds = _sqlproxy_ds()
        cached_ds['tables'] = [{'name': 'CachedTable'}]
        cached_ds['connection'] = {'type': 'sqlserver', 'details': {'server': 'db.co.com'}}
        cache_published_datasource(cached_ds, self.tmpdir)

        # Now resolve a sqlproxy DS with same name
        ds = _sqlproxy_ds()
        result = resolve_published_datasource_cached(ds, cache_dir=self.tmpdir)
        self.assertTrue(result.get('_published_resolved'))
        self.assertEqual(result.get('_published_source'), 'cache')

    def test_marks_unresolved_without_server(self):
        ds = _sqlproxy_ds()
        result = resolve_published_datasource_cached(ds, server_client=None, cache_dir=None)
        self.assertTrue(result.get('_published_unresolved'))


class TestResolveAllPublished(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bulk_resolution(self):
        # Pre-populate cache for one DS
        cached = _sqlproxy_ds('CachedDS')
        cached['tables'] = [{'name': 'T1'}]
        cached['connection'] = {'type': 'sqlserver', 'details': {}}
        cache_published_datasource(cached, self.tmpdir)

        datasources = [
            _sqlproxy_ds('CachedDS'),
            _sqlproxy_ds('MissingDS'),
            _regular_ds(),
        ]
        result = resolve_all_published(datasources, cache_dir=self.tmpdir)
        self.assertEqual(len(result['cached']), 1)
        self.assertEqual(len(result['unresolved']), 1)

    def test_empty_list(self):
        result = resolve_all_published([])
        self.assertEqual(result['resolved'], [])
        self.assertEqual(result['unresolved'], [])

    def test_embedded_snowflake_sqlproxy_resolves_by_published_parent_name(self):
        with tempfile.NamedTemporaryFile(suffix='.tdsx') as downloaded:
            class Client:
                def list_datasources(self):
                    return [{'id': 'published-luid',
                             'name': 'INT_LOGISTICS_PERFORMANCE_BASE'}]

                def download_datasource(self, datasource_id, output_path):
                    self.asserted_id = datasource_id
                    shutil.copyfile(downloaded.name, output_path)
                    return output_path

            client = Client()
            datasource = {
                'name': 'sqlproxy.embedded-luid',
                'caption': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'connection': {'type': 'Snowflake', 'details': {'database': 'PROD'}},
                'published_datasource_id': 'repository-id',
                'published_datasource_name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'tables': [{'name': 'sqlproxy', 'columns': []}],
                'columns': [],
            }
            published = {
                'connection': {'type': 'Snowflake', 'details': {'database': 'PROD'}},
                'tables': [{'name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                            'source_table': 'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE',
                            'columns': [{'name': 'TRANSFER_ID', 'datatype': 'string'}]}],
                'columns': [{'name': 'TRANSFER_ID'}],
                'relationships': [],
                'connection_map': {},
            }
            with patch('tableau_export.datasource_extractor._parse_published_datasource_file',
                       return_value=published):
                result = resolve_published_datasource_cached(
                    datasource, server_client=client, cache_dir=None)

        self.assertTrue(result.get('_published_resolved'))
        self.assertEqual(client.asserted_id, 'published-luid')
        self.assertEqual(result['tables'][0]['name'], 'INT_LOGISTICS_PERFORMANCE_BASE')
        self.assertEqual(result['tables'][0]['source_table'],
                         'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE')

    def test_published_repository_content_url_matches_site_datasource(self):
        with tempfile.NamedTemporaryFile(suffix='.tdsx') as downloaded:
            class Client:
                def list_datasources(self):
                    return [{'id': 'published-luid', 'name': 'Published caption',
                             'contentUrl': 'INT_LOGISTICS_PERFORMANCE_BASE'}]

                def download_datasource(self, datasource_id, output_path):
                    self.asserted_id = datasource_id
                    shutil.copyfile(downloaded.name, output_path)
                    return output_path

            client = Client()
            datasource = {
                'name': 'sqlproxy.embedded-luid',
                'caption': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'connection': {'type': 'Snowflake', 'details': {}},
                'published_datasource_id': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'published_datasource_name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'tables': [{'name': 'INT_LOGISTICS_PERFORMANCE_BASE', 'columns': []}],
            }
            published = {
                'connection': {'type': 'Snowflake', 'details': {'database': 'PROD'}},
                'tables': [{'name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                            'source_table': 'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE',
                            'columns': [{'name': 'TRANSFER_ID', 'datatype': 'string'}]}],
                'columns': [{'name': 'TRANSFER_ID'}],
                'relationships': [],
                'connection_map': {},
            }
            with patch('tableau_export.datasource_extractor._parse_published_datasource_file',
                       return_value=published):
                result = resolve_published_datasource_cached(
                    datasource, server_client=client, cache_dir=None)

        self.assertTrue(result.get('_published_resolved'))
        self.assertEqual(client.asserted_id, 'published-luid')
        self.assertEqual(result['connection']['details']['database'], 'PROD')
        self.assertEqual(result['tables'][0]['source_table'],
                         'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE')

    def test_published_merge_replaces_sqlproxy_table_with_tds_relation(self):
        with tempfile.NamedTemporaryFile(suffix='.tdsx') as downloaded:
            class Client:
                def list_datasources(self):
                    return [{'id': 'published-luid', 'name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                             'contentUrl': 'INT_LOGISTICS_PERFORMANCE_BASE'}]

                def download_datasource(self, datasource_id, output_path):
                    self.asserted_id = datasource_id
                    shutil.copyfile(downloaded.name, output_path)
                    return output_path

            datasource = {
                'name': 'sqlproxy.embedded-luid',
                'caption': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'connection': {'type': 'Snowflake', 'details': {}},
                'published_datasource_id': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'published_datasource_name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                'tables': [{'name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                            'source_table': 'sqlproxy', 'columns': []}],
                'columns': [],
            }
            published = {
                'connection': {'type': 'Snowflake', 'details': {'database': 'PROD'}},
                'tables': [{'name': 'INT_LOGISTICS_PERFORMANCE_BASE',
                            'source_table': 'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE',
                            'columns': [{'name': 'TRANSFER_ID', 'datatype': 'string'}]}],
                'columns': [{'name': 'TRANSFER_ID'}],
                'relationships': [],
                'connection_map': {},
            }
            client = Client()
            with patch('tableau_export.datasource_extractor._parse_published_datasource_file',
                       return_value=published):
                result = resolve_published_datasource_cached(
                    datasource, server_client=client, cache_dir=None)

        self.assertTrue(result.get('_published_resolved'))
        self.assertEqual(result['tables'][0]['source_table'],
                         'PROD.INTERMEDIATE.INT_LOGISTICS_PERFORMANCE_BASE')
        self.assertEqual(result['tables'][0]['columns'][0]['name'], 'TRANSFER_ID')


if __name__ == '__main__':
    unittest.main()
