"""Step 5: compact tabular Q-Learning agent for simulated route selection."""
import random
from agents import RoutingAgent


class QLearningRoutingAgent(RoutingAgent):
    """Learn next-hop values Q(destination, current_device, next_device)."""

    def __init__(self, episodes=500, alpha=0.4, gamma=0.85, epsilon=0.25):
        self.q = {}
        self.episodes = episodes
        self.alpha, self.gamma, self.epsilon = alpha, gamma, epsilon
        self.rng = random.Random(7)  # repeatable classroom demonstrations
        self.feedback = 0

    def plan(self, graph, task):
        target = task["target"]
        net = task["network"]
        blocked = set(task.get("untrusted_nodes", []))
        busy = set(task.get("busy_nodes", []))
        busy_links = {tuple(k) for k in task.get("busy_links", [])}
        scores = task.get("trust_scores", {})
        sim = task.get("simulator")

        def neighbors(node, seen):
            if node != task["source"] and net.devices[node].kind in ("PC", "SERVER"):
                return []
            return [(n, delay, key) for n, delay, key in graph.get(node, [])
                    if n not in seen and n not in blocked
                    and (n == target or net.devices[n].kind not in ("PC", "SERVER"))]

        def reward(neighbor, delay, key):
            level = (sim.queue_size(neighbor) / net.devices[neighbor].queue_limit
                     if sim else 0)
            trust_penalty = 8 * (1 - scores.get(neighbor, 1))
            congestion_penalty = 15 * (neighbor in busy) + 10 * (key in busy_links)
            return (-delay - trust_penalty - 12 * level - congestion_penalty
                    + (30 if neighbor == target else 0))

        # Learn from simulated transitions. Each iteration explores a short path.
        starts = [n for n in graph if n not in blocked and n != target]
        if task["source"] not in graph or target not in graph or not starts:
            return None
        for _ in range(self.episodes):
            node = self.rng.choice(starts)
            visited = {node}
            for _ in range(len(graph)):
                options = neighbors(node, visited)
                if not options:
                    break
                if self.rng.random() < self.epsilon:
                    nxt, delay, key = self.rng.choice(options)
                else:
                    nxt, delay, key = max(
                        options, key=lambda option: self.q.get((target, node, option[0]), 0))
                next_options = neighbors(nxt, visited | {nxt})
                future = max((self.q.get((target, nxt, x), 0) for x, _, _ in next_options),
                             default=0)
                state = (target, node, nxt)
                old = self.q.get(state, 0)
                self.q[state] = old + self.alpha * (
                    reward(nxt, delay, key) + self.gamma * future - old)
                node = nxt
                visited.add(node)
                if node == target:
                    break

        # Use the learned next-hop values, forbidding loops and unsafe nodes.
        route = [task["source"]]
        while route[-1] != target:
            node = route[-1]
            options = neighbors(node, set(route))
            if not options:
                # Fall back to known-safe Dijkstra if the learned policy is incomplete.
                return super().plan(graph, task)
            nxt, _, _ = max(options,
                            key=lambda option: self.q.get((target, node, option[0]), -1e9))
            route.append(nxt)
        return route

    def observe(self, outcomes, network):
        """Reinforce paths for packets that actually completed or were dropped."""
        for route, result in outcomes:
            if len(route) < 2:
                continue
            target = route[-1]
            future = 0
            for a, b in reversed(list(zip(route, route[1:]))):
                link = network.links.get(tuple(sorted((a, b))))
                delay = link.delay if link else 1
                # Actual delivery adds positive feedback; unexplained drops are penalized.
                reward = -delay + (20 if result == "delivered" and b == target else 0)
                if result == "unexplained":
                    reward -= 20
                state = (target, a, b)
                old = self.q.get(state, 0)
                new = old + self.alpha * (reward + self.gamma * future - old)
                self.q[state] = new
                future = new
            self.feedback += 1
