# 2026 fundamentals impact

Poll cutoff: **2026-09-27T02:11:02Z**. Simulation: **75,000 paired draws**.

Each row adds one input to the preceding row using the same polls and simulated draws. These are first-stage leader comparisons; ranked-choice and runoff rules are applied to the final forecast below.

| Addition | House D seats, mean | House D 218+ | Senate D seats up, mean | Senate D 51+ if O caucuses D | Governor D wins, mean |
|---|---:|---:|---:|---:|---:|
| Base model, including governor local lean | 231.38 | 76.0% | 16.87 | 70.7% | 20.48 |
| + 2026 House district maps | 231.52 | 75.0% | 16.87 | 70.7% | 20.48 |
| + governor approval | 231.52 | 75.0% | 16.87 | 70.7% | 20.48 |
| + open seats and candidate experience | 233.65 | 77.0% | 16.99 | 71.5% | 20.48 |

## Incremental changes

| Addition | House D seats | House control | Senate D seats up | Senate control scenario | Governor D wins |
|---|---:|---:|---:|---:|---:|
| + 2026 House district maps | +0.15 | -1.0% | +0.00 | +0.0% | +0.00 |
| + governor approval | +0.00 | +0.0% | +0.00 | +0.0% | +0.00 |
| + open seats and candidate experience | +2.13 | +2.0% | +0.12 | +0.8% | +0.00 |

## Governor local-lean model

The 2026 governor baseline uses **previous_and_presidential** with ridge penalty **1.0**, selected on expanding-cycle errors through 2018. It predicts state governor lean relative to the drawn national House margin. The previous governor open-seat adjustment is disabled for governor races; open-seat status is not added a second time.

The table compares the post-national, pre-poll governor baseline before and after local-lean recentering:

| Race | Predicted local lean | Pre-poll D-R before | Pre-poll D-R after | D leader chance before | D leader chance after |
|---|---:|---:|---:|---:|---:|
| VT | -10.8 points | -49.2 points | -3.2 points | 0.5% | 45.1% |
| WY | -43.8 points | -60.4 points | -35.1 points | 0.0% | 3.8% |
| AK | -21.2 points | -33.4 points | -13.3 points | 33.2% | 67.8% |
| ID | -34.3 points | -44.7 points | -25.9 points | 0.9% | 9.2% |
| AL | -27.6 points | -34.0 points | -19.5 points | 4.4% | 17.2% |
| OH | -14.8 points | -20.0 points | -7.2 points | 16.2% | 36.3% |
| TN | -24.7 points | -27.5 points | -16.7 points | 8.7% | 20.9% |
| NE | -18.0 points | -19.4 points | -10.3 points | 17.3% | 30.8% |
| FL | -13.3 points | -14.6 points | -5.7 points | 23.8% | 39.0% |
| NH | -3.5 points | -4.8 points | +3.5 points | 40.8% | 55.1% |
| IA | -13.1 points | -13.9 points | -5.6 points | 25.0% | 39.3% |
| AR | -23.4 points | -23.1 points | -15.4 points | 12.7% | 22.7% |
| SD | -22.6 points | -22.3 points | -14.6 points | 13.5% | 23.8% |
| PA | +4.9 points | +18.5 points | +11.3 points | 82.0% | 65.9% |
| MD | +23.6 points | +36.1 points | +29.7 points | 96.5% | 92.7% |
| SC | -14.3 points | -12.7 points | -6.7 points | 26.8% | 37.4% |
| GA | -4.5 points | -3.1 points | +2.7 points | 44.3% | 55.3% |
| MA | +20.7 points | +32.3 points | +26.9 points | 94.7% | 90.9% |
| OR | +6.3 points | +7.9 points | +13.0 points | 64.9% | 73.5% |
| CO | +11.5 points | +23.1 points | +18.0 points | 87.2% | 80.9% |
| KS | -5.6 points | +6.4 points | +1.6 points | 62.2% | 52.6% |
| MI | +3.2 points | +14.5 points | +9.8 points | 75.9% | 64.2% |
| HI | +18.5 points | +29.1 points | +24.7 points | 90.4% | 86.3% |
| RI | +12.5 points | +23.0 points | +19.0 points | 86.7% | 82.0% |
| TX | -10.1 points | -6.2 points | -2.7 points | 38.1% | 44.7% |
| ME | +7.4 points | +17.2 points | +14.1 points | 79.8% | 75.4% |
| OK | -18.9 points | -9.2 points | -11.1 points | 32.8% | 29.6% |
| NY | +7.2 points | +12.1 points | +14.0 points | 72.3% | 75.3% |
| NV | -2.4 points | +2.9 points | +4.6 points | 55.4% | 56.6% |
| IL | +8.6 points | +16.5 points | +15.3 points | 78.8% | 76.9% |
| CA | +14.3 points | +21.8 points | +20.8 points | 85.8% | 84.6% |
| MN | +4.2 points | +11.9 points | +11.0 points | 71.9% | 70.5% |
| CT | +9.4 points | +15.4 points | +16.1 points | 77.4% | 78.3% |
| NM | +4.2 points | +10.6 points | +11.1 points | 69.6% | 70.3% |
| AZ | -2.4 points | +5.0 points | +4.6 points | 59.5% | 56.5% |
| WI | +0.5 points | +7.6 points | +7.5 points | 64.3% | 64.1% |

The historical terminal-result replay is an imperfect proxy for a forecast made at its historical cutoff. See `artifacts/calibration/governor_local_lean_audit.json` for the full expanding-cycle comparison.

## Final forecast with counting rules

- House Democratic control: **77.2%**.
- Senate Democratic control: **69.9%** if all elected independent or other winners caucus with Democrats; **57.1%** if they remain unaligned.
- The Senate has no single overall control estimate while independent caucus choices remain unresolved.

## Most affected races

### + 2026 House district maps

| Race | D–R mean share change | D first-stage leader change |
|---|---:|---:|
| H-2026-TX-09 | -59.79 points | -59.5% |
| H-2026-LA-06 | -43.97 points | -25.0% |
| H-2026-UT-01 | +42.39 points | +86.7% |
| H-2026-TX-32 | -41.51 points | -82.0% |
| H-2026-CA-01 | +37.69 points | +80.8% |
| H-2026-TN-09 | -25.06 points | -79.5% |
| H-2026-LA-04 | +21.42 points | +37.4% |
| H-2026-CA-02 | -20.80 points | -1.7% |
| H-2026-UT-03 | -20.64 points | -2.9% |
| H-2026-TN-08 | +20.35 points | +4.4% |

### + governor approval

| Race | D–R mean share change | D first-stage leader change |
|---|---:|---:|
| G-2026-AK | +0.00 points | +0.0% |
| G-2026-AL | +0.00 points | +0.0% |
| G-2026-AR | +0.00 points | +0.0% |
| G-2026-AZ | +0.00 points | +0.0% |
| G-2026-CA | +0.00 points | +0.0% |
| G-2026-CO | +0.00 points | +0.0% |
| G-2026-CT | +0.00 points | +0.0% |
| G-2026-FL | +0.00 points | +0.0% |
| G-2026-GA | +0.00 points | +0.0% |
| G-2026-HI | +0.00 points | +0.0% |

### + open seats and candidate experience

| Race | D–R mean share change | D first-stage leader change |
|---|---:|---:|
| H-2026-ME-02 | -11.33 points | -33.5% |
| H-2026-CA-03 | +11.10 points | +18.6% |
| H-2026-CA-41 | +10.48 points | +3.5% |
| H-2026-UT-01 | +10.35 points | +7.8% |
| H-2026-TX-09 | -7.00 points | -18.7% |
| H-2026-AZ-05 | +6.94 points | +14.3% |
| H-2026-FL-02 | +6.89 points | +11.9% |
| H-2026-GA-01 | +6.88 points | +11.3% |
| H-2026-TX-21 | +6.87 points | +10.8% |
| H-2026-IL-08 | -6.85 points | -10.3% |

## Inputs and fitted terms

- District map: [The Downballot 2026 map](https://docs.google.com/spreadsheets/d/1eZfaFI-c-PFOoKx1-zZA2MP0_dxRq_LVK0re3BOQqy0/edit?gid=1491069057) compared with [the 2024 map](https://docs.google.com/spreadsheets/d/1ng1i_Dm_RMDnEvauH44pgE6JCUsapcuu8F2pCfeLWFo/edit?gid=1491069057); 435 districts matched. Change in 2024 presidential Democratic-versus-Republican vote odds is added to the same-label prior House result.
- Governor approval: [Morning Consult](https://pro.morningconsult.com/trackers/governor-approval-ratings) net approval, surveys ending 2025-12-31. It applies only when the prior governor is running again; 0 races qualify. This snapshot is older than the poll cutoff.
- Open seat and experience (House and Senate): a seat is open when the prior winner is absent from the ballot. Experience means the candidate previously won a general election for House, Senate, or governor in the same state. The seat and experience effects are estimated from historical transitions after removing election-wide residuals.

| Office | Open-seat fitted coefficient | Prior elected winner coefficient | Active in 2026 nowcast | Training races |
|---|---:|---:|---|---:|
| house | -0.143 | +0.088 | Yes | 2455 |
| senate | -0.137 | +0.145 | Yes | 151 |
| governor | -0.255 | -0.012 | No; governor local-lean model is used | 256 |

Coefficients are shifts in D/R log vote odds. The approval coefficient is per unit of net approval on a −1 to +1 scale. Poll updates attenuate these shifts in well-polled races.

The first-stage ablation uses the current ballot registry and holds its candidate list fixed. The same-label map comparison can be less reliable where redistricting reassigned an incumbent to another district; inspect individual race rows in the JSON before treating large changes as definitive.
