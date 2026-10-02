"""Score the gate on the synthetic encounters and print a short report."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prebill_gate.pipeline import evaluate, gate_encounter  # noqa: E402


def main() -> None:
    rows = json.loads((ROOT / "data" / "encounters.json").read_text())
    report = evaluate(rows, holdout_clinician="c3")
    print("route accuracy, all encounters: {:.0%}".format(report["all"]["route_accuracy"]))
    held = report["held_out_clinician"]
    print(
        "route accuracy, held-out clinician {}: {:.0%} (n={})".format(
            held["clinician_id"], held["route_accuracy"], held["n"]
        )
    )
    print()
    for row in rows:
        result = gate_encounter(row)
        flags = ", ".join(flag["code"] for flag in result["flags"]) or "none"
        mark = "ok" if result["route"] == row["gold_route"] else "MISS"
        print(f"{row['id']}  {result['route']:6}  gold={row['gold_route']:6}  {mark}  flags: {flags}")
        for item in result["evidence"]:
            span = item["span"] if item["span"] else "—"
            print(f"    {item['code']:8}  {span}")


if __name__ == "__main__":
    main()
