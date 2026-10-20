"""Interactive simulator with Dijkstra and Q-Learning routing modes."""
from network import Network
from agents import MainAgent


def optional_int(prompt):
    value = input(prompt).strip()
    return int(value) if value else None


def run():
    network = Network()
    main_agent = MainAgent(network)
    menu = (
        "\n1 Add device        2 Connect devices\n"
        "3 Show network      4 Set device online/offline\n"
        "5 Enable/disable link  6 Remove device\n"
        "7 Remove link       8 Save network\n"
        "9 Load network     10 Send simulated packet\n"
        "11 Agent history    12 Send traffic burst\n"
        "13 Traffic status   14 Drain queues\n"
        "15 Set router behavior  16 Show trust scores\n"
        "17 Reset device trust  18 Set routing algorithm\n"
        "19 Q-Learning stats   20 Compare routes\n"
        "0 Exit\n"
    )
    while True:
        print(menu)
        choice = input("Choose: ").strip()
        try:
            if choice == "1":
                name = input("Device name: ").strip()
                kind = input("Type (PC/ROUTER/SWITCH/SERVER): ")
                capacity = optional_int("Capacity in packets/step (Enter = default): ")
                queue = optional_int("Queue limit in packets (Enter = default): ")
                network.add_device(name, kind, capacity, queue)
                print("Device added.")
            elif choice == "2":
                a, b = input("From: ").strip(), input("To: ").strip()
                delay = float(input("Link delay (ms): "))
                bandwidth = float(input("Bandwidth (Mbps): "))
                network.connect(a, b, delay, bandwidth)
                print("Link created or updated.")
            elif choice == "3":
                network.show()
            elif choice == "4":
                name = input("Device: ").strip()
                network.set_device_status(name, input("Online? (y/n): ").strip().lower() == "y")
            elif choice == "5":
                a, b = input("From: ").strip(), input("To: ").strip()
                network.set_link_status(a, b, input("Enabled? (y/n): ").strip().lower() == "y")
            elif choice == "6":
                network.remove_device(input("Device to remove: ").strip())
            elif choice == "7":
                network.remove_link(input("From: ").strip(), input("To: ").strip())
            elif choice == "8":
                network.save(input("File (Enter = topology.json): ").strip() or "topology.json")
                print("Network saved.")
            elif choice == "9":
                network = Network.load(input("File (Enter = topology.json): ").strip() or "topology.json")
                main_agent = MainAgent(network)
                print("Network loaded; agent history reset.")
            elif choice == "10":
                source = input("Source device: ").strip()
                target = input("Destination device: ").strip()
                result = main_agent.send_packet(source, target)
                if result["delivered"]:
                    print("Delivered:", " -> ".join(result["route"]))
                    print("Simulated link delay:", result["delay_ms"], "ms")
                else:
                    print("Packet not delivered (no usable route).")
            elif choice == "11":
                print("AGENT COMMUNICATION")
                for message in main_agent.activity:
                    print(" ", message)
                print("PACKET HISTORY")
                for i, entry in enumerate(main_agent.history, 1):
                    print(i, entry)
                if not main_agent.history:
                    print("No packets attempted yet.")
            elif choice == "12":
                source = input("Source device: ").strip()
                target = input("Destination device: ").strip()
                rate = int(input("Packets per step: "))
                steps = int(input("Simulation steps (e.g. 8): "))
                report = main_agent.send_traffic(source, target, rate, steps)
                for entry in report["timeline"]:
                    path = " -> ".join(entry["route"]) if entry["route"] else "unavailable"
                    print(f"Step {entry['step']}: {path}; busy={entry['congested']}; "
                          f"untrusted={entry['untrusted']}; "
                          f"delivered={entry['delivered']}, dropped={entry['dropped']}, "
                          f"queued={entry['queued']}")
                print("Traffic summary:", {key: value for key, value in report.items()
                                           if key != "timeline"})
            elif choice == "13":
                print("TRAFFIC STATUS:", main_agent.simulator.status())
            elif choice == "14":
                steps = int(input("How many steps to process remaining queues? "))
                report = main_agent.send_traffic("", "", 0, steps)
                print("Drained:", {key: value for key, value in report.items()
                                    if key != "timeline"})
            elif choice == "15":
                device = input("Router or switch: ").strip()
                mode = input("Behavior (normal/blackhole/grayhole): ").strip().lower()
                main_agent.simulator.set_behavior(device, mode)
                print(f"Simulation behavior for {device}: {mode}")
            elif choice == "16":
                result = main_agent.ask("trust", {
                    "network": network, "simulator": main_agent.simulator
                })
                print("TRUST SCORES:", result["scores"])
                print("UNTRUSTED:", result["untrusted_nodes"])
                print("SIMULATED BEHAVIORS:", main_agent.simulator.behaviors)
                print("DROPS BY CAUSE:", dict(main_agent.simulator.drop_reasons))
            elif choice == "17":
                name = input("Device to reset after repair: ").strip()
                main_agent.agents["trust"].reset(name)
                print("Trust reset for", name)
            elif choice == "18":
                mode = input("Routing mode (dijkstra/qlearning): ").strip().lower()
                main_agent.set_routing_mode(mode)
                print("Active routing algorithm:", main_agent.routing_mode)
            elif choice == "19":
                learner = main_agent.agents["qlearning"]
                print(f"Learned Q entries: {len(learner.q)}; "
                      f"actual packet outcomes observed: {learner.feedback}")
                for (dest, current, neighbor), value in sorted(learner.q.items())[:20]:
                    print(f"  To {dest}: {current} -> {neighbor} = {value:.2f}")
            elif choice == "20":
                source = input("Source device: ").strip()
                target = input("Destination device: ").strip()
                trust = main_agent.ask("trust", {
                    "network": network, "simulator": main_agent.simulator})
                congestion = main_agent.ask("congestion", {
                    "network": network, "simulator": main_agent.simulator})
                task = {"network": network, "simulator": main_agent.simulator,
                        "source": source, "target": target,
                        "trust_scores": trust["scores"],
                        "untrusted_nodes": trust["untrusted_nodes"], **congestion}
                for mode in ("routing", "qlearning"):
                    route = main_agent.ask(mode, dict(task))
                    print(f"{mode}: {' -> '.join(route) if route else 'No route'}")
            elif choice == "0":
                print("Goodbye!")
                break
            else:
                print("Invalid menu choice.")
        except (ValueError, OSError, KeyError, TypeError) as error:
            print("Error:", error)


if __name__ == "__main__":
    run()
