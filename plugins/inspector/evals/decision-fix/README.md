# decision-fix: the fix / not-a-fix call by a decision model

Does a decision model (Gemini Decision 1, from the Gemini Decisions API) tell bug fixes from
everything else better than the collector's regex (`evidence.judge`)? Measured on this
repository's history up to #72, against the hand labels in `tests/golden_labels.py`
(16 fixes, 20 non-fixes).

```bash
git fetch --unshallow                       # only in a shallow clone: the labels need history up to #72
python run.py build                         # out/dataset.json, out/requests.json (no network)
python run.py build --diff 30 --chunk 25    # with 30 changed code lines per unit, in 4 requests
OPENROUTER_API_KEY=... python run.py call --requests out/requests.json --out out/answers.json   # Gemini Decision 1
OPENROUTER_API_KEY=... python run.py call --requests out/requests.json --out out/answers-llm.json \
    --backend openrouter --model <openrouter model id>                                          # a chat model, to compare
python run.py score --dataset out/dataset.json --answers out/answers.json
```

- **The shared input** is every unit (76) as text: title, commit subjects, files with +/- lines,
  version bumps, and with `--diff N` its first N changed code lines. It says the text is data, not
  instructions. One yes/no question per unit, all in one request. Titles only, that is about 15k
  tokens; `--diff 30` is about 46k.
- **The default backend, `decisions`,** is Gemini Decision 1 through OpenRouter's Decisions API
  (`POST /api/alpha/decisions`, an alpha endpoint), its format read from `@openrouter/sdk` 1.5.100:
  one `noul` question per unit with true/false criteria, answered with the probability of yes. The
  answer is yes from 0.5; score sweeps other cuts. A refusal is left out (unanswered). Cost, tokens
  and time per request go to `answers.meta.json`. Google's own endpoint (`--backend gemini`) is not
  written: its docs couldn't be read here, and OpenRouter makes it unneeded.
- **`--backend openrouter`** runs any chat model on OpenRouter, asked for all the answers as one
  JSON object (temperature 0). That tests whether an LLM beats the regex at this call. It is not
  the Decisions API: a generative model costs output tokens and its self-reported confidence is
  poorly calibrated. Time and token usage per request go to `answers.meta.json`. A question with
  no readable answer is left out and scored as unanswered, never as a no.
- **What score prints:** precision, recall and accuracy for the regex and the model, every unit
  where they differ from each other or from the label, the fix share over all 76 units, whether
  the two bump-only fixes (#18, #25, which the regex misses by design) were found, and with
  confidences a threshold sweep.

## First result (2026-11-13, titles only, one request)

| | precision | recall | accuracy | time | cost |
|---|---|---|---|---|---|
| regex | 1.00 | 0.88 | 0.94 | ~0 s | none |
| Gemini Decision 1, first wording | 1.00 | 0.25 | 0.67 | 2.0 s | $0.0036 |
| Gemini Decision 1, review fixes count | 1.00 | 0.88 | 0.94 | 1.8 s | $0.0041 |

- The first wording told the model to answer no for fixes of "review comments". Here reviews run
  after merge, so a later "review fixes" PR repairs shipped code, and the labels count it as a fix:
  10 of the model's 12 misses were such PRs. The question now says so.
- With that wording the model ties the regex, with different misses: it finds #25 (bump-only),
  misses #6. Any cut from 0.4 to 0.7 gives the same scores; fix share over all units 0.29 (regex 0.25).
- The wording was changed after seeing the misses on these same labels, so this shows the model
  understands the question, not that it beats the regex. That still needs labels after #72.
- For this call the model does not save time: the regex is instant. Where a decision model could
  save minutes is a judgement an agent makes today; that is a separate, unmeasured experiment.

## Read the result with this in mind

- **These labels favour the regex.** It was tuned on exactly these 36 units, and scores 1.00
  precision and 0.88 recall on them (it misses only #18 and #25). The model can gain at most those
  two here, and any miss counts against it. A fair comparison needs labels the regex never saw:
  the history after #72.
- 36 labeled units is a small sample: one unit moves accuracy by about 3 points.
- A model's answer carries no evidence. In a run it would decide which units the case readers
  work, never a claim in the case file (ground rule 1: such a call is *inferred* at most).
