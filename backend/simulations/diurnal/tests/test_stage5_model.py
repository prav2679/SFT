import unittest
from spb_stage5_model import (
    Balloon, solar_disc_fraction, implicit_quadratic_drag_step, envelope_state
)


class Stage5ModelTests(unittest.TestCase):
    def test_solar_disc_visibility_limits(self):
        self.assertEqual(solar_disc_fraction(-0.02, 0.0), 0.0)
        self.assertEqual(solar_disc_fraction(0.02, 0.0), 1.0)

    def test_implicit_drag_step_is_finite_and_preserves_sign(self):
        up = implicit_quadratic_drag_step(1.0, 0.1, 0.1, 0.45, 10.0, 6.0, 1.0)
        down = implicit_quadratic_drag_step(-1.0, -0.1, 0.1, 0.45, 10.0, 6.0, 1.0)
        self.assertGreater(up, 0.0)
        self.assertLess(down, 0.0)

    def test_rigid_envelope_holds_taut_volume(self):
        balloon = Balloon(envelope_mode="rigid")
        # Select a temperature/pressure where the free gas volume exceeds Vmax.
        volume, _ = envelope_state(balloon, 235.0, 1800.0)
        self.assertAlmostEqual(volume, balloon.max_volume_m3, places=8)

    def test_invalid_envelope_mode_is_rejected(self):
        balloon = Balloon(envelope_mode="invalid")
        with self.assertRaises(ValueError):
            envelope_state(balloon, 230.0, 1800.0)


if __name__ == "__main__":
    unittest.main()
