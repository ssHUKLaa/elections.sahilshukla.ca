"""Explain the 2020 House miss without changing its chronological backtest."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "artifacts/calibration"
JOINT = CAL / "stage6_joint_replay.json"
FORENSIC = CAL / "stage6_house_2020_forensic_floor.json"
SNAPSHOTS = CAL / "stage6_national_snapshots.json"
PARAMETERS = ROOT / "artifacts/nowcast/model_parameters.json"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    joint = read(JOINT)
    forensic = read(FORENSIC)
    snapshots = read(SNAPSHOTS)
    parameters = read(PARAMETERS)
    base = next(c for c in joint["cells"] if c["cycle"] == 2020 and c["lead_days"] == 7)
    stressed = forensic["cells"][0]
    assert stressed["cycle"] == 2020 and stressed["lead_days"] == 7
    assert base["national"]["center_logratio"] == stressed["national"]["center_logratio"]
    live_generic = parameters["national_signal_update"]["generic_ballot"]
    live_sd = live_generic["observation_sd_logratio"]
    assert math.isclose(live_sd, stressed["national"]["forensic_sd_floor"], rel_tol=1e-12)
    snap = next(s for s in snapshots["snapshots"] if s["cycle"] == 2020 and s["lead_days"] == 7)
    terminal_error = live_generic["historical_error_calibration"]["rows"][0]["terminal_proxy_error_logratio"]
    assert math.isclose(2*snap["generic_ballot"]["terminal_margin_error"], terminal_error,
                        rel_tol=0.01)
    base_house = base["office_seats"]["house"]
    stress_house = stressed["office_seats"]["house"]
    assert base_house["actual_D_wins"] == stress_house["actual_D_wins"] == 222
    assert base_house["actual_percentile"] < 0.025
    assert stress_house["interval95"][0] <= 222 <= stress_house["interval95"][1]
    prior_sd = math.sqrt(base["national"]["variance"])
    report = {
        "status": "reviewed_no_live_change_required",
        "decision": "Keep the chronological 2020 replay miss visible. Its national uncertainty used only the unusually accurate 2018 generic-ballot cycle. The 2026 model already uses a wider variance from three later cycles; do not choose a signed partisan correction from this inspected sample.",
        "evidence_hashes": {"joint_replay": digest(JOINT), "forensic_replay": digest(FORENSIC),
                            "national_snapshots": digest(SNAPSHOTS), "live_parameters": digest(PARAMETERS)},
        "chronological_2020_seven_day": {
            "house_actual_D": 222,
            "house_predicted_D": base_house["predicted_D_wins_mean"],
            "house_interval95": base_house["interval95"],
            "house_actual_percentile": base_house["actual_percentile"],
            "national_logratio_sd": prior_sd,
            "generic_terminal_proxy_error_margin": snap["generic_ballot"]["terminal_margin_error"],
            "generic_terminal_proxy_error_logratio": terminal_error,
            "generic_error_in_prior_sd_units": terminal_error / prior_sd,
            "national_error_training_cycles": base["national"]["generic_training_cycles"]},
        "current_2026": {
            "generic_observation_sd_logratio": live_sd,
            "generic_error_training_cycles": live_generic["historical_error_calibration"]["training_cycles"],
            "sd_ratio_to_2020_replay": live_sd/prior_sd},
        "forensic_sensitivity_not_a_backtest": {
            "used_later_known_2026_national_sd": live_sd,
            "house_predicted_D": stress_house["predicted_D_wins_mean"],
            "house_interval95": stress_house["interval95"],
            "actual_in_interval95": True,
            "house_actual_percentile": stress_house["actual_percentile"]},
        "limitations": [
            "The forensic floor uses post-2020 information and must not replace the chronological backtest score.",
            "One missed 95% interval among a few correlated cycles cannot identify a unique covariance correction.",
            "Generic-to-final-House errors include movement after each forecast cutoff, so they are proxy errors for a held-today forecast.",
            "The signed error is not subtracted from the 2026 generic ballot; the same inspected cycles set a variance floor only."],
    }
    out = CAL / "stage6_house_2020_audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "chronological_interval": base_house["interval95"],
                      "forensic_interval": stress_house["interval95"],
                      "2026_to_2020_national_sd_ratio": live_sd/prior_sd}, indent=2))


if __name__ == "__main__":
    main()
