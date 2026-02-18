# Agentic system for BOM360 stored in a Neo4j database
BOM360 is a multi-agent AI system built on LangGraph and PydanticAI that connects natural-language queries to a live Neo4j production graph database. Instead of a monolithic chatbot, it uses a team of specialized AI analysts — each focused on a specific domain — coordinated by an automated workflow.
A plant supervisor or operations manager can ask questions like:

"What's the status of our production lines?"
"Are there any supplier risks we should address?"
"Generate work instructions for the current assembly job."

The system automatically classifies the intent, fetches precisely the right graph data, runs it through the appropriate AI analyst, verifies the output for accuracy against source data, and returns a structured, grounded answer.

<img width="1444" height="1549" alt="image" src="https://github.com/user-attachments/assets/f3299713-9c58-4de3-bd84-126a2c07732d" />
<img width="1367" height="1232" alt="image" src="https://github.com/user-attachments/assets/af74a4c0-27a0-4557-b75b-3b8cf02dfae0" />
