import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aoe4.monitor import (
    AgeProgression,
    ResearchProgressTracker,
    TimerSynchronizer,
    available_technology_keys,
    locked_technology_keys,
    should_remind_villager,
)


class TimerSynchronizerTests(unittest.TestCase):
    def test_tracks_an_aligned_timer(self):
        synchronizer = TimerSynchronizer(
            tolerance=1.5,
            confirmation_checks=5,
            confirmation_wins=3,
        )

        initial = synchronizer.observe(10, now=100.0)
        aligned = synchronizer.observe(15, now=105.0)

        self.assertTrue(initial.reminders_enabled)
        self.assertEqual(aligned.mode, "tracking")
        self.assertEqual(aligned.mismatch_count, 0)
        self.assertTrue(aligned.reminders_enabled)

    def test_disables_reminders_after_timer_stops_advancing(self):
        synchronizer = TimerSynchronizer(
            tolerance=1.5,
            confirmation_checks=5,
            confirmation_wins=3,
        )
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)

        decisions = [
            synchronizer.observe(15, now=moment)
            for moment in (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)
        ]

        self.assertEqual(decisions[0].mode, "resyncing")
        self.assertTrue(decisions[0].reminders_enabled)
        self.assertEqual(decisions[-1].mode, "paused")
        self.assertEqual(decisions[-1].mismatch_count, 6)
        self.assertFalse(decisions[-1].reminders_enabled)

    def test_resumes_when_the_observed_timer_advances_again(self):
        synchronizer = TimerSynchronizer(
            tolerance=1.5,
            confirmation_checks=5,
            confirmation_wins=3,
        )
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)
        for moment in (10.0, 11.0, 12.0, 13.0, 14.0, 15.0):
            synchronizer.observe(15, now=moment)

        for value, moment in ((16, 16.0), (17, 17.0), (18, 18.0), (19, 19.0)):
            synchronizer.observe(value, now=moment)
        recovered = synchronizer.observe(20, now=20.0)

        self.assertEqual(recovered.mode, "tracking")
        self.assertTrue(recovered.reminders_enabled)
        self.assertEqual(recovered.estimated_seconds, 20)

    def test_accepts_a_paused_timer_with_five_matching_reads_in_six_samples(self):
        synchronizer = TimerSynchronizer(
            tolerance=1.5,
            confirmation_checks=5,
            confirmation_wins=3,
        )
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)

        decisions = [
            synchronizer.observe(value, now=moment)
            for value, moment in (
                (15, 10.0),
                (None, 11.0),
                (15, 12.0),
                (15, 13.0),
                (15, 14.0),
                (15, 15.0),
            )
        ]

        self.assertEqual(decisions[-1].mode, "paused")
        self.assertFalse(decisions[-1].reminders_enabled)


class AgeProgressionTests(unittest.TestCase):
    def test_accepts_the_first_recognized_age_and_never_moves_backward(self):
        progression = AgeProgression(confirmation_checks=5, confirmation_wins=3)

        initial = progression.observe("age_2")
        lower = progression.observe("age_1")
        missing = progression.observe(None)

        self.assertEqual(initial.age, "age_2")
        self.assertEqual(lower.age, "age_2")
        self.assertEqual(missing.age, "age_2")

    def test_confirms_an_age_up_after_a_two_of_three_majority(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)
        progression.observe("age_2")

        decisions = [
            progression.observe(age)
            for age in ("age_3", None, "age_3")
        ]

        self.assertTrue(decisions[0].pending)
        self.assertTrue(decisions[1].pending)
        self.assertEqual(decisions[-1].age, "age_3")
        self.assertFalse(decisions[-1].pending)

    def test_discards_an_age_up_without_a_two_of_three_majority(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)
        progression.observe("age_2")

        progression.observe("age_3")
        progression.observe(None)
        rejected = progression.observe("age_2")

        self.assertEqual(rejected.age, "age_2")
        self.assertFalse(rejected.pending)

    def test_discards_an_unconfirmed_age_transition(self):
        progression = AgeProgression(confirmation_checks=5, confirmation_wins=3)
        progression.observe("age_2")

        for age in ("age_3", None, "age_2", "age_3", None):
            decision = progression.observe(age)

        self.assertEqual(decision.age, "age_2")
        self.assertFalse(decision.pending)


class VillagerReminderTests(unittest.TestCase):
    def test_reminds_before_twenty_minutes_with_more_than_fifty_food(self):
        self.assertTrue(
            should_remind_villager(
                food=51,
                villager_queued=False,
                game_seconds=(20 * 60) - 1,
            )
        )

    def test_does_not_remind_at_or_below_the_food_threshold(self):
        self.assertFalse(
            should_remind_villager(food=50, villager_queued=False, game_seconds=60)
        )

    def test_does_not_remind_after_twenty_minutes_or_with_a_queued_villager(self):
        self.assertFalse(
            should_remind_villager(food=100, villager_queued=False, game_seconds=20 * 60)
        )
        self.assertFalse(
            should_remind_villager(food=100, villager_queued=True, game_seconds=60)
        )


class TechnologyReminderTests(unittest.TestCase):
    technologies = [
        {"key": "wheelbarrow", "ageAvailable": "dark", "prerequisites": []},
        {
            "key": "wood_1",
            "ageAvailable": "feudal",
            "prerequisites": [],
            "previewBeforeAge": True,
        },
        {"key": "wood_2", "ageAvailable": "castle", "prerequisites": ["wood_1"]},
        {"key": "wood_3", "ageAvailable": "imperial", "prerequisites": ["wood_2"]},
    ]

    def test_only_age_one_technologies_are_available_in_age_one(self):
        self.assertEqual(
            available_technology_keys(self.technologies, "age_1", set()),
            ["wheelbarrow"],
        )

    def test_unresearched_technology_carries_forward_to_later_ages(self):
        self.assertEqual(
            available_technology_keys(self.technologies, "age_3", set()),
            ["wheelbarrow", "wood_1"],
        )

    def test_upgrade_levels_require_the_previous_level(self):
        self.assertEqual(
            available_technology_keys(self.technologies, "age_3", {"wood_1"}),
            ["wheelbarrow", "wood_2"],
        )
        self.assertEqual(
            available_technology_keys(
                self.technologies,
                "age_4",
                {"wood_1", "wood_2"},
            ),
            ["wheelbarrow", "wood_3"],
        )

    def test_next_upgrade_is_a_locked_preview_before_its_age(self):
        self.assertEqual(
            locked_technology_keys(
                self.technologies,
                "age_2",
                {"wood_1"},
            ),
            ["wood_2"],
        )
        self.assertEqual(
            locked_technology_keys(
                self.technologies,
                "age_3",
                {"wood_1", "wood_2"},
            ),
            ["wood_3"],
        )

    def test_age_one_previews_the_first_feudal_upgrade(self):
        self.assertEqual(
            locked_technology_keys(self.technologies, "age_1", set()),
            ["wood_1"],
        )

    def test_research_becomes_active_after_six_matches_in_ten_queue_reads(self):
        tracker = ResearchProgressTracker(
            confirmation_checks=10,
            confirmation_wins=6,
            completion_delay_seconds=30,
        )

        for game_seconds, detected in enumerate(([["wood_1"]] * 6) + ([[]] * 4)):
            tracker.observe(detected, game_seconds)

        self.assertEqual(tracker.in_progress, {"wood_1"})
        self.assertEqual(tracker.researched, set())

    def test_research_completes_thirty_game_seconds_after_confirmation(self):
        tracker = ResearchProgressTracker(
            confirmation_checks=10,
            confirmation_wins=6,
            completion_delay_seconds=30,
        )
        for game_seconds in range(10):
            tracker.observe(["wood_1"], game_seconds)
        self.assertEqual(tracker.in_progress, {"wood_1"})

        tracker.observe([], 38)
        self.assertEqual(tracker.in_progress, {"wood_1"})

        tracker.observe([], 39)
        self.assertEqual(tracker.in_progress, set())
        self.assertEqual(tracker.researched, {"wood_1"})


if __name__ == "__main__":
    unittest.main()
