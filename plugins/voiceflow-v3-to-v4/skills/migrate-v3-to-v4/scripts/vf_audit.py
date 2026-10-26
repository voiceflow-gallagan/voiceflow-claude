#!/usr/bin/env python3
"""Parse a Voiceflow v3 .vf export and write a migration audit.

Usage:
    python3 vf_audit.py <project.vf> [--out DIR]

Writes two files next to the .vf (or into --out):
    <name>.audit.md   human-readable audit (Phase 1 of the V4 migration guide)
    <name>.ir.json    normalized intermediate representation used by the build phase

Standard library only. Credentials found in the file are never written out:
header values, inline tokens and suspicious code literals are replaced with
<REDACTED> and listed by location so they can be recreated as secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

REDACTED = "<REDACTED>"
SAFE_HEADERS = {"content-type", "accept", "user-agent", "accept-language", "cache-control"}
TOKEN_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}"           # OpenAI-style keys
    r"|shpat_[A-Za-z0-9]{20,}"          # Shopify admin tokens
    r"|pat-[a-z]{2}\d-[0-9a-f-]{20,}"   # HubSpot private app tokens
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"   # Slack tokens
    r"|gh[pousr]_[A-Za-z0-9]{30,}"      # GitHub tokens
    r"|AKIA[0-9A-Z]{16}"                # AWS access key IDs
    r"|VF\.(?:DM|API)\.[A-Za-z0-9.]{10,}"  # Voiceflow API keys
    r"|Bearer\s+(?!\{)[A-Za-z0-9._~+/=-]{12,})"
)
CODE_SECRET_RE = re.compile(
    r"((?:api[_-]?key|apikey|token|secret|password|authorization)\s*[:=]\s*['\"`])([^'\"`{]{12,})(['\"`])",
    re.IGNORECASE,
)
VAR_RE = re.compile(r"\{\{\[([^\]]+)\]\.[^}]*\}\}")

# How each v3 step type is reported, and the default v4 target (see references/step-mapping.md).
STEP_KINDS = {
    "start": ("Start", "Initialization workflow / Start message"),
    "block": ("Block", "Workflow block"),
    "message": ("Message", "Message step (scripted)"),
    "text": ("Message", "Message step (scripted)"),
    "speak": ("Speak", "Message step (voice)"),
    "visual": ("Visual", "Message step with image / Card"),
    "card": ("Card", "Card system tool or Card step"),
    "cardV2": ("Card", "Card system tool or Card step"),
    "carousel": ("Carousel", "Carousel system tool or step"),
    "buttons": ("Buttons", "Buttons step or Buttons system tool"),
    "choice": ("Choice", "Buttons step / Operator step / Playbook"),
    "interaction": ("Choice", "Buttons step / Operator step / Playbook"),
    "prompt": ("Prompt (listen)", "Playbook or Listen step"),
    "captureV2": ("Capture", "Playbook with structured output, or Listen step"),
    "capture": ("Capture", "Playbook with structured output, or Listen step"),
    "intent": ("Intent trigger", "Agent instruction routing to a skill"),
    "trigger": ("Trigger", "Agent instruction routing to a skill"),
    "command": ("Command (global intent)", "Agent instruction routing to a skill"),
    "goTo": ("Go to intent", "Workflow step / Playbook step / instruction"),
    "goToNode": ("Go to block", "Link to a workflow block"),
    "component": ("Component", "Sub-workflow (Workflow step) or Crew step"),
    "flow": ("Flow (legacy component)", "Sub-workflow (Workflow step)"),
    "exit": ("End", "End conversation system tool / End step"),
    "ifV2": ("Condition", "Condition step or Operator step"),
    "if": ("Condition", "Condition step or Operator step"),
    "setV2": ("Set", "Set step"),
    "set-v3": ("Set", "Set step"),
    "set": ("Set", "Set step"),
    "random": ("Random", "Message step with variants"),
    "randomV2": ("Random", "Message step with variants"),
    "api": ("API", "API tool + API step"),
    "integration": ("Integration (legacy)", "API tool or Integration tool"),
    "code": ("Code", "Function tool + Function step (or Code step)"),
    "generative": ("AI Response (deprecated)", "Message step in Prompt mode, or Playbook"),
    "ai_set": ("AI Set (deprecated)", "Structured output / Operator step / Playbook"),
    "trace": ("Custom action", "Custom action / event (manual review)"),
    "actions": ("Port actions", "Port actions on a workflow exit"),
    "knowledgeBase": ("KB answer", "Knowledge Base system tool"),
    "kb": ("KB answer", "Knowledge Base system tool"),
    "agent": ("Agent step", "Playbook"),
    "function": ("Function", "Function tool + Function step"),
}
SKIP_TYPES = {"markup_text", "markup_image", "markup_video", "comment"}


# ---------------------------------------------------------------- helpers

def norm_vars(text):
    """{{[name].id}} -> {name}"""
    if not isinstance(text, str):
        return text
    return VAR_RE.sub(lambda m: "{" + m.group(1) + "}", text)


def slate_text(node, entities=None):
    """Flatten Slate / CMS rich text into a plain string."""
    entities = entities or {}
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(slate_text(n, entities) for n in node)
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], (str, list)):
            return slate_text(node["text"], entities)
        if "children" in node:
            return slate_text(node["children"], entities)
        if "content" in node:
            return slate_text(node["content"], entities)
        if "entityID" in node:
            return "{" + entities.get(node["entityID"], node["entityID"]) + "}"
        if "variableID" in node:
            return "{" + str(node["variableID"]) + "}"
    return ""


class Redactor:
    def __init__(self):
        self.findings = []

    def text(self, value, where):
        if not isinstance(value, str):
            return value
        out, n = TOKEN_RE.subn(REDACTED, value)
        if n:
            self.findings.append({"where": where, "kind": "inline token", "count": n})
        return out

    def header(self, key, value, where):
        k = (key or "").strip()
        v = value if isinstance(value, str) else ""
        if k.lower() in SAFE_HEADERS or not v:
            return v
        if "{{" in v or re.fullmatch(r"\s*(Bearer\s+)?\{[A-Za-z0-9_]+\}\s*", norm_vars(v)):
            return norm_vars(v)  # already a variable reference
        if "<" in v and ">" in v and len(v) < 60:
            self.findings.append({"where": where, "kind": "placeholder", "header": k})
            return v
        if len(v) >= 12:
            self.findings.append({"where": where, "kind": "header credential", "header": k})
            return REDACTED
        return v

    def code(self, value, where):
        if not isinstance(value, str):
            return value
        value = self.text(value, where)
        out, n = CODE_SECRET_RE.subn(lambda m: m.group(1) + REDACTED + m.group(3), value)
        if n:
            self.findings.append({"where": where, "kind": "code literal", "count": n})
        return out


# ---------------------------------------------------------------- loader

class VF:
    def __init__(self, path):
        with open(path, encoding="utf-8") as fh:
            self.d = json.load(fh)
        d = self.d
        self.version = d.get("version", {})
        self.project = d.get("project", {})
        self.pd = self.version.get("platformData", {}) or {}
        self.red = Redactor()

        # entities: platformData.slots first, CMS entities as fallback
        self.entities = {}
        for s in self.pd.get("slots", []) or []:
            self.entities[s.get("key")] = {
                "name": s.get("name"),
                "type": (s.get("type") or {}).get("value"),
                "values": [v for v in (s.get("inputs") or []) if isinstance(v, str)],
            }
        variants = defaultdict(list)
        for v in d.get("entityVariants", []) or []:
            variants[v.get("entityID")].append(",".join([v.get("value", "")] + (v.get("synonyms") or [])))
        for e in d.get("entities", []) or []:
            ent = self.entities.setdefault(e["id"], {"name": e.get("name"), "type": e.get("classifier"), "values": []})
            if not ent["values"]:
                ent["values"] = variants.get(e["id"], [])
        self.entity_names = {k: v["name"] for k, v in self.entities.items()}

        # intents: platformData first, CMS as fallback
        self.intents = {}
        for i in self.pd.get("intents", []) or []:
            self.intents[i.get("key")] = {
                "name": i.get("name"),
                "utterances": [norm_vars(x.get("text", "")).strip() for x in i.get("inputs", []) or []],
                "entities": sorted({self.entity_names.get(s, s) for x in i.get("inputs", []) or [] for s in x.get("slots", []) or []}),
            }
        utt = defaultdict(list)
        for u in d.get("utterances", []) or []:
            utt[u.get("intentID")].append(slate_text(u.get("text"), self.entity_names).strip())
        for i in d.get("intents", []) or []:
            it = self.intents.setdefault(i["id"], {"name": i.get("name"), "utterances": [], "entities": []})
            if not it["utterances"]:
                it["utterances"] = utt.get(i["id"], [])
            if i.get("description"):
                it["description"] = i["description"]

        # variables
        names = set(self.version.get("variables") or [])
        for v in d.get("variables", []) or []:
            if not v.get("isSystem"):
                names.add(v.get("name"))
        self.variables = sorted(n for n in names if n and not n.startswith("vf_"))

        # CMS messages: response -> discriminators -> messages
        msgs_by_disc = defaultdict(list)
        for m in d.get("responseMessages", []) or []:
            msgs_by_disc[m.get("discriminatorID")].append(m)
        self.messages = {}
        for disc in d.get("responseDiscriminators", []) or []:
            texts = [norm_vars(slate_text(m.get("text"), self.entity_names)).strip() for m in msgs_by_disc[disc["id"]]]
            self.messages.setdefault(disc.get("responseID"), []).extend(t for t in texts if t)

        self.topic_ids = [t.get("sourceID") for t in self.version.get("topics") or []]
        self.component_ids = [c.get("sourceID") for c in self.version.get("components") or []]

    # ------------------------------------------------------------ steps

    def channel(self):
        t = (self.project.get("type") or "").lower()
        p = (self.project.get("platform") or "").lower()
        if t == "voice" or "voice" in p or p in {"alexa", "google", "phone", "voiceflow_voice"}:
            return "voice"
        return "chat"

    def step(self, node, where):
        t = node.get("type")
        data = node.get("data", {}) or {}
        label, target = STEP_KINDS.get(t, (f"Unknown ({t})", "Manual review"))
        s = {"id": node.get("nodeID"), "type": t, "label": label, "v4": target}
        name = data.get("name") or data.get("label") or data.get("title")
        if name:
            s["name"] = name
        r = self.red
        if t in ("message",):
            s["text"] = self.messages.get(data.get("messageID"), [])
        elif t == "text":
            s["text"] = [norm_vars(slate_text(x.get("content"), self.entity_names)) for x in data.get("texts", []) or []]
        elif t == "speak":
            s["text"] = [norm_vars(x.get("content", "")) for x in data.get("dialogs", []) or []]
        elif t in ("buttons", "prompt", "interaction", "choice"):
            btns = data.get("buttons") or []
            s["buttons"] = [b.get("name") for b in btns if b.get("name")]
            intents = [self.intents.get(((b.get("payload") or {}).get("intentID")), {}).get("name") for b in btns]
            intents += [self.intents.get(c.get("intent"), {}).get("name") for c in data.get("choices", []) or []]
            if any(intents):
                s["intents"] = [i for i in intents if i]
            nm = data.get("noMatch") or data.get("else") or {}
            reps = [norm_vars(slate_text(x.get("content"), self.entity_names)) for x in nm.get("reprompts", []) or []]
            if any(reps):
                s["no_match"] = [x for x in reps if x]
        elif t in ("captureV2", "capture"):
            cap = data.get("capture") or {}
            if cap.get("type") == "query":
                s["captures"] = {"variable": cap.get("variable"), "mode": "full utterance"}
            else:
                slots = (cap.get("intent") or {}).get("slots") or []
                s["captures"] = {
                    "mode": "entities",
                    "entities": [self.entity_names.get(x.get("id"), x.get("id")) for x in slots],
                    "prompts": [slate_text(p.get("content"), self.entity_names) for x in slots for p in (x.get("dialog") or {}).get("prompt", []) or []],
                }
        elif t in ("intent", "command", "goTo"):
            s["intent"] = self.intents.get(data.get("intent"), {}).get("name")
            if data.get("diagramID"):
                s["diagram"] = data.get("diagramID")
        elif t == "trigger":
            s["intents"] = [self.intents.get(i.get("resourceID"), {}).get("name") for i in data.get("items", []) or [] if i.get("type") == "intent"]
        elif t == "component" or t == "flow":
            s["diagram"] = data.get("diagramID")
        elif t in ("ifV2", "if"):
            s["conditions"] = [e.get("name") or json.dumps(e.get("value"))[:200] for e in data.get("expressions", []) or []]
        elif t in ("setV2", "set-v3", "set"):
            items = data.get("sets") or data.get("items") or []
            s["sets"] = [{"variable": i.get("variable") or i.get("variableID"),
                          "value": r.code(norm_vars(i.get("expression") if "expression" in i else " ".join(map(str, i.get("value") or []))), where)}
                         for i in items]
        elif t == "api":
            hdrs = [{"key": h.get("key"), "value": r.header(h.get("key"), h.get("val"), where)} for h in data.get("headers", []) or [] if h.get("key")]
            s["api"] = {
                "method": data.get("method"),
                "url": r.text(norm_vars(data.get("url", "")), where),
                "headers": hdrs,
                "params": [{"key": p.get("key"), "value": r.text(norm_vars(p.get("val")), where)} for p in data.get("params", []) or [] if p.get("key")],
                "body_type": data.get("bodyType"),
                "body": r.code(norm_vars(data.get("content") or ""), where) or None,
                "mappings": [{"path": m.get("path"), "variable": m.get("var")} for m in data.get("mappings", []) or []],
            }
        elif t == "code":
            s["code"] = r.code(data.get("code", ""), where)
        elif t == "generative":
            s["ai"] = {k: norm_vars(data.get(k)) for k in ("prompt", "system", "model", "temperature", "maxTokens") if data.get(k) not in (None, "")}
        elif t == "ai_set":
            s["ai"] = {k: data.get(k) for k in ("system", "model", "temperature", "maxTokens") if data.get(k) not in (None, "")}
            s["sets"] = [{"variable": x.get("variable"), "prompt": norm_vars(x.get("prompt"))} for x in data.get("sets", []) or []]
        elif t == "trace":
            s["custom_action"] = (data.get("payload") or {}).get("name")
            s["paths"] = [p.get("label") for p in data.get("paths", []) or []]
        elif t == "visual":
            s["image"] = data.get("image")
        return s

    def links(self, node):
        ports = (node.get("data") or {}).get("portsV2") or {}
        out = []
        for group in ("builtIn", "byKey"):
            for key, p in (ports.get(group) or {}).items():
                if p and p.get("target"):
                    out.append({"port": key, "to": p["target"]})
        for i, p in enumerate(ports.get("dynamic") or []):
            if p and p.get("target"):
                out.append({"port": f"path{i + 1}", "to": p["target"]})
        return out

    def diagrams(self):
        result = []
        unknown = Counter()
        for did, dg in (self.d.get("diagrams") or {}).items():
            nodes = dg.get("nodes") or {}
            in_block = {sid for n in nodes.values() if n.get("type") == "block" for sid in (n.get("data") or {}).get("steps", [])}
            blocks = []
            for nid, n in nodes.items():
                t = n.get("type")
                if t in SKIP_TYPES or nid in in_block:
                    continue
                where = f"{dg.get('name')} / {(n.get('data') or {}).get('name') or t}"
                if t == "block":
                    steps = []
                    for sid in (n.get("data") or {}).get("steps", []):
                        sn = nodes.get(sid)
                        if not sn or sn.get("type") in SKIP_TYPES:
                            continue
                        if sn.get("type") not in STEP_KINDS:
                            unknown[sn.get("type")] += 1
                        st = self.step(sn, f"{dg.get('name')} / {(n.get('data') or {}).get('name')}")
                        st["links"] = self.links(sn)
                        steps.append(st)
                    blocks.append({"id": nid, "name": (n.get("data") or {}).get("name"), "steps": steps})
                else:
                    if t not in STEP_KINDS:
                        unknown[t] += 1
                    st = self.step(n, where)
                    st["links"] = self.links(n)
                    blocks.append({"id": nid, "name": st.get("name") or st["label"], "steps": [st]})
            kind = dg.get("type") or ("TOPIC" if did in self.topic_ids else "COMPONENT" if did in self.component_ids else "DIAGRAM")
            result.append({"id": did, "name": dg.get("name"), "kind": kind, "blocks": blocks})
        return result, unknown

    def build(self):
        diagrams, unknown = self.diagrams()
        steps = [s for dg in diagrams for b in dg["blocks"] for s in b["steps"]]
        counts = Counter(s["label"] for s in steps)
        settings = self.version.get("settings") or {}
        ir = {
            "source": {
                "name": self.project.get("name"),
                "channel": self.channel(),
                "platform": self.project.get("platform"),
                "project_type": self.project.get("type"),
                "schema_version": self.version.get("_version"),
                "intent_classification": (settings.get("intentClassification") or {}).get("type") or "nlu (default)",
            },
            "variables": self.variables,
            "entities": [{"id": k, **v} for k, v in self.entities.items()],
            "intents": [{"id": k, **v, "builtin": str(v.get("name", "")).startswith(("VF.", "AMAZON.", "actions.")) or v.get("name") == "None"} for k, v in self.intents.items()],
            "diagrams": diagrams,
            "step_counts": dict(counts),
            "unknown_step_types": dict(unknown),
            "credentials": self.red.findings,
        }
        return ir


# ---------------------------------------------------------------- audit

def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def audit_md(ir):
    src = ir["source"]
    out = []
    w = out.append
    w(f"# Migration audit: {src['name']}\n")
    w("Phase 1 of the Voiceflow V4 migration guide: what this v3 agent does, and what has to be rebuilt.\n")
    w("| Field | Value |\n|---|---|")
    for k, label in (("channel", "Channel"), ("platform", "Platform"), ("schema_version", "Schema version"), ("intent_classification", "Intent classification")):
        w(f"| {label} | {md_escape(src.get(k))} |")
    topics = [d for d in ir["diagrams"] if d["kind"] == "TOPIC"]
    comps = [d for d in ir["diagrams"] if d["kind"] == "COMPONENT"]
    custom_intents = [i for i in ir["intents"] if not i["builtin"]]
    w(f"| Topics / components | {len(topics)} / {len(comps)} |")
    w(f"| Custom intents (utterances) | {len(custom_intents)} ({sum(len(i['utterances']) for i in custom_intents)}) |")
    w(f"| Entities | {len(ir['entities'])} |")
    w(f"| Variables | {len(ir['variables'])} |\n")

    if ir["credentials"]:
        w("## ⚠️ Credentials found in the file\n")
        w("These values were redacted and never copied. Recreate each one as a Voiceflow secret and rotate any key that was shared with this file.\n")
        w("| Where | Kind | Header |\n|---|---|---|")
        for c in ir["credentials"]:
            w(f"| {md_escape(c['where'])} | {c['kind']} | {md_escape(c.get('header', ''))} |")
        w("")

    w("## Step inventory\n")
    w("| v3 step | Count |\n|---|---|")
    for k, v in sorted(ir["step_counts"].items(), key=lambda x: -x[1]):
        w(f"| {md_escape(k)} | {v} |")
    if ir["unknown_step_types"]:
        w(f"\nUnknown step types (manual review): {', '.join(f'{k} ×{v}' for k, v in ir['unknown_step_types'].items())}")
    w("")

    w("## Intents\n")
    w("In v4 each intent becomes an instruction line routing to a skill. The utterances become routing test cases.\n")
    for i in ir["intents"]:
        tag = " (built-in)" if i["builtin"] else ""
        w(f"- **{md_escape(i['name'])}**{tag}: {len(i['utterances'])} utterances" + (f", entities {', '.join(i['entities'])}" if i.get("entities") else ""))
        for u in i["utterances"][:3]:
            w(f"  - \"{md_escape(u)}\"")
    w("")

    if ir["entities"]:
        w("## Entities\n")
        w("| Entity | Type | Values |\n|---|---|---|")
        for e in ir["entities"]:
            vals = ", ".join(v.split(",")[0] for v in e["values"][:6]) + (" …" if len(e["values"]) > 6 else "")
            w(f"| {md_escape(e['name'])} | {md_escape(e.get('type'))} | {md_escape(vals)} |")
        w("")

    if ir["variables"]:
        w("## Variables\n")
        w(", ".join(f"`{v}`" for v in ir["variables"]) + "\n")

    w("## Topics and components\n")
    for dg in ir["diagrams"]:
        if dg["kind"] == "TEMPLATE":
            continue
        steps = [s for b in dg["blocks"] for s in b["steps"]]
        triggers = sorted({i for s in steps for i in ([s.get("intent")] if s.get("intent") else []) + (s.get("intents") or []) if i and s["type"] in ("intent", "trigger")})
        w(f"### {md_escape(dg['name'])} ({dg['kind'].lower()}, {len(steps)} steps)\n")
        if triggers:
            w(f"Triggered by: {', '.join(triggers)}\n")
        for s in steps:
            line = f"- {s['label']}"
            if s.get("name") and s["name"] not in (s["label"], "Text", "Buttons", "Capture"):
                line += f" «{md_escape(s['name'])}»"
            if s.get("text"):
                line += f": \"{md_escape(s['text'][0])[:160]}\""
            if s.get("buttons"):
                line += f": [{', '.join(map(md_escape, s['buttons']))}]"
            if s.get("captures"):
                c = s["captures"]
                line += f": → {c.get('variable') or ', '.join(c.get('entities') or [])}"
            if s.get("api"):
                line += f": {s['api']['method']} {md_escape(s['api']['url'])}"
            if s.get("ai") and s["ai"].get("prompt"):
                line += f": prompt \"{md_escape(s['ai']['prompt'])[:160]}\""
            if s.get("sets") and s["type"] == "ai_set":
                line += ": " + "; ".join(f"{x.get('variable')} ← \"{md_escape(x.get('prompt') or '')[:120]}\"" for x in s["sets"])
            if s.get("conditions"):
                line += f": {'; '.join(map(md_escape, s['conditions']))[:160]}"
            if s.get("intent") and s["type"] in ("goTo", "command"):
                line += f": {s['intent']}"
            if s.get("custom_action"):
                line += f": {md_escape(s['custom_action'])} (paths: {', '.join(s.get('paths') or [])})"
            w(line)
        w("")

    w("## Needs a human\n")
    needs = []
    if ir["credentials"]:
        needs.append("Recreate the redacted credentials as secrets (see above).")
    if ir["step_counts"].get("AI Response (deprecated)") or ir["step_counts"].get("AI Set (deprecated)"):
        needs.append("AI Response / AI Set steps: confirm the model and prompt for the v4 replacement (Message step in Prompt mode, structured output or Playbook).")
    if ir["step_counts"].get("Code"):
        needs.append("Code steps: review each one before it becomes a Function tool.")
    if ir["step_counts"].get("Custom action"):
        needs.append("Custom actions: the client integration that handled them must be checked against v4.")
    if ir["source"]["channel"] == "voice":
        needs.append("Voice project: build as a phone-call project and review voices and reprompts.")
    if ir["unknown_step_types"]:
        needs.append("Unknown step types listed above.")
    needs.append("Knowledge base: a .vf export does not contain KB documents. List the source URLs and files to re-add in v4.")
    for n in needs:
        w(f"- {n}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vf", help="path to the .vf export")
    ap.add_argument("--out", help="output directory (default: next to the .vf)")
    ap.add_argument("--stdout", action="store_true", help="print the audit instead of writing files")
    a = ap.parse_args(argv)
    try:
        ir = VF(a.vf).build()
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"error: {a.vf} is not a readable .vf export ({e})", file=sys.stderr)
        return 1
    md = audit_md(ir)
    if a.stdout:
        print(md)
        return 0
    base = os.path.splitext(os.path.basename(a.vf))[0]
    out = a.out or os.path.dirname(os.path.abspath(a.vf))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, base + ".audit.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(out, base + ".ir.json"), "w", encoding="utf-8") as fh:
        json.dump(ir, fh, indent=2, ensure_ascii=False)
    print(json.dumps({"audit": os.path.join(out, base + ".audit.md"), "ir": os.path.join(out, base + ".ir.json"),
                      "steps": sum(ir["step_counts"].values()), "unknown": ir["unknown_step_types"],
                      "credentials": len(ir["credentials"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
