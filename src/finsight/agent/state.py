"""Shared LangGraph state passed between agents (the 'memory sheet').

Holds the question, resolved slots (companies/years/statement/metric), tool observations,
the draft answer, the critic verdict, retry counts, and the final status.
TODO (Week 2): define the TypedDict/Pydantic state model.
"""
