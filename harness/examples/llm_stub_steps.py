"""Real LLM-backed step functions for the summarize example flow."""

from __future__ import annotations

from pydantic import BaseModel

from harness import llm_step


class TextInput(BaseModel):
    """The text a step reads and the next step summarizes."""

    text: str


class SummaryOutput(BaseModel):
    """The one-sentence summary produced by the DeepSeek call."""

    summary: str


def read_input(data: TextInput) -> dict[str, str]:
    """Pass the validated text through unchanged."""
    return {"text": data.text}


def summarize(data: TextInput) -> dict[str, str]:
    """Ask DeepSeek for a one-sentence summary of the input text."""
    prompt = (
        "Summarize the following text in exactly one sentence. "
        "Return only the summary sentence with no extra commentary.\n\n"
        f"{data.text}"
    )
    return {"summary": llm_step.call_deepseek(prompt)}
