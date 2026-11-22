<!-- ORIGINAL PLACEHOLDER (kept):
# Critic prompt
TODO (Week 2): checklist the critic LLM call applies (provenance, citation, formula, scope/year, no advice).

IMPLEMENTED (agent layer, 13 Nov 2026) as CODE, in agent/critic.py. No model call is made.
WHY code instead of a model call: each check below has a yes/no answer that code can decide exactly, at no
token cost, and an 8B model is an unreliable judge of another 8B model's numbers. A model-based check can be
added later for summaries (are the key points supported by the excerpts?) if evaluation shows it is needed. -->
# Critic checklist (applied in code by agent/critic.py)

1. Provenance: every number in the answer text equals a tool result (an input figure, a computed value, a
   ranking value), within rounding.
2. Citation: every input figure has a page and a citation, and the answer's citations cover all of them.
3. Formula: for a computed metric, the formula shown is the one in config/glossary.yaml.
4. Year and scope: the answer states the fiscal year of the plan and does not state the other scope.
5. No advice: no buy/sell/hold, valuation or forecast wording.
6. Summaries: at least 3 key points, and every citation is one of the retrieved passages.

Fail on any point: the writer is asked again (maximum 2 rewrites; the last is a code template). If it still
fails, the answer is returned as "Unverified, please check page X".
