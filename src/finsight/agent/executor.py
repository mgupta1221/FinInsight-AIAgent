"""Executor node (code): runs the plan's tool steps; each observation can trigger a re-plan
(missing item -> search_report; unit mismatch -> normalise_units). Enforces the step cap.
TODO (Week 2)."""
