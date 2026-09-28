# Wikipedia and state-source candidate cross-check

The national aggregation snapshot was compared with the 161 races already covered by reviewed state sources. Candidate names were normalized to first and last name for this audit, ignoring middle initials and suffixes. State-source entries remain authoritative when the sources differ.

Snapshot revisions:

- House: `1375857628` (20 September 2026 at 14:26:46 UTC)
- Senate: `1375971650` (21 September 2026 at 05:15:55 UTC)
- Governors: `1375826994` (20 September 2026 at 08:51:45 UTC)

Results:

- 151 of 161 state-reviewed race candidate sets matched after name normalization.
- Three differences were alternate name forms: John/Johnny Olszewski in Maryland 2, Mahesh/Max Ganorkar in North Carolina 4, and Steven/Steve Feldman in North Carolina 10.
- Wikipedia omitted seven entries present in state sources: Pat Dixon (TX governor, Libertarian), Edward Shlikas (MD-01, independent), Mildred Marie Hall (MD-05, other), Michael Dublin (NC Senate, Green), Jami Dee Woodman (MT Senate, nonpartisan), Collin Corbett (IL governor, independent), and Whitfield Harrington Jr. (IL Senate, American Center).

The omissions show why the source hierarchy matters. Wikipedia provides complete race coverage quickly, while reviewed state lists replace it race by race and preserve minor-party candidates that a national summary can miss. Stage 1 should rerun this comparison after each new snapshot and alert on a candidate-set change.
