# Pre-bill note gate

A small, auditable gate for the step before a medical claim goes out: read an unstructured visit note, compare it with the codes on the draft claim, and decide whether the encounter can move forward or needs a person.

This is a synthetic demo. It is not a certified coder, not medical advice, and not affiliated with any company. The notes were written for this repository. No patient data is included.

## Why this shape

A chart-audit agent is only as good as the text it was given. If the note does not support the code, if laterality is missing, or if the extraction is thin, the safe move is to hold the encounter for review. That is the same habit as scoring a clinical labeling model on a grouped holdout and sending low-confidence predictions to a person: the downstream workflow should not inherit an uncertain label.

The gate is rule-based on purpose. Every flag points at a phrase in the note or at the absence of one. An interview or a code review can trace a decision without calling a model.

## What it checks

On each synthetic encounter the gate looks for:

- a claim code whose description is not supported by the note
- an eye finding or procedure with no laterality (right, left, or both)
- a procedure the note describes that is not on the claim
- a note with no signature line
- a note too thin to trust, even if the codes look aligned

`submit` means none of those fired. Anything else is `review`.

Each claim line also returns the sentence that supports it. A missing sentence is the unsupported-code flag. A downstream agent can quote that span, and a reviewer can check it without opening the rest of the chart.

```json
{
  "id": "e1",
  "route": "submit",
  "confidence": 0.9,
  "evidence": [
    {
      "code": "H25.11",
      "span": "Exam of the right eye (OD) shows a visually significant cataract."
    },
    {
      "code": "92134",
      "span": "OCT of the right eye shows no macular edema."
    }
  ],
  "flags": []
}
```

## Run

```bash
python3 -m unittest discover -s tests -v
python3 scripts/evaluate.py
```

No third-party packages. Python 3.9+.

## Layout

- `src/prebill_gate/pipeline.py` — the gate
- `data/encounters.json` — synthetic notes, draft claims, and gold routes
- `scripts/evaluate.py` — overall score, plus a split that holds out a clinician

Gold labels were written with the notes, before the scorer. The held-out clinician is there to show the evaluation habit: do not treat one author's notes as if they were new clinics.
