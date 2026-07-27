import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aoe4.session import TimerSynchronizer


class TimerSynchronizerTests(unittest.TestCase):
    def test_tracks_an_aligned_timer(self):
        synchronizer = TimerSynchronizer(tolerance=1.5, mismatch_limit=5)

        initial = synchronizer.observe(10, now=100.0)
        aligned = synchronizer.observe(15, now=105.0)

        self.assertTrue(initial.reminders_enabled)
        self.assertEqual(aligned.mode, "tracking")
        self.assertEqual(aligned.mismatch_count, 0)
        self.assertTrue(aligned.reminders_enabled)

    def test_disables_reminders_after_timer_stops_advancing(self):
        synchronizer = TimerSynchronizer(tolerance=1.5, mismatch_limit=5)
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)

        decisions = [
            synchronizer.observe(15, now=moment)
            for moment in (10.0, 11.0, 12.0, 13.0, 14.0)
        ]

        self.assertEqual(decisions[0].mode, "resyncing")
        self.assertFalse(decisions[0].reminders_enabled)
        self.assertEqual(decisions[-1].mode, "paused")
        self.assertEqual(decisions[-1].mismatch_count, 5)
        self.assertFalse(decisions[-1].reminders_enabled)

    def test_resumes_when_the_observed_timer_advances_again(self):
        synchronizer = TimerSynchronizer(tolerance=1.5, mismatch_limit=5)
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)
        for moment in (10.0, 11.0, 12.0, 13.0, 14.0):
            synchronizer.observe(15, now=moment)

        recovered = synchronizer.observe(16, now=15.0)

        self.assertEqual(recovered.mode, "tracking")
        self.assertTrue(recovered.reminders_enabled)
        self.assertEqual(recovered.estimated_seconds, 16)


if __name__ == "__main__":
    unittest.main()
