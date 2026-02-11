"""Thin Neo4j driver wrapper that returns QueryResult for auditability."""

from __future__ import annotations

import logging
from typing import Any

from neo4j import GraphDatabase, Driver

from .models import QueryResult

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Direct Neo4j access via Bolt driver with auditable query results."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        # Verify connectivity on init
        self._driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s (db=%s)", uri, database)

    def close(self) -> None:
        self._driver.close()

    def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> QueryResult:
        """Execute a read query and wrap results in a QueryResult."""
        params = parameters or {}
        logger.debug("Cypher: %s | Params: %s", cypher, params)
        try:
            records, _, _ = self._driver.execute_query(
                cypher, params, database_=self._database
            )
            rows = [dict(record) for record in records]
            result = QueryResult(
                cypher=cypher,
                parameters=params,
                rows=rows,
                row_count=len(rows),
            )
            logger.debug("Returned %d rows", result.row_count)
            return result
        except Exception as e:
            logger.error("Cypher execution failed: %s\nQuery: %s\nParams: %s", e, cypher, params)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
