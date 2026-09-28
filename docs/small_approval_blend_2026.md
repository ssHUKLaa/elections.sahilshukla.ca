# Small approval contribution for the next nowcast (version 0.6)

Following the [generic-first version 0.5 run](generic_first_nowcast_2026.md), the model code now gives the approval-and-previous-House-vote estimate a **5%** contribution to the shared national D/R center. The quality-weighted generic ballot contributes **95%**. Both are combined on the D/R log-odds scale:

`national_mean = 0.95 * generic_mean + 0.05 * approval_structural_mean`

This weight is an explicit small policy choice requested for the well-polled 2026 cycle, **not** a coefficient learned from the limited historical ablation. The previous independent Gaussian update is still available as `approval_prior_plus_generic_legacy`, and a `generic_only` comparison is also recorded.

Because the correlation between generic and approval errors is not identified, the blend uses the maximum standard deviation allowed by their two marginal standard deviations and any correlation from −1 to +1:

`national_sd = 0.95 * generic_sd + 0.05 * approval_structural_sd`

This corresponds to perfect positive error correlation and prevents the extra signal from artificially narrowing the national interval. The two component SDs remain provisional for a held-today nowcast, so this bound is not a fully calibrated coverage guarantee.

**Run status:** The full pipeline was rerun on September 23, 2026, after the owner requested the three additional fundamentals. The validated version 0.7 artifact includes this 5% blend. The Stage 5 validator checks its mean and uncertainty rule. See `artifacts/nowcast/fundamentals_impact_2026.md` for the new paired comparison.
