const bridge = window.AstrBotPluginPage;

function asDict() {
  try {
    return (bridge && typeof bridge.getI18n === "function" && bridge.getI18n()) || {};
  } catch {
    return {};
  }
}

function resolveLocal(key) {
  const locale = (bridge && typeof bridge.getLocale === "function" && bridge.getLocale()) || "zh-CN";
  const dict = asDict();
  const locales = [locale, "zh-CN", "en-US"].filter(Boolean);
  for (const loc of locales) {
    let obj = dict[loc];
    for (const part of key.split(".")) {
      if (obj && typeof obj === "object" && part in obj) {
        obj = obj[part];
      } else {
        obj = undefined;
        break;
      }
    }
    if (typeof obj === "string") return obj;
  }
  return undefined;
}

function t(key, fallback) {
  try {
    if (bridge && typeof bridge.t === "function") {
      const val = bridge.t(key, fallback);
      if (typeof val === "string" && val !== "") return val;
    }
  } catch {
    /* fall through to local lookup */
  }
  const local = resolveLocal(key);
  return local !== undefined ? local : fallback;
}

function tf(key, params, fallback) {
  let str = t(key, fallback);
  if (params && typeof str === "string") {
    for (const k of Object.keys(params)) {
      str = str.split("{" + k + "}").join(String(params[k]));
    }
  }
  return str;
}

function applyI18n(root) {
  const el = root || document;
  for (const node of el.querySelectorAll("[data-i18n]")) {
    const key = node.getAttribute("data-i18n");
    if (!key) continue;
    const val = t(key, null);
    if (typeof val === "string") node.textContent = val;
  }
  const titles = el.querySelectorAll("[data-i18n-title]");
  for (const node of titles) {
    const key = node.getAttribute("data-i18n-title");
    if (!key) continue;
    const val = t(key, null);
    if (typeof val === "string") node.title = val;
  }
}

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
    el.innerHTML = `<p class="empty-msg">${esc(t("status.life_state.empty", "No life state data for today."))}</p>`;
    return;
  }
  let html = '<div class="ls-grid">';
  for (const item of items) {
    const pct = energyPercent(item.energy);
    html += `
      <div class="ls-card">
        <div class="persona">${esc(item.persona_id)}</div>
        <div class="field"><span class="label">${esc(t("status.life_state.activity", "Activity"))}</span><span class="value">${esc(item.activity || "—")}</span></div>
        <div class="field"><span class="label">${esc(t("status.life_state.scene", "Scene"))}</span><span class="value">${esc(item.scene || "—")}</span></div>
        <div class="field"><span class="label">${esc(t("status.life_state.energy", "Energy"))}</span><span class="value">${pct}%</span></div>
        <div class="energy-bar"><div class="fill" style="width:${pct}%"></div></div>
        ${item.summary ? `<div class="summary">${esc(item.summary)}</div>` : ""}
        <div class="field"><span class="label">${esc(t("status.life_state.as_of", "As of"))}</span><span class="value">${formatDateTime(item.as_of)}</span></div>
      </div>`;
  }
  html += "</div>";
  el.innerHTML = html;
}

function renderRelationships(data) {
  const el = document.getElementById("relationships-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = `<p class="empty-msg">${esc(t("status.relationships.empty", "No relationships recorded."))}</p>`;
    return;
  }
  let html = `<table class="rel-table">
    <thead><tr>
      <th>${esc(t("status.relationships.user", "User"))}</th><th>${esc(t("status.relationships.persona", "Persona"))}</th><th>${esc(t("status.relationships.stage", "Stage"))}</th><th>${esc(t("status.relationships.affinity", "Affinity"))}</th><th>${esc(t("status.relationships.bond", "Bond"))}</th><th>${esc(t("status.relationships.updated", "Updated"))}</th>
    </tr></thead><tbody>`;
  for (const r of items) {
    const bond = r.bond ? t("status.relationships.yes", "Yes") : t("status.relationships.no", "No");
    html += `<tr>
      <td>${esc(r.user_id)}</td>
      <td>${esc(r.persona_id)}</td>
      <td><span class="stage-badge">${esc(r.stage)}</span></td>
      <td>${Number(r.affinity).toFixed(2)}</td>
      <td>${esc(bond)}</td>
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
    el.innerHTML = `<p class="empty-msg">${esc(t("status.motivation.empty", "No motivation log entries."))}</p>`;
    return;
  }
  let html = `<table class="ml-table">
    <thead><tr>
      <th>${esc(t("status.motivation.persona", "Persona"))}</th><th>${esc(t("status.motivation.user", "User"))}</th><th>${esc(t("status.motivation.kind", "Kind"))}</th><th>${esc(t("status.motivation.score", "Score"))}</th>
      <th>${esc(t("status.motivation.reason", "Reason"))}</th><th>${esc(t("status.motivation.decision", "Decision"))}</th><th>${esc(t("status.motivation.created", "Created"))}</th>
    </tr></thead><tbody>`;
  for (const m of items) {
    const adopted = m.adopted ? t("status.motivation.adopted", "Adopted") : "";
    const blocked = m.blocked_reason
      ? tf("status.motivation.blocked", { reason: m.blocked_reason }, "Blocked: {reason}")
      : "";
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
    el.innerHTML = `<p class="empty-msg">${esc(t("status.emotion.empty", "No emotion data recorded."))}</p>`;
    return;
  }
  let html = `<table class="emotion-table">
    <thead><tr>
      <th>${esc(t("status.emotion.user", "User"))}</th><th>${esc(t("status.emotion.persona", "Persona"))}</th><th>${esc(t("status.emotion.state", "Emotion"))}</th><th>${esc(t("status.emotion.valence", "Valence"))}</th>
      <th>${esc(t("status.emotion.mode", "Expression"))}</th><th>${esc(t("status.emotion.last_event", "Last event"))}</th><th>${esc(t("status.emotion.as_of", "As of"))}</th>
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
      `<p class="empty-msg">${esc(tf("status.error", { message: err.message }, "Error loading data: {message}"))}</p>`;
  }
}

await bridge.ready();
document.title = t("status.title", "Hearthlight Status");
applyI18n(document);
await loadAll();
