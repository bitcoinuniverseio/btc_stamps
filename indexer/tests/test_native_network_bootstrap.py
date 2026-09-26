"""Metadata isolation tests only; these do not prove protocol acceptance."""
from unittest import TestCase
from unittest.mock import patch, MagicMock

import config
from index_core.database import import_bootstrap_data, initialize_db


class NetworkBootstrapTest(TestCase):
    def test_testnet_never_imports_mainnet_metadata(self):
        with patch.object(config, 'TESTNET', '1'), patch.object(config, 'REGTEST', False):
            with patch('index_core.database.import_csv_data') as importer:
                import_bootstrap_data(None, 'creator.csv', 'https://invalid.example', 'INSERT')
                importer.assert_not_called()

    def test_regtest_never_imports_mainnet_metadata(self):
        with patch.object(config, 'TESTNET', None), patch.object(config, 'REGTEST', True):
            with patch('index_core.database.import_csv_data') as importer:
                import_bootstrap_data(None, 'creator.csv', 'https://invalid.example', 'INSERT')
                importer.assert_not_called()

    def test_mainnet_keeps_existing_local_bootstrap(self):
        with patch.object(config, 'TESTNET', None), patch.object(config, 'REGTEST', False):
            with patch('index_core.database.import_csv_data') as importer:
                import_bootstrap_data(None, 'creator.csv', 'https://invalid.example', 'INSERT')
                self.assertEqual(importer.call_count, 1)
                self.assertFalse(importer.call_args.kwargs['is_url'])

    def test_failed_initializer_releases_connection_before_retry(self):
        first, second = MagicMock(), MagicMock()
        with patch('index_core.database.db_manager.connect', side_effect=[first, second]):
            with patch('index_core.database.last_db_index', return_value=0):
                with patch('index_core.database.initialize_tables', side_effect=[RuntimeError('schema failure'), None]):
                    with patch('index_core.database.time.sleep'):
                        self.assertIs(initialize_db(), second)
        first.rollback.assert_called_once()
        first.close.assert_called_once()
        second.close.assert_not_called()
