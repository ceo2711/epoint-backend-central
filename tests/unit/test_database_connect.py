import time
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from app.core import database


def test_connect_psycopg2_with_retry_succeeds_on_second_attempt():
    connection = MagicMock()
    connect = MagicMock(
        side_effect=[
            psycopg2.OperationalError("timeout expired"),
            connection,
        ]
    )

    with (
        patch.object(database.settings, "db_connect_retries", 3),
        patch.object(database.settings, "db_connect_retry_delay_seconds", 0),
        patch.object(database.settings, "db_connect_timeout", 30),
        patch("app.core.database.psycopg2.connect", connect),
        patch("app.core.database.time.sleep") as sleep,
    ):
        result = database._connect_psycopg2_with_retry()

    assert result is connection
    assert connect.call_count == 2
    sleep.assert_called_once_with(0)


def test_connect_psycopg2_with_retry_raises_after_exhausting_retries():
    connect = MagicMock(side_effect=psycopg2.OperationalError("timeout expired"))

    with (
        patch.object(database.settings, "db_connect_retries", 2),
        patch.object(database.settings, "db_connect_retry_delay_seconds", 0),
        patch.object(database.settings, "db_connect_timeout", 30),
        patch("app.core.database.psycopg2.connect", connect),
        patch("app.core.database.time.sleep"),
        pytest.raises(psycopg2.OperationalError, match="timeout expired"),
    ):
        database._connect_psycopg2_with_retry()

    assert connect.call_count == 2
