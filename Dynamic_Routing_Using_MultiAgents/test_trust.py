"""Step 4 regression: simulated behavior, trust updates, and rerouting."""
import unittest
from agents import MainAgent
from network import Network
from traffic import TrafficSimulator
from demo_step4 import create_demo


class TrustTests(unittest.TestCase):
    def setUp(self):
        self.main = MainAgent(create_demo())

    def test_rejects_unknown_and_end_devices_as_attack_targets(self):
        with self.assertRaises(ValueError):
            self.main.simulator.set_behavior("PC1", "blackhole")
        with self.assertRaises(ValueError):
            self.main.simulator.set_behavior("missing", "grayhole")
        with self.assertRaises(ValueError):
            self.main.simulator.set_behavior("R1", "wrong")

    def test_blackhole_causes_unexplained_loss_and_avoids_router(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        report = self.main.send_traffic("PC1", "Server1", 1, 14)
        routes = [tuple(x["route"] or []) for x in report["timeline"]]
        self.assertEqual(routes[0], ("PC1", "SW1", "R1", "Server1"))
        self.assertIn(("PC1", "SW1", "R2", "Server1"), routes)
        self.assertIn("R1", report["timeline"][3]["untrusted"])
        self.assertGreater(report["dropped"], 0)
        self.assertGreater(report["drop_reasons"].get("unexplained", 0), 0)

    def test_recovery_delivers_remaining_packets(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        self.main.send_traffic("PC1", "Server1", 1, 14)
        self.main.send_traffic("", "", 0, 8)
        stats = self.main.simulator.status()
        self.assertGreater(stats["delivered"], 0)
        self.assertEqual(stats["in_flight"], 0)
        self.assertEqual(stats["attempted"], stats["delivered"] + stats["dropped"])

    def test_grayhole_forwards_some_and_drops_some(self):
        self.main.simulator.set_behavior("R1", "grayhole")
        self.main.send_traffic("PC1", "Server1", 1, 5)
        self.main.send_traffic("", "", 0, 6)
        events = self.main.simulator.node_events["R1"]
        self.assertGreater(events["forwarded"], 0)
        self.assertGreater(events["unexplained"], 0)

    def test_trust_does_not_penalize_congestion_drops(self):
        net = Network()
        net.add_device("A", "PC", capacity=20, queue_limit=20)
        net.add_device("R", "ROUTER", capacity=1, queue_limit=2)
        net.add_device("B", "SERVER", capacity=20, queue_limit=20)
        net.connect("A", "R", 1, 100)
        net.connect("R", "B", 1, 100)
        main = MainAgent(net)
        main.send_traffic("A", "B", 8, 3)
        self.assertGreater(main.simulator.drop_reasons["congestion"], 0)
        self.assertEqual(main.agents["trust"].scores["R"], 1.0)
        self.assertNotIn("R", main.agents["trust"].run({
            "network": net, "simulator": main.simulator
        })["untrusted_nodes"])

    def test_repeated_checks_do_not_double_penalize(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        self.main.send_traffic("PC1", "Server1", 1, 4)
        trust = self.main.agents["trust"]
        score = trust.scores["R1"]
        task = {"network": self.main.network, "simulator": self.main.simulator}
        trust.run(task)
        trust.run(task)
        self.assertEqual(score, trust.scores["R1"])

    def test_trust_is_bounded(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        self.main.send_traffic("PC1", "Server1", 1, 20)
        self.assertTrue(all(0 <= s <= 1 for s in self.main.agents["trust"].scores.values()))

    def test_no_backup_does_not_use_untrusted_router(self):
        net = create_demo()
        net.set_device_status("R2", False)
        main = MainAgent(net)
        main.simulator.set_behavior("R1", "blackhole")
        report = main.send_traffic("PC1", "Server1", 1, 10)
        self.assertTrue(any(x["route"] is None for x in report["timeline"]))
        self.assertGreater(main.simulator.drop_reasons["no_route"], 0)

    def test_reset_trust_after_repair(self):
        self.main.simulator.set_behavior("R1", "blackhole")
        self.main.send_traffic("PC1", "Server1", 1, 10)
        trust = self.main.agents["trust"]
        self.assertLess(trust.scores["R1"], 0.5)
        self.main.simulator.set_behavior("R1", "normal")
        trust.reset("R1")
        self.assertEqual(trust.scores["R1"], 1.0)
        report = self.main.send_traffic("PC1", "Server1", 1, 1)
        self.assertEqual(report["timeline"][0]["route"], ["PC1", "SW1", "R1", "Server1"])

    def test_all_agents_follow_four_steps(self):
        for agent in self.main.agents.values():
            for method in ("assess", "plan", "act", "check"):
                self.assertTrue(callable(getattr(agent, method)))


if __name__ == "__main__":
    unittest.main()
