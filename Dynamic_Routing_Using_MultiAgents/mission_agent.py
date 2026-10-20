"""Step 8: natural-language mission planner for our existing Main Agent.

Offline planning works without dependencies. Optional Gemini provides structured
intent parsing, but never executes model-generated code or unapproved commands.
"""
import json
import os
import re
from urllib import request, error


class MissionAgent:
    ALLOWED = {"inspect", "preview", "compare", "traffic", "attack", "overload", "restore"}

    def __init__(self, network):
        self.network = network

    def assess(self, message):
        if not isinstance(message, str) or not 3 <= len(message.strip()) <= 450:
            raise ValueError("Enter a mission between 3 and 450 characters")
        return {"message": message.strip(), "devices": sorted(self.network.devices),
                "forwarders": sorted(n for n, d in self.network.devices.items()
                                     if d.kind in ("ROUTER", "SWITCH"))}

    def plan(self, facts):
        if os.environ.get("GEMINI_API_KEY", "").strip():
            try:
                suggestion = self._gemini(facts)
                return self._validate(suggestion, facts, "Gemini-assisted")
            except (ValueError, KeyError, TimeoutError, OSError, error.URLError) as exc:
                fallback = self._offline(facts)
                planned = self._validate(fallback, facts, "Offline fallback")
                planned["note"] = f"Cloud planner unavailable ({type(exc).__name__}); used local rules."
                return planned
        return self._validate(self._offline(facts), facts, "Offline rules")

    def act(self, plan):
        return plan  # Only the Main Agent can execute a user-approved plan.

    def check(self, result):
        return result

    def run(self, message):
        return self.check(self.act(self.plan(self.assess(message))))

    def _offline(self, facts):
        raw = facts["message"]
        text = raw.lower()
        named = [n for n in facts["devices"] if re.search(r'(?<![\w])' + re.escape(n) + r'(?![\w])', raw, re.I)]
        forwarders = [n for n in named if n in facts["forwarders"]]
        match_src = re.search(r'\bfrom\s+([\w-]+)', text)
        match_dst = re.search(r'\b(?:to|towards)\s+([\w-]+)', text)
        src = next((n for n in facts["devices"] if match_src and n.lower() == match_src[1]), None)
        dst = next((n for n in facts["devices"] if match_dst and n.lower() == match_dst[1]), None)
        if not src and named: src = named[0]
        if not dst: dst = next((n for n in named if n != src), None)
        if not src: src = next((n for n in facts["devices"] if self.network.devices[n].kind == "PC"), None)
        if not dst: dst = next((n for n in facts["devices"] if self.network.devices[n].kind == "SERVER"), None)
        if not dst or dst == src: dst = next((n for n in facts["devices"] if n != src), None)
        numbers = re.findall(r'\b\d+\b', text)
        def grab(pattern, default, maximum):
            m = re.search(pattern, text)
            return min(maximum, int(m[1])) if m else default
        rate = grab(r'(\d+)\s*(?:packets?|pkts?)\s*(?:per\s*step|/\s*step)', 4, 100)
        steps = grab(r'(?:for\s+)?(\d+)\s*(?:simulation\s*)?steps?', 10, 30)
        target = forwarders[0] if forwarders else None
        if any(w in text for w in ("restore", "repair", "recover", "reset trust")):
            intent = "restore"
        elif any(w in text for w in ("blackhole", "grayhole", "attack", "malicious", "compromised")):
            intent = "attack"
        elif any(w in text for w in ("overload", "congest", "bottleneck", "capacity")):
            intent = "overload"
        elif any(w in text for w in ("compare", "dijkstra vs", "versus")):
            intent = "compare"
        elif any(w in text for w in ("send", "transmit", "traffic", "run", "packets", "simulate")):
            intent = "traffic"
        elif any(w in text for w in ("route", "path", "navigate", "deliver")):
            intent = "preview"
        else:
            intent = "inspect"
        return {"intent":intent,"source":src,"target":dst if intent not in ("attack","overload","restore") else target,
                "rate":rate,"steps":steps,
                "behavior":"grayhole" if "grayhole" in text else "blackhole"}

    def _gemini(self, facts):
        api_key = os.environ["GEMINI_API_KEY"].strip()
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
            raise ValueError("Invalid Gemini model name")
        system = ("You translate the user's simulated network request to ONE JSON object. "
                  "Never invent devices or introduce new actions. Return only keys: "
                  "intent (inspect|preview|compare|traffic|attack|overload|restore), "
                  "source, target, rate, steps, behavior (blackhole|grayhole). "
                  "For attack/overload/restore target is the router or switch. "
                  "For other intents source and target are different existing devices. "
                  "rate <= 100, steps <= 30. Default inspect if ambiguous. "
                  "This is a safe simulation, not real network control.")
        payload = {"systemInstruction":{"parts":[{"text":system}]},
                   "contents":[{"role":"user","parts":[{"text":json.dumps(facts)}]}],
                   "generationConfig":{"responseMimeType":"application/json","temperature":0.1}}
        req = request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type":"application/json", "x-goog-api-key":api_key})
        with request.urlopen(req, timeout=8) as response:
            doc = json.load(response)
        content = doc["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(content)

    def _validate(self, plan, facts, mode):
        if not isinstance(plan, dict): raise ValueError("Expected a plan")
        intent = str(plan.get("intent", "inspect")).lower()
        if intent not in self.ALLOWED: intent = "inspect"
        valid = facts["devices"]
        forwarders = facts["forwarders"]
        source = plan.get("source") if plan.get("source") in valid else None
        target = plan.get("target") if plan.get("target") in valid else None
        if intent in ("attack", "overload", "restore"):
            if target not in forwarders:
                raise ValueError("Mention an existing router or switch, e.g. R2")
            source = None
        elif intent in ("traffic", "preview", "compare"):
            if source not in valid or target not in valid or source == target:
                raise ValueError("Mention two different existing devices, e.g. PC1 and S1")
        rate = plan.get("rate", 4)
        steps = plan.get("steps", 10)
        try:
            rate, steps = int(rate), int(steps)
        except (ValueError, TypeError):
            rate, steps = 4, 10
        rate, steps = max(0,min(100,rate)), max(1,min(30,steps))
        behavior = plan.get("behavior") if plan.get("behavior") in ("blackhole", "grayhole") else "blackhole"
        descriptions = {
            "inspect":"Ask the monitoring agents for network health, trust and queues",
            "preview":f"Ask Routing Agent for a path from {source} to {target}",
            "compare":f"Compare shortest-path and Q-Learning from {source} to {target}",
            "traffic":f"Generate {rate} packets/step from {source} to {target} for {steps} steps",
            "attack":f"Simulate {behavior} forwarding on {target}",
            "overload":f"Simulate congestion on {target} (capacity 2, queue 8)",
            "restore":f"Restore normal forwarding and trust on {target}",
        }
        return {"intent":intent,"source":source,"target":target,"rate":rate,"steps":steps,
                "behavior":behavior,"mode":mode,"summary":descriptions[intent],
                "cycle":["Assess network state", "Plan specialized-agent tasks", descriptions[intent],
                         "Check feedback and update the Main Agent"]}
