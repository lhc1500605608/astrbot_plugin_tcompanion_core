const bridge = window.AstrBotPluginPage;

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function energyPercent(val) {
  const n = Number(val);
  if (isNaN(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

function renderLifeState(data) {
  const el = document.getElementById("life-state-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = '<p class="empty-msg">No life state data for today.</p>';
    return;
  }
  let html = '<div class="ls-grid">';
  for (const item of items) {
    const pct = energyPercent(item.energy);
    html += `
      <div class="ls-card">
        <div class="persona">${esc(item.persona_id)}</div>
        <div class="field"><span class="label">Activity</span><span class="value">${esc(item.activity || "—")}</span></div>
        <div class="field"><span class="label">Scene</span><span class="value">${esc(item.scene || "—")}</span></div>
        <div class="field"><span class="label">Energy</span><span class="value">${pct}%</span></div>
        <div class="energy-bar"><div class="fill" style="width:${pct}%"></div></div>
        ${item.summary ? `<div class="summary">${esc(item.summary)}</div>` : ""}
        <div class="field"><span class="label">As of</span><span class="value">${formatDateTime(item.as_of)}</span></div>
      </div>`;
  }
  html += "</div>";
  el.innerHTML = html;
}

function renderRelationships(data) {
  const el = document.getElementById("relationships-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = '<p class="empty-msg">No relationships recorded.</p>';
    return;
  }
  let html = `<table class="rel-table">
    <thead><tr>
      <th>User</th><th>Persona</th><th>Stage</th><th>Affinity</th><th>Bond</th><th>Updated</th>
    </tr></thead><tbody>`;
  for (const r of items) {
    const bond = r.bond ? "Yes" : "No";
    html += `<tr>
      <td>${esc(r.user_id)}</td>
      <td>${esc(r.persona_id)}</td>
      <td><span class="stage-badge">${esc(r.stage)}</span></td>
      <td>${Number(r.affinity).toFixed(2)}</td>
      <td>${bond}</td>
      <td>${formatDateTime(r.updated_at)}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

function kindClass(kind) {
  const k = (kind || "").toLowerCase();
  if (k.includes("adopt")) return "kind-adopted";
  if (k.includes("block")) return "kind-blocked";
  return "kind-candidate";
}

function renderMotivationLog(data) {
  const el = document.getElementById("motivation-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = '<p class="empty-msg">No motivation log entries.</p>';
    return;
  }
  let html = `<table class="ml-table">
    <thead><tr>
      <th>Persona</th><th>User</th><th>Kind</th><th>Score</th>
      <th>Reason</th><th>Decision</th><th>Created</th>
    </tr></thead><tbody>`;
  for (const m of items) {
    const adopted = m.adopted ? "Adopted" : "";
    const blocked = m.blocked_reason ? `Blocked: ${m.blocked_reason}` : "";
    const decision = blocked || adopted || "—";
    html += `<tr>
      <td>${esc(m.persona_id)}</td>
      <td>${esc(m.user_id || "—")}</td>
      <td><span class="kind-badge ${kindClass(m.kind)}">${esc(m.kind)}</span></td>
      <td>${Number(m.value).toFixed(2)}</td>
      <td>${esc(m.selected_reason || m.reason || "—")}</td>
      <td>${esc(decision)}</td>
      <td>${formatDateTime(m.created_at)}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

function renderEmotionState(data) {
  const el = document.getElementById("emotion-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = '<p class="empty-msg">No emotion data recorded.</p>';
    return;
  }
  let html = `<table class="emotion-table">
    <thead><tr>
      <th>User</th><th>Persona</th><th>Emotion</th><th>Valence</th>
      <th>Expression</th><th>Last event</th><th>As of</th>
    </tr></thead><tbody>`;
  for (const e of items) {
    html += `<tr>
      <td>${esc(e.user_id)}</td>
      <td>${esc(e.persona_id)}</td>
      <td><span class="stage-badge">${esc(e.state)}</span></td>
      <td>${Number(e.valence).toFixed(2)}</td>
      <td><span class="kind-badge kind-candidate">${esc(e.mode)}</span></td>
      <td>${esc(e.last_event || "—")}</td>
      <td>${formatDateTime(e.as_of)}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

async function loadAll() {
  try {
    const [lifeState, relationships, motivationLog, emotionState] = await Promise.all([
      bridge.apiGet("life-state"),
      bridge.apiGet("relationships"),
      bridge.apiGet("motivation-log"),
      bridge.apiGet("emotion-state"),
    ]);
    renderLifeState(lifeState);
    renderRelationships(relationships);
    renderMotivationLog(motivationLog);
    renderEmotionState(emotionState);
  } catch (err) {
    console.error("Failed to load status data:", err);
    document.getElementById("life-state-content").innerHTML =
      `<p class="empty-msg">Error loading data: ${esc(err.message)}</p>`;
  }
}

await bridge.ready();
await loadAll();