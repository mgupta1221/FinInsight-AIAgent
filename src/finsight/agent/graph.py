"""Wires the agents into a LangGraph StateGraph with the SqliteSaver checkpointer (cross-turn
memory) and a recursion/step cap of settings.max_steps (=10). Exposes run(question, session_id).
TODO (Week 2)."""
