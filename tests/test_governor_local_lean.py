import unittest

import numpy as np

from modeling.governor_local_lean import prior_presidential_lean, recenter_candidate_draws, two_party_margin


class GovernorLocalLeanTests(unittest.TestCase):
    def test_two_party_margin_excludes_other_vote(self):
        self.assertAlmostEqual(two_party_margin([0.4, 0.5, 0.1]), -1 / 9)
        self.assertIsNone(two_party_margin([0.0, 0.0, 1.0]))

    def test_presidential_feature_uses_latest_result_before_target(self):
        history = {2016: {"OK": -0.4}, 2020: {"OK": -0.3}, 2024: {"TX": -0.1}}
        self.assertEqual(prior_presidential_lean(history, 2026, "OK"), (2020, -0.3))
        self.assertIsNone(prior_presidential_lean(history, 2016, "OK"))

    def test_recenter_hits_fitted_two_party_margin_and_preserves_total_share(self):
        draws = np.tile([0.40, 0.50, 0.10], (20, 1)).astype(float)
        national_logratio = np.log(0.55 / 0.45)
        local_lean = -0.05
        adjusted, report = recenter_candidate_draws(
            draws.copy(), ["D", "R", "O"], national_logratio, local_lean,
        )
        expected = np.tanh(national_logratio / 2) + local_lean
        actual = (adjusted[:, 0] - adjusted[:, 1]) / (adjusted[:, 0] + adjusted[:, 1])
        np.testing.assert_allclose(actual, expected)
        np.testing.assert_allclose(adjusted.sum(axis=1), 1.0)
        self.assertEqual(report["applied"], 1.0)


if __name__ == "__main__":
    unittest.main()
