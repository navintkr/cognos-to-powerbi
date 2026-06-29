"use strict";

const form = document.getElementById("migrate-form");
const fileInput = document.getElementById("file");
const aiSelect = document.getElementById("ai");
const analyzeBtn = document.getElementById("analyze-btn");
const migrateBtn = document.getElementById("migrate-btn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");

function setBusy(busy, message) {
  analyzeBtn.disabled = busy;
  migrateBtn.disabled = busy;
  statusEl.textContent = message || "";
}

function requireFile() {
  if (!fileInput.files || fileInput.files.length === 0) {
    setBusy(false, "Select a Cognos report specification first.");
    return null;
  }
  return fileInput.files[0];
}

async function analyze() {
  const file = requireFile();
  if (!file) {
    return;
  }
  summaryEl.hidden = true;
  setBusy(true, "Analyzing report...");
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch("/api/v1/analyze", { method: "POST", body });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    summaryEl.textContent = JSON.stringify(data, null, 2);
    summaryEl.hidden = false;
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
  summaryEl.hidden = true;
  setBusy(true, "Migrating report...");
  const body = new FormData();
  body.append("file", file);
  body.append("ai", aiSelect.value);
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

    const review = response.headers.get("X-Migration-Review-Items") || "0";
    setBusy(false, `Migration complete. Download started. Items to review: ${review}.`);
  } catch (error) {
    setBusy(false, `Error: ${error.message}`);
  }
}

analyzeBtn.addEventListener("click", analyze);
form.addEventListener("submit", migrate);
