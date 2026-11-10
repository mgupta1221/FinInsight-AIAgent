"""Planner node (LLM->JSON, schemas.Plan): breaks the question into steps and fills slots;
emits a clarify_question when a slot is missing/ambiguous. Few-shot plans in prompts/planner.md.
TODO (Week 2)."""
