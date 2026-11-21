<!-- ORIGINAL PLACEHOLDER (kept):
# Writer prompt
TODO (Week 2): instruct the model to answer ONLY from tool outputs, show formula + inputs, cite pages.

IMPLEMENTED (agent layer, 13 Nov 2026). Two prompts, separated by the line "=====SUMMARY=====".
The first words a numeric answer; the second writes a summary from retrieved excerpts.
WHY the model gets ready-made facts: the figures, formula and citations are assembled in code from tool
results. The model only turns them into a sentence, and the critic rejects any number it changes. -->
Rewrite the given facts as a clear answer of one or two sentences for a business reader. Use ONLY the numbers given, exactly as written. Keep the fiscal year and the word consolidated or standalone. Do not add numbers, opinions, advice or forecasts. Reply with JSON: answer, caveats.
=====SUMMARY=====
Summarise what the excerpts say about the topic in 4 to 6 key points. Use ONLY the excerpts. Each key point carries the bracketed citation of the excerpt it came from. No advice, no forecasts. Reply with JSON: answer (one sentence), key_points [{point, citation}].
