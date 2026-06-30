"use strict";

const form = document.getElementById("migrate-form");
const fileInput = document.getElementById("file");
const aiSelect = document.getElementById("ai");
const kindSelect = document.getElementById("kind");
const analyzeBtn = document.getElementById("analyze-btn");
const migrateBtn = document.getElementById("migrate-btn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const flagsEl = document.getElementById("flags");

function setBusy(busy, message) {
  analyzeBtn.disabled = busy;
  migrateBtn.disabled = busy;
  statusEl.textContent = message || "";
}

function requireFile() {
  if (!fileInput.files || fileInput.files.length === 0) {
    setBusy(false, "Select a Cognos source file first.");
    return null;
  }
  return fileInput.files[0];
}

function clearOutputs() {
  summaryEl.hidden = true;
  summaryEl.textContent = "";
  flagsEl.hidden = true;
  flagsEl.replaceChildren();
}

function renderSummary(data) {
  const facts = [
    ["Project", data.project_name],
    ["Detected kind", data.detected_kind || data.source_kind],
    ["Tables", data.table_count],
    ["Measures", data.measure_count],
    ["Pages", data.page_count],
    ["Relationships", data.relationship_count],
    ["Items to review", data.review_flag_count],
  ];
  const lines = facts
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([label, value]) => `${label}: ${value}`);
  summaryEl.textContent = lines.join("\n");
  summaryEl.hidden = false;
}

function renderFlags(flags) {
  flagsEl.replaceChildren();
  if (!Array.isArray(flags) || flags.length === 0) {
    flagsEl.hidden = true;
    return;
  }
  const heading = document.createElement("h3");
  heading.textContent = `Review items (${flags.length})`;
  flagsEl.appendChild(heading);

  const table = document.createElement("table");
  table.className = "flag-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Severity", "Code", "Message", "Location"]) {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const flag of flags) {
    const row = document.createElement("tr");
    const severity = (flag.severity || "info").toLowerCase();
    row.className = `severity-${severity}`;
    const cells = [flag.severity, flag.code, flag.message, flag.location];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value == null ? "" : String(value);
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  flagsEl.appendChild(table);
  flagsEl.hidden = false;
}

async function analyze() {
  const file = requireFile();
  if (!file) {
    return;
  }
  clearOutputs();
  setBusy(true, "Analyzing source...");
  const body = new FormData();
  body.append("file", file);
  body.append("kind", kindSelect.value);
  try {
    const response = await fetch("/api/v1/analyze", { method: "POST", body });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    renderSummary(data);
    renderFlags(data.review_flags);
    setBusy(false, "Analysis complete.");
  } catch (error) {
    setBusy(false, `Error: ${error.message}`);
  }
}

async function migrate(event) {
  event.preventDefault();
  const file = requireFile();
  if (!file) {
    return;
  }
  clearOutputs();
  setBusy(true, "Migrating source...");
  const body = new FormData();
  body.append("file", file);
  body.append("ai", aiSelect.value);
  body.append("kind", kindSelect.value);
  try {
    const response = await fetch("/api/v1/migrate", { method: "POST", body });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed (${response.status})`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "migration.pbip.zip";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);

    const kind = response.headers.get("X-Migration-Kind") || "source";
    const review = response.headers.get("X-Migration-Review-Items") || "0";
    setBusy(
      false,
      `Migration complete (${kind}). Download started. Items to review: ${review}.`,
    );
  } catch (error) {
    setBusy(false, `Error: ${error.message}`);
  }
}

analyzeBtn.addEventListener("click", analyze);
form.addEventListener("submit", migrate);
