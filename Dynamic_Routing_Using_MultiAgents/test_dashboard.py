"""Tests for Step 6 UI API integration (no browser or extra packages required)."""
import json
import unittest
from pathlib import Path
from server import Project


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.project = Project()

    def update(self, **action):
        return self.project.apply(action)["state"]

    def test_example_contains_saved_topology(self):
        state = self.project.state()
        self.assertEqual(len(state["devices"]), 5)
        self.assertEqual(len(state["links"]), 5)
        self.assertEqual({d["name"] for d in state["devices"]},
                         {"PC1", "SW1", "R1", "R2", "S1"})

    def test_add_connect_and_drag_custom_nodes(self):
        self.update(op="add_device", name="R3", kind="ROUTER", x=450, y=240)
        self.update(op="connect", a="R2", b="R3", delay=5, bandwidth=100)
        self.update(op="move_device", name="R3", x=612, y=455)
        self.assertEqual(self.project.positions["R3"], [612, 455])
        self.assertEqual(len(self.project.network.links), 6)

    def test_import_legacy_topology_and_export(self):
        old = json.loads((Path(__file__).parent / "topology.json").read_text())
        state = self.update(op="import", topology=old)
        self.assertEqual(len({(d["x"], d["y"]) for d in state["devices"]}), 5)
        self.assertEqual(len(self.project.topology()["devices"]), 5)

    def test_simulation_step_updates_counters_and_graph(self):
        self.update(op="routing_mode", mode="qlearning")
        state = self.update(op="step", source="PC1", target="S1", rate=4)
        self.assertEqual(state["stats"]["attempted"], 4)
        self.assertEqual(state["latest"]["route"][-1], "S1")
        self.assertEqual(len(state["timeline"]), 1)
        self.assertGreater(state["q_entries"], 0)

    def test_blackhole_recovery_under_light_load(self):
        self.update(op="routing_mode", mode="qlearning")
        self.update(op="behavior", name="R2", mode="blackhole")
        routes = []
        for _ in range(14):
            s = self.update(op="step", source="PC1", target="S1", rate=1)
            routes.append(s["latest"]["route"])
        self.assertIn("R2", routes[0])
        self.assertIn("R1", routes[-1])
        self.assertIn("R2", s["untrusted"])
        self.assertEqual(s["stats"]["attempted"], 14)
        self.assertGreater(s["stats"]["delivered"], 0)

    def test_repair_restores_trust_and_behavior(self):
        self.update(op="behavior", name="R2", mode="blackhole")
        for _ in range(5):
            self.update(op="step", source="PC1", target="S1", rate=1)
        state = self.update(op="repair", name="R2")
        self.assertNotIn("R2", state["behaviors"])
        self.assertEqual(state["trust"]["R2"], 1.0)

    def test_compare_returns_both_routes(self):
        s = self.update(op="compare", source="PC1", target="S1")
        self.assertEqual(s["latest"]["dijkstra"][0], "PC1")
        self.assertEqual(s["latest"]["qlearning"][-1], "S1")

    def test_topology_changes_reset_traffic_and_not_positions(self):
        self.update(op="step", source="PC1", target="S1", rate=2)
        original = self.project.positions["R2"][:]
        self.update(op="connect", a="R1", b="R2", delay=1, bandwidth=100)
        self.assertEqual(self.project.state()["stats"]["attempted"], 0)
        self.assertEqual(self.project.positions["R2"], original)

    def test_invalid_end_device_behavior_rejected(self):
        with self.assertRaises(ValueError):
            self.update(op="behavior", name="PC1", mode="blackhole")

    def test_cannot_overrun_traffic_limits(self):
        with self.assertRaises(ValueError):
            self.update(op="step", source="PC1", target="S1", rate=201)


if __name__ == '__main__':
    unittest.main()
