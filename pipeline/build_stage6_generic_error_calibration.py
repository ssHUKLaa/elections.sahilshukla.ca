"""Pin recent seven-day generic-ballot terminal proxy errors for 2026 uncertainty."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "artifacts/calibration/stage6_national_snapshots.json"
OUTPUT = ROOT / "data/reference/stage6_generic_error_calibration.json"


def main() -> None:
    report = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
    by_cycle = {(row["cycle"], row["lead_days"]): row for row in report["snapshots"]}
    rows = []
    for cycle in (2020, 2022, 2024):
        snap = by_cycle[cycle, 7]
        generic = snap["generic_ballot"]
        if generic["status"] != "available" or generic["poll_count"] < 30:
            raise ValueError(f"Generic archive too sparse for {cycle}")
        actual_margin = snap["terminal_house_D_two_party_margin"]
        if not -1 < actual_margin < 1:
            raise ValueError(f"Invalid certified House margin for {cycle}")
        actual_logratio = math.log((1+actual_margin)/(1-actual_margin))
        rows.append({"cycle": cycle, "poll_count": generic["poll_count"],
                     "generic_mean_logratio": generic["mean"],
                     "terminal_house_logratio": actual_logratio,
                     "terminal_proxy_error_logratio": generic["mean"]-actual_logratio})
    rms = math.sqrt(sum(row["terminal_proxy_error_logratio"]**2 for row in rows)/len(rows))
    output = {"training_cycles": [2020, 2022, 2024],
              "cutoff_days_before_election": 7,
              "estimand_warning": "Terminal House vote includes changes after the cutoff and is only a noisy proxy for current generic-ballot survey error.",
              "use": "RMS magnitude enters 2026 national generic-ballot variance; historical mean signed error is not subtracted.",
              "snapshot_sha256": hashlib.sha256(SNAPSHOTS.read_bytes()).hexdigest(),
              "source_manifest_sha256": report["design"]["source_manifest_sha256"],
              "rows": rows, "rms_error_logratio": rms,
              "mean_signed_error_logratio_diagnostic_only": sum(
                  row["terminal_proxy_error_logratio"] for row in rows)/len(rows)}
    OUTPUT.write_text(json.dumps(output, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"cycles": output["training_cycles"], "rms_logratio": rms}, indent=2))


if __name__ == "__main__":
    main()
