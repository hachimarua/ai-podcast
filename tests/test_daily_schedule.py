import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daily_schedule


class DailyScheduleTests(unittest.TestCase):
    def test_waits_before_daily_time_and_lands_on_wall_clock(self):
        now = datetime.fromisoformat("2026-07-23T06:29:45+09:00")
        self.assertEqual(daily_schedule.poll_delay((6, 30), now), 15)

    def test_startup_after_time_catches_up_once(self):
        now = datetime.fromisoformat("2026-07-23T08:00:00+09:00")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "schedule.json"
            run = daily_schedule.claim_daily_run(state_path, "radio", (6, 30), now)
            self.assertEqual(run.trigger, "startup_catchup")
            daily_schedule.finish_daily_run(
                state_path,
                run,
                success=True,
                completed_at=now,
            )
            self.assertIsNone(
                daily_schedule.claim_daily_run(state_path, "radio", (6, 30), now)
            )

    def test_wake_after_time_is_classified_as_wake_catchup(self):
        previous = datetime.fromisoformat("2026-07-22T22:14:00+09:00")
        now = datetime.fromisoformat("2026-07-23T06:52:00+09:00")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "schedule.json"
            run = daily_schedule.claim_daily_run(
                state_path,
                "radio",
                (6, 30),
                now,
                previous_tick=previous,
            )
            self.assertEqual(run.trigger, "wake_catchup")
            self.assertEqual(run.delay_seconds, 22 * 60)


if __name__ == "__main__":
    unittest.main()
