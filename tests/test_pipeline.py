import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prebill_gate.pipeline import evaluate, gate_encounter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "encounters.json"


def _load():
    return json.loads(DATA.read_text())


class GateTests(unittest.TestCase):
    def test_supported_complete_note_can_submit(self):
        encounter = _load()[0]
        result = gate_encounter(encounter)
        self.assertEqual(result["route"], "submit")
        self.assertEqual(result["flags"], [])
        self.assertGreaterEqual(result["confidence"], 0.8)

    def test_extraction_on_claim_without_a_procedure_in_the_note_is_held(self):
        encounter = next(row for row in _load() if row["id"] == "e2")
        result = gate_encounter(encounter)
        self.assertEqual(result["route"], "review")
        self.assertIn("unsupported_code", {flag["code"] for flag in result["flags"]})

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

    def test_gold_routes_match_and_held_out_clinician_is_separate(self):
        rows = _load()
        report = evaluate(rows, holdout_clinician="c3")
        self.assertEqual(report["all"]["route_accuracy"], 1.0)
        self.assertEqual(report["held_out_clinician"]["n"], 2)
        self.assertEqual(report["held_out_clinician"]["route_accuracy"], 1.0)
        self.assertNotEqual(
            {row["clinician_id"] for row in rows if row["clinician_id"] != "c3"},
            {"c3"},
        )


if __name__ == "__main__":
    unittest.main()
