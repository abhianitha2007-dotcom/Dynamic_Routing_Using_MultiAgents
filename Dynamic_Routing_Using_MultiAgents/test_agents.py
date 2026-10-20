"""Step 2 tests. Run python -m unittest -v"""
import unittest
from agents import MainAgent, RoutingAgent
from network import Network


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.network = Network()
        for name, kind in [
            ("PC1", "PC"), ("SW1", "SWITCH"),
            ("R1", "ROUTER"), ("R2", "ROUTER"),
            ("Server1", "SERVER"),
        ]:
            self.network.add_device(name, kind)
        for a, b, delay in [
            ("PC1", "SW1", 1), ("SW1", "R1", 2),
            ("R1", "Server1", 2), ("SW1", "R2", 3),
            ("R2", "Server1", 3),
        ]:
            self.network.connect(a, b, delay)
        self.main = MainAgent(self.network)

    def test_normal_routing(self):
        result = self.main.send_packet("PC1", "Server1")
        self.assertEqual(result["route"], ["PC1", "SW1", "R1", "Server1"])
        self.assertEqual(result["delay_ms"], 5)
        self.assertTrue(result["delivered"])

    def test_offline_router_uses_backup_path(self):
        self.network.set_device_status("R1", False)
        result = self.main.send_packet("PC1", "Server1")
        self.assertEqual(result["route"], ["PC1", "SW1", "R2", "Server1"])
        self.assertTrue(result["delivered"])

    def test_disabled_link_uses_backup_path(self):
        self.network.set_link_status("SW1", "R1", False)
        self.assertEqual(self.main.send_packet("PC1", "Server1")["route"],
                         ["PC1", "SW1", "R2", "Server1"])

    def test_disconnected_returns_failure(self):
        self.network.set_device_status("R1", False)
        self.network.set_device_status("R2", False)
        result = self.main.send_packet("PC1", "Server1")
        self.assertIsNone(result["route"])
        self.assertFalse(result["delivered"])

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            self.main.send_packet("Unknown", "Server1")

    def test_offline_source_fails(self):
        self.network.set_device_status("PC1", False)
        self.assertFalse(self.main.send_packet("PC1", "Server1")["delivered"])

    def test_servers_not_used_as_transit_routers(self):
        self.network.add_device("PC2", "PC")
        self.network.connect("Server1", "PC2", 1)
        self.assertIsNone(self.main.send_packet("PC1", "PC2")["route"])

    def test_records_history(self):
        self.main.send_packet("PC1", "Server1")
        self.assertEqual(len(self.main.history), 1)
        self.assertEqual(self.main.history[0]["source"], "PC1")
        self.assertEqual(len(self.main.activity), 6)  # trust, routing, delivery

    def test_each_agent_has_four_methods(self):
        for agent in self.main.agents.values():
            for method in ("assess", "plan", "act", "check"):
                self.assertTrue(callable(getattr(agent, method)))

    def test_mid_delivery_link_failure_detected(self):
        task = {"network": self.network, "source": "PC1", "target": "Server1"}
        route = RoutingAgent().run(task)
        self.assertIsNotNone(route)
        self.network.set_link_status("R1", "Server1", False)
        result = self.main.agents["delivery"].run(task)
        self.assertFalse(result["delivered"])


if __name__ == "__main__":
    unittest.main()
