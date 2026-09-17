import time
import unittest

from gitbot.health import ALERT_AFTER, Health


class HealthTests(unittest.TestCase):
    def test_unregistered_is_noop(self):
        h = Health()
        h.ok("nope")
        self.assertEqual(h.fail("nope", "x"), 0)
        self.assertTrue(h.healthy())

    def test_ok_clears_failures(self):
        h = Health()
        h.register("pr", 60)
        self.assertEqual(h.fail("pr", "boom"), 1)
        self.assertEqual(h.fail("pr", "boom"), 2)
        h.ok("pr")
        snap = h.snapshot()
        self.assertEqual(snap["components"]["pr"]["fails"], 0)
        self.assertEqual(snap["components"]["pr"]["last_error"], "")

    def test_fail_counts_up_to_alert_threshold(self):
        h = Health()
        h.register("rel", 300)
        counts = [h.fail("rel", "e") for _ in range(ALERT_AFTER)]
        self.assertEqual(counts[-1], ALERT_AFTER)

    def test_no_cycle_within_grace_is_healthy(self):
        h = Health()
        now = time.time()
        h.register("pr", 60)
        # inside the grace window (3 intervals) with no cycle yet
        self.assertTrue(h.healthy(now + 100))

    def test_missing_first_cycle_goes_stale(self):
        h = Health()
        now = time.time()
        h.register("pr", 60)
        # past 3 intervals (180s) with no cycle
        self.assertFalse(h.healthy(now + 200))

    def test_recent_ok_is_fresh_then_goes_stale(self):
        h = Health()
        h.register("pr", 60)
        h.ok("pr")
        base = time.time()
        self.assertTrue(h.healthy(base + 10))
        self.assertFalse(h.healthy(base + 500))

    def test_snapshot_shape(self):
        h = Health()
        h.register("pr", 90)
        h.ok("pr")
        snap = h.snapshot()
        self.assertIn("ok", snap)
        self.assertIn("uptime_seconds", snap)
        self.assertIn("pr", snap["components"])
        c = snap["components"]["pr"]
        self.assertTrue(c["ok"])
        self.assertIsNotNone(c["last_ok_age_seconds"])

    def test_overall_ok_false_when_any_stale(self):
        h = Health()
        h.register("pr", 60)
        h.register("rel", 60)
        h.ok("pr")
        h.ok("rel")
        base = time.time()
        self.assertTrue(h.healthy(base + 10))
        # rel stays fresh only up to its window; push well past it
        self.assertFalse(h.healthy(base + 1000))
