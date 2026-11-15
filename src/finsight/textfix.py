"""Repairs for PDFs whose fonts map characters to the wrong Unicode code points.

The TCS FY2024-25 report stores digits and punctuation as Greek and combining characters
(for example 'ϰ' for 4, so revenue reads '2,55,32ϰ' instead of '2,55,324'). The mapping below was worked out
from that report: U+03EC..U+03F5 are the digits 0..9 in order, and a few marks stand for punctuation.
"""
from __future__ import annotations

_MAP = {0x03EC + i: str(i) for i in range(10)}
_MAP.update({0x0439: "%", 0x0358: ".", 0x0357: ":", 0x036C: "/", 0x0372: "-", 0x037E: "(", 0x037F: ")",
             0x0F24: "₹", 0x0398: "&", 0x035E: '"', 0x035F: '"', 0x2011: "-"})


def fix(text: str) -> str:
    return text.translate(_MAP)
