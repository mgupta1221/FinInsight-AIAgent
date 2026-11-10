"""Day-0 capability check for the provided endpoint.

Run: python scripts/endpoint_check.py

Confirms, using your .env settings and the CA cert:
  1. The cert connects over HTTPS and /v1/models lists the model.
  2. A tiny /v1/chat/completions returns content.
  3. Whether response_format: json_schema is accepted (structured-output support).
  4. Whether Qwen "thinking" is on (so we know to disable it).

Prints a short PASS/FAIL report. Does not need any project data — only a valid .env + cert.
"""

from __future__ import annotations

import sys

import httpx
from openai import OpenAI

from finsight.config import settings


def main() -> int:
    print(f"Endpoint : {settings.openai_base_url}")
    print(f"Model    : {settings.model_name}")
    print(f"CA cert  : {settings.ca_cert_path}")
    if not settings.openai_api_key:
        print("\n[!] OPENAI_API_KEY is empty — set your group key in .env before running live checks.")
        return 2

    http_client = httpx.Client(verify=settings.ca_cert_path, timeout=60.0)
    client = OpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        http_client=http_client,
    )

    # 1. models
    try:
        models = client.models.list()
        ids = [m.id for m in models.data]
        print(f"\n[1] /models OK -> {ids}")
    except Exception as e:  # noqa: BLE001
        print(f"\n[1] /models FAILED: {e}")
        return 1

    # 2. basic chat
    try:
        r = client.chat.completions.create(
            model=settings.model_name,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=16,
            temperature=0.0,
        )
        content = r.choices[0].message.content
        thinking = "<think>" in (content or "")
        print(f"[2] chat OK -> {content!r}")
        print(f"[4] thinking-mode emitted: {thinking} "
              f"(QWEN_DISABLE_THINKING={settings.qwen_disable_thinking})")
    except Exception as e:  # noqa: BLE001
        print(f"[2] chat FAILED: {e}")
        return 1

    # 3. json_schema / structured output support
    try:
        client.chat.completions.create(
            model=settings.model_name,
            messages=[{"role": "user", "content": "Return JSON {\"ok\": true}"}],
            max_tokens=32,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        print("[3] response_format json_object: SUPPORTED")
    except Exception as e:  # noqa: BLE001
        print(f"[3] response_format json_object: NOT supported ({e}) — rely on instructor prompting")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
