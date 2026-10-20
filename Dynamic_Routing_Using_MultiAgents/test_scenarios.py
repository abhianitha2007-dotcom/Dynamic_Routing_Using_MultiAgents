"""Scenario Studio actions must change real agent state, not just the frontend."""
import unittest
from server import Project

class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.p = Project()
    def use(self, **kw):
        return self.p.apply(kw)["state"]
    def test_blackhole_apply_and_restore(self):
        s = self.use(op="behavior", name="R2", mode="blackhole")
        self.assertEqual(s["behaviors"]["R2"], "blackhole")
        for _ in range(5):
            s = self.use(op="step", source="PC1", target="S1", rate=1)
        self.assertLess(s["trust"]["R2"], 1.0)
        s = self.use(op="repair", name="R2")
        self.assertEqual(s["trust"]["R2"], 1.0)
        self.assertNotIn("R2", s["behaviors"])
    def test_overload_preserves_original_device_settings(self):
        d = self.p.network.devices["R2"]
        original = (d.capacity, d.queue_limit)
        s = self.use(op="overload", name="R2", capacity=2, queue_limit=8)
        self.assertIn("R2", s["overloads"])
        self.assertEqual((d.capacity, d.queue_limit), (2,8))
        s = self.use(op="restore_limits", name="R2")
        self.assertEqual((d.capacity, d.queue_limit), original)
        self.assertNotIn("R2", s["overloads"])
    def test_congestion_policy_controls_routing(self):
        s = self.use(op="congestion_settings", enabled=False, threshold=.45)
        self.assertFalse(s["congestion_settings"]["enabled"])
        self.assertAlmostEqual(s["congestion_settings"]["threshold"],.45)
        self.use(op="overload", name="R2", capacity=2, queue_limit=8)
        for _ in range(6):
            s = self.use(op="step", source="PC1", target="S1", rate=8)
        self.assertEqual(s["busy"], [])
        self.use(op="congestion_settings", enabled=True, threshold=.45)
        s = self.use(op="step", source="PC1", target="S1", rate=8)
        self.assertIn("R2", s["busy"])
    def test_invalid_setup_is_rejected(self):
        for kw in [dict(op="overload",name="PC1",capacity=2,queue_limit=6),
                   dict(op="overload",name="R2",capacity=0,queue_limit=5),
                   dict(op="congestion_settings",enabled=True,threshold=1.2)]:
            with self.assertRaises(ValueError): self.use(**kw)
    def test_sample_topology_exists(self):
        self.assertEqual(len(self.p.state()["devices"]),5)
        self.assertIn("R2", self.p.state()["trust"])

if __name__ == "__main__": unittest.main()
