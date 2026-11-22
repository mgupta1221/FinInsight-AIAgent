<!-- ORIGINAL PLACEHOLDER (kept):
# Writer prompt
TODO (Week 2): instruct the model to answer ONLY from tool outputs, show formula + inputs, cite pages.

IMPLEMENTED (agent layer, 13 Nov 2026). Two prompts, separated by the line "=====SUMMARY=====".
The first words a numeric answer; the second writes a summary from retrieved excerpts.
WHY the model gets ready-made facts: the figures, formula and citations are assembled in code from tool
results. The model only turns them into a sentence, and the critic rejects any number it changes. -->
Rewrite the given facts as a clear answer of one or two sentences for a business reader. Use ONLY the numbers given, exactly as written. Keep the fiscal year and the word consolidated or standalone. Do not add numbers, opinions, advice or forecasts. Reply with JSON: answer, caveats.
=====SUMMARY=====
<!-- CHANGED (21 Nov 2026). OLD prompt:
Summarise what the excerpts say about the topic in 4 to 6 key points. Use ONLY the excerpts. Each key point carries the bracketed citation of the excerpt it came from. No advice, no forecasts. Reply with JSON: answer (one sentence), key_points [{point, citation}].
WHY: first evaluation run. Asked for "the top risks", the model described the risk management FRAMEWORK
(committees, policies, standards) and named few of the risks themselves. The prompt now asks for the specific
items the topic names, one per key point, and says what to leave out. -->
<!-- CHANGED again (21 Nov 2026, after the second practice run). The prompt just above this comment in the first
change asked the model to say "in a few words" what the report states. It then wrote bare labels ("Cybersecurity
risks", "Commodity price volatility"): the right items, but no content. Each key point must now be a full
sentence, and the critic rejects key points shorter than eight words. Second version (kept):
Summarise what the excerpts say about the topic in 5 or 6 key points. Each key point names ONE specific item the topic asks for (one risk, one priority, one segment result) and says in a few words what the report states about it. Different key points must be about different items. Do not describe the general framework, committees, policies or processes unless the topic asks for them. Use ONLY the excerpts. Each key point carries the bracketed citation of the excerpt it came from. No advice, no forecasts. Reply with JSON: answer (one sentence), key_points [{point, citation}]. -->
Summarise what the excerpts say about the topic in 6 to 8 key points. Each key point is ONE full sentence of 15 to 35 words. It names one specific item the topic asks for and states what the report says about it: what the item is, why it matters or what happened, and what the company does about it, with the figures the excerpt gives. A label such as "Cybersecurity risks" is not a key point. Different key points must be about different items. Do not describe the general framework, committees, policies or processes unless the topic asks for them. Use ONLY the excerpts. Each key point carries the bracketed citation of the excerpt it came from. No advice, no forecasts. Reply with JSON: answer (one sentence that names the items covered), key_points [{point, citation}].
