"""test db module."""
from itertools import product
from unittest import mock

import pytest


@pytest.mark.parametrize(
    'path_isfile_retval, check_dbv_retval, path_is_dbc_path',
    product([False, True], repeat=3)
)
def test_init_db(path_isfile_retval, check_dbv_retval, path_is_dbc_path):
    """test sqlite generation and db creation"""
    with mock.patch('version.database.db.db_constants') as m_dbc, \
            mock.patch('version.database.db.sqlite3') as m_sl3, \
            mock.patch('version.database.db.os') as m_os, \
            mock.patch('version.database.db.create_db_path') as m_create_db_path, \
            mock.patch('version.database.db.check_db_version') \
            as m_check_dbv:
        from version.database import db
        m_os.path.isfile.return_value = path_isfile_retval
        m_check_dbv.return_value = check_dbv_retval
        if path_is_dbc_path:
            path = m_dbc.DB_PATH
        else:
            path = mock.Mock()
        # run
        res = db.init_db(path)
        # test
        if path_isfile_retval:
            if path == m_dbc.DB_PATH and not check_dbv_retval:
                m_sl3.assert_has_calls([
                    mock.call.connect(path, check_same_thread=False),
                ])
                assert res is None
                return
            else:
                m_sl3.assert_has_calls([
                    mock.call.connect(path, check_same_thread=False),
                    mock.call.connect().execute('PRAGMA foreign_keys = on')
                ])
        else:
            m_create_db_path.assert_called_once_with()

            m_sl3.assert_has_calls([
                mock.call.connect(path, check_same_thread=False),
                mock.call.connect().cursor(),
                mock.call.connect().cursor().execute(
                    'CREATE TABLE IF NOT EXISTS version(version REAL)'),
                mock.call.connect().cursor().execute(
                    'INSERT INTO version(version) VALUES(?)',
                    (m_dbc.CURRENT_DB_VERSION,)
                ),
                mock.call.connect().cursor().executescript(db.STRUCTURE_SCRIPT),
                mock.call.connect().commit(),
                mock.call.connect().execute('PRAGMA foreign_keys = on')
            ])
        assert res == m_sl3.connect.return_value
        assert res.isolation_level is None
