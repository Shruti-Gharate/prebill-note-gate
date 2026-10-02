"""Compare a visit note with a draft claim and route the encounter.

The rules are deliberately shallow. They show the infrastructure decision —
submit, or hold for a person — and they leave a reason a reviewer can check.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

# Phrases that count as support for a draft code. Keys are lowercase
# fragments of the code description used in the synthetic claims.
SUPPORT = {
    "cataract": ("cataract",),
    "glaucoma": ("glaucoma", "intraocular pressure", "iop"),
    "diabetic retinopathy": ("diabetic retinopathy", "dot blot", "microaneurysm"),
    "oct": ("oct", "optical coherence"),
    "visual field": ("visual field", "humphrey"),
    "intravitreal": ("intravitreal", "injection"),
    "cataract extraction": ("phaco", "cataract extraction", "iol"),
    "intraocular": ("iol", "intraocular"),
}

PROCEDURES = {
    "oct": ("oct", "optical coherence"),
    "visual field": ("visual field", "humphrey"),
    "intravitreal injection": ("intravitreal", "injection"),
    "cataract extraction": ("phaco", "cataract extraction"),
}

LATERALITY = re.compile(r"\b(od|os|ou|right eye|left eye|both eyes)\b", re.I)
SIGNED = re.compile(r"\bsigned by\b", re.I)
MIN_NOTE_CHARS = 180


def _norm(text: str) -> str:
    return text.lower()


def _supported(description: str, note: str) -> bool:
    haystack = _norm(note)
    key = _norm(description)
    matches = [name for name in SUPPORT if name in key]
    if matches:
        # Prefer the longest phrase so "cataract extraction" is not
        # treated as supported just because the note says "cataract".
        name = max(matches, key=len)
        return any(phrase in haystack for phrase in SUPPORT[name])
    words = [w for w in re.findall(r"[a-z]{4,}", key)]
    return bool(words) and all(word in haystack for word in words)


def _mentioned_procedures(note: str) -> list[str]:
    """Procedures the note says were done, not ones it only discusses."""
    found = []
    sentences = re.split(r"(?<=[.])\s+", note)
    for name, phrases in PROCEDURES.items():
        for sentence in sentences:
            lowered = sentence.lower()
            if not any(phrase in lowered for phrase in phrases):
                continue
            if re.search(r"\b(performed|obtained)\b", sentence, re.I):
                found.append(name)
                break
    return found


def _needs_laterality(note: str) -> bool:
    haystack = _norm(note)
    eye_topic = any(
        token in haystack
        for token in ("cataract", "glaucoma", "retina", "eye", "iop", "oct")
    )
    return eye_topic and LATERALITY.search(note) is None


def gate_encounter(encounter: dict) -> dict:
    """Return a route, a confidence, and the flags that drove the route."""
    note = encounter.get("note") or ""
    claim = encounter.get("claim") or []
    flags: list[dict] = []

    if len(note.strip()) < MIN_NOTE_CHARS:
        flags.append(
            {
                "code": "thin_note",
                "detail": "Note is too short to support a coding decision.",
            }
        )
    if SIGNED.search(note) is None:
        flags.append(
            {
                "code": "missing_signature",
                "detail": "No signature line on the note.",
            }
        )
    if _needs_laterality(note):
        flags.append(
            {
                "code": "missing_laterality",
                "detail": "Eye finding or procedure without right, left, or both.",
            }
        )

    for item in claim:
        description = item.get("description") or item.get("code") or ""
        if not _supported(description, note):
            flags.append(
                {
                    "code": "unsupported_code",
                    "detail": f"Claim lists {item.get('code', description)}, which the note does not support.",
                }
            )

    claim_text = " ".join(_norm(item.get("description") or "") for item in claim)
    for procedure in _mentioned_procedures(note):
        phrases = PROCEDURES[procedure]
        if not any(phrase in claim_text for phrase in phrases):
            flags.append(
                {
                    "code": "procedure_not_on_claim",
                    "detail": f"Note describes {procedure}, which is not on the draft claim.",
                }
            )

    # Confidence is how much of the note the gate could actually use.
    confidence = 0.9
    if any(flag["code"] == "thin_note" for flag in flags):
        confidence = 0.35
    elif len(flags) >= 2:
        confidence = 0.55
    elif flags:
        confidence = 0.7

    route = "submit" if not flags else "review"
    return {
        "encounter_id": encounter.get("id"),
        "route": route,
        "confidence": confidence,
        "flags": flags,
    }


def evaluate(encounters: Iterable[dict], holdout_clinician: str = "") -> dict:
    """Score routes against gold labels.

    If holdout_clinician is non-empty, also score only that clinician's notes.
    The gate has no fitted parameters. The split is there so a single
    clinician's writing style cannot be mistaken for performance on a new clinic.
    """
    rows = list(encounters)

    def _score(subset: list[dict]) -> dict:
        correct = 0
        by_gold: dict[str, int] = defaultdict(int)
        by_hit: dict[str, int] = defaultdict(int)
        for encounter in subset:
            gold = encounter["gold_route"]
            pred = gate_encounter(encounter)["route"]
            by_gold[gold] += 1
            if pred == gold:
                correct += 1
                by_hit[gold] += 1
        total = len(subset)
        return {
            "n": total,
            "route_accuracy": (correct / total) if total else 0.0,
            "per_route": {
                route: (by_hit[route] / by_gold[route]) if by_gold[route] else None
                for route in sorted(by_gold)
            },
        }

    report = {"all": _score(rows)}
    if holdout_clinician:
        held = [row for row in rows if row.get("clinician_id") == holdout_clinician]
        report["held_out_clinician"] = {
            "clinician_id": holdout_clinician,
            **_score(held),
        }
    return report
