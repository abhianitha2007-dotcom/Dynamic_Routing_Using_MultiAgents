"""Step 5 tests: Q-Learning, topology compatibility, packet feedback."""
import unittest
from pathlib import Path
from network import Network
from agents import MainAgent
from demo_step4 import create_demo


class QLearningTests(unittest.TestCase):
    def setUp(self):
        self.main = MainAgent(create_demo())
        self.main.set_routing_mode("qlearning")

    def test_sample_topology_json(self):
        net = Network.load(Path(__file__).with_name("topology.json"))
        self.assertEqual(len(net.devices), 5)
        self.assertEqual(len(net.links), 5)
        main = MainAgent(net)
        main.set_routing_mode("qlearning")
        self.assertEqual(main.send_packet("PC1", "S1")["route"],
                         ["PC1", "SW1", "R2", "S1"])

    def test_shortest_route_in_normal_network(self):
        result = self.main.send_packet("PC1", "Server1")
        self.assertEqual(result["route"], ["PC1", "SW1", "R1", "Server1"])
        self.assertEqual(result["delay_ms"], 3)
        self.assertTrue(result["delivered"])

    def test_switches_to_backup_when_router_offline(self):
        self.main.network.set_device_status("R1", False)
        self.assertEqual(self.main.send_packet("PC1", "Server1")["route"],
                         ["PC1", "SW1", "R2", "Server1"])

    def test_avoids_untrusted_router(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        report = self.main.send_traffic("PC1", "Server1", 1, 14)
        routes = [tuple(row["route"] or []) for row in report["timeline"]]
        self.assertEqual(routes[0], ("PC1", "SW1", "R1", "Server1"))
        self.assertIn(("PC1", "SW1", "R2", "Server1"), routes)
        self.assertGreater(report["drop_reasons"].get("unexplained", 0), 0)

    def test_qtable_updates_from_packet_outcomes(self):
        learner = self.main.agents["qlearning"]
        self.main.send_traffic("PC1", "Server1", 1, 8)
        self.assertGreater(len(learner.q), 0)
        self.assertGreater(learner.feedback, 0)

    def test_congestion_can_change_route(self):
        from test_traffic import make_network
        main = MainAgent(make_network())
        main.set_routing_mode("qlearning")
        result = main.send_traffic("PC1", "Server1", 8, 6)
        routes = [tuple(x["route"] or []) for x in result["timeline"]]
        self.assertIn(("PC1", "SW1", "R2", "Server1"), routes)

    def test_disconnected_reports_no_route(self):
        self.main.network.set_device_status("R1", False)
        self.main.network.set_device_status("R2", False)
        self.assertFalse(self.main.send_packet("PC1", "Server1")["delivered"])

    def test_mode_selection_and_four_step_agent(self):
        self.assertEqual(self.main.routing_mode, "qlearning")
        self.main.set_routing_mode("dijkstra")
        self.assertEqual(self.main.routing_mode, "dijkstra")
        with self.assertRaises(ValueError):
            self.main.set_routing_mode("bad")
        learner = self.main.agents["qlearning"]
        for method in ("assess", "plan", "act", "check"):
            self.assertTrue(callable(getattr(learner, method)))

    def test_learner_works_with_custom_topology(self):
        net = Network()
        for name, kind in (("HOME", "PC"), ("X", "ROUTER"),
                           ("Y", "ROUTER"), ("DATA", "SERVER")):
            net.add_device(name, kind)
        for a, b, delay in (("HOME", "X", 1), ("X", "DATA", 1),
                            ("HOME", "Y", 3), ("Y", "DATA", 3)):
            net.connect(a, b, delay)
        main = MainAgent(net)
        main.set_routing_mode("qlearning")
        self.assertEqual(main.send_packet("HOME", "DATA")["route"],
                         ["HOME", "X", "DATA"])


if __name__ == "__main__":
    unittest.main()
