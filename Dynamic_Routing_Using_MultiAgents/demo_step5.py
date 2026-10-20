"""Step 5 demonstration using the included topology.json."""
from pathlib import Path
from network import Network
from agents import MainAgent


def main():
    network = Network.load(Path(__file__).with_name("topology.json"))
    main_agent = MainAgent(network)
    main_agent.set_routing_mode("qlearning")

    print("Loaded example: PC1, SW1, R1, R2, S1")
    print("Algorithm:", main_agent.routing_mode)
    print("Normal route:", " -> ".join(main_agent.send_packet("PC1", "S1")["route"]))

    # Simulates an unreliable router on the preferred path.
    main_agent.simulator.set_behavior("R2", "blackhole")
    print("\nR2 now simulates unexplained packet drops.")
    report = main_agent.send_traffic("PC1", "S1", 1, 14)
    for row in report["timeline"]:
        path = " -> ".join(row["route"] or []) or "No route"
        score = row["trust_scores"].get("R2", 1.0)
        print(f"Step {row['step']:2d}: {path} | R2 trust={score:.2f}")

    main_agent.send_traffic("", "", 0, 8)
    results = main_agent.simulator.status()
    learner = main_agent.agents["qlearning"]
    print("\nPacket totals:", {k: results[k] for k in (
        "attempted", "delivered", "dropped", "in_flight")})
    print("Q entries:", len(learner.q), "| Packet feedback events:", learner.feedback)
    print("The blackhole is simulated; this is not real-device intrusion detection.")


if __name__ == "__main__":
    main()
