"""Real LLM-backed steps via the DeepSeek OpenAI-compatible API."""

from __future__ import annotations

import os

from openai import OpenAI


DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
    """Call DeepSeek chat completions and return the assistant's text content.

    The API key is read from the ``DEEPSEEK_API_KEY`` environment variable and
    is validated before any client is constructed or network call is made, so
    a missing key fails fast with a clear error.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY environment variable is not set. "
            "Set it before calling call_deepseek()."
        )

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("DeepSeek returned no message content.")
    return content
