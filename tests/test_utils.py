"""test utils module."""
from unittest import mock
from itertools import product

import pytest

from version.utils import backup_database


@pytest.mark.parametrize(
    'mock_exists_retval, mock_isdir_retval',
    product([True, False], repeat=2)
)
def test_run_backup_database(mock_exists_retval, mock_isdir_retval):
    """test run with mock obj as input."""
    mock_db_path = mock.Mock()
    mock_base_path = mock.Mock()
    mock_name = mock.Mock()
    with mock.patch('version.utils.os') as mock_os, \
            mock.patch('version.utils.shutil') as mock_shutil, \
            mock.patch('version.utils.datetime') as mock_datetime:
        mock_datetime.datetime.today.return_value = '2016-10-25 15:42:47.649416'
        mock_os.path.split.return_value = (mock_base_path, mock_name)
        mock_os.path.exists.return_value = mock_exists_retval
        mock_os.path.isdir.return_value = mock_isdir_retval
        res = backup_database(mock_db_path)
        assert res
        mock_datetime.datetime.today.assert_called_once_with()
        os_calls = [
            mock.call.path.split(mock_db_path),
            mock.call.path.join(mock_base_path, 'backup'),
            mock.call.path.isdir(mock_os.path.join.return_value),
            mock.call.path.join(
                mock_os.path.join.return_value,
                "2016-10-25-{}".format(mock_name)),
            mock.call.path.exists(mock_os.path.join.return_value),
        ]
        if mock_exists_retval:
            if mock_isdir_retval:
                assert len(mock_os.mock_calls) == 103
            else:
                assert len(mock_os.mock_calls) == 104
            os_calls.extend([
                mock.call.path.join(
                    mock_os.path.join.return_value,
                    "2016-10-25(1)-2016-10-25-{}".format(mock_name)),
                mock.call.path.join(
                    mock_os.path.join.return_value,
                    "2016-10-25(2)-2016-10-25-{}".format(mock_name)),
            ])
            assert not mock_shutil.mock_calls
        else:
            if mock_isdir_retval:
                assert len(mock_os.mock_calls) == 5
            else:
                assert len(mock_os.mock_calls) == 6
            mock_shutil.copyfile.assert_called_once_with(
                mock_db_path, mock_os.path.join.return_value)

        if mock_isdir_retval:
            assert not mock_os.mkdir.called
        else:
            mock_os.mkdir.assert_called_once_with(mock_os.path.join.return_value)
        mock_os.assert_has_calls(os_calls, any_order=True)
