"""Step 4 demonstration: the main agent bypasses a simulated blackhole."""
from network import Network
from agents import MainAgent


def create_demo():
    net = Network()
    for name, kind in [("PC1", "PC"), ("SW1", "SWITCH"),
                       ("R1", "ROUTER"), ("R2", "ROUTER"),
                       ("Server1", "SERVER")]:
        net.add_device(name, kind, capacity=20, queue_limit=50)
    for a, b, delay in [("PC1", "SW1", 1), ("SW1", "R1", 1),
                        ("R1", "Server1", 1), ("SW1", "R2", 3),
                        ("R2", "Server1", 3)]:
        net.connect(a, b, delay, bandwidth=100)
    return net


if __name__ == "__main__":
    main = MainAgent(create_demo())
    main.simulator.set_behavior("R1", "blackhole")
    print("R1 simulates packet dropping. R2 is the backup path.\n")
    report = main.send_traffic("PC1", "Server1", packets_per_step=1, steps=14)
    for item in report["timeline"]:
        route = " -> ".join(item["route"] or []) or "unavailable"
        print(f"Step {item['step']:>2}: {route} | "
              f"R1 trust={item['trust_scores']['R1']:.2f} | "
              f"untrusted={item['untrusted']}")
    main.send_traffic("", "", 0, 8)  # finish packets already in transit
    final = main.simulator.status()
    print("\nPacket results:", {k: final[k] for k in (
        "attempted", "delivered", "dropped", "in_flight")})
    print("Drop causes:", final["drop_reasons"])
    print("Trust scores:", main.agents["trust"].scores)
    print("This models simulated behavior; it does not detect real intrusions.")
