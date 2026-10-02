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
NEGATION = re.compile(
    r"\b(no|not|without|denies|denied|deferred|ruled out)\b", re.I
)
NOT_THIS_VISIT = re.compile(
    r"\bhistory:|\b(performed|underwent|done)\s+last\s+(year|month)\b|\byears ago\b|\bpreviously underwent\b|\bprior surgery\b",
    re.I,
)
EYE_TOKENS = {
    "right": (r"\bright eye\b", r"\bod\b"),
    "left": (r"\bleft eye\b", r"\bos\b"),
    "both": (r"\bboth eyes\b", r"\bou\b"),
}


def _norm(text: str) -> str:
    return text.lower()


def _lookup(description: str) -> tuple[str, tuple[str, ...]]:
    """Phrases that can support a claim description, and how to match them.

    Prefer the longest lexicon key so "cataract extraction" is not treated
    as supported just because the note says "cataract".
    """
    key = _norm(description)
    matches = [name for name in SUPPORT if name in key]
    if matches:
        name = max(matches, key=len)
        return "phrase", SUPPORT[name]
    words = tuple(w for w in re.findall(r"[a-z]{4,}", key))
    return "words", words


def _sentences(note: str) -> list[str]:
    parts = re.split(r"(?<=[.])\s+", note.strip())
    return [part.strip() for part in parts if part.strip()]


def _sentence_has_support(sentence: str, mode: str, phrases: tuple[str, ...]) -> bool:
    lowered = sentence.lower()
    if mode == "phrase":
        return any(phrase in lowered for phrase in phrases)
    return bool(phrases) and all(word in lowered for word in phrases)


def _expand(sentence: str, clinician_id: str, phrasebook: dict) -> tuple[str, str | None]:
    """Append this surgeon's own expansion when their abbreviation is on the page.

    Another surgeon's entries are never consulted. The expansion is a reading
    aid for matching. It is not text the note actually contains.
    """
    expanded = sentence
    used: list[str] = []
    for entry in phrasebook.get(clinician_id) or []:
        abbr = entry["abbr"]
        if re.search(rf"\b{re.escape(abbr)}\b", sentence, re.I):
            expanded = f"{expanded} {entry['expansion']}"
            used.append(
                f"{abbr} reads as {entry['expansion']} in this surgeon's earlier notes"
            )
    reading = "; ".join(used) if used else None
    return expanded, reading


def _eyes(text: str) -> set[str]:
    found = set()
    for name, patterns in EYE_TOKENS.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            found.add(name)
    return found


def _negated(sentence: str, anchors: list[str]) -> bool:
    lowered = sentence.lower()
    for anchor in anchors:
        idx = lowered.find(anchor.lower())
        if idx < 0:
            continue
        before = lowered[max(0, idx - 40) : idx]
        after = lowered[idx : idx + len(anchor) + 48]
        if NEGATION.search(before) or re.search(r"\bnot performed\b", after, re.I):
            return True
    return False


def _span_problem(sentence: str, anchors: list[str], description: str) -> str | None:
    """A found sentence can still be the wrong kind of support."""
    if anchors and _negated(sentence, anchors):
        return "negated_span"
    claim_eyes = _eyes(description)
    span_eyes = _eyes(sentence)
    if claim_eyes and span_eyes and claim_eyes.isdisjoint(span_eyes):
        return "laterality_mismatch"
    if NOT_THIS_VISIT.search(sentence):
        return "not_this_visit"
    return None


def _evidence_for(
    description: str, note: str, clinician_id: str, phrasebook: dict
) -> dict:
    """Return the supporting sentence, a surgeon-specific reading, and why it may be invalid."""
    mode, phrases = _lookup(description)
    if not phrases:
        return {"span": None, "reading": None, "problem": None, "anchors": []}
    for sentence in _sentences(note):
        expanded, reading = _expand(sentence, clinician_id, phrasebook)
        if not _sentence_has_support(expanded, mode, phrases):
            continue
        haystack = expanded.lower()
        if mode == "phrase":
            anchors = [phrase for phrase in phrases if phrase in haystack]
        else:
            anchors = list(phrases)
        # Also anchor on the abbreviation, so "no CE" negates the reading.
        if reading:
            for entry in phrasebook.get(clinician_id) or []:
                if re.search(rf"\b{re.escape(entry['abbr'])}\b", sentence, re.I):
                    anchors.append(entry["abbr"].lower())
        return {
            "span": sentence,
            "reading": reading,
            "problem": _span_problem(sentence, anchors, description),
            "anchors": anchors,
        }
    return {"span": None, "reading": None, "problem": None, "anchors": []}


def _mentioned_procedures(note: str) -> list[str]:
    """Procedures the note says were done, not ones it only discusses."""
    found = []
    sentences = re.split(r"(?<=[.])\s+", note)
    for name, phrases in PROCEDURES.items():
        for sentence in sentences:
            lowered = sentence.lower()
            if not any(phrase in lowered for phrase in phrases):
                continue
            if re.search(r"\bnot performed\b|\bnot obtained\b", sentence, re.I):
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


PROBLEM_DETAIL = {
    "negated_span": "The sentence mentions the code and also denies it.",
    "laterality_mismatch": "The sentence names a different eye from the claim.",
    "not_this_visit": "The sentence describes another visit, not today's encounter.",
}


def gate_encounter(encounter: dict, phrasebook: dict | None = None) -> dict:
    """Return a route, the sentence behind each code, and the flags that drove the route.

    A found sentence is not eligibility. Negation, the other eye, or another
    visit keeps the sentence visible and holds the encounter.
    """
    note = encounter.get("note") or ""
    claim = encounter.get("claim") or []
    clinician_id = encounter.get("clinician_id") or ""
    phrasebook = phrasebook or {}
    flags: list[dict] = []
    evidence: list[dict] = []

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
        code = item.get("code", description)
        found = _evidence_for(description, note, clinician_id, phrasebook)
        evidence.append(
            {
                "code": code,
                "span": found["span"],
                "reading": found["reading"],
                "valid": found["span"] is not None and found["problem"] is None,
            }
        )
        if found["span"] is None:
            flags.append(
                {
                    "code": "unsupported_code",
                    "detail": f"Claim lists {code}, which the note does not support.",
                }
            )
        elif found["problem"]:
            flags.append(
                {
                    "code": found["problem"],
                    "detail": PROBLEM_DETAIL[found["problem"]],
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
        "eligible": route == "submit",
        "confidence": confidence,
        "evidence": evidence,
        "flags": flags,
    }


def evaluate(
    encounters: Iterable[dict],
    holdout_clinician: str = "",
    phrasebook: dict | None = None,
) -> dict:
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
            pred = gate_encounter(encounter, phrasebook)["route"]
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
