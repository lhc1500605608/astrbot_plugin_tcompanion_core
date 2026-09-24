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

function relationshipRow(r) {
  const bond = r.bond ? t("status.relationships.yes", "Yes") : t("status.relationships.no", "No");
  return `<tr>
      <td>${esc(r.user_id)}</td>
      <td>${esc(r.persona_id)}</td>
      <td><span class="stage-badge">${esc(r.stage)}</span></td>
      <td>${Number(r.affinity).toFixed(2)}</td>
      <td>${esc(bond)}</td>
      <td>${formatDateTime(r.updated_at)}</td>
    </tr>`;
}

function relationshipTableHead() {
  return `<thead><tr>
      <th>${esc(t("status.relationships.user", "User"))}</th><th>${esc(t("status.relationships.persona", "Persona"))}</th><th>${esc(t("status.relationships.stage", "Stage"))}</th><th>${esc(t("status.relationships.affinity", "Affinity"))}</th><th>${esc(t("status.relationships.bond", "Bond"))}</th><th>${esc(t("status.relationships.updated", "Updated"))}</th>
    </tr></thead>`;
}

function renderRelationships(data) {
  const el = document.getElementById("relationships-content");
  const items = data.items || [];
  if (items.length === 0) {
    el.innerHTML = `<p class="empty-msg">${esc(t("status.relationships.empty", "No relationships recorded."))}</p>`;
    return;
  }
  const privateRows = [];
  const groupRows = [];
  for (const r of items) {
    if (r.is_group) groupRows.push(r);
    else privateRows.push(r);
  }
  const byPerson = new Map();
  for (const r of privateRows) {
    const key = r.person_key || r.user_id;
    if (!byPerson.has(key)) byPerson.set(key, []);
    byPerson.get(key).push(r);
  }
  let html = "";
  if (byPerson.size > 0) {
    html += `<p class="section-summary">${esc(t("status.relationships.private", "Private"))}</p>`;
    for (const [personKey, rows] of byPerson) {
      const multi = rows.length > 1;
      html += `<div class="rel-group${multi ? " rel-group-suspected" : ""}">`;
      if (multi) {
        html += `<div class="rel-group-head"><span class="person-badge">${esc(personKey)}</span><span class="suspect-tag">${esc(t("status.person.suspected", "May be the same person"))}</span></div>`;
      }
      html += `<table class="rel-table">${relationshipTableHead()}<tbody>`;
      for (const r of rows) html += relationshipRow(r);
      html += `</tbody></table></div>`;
    }
  }
  if (groupRows.length > 0) {
    html += `<p class="section-summary">${esc(t("status.relationships.groups", "Groups"))}</p>`;
    html += `<table class="rel-table">${relationshipTableHead()}<tbody>`;
    for (const r of groupRows) html += relationshipRow(r);
    html += `</tbody></table>`;
  }
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

function activityLabel(level) {
  const key = (level || "").toLowerCase();
  if (key === "high") return t("status.group.activity_high", "High");
  if (key === "medium") return t("status.group.activity_medium", "Medium");
  if (key === "low") return t("status.group.activity_low", "Low");
  return level || "—";
}

function participationLabel(part) {
  if (!part || typeof part !== "object") {
    return t("status.group.part_unknown", "Unknown");
  }
  if (part.allow) return t("status.group.part_ok", "Open");
  const reason = String(part.reason || "");
  if (reason === "cooldown") return t("status.group.part_cooldown", "Cooling down");
  if (reason === "hourly_limit") return t("status.group.part_hourly_limit", "Hourly limit reached");
  if (reason === "group_busy") return t("status.group.part_group_busy", "Group is busy");
  if (reason === "disabled") return t("status.group.part_disabled", "Disabled");
  return t("status.group.part_unknown", "Unknown");
}

function renderGroupState(data) {
  const el = document.getElementById("group-state-content");
  const items = Array.isArray(data.items) ? data.items : [];
  if (items.length === 0) {
    el.innerHTML = `<p class="empty-msg">${esc(t("status.group.empty", "No group chat data yet."))}</p>`;
    return;
  }
  let html = `<p class="section-summary">${esc(tf("status.group.summary", { count: items.length }, "{count} groups"))}</p>`;
  html += '<div class="ls-grid">';
  for (const item of items) {
    const group = (item && typeof item.group === "object" && item.group) || item || {};
    const part = (item && typeof item.participation === "object" && item.participation) || item || {};
    const topic = String(group.topic || "");
    html += `
      <div class="ls-card">
        <div class="persona">${esc(String(item.umo || "—"))}</div>
        <div class="field"><span class="label">${esc(t("status.group.member_count", "Members"))}</span><span class="value">${esc(String(group.member_count ?? "—"))}</span></div>
        <div class="field"><span class="label">${esc(t("status.group.activity", "Activity"))}</span><span class="value">${esc(activityLabel(group.activity_level))}</span></div>
        <div class="field"><span class="label">${esc(t("status.group.participation", "Participation"))}</span><span class="value">${esc(participationLabel(part))}</span></div>
        ${topic ? `<div class="field"><span class="label">${esc(t("status.group.topic", "Topic"))}</span><span class="value">${esc(topic)}</span></div>` : ""}
        <div class="field"><span class="label">${esc(t("status.group.last_activity", "Last active"))}</span><span class="value">${formatDateTime(group.last_activity)}</span></div>
      </div>`;
  }
  html += "</div>";
  el.innerHTML = html;
}

function growthPercent(val) {
  const n = Number(val);
  if (isNaN(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

function renderGrowthState(data) {
  const el = document.getElementById("growth-state-content");
  const items = Array.isArray(data.items) ? data.items : [];
  if (items.length === 0) {
    el.innerHTML = `<p class="empty-msg">${esc(t("status.growth.empty", "No growth data yet."))}</p>`;
    return;
  }
  let html = '<div class="ls-grid">';
  for (const item of items) {
    const growth = (item && typeof item.growth === "object" && item.growth) || item || {};
    const level = growth.level ?? "—";
    const maxLevel = growth.max_level ?? "—";
    const pct = growthPercent(growth.progress);
    const traits = Array.isArray(growth.traits) ? growth.traits.filter(Boolean) : [];
    html += `
      <div class="ls-card">
        <div class="persona">${esc(String(item.persona_id || "—"))}</div>
        <div class="field"><span class="label">${esc(t("status.growth.user", "User"))}</span><span class="value">${esc(String(item.user_id || "—"))}</span></div>
        <div class="field"><span class="label">${esc(t("status.growth.level", "Level"))}</span><span class="value">${esc(String(level))} / ${esc(String(maxLevel))}</span></div>
        <div class="field"><span class="label">${esc(t("status.growth.progress", "Progress"))}</span><span class="value">${pct}%</span></div>
        <div class="energy-bar"><div class="fill" style="width:${pct}%"></div></div>
        ${traits.length ? `<div class="field"><span class="label">${esc(t("status.growth.traits", "Traits"))}</span><span class="value">${esc(traits.join("、"))}</span></div>` : ""}
      </div>`;
  }
  html += "</div>";
  el.innerHTML = html;
}

function unavailableMsg() {
  return `<p class="empty-msg">${esc(t("status.unavailable", "Data is unavailable right now."))}</p>`;
}

function personReasonLabel(reason) {
  if (reason === "canonical_suffix") return t("status.person.reason_canonical", "Same account");
  if (reason === "same_tail") return t("status.person.reason_same_tail", "Same account number");
  return "";
}

function setPersonFeedback(kind, message) {
  const el = document.getElementById("person-keys-feedback");
  if (!el) return;
  if (!kind || !message) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("feedback-ok", "feedback-error");
    return;
  }
  el.hidden = false;
  el.textContent = message;
  el.classList.toggle("feedback-ok", kind === "ok");
  el.classList.toggle("feedback-error", kind === "error");
}

function errMessage(err, fallback) {
  if (!err) return fallback;
  if (typeof err === "string" && err.trim()) return err;
  const msg = err.message || err.reason || err.error;
  if (typeof msg === "string" && msg.trim()) return msg;
  return fallback;
}

function groupPersonKeys(items) {
  const clusters = new Map();
  const lone = [];
  for (const item of items) {
    const suspect = String(item.suspected_person || "");
    if (suspect) {
      if (!clusters.has(suspect)) clusters.set(suspect, []);
      clusters.get(suspect).push(item);
    } else {
      lone.push(item);
    }
  }
  for (const [key, members] of clusters) {
    if (members.length < 2) {
      for (const m of members) lone.push(m);
      clusters.delete(key);
    }
  }
  return { clusters, lone };
}

function personMeta(item) {
  const rows = Number(item.rows ?? 0);
  const last = formatDateTime(item.last_active_at);
  const reason = personReasonLabel(item.suspected_reason);
  return `<div class="person-meta"><span>${esc(t("status.person.rows", "Records"))}: <strong>${isNaN(rows) ? 0 : rows}</strong></span><span>${esc(t("status.person.last_active", "Last active"))}: ${esc(last)}</span>${reason ? `<span class="reason-tag">${esc(reason)}</span>` : ""}</div>`;
}

function renderPersonKeys(data) {
  const el = document.getElementById("person-keys-content");
  const items = Array.isArray(data.items) ? data.items : [];
  if (items.length === 0) {
    el.innerHTML = `<p class="empty-msg">${esc(t("status.person.empty", "No relationship keys yet."))}</p>`;
    return;
  }
  const { clusters, lone } = groupPersonKeys(items);
  let html = "";
  let groupIdx = 0;
  for (const [suspect, members] of clusters) {
    const gid = `pg-${groupIdx++}`;
    const sorted = [...members].sort((a, b) => {
      const ar = Number(a.rows) || 0;
      const br = Number(b.rows) || 0;
      if (ar !== br) return br - ar;
      return String(a.user_id).localeCompare(String(b.user_id));
    });
    html += `<div class="person-cluster" data-cluster="${esc(gid)}">`;
    html += `<div class="rel-group-head"><span class="person-badge">${esc(suspect)}</span><span class="suspect-tag">${esc(t("status.person.suspected", "May be the same person"))}</span></div>`;
    html += `<label class="field-label" for="${gid}-target">${esc(t("status.person.target", "Merge into"))}</label>`;
    html += `<select id="${gid}-target" class="person-select">`;
    for (const m of sorted) {
      const selected = m.user_id === suspect ? " selected" : "";
      html += `<option value="${esc(m.user_id)}"${selected}>${esc(m.user_id)}</option>`;
    }
    html += `</select>`;
    html += `<p class="field-label">${esc(t("status.person.aliases", "Select records to merge"))}</p><ul class="person-keys-list">`;
    for (const m of sorted) {
      html += `<li class="person-key-row">
        <label><input type="checkbox" class="alias-check" value="${esc(m.user_id)}" data-persona="${esc(m.persona_id)}" /> <code>${esc(m.user_id)}</code></label>
        ${personMeta(m)}
      </li>`;
    }
    html += `</ul>`;
    html += `<button type="button" class="btn btn-merge" data-cluster="${esc(gid)}" data-suspect="${esc(suspect)}">${esc(t("status.person.merge", "Merge"))}</button>`;
    html += `</div>`;
  }
  if (lone.length > 0) {
    html += `<p class="section-summary">${esc(t("status.person.title", "People / Merge"))}</p><ul class="person-keys-list person-keys-lone">`;
    for (const m of lone) {
      html += `<li class="person-key-row"><code>${esc(m.user_id)}</code>${personMeta(m)}</li>`;
    }
    html += `</ul>`;
  }
  el.innerHTML = html;
}

async function personMergeHandler(btn) {
  const cluster = btn.closest(".person-cluster");
  if (!cluster) return;
  const select = cluster.querySelector(".person-select");
  const personId = String(select && select.value ? select.value : "").trim();
  const aliases = Array.from(cluster.querySelectorAll(".alias-check:checked"))
    .map((cb) => String(cb.value || "").trim())
    .filter((v) => v && v !== personId);
  const personaIds = Array.from(cluster.querySelectorAll(".alias-check:checked"))
    .map((cb) => String(cb.getAttribute("data-persona") || ""))
    .filter(Boolean);
  if (!personId || aliases.length === 0) {
    setPersonFeedback("error", t("status.person.select_one", "Select at least one record to merge."));
    return;
  }
  const beforeKeys = new Set([personId, ...aliases]);
  const beforeCount = personRowsSum(beforeKeys);
  btn.disabled = true;
  setPersonFeedback(null, null);
  try {
    const result = await bridge.apiPost("person/migrate", { person_id: personId, aliases });
    if (!result || typeof result !== "object" || result.ok === false) {
      throw new Error(errMessage(result, "merge rejected"));
    }
    const personaId = personaIds[0] || "";
    const after = await bridge.apiGet("person/keys");
    const afterItems = (after && after.items) || [];
    const afterCount = afterItems
      .filter((it) => String(it.user_id || "") === personId && (!personaId || String(it.persona_id || "") === personaId))
      .reduce((sum, it) => sum + (Number(it.rows) || 0), 0);
    const merged = result.merged && typeof result.merged === "object" ? result.merged : {};
    const mergedParts = Object.entries(merged)
      .filter(([, n]) => Number(n) > 0)
      .map(([k, n]) => `${k}: ${Number(n)}`);
    const bits = [
      t("status.person.merge_ok", "Merge complete."),
      `${t("status.person.before", "Records before")}: ${beforeCount}`,
      `${t("status.person.after", "Records after")}: ${afterCount}`,
    ];
    if (mergedParts.length) {
      bits.push(`${t("status.person.merged_tables", "Merge details")} — ${mergedParts.join(", ")}`);
    }
    if (result.backup_path) {
      bits.push(`${t("status.person.backup", "Backup file")}: ${result.backup_path}`);
    }
    setPersonFeedback("ok", bits.join(" · "));
    await personReload();
    await loadSection("relationships-content", "relationships", renderRelationships);
  } catch (err) {
    console.error("person/migrate failed:", err);
    setPersonFeedback(
      "error",
      tf("status.person.merge_fail", { message: errMessage(err, "error") }, "Merge failed: {message}")
    );
  } finally {
    btn.disabled = false;
  }
}

let personRowsCache = new Map();

function personRowsSum(keys) {
  let total = 0;
  for (const k of keys) total += Number(personRowsCache.get(k) || 0);
  return total;
}

async function personReload() {
  const el = document.getElementById("person-keys-content");
  if (!el) return;
  try {
    const data = await bridge.apiGet("person/keys");
    if (!data || typeof data !== "object") throw new Error("invalid response");
    if (data.error) throw new Error(String(data.error));
    personRowsCache = new Map(
      (data.items || []).map((it) => [String(it.user_id || ""), Number(it.rows) || 0])
    );
    renderPersonKeys(data);
  } catch (err) {
    console.error("Failed to load person/keys:", err);
    el.innerHTML = unavailableMsg();
  }
}

async function personRollbackHandler() {
  const btn = document.getElementById("person-rollback-btn");
  if (btn) btn.disabled = true;
  setPersonFeedback(null, null);
  try {
    const result = await bridge.apiPost("person/migrate/rollback", {});
    if (!result || typeof result !== "object" || result.ok === false) {
      throw new Error(errMessage(result, "rollback rejected"));
    }
    const bits = [t("status.person.rollback_ok", "Rolled back.")];
    if (result.backup_path) {
      bits.push(`${t("status.person.backup", "Backup file")}: ${result.backup_path}`);
    }
    setPersonFeedback("ok", bits.join(" · "));
    await personReload();
    await loadSection("relationships-content", "relationships", renderRelationships);
  } catch (err) {
    console.error("person/migrate/rollback failed:", err);
    setPersonFeedback(
      "error",
      tf("status.person.rollback_fail", { message: errMessage(err, "error") }, "Rollback failed: {message}")
    );
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadSection(elementId, path, render) {
  const el = document.getElementById(elementId);
  if (!el) return;
  try {
    const data = await bridge.apiGet(path);
    if (!data || typeof data !== "object") {
      throw new Error("invalid response");
    }
    if (data.error) {
      throw new Error(String(data.error));
    }
    render(data);
  } catch (err) {
    console.error(`Failed to load ${path}:`, err);
    el.innerHTML = unavailableMsg();
  }
}

async function loadAll() {
  await Promise.all([
    loadSection("life-state-content", "life-state", renderLifeState),
    loadSection("relationships-content", "relationships", renderRelationships),
    loadSection("motivation-content", "motivation-log", renderMotivationLog),
    loadSection("emotion-content", "emotion-state", renderEmotionState),
    loadSection("group-state-content", "group-state", renderGroupState),
    loadSection("growth-state-content", "growth-state", renderGrowthState),
    personReload(),
  ]);
}

await bridge.ready();
document.title = t("status.title", "Hearthlight Status");
applyI18n(document);
document.getElementById("person-keys-content")?.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".btn-merge");
  if (btn) personMergeHandler(btn);
});
document.getElementById("person-rollback-btn")?.addEventListener("click", personRollbackHandler);
await loadAll();
