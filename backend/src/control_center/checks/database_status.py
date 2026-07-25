from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

# Same MySQL/Neo4j/Redis instances the workbench/rag services use (see the
# "control-center" service's environment block in docker-compose.yml, which
# mirrors what those services are already configured with).
MYSQL_HOST = os.environ.get("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "omnibioai")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "omnibioai")

_CONNECT_TIMEOUT_S = 3


def get_database_status() -> dict[str, Any]:
    """Live status for the /database endpoint. Each store is checked
    independently and concurrently -- one being unreachable shouldn't slow
    down or blank out the other two."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        mysql_f = pool.submit(_mysql_status)
        redis_f = pool.submit(_redis_status)
        neo4j_f = pool.submit(_neo4j_status)
        return {
            "mysql": mysql_f.result(),
            "redis": redis_f.result(),
            "neo4j": neo4j_f.result(),
        }


def _mysql_status() -> Optional[dict[str, Any]]:
    try:
        import pymysql

        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
            connect_timeout=_CONNECT_TIMEOUT_S,
        )
    except Exception:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("SHOW STATUS LIKE 'Threads_connected'")
            connections = int((cur.fetchone() or (None, 0))[1])
            cur.execute("SHOW VARIABLES LIKE 'max_connections'")
            max_connections = int((cur.fetchone() or (None, 0))[1])
            cur.execute("SHOW STATUS LIKE 'Slow_queries'")
            slow_queries = int((cur.fetchone() or (None, 0))[1])
            cur.execute("""
                SELECT table_schema, ROUND(SUM(data_length + index_length) / 1024 / 1024, 2)
                FROM information_schema.tables
                GROUP BY table_schema
                ORDER BY 2 DESC
            """)
            databases = [{"name": row[0], "size_mb": float(row[1] or 0)} for row in cur.fetchall()]
        return {
            "connections": connections,
            "max_connections": max_connections,
            "slow_queries": slow_queries,
            "databases": databases,
        }
    except Exception:
        return None
    finally:
        conn.close()


def _redis_status() -> Optional[dict[str, Any]]:
    try:
        import redis

        r = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=_CONNECT_TIMEOUT_S, socket_timeout=_CONNECT_TIMEOUT_S,
        )
        info = r.info()
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        hit_rate = round(100 * hits / total, 1) if total else 0.0
        return {
            "used_memory_human": info.get("used_memory_human", "—"),
            "hit_rate_pct": hit_rate,
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception:
        return None


def _neo4j_status() -> Optional[dict[str, Any]]:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=_CONNECT_TIMEOUT_S,
        )
    except Exception:
        return None

    try:
        with driver.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return {"node_count": node_count, "relationship_count": rel_count}
    except Exception:
        return None
    finally:
        driver.close()
