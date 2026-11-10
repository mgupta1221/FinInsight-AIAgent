"""Critic node (code + 1 LLM call, schemas.CriticVerdict): rejects any answer whose numbers aren't
traceable to a tool, whose pages aren't cited, whose formula != glossary, or that gives advice.
Fail -> back to planner (max 2 retries) -> else escalate. Prompt in prompts/critic.md. TODO (Week 2)."""
