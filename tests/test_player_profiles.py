"""Regression tests for the opt-in GIEC G2805 test profile."""
import unittest
from player_profiles import PLAYER_PROFILES, encode_targets


class PlayerProfilesTests(unittest.TestCase):
    def test_universal_mode_does_not_change_bitrate(self):
        self.assertEqual(encode_targets("universal", 28_000_000, 640_000), (28_000_000, None))

    def test_g2805_sets_conservative_test_targets(self):
        self.assertEqual(encode_targets("giec-g2805", 28_000_000, 640_000), (24_000_000, 26_000_000))
        self.assertEqual(encode_targets("giec-g2805", 12_000_000, 640_000), (12_000_000, 26_000_000))

    def test_audio_peak_reduces_video_peak_and_target(self):
        self.assertEqual(encode_targets("giec-g2805", 28_000_000, 9_000_000), (22_000_000, 22_000_000))
        with self.assertRaisesRegex(ValueError, "аудиобитрейт"):
            encode_targets("giec-g2805", 24_000_000, 28_000_000)

    def test_profile_must_be_known(self):
        self.assertIn("giec-g2805", PLAYER_PROFILES)
        with self.assertRaisesRegex(ValueError, "профиль"):
            encode_targets("unknown", 15_000_000, 640_000)


if __name__ == "__main__":
    unittest.main()
