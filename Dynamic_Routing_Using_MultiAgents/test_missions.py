"""Step 8 regression tests for mission planning and approved execution."""
import os
import unittest
from unittest.mock import patch
from server import Project
from mission_agent import MissionAgent


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.project = Project()
        self.key_off = patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        self.key_off.start()

    def tearDown(self):
        self.key_off.stop()

    def plan(self, message):
        return self.project.plan_mission(message)

    def test_planning_does_not_modify_network(self):
        before = self.project.state()
        proposal = self.plan("Simulate blackhole on R2")
        self.assertEqual(proposal["proposal"]["intent"], "attack")
        self.assertEqual(self.project.state()["behaviors"], before["behaviors"])
        self.assertEqual(self.project.state()["stats"], before["stats"])

    def test_approved_attack_and_recovery(self):
        p = self.plan("Simulate blackhole on R2")
        result = self.project.execute_mission(p["mission_id"])
        self.assertEqual(result["state"]["behaviors"].get("R2"), "blackhole")
        p = self.plan("Restore R2")
        result = self.project.execute_mission(p["mission_id"])
        self.assertNotIn("R2", result["state"]["behaviors"])

    def test_approved_traffic(self):
        p = self.plan("Send 4 packets per step from PC1 to S1 for 10 steps")
        self.assertEqual(p["proposal"]["rate"], 4)
        self.assertEqual(p["proposal"]["steps"], 10)
        result = self.project.execute_mission(p["mission_id"])
        self.assertEqual(result["state"]["stats"]["attempted"], 40)
        self.assertEqual(len(result["state"]["timeline"]), 10)

    def test_unapproved_missions_are_not_run(self):
        p = self.plan("Simulate grayhole on R1")
        self.assertFalse(self.project.state()["behaviors"])
        with self.assertRaises(ValueError):
            self.project.execute_mission("made-up-id")
        self.project.execute_mission(p["mission_id"])
        with self.assertRaises(ValueError):
            self.project.execute_mission(p["mission_id"])

    def test_invalid_router_rejected(self):
        with self.assertRaises(ValueError):
            self.plan("Simulate blackhole on RouterX")

    def test_scenarios_keep_existing_agents_and_topology(self):
        before = len(self.project.network.devices)
        p = self.plan("Overload R1")
        self.project.execute_mission(p["mission_id"])
        self.assertEqual(self.project.network.devices["R1"].capacity, 2)
        self.assertEqual(len(self.project.network.devices), before)
        p = self.plan("Restore R1")
        self.project.execute_mission(p["mission_id"])
        self.assertEqual(self.project.network.devices["R1"].capacity, 20)

    def test_live_route_preview(self):
        p = self.plan("Find best route from PC1 to S1")
        state = self.project.execute_mission(p["mission_id"])["state"]
        self.assertEqual(state["latest"]["route"][0], "PC1")
        self.assertEqual(state["latest"]["route"][-1], "S1")

    def test_reject_extremely_long_or_short_prompts(self):
        with self.assertRaises(ValueError):
            self.plan("Hi")
        with self.assertRaises(ValueError):
            self.plan("x"*500)

    def test_optional_gemini_parser_is_constrained(self):
        with patch.object(MissionAgent, "_gemini", return_value={"intent":"arbitrary_command", "source":"PC1", "target":"S1"}):
            with patch.dict(os.environ, {"GEMINI_API_KEY":"fake"}):
                result = self.plan("Do anything with the network")
        self.assertEqual(result["proposal"]["intent"], "inspect")

    def test_gemini_outage_falls_back_to_offline(self):
        with patch.object(MissionAgent, "_gemini", side_effect=TimeoutError("offline")):
            with patch.dict(os.environ, {"GEMINI_API_KEY":"fake"}):
                result = self.plan("Simulate blackhole on R2")
        self.assertEqual(result["proposal"]["intent"], "attack")
        self.assertEqual(result["proposal"]["mode"], "Offline fallback")


if __name__ == '__main__': unittest.main()
