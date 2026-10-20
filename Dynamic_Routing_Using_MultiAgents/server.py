"""Step 8 refined UI web bridge: an HTTP API over the multi-agent simulator.

No third-party packages. Run: py server.py (Windows) or python server.py.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from math import cos, sin, pi
import json
import webbrowser
import os
from uuid import uuid4
from mission_agent import MissionAgent

from network import Network, DEFAULTS
from agents import MainAgent

HERE = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8765
LOCK = RLock()

DEFAULT_POSITIONS = {
    "PC1": [110, 268], "SW1": [300, 268], "R1": [510, 140],
    "R2": [510, 395], "S1": [770, 268],
}


class Project:
    def __init__(self):
        self.positions = {}
        self.timeline = []
        self.latest = {}
        self.saved_limits = {}
        self.pending_missions = {}
        self.last_mission = None
        self.load_example()

    def reset_agents(self):
        self.main = MainAgent(self.network)
        self.timeline = []
        self.latest = {}

    def load_example(self):
        self.saved_limits = {}
        self.network = Network.load(HERE / "topology.json")
        self.positions = {name: DEFAULT_POSITIONS.get(name, [450, 265])[:]
                          for name in self.network.devices}
        self.reset_agents()

    def topology(self):
        return {
            "devices": [{**vars(d), "x": self.positions.get(d.name, [450, 265])[0],
                         "y": self.positions.get(d.name, [450, 265])[1]}
                        for d in self.network.devices.values()],
            "links": [vars(link).copy() for link in self.network.links.values()],
        }

    def state(self):
        sim, main = self.main.simulator, self.main
        trust_agent = main.agents["trust"]
        scores = {name: trust_agent.scores.get(name, 1.0)
                  for name, d in self.network.devices.items()
                  if d.kind in ("ROUTER", "SWITCH")}
        timeline = self.timeline[-75:]
        return {
            **self.topology(),
            "stats": sim.status(),
            "trust": scores,
            "untrusted": [name for name, score in scores.items()
                          if score < trust_agent.threshold],
            "busy": sorted(main.agents["congestion"].busy) if main.congestion_enabled else [],
            "congestion_settings": {"enabled": main.congestion_enabled,
                                    "threshold": main.congestion_threshold},
            "overloads": sorted(self.saved_limits),
            "behaviors": dict(sim.behaviors),
            "mode": main.routing_mode,
            "q_entries": len(main.agents["qlearning"].q),
            "q_feedback": main.agents["qlearning"].feedback,
            "activity": main.activity[-25:],
            "timeline": timeline,
            "latest": self.latest,
            "mission": self.last_mission,
            "llm_enabled": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        }

    def plan_mission(self, message):
        """Read-only proposal; the user must explicitly click Execute."""
        proposed = MissionAgent(self.network).run(message)
        identifier = uuid4().hex
        self.pending_missions = {identifier: proposed}  # one pending mission
        return {"mission_id": identifier, "proposal": proposed, "state": self.state()}

    def execute_mission(self, identifier):
        """Execute only a previously validated and user-approved mission."""
        proposal = self.pending_missions.pop(identifier, None)
        if not proposal:
            raise ValueError("Mission expired. Plan the mission again.")
        intent = proposal["intent"]
        source, target = proposal["source"], proposal["target"]
        if intent in ("attack", "overload", "restore"):
            if target not in self.network.devices:
                raise ValueError("Router was removed. Plan again.")
        elif intent in ("traffic", "preview", "compare"):
            if source not in self.network.devices or target not in self.network.devices:
                raise ValueError("Network changed. Plan again.")
        self.main.activity.append(f"Main Agent: Assess → Plan → Act → Check: {proposal['summary']}")
        if intent == "attack":
            self.apply({"op":"behavior", "name":target, "mode":proposal["behavior"]})
        elif intent == "overload":
            self.apply({"op":"overload", "name":target, "capacity":2, "queue_limit":8})
        elif intent == "restore":
            self.apply({"op":"repair", "name":target})
            if target in self.saved_limits:
                self.apply({"op":"restore_limits", "name":target})
        elif intent in ("preview", "compare"):
            self.apply({"op": intent, "source":source, "target":target})
        elif intent == "traffic":
            for _ in range(proposal["steps"]):
                self.apply({"op":"step", "source":source, "target":target, "rate":proposal["rate"]})
        # inspect does not mutate the network.
        status = self.main.simulator.status()
        report = {"intent":intent,"summary":proposal["summary"],
                  "mode":proposal["mode"],"outcome":
                  f"Delivered {status['delivered']} · Dropped {status['dropped']} · Queued {status['in_flight']}"}
        self.last_mission = report
        self.main.activity.append(f"Main Agent: Check complete — {report['outcome']}")
        self.main.activity = self.main.activity[-80:]
        return {"state":self.state(),"report":report}

    def apply(self, action):
        op = action.get("op")
        net, main = self.network, self.main
        note = None
        if op == "add_device":
            name = str(action["name"]).strip()
            kind = str(action["kind"]).upper()
            capacity = action.get("capacity")
            queue_limit = action.get("queue_limit")
            net.add_device(name, kind,
                           int(capacity) if capacity not in (None, "") else None,
                           int(queue_limit) if queue_limit not in (None, "") else None)
            self.positions[name] = [float(action.get("x", 450)), float(action.get("y", 265))]
            self.reset_agents()
            note = f"{name} added. Simulation reset to keep topology consistent."
        elif op == "move_device":
            name = action["name"]
            if name not in net.devices:
                raise ValueError("Unknown device")
            self.positions[name] = [max(30, min(870, float(action["x"]))),
                                    max(30, min(490, float(action["y"])))]
        elif op == "connect":
            net.connect(str(action["a"]), str(action["b"]),
                        float(action.get("delay", 2)), float(action.get("bandwidth", 100)))
            self.reset_agents()
            note = "Connection updated. Simulation reset."
        elif op == "remove_device":
            net.remove_device(action["name"])
            self.positions.pop(action["name"], None)
            self.saved_limits.pop(action["name"], None)
            self.reset_agents()
        elif op == "remove_link":
            net.remove_link(action["a"], action["b"])
            self.reset_agents()
        elif op == "device_status":
            net.set_device_status(action["name"], bool(action["online"]))
        elif op == "link_status":
            net.set_link_status(action["a"], action["b"], bool(action["enabled"]))
        elif op == "device_settings":
            d = net.devices[action["name"]]
            capacity = int(action["capacity"])
            queue_limit = int(action["queue_limit"])
            if not 0 < capacity <= 10000 or not 0 < queue_limit <= 100000:
                raise ValueError("Device capacity and queue must be positive and within limits")
            d.capacity, d.queue_limit = capacity, queue_limit
        elif op == "link_settings":
            net.connect(action["a"], action["b"], float(action["delay"]),
                        float(action["bandwidth"]))
            net.set_link_status(action["a"], action["b"], bool(action.get("enabled", True)))
        elif op == "behavior":
            main.simulator.set_behavior(action["name"], action["mode"])
        elif op == "repair":
            name = action["name"]
            main.simulator.set_behavior(name, "normal")
            if name in main.agents["trust"].scores:
                main.agents["trust"].reset(name)
        elif op == "congestion_settings":
            enabled = action.get("enabled")
            threshold = float(action.get("threshold", main.congestion_threshold))
            if not 0.25 <= threshold <= 0.95:
                raise ValueError("Congestion threshold must be between 0.25 and 0.95")
            if not isinstance(enabled, bool):
                raise ValueError("Congestion rerouting must be enabled or disabled")
            main.congestion_enabled = enabled
            main.congestion_threshold = threshold
            if not enabled:
                main.agents["congestion"].busy.clear()
            main.activity.append(f"Main Agent: Congestion avoidance {'enabled' if enabled else 'disabled'} at {threshold:.0%}")
            note = "Congestion policy updated. New packets use the updated routing policy."
        elif op == "overload":
            name = action["name"]
            if name not in net.devices or net.devices[name].kind not in ("ROUTER", "SWITCH"):
                raise ValueError("Choose an existing router or switch")
            capacity = int(action.get("capacity", 2))
            queue_limit = int(action.get("queue_limit", 8))
            if not 1 <= capacity <= 10000 or not 1 <= queue_limit <= 100000:
                raise ValueError("Capacity and queue limit must be positive and within limits")
            d = net.devices[name]
            if name not in self.saved_limits:
                self.saved_limits[name] = (d.capacity, d.queue_limit)
            d.capacity, d.queue_limit = capacity, queue_limit
            main.activity.append(f"Main Agent: Congestion scenario on {name}: capacity={capacity}, queue={queue_limit}")
            note = f"Overload settings applied to {name}. Run packet traffic to test congestion."
        elif op == "restore_limits":
            name = action["name"]
            if name not in self.saved_limits or name not in net.devices:
                raise ValueError("No saved capacity settings for this device")
            d = net.devices[name]
            d.capacity, d.queue_limit = self.saved_limits.pop(name)
            note = f"Original capacity and queue limit restored for {name}."
        elif op == "routing_mode":
            main.set_routing_mode(action["mode"])
        elif op == "step":
            rate = int(action.get("rate", 1))
            if not 0 <= rate <= 200:
                raise ValueError("Rate must be between 0 and 200 packets per step")
            source = str(action.get("source", ""))
            target = str(action.get("target", ""))
            if rate and (source not in net.devices or target not in net.devices or source == target):
                raise ValueError("Choose different existing source and destination devices")
            report = main.send_traffic(source, target, rate, 1)
            item = report["timeline"][-1]
            self.timeline.append({"time": main.simulator.steps,
                                  "delivered": main.simulator.delivered,
                                  "dropped": main.simulator.dropped,
                                  "queued": main.simulator.status()["in_flight"],
                                  "route": item["route"],
                                  "busy": item["congested"],
                                  "untrusted": item["untrusted"]})
            self.latest = {"type": "traffic", "route": item["route"],
                           "step": main.simulator.steps, "rate": rate}
            main.activity = main.activity[-80:]
        elif op in ("preview", "compare"):
            source, target = str(action["source"]), str(action["target"])
            info = {"network": net, "simulator": main.simulator}
            trust = main.agents["trust"].run(info)
            congestion = main.agents["congestion"].run({**info, "threshold": main.congestion_threshold}) if main.congestion_enabled else {"busy_nodes": [], "busy_links": []}
            task = {**info, **congestion, "source": source, "target": target,
                    "untrusted_nodes": trust["untrusted_nodes"],
                    "trust_scores": trust["scores"]}
            if op == "preview":
                route = main.choose_route(task)
                self.latest = {"type": "preview", "route": route}
            else:
                dijkstra = main.agents["routing"].run(dict(task))
                learned = main.agents["qlearning"].run(dict(task))
                self.latest = {"type": "compare", "route": learned,
                               "dijkstra": dijkstra, "qlearning": learned}
        elif op == "reset_simulation":
            self.reset_agents()
            note = "Simulation and learned state reset. Topology retained."
        elif op == "load_example":
            self.load_example()
        elif op == "clear_network":
            self.network = Network()
            self.positions = {}
            self.saved_limits = {}
            self.reset_agents()
        elif op == "import":
            data = action["topology"]
            if not isinstance(data, dict):
                raise ValueError("Invalid topology format")
            if len(data.get("devices", [])) > 80 or len(data.get("links", [])) > 400:
                raise ValueError("Topology is too large for this classroom simulator")
            new = Network()
            locations = {}
            for i, d in enumerate(data["devices"]):
                new.add_device(d["name"], d["kind"], int(d["capacity"]), int(d["queue_limit"]))
                new.set_device_status(d["name"], bool(d.get("online", True)))
                # Step 5 JSON files do not have x/y: spread devices around a circle.
                angle = 2 * pi * i / max(1, len(data["devices"]))
                x = d.get("x", 450 + 245 * cos(angle))
                y = d.get("y", 265 + 160 * sin(angle))
                locations[d["name"]] = [float(x), float(y)]
            for link in data["links"]:
                new.connect(link["a"], link["b"], float(link["delay"]), float(link["bandwidth"]))
                new.set_link_status(link["a"], link["b"], bool(link.get("enabled", True)))
            self.network, self.positions = new, locations
            self.saved_limits = {}
            self.reset_agents()
            note = "Topology imported. Simulation reset."
        else:
            raise ValueError("Unknown action")
        return {"state": self.state(), "notice": note}


PROJECT = Project()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/state"):
            super().log_message(fmt, *args)

    def send_data(self, data, status=200, mime="application/json", attachment=None):
        if isinstance(data, (dict, list)):
            content = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            content = data.encode("utf-8")
        else:
            content = data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            with LOCK:
                self.send_data(PROJECT.state())
        elif path == "/api/export":
            with LOCK:
                self.send_data(PROJECT.topology(), attachment="topology.json")
        elif path in ("/", "/styles.css", "/app.js"):
            filename = {"/": "index.html", "/styles.css": "styles.css",
                        "/app.js": "app.js"}[path]
            mime = {"index.html": "text/html; charset=utf-8", "styles.css": "text/css; charset=utf-8",
                    "app.js": "text/javascript; charset=utf-8"}[filename]
            self.send_data((HERE / "web" / filename).read_bytes(), mime=mime)
        else:
            self.send_data({"error": "Not found"}, status=404)

    def do_POST(self):
        endpoint = urlsplit(self.path).path
        if endpoint not in ("/api/action", "/api/mission", "/api/mission/execute"):
            return self.send_data({"error": "Not found"}, status=404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 800000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            with LOCK:
                if endpoint == "/api/mission":
                    data = PROJECT.plan_mission(payload.get("message", ""))
                elif endpoint == "/api/mission/execute":
                    data = PROJECT.execute_mission(payload.get("mission_id", ""))
                else:
                    data = PROJECT.apply(payload)
            self.send_data(data)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self.send_data({"error": str(error)}, status=400)


def start(port=PORT, open_browser=True):
    address = f"http://{HOST}:{port}"
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"\nDynamic Routing Using MultiAgents — Step 8 · Refined UI\nOpen {address}\nPress Ctrl+C to stop.\n")
    if open_browser:
        # Opening is optional: the URL can always be pasted into any browser.
        from threading import Timer
        Timer(0.6, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    start()
