"use strict";

// Endpoints are relative so the dashboard works whether mounted at "/" or
// behind a prefix like "/api/v1/noc/discovery/".
const API = {
  scan: "api/scan",
  devices: "api/devices",
  history: "api/history",
  stats: "api/stats",
  vendors: "api/vendors",
  deviceHistory: (k) => `api/device/${encodeURIComponent(k)}/history`,
};

const TYPE_ICONS = {
  "Router": "bi-router", "Managed Switch": "bi-diagram-3", "Firewall": "bi-shield-lock",
  "Access Point": "bi-broadcast", "Printer": "bi-printer", "Camera": "bi-camera-video",
  "Server": "bi-server", "PC/Laptop": "bi-pc-display", "Unknown": "bi-question-circle",
};

let allDevices = [];

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-scan").addEventListener("click", runScan);
  document.getElementById("search").addEventListener("input", render);
  document.getElementById("vendor-filter").addEventListener("change", loadDevices);
  document.getElementById("status-filter").addEventListener("change", loadDevices);
  refreshAll();
});

async function refreshAll() {
  await Promise.all([loadStats(), loadVendors(), loadDevices(), loadHistory()]);
}

function fmtTime(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
}

async function getJSON(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (r.status === 401) { window.location = "login"; return null; }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function loadStats() {
  const s = await getJSON(API.stats); if (!s) return;
  document.getElementById("stat-online").textContent = s.online_devices;
  document.getElementById("stat-total").textContent = s.total_devices;
  document.getElementById("stat-offline").textContent = s.offline_devices;
  document.getElementById("stat-lastscan").textContent = s.last_scan ? fmtTime(s.last_scan) : "Never";
}

async function loadVendors() {
  const data = await getJSON(API.vendors); if (!data) return;
  const sel = document.getElementById("vendor-filter");
  const current = sel.value;
  sel.innerHTML = '<option value="">All vendors</option>' +
    data.vendors.map(v => `<option value="${v}">${v}</option>`).join("");
  sel.value = current;
}

async function loadDevices() {
  const status = document.getElementById("status-filter").value;
  const vendor = document.getElementById("vendor-filter").value;
  const params = new URLSearchParams({ status });
  if (vendor) params.set("vendor", vendor);
  const data = await getJSON(`${API.devices}?${params}`); if (!data) return;
  allDevices = data.devices;
  render();
}

function render() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const rows = allDevices.filter(d => !q || [d.ip_address, d.hostname, d.mac_address, d.vendor, d.device_type]
    .some(f => (f || "").toLowerCase().includes(q)));
  const tbody = document.getElementById("device-rows");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="text-center text-secondary py-4">No matching devices.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(d => {
    const online = d.status === "online";
    const icon = TYPE_ICONS[d.device_type] || TYPE_ICONS["Unknown"];
    const ports = (d.open_ports || []).map(p => `<span class="port-chip">${p}</span>`).join("");
    const gw = d.is_gateway ? '<span class="badge text-bg-warning gw-badge ms-1">GW</span>' : "";
    return `<tr>
      <td><span class="status-dot ${online ? "status-online" : "status-offline"}"></span>${online ? "Online" : "Offline"}</td>
      <td class="ip">${d.ip_address}${gw}</td>
      <td class="mac">${d.mac_address || "—"}</td>
      <td>${d.hostname || "—"}</td>
      <td>${d.vendor || "Unknown"}</td>
      <td class="type-badge"><i class="bi ${icon} me-1"></i>${d.device_type || "Unknown"}</td>
      <td>${ports || "—"}</td>
      <td class="small text-secondary">${fmtTime(d.first_seen)}</td>
      <td class="small text-secondary">${fmtTime(d.last_seen)}</td>
      <td><button class="btn btn-sm btn-outline-secondary" onclick="showHistory('${d.device_key}')"><i class="bi bi-clock-history"></i></button></td>
    </tr>`;
  }).join("");
}

async function loadHistory() {
  const data = await getJSON(API.history); if (!data) return;
  const tbody = document.getElementById("history-rows");
  if (!data.scans.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-secondary py-3">No scans yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.scans.map(s => `<tr>
    <td>${s.id}</td><td class="small">${fmtTime(s.started_at)}</td>
    <td class="ip">${s.subnet || "—"}</td><td><span class="badge text-bg-secondary">${s.method || "—"}</span></td>
    <td>${s.hosts_found}</td><td>${s.duration_sec != null ? s.duration_sec + "s" : "—"}</td>
    <td class="small text-secondary">${s.triggered_by || "—"}</td>
  </tr>`).join("");
}

async function showHistory(key) {
  const data = await getJSON(API.deviceHistory(key)); if (!data) return;
  document.getElementById("hist-body").innerHTML = (data.history || []).map(h => `<tr>
    <td class="small">${fmtTime(h.seen_at)}</td><td class="ip">${h.ip_address}</td>
    <td>${h.hostname || "—"}</td><td>${h.device_type || "—"}</td>
    <td class="small">${h.open_ports || "—"}</td></tr>`).join("") ||
    `<tr><td colspan="5" class="text-center text-secondary py-3">No history.</td></tr>`;
  new bootstrap.Modal(document.getElementById("histModal")).show();
}

async function runScan() {
  const btn = document.getElementById("btn-scan");
  const msg = document.getElementById("scan-msg");
  btn.disabled = true;
  btn.querySelector(".scan-idle").classList.add("d-none");
  btn.querySelector(".scan-busy").classList.remove("d-none");
  msg.textContent = "Scanning the local subnet… this can take a moment.";
  try {
    const r = await fetch(API.scan, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    if (r.status === 401) { window.location = "login"; return; }
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Scan failed");
    msg.innerHTML = `<span class="text-success"><i class="bi bi-check-circle me-1"></i>` +
      `Found <strong>${data.hosts_found}</strong> live hosts on ${data.subnet} ` +
      `via ${data.method} in ${data.duration_sec}s.</span>`;
    await refreshAll();
  } catch (e) {
    msg.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-triangle me-1"></i>${e.message}</span>`;
  } finally {
    btn.disabled = false;
    btn.querySelector(".scan-idle").classList.remove("d-none");
    btn.querySelector(".scan-busy").classList.add("d-none");
  }
}
window.showHistory = showHistory;
