"""CLI entry point for BOM360 multi-agent system."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage

from .models import AppState
from .neo4j_client import Neo4jClient
from .workflows import build_graph


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # --- Connect to Neo4j ---
    try:
        db = Neo4jClient(
            uri=os.environ["NEO4J_URI"],
            user=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.getenv("NEO4J_DB", "neo4j"),
        )
    except KeyError as e:
        print(f"Missing environment variable: {e}", file=sys.stderr)
        print("Copy .env.example to .env and fill in your values.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Build LangGraph ---
    app = build_graph(db)

    print("\nBOM360 Multi-Agent System")
    print("Type your question (or 'exit' to quit)\n")

    # --- Handle single-shot mode from CLI args ---
    if len(sys.argv) > 1:
        user_goal = " ".join(sys.argv[1:])
        _run_once(app, user_goal)
        db.close()
        return

    # --- Chat loop ---
    while True:
        try:
            user_goal = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_goal:
            continue
        if user_goal.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break

        _run_once(app, user_goal)

    db.close()


def _run_once(app, user_goal: str) -> None:
    """Run a single query through the workflow and print the response."""
    state = AppState(
        user_goal=user_goal,
        messages=[HumanMessage(content=user_goal)],
    )
    print(f"\nProcessing: \"{user_goal}\"\n")

    try:
        out = AppState(**app.invoke(state))
    except Exception as e:
        logging.exception("Workflow failed")
        print(f"\nWorkflow error: {e}\n", file=sys.stderr)
        return

    # Display the formatted AI response from messages
    if out.messages:
        last = out.messages[-1]
        text = last.content if hasattr(last, "content") else str(last)
        print(text)
        print()


if __name__ == "__main__":
    main()
