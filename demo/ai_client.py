"""
Multi-provider AI client with automatic fallback.

Fallback chain:
  1. Ollama (local, free, private)         — http://localhost:11434
  2. Anthropic Claude (cloud, paid)        — ANTHROPIC_API_KEY
  3. OpenAI / OpenAI-compatible (cloud)    — OPENAI_API_KEY
  4. Deterministic keyword-based fallback  — no network needed

Each provider returns the same dict: {answer, model, provider, latency_ms, ok}.
A provider is "available" when its health check passes; the client picks the
first available one and falls through on error.

Configure via env vars (all optional):
  AEAOP_OLLAMA_URL        default http://localhost:11434
  AEAOP_OLLAMA_MODEL      default qwen2.5:7b
  ANTHROPIC_API_KEY       enables Claude fallback
  ANTHROPIC_MODEL         default claude-haiku-4-5-20251001
  OPENAI_API_KEY          enables OpenAI fallback
  OPENAI_BASE_URL         override (for vLLM/LM-studio/OpenRouter)
  OPENAI_MODEL            default gpt-4o-mini
"""
from __future__ import annotations
import json
import os
import time
from typing import Any, Optional

import httpx


# ── Config (read once at import) ─────────────────────────────────────────────

OLLAMA_URL    = os.getenv("AEAOP_OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL  = os.getenv("AEAOP_OLLAMA_MODEL", "qwen2.5:7b")

# Ranked chat-model preferences when no explicit AEAOP_OLLAMA_MODEL is set.
# We pick the first model the user actually has installed.
_OLLAMA_CHAT_PREFERENCES = [
    "qwen2.5", "qwen3", "llama3.3", "llama3.2", "llama3.1", "llama3",
    "mistral", "gemma3", "gemma2", "deepseek", "phi3",
]
# Substring blocklist — these are embedding/code-only models, not chat.
_OLLAMA_NON_CHAT_HINTS = ["embed", "embedding", "rerank"]
_resolved_ollama_model: Optional[str] = None  # cached after first probe


async def _resolve_ollama_model() -> Optional[str]:
    """Return a chat-capable model that's actually installed locally."""
    global _resolved_ollama_model
    if _resolved_ollama_model is not None:
        return _resolved_ollama_model
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.5)) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            tags = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None

    if not tags:
        return None

    # If user-set model exists, use it.
    if OLLAMA_MODEL in tags or any(t.split(":")[0] == OLLAMA_MODEL.split(":")[0] for t in tags):
        _resolved_ollama_model = OLLAMA_MODEL if OLLAMA_MODEL in tags else \
            next(t for t in tags if t.split(":")[0] == OLLAMA_MODEL.split(":")[0])
        return _resolved_ollama_model

    # Strip embedding-only models
    chat_tags = [t for t in tags if not any(h in t.lower() for h in _OLLAMA_NON_CHAT_HINTS)]

    # Match in preference order
    for pref in _OLLAMA_CHAT_PREFERENCES:
        for t in chat_tags:
            if pref in t.lower():
                _resolved_ollama_model = t
                return t

    # Last resort: first non-embedding model
    if chat_tags:
        _resolved_ollama_model = chat_tags[0]
        return chat_tags[0]

    return None

ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

OPENAI_KEY      = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ── Provider implementations ─────────────────────────────────────────────────


_LAST_OLLAMA_ERROR: Optional[str] = None


def last_ollama_error() -> Optional[str]:
    return _LAST_OLLAMA_ERROR


async def _try_ollama(messages: list[dict], system: str = "") -> Optional[dict]:
    """Call local Ollama. Returns None if not reachable or no chat model installed."""
    global _LAST_OLLAMA_ERROR
    model = await _resolve_ollama_model()
    if not model:
        _LAST_OLLAMA_ERROR = "no chat-capable model installed"
        return None
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=2.0)) as c:
            payload = {
                "model":    model,
                "messages": ([{"role": "system", "content": system}] if system else []) + messages,
                "stream":   False,
                "options":  {"temperature": 0.3, "num_ctx": 4096},
            }
            r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
            if r.status_code >= 400:
                # Capture the error body so we can show it to the operator
                try:
                    err = r.json().get("error", r.text)
                except Exception:
                    err = r.text
                _LAST_OLLAMA_ERROR = f"HTTP {r.status_code}: {err[:300]}"
                return None
            data = r.json()
        text = data.get("message", {}).get("content", "").strip()
        if not text:
            _LAST_OLLAMA_ERROR = "empty response"
            return None
        _LAST_OLLAMA_ERROR = None
        return {
            "answer":     text,
            "model":      f"ollama/{model}",
            "provider":   "ollama (local)",
            "latency_ms": int((time.time() - t0) * 1000),
            "ok":         True,
        }
    except Exception as e:
        _LAST_OLLAMA_ERROR = f"{type(e).__name__}: {e}"
        return None


async def _try_anthropic(messages: list[dict], system: str = "") -> Optional[dict]:
    """Call Anthropic Claude. Returns None if no key or fails."""
    if not ANTHROPIC_KEY:
        return None
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as c:
            payload: dict[str, Any] = {
                "model":      ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "messages":   messages,
            }
            if system:
                payload["system"] = system
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers={
                    "x-api-key":         ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return {
            "answer":     text.strip(),
            "model":      f"anthropic/{ANTHROPIC_MODEL}",
            "provider":   "anthropic (cloud)",
            "latency_ms": int((time.time() - t0) * 1000),
            "ok":         True,
        }
    except Exception:
        return None


async def _try_openai(messages: list[dict], system: str = "") -> Optional[dict]:
    """Call OpenAI-compatible API. Returns None if no key or fails."""
    if not OPENAI_KEY:
        return None
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as c:
            payload = {
                "model":       OPENAI_MODEL,
                "messages":    ([{"role": "system", "content": system}] if system else []) + messages,
                "temperature": 0.3,
                "max_tokens":  1024,
            }
            r = await c.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"]
        return {
            "answer":     text.strip(),
            "model":      f"openai/{OPENAI_MODEL}",
            "provider":   "openai-compatible (cloud)",
            "latency_ms": int((time.time() - t0) * 1000),
            "ok":         True,
        }
    except Exception:
        return None


# ── Keyword-based deterministic fallback (never fails) ───────────────────────

_FALLBACK = {
    "bgp":     "**BGP Session Recovery (Cisco IOS-XE)**\n\n1. Verify BGP state: `show bgp summary`\n2. Check peer reachability: `ping <peer_ip> source <local_ip>`\n3. Clear soft: `clear ip bgp <peer_ip> soft`\n4. Hard reset if needed: `clear ip bgp <peer_ip>`\n5. Inspect logs: `show logging | include BGP`",
    "disk":    "**Linux Disk Space Recovery**\n\n1. Find biggest files: `find / -size +100M -type f 2>/dev/null | sort -k5 -rn`\n2. Clean old logs: `find /var/log -name '*.gz' -mtime +7 -delete`\n3. Journal cleanup: `journalctl --vacuum-time=7d`\n4. Package cache: `apt-get clean` / `yum clean all`",
    "cpu":     "**High CPU Investigation**\n\n1. Top process: `top -bn1 | head -20`\n2. Java GC: `jstat -gcutil <pid> 1000 5`\n3. Thread dump: `jstack <pid> > /tmp/dump.txt`\n4. If heap issue: restart with larger heap or analyse dump",
    "ssh":     "**SSH Brute Force Response**\n\n1. Block source IP at firewall: `iptables -I INPUT -s <ip> -j DROP`\n2. Check for successful logins: `grep 'Accepted' /var/log/auth.log`\n3. Reset any compromised accounts\n4. Enable fail2ban; disable password auth, use keys only",
    "default": "**Operations Guidance**\n\n1. Verify the alert is genuine (not a false positive)\n2. Identify affected systems and blast radius\n3. Check past incidents in the runbook KB\n4. Follow the matching runbook for this alert type\n5. Document every action in the incident timeline",
}


def _keyword_fallback(question: str) -> dict:
    q = question.lower()
    body = _FALLBACK["default"]
    if any(w in q for w in ["bgp", "ospf", "mpls", "routing"]):
        body = _FALLBACK["bgp"]
    elif any(w in q for w in ["disk", "storage", "partition", "/var"]):
        body = _FALLBACK["disk"]
    elif any(w in q for w in ["cpu", "memory", "heap", "performance"]):
        body = _FALLBACK["cpu"]
    elif any(w in q for w in ["ssh", "brute", "attack", "login"]):
        body = _FALLBACK["ssh"]
    return {
        "answer":     body,
        "model":      "keyword-fallback",
        "provider":   "deterministic (no LLM)",
        "latency_ms": 0,
        "ok":         True,
    }


# ── Public API ───────────────────────────────────────────────────────────────


async def chat(question: str, *, system: str = "", context: str = "") -> dict:
    """Send a single user question through the fallback chain.

    `context` (RAG-retrieved chunks, host metrics, etc.) is appended to the
    user message so the model sees grounded facts.
    """
    user_content = question
    if context:
        user_content = f"# Context\n{context}\n\n# Question\n{question}"

    messages = [{"role": "user", "content": user_content}]
    sys_prompt = system or (
        "You are AEAOP — an autonomous enterprise AI operations assistant. "
        "You help NOC/SOC/Server-Ops engineers diagnose and remediate issues. "
        "Be concise, use bullet/numbered steps, and prefer concrete shell/CLI commands. "
        "When a Context block is provided, ground your answer strictly in it."
    )

    attempts: list[str] = []
    for provider, name in ((_try_ollama, "ollama"), (_try_anthropic, "anthropic"), (_try_openai, "openai")):
        result = await provider(messages, system=sys_prompt)
        if result and result.get("answer"):
            if attempts:
                result["fallback_from"] = attempts
            return result
        attempts.append(name)

    fb = _keyword_fallback(question)
    fb["fallback_from"]  = attempts
    fb["fallback_reason"] = last_ollama_error() or "no LLM provider available — set ANTHROPIC_API_KEY or OPENAI_API_KEY, or `ollama pull qwen2.5:7b`"
    return fb


async def providers_status() -> dict:
    """Probe each provider so the UI can show which one will be used."""
    status = {"chain": ["ollama", "anthropic", "openai", "fallback"], "providers": {}}

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.5)) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            ok = r.status_code == 200
            models = [m["name"] for m in r.json().get("models", [])] if ok else []
        resolved = await _resolve_ollama_model()
        chat_capable = resolved is not None
        last_err = last_ollama_error()
        status["providers"]["ollama"] = {
            "available":      ok and chat_capable and not last_err,
            "reachable":      ok,
            "url":            OLLAMA_URL,
            "default_model":  OLLAMA_MODEL,
            "resolved_model": resolved,
            "models":         models,
            "last_error":     last_err,
            "note":           None if chat_capable else "ollama running but no chat model installed — run `ollama pull qwen2.5:7b` (smaller, fits 8GB RAM)",
        }
    except Exception:
        status["providers"]["ollama"] = {"available": False, "url": OLLAMA_URL, "default_model": OLLAMA_MODEL, "error": "not reachable"}

    status["providers"]["anthropic"] = {
        "available": bool(ANTHROPIC_KEY),
        "model":     ANTHROPIC_MODEL,
        "note":      "set ANTHROPIC_API_KEY to enable",
    }
    status["providers"]["openai"] = {
        "available": bool(OPENAI_KEY),
        "model":     OPENAI_MODEL,
        "base_url":  OPENAI_BASE_URL,
        "note":      "set OPENAI_API_KEY to enable",
    }
    status["providers"]["fallback"] = {
        "available": True,
        "note":      "deterministic keyword responses — always available",
    }

    # Which one will be picked first?
    picked = next(
        (name for name, p in [
            ("ollama",    status["providers"]["ollama"]),
            ("anthropic", status["providers"]["anthropic"]),
            ("openai",    status["providers"]["openai"]),
        ] if p.get("available")),
        "fallback",
    )
    status["active"] = picked
    return status


# ── Structured host explanation ──────────────────────────────────────────────

EXPLAIN_SYSTEM = """You are AEAOP's diagnostics engine. Given a JSON snapshot of a host
(reachability, ports, services, metrics, recent alerts), produce a strict JSON object
with exactly these fields:
{
  "what":     "<1-2 sentence summary of the problem(s) detected>",
  "why":      "<root cause analysis, technical reason>",
  "impact":   "<business / operational impact if not fixed>",
  "solutions": [
     {"id": "sol_1", "title": "<short>", "risk": "low|medium|high", "auto_executable": true|false, "steps": ["cmd1","cmd2",...]},
     ... up to 4 solutions, lowest-risk first
  ]
}
Return ONLY the JSON — no markdown fences, no prose. If the host looks healthy,
set what/why/impact accordingly and return solutions=[].
"""


async def explain_host(snapshot: dict) -> dict:
    """Ask the LLM for a structured explanation of a host snapshot.
    Always returns valid dict; on parse failure synthesizes from rules."""
    ctx = json.dumps(snapshot, default=str, indent=2)
    result = await chat(
        question="Analyze this host and produce the JSON explanation.",
        system=EXPLAIN_SYSTEM,
        context=ctx,
    )
    raw = result.get("answer", "").strip()

    # Try to extract JSON from the response
    parsed = _extract_json(raw)
    if parsed and isinstance(parsed, dict) and "solutions" in parsed:
        parsed["provider"] = result.get("provider")
        parsed["model"]    = result.get("model")
        return parsed

    # Rule-based fallback if model didn't return JSON
    return _rule_based_explain(snapshot, raw, result.get("provider", "fallback"))


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _rule_based_explain(snap: dict, raw_text: str, provider: str) -> dict:
    """Deterministic structured explanation when the LLM fails to emit JSON."""
    issues, sols = [], []
    cpu  = snap.get("metrics", {}).get("cpu",  0) or 0
    mem  = snap.get("metrics", {}).get("mem",  0) or 0
    disk = snap.get("metrics", {}).get("disk", 0) or 0
    reach = snap.get("reachability", {}).get("ping_ok", True)

    if not reach:
        issues.append("Host is unreachable (ICMP/TCP probes failed)")
        sols.append({"id": "sol_ping", "title": "Verify physical/network path",
                     "risk": "low", "auto_executable": False,
                     "steps": ["Check switch port LED/status", "Verify VLAN & gateway",
                               "Trace cable / SFP", "ping default gateway from neighbor"]})

    if cpu >= 85:
        issues.append(f"CPU at {cpu}% — sustained pressure")
        sols.append({"id": "sol_cpu", "title": "Identify & restart hot process",
                     "risk": "low", "auto_executable": True,
                     "steps": ["top -bn1 | head -20",
                               "ps -eo pid,pcpu,pmem,cmd --sort=-pcpu | head",
                               "systemctl restart <hot-service>",
                               "verify with: uptime && top -bn1 | head -5"]})

    if mem >= 85:
        issues.append(f"Memory at {mem}% — risk of OOM")
        sols.append({"id": "sol_mem", "title": "Free memory / cap consumer",
                     "risk": "low", "auto_executable": True,
                     "steps": ["free -h", "ps -eo pid,pmem,cmd --sort=-pmem | head",
                               "sync && echo 3 > /proc/sys/vm/drop_caches",
                               "restart leaking service"]})

    if disk >= 85:
        issues.append(f"Disk at {disk}% — write failure imminent")
        sols.append({"id": "sol_disk", "title": "Reclaim disk space",
                     "risk": "low", "auto_executable": True,
                     "steps": ["df -h", "du -sh /var/log/* | sort -h | tail",
                               "journalctl --vacuum-time=7d",
                               "find /var/log -name '*.log' -mtime +7 -delete"]})

    open_ports     = snap.get("ports", {}).get("open", [])
    risky_services = [p for p in open_ports if p.get("service", "").lower() in ("telnet", "ftp", "rsh", "snmp v1", "snmp v2c")]
    if risky_services:
        names = ", ".join(p["service"] for p in risky_services)
        issues.append(f"Insecure services exposed: {names}")
        sols.append({"id": "sol_sec", "title": "Disable / harden insecure services",
                     "risk": "medium", "auto_executable": False,
                     "steps": ["systemctl disable telnet ftp rsh",
                               "Switch SNMPv1/v2c → SNMPv3 with authPriv",
                               "Verify firewall rules"]})

    if not issues:
        what   = "Host appears healthy — no critical thresholds breached."
        why    = "Reachability OK, CPU/mem/disk within nominal ranges, no insecure services detected."
        impact = "No operational impact at this time."
    else:
        what   = " · ".join(issues)
        why    = (raw_text[:400] if raw_text else
                  "Threshold-based analysis surfaced the above conditions. Deeper RCA would require historical metrics correlation.")
        impact = "Continued degradation can cause SLA breach, OOM-kills, or security exposure."

    return {
        "what":      what,
        "why":       why,
        "impact":    impact,
        "solutions": sols,
        "provider":  f"{provider} + rule-engine",
        "model":     "rule-based-fallback",
    }
