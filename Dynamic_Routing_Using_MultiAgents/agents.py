"""Specialized agents; each one uses Assess -> Plan -> Act -> Check."""
from heapq import heappop, heappush
from traffic import TrafficSimulator


class Agent:
    def run(self, task):
        facts = self.assess(task)
        decision = self.plan(facts, task)
        outcome = self.act(decision, task)
        return self.check(outcome, task)


class RoutingAgent(Agent):
    """Dijkstra routing: avoid untrusted routers; bypass congestion if possible."""

    def assess(self, task):
        net = task["network"]
        source, target = task["source"], task["target"]
        if source not in net.devices or target not in net.devices:
            raise ValueError("Source and destination must exist")
        if source == target:
            raise ValueError("Choose two different devices")
        graph = {name: [] for name, device in net.devices.items() if device.online}
        for key, link in net.links.items():
            if link.enabled and link.a in graph and link.b in graph:
                graph[link.a].append((link.b, link.delay, key))
                graph[link.b].append((link.a, link.delay, key))
        return graph

    def plan(self, graph, task):
        source, target = task["source"], task["target"]
        net = task["network"]

        def shortest(avoid_nodes, avoid_links):
            heap = [(0, source, [source])]
            visited = set()
            while heap:
                delay, node, path = heappop(heap)
                if node in visited:
                    continue
                if node == target:
                    return path
                visited.add(node)
                if node != source and net.devices[node].kind in ("PC", "SERVER"):
                    continue  # end devices do not forward transit traffic
                for neighbor, cost, key in graph.get(node, []):
                    if neighbor not in avoid_nodes and key not in avoid_links:
                        heappush(heap, (delay + cost, neighbor, path + [neighbor]))
            return None

        blocked = set(task.get("untrusted_nodes", []))
        busy = set(task.get("busy_nodes", []))
        # Untrusted nodes are NEVER used as a fallback; congested ones may be.
        return (shortest(blocked | busy, set(task.get("busy_links", [])))
                or shortest(blocked, set()))

    def act(self, path, task):
        task["route"] = path
        return path

    def check(self, path, task):
        return path if path and path[0] == task["source"] and path[-1] == task["target"] else None


class DeliveryAgent(Agent):
    """Step 2 single packet; Step 3 queued traffic forwarding."""

    def assess(self, task):
        return task["simulator"] if "simulator" in task else task.get("route")

    def plan(self, facts, task):
        return facts if "simulator" in task else list(zip(facts, facts[1:])) if facts else []

    def act(self, plan, task):
        if "simulator" in task:
            return plan.tick()
        net, delay = task["network"], 0.0
        for a, b in plan:
            link = net.links.get(tuple(sorted((a, b))))
            if not link or not link.enabled or not net.devices[a].online or not net.devices[b].online:
                return {"delivered": False, "delay_ms": None}
            delay += link.delay
        return {"delivered": bool(plan), "delay_ms": delay if plan else None}

    def check(self, result, task):
        if "simulator" not in task and result["delivered"] and task["route"][-1] != task["target"]:
            return {"delivered": False, "delay_ms": None}
        return result


class TrafficAgent(Agent):
    """Generate a batch of simulated packets on the selected route."""

    def assess(self, task):
        count = task["count"]
        if count < 0:
            raise ValueError("Packet count cannot be negative")
        return count

    def plan(self, count, task):
        return task.get("route"), count

    def act(self, decision, task):
        route, count = decision
        return task["simulator"].inject(route, count)

    def check(self, result, task):
        return result


class CongestionAgent(Agent):
    """Detect queue build-up and avoid bad paths until their queues drain."""

    def __init__(self):
        self.busy = set()  # persists between simulation steps (hysteresis)

    def assess(self, task):
        net, sim = task["network"], task["simulator"]
        levels = {
            name: sim.queue_size(name) / device.queue_limit
            for name, device in net.devices.items()
            if device.kind in ("ROUTER", "SWITCH") and device.online
        }
        saturated = {
            key for key, data in sim.last_link_usage.items()
            if data["limit"] > 0 and data["sent"] >= data["limit"]
            and any(sim.queue_size(n) for n in key)
        }
        return levels, saturated

    def plan(self, facts, task):
        levels, links = facts
        threshold = task.get("threshold", 0.6)
        if not 0 < threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        # Once congested, a router stays flagged until its queue falls below 25%.
        busy = {name for name, level in levels.items()
                if level >= (0.25 if name in self.busy else threshold)}
        return busy, links

    def act(self, decision, task):
        self.busy = decision[0]
        return {"busy_nodes": sorted(self.busy), "busy_links": sorted(decision[1])}

    def check(self, result, task):
        return result


class TrustAgent(Agent):
    """Scores router reliability from new forwarding observations only."""

    def __init__(self, threshold=0.5):
        self.scores = {}     # router name -> trust, between 0 and 1
        self.seen = {}       # previously processed event counts
        self.threshold = threshold

    def assess(self, task):
        sim = task["simulator"]
        net = task["network"]
        return {
            name: dict(sim.node_events[name])
            for name, device in net.devices.items()
            if device.kind in ("ROUTER", "SWITCH")
        }

    def plan(self, facts, task):
        updates = {}
        for name, totals in facts.items():
            previous = self.seen.get(name, {})
            good = max(0, totals["forwarded"] - previous.get("forwarded", 0))
            bad = max(0, totals["unexplained"] - previous.get("unexplained", 0))
            # Queue overflow is deliberately NOT counted as suspicious.
            score = self.scores.get(name, 1.0) + 0.03 * good - 0.4 * bad
            updates[name] = (round(max(0.0, min(1.0, score)), 3), totals)
        return updates

    def act(self, decision, task):
        for name, (score, totals) in decision.items():
            self.scores[name] = score
            self.seen[name] = totals
        return dict(self.scores)

    def check(self, result, task):
        return {"scores": result, "untrusted_nodes": sorted(
            name for name, score in result.items() if score < self.threshold
        )}

    def reset(self, name):
        """After manual investigation/repair, allow a router to regain trust."""
        if name not in self.scores:
            raise ValueError("Unknown trust entry; run a simulation first")
        self.scores[name] = 1.0
        # Keep the processed counts so the same historical losses aren't reused.


class MainAgent:
    """Orchestrator: delegates decisions and maintains state between steps."""

    def __init__(self, network):
        self.network = network
        self.simulator = TrafficSimulator(network)
        from qlearning import QLearningRoutingAgent
        self.routing_mode = "dijkstra"  # use "qlearning" to enable adaptive routes
        self.congestion_enabled = True
        self.congestion_threshold = 0.6
        self.agents = {
            "routing": RoutingAgent(),
            "qlearning": QLearningRoutingAgent(),
            "delivery": DeliveryAgent(),
            "traffic": TrafficAgent(),
            "congestion": CongestionAgent(),
            "trust": TrustAgent(),
        }
        self.history = []
        self.activity = []

    def ask(self, name, task):
        self.activity.append(f"Main Agent -> {name}: assigned task")
        result = self.agents[name].run(task)
        self.activity.append(f"{name} -> Main Agent: {result}")
        return result

    def set_routing_mode(self, mode):
        if mode not in ("dijkstra", "qlearning"):
            raise ValueError("Choose dijkstra or qlearning")
        self.routing_mode = mode

    def choose_route(self, task):
        return self.ask("qlearning" if self.routing_mode == "qlearning" else "routing", task)

    def send_packet(self, source, target):
        """Original Step 2 demonstration remains available."""
        task = {"network": self.network, "source": source, "target": target}
        # Simple packet mode checks topology only; attacks affect queued traffic.
        trust = self.ask("trust", {"network": self.network, "simulator": self.simulator})
        task["untrusted_nodes"] = trust["untrusted_nodes"]
        task["trust_scores"] = trust["scores"]
        route = self.choose_route({**task, "simulator": self.simulator})
        task["route"] = route
        result = self.ask("delivery", task) if route else {"delivered": False, "delay_ms": None}
        output = {"source": source, "target": target, "route": route, **result}
        self.history.append(output)
        return output

    def send_traffic(self, source, target, packets_per_step, steps=8):
        """Inject packets every step, monitor congestion and reroute NEW packets."""
        if not isinstance(packets_per_step, int) or packets_per_step < 0 or not isinstance(steps, int) or steps < 1:
            raise ValueError("Use nonnegative packets/step and positive step count")
        before = self.simulator.status()
        timeline = []
        trust = self.ask("trust", {"network": self.network, "simulator": self.simulator})
        for step in range(1, steps + 1):
            congestion = self.ask("congestion", {
                "network": self.network, "simulator": self.simulator,
                "threshold": self.congestion_threshold,
            }) if self.congestion_enabled else {"busy_nodes": [], "busy_links": []}
            task = {"network": self.network, "source": source, "target": target,
                    **congestion, "untrusted_nodes": trust["untrusted_nodes"],
                    "trust_scores": trust["scores"], "simulator": self.simulator}
            # No route needed when draining the queues (packets_per_step=0).
            route = self.choose_route(task) if packets_per_step else None
            if packets_per_step:
                self.ask("traffic", {"route": route, "count": packets_per_step,
                                     "simulator": self.simulator})
            stats = self.ask("delivery", {"simulator": self.simulator})
            self.agents["qlearning"].observe(self.simulator.last_outcomes, self.network)
            trust = self.ask("trust", {"network": self.network, "simulator": self.simulator})
            timeline.append({"step": step, "route": route,
                             "congested": congestion["busy_nodes"],
                             "untrusted": trust["untrusted_nodes"],
                             "trust_scores": dict(trust["scores"]),
                             "delivered": stats["delivered"] - before["delivered"],
                             "dropped": stats["dropped"] - before["dropped"],
                             "queued": stats["in_flight"]})

        after = self.simulator.status()
        reason_delta = {key: after["drop_reasons"].get(key, 0)
                        - before["drop_reasons"].get(key, 0)
                        for key in after["drop_reasons"]}
        return {
            "attempted": after["attempted"] - before["attempted"],
            "delivered": after["delivered"] - before["delivered"],
            "dropped": after["dropped"] - before["dropped"],
            "still_queued": after["in_flight"],
            "drop_reasons": {key: count for key, count in reason_delta.items() if count},
            "trust_scores": dict(trust["scores"]),
            "timeline": timeline,
        }
