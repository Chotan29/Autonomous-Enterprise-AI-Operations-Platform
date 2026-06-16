"""Real-time link-up / link-down test via WebSocket.

Plan
-----
1. Open the live WebSocket.
2. Add two NOC devices:
     - reachable: 127.0.0.1   (will probe online)
     - unreachable: 10.255.255.99   (will probe offline)
3. Wait up to 20s for the host monitor (5s interval) to broadcast
   `host_status_change` events for each.
4. Assert we saw BOTH transitions live.
"""
import asyncio
import json
import time
import urllib.request
import urllib.error

import websockets

BASE = "http://localhost:8888"
WS   = "ws://localhost:8888/ws/live"


def http_post(path, body):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        # 409 = already exists — that's fine, monitor is still probing it
        if e.code == 409:
            return 409, {"detail": "already monitored"}
        raise


async def main():
    saw_online  = False
    saw_offline = False
    started     = time.time()

    print(">> connecting WS")
    async with websockets.connect(WS) as ws:
        # Drain initial backlog
        async def drain():
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                pass
        await drain()

        # Pick a fresh TEST-NET-1 IP (RFC 5737 — guaranteed unreachable, no router will route this)
        unreachable_ip = f"192.0.2.{(int(time.time()) % 250) + 5}"
        reachable_ip   = "127.0.0.1"

        print(f">> adding REACHABLE host ({reachable_ip}) ...")
        http_post("/api/v1/noc/devices", {
            "hostname": f"test-loop-{int(time.time())}",
            "ip":       reachable_ip,
            "vendor":   "Cisco", "category": "Router",
            "snmp_community": "public",
        })

        print(f">> adding UNREACHABLE host ({unreachable_ip}) — simulates link-down ...")
        http_post("/api/v1/noc/devices", {
            "hostname": f"test-down-{int(time.time())}",
            "ip":       unreachable_ip,
            "vendor":   "Cisco", "category": "Router",
            "snmp_community": "public",
        })

        print(">> listening for host_status_change events (timeout 25s)\n")
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
            except asyncio.TimeoutError:
                break

            d = json.loads(msg)
            if d.get("type") != "host_status_change":
                continue
            t = time.time() - started
            print(f"  [{t:5.1f}s]  {d['hostname']:32s} {d['ip']:15s}  "
                  f"{d['previous']:>8s}  ->  {d['current']:<8s}  "
                  f"rtt={d.get('rtt_ms')}")

            if d["ip"] == reachable_ip   and d["current"] == "online":  saw_online  = True
            if d["ip"] == unreachable_ip and d["current"] == "offline": saw_offline = True
            if saw_online and saw_offline:
                break

    print()
    print(f"[{'PASS' if saw_online  else 'FAIL'}] saw reachable host go ONLINE  live")
    print(f"[{'PASS' if saw_offline else 'FAIL'}] saw unreachable host go OFFLINE live")
    return 0 if (saw_online and saw_offline) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
