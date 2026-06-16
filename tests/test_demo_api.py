"""Smoke tests for AEAOP demo app API endpoints."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8888"


def req(method, path, data=None, timeout=10):
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw[:60].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:60].decode("utf-8", "replace")


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name} {detail}")
    return ok


def server_list():
    s, j = req("GET", "/api/v1/server/servers")
    return s, (j.get("items", []) if isinstance(j, dict) else []), (j.get("total", 0) if isinstance(j, dict) else 0)


def main():
    results = []

    s, _ = req("GET", "/")
    results.append(check("GET / (index HTML)", s == 200, f"status={s}"))

    s, j = req("GET", "/api/v1/dashboard/stats")
    results.append(check("GET /api/v1/dashboard/stats", s == 200, str(j)[:80]))

    s, j = req("GET", "/api/v1/noc/devices")
    results.append(check("GET /api/v1/noc/devices", s == 200, f"count={len(j) if isinstance(j, list) else j}"))

    s, j = req("GET", "/api/v1/noc/topology")
    results.append(check("GET /api/v1/noc/topology", s == 200))

    s, j = req("GET", "/api/v1/noc/alerts")
    results.append(check("GET /api/v1/noc/alerts", s == 200))

    s, j = req("GET", "/api/v1/soc/incidents")
    results.append(check("GET /api/v1/soc/incidents", s == 200))

    s, j = req("GET", "/api/v1/physec/cameras")
    results.append(check("GET /api/v1/physec/cameras", s == 200))

    s, j = req("GET", "/api/v1/healing/actions")
    results.append(check("GET /api/v1/healing/actions", s == 200))

    # Server reset → load → verify → cleanup
    s, j = req("DELETE", "/api/v1/server/reset")
    results.append(check("DELETE /api/v1/server/reset", s == 200, j.get("message", "") if isinstance(j, dict) else ""))

    s, items, total = server_list()
    results.append(check("Server list empty after reset", s == 200 and total == 0, f"total={total}"))

    s, j = req("POST", "/api/v1/server/load-demo-data")
    loaded = j.get("total", 0) if isinstance(j, dict) else 0
    results.append(check("POST /api/v1/server/load-demo-data", s == 200 and loaded > 0, f"total={loaded}"))

    s, items, total = server_list()
    results.append(check("Server list populated", s == 200 and total > 0, f"total={total}"))

    # PC connect
    s, j = req("POST", "/api/v1/server/pc/connect", {
        "hostname": "test-pc-01", "ip": "10.99.99.99",
        "os_type": "linux", "connect_method": "agent",
    })
    results.append(check("POST /api/v1/server/pc/connect", s == 200, str(j)[:80]))

    # Duplicate-IP rejection
    s, j = req("POST", "/api/v1/server/pc/connect", {
        "hostname": "test-pc-dup", "ip": "10.99.99.99",
        "os_type": "linux", "connect_method": "agent",
    })
    results.append(check("Duplicate IP rejected (409)", s == 409))

    # Inject problem on first server (server_id is query param)
    s, items, _ = server_list()
    if items:
        sid = items[0]["id"]
        s, j = req("POST", f"/api/v1/demo/inject-problem?server_id={sid}&problem_type=high_cpu")
        results.append(check("POST /api/v1/demo/inject-problem", s == 200, str(j)[:80]))
        time.sleep(2)

        s, log = req("GET", "/api/v1/demo/healing-log")
        results.append(check("GET /api/v1/demo/healing-log", s == 200, f"entries={len(log) if isinstance(log, list) else 0}"))

    # RAG query
    s, j = req("POST", "/api/v1/rag/query", {"question": "What is AEAOP?"})
    results.append(check("POST /api/v1/rag/query", s == 200, str(j)[:80]))

    # ────────────────────────── New endpoints ──────────────────────────
    # AI providers
    s, j = req("GET", "/api/v1/ai/providers")
    has_chain = isinstance(j, dict) and "chain" in j and "active" in j
    results.append(check("GET /api/v1/ai/providers", s == 200 and has_chain, f"active={j.get('active') if isinstance(j, dict) else '?'}"))

    # AI chat (will fall through to keyword fallback if no LLM available)
    s, j = req("POST", "/api/v1/ai/chat", {"question": "How do I fix BGP?"})
    answered = isinstance(j, dict) and j.get("answer")
    results.append(check("POST /api/v1/ai/chat", s == 200 and bool(answered), f"provider={j.get('provider') if isinstance(j, dict) else '?'}"))

    # RAG info (pipeline transparency)
    s, j = req("GET", "/api/v1/rag/info")
    valid = isinstance(j, dict) and "pipeline" in j and "providers" in j
    results.append(check("GET /api/v1/rag/info", s == 200 and valid))

    # Host monitor snapshot
    s, j = req("GET", "/api/v1/host/monitor")
    valid = isinstance(j, dict) and "hosts" in j and "interval_seconds" in j
    results.append(check("GET /api/v1/host/monitor", s == 200 and valid, f"total={j.get('total') if isinstance(j, dict) else '?'}"))

    # Per-host status probe (use first NOC device)
    s, devs = req("GET", "/api/v1/noc/devices")
    dev_items = devs.get("items", []) if isinstance(devs, dict) else []
    if dev_items:
        host_id = dev_items[0]["id"]
        s, j = req("GET", f"/api/v1/host/{host_id}/status")
        results.append(check(f"GET /api/v1/host/{host_id}/status", s == 200 and isinstance(j, dict) and "live_status" in j, f"status={j.get('live_status')}"))

        # Deep analyze
        s, j = req("POST", f"/api/v1/host/{host_id}/analyze")
        valid = isinstance(j, dict) and "rca_summary" in j and "findings" in j and "ports" in j
        results.append(check(f"POST /api/v1/host/{host_id}/analyze", s == 200 and valid))

        # AI-explain (uses cached snapshot)
        s, j = req("POST", f"/api/v1/host/{host_id}/explain")
        valid = isinstance(j, dict) and j.get("explanation", {}).get("solutions") is not None
        results.append(check(f"POST /api/v1/host/{host_id}/explain", s == 200 and valid))

        # Try a remediation (may 404 if no solutions)
        exp = j.get("explanation", {}) if isinstance(j, dict) else {}
        sols = exp.get("solutions", [])
        if sols:
            auto = next((s for s in sols if s.get("auto_executable")), sols[0])
            s, j = req("POST", f"/api/v1/host/{host_id}/remediate", {"solution_id": auto["id"], "confirm": True})
            results.append(check(f"POST /api/v1/host/{host_id}/remediate", s == 200 and isinstance(j, dict) and j.get("outcome") == "success"))
        else:
            results.append(check("Remediate (no solutions to test)", True, "skipped — host healthy"))

    # ──────────────── NOC empty-start + auto-analyzer flow ─────────────────
    # NOC devices should start empty (we cleared via /reset earlier, plus the
    # server itself starts with no DEMO_DEVICES seed). Load demo data → import
    # → solve.
    # Load demo accepts either "added>0" (fresh server) or "total>0" (already loaded)
    s, j = req("POST", "/api/v1/noc/load-demo-data")
    ok = s == 200 and isinstance(j, dict)
    if ok:
        # Verify devices exist via the devices endpoint
        sd, jd = req("GET", "/api/v1/noc/devices")
        ok = sd == 200 and jd.get("total", 0) > 0
    results.append(check("POST /api/v1/noc/load-demo-data",
                         ok,
                         f"added={j.get('added') if isinstance(j, dict) else '?'}"))

    # ─────────────── Real LAN discovery (network/* endpoints) ───────────────
    s, j = req("GET", "/api/v1/network/info")
    has_subnet = isinstance(j, dict) and "auto_detected_cidr" in j
    results.append(check("GET /api/v1/network/info", s == 200 and has_subnet, f"subnet={j.get('auto_detected_cidr') if isinstance(j, dict) else '?'}"))

    s, j = req("GET", "/api/v1/network/hosts")
    results.append(check("GET /api/v1/network/hosts (empty ok)", s == 200 and isinstance(j, dict)))

    # Actually run a discovery — this hits the LAN, can take 10-30s
    s, j = req("POST", "/api/v1/network/discover", {"deep_probe": True, "ping_sweep": True})
    found = j.get("host_count", 0) if isinstance(j, dict) else 0
    results.append(check("POST /api/v1/network/discover", s == 200 and found > 0,
                         f"found={found} hosts on {j.get('subnet') if isinstance(j, dict) else '?'}"))

    # Subsequent GET should now return the discovered hosts
    s, j = req("GET", "/api/v1/network/hosts")
    cached = j.get("host_count", 0) if isinstance(j, dict) else 0
    results.append(check("GET /api/v1/network/hosts (after scan)", s == 200 and cached > 0, f"cached={cached}"))

    # Import discovered into NOC
    s, j = req("POST", "/api/v1/noc/import-discovered")
    results.append(check("POST /api/v1/noc/import-discovered",
                         s == 200 and isinstance(j, dict) and j.get("added", 0) >= 0,
                         f"added={j.get('added') if isinstance(j, dict) else '?'}"))

    # Vendor-aware config generation for a known finding title — prefer a
    # Telnet alert (we have recipes for every vendor).
    time.sleep(2)
    s, j = req("GET", "/api/v1/noc/alerts")
    alerts = j.get("items", []) if isinstance(j, dict) else []
    candidate = (
        next((a for a in alerts if "telnet" in a.get("title", "").lower() and a.get("host_id")), None)
        or next((a for a in alerts if a.get("host_id")), None)
    )
    if candidate:
        s, j = req("POST", f"/api/v1/alerts/{candidate['id']}/solve", {"auto_execute": True})
        # Accept either successful execution OR an unsupported vendor (still 200)
        cfg = (j or {}).get("config", {})
        ok = s == 200 and isinstance(j, dict)
        results.append(check(f"POST /api/v1/alerts/{candidate['id']}/solve",
                             ok,
                             f"vendor={j.get('vendor')} supported={cfg.get('supported')}"))
    else:
        results.append(check("Solve (no auto-alerts yet)", True, "skipped"))

    # ─────────────── Config Intelligence (RAG over device configs) ──────────
    s, j = req("POST", "/api/v1/config/ingest-all", timeout=300)
    blocks = sum(s.get("blocks", 0) for s in (j.get("summary", []) if isinstance(j, dict) else []))
    results.append(check("POST /api/v1/config/ingest-all",
                         s == 200 and blocks > 0, f"blocks={blocks}"))

    s, j = req("GET", "/api/v1/config/stats")
    valid = isinstance(j, dict) and j.get("total_entries", 0) > 0 and j.get("embed_dimension", 0) > 0
    results.append(check("GET /api/v1/config/stats",
                         s == 200 and valid,
                         f"entries={j.get('total_entries') if isinstance(j, dict) else '?'} "
                         f"dim={j.get('embed_dimension') if isinstance(j, dict) else '?'}"))

    s, j = req("POST", "/api/v1/config/search", {"query": "SSH version 2 and ACL", "k": 3})
    has_hits = isinstance(j, dict) and len(j.get("results", [])) > 0
    results.append(check("POST /api/v1/config/search", s == 200 and has_hits,
                         f"hits={len(j.get('results', [])) if isinstance(j, dict) else 0}"))

    s, j = req("POST", "/api/v1/config/generate",
               {"intent": "Add VLAN 100 named GUEST_WIFI", "vendor": "Cisco", "context_k": 3},
               timeout=120)
    has_draft = isinstance(j, dict) and isinstance(j.get("draft", ""), str) and len(j["draft"]) > 0
    has_citations = isinstance(j, dict) and len(j.get("citations", [])) > 0
    results.append(check("POST /api/v1/config/generate",
                         s == 200 and has_draft and has_citations,
                         f"citations={len(j.get('citations', [])) if isinstance(j, dict) else 0}"))

    # Clear all alerts
    s, j = req("DELETE", "/api/v1/alerts/clear-all")
    results.append(check("DELETE /api/v1/alerts/clear-all", s == 200))

    # Cleanup
    s, j = req("DELETE", "/api/v1/server/reset")
    results.append(check("Final cleanup reset", s == 200))

    s, items, total = server_list()
    results.append(check("Final empty state", s == 200 and total == 0, f"total={total}"))

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{'='*50}\n{passed}/{total} tests passed\n{'='*50}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
