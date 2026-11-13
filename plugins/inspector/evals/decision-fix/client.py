"""The one part of the experiment that talks to the Gemini Decisions API: fill in `decide`.

Not written yet on purpose. The API's request and response format could not be read when this
experiment was built (its docs are at aistudio.google.com/docs/decisions), and a guessed format
would fail in ways that look like model errors. Fill it in from the docs; run.py needs nothing else.

Contract:
    decide(shared_input: str, questions: list[dict]) -> dict[str, dict]

- shared_input: the text every question is asked about (one request's "input" in requests.json).
- questions: [{"id": "#6", "type": "yes_no", "text": "Unit #6: did this change repair ..."}, ...]
- returns: {"#6": {"answer": "yes" | "no", "confidence": 0.93}, ...}, one entry per question id.
  confidence is the model's confidence in the answer it gave (leave it out if the API has none);
  run.py score turns it into a confidence of "yes" and sweeps thresholds over it.

The key: read it from the environment (GEMINI_API_KEY), never from a file in the repository.
"""
from __future__ import annotations


def decide(shared_input: str, questions: list[dict]) -> dict[str, dict]:
    raise NotImplementedError(
        "client.decide is not written yet: fill it in from the Gemini Decisions API docs "
        "(aistudio.google.com/docs/decisions); see this file's docstring for the contract.")
