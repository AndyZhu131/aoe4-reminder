import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SOURCE_ROOT.parent
sys.path.insert(0, str(SOURCE_ROOT))

from backend.runtime.monitor import (
    AgeProgression,
    ResearchProgressTracker,
    TimerSynchronizer,
    VillagerReminderTracker,
    available_technology_keys,
    clear_debug_events,
    locked_technology_keys,
    scaled_template_scales,
    should_remind_villager,
)
from backend.shared.common import load_region
from backend.app.cli import build_parser
from backend.recognition.villager import queue_geometry
from backend.recognition.ageAndTimer import age_capture_layout, parse_timer, resolve_age_timer_rect
from backend.runtime.apm import ActionPerMinuteTracker
from backend.recognition.tech import (
    DEFAULT_TECH_CATALOG,
    DEFAULT_TECH_TEMPLATE_ROOT,
    default_research_threshold,
    load_technology_catalog,
)


ROOT = REPOSITORY_ROOT


class CalibrationProfileTests(unittest.TestCase):
    def test_reset_debug_cleanup_removes_prior_event_files(self):
        with tempfile.TemporaryDirectory() as directory:
            debug_dir = Path(directory) / "debug-events"
            debug_dir.mkdir()
            (debug_dir / "age-up.png").write_bytes(b"image")
            nested_dir = debug_dir / "prior-session"
            nested_dir.mkdir()
            (nested_dir / "research.json").write_text("{}", encoding="utf-8")

            self.assertEqual(clear_debug_events(debug_dir), 2)
            self.assertEqual(list(debug_dir.iterdir()), [])

    def test_scaled_profiles_rebase_to_the_selected_monitor(self):
        monitor = {"left": -1920, "top": 120}

        profile_1080 = ROOT / "config" / "calibration.1920x1080.json"
        profile_4k = ROOT / "config" / "calibration.3840x2160.json"

        self.assertEqual(
            load_region(profile_1080, "globalQueue", monitor),
            (-1916, 802, 390, 87),
        )
        self.assertEqual(
            load_region(profile_4k, "ageAndTimer", monitor),
            (-159, 192, 311, 293),
        )

    def test_villager_watcher_accepts_a_monitor_selection(self):
        args = build_parser().parse_args(
            ["watch-villager", "--once", "--monitor", "1"]
        )

        self.assertEqual(args.monitor, 1)

    def test_monitor_debug_events_can_be_enabled_with_a_custom_output_directory(self):
        args = build_parser().parse_args(
            [
                "watch-monitor",
                "--once",
                "--debug-events",
                "--debug-event-dir",
                "captures/diagnostics",
            ]
        )

        self.assertTrue(args.debug_events)
        self.assertEqual(args.debug_event_dir, "captures/diagnostics")
        self.assertEqual(args.age_confirmation_checks, 5)
        self.assertEqual(args.age_confirmation_wins, 4)

    def test_villager_queue_geometry_scales_with_the_profile(self):
        self.assertEqual(queue_geometry(0.75), (36, 8, 44))
        self.assertEqual(queue_geometry(1.0), (48, 10, 58))
        self.assertEqual(queue_geometry(1.5), (72, 15, 87))

    def test_research_threshold_is_calibrated_per_template_resolution(self):
        self.assertEqual(default_research_threshold("1920x1080"), 0.80)
        self.assertEqual(default_research_threshold("2560x1440"), 0.80)
        self.assertEqual(default_research_threshold("3840x2160"), 0.80)

    def test_calibrated_age_region_rebases_to_the_selected_monitor(self):
        args = SimpleNamespace(
            rect=None,
            use_calibrated_region=True,
            config=str(ROOT / "config" / "calibration.1920x1080.json"),
            monitor=2,
        )
        monitor = {"left": 2560, "top": 0, "width": 1920, "height": 1080}

        with patch("backend.recognition.ageAndTimer.load_monitor", return_value=monitor):
            self.assertEqual(resolve_age_timer_rect(args), (3441, 36, 155, 146))

    def test_age_reader_uses_the_wide_layout_for_calibrated_captures(self):
        frame = SimpleNamespace(shape=(146, 155, 3))

        roman_rect, timer_rects = age_capture_layout(frame)

        self.assertEqual(roman_rect, (52 / 155, 0.0, 70 / 155, 38 / 146))
        self.assertEqual(
            timer_rects[0],
            ("standard", (45 / 155, 60 / 146, 70 / 155, 40 / 146)),
        )


class TimerSynchronizerTests(unittest.TestCase):
    def test_timer_parser_requires_two_digits_for_minutes_and_seconds(self):
        self.assertEqual(parse_timer("00:01"), "00:01")
        self.assertEqual(parse_timer(" 99 : 59\n"), "99:59")
        self.assertIsNone(parse_timer("500:01"))
        self.assertIsNone(parse_timer("5:01"))
        self.assertIsNone(parse_timer("00:001"))
        self.assertIsNone(parse_timer("00:60"))

    def test_keeps_the_original_anchor_during_normal_tracking(self):
        synchronizer = TimerSynchronizer()

        initial = synchronizer.observe(10, now=100.0)
        tracking = synchronizer.observe(14, now=105.0)

        self.assertTrue(initial.reminders_enabled)
        self.assertEqual(tracking.mode, "tracking")
        self.assertEqual(tracking.estimated_seconds, 15)
        self.assertEqual(synchronizer.anchor_game_seconds, 10)

    def test_disables_reminders_after_three_matches_in_five_pause_checks(self):
        synchronizer = TimerSynchronizer()
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)
        started = synchronizer.observe(15, now=10.0)

        decisions = [
            synchronizer.observe(value, now=moment)
            for value, moment in (
                (15, 11.0),
                (None, 12.0),
                (15, 13.0),
                (16, 14.0),
                (15, 15.0),
            )
        ]

        self.assertEqual(started.mode, "pause_checking")
        self.assertTrue(started.reminders_enabled)
        self.assertEqual(decisions[-1].mode, "paused")
        self.assertEqual(decisions[-1].mismatch_count, 5)
        self.assertFalse(decisions[-1].reminders_enabled)

    def test_resumes_and_reanchors_from_the_first_advancing_timer_read(self):
        synchronizer = TimerSynchronizer()
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)
        synchronizer.observe(15, now=10.0)
        for moment in (11.0, 12.0, 13.0, 14.0, 15.0):
            synchronizer.observe(15, now=moment)
        recovered = synchronizer.observe(16, now=16.0)

        self.assertEqual(recovered.mode, "tracking")
        self.assertTrue(recovered.reminders_enabled)
        self.assertEqual(recovered.estimated_seconds, 16)

    def test_does_not_begin_a_pause_check_until_two_timer_reads_match(self):
        synchronizer = TimerSynchronizer()
        synchronizer.observe(10, now=0.0)
        synchronizer.observe(15, now=5.0)
        changing = synchronizer.observe(16, now=10.0)
        unchanged = synchronizer.observe(16, now=15.0)

        self.assertEqual(changing.mode, "tracking")
        self.assertEqual(unchanged.mode, "pause_checking")


class ActionPerMinuteTrackerTests(unittest.TestCase):
    def test_calculates_the_last_sixty_seconds_as_a_minute_rate(self):
        tracker = ActionPerMinuteTracker(window_seconds=60)
        tracker.record(0)
        tracker.record(30)
        tracker.record(59)

        self.assertEqual(tracker.actions_per_minute(timestamp=60), 3)
        self.assertEqual(tracker.actions_per_minute(timestamp=60.1), 2)

    def test_ignores_actions_while_game_time_is_inactive(self):
        tracker = ActionPerMinuteTracker(window_seconds=5)
        tracker.record(1)
        self.assertEqual(tracker.actions_per_minute(timestamp=1, active=False), 0)
        tracker.record(2)

        self.assertEqual(tracker.actions_per_minute(timestamp=2), 12)

    def test_reset_clears_recorded_actions(self):
        tracker = ActionPerMinuteTracker()
        tracker.record(10)
        tracker.reset()

        self.assertEqual(tracker.actions_per_minute(timestamp=10), 0)


class AgeProgressionTests(unittest.TestCase):
    def test_starts_in_age_one_and_rejects_skipped_ages(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)

        skipped = progression.observe("age_4")
        lower = progression.observe("age_1")
        missing = progression.observe(None)

        self.assertEqual(skipped.age, "age_1")
        self.assertEqual(lower.age, "age_1")
        self.assertEqual(missing.age, "age_1")

    def test_confirms_an_age_up_after_a_two_of_three_majority(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)

        decisions = [
            progression.observe(age)
            for age in ("age_2", None, "age_2")
        ]

        self.assertTrue(decisions[0].pending)
        self.assertTrue(decisions[1].pending)
        self.assertEqual(decisions[-1].age, "age_2")
        self.assertFalse(decisions[-1].pending)

    def test_confirms_age_four_after_four_hits_in_five_checks(self):
        progression = AgeProgression(confirmation_checks=5, confirmation_wins=4)

        for expected_age in ("age_2", "age_3"):
            for _ in range(5):
                progression.observe(expected_age)

        decisions = [
            progression.observe(age)
            for age in ("age_4", None, "age_4", "age_4", "age_4")
        ]

        self.assertTrue(decisions[0].pending)
        self.assertEqual(decisions[-1].age, "age_4")
        self.assertFalse(decisions[-1].pending)

    def test_discards_an_age_up_without_a_two_of_three_majority(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)

        progression.observe("age_2")
        progression.observe(None)
        rejected = progression.observe("age_1")

        self.assertEqual(rejected.age, "age_1")
        self.assertFalse(rejected.pending)

    def test_current_age_read_cancels_a_pending_advance(self):
        progression = AgeProgression(confirmation_checks=3, confirmation_wins=2)
        for age in ("age_2", None, "age_2"):
            progression.observe(age)

        progression.observe("age_3")
        progression.observe("age_3")
        cancelled = progression.observe("age_2")

        self.assertEqual(cancelled.age, "age_2")
        self.assertFalse(cancelled.pending)

    def test_discards_an_unconfirmed_age_transition(self):
        progression = AgeProgression(confirmation_checks=5, confirmation_wins=3)

        for age in ("age_2", None, "age_1", None, "age_1"):
            decision = progression.observe(age)

        self.assertEqual(decision.age, "age_1")
        self.assertFalse(decision.pending)


class VillagerReminderTests(unittest.TestCase):
    def test_requires_three_consecutive_missing_villager_checks(self):
        tracker = VillagerReminderTracker(required_misses=3)

        self.assertFalse(tracker.observe(villager_queued=False, game_seconds=60))
        self.assertFalse(tracker.observe(villager_queued=False, game_seconds=61))
        self.assertTrue(tracker.observe(villager_queued=False, game_seconds=62))
        self.assertFalse(tracker.observe(villager_queued=True, game_seconds=63))
        self.assertFalse(tracker.observe(villager_queued=False, game_seconds=64))

    def test_reminds_before_twenty_minutes_without_a_villager(self):
        self.assertTrue(
            should_remind_villager(
                villager_queued=False,
                game_seconds=(20 * 60) - 1,
            )
        )

    def test_reminds_regardless_of_food(self):
        self.assertTrue(should_remind_villager(villager_queued=False, game_seconds=60))

    def test_does_not_remind_after_twenty_minutes_or_with_a_queued_villager(self):
        self.assertFalse(
            should_remind_villager(villager_queued=False, game_seconds=20 * 60)
        )
        self.assertFalse(
            should_remind_villager(villager_queued=True, game_seconds=60)
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

    def test_sis_catalog_references_only_existing_templates(self):
        _, missing_templates = load_technology_catalog(
            Path(DEFAULT_TECH_CATALOG),
            DEFAULT_TECH_TEMPLATE_ROOT,
            ["economy", "military"],
            ["sis"],
        )

        self.assertEqual(missing_templates, [])

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

    def test_scales_canonical_templates_for_each_resolution(self):
        scales = [0.96, 1.0, 1.04]

        self.assertEqual(scaled_template_scales(scales, "1920x1080"), [0.72, 0.75, 0.78])
        self.assertEqual(scaled_template_scales(scales, "2560x1440"), scales)
        self.assertEqual(scaled_template_scales(scales, "3840x2160"), [1.44, 1.5, 1.56])

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
