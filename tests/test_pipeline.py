import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prebill_gate.pipeline import evaluate, gate_encounter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "encounters.json"
PHRASEBOOK = ROOT / "data" / "phrasebook.json"


def _load():
    return json.loads(DATA.read_text())


def _phrasebook():
    return json.loads(PHRASEBOOK.read_text())


class GateTests(unittest.TestCase):
    def test_supported_complete_note_can_submit(self):
        encounter = _load()[0]
        result = gate_encounter(encounter)
        self.assertEqual(result["route"], "submit")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["flags"], [])
        self.assertGreaterEqual(result["confidence"], 0.8)
        spans = {item["code"]: item["span"] for item in result["evidence"]}
        self.assertIn("cataract", spans["H25.11"].lower())
        self.assertIn("oct", spans["92134"].lower())
        for span in spans.values():
            self.assertIn(span, encounter["note"])

    def test_extraction_on_claim_without_a_procedure_in_the_note_is_held(self):
        encounter = next(row for row in _load() if row["id"] == "e2")
        result = gate_encounter(encounter)
        self.assertEqual(result["route"], "review")
        self.assertIn("unsupported_code", {flag["code"] for flag in result["flags"]})
        spans = {item["code"]: item["span"] for item in result["evidence"]}
        self.assertIn("cataract", spans["H25.12"].lower())
        self.assertIsNone(spans["66984"])

    def test_injection_described_but_missing_from_the_claim_is_held(self):
        encounter = next(row for row in _load() if row["id"] == "e5")
        result = gate_encounter(encounter)
        self.assertEqual(result["route"], "review")
        self.assertIn(
            "procedure_not_on_claim", {flag["code"] for flag in result["flags"]}
        )

    def test_thin_note_without_laterality_or_signature_is_held(self):
        encounter = next(row for row in _load() if row["id"] == "e3")
        codes = {flag["code"] for flag in gate_encounter(encounter)["flags"]}
        self.assertTrue(
            {"thin_note", "missing_signature", "missing_laterality"} <= codes
        )

    def test_a_denial_in_the_matched_sentence_is_not_eligible(self):
        encounter = next(row for row in _load() if row["id"] == "e9")
        result = gate_encounter(encounter, _phrasebook())
        self.assertEqual(result["route"], "review")
        self.assertFalse(result["eligible"])
        item = result["evidence"][0]
        self.assertIn("no cataract", item["span"].lower())
        self.assertFalse(item["valid"])
        self.assertIn("negated_span", {flag["code"] for flag in result["flags"]})

    def test_the_other_eye_is_not_eligible(self):
        encounter = next(row for row in _load() if row["id"] == "e10")
        result = gate_encounter(encounter, _phrasebook())
        self.assertFalse(result["eligible"])
        self.assertIn("laterality_mismatch", {flag["code"] for flag in result["flags"]})
        self.assertIsNotNone(result["evidence"][0]["span"])

    def test_last_year_is_not_this_visit(self):
        encounter = next(row for row in _load() if row["id"] == "e11")
        result = gate_encounter(encounter, _phrasebook())
        self.assertFalse(result["eligible"])
        self.assertIn("not_this_visit", {flag["code"] for flag in result["flags"]})

    def test_abbreviation_reads_only_for_the_surgeon_who_uses_it(self):
        book = _phrasebook()
        own = gate_encounter(next(row for row in _load() if row["id"] == "e12"), book)
        other = gate_encounter(next(row for row in _load() if row["id"] == "e13"), book)
        self.assertTrue(own["eligible"])
        self.assertIn("cataract extraction", own["evidence"][0]["reading"])
        self.assertFalse(other["eligible"])
        self.assertIsNone(other["evidence"][0]["span"])

    def test_gold_routes_match_and_held_out_clinician_is_separate(self):
        rows = _load()
        report = evaluate(rows, holdout_clinician="c3", phrasebook=_phrasebook())
        self.assertEqual(report["all"]["route_accuracy"], 1.0)
        self.assertEqual(report["held_out_clinician"]["n"], 2)
        self.assertEqual(report["held_out_clinician"]["route_accuracy"], 1.0)
        self.assertNotEqual(
            {row["clinician_id"] for row in rows if row["clinician_id"] != "c3"},
            {"c3"},
        )


if __name__ == "__main__":
    unittest.main()
