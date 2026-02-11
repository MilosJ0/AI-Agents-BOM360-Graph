"""LangGraph Studio entrypoint — exposes a compiled graph at module level."""

import os

from dotenv import load_dotenv

load_dotenv()

from src.neo4j_client import Neo4jClient
from src.workflows import build_graph

db = Neo4jClient(
    uri=os.environ["NEO4J_URI"],
    user=os.environ["NEO4J_USER"],
    password=os.environ["NEO4J_PASSWORD"],
    database=os.getenv("NEO4J_DB", "neo4j"),
)

graph = build_graph(db)
