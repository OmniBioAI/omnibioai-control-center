"""
tests/test_check_database_status.py

Unit tests for:
  - control_center.checks.database_status

Covers each backend's status collector (_mysql_status/_redis_status/
_neo4j_status) independently -- connection failure returns None, a
query/info/session failure returns None while still closing the
connection, missing rows default to zero rather than raising -- and
get_database_status()'s combination of all three into one dict.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import database_status


def _cursor_ctx(cursor: MagicMock) -> MagicMock:
    """A context-manager mock wrapping a fake DB-API cursor."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestMysqlStatus(unittest.TestCase):
    """_mysql_status()'s connection stats/database-size query, with
    fail-safe handling of connect/query errors."""

    def test_connect_failure_returns_none(self) -> None:
        """A MySQL connection failure returns None."""
        with patch("pymysql.connect", side_effect=ConnectionError("refused")):
            self.assertIsNone(database_status._mysql_status())

    def test_success_returns_stats(self) -> None:
        """A successful query returns parsed connections/max_connections/
        slow_queries and a databases list with each name/size_mb."""
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            (None, "5"),   # Threads_connected
            (None, "151"),  # max_connections
            (None, "2"),   # Slow_queries
        ]
        cursor.fetchall.return_value = [("omnibioai", 12.5), ("licenses", 0.3)]
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)

        with patch("pymysql.connect", return_value=conn):
            result = database_status._mysql_status()

        self.assertEqual(result["connections"], 5)
        self.assertEqual(result["max_connections"], 151)
        self.assertEqual(result["slow_queries"], 2)
        self.assertEqual(result["databases"], [
            {"name": "omnibioai", "size_mb": 12.5},
            {"name": "licenses", "size_mb": 0.3},
        ])
        conn.close.assert_called_once()

    def test_query_failure_returns_none_and_closes_conn(self) -> None:
        """A query execution failure returns None and still closes the
        connection rather than leaking it."""
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("bad query")
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)

        with patch("pymysql.connect", return_value=conn):
            result = database_status._mysql_status()

        self.assertIsNone(result)
        conn.close.assert_called_once()

    def test_missing_row_defaults_to_zero(self) -> None:
        """A cursor returning no rows at all yields connections=0 and an
        empty databases list, not a raised exception."""
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)

        with patch("pymysql.connect", return_value=conn):
            result = database_status._mysql_status()

        self.assertEqual(result["connections"], 0)
        self.assertEqual(result["databases"], [])


class TestRedisStatus(unittest.TestCase):
    """_redis_status()'s hit-rate computation from Redis INFO, with
    fail-safe handling of connect/info errors."""

    def test_connect_failure_returns_none(self) -> None:
        """A Redis connection failure returns None."""
        with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
            self.assertIsNone(database_status._redis_status())

    def test_success_computes_hit_rate(self) -> None:
        """hit_rate_pct is computed from keyspace_hits/(hits+misses),
        and used_memory_human/connected_clients pass through."""
        mock_r = MagicMock()
        mock_r.info.return_value = {
            "used_memory_human": "1.2M", "keyspace_hits": 80, "keyspace_misses": 20,
            "connected_clients": 3,
        }
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = database_status._redis_status()

        self.assertEqual(result["hit_rate_pct"], 80.0)
        self.assertEqual(result["used_memory_human"], "1.2M")
        self.assertEqual(result["connected_clients"], 3)

    def test_zero_total_gives_zero_hit_rate(self) -> None:
        """With no hits or misses reported at all (both default to 0),
        hit_rate_pct is 0.0 rather than a division-by-zero error."""
        mock_r = MagicMock()
        mock_r.info.return_value = {}
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = database_status._redis_status()
        self.assertEqual(result["hit_rate_pct"], 0.0)

    def test_info_call_failure_returns_none(self) -> None:
        """A failure calling INFO returns None."""
        mock_r = MagicMock()
        mock_r.info.side_effect = RuntimeError("boom")
        with patch("redis.Redis.from_url", return_value=mock_r):
            self.assertIsNone(database_status._redis_status())


class TestNeo4jStatus(unittest.TestCase):
    """_neo4j_status()'s node/relationship count query, with fail-safe
    handling of driver-creation/query errors."""

    def test_driver_creation_failure_returns_none(self) -> None:
        """A Neo4j driver-creation failure returns None."""
        with patch("neo4j.GraphDatabase.driver", side_effect=ConnectionError("down")):
            self.assertIsNone(database_status._neo4j_status())

    def test_success_returns_counts(self) -> None:
        """A successful query returns node_count/relationship_count, and
        the driver is closed afterward."""
        node_record = MagicMock()
        node_record.__getitem__.return_value = 42
        rel_record = MagicMock()
        rel_record.__getitem__.return_value = 7

        session = MagicMock()
        session.run.return_value.single.side_effect = [node_record, rel_record]
        session_ctx = MagicMock()
        session_ctx.__enter__ = MagicMock(return_value=session)
        session_ctx.__exit__ = MagicMock(return_value=False)

        driver = MagicMock()
        driver.session.return_value = session_ctx

        with patch("neo4j.GraphDatabase.driver", return_value=driver):
            result = database_status._neo4j_status()

        self.assertEqual(result, {"node_count": 42, "relationship_count": 7})
        driver.close.assert_called_once()

    def test_query_failure_returns_none_and_closes_driver(self) -> None:
        """A failure opening the session returns None and still closes
        the driver rather than leaking it."""
        session_ctx = MagicMock()
        session_ctx.__enter__ = MagicMock(side_effect=RuntimeError("query failed"))
        session_ctx.__exit__ = MagicMock(return_value=False)
        driver = MagicMock()
        driver.session.return_value = session_ctx

        with patch("neo4j.GraphDatabase.driver", return_value=driver):
            result = database_status._neo4j_status()

        self.assertIsNone(result)
        driver.close.assert_called_once()


class TestGetDatabaseStatus(unittest.TestCase):
    """get_database_status()'s combination of all three backend statuses."""

    def test_combines_all_three_stores(self) -> None:
        """mysql/redis/neo4j statuses are combined into one dict
        unchanged, including a None value for an unreachable store."""
        with patch.object(database_status, "_mysql_status", return_value={"connections": 1}):
            with patch.object(database_status, "_redis_status", return_value={"hit_rate_pct": 99.0}):
                with patch.object(database_status, "_neo4j_status", return_value=None):
                    result = database_status.get_database_status()

        self.assertEqual(result, {
            "mysql": {"connections": 1},
            "redis": {"hit_rate_pct": 99.0},
            "neo4j": None,
        })


if __name__ == "__main__":
    unittest.main()
