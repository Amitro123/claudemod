# decision-fix: the fix / not-a-fix call by a decision model

Does a decision model (Gemini Decision 1, from the Gemini Decisions API) tell bug fixes from
everything else better than the collector's regex (`evidence.judge`)? Measured on this
repository's history up to #72, against the hand labels in `tests/golden_labels.py`
(16 fixes, 20 non-fixes).

```bash
git fetch --unshallow                       # only in a shallow clone: the labels need history up to #72
python run.py build                         # out/dataset.json, out/requests.json (no network)
python run.py build --diff 30 --chunk 25    # with 30 changed code lines per unit, in 4 requests
GEMINI_API_KEY=... python run.py call --requests out/requests.json --out out/answers.json        # once client.decide is written
OPENROUTER_API_KEY=... python run.py call --requests out/requests.json --out out/answers.json \
    --backend openrouter --model <openrouter model id>
python run.py score --dataset out/dataset.json --answers out/answers.json
```

- **The shared input** is every unit (76) as text: title, commit subjects, files with +/- lines,
  version bumps, and with `--diff N` its first N changed code lines. It says the text is data, not
  instructions. One yes/no question per unit, all in one request. Titles only, that is about 15k
  tokens; `--diff 30` is about 46k.
- **`client.py` is not written yet.** The API's request format couldn't be read when this was
  built, and a guessed one would fail in ways that look like model errors. Fill in `decide()` from
  the docs (aistudio.google.com/docs/decisions); its docstring has the contract run.py needs.
  Until then, any tool can produce `answers.json` (`{"#6": {"answer": "yes", "confidence": 0.9}}`).
- **`--backend openrouter`** runs any chat model on OpenRouter, asked for all the answers as one
  JSON object (temperature 0). That tests whether an LLM beats the regex at this call. It is not
  the Decisions API: a generative model costs output tokens and its self-reported confidence is
  poorly calibrated. Time and token usage per request go to `answers.meta.json`. A question with
  no readable answer is left out and scored as unanswered, never as a no.
- **What score prints:** precision, recall and accuracy for the regex and the model, every unit
  where they differ from each other or from the label, the fix share over all 76 units, whether
  the two bump-only fixes (#18, #25, which the regex misses by design) were found, and with
  confidences a threshold sweep.

## Read the result with this in mind

- **These labels favour the regex.** It was tuned on exactly these 36 units, and scores 1.00
  precision and 0.88 recall on them (it misses only #18 and #25). The model can gain at most those
  two here, and any miss counts against it. A fair comparison needs labels the regex never saw:
  the history after #72.
- 36 labeled units is a small sample: one unit moves accuracy by about 3 points.
- A model's answer carries no evidence. In a run it would decide which units the case readers
  work, never a claim in the case file (ground rule 1: such a call is *inferred* at most).
