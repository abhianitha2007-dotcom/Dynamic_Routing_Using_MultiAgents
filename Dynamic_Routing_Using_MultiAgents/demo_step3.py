"""Ready-made demo: shortest path first, reroute when its router gets busy."""
from agents import MainAgent
from network import Network


def create_demo():
    network = Network()
    for name, kind, capacity, queue_limit in [
        ("PC1", "PC", 20, 50),
        ("SW1", "SWITCH", 30, 60),
        ("R1", "ROUTER", 2, 8),     # deliberately slow router
        ("R2", "ROUTER", 20, 50),
        ("Server1", "SERVER", 25, 50),
    ]:
        network.add_device(name, kind, capacity, queue_limit)
    for a, b, delay in [
        ("PC1", "SW1", 1), ("SW1", "R1", 1),
        ("R1", "Server1", 1), ("SW1", "R2", 3),
        ("R2", "Server1", 3),
    ]:
        network.connect(a, b, delay, bandwidth=100)
    return network


if __name__ == "__main__":
    main = MainAgent(create_demo())
    print("\nGenerating 8 packets per step for 10 steps...\n")
    report = main.send_traffic("PC1", "Server1", packets_per_step=8, steps=10)
    for item in report["timeline"]:
        print(f"Step {item['step']:>2}: route={' -> '.join(item['route'])} | "
              f"busy={item['congested']} | delivered={item['delivered']} | "
              f"dropped={item['dropped']}")
    print("\nBefore draining:", {k: v for k, v in report.items() if k != "timeline"})
    main.send_traffic("", "", packets_per_step=0, steps=10)  # wait for queued packets
    print("After draining:", main.simulator.status())
