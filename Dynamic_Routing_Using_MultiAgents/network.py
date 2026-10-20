"""Step 1: Device and link definitions for our network simulator."""
from dataclasses import asdict, dataclass
import json

# (processing capacity: packets/step, queue limit: packets)
DEFAULTS = {
    "PC": (5, 10),
    "ROUTER": (20, 50),
    "SWITCH": (30, 60),
    "SERVER": (25, 50),
}


@dataclass
class Device:
    name: str
    kind: str
    capacity: int
    queue_limit: int
    online: bool = True


@dataclass
class Link:
    a: str
    b: str
    delay: float  # milliseconds (simulated)
    bandwidth: float  # Mbps (used by TrafficSimulator per simulation step)
    enabled: bool = True


class Network:
    def __init__(self):
        self.devices = {}  # name -> Device
        self.links = {}    # (name1, name2) -> Link

    def add_device(self, name, kind, capacity=None, queue_limit=None):
        name, kind = name.strip(), kind.strip().upper()
        if not name or name in self.devices:
            raise ValueError("Device name must be unique and nonempty")
        if kind not in DEFAULTS:
            raise ValueError("Choose PC, ROUTER, SWITCH, or SERVER")
        default_capacity, default_queue = DEFAULTS[kind]
        capacity = default_capacity if capacity is None else capacity
        queue_limit = default_queue if queue_limit is None else queue_limit
        if capacity <= 0 or queue_limit <= 0:
            raise ValueError("Capacity and queue limit must be positive")
        self.devices[name] = Device(name, kind, capacity, queue_limit)

    def connect(self, a, b, delay=1.0, bandwidth=100.0):
        if a == b or a not in self.devices or b not in self.devices:
            raise ValueError("Connect two different, existing devices")
        if delay <= 0 or bandwidth <= 0:
            raise ValueError("Delay and bandwidth must be positive")
        self.links[tuple(sorted((a, b)))] = Link(a, b, delay, bandwidth)

    def set_device_status(self, name, online):
        if name not in self.devices:
            raise ValueError("Unknown device")
        self.devices[name].online = online

    def set_link_status(self, a, b, enabled):
        key = tuple(sorted((a, b)))
        if key not in self.links:
            raise ValueError("Unknown link")
        self.links[key].enabled = enabled

    def remove_device(self, name):
        if name not in self.devices:
            raise ValueError("Unknown device")
        del self.devices[name]
        self.links = {key: link for key, link in self.links.items() if name not in key}

    def remove_link(self, a, b):
        key = tuple(sorted((a, b)))
        if key not in self.links:
            raise ValueError("Unknown link")
        del self.links[key]

    def show(self):
        print("\nDEVICES")
        if not self.devices:
            print("  (none)")
        for d in self.devices.values():
            status = "online" if d.online else "offline"
            print(f"  {d.name}: {d.kind}, capacity={d.capacity}, queue={d.queue_limit}, {status}")
        print("LINKS")
        if not self.links:
            print("  (none)")
        for l in self.links.values():
            status = "active" if l.enabled else "disabled"
            print(f"  {l.a} <-> {l.b}: {l.delay} ms, {l.bandwidth} Mbps, {status}")

    def save(self, filename="topology.json"):
        data = {
            "devices": [asdict(d) for d in self.devices.values()],
            "links": [asdict(l) for l in self.links.values()],
        }
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

    @classmethod
    def load(cls, filename="topology.json"):
        with open(filename, encoding="utf-8") as file:
            data = json.load(file)
        network = cls()
        for d in data["devices"]:
            network.add_device(d["name"], d["kind"], d["capacity"], d["queue_limit"])
            network.set_device_status(d["name"], d["online"])
        for l in data["links"]:
            network.connect(l["a"], l["b"], l["delay"], l["bandwidth"])
            network.set_link_status(l["a"], l["b"], l["enabled"])
        return network
