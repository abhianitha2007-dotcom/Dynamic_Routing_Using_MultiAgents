"""Step 3 tests for queues, bandwidth, agents, and congestion rerouting."""
import unittest
from network import Network
from traffic import TrafficSimulator
from agents import MainAgent


def make_network():
    net = Network()
    for name, kind, capacity, limit in [
        ("PC1", "PC", 20, 50),
        ("SW1", "SWITCH", 30, 60),
        ("R1", "ROUTER", 2, 8),
        ("R2", "ROUTER", 20, 50),
        ("Server1", "SERVER", 25, 50),
    ]:
        net.add_device(name, kind, capacity, limit)
    for a, b, delay in [
        ("PC1", "SW1", 1), ("SW1", "R1", 1),
        ("R1", "Server1", 1), ("SW1", "R2", 3),
        ("R2", "Server1", 3),
    ]:
        net.connect(a, b, delay, 100)
    return net


class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.net = make_network()
        self.main = MainAgent(self.net)

    def test_traffic_reroutes_when_router_congested(self):
        result = self.main.send_traffic("PC1", "Server1", 8, 5)
        paths = [tuple(row["route"]) for row in result["timeline"]]
        self.assertEqual(paths[0], ("PC1", "SW1", "R1", "Server1"))
        self.assertIn(("PC1", "SW1", "R2", "Server1"), paths)
        self.assertIn("R1", result["timeline"][2]["congested"])

    def test_router_queue_overflow_drops_some_packets(self):
        result = self.main.send_traffic("PC1", "Server1", 8, 4)
        self.assertGreater(result["dropped"], 0)
        self.assertEqual(result["attempted"], 32)

    def test_conservation_of_all_packets(self):
        self.main.send_traffic("PC1", "Server1", 8, 10)
        status = self.main.simulator.status()
        self.assertEqual(status["attempted"],
                         status["delivered"] + status["dropped"] + status["in_flight"])

    def test_draining_finishes_pending_packets(self):
        self.main.send_traffic("PC1", "Server1", 8, 10)
        self.main.send_traffic("", "", 0, 20)
        status = self.main.simulator.status()
        self.assertEqual(status["in_flight"], 0)
        self.assertEqual(status["attempted"], status["delivered"] + status["dropped"])

    def test_single_link_bandwidth_limits_packets_per_step(self):
        network = Network()
        network.add_device("A", "PC", 20, 30)
        network.add_device("B", "SERVER", 20, 30)
        # 0.8 Mbps at 10ms and 1000B packets = exactly 1 packet/step
        network.connect("A", "B", 1, bandwidth=0.8)
        sim = TrafficSimulator(network)
        sim.inject(["A", "B"], 5)
        sim.tick()
        self.assertEqual(sim.queue_size("A"), 4)
        self.assertEqual(sim.queue_size("B"), 1)
        self.assertEqual(sim.last_link_usage[("A", "B")]["sent"], 1)

    def test_device_capacity_limits_forwarding(self):
        network = Network()
        network.add_device("A", "PC", 2, 10)
        network.add_device("B", "SERVER", 20, 30)
        network.connect("A", "B", 1, 100)
        sim = TrafficSimulator(network)
        sim.inject(["A", "B"], 5)
        sim.tick()
        self.assertEqual(sim.queue_size("A"), 3)
        self.assertEqual(sim.queue_size("B"), 2)

    def test_source_queue_overflow(self):
        network = Network()
        network.add_device("A", "PC", 2, 3)
        network.add_device("B", "SERVER")
        network.connect("A", "B", 1, 100)
        sim = TrafficSimulator(network)
        result = sim.inject(["A", "B"], 5)
        self.assertEqual(result, {"admitted": 3, "rejected": 2})
        self.assertEqual(sim.dropped, 2)

    def test_offline_device_drops_queued_packets(self):
        self.main.send_traffic("PC1", "Server1", 8, 3)
        current = self.main.simulator.queue_size("R1")
        self.assertGreater(current, 0)
        self.net.set_device_status("R1", False)
        self.main.send_traffic("", "", 0, 1)
        self.assertEqual(self.main.simulator.queue_size("R1"), 0)
        self.assertGreaterEqual(self.main.simulator.dropped, current)

    def test_no_route_rejects_all_generated_packets(self):
        self.net.set_device_status("R1", False)
        self.net.set_device_status("R2", False)
        result = self.main.send_traffic("PC1", "Server1", 5, 2)
        self.assertEqual(result["attempted"], 10)
        self.assertEqual(result["dropped"], 10)
        self.assertEqual(result["delivered"], 0)

    def test_existing_packet_mode_still_works(self):
        self.assertTrue(self.main.send_packet("PC1", "Server1")["delivered"])

    def test_new_agents_follow_four_step_cycle(self):
        for name in ("traffic", "congestion"):
            for method in ("assess", "plan", "act", "check"):
                self.assertTrue(callable(getattr(self.main.agents[name], method)))

    def test_reject_invalid_traffic_counts(self):
        with self.assertRaises(ValueError):
            self.main.send_traffic("PC1", "Server1", -1, 5)
        with self.assertRaises(ValueError):
            self.main.send_traffic("PC1", "Server1", 2, 0)


if __name__ == "__main__":
    unittest.main()
