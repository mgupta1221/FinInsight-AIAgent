# ORIGINAL PLACEHOLDER (kept):
# """Mask any user-entered personal data before it is written to logs/traces. TODO (Week 3)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
# WHY: the agent logs every question in store/memory.sqlite. The Responsible-AI section of the brief asks
# that user-entered personal data is not stored, so emails, phone numbers and PAN-like ids are masked first.
"""Mask personal data in text that is about to be logged."""
from __future__ import annotations

import re


def mask_pii(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    text = re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[pan]", text)
    return re.sub(r"(?<!\d)(\+?\d[\d\s-]{8,13}\d)(?!\d)", "[phone]", text)
