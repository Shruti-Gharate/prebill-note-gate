"""Score the gate on the synthetic encounters and print a short report."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prebill_gate.pipeline import evaluate, gate_encounter  # noqa: E402


def main() -> None:
    rows = json.loads((ROOT / "data" / "encounters.json").read_text())
    phrasebook = json.loads((ROOT / "data" / "phrasebook.json").read_text())
    report = evaluate(rows, holdout_clinician="c3", phrasebook=phrasebook)
    print("route accuracy, all encounters: {:.0%}".format(report["all"]["route_accuracy"]))
    held = report["held_out_clinician"]
    print(
        "route accuracy, held-out clinician {}: {:.0%} (n={})".format(
            held["clinician_id"], held["route_accuracy"], held["n"]
        )
    )
    print()
    matched_but_held = 0
    for row in rows:
        result = gate_encounter(row, phrasebook)
        flags = ", ".join(flag["code"] for flag in result["flags"]) or "none"
        mark = "ok" if result["route"] == row["gold_route"] else "MISS"
        eligible = "eligible" if result["eligible"] else "held"
        print(
            f"{row['id']}  {result['route']:6}  gold={row['gold_route']:6}  {mark}  {eligible}  flags: {flags}"
        )
        for item in result["evidence"]:
            if item["span"] and not item["valid"]:
                matched_but_held += 1
            if item["span"] is None:
                state, span = "missing", "—"
            else:
                state = "valid" if item["valid"] else "invalid"
                span = item["span"]
            print(f"    {item['code']:8}  {state:7}  {span}")
            if item["reading"]:
                print(f"    reading  {item['reading']}")
    print()
    print(f"matched sentence, still ineligible: {matched_but_held}")


if __name__ == "__main__":
    main()
