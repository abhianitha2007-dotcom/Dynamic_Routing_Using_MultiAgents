"""Packet simulator: congestion plus controlled, simulated unreliable routers."""
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Packet:
    route: list
    position: int = 0


class TrafficSimulator:
    """One hop per step; device capacity and link bandwidth limit forwarding."""

    def __init__(self, network, packet_bytes=1000, step_seconds=0.01):
        self.network = network
        self.packet_bytes = packet_bytes
        self.step_seconds = step_seconds
        self.queues = {}  # device -> deque of packets
        self.attempted = self.admitted = self.delivered = self.dropped = 0
        self.steps = 0
        self.last_link_usage = {}
        self.behaviors = {}         # router -> normal / blackhole / grayhole
        self.attempts_by_device = defaultdict(int)
        self.node_events = defaultdict(lambda: {"forwarded": 0, "unexplained": 0})
        self.drop_reasons = defaultdict(int)  # congestion / unexplained / offline / no_route
        self.last_outcomes = []  # (route, outcome), cleared each simulation step

    def set_behavior(self, name, mode):
        """Set only a local SIMULATION behavior, never a real network attack."""
        device = self.network.devices.get(name)
        if not device or device.kind not in ("ROUTER", "SWITCH"):
            raise ValueError("Choose an existing router or switch")
        if mode not in ("normal", "blackhole", "grayhole"):
            raise ValueError("Use normal, blackhole, or grayhole")
        if mode == "normal":
            self.behaviors.pop(name, None)
        else:
            self.behaviors[name] = mode
        self.attempts_by_device[name] = 0

    def _drop(self, reason, device=None, count=1):
        self.dropped += count
        self.drop_reasons[reason] += count
        if reason == "unexplained" and device:
            self.node_events[device]["unexplained"] += count

    def queue_size(self, name):
        return len(self.queues.get(name, ()))

    def inject(self, route, count):
        if count < 0:
            raise ValueError("Packet count cannot be negative")
        accepted = 0
        self.attempted += count
        if not route or route[0] not in self.network.devices:
            self._drop("no_route", count=count)
            return {"admitted": 0, "rejected": count}

        source = self.network.devices[route[0]]
        queue = self.queues.setdefault(source.name, deque())
        for _ in range(count):
            if not source.online or len(queue) >= source.queue_limit:
                self._drop("congestion" if source.online else "offline")
            else:
                queue.append(Packet(list(route)))
                self.admitted += 1
                accepted += 1
        return {"admitted": accepted, "rejected": count - accepted}

    def tick(self):
        """Forward packets from queues, then deliver arrivals to next-hop queues."""
        self.last_outcomes = []
        budgets = {
            key: int(link.bandwidth * 1_000_000 * self.step_seconds
                     // (self.packet_bytes * 8))
            for key, link in self.network.links.items()
            if link.enabled
        }
        usage = {key: {"sent": 0, "limit": limit} for key, limit in budgets.items()}
        arrivals = []
        for name, queue in list(self.queues.items()):
            device = self.network.devices.get(name)
            if device is None or not device.online:
                self._drop("offline", count=len(queue))
                queue.clear()
                continue

            # Only packets already queued at the START of this step may be sent.
            for _ in range(min(device.capacity, len(queue))):
                packet = queue.popleft()
                if packet.position == len(packet.route) - 1:
                    self.delivered += 1
                    self.last_outcomes.append((packet.route, "delivered"))
                    continue

                neighbor = packet.route[packet.position + 1]
                other = self.network.devices.get(neighbor)
                key = tuple(sorted((name, neighbor)))
                link = self.network.links.get(key)
                if not other or not other.online:
                    self._drop("offline")
                elif not link or not link.enabled:
                    self._drop("link_failure")
                elif budgets.get(key, 0) <= 0:
                    queue.append(packet)  # wait for next step; link has no capacity
                else:
                    # Blackhole: drop all; grayhole: drop every second transit packet.
                    mode = self.behaviors.get(name, "normal")
                    self.attempts_by_device[name] += 1
                    seq = self.attempts_by_device[name]
                    if mode == "blackhole" or (mode == "grayhole" and seq % 2 == 0):
                        self._drop("unexplained", device=name)
                        self.last_outcomes.append((packet.route, "unexplained"))
                        continue
                    budgets[key] -= 1
                    usage[key]["sent"] += 1
                    packet.position += 1
                    arrivals.append((name, neighbor, packet))

        for sender, name, packet in arrivals:
            device = self.network.devices.get(name)
            queue = self.queues.setdefault(name, deque())
            if not device or not device.online:
                self._drop("offline")
            elif len(queue) >= device.queue_limit:
                self._drop("congestion")
            else:
                queue.append(packet)
                if self.network.devices[sender].kind in ("ROUTER", "SWITCH"):
                    self.node_events[sender]["forwarded"] += 1

        self.last_link_usage = usage
        self.steps += 1
        return self.status()

    def status(self):
        return {
            "attempted": self.attempted,
            "admitted": self.admitted,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "in_flight": sum(len(q) for q in self.queues.values()),
            "steps": self.steps,
            "queues": {name: self.queue_size(name) for name in self.network.devices},
            "drop_reasons": dict(self.drop_reasons),
        }
