const STORAGE = {
  token: "agentotel_token",
  projectId: "current_project_id",
  apiKeyPlaintext: "agentotel_api_key_plaintext_once",
  agentKeyPrefix: "agentotel_agent_key_plaintext_"
};
const DEFAULT_OTLP_ENDPOINT = `${window.location.protocol}//${window.location.hostname || "localhost"}:4318/v1/traces`;

function authToken() { return localStorage.getItem(STORAGE.token) || ""; }
function currentProjectId() { return localStorage.getItem(STORAGE.projectId) || state.currentProjectId || ""; }
function projectPath(path) {
  const projectId = encodeURIComponent(currentProjectId());
  return projectId ? `/api/projects/${projectId}${path}` : `/api${path}`;
}
function withTime(url) {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${timeRangeQuery()}`;
}

const API = {
  phoneCode: () => "/api/auth/phone/code",
  phoneLogin: () => "/api/auth/phone/login",
  me: () => "/api/me",
  projects: () => "/api/projects",
  apiKeys: () => projectPath("/api-keys"),
  apiKey: (id) => `${projectPath("/api-keys")}/${encodeURIComponent(id)}`,
  agents: () => projectPath("/agents"),
  agent: (id) => `${projectPath("/agents")}/${encodeURIComponent(id)}`,
  agentApiKey: (id) => `${projectPath("/agents")}/${encodeURIComponent(id)}/api-key`,
  sessions: () => {
    const params = new URLSearchParams({ limit: "100" });
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    return withTime(`${projectPath("/sessions")}?${params.toString()}`);
  },
  sessionCard: () => {
    const params = new URLSearchParams();
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withTime(`${projectPath("/overview/session-card")}${suffix}`);
  },
  traceCard: () => {
    const params = new URLSearchParams();
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withTime(`${projectPath("/overview/trace-card")}${suffix}`);
  },
  tokenCard: () => {
    const params = new URLSearchParams();
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withTime(`${projectPath("/overview/token-card")}${suffix}`);
  },
  topSessions: (sort = state.topSessionsSort) => {
    const params = new URLSearchParams({ sort, limit: "5" });
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    return withTime(`${projectPath("/overview/top-sessions")}?${params.toString()}`);
  },
  sessionPageSessions: () => {
    const params = new URLSearchParams({ sort: state.sessionPageSort, limit: String(state.sessionPageSize), offset: String((state.sessionPagePage - 1) * state.sessionPageSize) });
    if (state.sessionPageQuery.trim()) params.set("q", state.sessionPageQuery.trim());
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    if (state.sessionPageStatusFilter === "errors") params.set("sort", "errors");
    return withTime(`${projectPath("/sessions")}?${params.toString()}`);
  },
  topTraces: (sort = state.topTracesSort) => {
    const params = new URLSearchParams({ sort, limit: "5" });
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    return withTime(`${projectPath("/traces")}?${params.toString()}`);
  },
  tracePageTraces: () => {
    const params = new URLSearchParams({ sort: state.tracePageSort, limit: String(state.tracePageSize), offset: String((state.tracePagePage - 1) * state.tracePageSize) });
    const query = state.tracePageQuery.trim();
    if (query) params.set("q", query);
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    if (state.tracePageStatusFilter === "errors") params.set("sort", "errors");
    return withTime(`${projectPath("/traces")}?${params.toString()}`);
  },
  search: (sessionId) => {
    const params = new URLSearchParams({ session_id: sessionId });
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    return withTime(`${projectPath("/search")}?${params.toString()}`);
  },
  trace: (traceId) => {
    const params = new URLSearchParams();
    const agent = selectedAgent();
    if (agent?.name) params.set("agent_name", agent.name);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withTime(`${projectPath(`/traces/${encodeURIComponent(traceId)}`)}${suffix}`);
  }
};

const TIME_PRESETS = {
  "1h": { label: "最近 1 小时", ms: 60 * 60 * 1000 },
  "3h": { label: "最近 3 小时", ms: 3 * 60 * 60 * 1000 },
  "6h": { label: "最近 6 小时", ms: 6 * 60 * 60 * 1000 },
  "12h": { label: "最近 12 小时", ms: 12 * 60 * 60 * 1000 },
  "24h": { label: "最近 24 小时", ms: 24 * 60 * 60 * 1000 },
  "3d": { label: "最近 3 天", ms: 3 * 24 * 60 * 60 * 1000 },
  "7d": { label: "最近 7 天", ms: 7 * 24 * 60 * 60 * 1000 }
};

const fallbackData = window.AGENT_OBSERVABILITY_MOCK || window.MISSION_CONTROL_DATA || {
  sessions: [], tracesBySession: {}, traceDetails: {}
};

const state = {
  sessions: [],
  sessionCard: null,
  sessionCardError: null,
  traceCard: null,
  traceCardError: null,
  tokenCard: null,
  tokenCardError: null,
  topSessions: [],
  topSessionsSort: "latest",
  topSessionsError: null,
  topTraces: [],
  topTracesSort: "latest",
  topTracesError: null,
  sessionPageSessions: [],
  sessionPageSort: "latest",
  sessionPagePage: 1,
  sessionPageSize: 20,
  sessionPageHasMore: false,
  sessionPageQuery: "",
  sessionPageStatusFilter: "all",
  sessionPageError: null,
  loadingSessionPage: false,
  tracePageTraces: [],
  tracePageSort: "latest",
  tracePagePage: 1,
  tracePageSize: 20,
  tracePageHasMore: false,
  tracePageQuery: "",
  tracePageStatusFilter: "all",
  tracePageError: null,
  loadingTracePage: false,
  traces: [],
  selectedSessionId: null,
  selectedTraceId: null,
  selectedTraceDetail: null,
  selectedTraceSpanId: null,
  query: "",
  statusFilter: "all",
  isFallback: false,
  apiError: null,
  lastRefreshed: null,
  loadingSessions: false,
  loadingTraces: false,
  loadingTraceDetail: false,
  bootstrapped: false,
  authReady: false,
  user: null,
  projects: [],
  currentProjectId: localStorage.getItem(STORAGE.projectId) || "",
  apiKeys: [],
  apiKeysError: null,
  agents: [],
  agentsError: null,
  creatingAgent: false,
  agentMenuOpen: false,
  selectedAgentId: localStorage.getItem("agentotel_selected_agent_id") || "",
  agentKeyPlaintexts: {},
  apiKeyPlaintext: sessionStorage.getItem(STORAGE.apiKeyPlaintext) || "",
  otlpEndpoint: DEFAULT_OTLP_ENDPOINT,
  timeRange: {
    preset: "24h",
    customFrom: null,
    customTo: null,
    picking: "from",
    menuOpen: false,
    calendarMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1)
  }
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
function pick(...values) { return values.find((value) => value !== undefined && value !== null && value !== "") ?? ""; }
function asNumber(value) { const n = Number(value || 0); return Number.isFinite(n) ? n : 0; }
function formatNumber(value) { return new Intl.NumberFormat().format(asNumber(value)); }
function formatCompactNumber(value) {
  const n = asNumber(value);
  if (n <= 0) return "--";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, "")}k`;
  return formatNumber(Math.round(n));
}
function formatPercent(value) { return `${Math.round(value * 10) / 10}%`; }
function formatRatio(value) { return `${Math.round(asNumber(value) * 1000) / 10}%`; }
function formatCurrencyCny(value) {
  const n = asNumber(value);
  if (n <= 0) return "¥0.00";
  return `¥${Math.max(n, 0.01).toFixed(2)}`;
}
function formatDuration(value) {
  const ms = asNumber(value);
  if (ms <= 0) return "--";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}
function parseDate(value) {
  if (!value) return null;
  const text = String(value);
  const normalized = text.includes("T") ? text : `${text.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}
function formatDateTime(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return "--";
  return new Intl.DateTimeFormat(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}
function toDatetimeLocal(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function fromDatetimeLocal(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
function syncCustomDatesFromInputs() {
  state.timeRange.preset = "custom";
  const from = fromDatetimeLocal($("custom-from")?.value);
  const to = fromDatetimeLocal($("custom-to")?.value);
  if (from) state.timeRange.customFrom = from;
  if (to) state.timeRange.customTo = to;
  if (from) state.timeRange.calendarMonth = new Date(from.getFullYear(), from.getMonth(), 1);
  syncTimeRangeControls();
}
function currentTimeRange() {
  if (state.timeRange.preset === "custom") {
    const fallbackTo = new Date();
    const fallbackFrom = new Date(fallbackTo.getTime() - TIME_PRESETS["24h"].ms);
    return {
      from: state.timeRange.customFrom || fallbackFrom,
      to: state.timeRange.customTo || fallbackTo,
      label: "自定义"
    };
  }
  const preset = TIME_PRESETS[state.timeRange.preset] || TIME_PRESETS["24h"];
  const to = new Date();
  const from = new Date(to.getTime() - preset.ms);
  return { from, to, label: preset.label };
}
function timeRangeQuery() {
  const range = currentTimeRange();
  return new URLSearchParams({ from: range.from.toISOString(), to: range.to.toISOString() }).toString();
}
function timeRangeSummary() {
  const range = currentTimeRange();
  return `${range.label}: ${formatDateTime(range.from)} → ${formatDateTime(range.to)}`;
}
function toDateKey(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
function sameDay(a, b) { return toDateKey(a) && toDateKey(a) === toDateKey(b); }
function monthLabel(date) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long" }).format(date);
}
function setDatePart(original, date, endOfDay = false) {
  const base = original instanceof Date && !Number.isNaN(original.getTime()) ? new Date(original) : new Date();
  base.setFullYear(date.getFullYear(), date.getMonth(), date.getDate());
  if (endOfDay && !(original instanceof Date)) base.setHours(23, 59, 0, 0);
  if (!endOfDay && !(original instanceof Date)) base.setHours(0, 0, 0, 0);
  return base;
}
function renderCalendarGrid() {
  const grid = $("calendar-grid");
  const title = $("calendar-title");
  if (!grid || !title) return;
  const month = state.timeRange.calendarMonth instanceof Date ? state.timeRange.calendarMonth : new Date();
  const monthStart = new Date(month.getFullYear(), month.getMonth(), 1);
  title.textContent = monthLabel(monthStart);
  const firstWeekday = (monthStart.getDay() + 6) % 7;
  const start = new Date(monthStart);
  start.setDate(monthStart.getDate() - firstWeekday);
  const range = currentTimeRange();
  const today = new Date();
  const cells = [];
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const inMonth = day.getMonth() === monthStart.getMonth();
    const inRange = range.from && range.to && day >= new Date(range.from.getFullYear(), range.from.getMonth(), range.from.getDate()) && day <= new Date(range.to.getFullYear(), range.to.getMonth(), range.to.getDate());
    const edge = sameDay(day, range.from) || sameDay(day, range.to);
    const classes = ["calendar-day", inMonth ? "" : "muted", inRange ? "in-range" : "", edge ? "edge" : "", sameDay(day, today) ? "today" : ""].filter(Boolean).join(" ");
    cells.push(`<button type="button" class="${classes}" data-calendar-date="${toDateKey(day)}">${day.getDate()}</button>`);
  }
  grid.innerHTML = cells.join("");
}
function syncTimeRangeControls() {
  const trigger = $("time-range-trigger");
  const current = $("time-range-current");
  const menu = $("time-range-menu");
  const custom = $("custom-time-range");
  const fromInput = $("custom-from");
  const toInput = $("custom-to");
  if (current) current.textContent = currentTimeRange().label;
  if (trigger) trigger.setAttribute("aria-expanded", state.timeRange.menuOpen ? "true" : "false");
  if (menu) menu.hidden = !state.timeRange.menuOpen;
  document.querySelectorAll("[data-time-preset]").forEach((button) => {
    button.classList.toggle("active", button.dataset.timePreset === state.timeRange.preset);
  });
  if (custom) custom.hidden = false;
  const range = currentTimeRange();
  if (fromInput && document.activeElement !== fromInput) fromInput.value = toDatetimeLocal(range.from);
  if (toInput && document.activeElement !== toInput) toInput.value = toDatetimeLocal(range.to);
  if (state.timeRange.preset !== "custom") {
    state.timeRange.calendarMonth = new Date(range.from.getFullYear(), range.from.getMonth(), 1);
  }
  renderCalendarGrid();
}
function statusClass(status) {
  const raw = String(status || "").toUpperCase();
  if (raw === "ERROR" || raw === "STATUS_CODE_ERROR") return "error";
  if (raw === "OK" || raw === "STATUS_CODE_OK") return "ok";
  return "unset";
}
function statusLabel(status) {
  const raw = String(status || "UNSET").toUpperCase().replace("STATUS_CODE_", "");
  return raw || "UNSET";
}
function typeClass(type) {
  const raw = String(type || "span").toLowerCase();
  if (raw.includes("llm")) return "llm";
  if (raw.includes("tool")) return "tool";
  if (raw.includes("event")) return "event";
  return "span";
}
function isErrored(item) { return asNumber(item.error_count) > 0 || statusClass(item.status_code) === "error"; }
function jsonString(value) {
  if (!value || (typeof value === "object" && !Object.keys(value).length)) return "";
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
}

function debounce(fn, delay = 250) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function fetchJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const token = authToken();
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { cache: "no-store", ...options, headers });
  if (!response.ok) {
    let detail = "";
    try { const payload = await response.json(); detail = payload.detail || payload.error || ""; }
    catch (_) { detail = await response.text().catch(() => ""); }
    throw new Error(`HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
  }
  return response.json();
}

function jsonPost(body) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
}
function normalizeProject(project) {
  return {
    id: String(pick(project.id, project.project_id, project.uuid, "")),
    name: String(pick(project.name, project.project_name, project.title, "默认项目")),
    otlpEndpoint: String(pick(project.otlp_endpoint, project.endpoint, project.traces_endpoint, DEFAULT_OTLP_ENDPOINT))
  };
}
function currentProject() {
  const id = currentProjectId();
  return state.projects.find((project) => project.id === id) || state.projects[0] || null;
}
function maskApiKey(key) {
  const raw = String(key || "");
  if (!raw) return "";
  if (raw.includes("•")) return raw;
  const prefix = raw.slice(0, Math.min(raw.length, 11));
  return `${prefix}••••`;
}
function normalizeApiKey(key) {
  const prefix = pick(key.key_prefix, key.prefix, key.name, "ak_live_xxx");
  const masked = pick(key.masked_key, key.masked, key.display, "");
  return {
    id: String(pick(key.id, key.api_key_id, key.key_id, prefix)),
    prefix: String(prefix),
    masked: String(masked || `${prefix}••••`),
    plaintext: String(pick(key.key, key.api_key, key.token, key.secret, "")),
    createdAt: pick(key.created_at, key.createdAt, "")
  };
}
function maskPhone(value) {
  const raw = String(value || "").trim();
  if (!raw) return "--";
  const digits = raw.replace(/\D/g, "");
  if (digits.length >= 11) {
    const local = digits.slice(-11);
    return `${local.slice(0, 3)}****${local.slice(-4)}`;
  }
  return raw;
}
function normalizeUser(user) {
  const phone = pick(user.phone, user.phone_normalized, user.phone_number, user.mobile, "");
  return {
    id: String(pick(user.user_id, user.id, "")),
    displayName: String(pick(user.display_name, user.name, "")),
    phone: String(phone)
  };
}
function renderSidebarUser() {
  const user = state.user || {};
  const phone = maskPhone(user.phone);
  const name = user.displayName || (phone !== "--" ? `用户 ${phone.slice(-4)}` : "当前用户");
  const nameEl = $("sidebar-user-name");
  const phoneEl = $("sidebar-user-phone");
  const avatar = document.querySelector(".user-avatar");
  if (nameEl) nameEl.textContent = name;
  if (phoneEl) phoneEl.textContent = phone;
  if (avatar) avatar.textContent = phone !== "--" ? phone.slice(-2) : "U";
}
function clearAuthState() {
  localStorage.removeItem(STORAGE.token);
  localStorage.removeItem(STORAGE.projectId);
  state.user = null;
  state.projects = [];
  state.currentProjectId = "";
  state.apiKeys = [];
  state.agents = [];
  state.agentsError = null;
  state.selectedAgentId = "";
  state.agentKeyPlaintexts = {};
  localStorage.removeItem("agentotel_selected_agent_id");
  state.apiKeyPlaintext = "";
  state.agents = [];
  state.selectedAgentId = "";
  state.agentKeyPlaintexts = {};
  localStorage.removeItem("agentotel_selected_agent_id");
  sessionStorage.removeItem(STORAGE.apiKeyPlaintext);
  state.sessions = [];
  state.traces = [];
  state.topSessions = [];
  state.topTraces = [];
  state.sessionPageSessions = [];
  state.tracePageTraces = [];
  state.selectedSessionId = null;
  state.selectedTraceId = null;
  state.selectedTraceDetail = null;
  state.selectedTraceSpanId = null;
}
function logout() {
  clearAuthState();
  setAuthenticatedShell(false);
  authMessage("已登出", "ok");
  window.history.replaceState(null, "", `${window.location.pathname}`);
}
async function loadCurrentUser() {
  const payload = await fetchJson(API.me());
  state.user = normalizeUser(payload.user || payload.data?.user || payload.data || payload);
  renderSidebarUser();
}
function activeApiKeyValue({ forCopy = false } = {}) {
  const plaintext = state.apiKeyPlaintext || sessionStorage.getItem(STORAGE.apiKeyPlaintext) || "";
  if (plaintext) return plaintext;
  const key = state.apiKeys[0];
  if (!key) return forCopy ? "请先在设置重新生成 API Key" : "未生成";
  return forCopy ? "<请先在设置重新生成 API Key，刷新后 masked Key 无法用于接入>" : key.masked;
}
function agentPlaintextStorageKey(agentId) { return `${STORAGE.agentKeyPrefix}${currentProjectId()}_${agentId}`; }
function selectedAgent() {
  return state.agents.find((agent) => agent.id === state.selectedAgentId) || state.agents[0] || null;
}
function selectedAgentName() {
  return selectedAgent()?.name || "未选择 Agent";
}
function agentApiKeyValue(agent, { forCopy = false } = {}) {
  if (!agent) return forCopy ? "请先在设置创建 Agent" : "未创建";
  const plaintext = state.agentKeyPlaintexts[agent.id] || agent.apiKey?.plaintext || sessionStorage.getItem(agentPlaintextStorageKey(agent.id)) || "";
  if (plaintext) return plaintext;
  const masked = agent.apiKey?.masked || agent.apiKey?.key_prefix || "";
  return forCopy ? "<请先在设置生成当前 Agent API Key>" : (masked || "未生成");
}
function normalizeAgent(agent) {
  const rawKey = agent.api_key || agent.key || agent.apiKey || {};
  const apiKey = rawKey && Object.keys(rawKey).length ? normalizeApiKey(rawKey) : null;
  return {
    id: String(pick(agent.agent_id, agent.id, "")),
    name: String(pick(agent.name, agent.agent_name, "未命名 Agent")),
    slug: String(pick(agent.slug, "")),
    kind: String(pick(agent.kind, "custom")),
    status: String(pick(agent.status, "active")),
    createdAt: pick(agent.created_at, agent.createdAt, ""),
    apiKey
  };
}
async function loadAgents() {
  if (!currentProjectId()) return;
  try {
    const payload = await fetchJson(API.agents());
    const rows = Array.isArray(payload) ? payload : (payload.agents || payload.data || []);
    state.agents = rows.map(normalizeAgent).filter((agent) => agent.id);
    state.agentsError = null;
    if (!state.selectedAgentId || !state.agents.some((agent) => agent.id === state.selectedAgentId)) {
      state.selectedAgentId = state.agents[0]?.id || "";
      if (state.selectedAgentId) localStorage.setItem("agentotel_selected_agent_id", state.selectedAgentId);
    }
  } catch (error) {
    state.agents = [];
    state.agentsError = error instanceof Error ? error.message : String(error);
  }
  renderAgents();
  renderIntegrationPanel();
}
async function createAgent() {
  const input = $("agent-name-input");
  const name = input?.value?.trim();
  if (!name) { state.agentsError = "请输入 Agent 名称"; renderAgents(); input?.focus(); return; }
  state.creatingAgent = true;
  renderAgents();
  try {
    const payload = await fetchJson(API.agents(), jsonPost({ name }));
    const agent = normalizeAgent(payload.agent || payload.data || payload);
    if (agent.apiKey?.plaintext) {
      state.agentKeyPlaintexts[agent.id] = agent.apiKey.plaintext;
      sessionStorage.setItem(agentPlaintextStorageKey(agent.id), agent.apiKey.plaintext);
    }
    state.selectedAgentId = agent.id;
    localStorage.setItem("agentotel_selected_agent_id", agent.id);
    if (input) input.value = "";
    await loadAgents();
    if (state.agentKeyPlaintexts[agent.id] && !state.agents.some((item) => item.id === agent.id)) state.agents = [agent, ...state.agents];
    state.agentsError = null;
  } finally {
    state.creatingAgent = false;
    renderAgents();
    renderIntegrationPanel();
  }
}
async function renameAgent(agentId, name) {
  const clean = String(name || "").trim();
  if (!agentId || !clean) return;
  await fetchJson(API.agent(agentId), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: clean }) });
  await loadAgents();
  await refreshForCurrentAgent();
}
async function deleteAgent(agentId) {
  if (!agentId) return;
  await fetchJson(API.agent(agentId), { method: "DELETE" });
  if (state.selectedAgentId === agentId) {
    state.selectedAgentId = "";
    localStorage.removeItem("agentotel_selected_agent_id");
  }
  delete state.agentKeyPlaintexts[agentId];
  sessionStorage.removeItem(agentPlaintextStorageKey(agentId));
  await loadAgents();
  await refreshForCurrentAgent();
}
async function refreshForCurrentAgent() {
  state.selectedSessionId = null;
  state.selectedTraceId = null;
  state.selectedTraceDetail = null;
  state.sessionPagePage = 1;
  state.tracePagePage = 1;
  state.sessionPageSessions = [];
  state.tracePageTraces = [];
  renderAgentSelector();
  renderIntegrationPanel();
  await loadSessions({ silent: false });
  if (parseRoute(window.location.hash).page === "sessions") loadSessionPage();
  if (parseRoute(window.location.hash).page === "traces") loadTracePage();
}
function renderAgents() {
  const list = $("agent-list");
  if (!list) return;
  const rows = state.agents.map((agent) => {
    const selected = agent.id === state.selectedAgentId;
    const keyText = agentApiKeyValue(agent);
    const cannotDelete = state.agents.length <= 1;
    return `<div class="agent-row ${selected ? "active" : ""}" data-agent-id="${escapeHtml(agent.id)}">
      <div class="agent-row-main">
        <input class="agent-name-edit" value="${escapeHtml(agent.name)}" aria-label="Agent 名称" data-agent-name-input="${escapeHtml(agent.id)}" />
        <span>${selected ? "当前选中" : "可切换"} · ${escapeHtml(agent.kind)}</span>
      </div>
      <div class="agent-row-actions">
        <button class="button subtle" type="button" data-agent-select="${escapeHtml(agent.id)}">${selected ? "已选择" : "选择"}</button>
        <button class="button subtle" type="button" data-agent-rename="${escapeHtml(agent.id)}">保存</button>
        <button class="button danger" type="button" data-agent-delete="${escapeHtml(agent.id)}" ${cannotDelete ? "disabled" : ""}>删除</button>
      </div>
    </div>`;
  }).join("");
  list.innerHTML = `${state.agentsError ? `<div class="state-card error"><strong>${escapeHtml(state.agentsError)}</strong></div>` : ""}${rows || `<div class="state-card"><strong>正在创建 default Agent</strong><span>如果持续为空，请刷新。</span></div>`}`;
  const button = $("create-agent");
  if (button) button.textContent = state.creatingAgent ? "创建中…" : "新增 Agent";
  renderAgentSelector();
}
function renderAgentSelector() {
  const current = $("agent-menu-current");
  const menu = $("agent-menu");
  const trigger = $("agent-menu-trigger");
  const list = $("agent-menu-list");
  const agent = selectedAgent();
  if (current) current.textContent = agent?.name || "未选择 Agent";
  if (trigger) {
    trigger.disabled = !state.agents.length;
    trigger.setAttribute("aria-expanded", state.agentMenuOpen ? "true" : "false");
  }
  if (menu) menu.hidden = !state.agentMenuOpen;
  if (!list) return;
  list.innerHTML = state.agents.map((item) => {
    const selected = item.id === state.selectedAgentId;
    return `<button class="agent-menu-item ${selected ? "active" : ""}" type="button" role="menuitem" data-agent-menu-select="${escapeHtml(item.id)}">
      <span class="agent-menu-dot" aria-hidden="true"></span>
      <span class="agent-menu-name">${escapeHtml(item.name)}</span>
      <span class="agent-menu-check" aria-hidden="true">${selected ? "✓" : ""}</span>
    </button>`;
  }).join("") || `<div class="agent-menu-empty">暂无 Agent</div>`;
}

function authMessage(text = "", type = "") {
  const el = $("auth-message");
  if (!el) return;
  el.textContent = text;
  el.className = `auth-message ${type}`.trim();
}
function setAuthenticatedShell(isAuthenticated) {
  const auth = $("auth-page");
  const shell = document.querySelector(".app-shell");
  if (auth) auth.hidden = isAuthenticated;
  if (shell) shell.classList.toggle("locked", !isAuthenticated);
}
async function sendPhoneCode() {
  const phone = $("phone-input")?.value?.trim();
  if (!phone) { authMessage("请输入手机号", "error"); return; }
  authMessage("正在发送…");
  await fetchJson(API.phoneCode(), jsonPost({ phone }));
  authMessage("验证码已发送", "ok");
}
async function phoneLogin() {
  const phone = $("phone-input")?.value?.trim();
  const code = $("phone-code-input")?.value?.trim();
  if (!phone || !code) { authMessage("请输入手机号和验证码", "error"); return; }
  authMessage("正在登录…");
  const payload = await fetchJson(API.phoneLogin(), jsonPost({ phone, code }));
  const token = pick(payload.token, payload.access_token, payload.jwt, payload.data?.token, payload.data?.access_token);
  const projectId = pick(payload.current_project_id, payload.project_id, payload.default_project_id, payload.data?.current_project_id, payload.data?.project_id);
  if (!token) throw new Error("登录成功但未返回 token");
  localStorage.setItem(STORAGE.token, token);
  if (projectId) localStorage.setItem(STORAGE.projectId, String(projectId));
  state.currentProjectId = localStorage.getItem(STORAGE.projectId) || "";
  setAuthenticatedShell(true);
  await bootstrapAuthenticatedApp();
}
async function loadProjects() {
  const payload = await fetchJson(API.projects());
  const rows = Array.isArray(payload) ? payload : (payload.projects || payload.data || []);
  state.projects = rows.map(normalizeProject).filter((project) => project.id);
  if (!state.projects.length) {
    state.projects = [{ id: "default", name: "默认项目", otlpEndpoint: DEFAULT_OTLP_ENDPOINT }];
  }
  let id = localStorage.getItem(STORAGE.projectId) || state.currentProjectId;
  if (!id || !state.projects.some((project) => project.id === id)) id = state.projects[0].id;
  state.currentProjectId = id;
  localStorage.setItem(STORAGE.projectId, id);
  state.otlpEndpoint = currentProject()?.otlpEndpoint || DEFAULT_OTLP_ENDPOINT;
  renderProjectSelector();
}
function renderProjectSelector() {
  const select = $("project-select");
  const label = $("current-project-label");
  const project = currentProject();
  if (label) label.textContent = `当前项目：${project?.name || "默认项目"}`;
  if (select) {
    select.innerHTML = state.projects.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
    select.value = currentProjectId();
  }
}
async function switchProject(projectId) {
  if (!projectId || projectId === currentProjectId()) return;
  state.currentProjectId = projectId;
  localStorage.setItem(STORAGE.projectId, projectId);
  state.otlpEndpoint = currentProject()?.otlpEndpoint || DEFAULT_OTLP_ENDPOINT;
  state.apiKeyPlaintext = "";
  state.agents = [];
  state.selectedAgentId = "";
  state.agentKeyPlaintexts = {};
  localStorage.removeItem("agentotel_selected_agent_id");
  sessionStorage.removeItem(STORAGE.apiKeyPlaintext);
  state.sessions = [];
  state.traces = [];
  state.selectedSessionId = null;
  state.selectedTraceId = null;
  state.selectedTraceDetail = null;
  state.sessionPageSessions = [];
  state.tracePageTraces = [];
  renderProjectSelector();
  await Promise.all([loadApiKeys(), loadAgents(), loadSessions({ silent: false })]);
  renderIntegrationPanel();
}
async function loadApiKeys() {
  if (!currentProjectId()) return;
  try {
    const payload = await fetchJson(API.apiKeys());
    const rows = Array.isArray(payload) ? payload : (payload.api_keys || payload.keys || payload.data || []);
    state.apiKeys = rows.map(normalizeApiKey);
    state.apiKeysError = null;
  } catch (error) {
    state.apiKeys = [];
    state.apiKeysError = error instanceof Error ? error.message : String(error);
  }
  renderApiKeys();
  renderIntegrationPanel();
}
async function createApiKey() {
  const agent = selectedAgent();
  if (!agent?.id) { state.apiKeysError = "请先创建 Agent"; renderApiKeys(); return; }
  const payload = await fetchJson(API.agentApiKey(agent.id), jsonPost({ name: `${agent.name} 接入 Key` }));
  const key = normalizeApiKey(payload.api_key || payload.key || payload.data || payload);
  if (key.plaintext) {
    state.agentKeyPlaintexts[agent.id] = key.plaintext;
    sessionStorage.setItem(agentPlaintextStorageKey(agent.id), key.plaintext);
  }
  await loadAgents();
  const current = state.agents.find((item) => item.id === agent.id);
  if (current && key.plaintext) current.apiKey = key;
  state.selectedAgentId = agent.id;
  localStorage.setItem("agentotel_selected_agent_id", agent.id);
  state.apiKeysError = null;
  renderApiKeys();
  renderIntegrationPanel();
}
async function revokeApiKey() {
  const key = state.apiKeys[0];
  if (!key) return;
  await fetchJson(API.apiKey(key.id), { method: "DELETE" });
  state.apiKeyPlaintext = "";
  state.agents = [];
  state.selectedAgentId = "";
  state.agentKeyPlaintexts = {};
  localStorage.removeItem("agentotel_selected_agent_id");
  sessionStorage.removeItem(STORAGE.apiKeyPlaintext);
  await loadApiKeys();
}
function renderApiKeys() {
  const display = $("integration-api-key-display");
  if (display) {
    const agent = selectedAgent();
    display.textContent = agent ? agentApiKeyValue(agent) : "未创建";
  }
  const currentAgentName = $("settings-current-agent-name");
  if (currentAgentName) currentAgentName.textContent = selectedAgentName();
  const createButton = $("create-api-key");
  const currentAgent = selectedAgent();
  if (createButton) createButton.textContent = currentAgent?.apiKey ? "重新生成当前 Agent API Key" : "生成当前 Agent API Key";
  const once = $("new-api-key-once");
  if (once) {
    once.hidden = true;
    once.innerHTML = "";
  }
  const list = $("api-key-list");
  if (list) {
    list.hidden = true;
    list.innerHTML = "";
  }
  const revoke = $("revoke-api-key");
  if (revoke) revoke.disabled = !state.apiKeys.length;
}

function filteredSessions() {
  const query = state.query.trim().toLowerCase();
  return state.sessions.filter((session) => {
    const searchable = [session.session_id, session.agent_name, session.input_preview, session.output_preview, session.tool_input_preview]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    const matchesQuery = !query || searchable.includes(query);
    const matchesStatus = state.statusFilter !== "errors" || isErrored(session);
    return matchesQuery && matchesStatus;
  });
}
function filteredTraces() {
  const query = state.query.trim().toLowerCase();
  return state.traces.filter((trace) => {
    const searchable = [trace.trace_id, trace.root_span_name, trace.agent_name, trace.input_preview, trace.output_preview, trace.tool_input_preview]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    const matchesQuery = !query || searchable.includes(query);
    const matchesStatus = state.statusFilter !== "errors" || isErrored(trace);
    return matchesQuery && matchesStatus;
  });
}
function inCurrentTimeRange(item) {
  const range = currentTimeRange();
  const date = parseDate(pick(item.updated_at, item.ended_at, item.started_at));
  if (!date) return true;
  return date >= range.from && date <= range.to;
}
function fallbackSessionsInRange() {
  return (Array.isArray(fallbackData.sessions) ? fallbackData.sessions : []).filter(inCurrentTimeRange);
}
function fallbackTracesInRange(sessionId) {
  return (fallbackData.tracesBySession?.[sessionId] || []).filter(inCurrentTimeRange);
}

function showBanner(message, type = "warning") {
  const banner = $("api-banner");
  if (!banner) return;
  if (!message) { banner.hidden = true; banner.textContent = ""; banner.className = "api-banner"; return; }
  banner.hidden = false;
  banner.textContent = message;
  banner.className = `api-banner ${type}`;
}

function renderHeader() {
  syncTimeRangeControls();
  const indicator = $("live-indicator");
  const label = $("live-label");
  if (indicator && label) {
    indicator.className = `status-chip ${state.isFallback ? "offline" : "live"}`;
    label.textContent = state.isFallback ? "Mock 兜底" : "实时 OTEL";
  }
  const refreshed = $("last-refreshed");
  if (refreshed) refreshed.textContent = state.lastRefreshed ? formatDateTime(state.lastRefreshed) : "--";
  const rangeSummary = $("time-range-summary");
  if (rangeSummary) rangeSummary.textContent = timeRangeSummary();
  if (state.isFallback) showBanner(`同源 /api/* 暂不可用，正在显示兜底 mock 数据。${state.apiError || ""}`.trim(), "warning");
  else if (state.apiError) showBanner(state.apiError, "error");
  else showBanner("");
  renderProjectSelector();
  renderApiKeys();
  renderAgents();
  renderAgentSelector();
  const copyTrace = $("copy-current-trace");
  if (copyTrace) copyTrace.disabled = !state.selectedTraceId;
}

function renderHermesTraceStatus() {
  const status = $("hermes-trace-status");
  const hint = $("hermes-trace-hint");
  const dot = $("hermes-trace-dot");
  if (!status || !hint || !dot) return;
  const hermesSessions = state.sessions.filter((session) => {
    const text = [session.agent_name, session.session_id, session.service_name, session.source]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    return text.includes("hermes");
  });
  if (state.loadingSessions && !state.bootstrapped) {
    status.textContent = "正在检查近期 Trace";
    hint.textContent = "正在通过 /api/sessions 检查所选时间范围内的 Hermes Agent 活动。";
    dot.style.background = "var(--amber)";
    dot.style.boxShadow = "0 0 0 4px rgba(251,191,36,.12), 0 0 18px var(--amber)";
    return;
  }
  if (hermesSessions.length) {
    const latest = hermesSessions[0];
    status.textContent = `已收到 ${formatNumber(hermesSessions.length)} 个 Hermes Session`;
    hint.textContent = `最新候选：${pick(latest.session_id, "未知 Session")} · ${formatDateTime(pick(latest.updated_at, latest.ended_at, latest.started_at))}`;
    dot.style.background = "var(--green)";
    dot.style.boxShadow = "0 0 0 4px var(--green-soft), 0 0 18px var(--green)";
    return;
  }
  if (state.isFallback || state.apiError) {
    status.textContent = "静态检测卡";
    hint.textContent = "Trace API 当前不可用，本页仍可展示接入指引，不阻塞配置。";
    dot.style.background = "var(--amber)";
    dot.style.boxShadow = "0 0 0 4px rgba(251,191,36,.12), 0 0 18px var(--amber)";
    return;
  }
  status.textContent = "暂未检测到 Hermes Trace";
  hint.textContent = "运行下方验证命令后刷新，或在 Trace Explorer 中按 session_id 搜索。";
  dot.style.background = "var(--red)";
  dot.style.boxShadow = "0 0 0 4px var(--red-soft), 0 0 18px var(--red)";
}

function sessionTimestamp(session) {
  return parseDate(pick(session.updated_at, session.ended_at, session.started_at));
}
function buildSparkline(points, { targetId = "session-sparkline", label = "Sessions", showPoints = true, pointLimit = 18 } = {}) {
  const svg = $(targetId);
  if (!svg) return;
  const normalized = (Array.isArray(points) ? points : []).map((point, index) => {
    if (typeof point === "number") return { ts: "", value: asNumber(point), index };
    return { ts: point?.ts || "", value: asNumber(point?.value), index };
  });
  if (!normalized.length) { svg.innerHTML = `<path d="M0 30 L160 30" />`; return; }
  const values = normalized.map((point) => point.value);
  const max = Math.max(...values, 1);
  const step = normalized.length > 1 ? 160 / (normalized.length - 1) : 0;
  const coords = normalized.map((point, index) => ({
    ...point,
    x: normalized.length > 1 ? Math.round(index * step * 10) / 10 : 80,
    y: Math.round((34 - (point.value / max) * 30) * 10) / 10
  }));
  const polyline = coords.length > 1 ? `<polyline points="${coords.map((point) => `${point.x},${point.y}`).join(" ")}" />` : `<path d="M0 34 L160 34" class="sparkline-baseline" />`;
  const shouldShowPoints = showPoints && coords.length <= pointLimit;
  const circles = coords.map((point) => {
    const tooltip = `${point.ts ? formatDateTime(point.ts) : `Bucket ${point.index + 1}`} · ${formatNumber(point.value)} ${label}`;
    const visiblePoint = shouldShowPoints ? `<circle cx="${point.x}" cy="${point.y}" r="1.6"><title>${escapeHtml(tooltip)}</title></circle>` : "";
    return `${visiblePoint}<circle class="sparkline-hit" cx="${point.x}" cy="${point.y}" r="7"><title>${escapeHtml(tooltip)}</title></circle>`;
  }).join("");
  svg.innerHTML = `${polyline}${circles}`;
}
function computeSessionKpiFromSessions() {
  const range = currentTimeRange();
  const windowMs = range.to.getTime() - range.from.getTime();
  const prevFrom = new Date(range.from.getTime() - windowMs);
  const prevTo = range.from;
  const current = state.sessions;
  const previous = (Array.isArray(fallbackData.sessions) ? fallbackData.sessions : [])
    .filter((session) => {
      const date = sessionTimestamp(session);
      return date && date >= prevFrom && date < prevTo;
    });
  const active = current.length;
  const prevActive = previous.length;
  const delta = prevActive ? ((active - prevActive) / prevActive) * 100 : active ? 100 : 0;
  const errored = current.filter(isErrored).length;
  const avgDuration = active ? current.reduce((sum, session) => sum + asNumber(session.duration_ms), 0) / active : 0;
  const avgTokens = active ? current.reduce((sum, session) => sum + asNumber(session.total_tokens), 0) / active : 0;
  const bucketCount = Math.min(24, Math.max(8, active || 8));
  const buckets = Array.from({ length: bucketCount }, () => 0);
  current.forEach((session) => {
    const date = sessionTimestamp(session);
    if (!date || windowMs <= 0) return;
    const index = Math.min(bucketCount - 1, Math.max(0, Math.floor(((date.getTime() - range.from.getTime()) / windowMs) * bucketCount)));
    buckets[index] += 1;
  });
  return {
    active,
    delta,
    avgDuration,
    avgTokens,
    errorRate: active ? errored / active : 0,
    sparkline: buckets.map((value, index) => ({
      ts: new Date(range.from.getTime() + ((index + 0.5) / bucketCount) * windowMs).toISOString(),
      value
    }))
  };
}

function normalizeSessionCard(payload) {
  if (!payload) return computeSessionKpiFromSessions();
  return {
    active: asNumber(pick(payload.total_sessions, payload.active_sessions)),
    delta: asNumber(pick(payload.active_sessions_delta_pct, payload.total_sessions_delta_pct, payload.delta_pct)),
    avgDuration: asNumber(payload.avg_duration_ms),
    avgTokens: asNumber(payload.avg_tokens_per_session),
    errorRate: asNumber(payload.error_session_rate),
    sparkline: Array.isArray(payload.sparkline) ? payload.sparkline : (Array.isArray(payload.trend) ? payload.trend : [])
  };
}

function normalizeTraceCard(payload, totals) {
  if (payload) {
    return {
      active: asNumber(pick(payload.total_traces, payload.active_traces)),
      delta: asNumber(pick(payload.active_traces_delta_pct, payload.total_traces_delta_pct, payload.delta_pct)),
      avgDuration: asNumber(payload.avg_duration_ms),
      avgTokens: asNumber(payload.avg_tokens_per_trace),
      errorRate: asNumber(payload.error_trace_rate),
      sparkline: Array.isArray(payload.sparkline) ? payload.sparkline : (Array.isArray(payload.trend) ? payload.trend : [])
    };
  }
  const active = asNumber(totals?.traces);
  return {
    active,
    delta: 0,
    avgDuration: active ? asNumber(totals?.duration) / active : 0,
    avgTokens: active ? asNumber(totals?.tokens) / active : 0,
    errorRate: active ? asNumber(totals?.errors) / active : 0,
    sparkline: []
  };
}

function buildTokenSparklineFromSessions(sessions) {
  const range = currentTimeRange();
  const windowMs = range.to.getTime() - range.from.getTime();
  const bucketCount = Math.min(24, Math.max(8, Array.isArray(sessions) ? sessions.length : 0, 8));
  const buckets = Array.from({ length: bucketCount }, () => 0);
  (Array.isArray(sessions) ? sessions : []).forEach((session) => {
    const date = sessionTimestamp(session);
    if (!date || windowMs <= 0) return;
    const index = Math.min(bucketCount - 1, Math.max(0, Math.floor(((date.getTime() - range.from.getTime()) / windowMs) * bucketCount)));
    buckets[index] += asNumber(session.total_tokens);
  });
  return buckets.map((value, index) => ({
    ts: new Date(range.from.getTime() + ((index + 0.5) / bucketCount) * windowMs).toISOString(),
    value
  }));
}

function normalizeTokenCard(payload, totals) {
  if (payload) {
    return {
      totalTokens: asNumber(pick(payload.total_tokens, payload.tokens)),
      delta: asNumber(payload.token_delta_pct),
      inputTokens: asNumber(pick(payload.input_tokens, payload.total_input_tokens, payload.prompt_tokens)),
      outputTokens: asNumber(pick(payload.output_tokens, payload.total_output_tokens, payload.completion_tokens)),
      cost: asNumber(pick(payload.cost_cny, payload.total_cost_cny, payload.cost, payload.total_cost, payload.cost_yuan)),
      sparkline: Array.isArray(payload.sparkline) ? payload.sparkline : (Array.isArray(payload.trend) ? payload.trend : [])
    };
  }
  return {
    totalTokens: asNumber(totals?.tokens),
    delta: 0,
    inputTokens: asNumber(totals?.inputTokens),
    outputTokens: asNumber(totals?.outputTokens),
    cost: asNumber(totals?.cost),
    sparkline: buildTokenSparklineFromSessions(state.sessions)
  };
}

function setDelta(el, delta) {
  if (!el) return;
  el.textContent = `${delta > 0 ? "↗" : delta < 0 ? "↘" : "→"} ${formatPercent(Math.abs(delta))}`;
  el.className = `kpi-delta ${delta > 0 ? "up" : delta < 0 ? "down" : "flat"}`;
}

function renderSummary() {
  const totals = state.sessions.reduce((acc, s) => {
    acc.traces += asNumber(s.trace_count);
    acc.observations += asNumber(s.observation_count);
    acc.errors += asNumber(s.error_count);
    acc.tokens += asNumber(s.total_tokens);
    acc.inputTokens += asNumber(s.input_tokens);
    acc.outputTokens += asNumber(s.output_tokens);
    acc.cost += asNumber(pick(s.cost_cny, s.total_cost_cny, s.cost, s.total_cost, s.cost_yuan));
    acc.duration += asNumber(s.duration_ms);
    return acc;
  }, { traces: 0, observations: 0, errors: 0, tokens: 0, inputTokens: 0, outputTokens: 0, cost: 0, duration: 0 });
  const sessionKpi = normalizeSessionCard(state.sessionCard);
  const delta = sessionKpi.delta;
  setDelta($("session-delta"), delta);
  $("summary-sessions").textContent = formatNumber(sessionKpi.active);
  $("session-avg-duration").textContent = formatDuration(sessionKpi.avgDuration);
  $("session-avg-tokens").textContent = formatCompactNumber(sessionKpi.avgTokens);
  const errorRateEl = $("session-error-rate");
  if (errorRateEl) {
    errorRateEl.textContent = formatRatio(sessionKpi.errorRate);
    errorRateEl.className = sessionKpi.errorRate >= 0.1 ? "danger" : sessionKpi.errorRate >= 0.05 ? "warn" : "";
  }
  buildSparkline(sessionKpi.sparkline || []);
  const traceKpi = normalizeTraceCard(state.traceCard, totals);
  const traceDelta = traceKpi.delta;
  setDelta($("trace-delta"), traceDelta);
  $("summary-traces").textContent = formatNumber(traceKpi.active);
  $("trace-avg-duration").textContent = formatDuration(traceKpi.avgDuration);
  $("trace-avg-tokens").textContent = formatCompactNumber(traceKpi.avgTokens);
  const traceErrorRateEl = $("trace-error-rate");
  if (traceErrorRateEl) {
    traceErrorRateEl.textContent = formatRatio(traceKpi.errorRate);
    traceErrorRateEl.className = traceKpi.errorRate >= 0.1 ? "danger" : traceKpi.errorRate >= 0.05 ? "warn" : "";
  }
  buildSparkline(traceKpi.sparkline || [], { targetId: "trace-sparkline", label: "Traces" });
  const tokenKpi = normalizeTokenCard(state.tokenCard, totals);
  setDelta($("token-delta"), tokenKpi.delta);
  const scoreEl = $("summary-score");
  if (scoreEl) scoreEl.textContent = "--";
  buildSparkline([], { targetId: "score-sparkline", label: "Score", showPoints: false });
  $("summary-tokens").textContent = formatCompactNumber(tokenKpi.totalTokens);
  $("token-input").textContent = formatCompactNumber(tokenKpi.inputTokens);
  $("token-output").textContent = formatCompactNumber(tokenKpi.outputTokens);
  $("token-cost").textContent = formatCurrencyCny(tokenKpi.cost);
  buildSparkline(tokenKpi.sparkline || [], { targetId: "token-sparkline", label: "Tokens" });
  const traceSubtitle = $("summary-traces-subtitle");
  if (traceSubtitle) traceSubtitle.textContent = "按所选时间范围筛选";
}

function copyButton(value, label = "复制") {
  if (!value) return "";
  return `<button class="copy-button" type="button" data-copy="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}
function statusPill(status) { return `<span class="status-pill ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span>`; }
function typePill(type) { const label = pick(type, "span"); return `<span class="type-pill ${typeClass(label)}">${escapeHtml(label)}</span>`; }
function oneLinePreview(...values) {
  const raw = pick(...values, "");
  if (!raw) return "";
  return String(raw).replace(/\s+/g, " ").trim();
}
function previewLine(value, fallback = "暂无输入预览") {
  const text = oneLinePreview(value);
  return text || fallback;
}
function compareByStartedAtAsc(a, b) {
  const leftRaw = pick(a.started_at, a.updated_at, a.ended_at, "");
  const rightRaw = pick(b.started_at, b.updated_at, b.ended_at, "");
  const left = parseDate(leftRaw)?.getTime();
  const right = parseDate(rightRaw)?.getTime();
  if (Number.isFinite(left) && Number.isFinite(right) && left !== right) return left - right;
  if (String(leftRaw) !== String(rightRaw)) return String(leftRaw).localeCompare(String(rightRaw));
  return 0;
}
function observationStartMs(obs, traceStartMs) {
  const started = parseDate(obs.started_at)?.getTime();
  if (!Number.isFinite(started)) return Number.isFinite(traceStartMs) ? traceStartMs : 0;
  return started;
}
function normalizeTraceObservations(detail) {
  const observations = Array.isArray(detail?.observations) ? [...detail.observations] : [];
  return observations.sort(compareByStartedAtAsc).map((obs, index) => ({ ...obs, __index: index }));
}
function traceBounds(trace, observations) {
  const startCandidates = [trace.started_at, ...observations.map((obs) => obs.started_at)].map(parseDate).filter(Boolean).map((d) => d.getTime());
  const endCandidates = [trace.ended_at, trace.updated_at, ...observations.map((obs) => pick(obs.ended_at, obs.started_at))].map(parseDate).filter(Boolean).map((d) => d.getTime());
  const start = startCandidates.length ? Math.min(...startCandidates) : Date.now();
  const end = endCandidates.length ? Math.max(...endCandidates) : start + asNumber(trace.duration_ms);
  const duration = Math.max(end - start, asNumber(trace.duration_ms), 1);
  return { start, end: start + duration, duration };
}
function spanDepth(obs, byId, guard = new Set()) {
  const spanId = obs?.span_id;
  if (!spanId || guard.has(spanId)) return 0;
  const parentId = obs.parent_span_id;
  if (!parentId || !byId.has(parentId)) return 0;
  guard.add(spanId);
  return Math.min(6, 1 + spanDepth(byId.get(parentId), byId, guard));
}
function spanPreview(obs) {
  return previewLine(obs.input_preview, obs.tool_input_preview, obs.output_preview, obs.tool_output_preview, pick(obs.name, obs.tool_name, "暂无预览"));
}
function renderTraceSpanDetail(obs) {
  if (!obs) {
    return `<aside class="trace-span-detail empty-state"><div class="state-card"><strong>选择一个 Span</strong><p>点击左侧时间线查看输入、输出和 attributes。</p></div></aside>`;
  }
  const errored = statusClass(obs.status_code) === "error";
  return `
    <aside class="trace-span-detail">
      <div class="span-detail-head">
        <div>
          <p class="eyebrow">Span Detail</p>
          <h4>${escapeHtml(pick(obs.name, obs.span_id, "未命名 Span"))}</h4>
        </div>
        ${statusPill(obs.status_code)}
      </div>
      <div class="span-detail-grid">
        ${summaryItem("类型", pick(obs.observation_type, obs.kind, "span"))}
        ${summaryItem("时长", formatDuration(obs.duration_ms))}
        ${summaryItem("开始", formatDateTime(obs.started_at))}
        ${summaryItem("结束", formatDateTime(obs.ended_at))}
        ${summaryItem("span_id", pick(obs.span_id, "--"))}
        ${summaryItem("parent", pick(obs.parent_span_id, "root"))}
        ${summaryItem("Token", formatNumber(obs.total_tokens))}
        ${summaryItem("模型/工具", modelOrTool(obs))}
      </div>
      ${errored && obs.status_message ? `<p class="status-message">${escapeHtml(obs.status_message)}</p>` : ""}
      <div class="previews span-previews">
        ${previewBlock("输入预览", obs.input_preview)}
        ${previewBlock("输出预览", obs.output_preview)}
        ${previewBlock("tool 输入", obs.tool_input_preview)}
        ${previewBlock("tool 输出", obs.tool_output_preview)}
      </div>
      ${detailsBlock("attributes", obs.attributes)}
      ${detailsBlock("resource attributes", obs.resource_attributes)}
    </aside>`;
}
function renderTraceWaterfall(detail) {
  const trace = detail?.trace || {};
  const observations = normalizeTraceObservations(detail);
  if (!observations.length) {
    return `<div class="trace-expand-detail empty-state"><div class="state-card"><strong>没有观测记录</strong><p>此 Trace 暂无可展开的 Span。</p></div></div>`;
  }
  const bounds = traceBounds(trace, observations);
  const byId = new Map(observations.filter((obs) => obs.span_id).map((obs) => [obs.span_id, obs]));
  const selected = observations.find((obs) => obs.span_id === state.selectedTraceSpanId) || observations[0];
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return `
    <div class="trace-expand-detail" aria-label="Trace Span 时间线">
      <div class="trace-detail-header">
        <div>
          <p class="eyebrow">Details & Timeline</p>
          <h3>${escapeHtml(pick(trace.root_span_name, trace.trace_id, "Trace"))}</h3>
        </div>
        <div class="inline-meta">${statusPill(trace.status_code)}<span class="metric-pill">${formatDuration(bounds.duration)}</span><span class="metric-pill">${formatNumber(observations.length)} spans</span><span class="metric-pill">${formatCompactNumber(trace.total_tokens)} token</span></div>
      </div>
      <div class="trace-waterfall-layout">
        <section class="trace-waterfall-panel">
          <div class="waterfall-axis" aria-hidden="true">
            ${ticks.map((tick) => `<span style="left:${tick * 100}%">${tick === 0 ? "0s" : `${(bounds.duration * tick / 1000).toFixed(bounds.duration < 10_000 ? 1 : 0)}s`}</span>`).join("")}
          </div>
          <div class="waterfall-list">
            ${observations.map((obs) => {
              const start = observationStartMs(obs, bounds.start);
              const offset = Math.max(0, Math.min(100, ((start - bounds.start) / bounds.duration) * 100));
              const width = Math.max(1.5, Math.min(100 - offset, (Math.max(asNumber(obs.duration_ms), 1) / bounds.duration) * 100));
              const depth = spanDepth(obs, byId);
              const selectedClass = obs.span_id === selected?.span_id ? "selected" : "";
              const errored = statusClass(obs.status_code) === "error";
              return `
                <button class="waterfall-row ${selectedClass} ${errored ? "error" : ""}" type="button" data-trace-span-id="${escapeHtml(obs.span_id || String(obs.__index))}">
                  <span class="waterfall-label" style="padding-left:${depth * 16}px">
                    <span class="row-status-dot ${errored ? "error" : "ok"}" aria-hidden="true"></span>
                    ${typePill(obs.observation_type)}
                    <strong>${escapeHtml(pick(obs.name, obs.tool_name, obs.span_id, "span"))}</strong>
                  </span>
                  <span class="waterfall-track">
                    <span class="waterfall-grid" aria-hidden="true"></span>
                    <span class="waterfall-bar ${errored ? "error" : typeClass(obs.observation_type)}" style="left:${offset}%;width:${width}%"></span>
                  </span>
                  <span class="waterfall-duration">${escapeHtml(formatDuration(obs.duration_ms))}</span>
                  <span class="waterfall-preview">${escapeHtml(spanPreview(obs))}</span>
                </button>`;
            }).join("")}
          </div>
        </section>
        ${renderTraceSpanDetail(selected)}
      </div>
    </div>`;
}

function renderSessionTraceTimeline(sessionId) {
  if (sessionId !== state.selectedSessionId) return "";
  if (state.loadingTraces) {
    return `
      <div class="session-trace-timeline loading-state">
        <div class="state-card"><span class="spinner"></span><strong>正在展开会话任务</strong></div>
      </div>`;
  }
  const traces = Array.isArray(state.traces) ? [...state.traces].sort(compareByStartedAtAsc) : [];
  if (!traces.length) {
    return `
      <div class="session-trace-timeline empty-state">
        <div class="state-card"><strong>暂无任务</strong><p>这个会话在当前时间范围内没有可展示的任务。</p></div>
      </div>`;
  }
  const started = traces[0]?.started_at;
  const ended = traces.reduce((latest, trace) => {
    const current = parseDate(pick(trace.ended_at, trace.updated_at, trace.started_at));
    const last = parseDate(latest);
    return !last || (current && current > last) ? pick(trace.ended_at, trace.updated_at, trace.started_at) : latest;
  }, started);
  return `
    <div class="session-trace-timeline" aria-label="Session Trace 时间线">
      <div class="timeline-summary">
        <span><small>开始</small><strong>${escapeHtml(formatDateTime(started))}</strong></span>
        <span><small>结束</small><strong>${escapeHtml(formatDateTime(ended))}</strong></span>
        <span><small>Trace</small><strong>${formatNumber(traces.length)}</strong></span>
      </div>
      <div class="trace-timeline-list">
        ${traces.map((trace) => {
          const traceId = pick(trace.trace_id, "");
          const errors = asNumber(trace.error_count);
          const preview = previewLine(trace.input_preview, trace.tool_input_preview, trace.output_preview, pick(trace.root_span_name, "暂无输入预览"));
          return `
            <button class="trace-timeline-item ${traceId === state.selectedTraceId ? "selected" : ""}" type="button" data-session-timeline-trace-id="${escapeHtml(traceId)}">
              <span class="timeline-dot ${statusClass(trace.status_code) === "error" || errors ? "error" : "ok"}" aria-hidden="true"></span>
              <span class="timeline-main">
                <span class="timeline-title">
                  <strong>${escapeHtml(pick(trace.root_span_name, trace.agent_name, "未命名 Trace"))}</strong>
                  <code>${escapeHtml(traceId)}</code>
                </span>
                <span class="timeline-preview">${escapeHtml(preview)}</span>
              </span>
              <span class="timeline-time">
                <small>${escapeHtml(formatDateTime(trace.started_at))}</small>
                <small>${escapeHtml(formatDateTime(pick(trace.ended_at, trace.updated_at)))}</small>
              </span>
              <span class="timeline-metrics">
                <span><small>时长</small><strong>${formatDuration(trace.duration_ms)}</strong></span>
                <span><small>Token</small><strong>${formatCompactNumber(trace.total_tokens)}</strong></span>
                <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
              </span>
            </button>`;
        }).join("")}
      </div>
    </div>`;
}

function renderSessions() {
  const container = $("sessions-list");
  const count = $("sessions-count");
  if (!container) return;
  const sessions = filteredSessions();
  count.textContent = state.loadingSessions && !state.sessions.length ? "加载中" : `${sessions.length}/${state.sessions.length}`;
  if (state.loadingSessions && !state.sessions.length) {
    container.className = "sessions-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载 Session</strong><p>正在通过同源代理获取 /api/sessions。</p></div>`;
    return;
  }
  if (!state.sessions.length) {
    container.className = "sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>所选时间范围内没有 Session</strong><p>${escapeHtml(timeRangeSummary())}。调整时间范围，或运行 OTel smoke ingest 写入 ClickHouse 数据。</p></div>`;
    return;
  }
  if (!sessions.length) {
    container.className = "sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>没有匹配的 Session</strong><p>尝试其他 session_id/agent 搜索，或切回“全部”。</p></div>`;
    return;
  }
  container.className = "sessions-list list-table";
  container.innerHTML = sessions.map((session) => {
    const selected = session.session_id === state.selectedSessionId ? "selected" : "";
    const errors = asNumber(session.error_count);
    const sessionId = pick(session.session_id, "");
    const preview = previewLine(session.input_preview, session.tool_input_preview, session.output_preview);
    return `
      <button class="session-row ${selected}" type="button" data-session-id="${escapeHtml(sessionId)}">
        <span class="row-status-dot ${errors ? "error" : "ok"}" aria-hidden="true"></span>
        <span class="row-main">
          <span class="row-title">
            <strong>${escapeHtml(pick(session.agent_name, "未知-agent"))}</strong>
            <code>${escapeHtml(sessionId)}</code>
          </span>
          <span class="row-preview">${escapeHtml(preview)}</span>
        </span>
        <span class="row-metrics call-metrics">
          <span><small>Trace</small><strong>${formatNumber(session.trace_count)}</strong></span>
          <span><small>LLM</small><strong>${formatNumber(session.llm_call_count)}</strong></span>
          <span><small>Tool</small><strong>${formatNumber(session.tool_call_count)}</strong></span>
          <span><small>知识库</small><strong>${formatNumber(session.knowledge_call_count)}</strong></span>
          <span><small>Token</small><strong>${formatCompactNumber(session.total_tokens)}</strong></span>
          <span><small>时长</small><strong>${formatDuration(session.duration_ms)}</strong></span>
          <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
        </span>
        <span class="row-time">${escapeHtml(formatDateTime(pick(session.updated_at, session.ended_at, session.started_at)))}</span>
      </button>`;
  }).join("");
}

function renderTraceList() {
  const title = $("trace-list-title");
  const container = $("trace-list");
  const count = $("traces-count");
  if (!container) return;
  title.textContent = state.selectedSessionId ? `Session Trace` : "选择一个 Session";
  const traces = filteredTraces();
  count.textContent = state.selectedSessionId ? `${traces.length}/${state.traces.length}` : "--";
  if (!state.selectedSessionId) {
    container.className = "trace-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>尚未选择 Session</strong><p>从当前时间范围选择一个 Session，以通过 /api/search 加载 Trace 摘要。</p></div>`;
    return;
  }
  if (state.loadingTraces) {
    container.className = "trace-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载 Trace</strong><p>正在按所选 session_id 搜索…</p></div>`;
    return;
  }
  if (!state.traces.length) {
    container.className = "trace-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>未找到 Trace</strong><p>此 Session 暂无 Trace 摘要。</p></div>`;
    return;
  }
  if (!traces.length) {
    container.className = "trace-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>没有错误 Trace</strong><p>切换到“全部”以查看成功 Trace。</p></div>`;
    return;
  }
  container.className = "trace-list list-table";
  container.innerHTML = traces.map((trace) => {
    const selected = trace.trace_id === state.selectedTraceId ? "selected" : "";
    const traceId = pick(trace.trace_id, "");
    const errors = asNumber(trace.error_count);
    const preview = previewLine(trace.input_preview, trace.tool_input_preview, trace.output_preview, pick(trace.root_span_name, "暂无输入预览"));
    return `
      <button class="trace-row ${selected}" type="button" data-trace-id="${escapeHtml(traceId)}">
        <span class="row-status-dot ${statusClass(trace.status_code) === "error" || errors ? "error" : "ok"}" aria-hidden="true"></span>
        <span class="row-main">
          <span class="row-title">
            <strong>${escapeHtml(pick(trace.root_span_name, "未命名根 Span"))}</strong>
            <code>${escapeHtml(traceId)}</code>
          </span>
          <span class="row-preview">${escapeHtml(preview)}</span>
        </span>
        <span class="row-metrics call-metrics">
          <span><small>Span</small><strong>${formatNumber(trace.observation_count)}</strong></span>
          <span><small>LLM</small><strong>${formatNumber(trace.llm_call_count)}</strong></span>
          <span><small>Tool</small><strong>${formatNumber(trace.tool_call_count)}</strong></span>
          <span><small>知识库</small><strong>${formatNumber(trace.knowledge_call_count)}</strong></span>
          <span><small>Token</small><strong>${formatCompactNumber(trace.total_tokens)}</strong></span>
          <span><small>时长</small><strong>${formatDuration(trace.duration_ms)}</strong></span>
          <span><small>状态</small><strong class="${statusClass(trace.status_code) === "error" ? "danger" : ""}">${escapeHtml(statusLabel(trace.status_code))}</strong></span>
        </span>
        <span class="row-time">${escapeHtml(formatDateTime(pick(trace.started_at, trace.updated_at)))}</span>
      </button>`;
  }).join("");
}

function summaryItem(label, value) {
  return `<div class="summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "--")}</strong></div>`;
}
function previewBlock(label, value) {
  if (!value) return "";
  return `<div class="preview-block"><span>${escapeHtml(label)}</span><pre>${escapeHtml(value)}</pre></div>`;
}
function detailsBlock(label, value) {
  const json = jsonString(value);
  if (!json) return "";
  return `<details><summary>${escapeHtml(label)}</summary><pre>${escapeHtml(json)}</pre></details>`;
}
function modelOrTool(obs) {
  const model = [obs.model_provider, obs.model_name].filter(Boolean).join(" / ");
  if (model) return model;
  if (obs.tool_name) return `tool: ${obs.tool_name}`;
  return pick(obs.kind, obs.source, "Span");
}

function renderTraceDetail() {
  const title = $("detail-title");
  const container = $("trace-detail");
  if (!container) return;
  if (!state.selectedTraceId) {
    title.textContent = "尚未选择 Trace";
    container.className = "empty-state";
    container.innerHTML = `<div class="state-card"><strong>准备下钻</strong><p>选择一个 Trace，检查观测时间线、预览和原始 attributes。</p></div>`;
    return;
  }
  if (state.loadingTraceDetail && !state.selectedTraceDetail) {
    title.textContent = "正在加载 Trace";
    container.className = "loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载 Trace 详情</strong><p>正在获取 /api/traces/${escapeHtml(state.selectedTraceId)}</p></div>`;
    return;
  }
  const detail = state.selectedTraceDetail;
  if (!detail) {
    title.textContent = "Trace 不可用";
    container.className = "empty-state";
    container.innerHTML = `<div class="state-card"><strong>Trace 详情不可用</strong><p>该 Trace 可能已过期，或 API 返回了错误。</p></div>`;
    return;
  }
  const trace = detail.trace || {};
  const observations = Array.isArray(detail.observations) ? detail.observations : [];
  title.textContent = pick(trace.root_span_name, trace.trace_id, state.selectedTraceId);
  container.className = "trace-detail-content";
  container.innerHTML = `
    <div class="detail-summary">
      <article class="trace-summary-card">
        <div class="summary-topline">
          <div>
            <p class="summary-title">${escapeHtml(pick(trace.root_span_name, "Trace 摘要"))}</p>
            <div class="inline-meta">${statusPill(trace.status_code)}<span class="metric-pill">${formatDuration(trace.duration_ms)}</span><span class="metric-pill">${formatNumber(pick(trace.observation_count, observations.length))} 观测</span><span class="metric-pill">${formatNumber(trace.total_tokens)} token</span></div>
          </div>
          ${copyButton(pick(trace.trace_id, state.selectedTraceId), "trace_id")}
        </div>
      </article>
      <div class="summary-grid">
        ${summaryItem("trace_id", pick(trace.trace_id, state.selectedTraceId))}
        ${summaryItem("session_id", pick(trace.session_id, state.selectedSessionId))}
        ${summaryItem("agent", pick(trace.agent_name, "--"))}
        ${summaryItem("开始时间", formatDateTime(trace.started_at))}
        ${summaryItem("错误", formatNumber(trace.error_count))}
        ${summaryItem("tokens", formatNumber(trace.total_tokens))}
      </div>
    </div>
    <h4 class="section-title">观测时间线</h4>
    ${observations.length ? `<div class="timeline">${observations.map(renderObservation).join("")}</div>` : `<div class="state-card"><strong>没有观测记录</strong><p>此 Trace 暂无 LLM/tool/Span/event 行。</p></div>`}
  `;
}

function renderObservation(obs) {
  const errored = statusClass(obs.status_code) === "error";
  return `
    <article class="observation-row ${errored ? "error" : ""}">
      <span class="timeline-dot" aria-hidden="true"></span>
      <div class="observation-card">
        <div class="observation-head">
          <div class="observation-name">
            ${typePill(obs.observation_type)}
            <strong>${escapeHtml(pick(obs.name, obs.span_id, "未命名观测"))}</strong>
            <code class="id-text">span ${escapeHtml(obs.span_id || "--")}</code>
          </div>
          ${statusPill(obs.status_code)}
        </div>
        <div class="observation-meta">
          <span>${escapeHtml(formatDateTime(obs.started_at))}</span>
          <span>${escapeHtml(formatDuration(obs.duration_ms))}</span>
          <span>${escapeHtml(modelOrTool(obs))}</span>
          <span>${formatNumber(obs.total_tokens)} tokens</span>
        </div>
        ${obs.status_message ? `<p class="status-message">${escapeHtml(obs.status_message)}</p>` : ""}
        <div class="previews">
          ${previewBlock("输入预览", obs.input_preview)}
          ${previewBlock("输出预览", obs.output_preview)}
          ${previewBlock("tool 输入", obs.tool_input_preview)}
          ${previewBlock("tool 输出", obs.tool_output_preview)}
        </div>
        ${detailsBlock("attributes", obs.attributes)}
        ${detailsBlock("resource attributes", obs.resource_attributes)}
      </div>
    </article>`;
}

function renderTopSessions() {
  const container = $("top-sessions-list");
  if (!container) return;
  document.querySelectorAll("[data-top-session-sort]").forEach((button) => {
    button.classList.toggle("active", button.dataset.topSessionSort === state.topSessionsSort);
  });
  const sessions = Array.isArray(state.topSessions) ? state.topSessions : [];
  if (state.loadingSessions && !sessions.length) {
    container.className = "top-sessions-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载重点会话</strong></div>`;
    return;
  }
  if (state.topSessionsError && !sessions.length) {
    container.className = "top-sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>重点会话暂不可用</strong><p>${escapeHtml(state.topSessionsError)}</p></div>`;
    return;
  }
  if (!sessions.length) {
    container.className = "top-sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>暂无重点会话</strong><p>调整时间范围，或等待更多任务数据。</p></div>`;
    return;
  }
  const sortMetric = state.topSessionsSort;
  const metricLabel = sortMetric === "duration" ? "时长" : sortMetric === "errors" ? "异常" : sortMetric === "latest" ? "最新" : "Token";
  container.className = "top-sessions-list top-rank-list";
  container.innerHTML = sessions.map((session, index) => {
    const sessionId = pick(session.session_id, "");
    const errors = asNumber(session.error_count);
    const preview = previewLine(session.input_preview, session.tool_input_preview, session.output_preview);
    const metricValue = sortMetric === "duration"
      ? formatDuration(session.duration_ms)
      : sortMetric === "errors"
        ? `${formatNumber(errors)} 次`
        : sortMetric === "latest"
          ? formatDateTime(pick(session.updated_at, session.ended_at, session.started_at))
          : formatCompactNumber(session.total_tokens);
    return `
      <button class="top-session-row top-rank-row" type="button" data-session-id="${escapeHtml(sessionId)}">
        <span class="rank-badge">${index + 1}</span>
        <span class="top-rank-main">
          <span class="row-title">
            <strong>${escapeHtml(pick(session.agent_name, "未知-agent"))}</strong>
            <code>${escapeHtml(sessionId)}</code>
          </span>
          <span class="row-preview">${escapeHtml(preview)}</span>
        </span>
        <span class="row-metrics top-rank-metrics call-metrics">
          <span><small>${metricLabel}</small><strong>${metricValue}</strong></span>
          <span><small>LLM</small><strong>${formatNumber(session.llm_call_count)}</strong></span>
          <span><small>Tool</small><strong>${formatNumber(session.tool_call_count)}</strong></span>
          <span><small>知识库</small><strong>${formatNumber(session.knowledge_call_count)}</strong></span>
          <span><small>Token</small><strong>${formatCompactNumber(session.total_tokens)}</strong></span>
          <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
        </span>
        <span class="row-time">${escapeHtml(formatDateTime(pick(session.updated_at, session.ended_at, session.started_at)))}</span>
      </button>`;
  }).join("");
}

function renderSessionPage() {
  // If coming from top sessions click, get the query from hash
  const hash = window.location.hash.replace(/^#/, '');
  if (hash.startsWith('sessions?q=')) {
    const q = decodeURIComponent(hash.substring('sessions?q='.length));
    if (q && q !== state.sessionPageQuery) {
      state.sessionPageQuery = q;
      const input = $("session-page-search");
      if (input) input.value = q;
      state.sessionPagePage = 1;
      state.sessionPageSessions = [];
      state.sessionPageHasMore = false;
      loadSessionPage();
    }
  } else if (hash === 'sessions' && state.sessionPageQuery.trim()) {
    // User navigated to pure #sessions, clear query
    state.sessionPageQuery = '';
    const input = $("session-page-search");
    if (input) input.value = '';
    state.sessionPagePage = 1;
    state.sessionPageSessions = [];
    state.sessionPageHasMore = false;
  }

  const container = $("session-page-list");
  const info = $("session-page-info");
  const summary = $("session-page-summary");
  const prev = $("session-page-prev");
  const next = $("session-page-next");
  if (!container) return;
  document.querySelectorAll("[data-session-page-sort]").forEach((button) => {
    const activeSort = state.sessionPageStatusFilter === "errors" ? "errors" : state.sessionPageSort;
    button.classList.toggle("active", button.dataset.sessionPageSort === activeSort);
  });
  document.querySelectorAll("[data-session-page-status]").forEach((button) => {
    button.classList.toggle("active", button.dataset.sessionPageStatus === state.sessionPageStatusFilter);
  });
  const sessions = Array.isArray(state.sessionPageSessions) ? state.sessionPageSessions : [];
  const page = state.sessionPagePage;
  const shownFrom = sessions.length ? (page - 1) * state.sessionPageSize + 1 : 0;
  const shownTo = sessions.length ? shownFrom + sessions.length - 1 : 0;
  const inferredTotal = state.sessionPageHasMore ? `${shownTo}+` : `${shownTo}`;
  const rangeLabel = timeRangeSummary();
  const filterParts = [];
  if (state.sessionPageQuery.trim()) filterParts.push(`搜索 ${state.sessionPageQuery.trim()}`);
  if (state.sessionPageStatusFilter === "errors") filterParts.push("仅错误");
  const contextLabel = filterParts.length ? `${rangeLabel} · ${filterParts.join(" · ")}` : rangeLabel;
  const statusText = state.loadingSessionPage && !sessions.length
    ? "正在加载"
    : sessions.length
      ? `显示 ${shownFrom}-${shownTo} / ${inferredTotal} 条`
      : "显示 0 条";
  if (summary) summary.innerHTML = `
    <span>${escapeHtml(contextLabel)}</span>
    <strong>${escapeHtml(statusText)}</strong>
  `;
  if (info) info.textContent = sessions.length
    ? `第 ${page} 页 · 每页 ${state.sessionPageSize} 条 · 当前 ${sessions.length} 条${state.sessionPageHasMore ? " · 还有更多" : " · 已全部加载"}`
    : `第 ${page} 页 · 每页 ${state.sessionPageSize} 条 · 当前 0 条`;
  if (prev) prev.disabled = page <= 1 || state.loadingSessionPage;
  if (next) next.disabled = !state.sessionPageHasMore || state.loadingSessionPage;
  if (state.loadingSessionPage && !sessions.length) {
    container.className = "top-sessions-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载 Sessions</strong></div>`;
    return;
  }
  if (state.sessionPageError && !sessions.length) {
    container.className = "top-sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>Sessions 暂不可用</strong><p>${escapeHtml(state.sessionPageError)}</p></div>`;
    return;
  }
  if (!sessions.length) {
    container.className = "top-sessions-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>暂无 Session</strong><p>调整时间范围，或等待更多 Trace 数据。</p></div>`;
    return;
  }
  const sortMetric = state.sessionPageSort;
  const metricLabel = sortMetric === "duration" ? "时长" : sortMetric === "errors" ? "异常" : sortMetric === "latest" ? "最新" : "Token";
  const baseRank = (page - 1) * state.sessionPageSize;
  container.className = "top-sessions-list top-rank-list session-expand-list";
  container.innerHTML = sessions.map((session, index) => {
    const sessionId = pick(session.session_id, "");
    const expanded = sessionId === state.selectedSessionId;
    const errors = asNumber(session.error_count);
    const preview = previewLine(session.input_preview, session.tool_input_preview, session.output_preview);
    const metricValue = sortMetric === "duration"
      ? formatDuration(session.duration_ms)
      : sortMetric === "errors"
        ? `${formatNumber(errors)} 次`
        : sortMetric === "latest"
          ? formatDateTime(pick(session.updated_at, session.ended_at, session.started_at))
          : formatCompactNumber(session.total_tokens);
    return `
      <article class="session-expand-card ${expanded ? "expanded" : ""}">
        <button class="top-session-row top-rank-row" type="button" data-session-id="${escapeHtml(sessionId)}" aria-expanded="${expanded ? "true" : "false"}">
          <span class="rank-badge">${baseRank + index + 1}</span>
          <span class="top-rank-main">
            <span class="row-title">
              <strong>${escapeHtml(pick(session.agent_name, "未知-agent"))}</strong>
              <code>${escapeHtml(sessionId)}</code>
            </span>
            <span class="row-preview">${escapeHtml(preview)}</span>
          </span>
          <span class="row-metrics top-rank-metrics call-metrics">
            <span><small>${metricLabel}</small><strong>${metricValue}</strong></span>
            <span><small>LLM</small><strong>${formatNumber(session.llm_call_count)}</strong></span>
            <span><small>Tool</small><strong>${formatNumber(session.tool_call_count)}</strong></span>
            <span><small>知识库</small><strong>${formatNumber(session.knowledge_call_count)}</strong></span>
            <span><small>Token</small><strong>${formatCompactNumber(session.total_tokens)}</strong></span>
            <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
          </span>
          <span class="row-time">${escapeHtml(formatDateTime(pick(session.updated_at, session.ended_at, session.started_at)))}</span>
        </button>
        ${expanded ? renderSessionTraceTimeline(sessionId) : ""}
      </article>`;
  }).join("");

  // If exactly one result from query, auto-expand it
  if (sessions.length === 1 && !state.selectedSessionId) {
    state.selectedSessionId = sessions[0].session_id;
    loadTracesForSelected({ autoSelectTrace: false });
  }
}

function renderTracePage() {
  // If coming from top traces click, get the query from hash
  const hash = window.location.hash.replace(/^#/, '');
  if (hash.startsWith('traces?q=')) {
    const q = decodeURIComponent(hash.substring('traces?q='.length));
    if (q && q !== state.tracePageQuery) {
      state.tracePageQuery = q;
      const input = $("trace-page-search");
      if (input) input.value = q;
      state.tracePagePage = 1;
      state.tracePageTraces = [];
      state.tracePageHasMore = false;
      loadTracePage();
    }
  } else if (hash === 'traces' && state.tracePageQuery.trim()) {
    // User navigated to pure #traces, clear query
    state.tracePageQuery = '';
    const input = $("trace-page-search");
    if (input) input.value = '';
    state.tracePagePage = 1;
    state.tracePageTraces = [];
    state.tracePageHasMore = false;
  }

  const container = $("trace-page-list");
  const info = $("trace-page-info");
  const summary = $("trace-page-summary");
  const prev = $("trace-page-prev");
  const next = $("trace-page-next");
  if (!container) return;
  document.querySelectorAll("[data-trace-page-sort]").forEach((button) => {
    const activeSort = state.tracePageStatusFilter === "errors" ? "errors" : state.tracePageSort;
    button.classList.toggle("active", button.dataset.tracePageSort === activeSort);
  });
  document.querySelectorAll("[data-trace-page-status]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tracePageStatus === state.tracePageStatusFilter);
  });
  const traces = Array.isArray(state.tracePageTraces) ? state.tracePageTraces : [];
  const page = state.tracePagePage;
  const shownFrom = traces.length ? (page - 1) * state.tracePageSize + 1 : 0;
  const shownTo = traces.length ? shownFrom + traces.length - 1 : 0;
  const inferredTotal = state.tracePageHasMore ? `${shownTo}+` : `${shownTo}`;
  const rangeLabel = timeRangeSummary();
  const filterParts = [];
  if (state.tracePageQuery.trim()) filterParts.push(`搜索 ${state.tracePageQuery.trim()}`);
  if (state.tracePageStatusFilter === "errors") filterParts.push("仅错误");
  const contextLabel = filterParts.length ? `${rangeLabel} · ${filterParts.join(" · ")}` : rangeLabel;
  const statusText = state.loadingTracePage && !traces.length
    ? "正在加载"
    : traces.length
      ? `显示 ${shownFrom}-${shownTo} / ${inferredTotal} 条`
      : "显示 0 条";
  if (summary) summary.innerHTML = `
    <span>${escapeHtml(contextLabel)}</span>
    <strong>${escapeHtml(statusText)}</strong>
  `;
  if (info) info.textContent = traces.length
    ? `第 ${page} 页 · 每页 ${state.tracePageSize} 条 · 当前 ${traces.length} 条${state.tracePageHasMore ? " · 还有更多" : " · 已全部加载"}`
    : `第 ${page} 页 · 每页 ${state.tracePageSize} 条 · 当前 0 条`;
  if (prev) prev.disabled = page <= 1 || state.loadingTracePage;
  if (next) next.disabled = !state.tracePageHasMore || state.loadingTracePage;
  if (state.loadingTracePage && !traces.length) {
    container.className = "top-traces-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载 Traces</strong></div>`;
    return;
  }
  if (state.tracePageError && !traces.length) {
    container.className = "top-traces-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>Traces 暂不可用</strong><p>${escapeHtml(state.tracePageError)}</p></div>`;
    return;
  }
  if (!traces.length) {
    container.className = "top-traces-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>暂无 Trace</strong><p>调整时间范围，或等待更多 Trace 数据。</p></div>`;
    return;
  }
  const sortMetric = state.tracePageSort;
  const metricLabel = sortMetric === "duration" ? "时长" : sortMetric === "errors" ? "异常" : sortMetric === "latest" ? "最新" : "Token";
  const baseRank = (page - 1) * state.tracePageSize;
  container.className = "top-traces-list top-rank-list trace-expand-list";
  container.innerHTML = traces.map((trace, index) => {
    const traceId = pick(trace.trace_id, "");
    const sessionId = pick(trace.session_id, "");
    const expanded = traceId === state.selectedTraceId;
    const errors = asNumber(trace.error_count);
    const preview = previewLine(trace.input_preview, trace.tool_input_preview, trace.output_preview, pick(trace.root_span_name, "暂无输入预览"));
    const metricValue = sortMetric === "duration"
      ? formatDuration(trace.duration_ms)
      : sortMetric === "errors"
        ? `${formatNumber(errors)} 次`
        : sortMetric === "latest"
          ? formatDateTime(pick(trace.updated_at, trace.started_at))
          : formatCompactNumber(trace.total_tokens);
    const expandContent = expanded
      ? state.loadingTraceDetail && !state.selectedTraceDetail
        ? `<div class="trace-expand-detail loading-state"><div class="state-card"><span class="spinner"></span><strong>正在加载 Trace Timeline</strong></div></div>`
        : state.selectedTraceDetail
          ? renderTraceWaterfall(state.selectedTraceDetail)
          : `<div class="trace-expand-detail empty-state"><div class="state-card"><strong>Trace 详情不可用</strong><p>该 Trace 暂无可展开详情。</p></div></div>`
      : "";
    return `
      <article class="trace-expand-card ${expanded ? "expanded" : ""}">
        <button class="top-trace-row top-rank-row" type="button" data-trace-page-id="${escapeHtml(traceId)}" data-session-id="${escapeHtml(sessionId)}" aria-expanded="${expanded ? "true" : "false"}">
          <span class="rank-badge">${baseRank + index + 1}</span>
          <span class="top-rank-main">
            <span class="row-title">
              <strong>${escapeHtml(pick(trace.root_span_name, trace.agent_name, "未知-trace"))}</strong>
              <code>${escapeHtml(traceId)}</code>
            </span>
            <span class="row-preview">${escapeHtml(preview)}</span>
          </span>
          <span class="row-metrics top-rank-metrics call-metrics">
            <span><small>${metricLabel}</small><strong>${metricValue}</strong></span>
            <span><small>LLM</small><strong>${formatNumber(trace.llm_call_count)}</strong></span>
            <span><small>Tool</small><strong>${formatNumber(trace.tool_call_count)}</strong></span>
            <span><small>知识库</small><strong>${formatNumber(trace.knowledge_call_count)}</strong></span>
            <span><small>Token</small><strong>${formatCompactNumber(trace.total_tokens)}</strong></span>
            <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
          </span>
          <span class="row-time">${escapeHtml(formatDateTime(pick(trace.updated_at, trace.started_at)))}</span>
        </button>
        ${expandContent}
      </article>`;
  }).join("");

  // If exactly one result from query, auto-expand it
  if (traces.length === 1 && !state.selectedTraceId) {
    state.selectedTraceId = traces[0].trace_id;
    // Load span detail waterfall
    selectTrace(state.selectedTraceId);
  }
}

function renderTopTraces() {
  const container = $("top-traces-list");
  if (!container) return;
  document.querySelectorAll("[data-top-trace-sort]").forEach((button) => {
    button.classList.toggle("active", button.dataset.topTraceSort === state.topTracesSort);
  });
  const traces = Array.isArray(state.topTraces) ? state.topTraces : [];
  if (state.loadingSessions && !traces.length) {
    container.className = "top-traces-list loading-state";
    container.innerHTML = `<div class="state-card"><span class="spinner"></span><strong>正在加载重点任务</strong></div>`;
    return;
  }
  if (state.topTracesError && !traces.length) {
    container.className = "top-traces-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>重点任务暂不可用</strong><p>${escapeHtml(state.topTracesError)}</p></div>`;
    return;
  }
  if (!traces.length) {
    container.className = "top-traces-list empty-state";
    container.innerHTML = `<div class="state-card"><strong>暂无重点任务</strong><p>调整时间范围，或等待更多任务数据。</p></div>`;
    return;
  }
  const sortMetric = state.topTracesSort;
  const metricLabel = sortMetric === "duration" ? "时长" : sortMetric === "errors" ? "异常" : sortMetric === "latest" ? "最新" : "Token";
  container.className = "top-traces-list top-rank-list";
  container.innerHTML = traces.map((trace, index) => {
    const traceId = pick(trace.trace_id, "");
    const sessionId = pick(trace.session_id, "");
    const errors = asNumber(trace.error_count);
    const preview = previewLine(trace.input_preview, trace.tool_input_preview, trace.output_preview, pick(trace.root_span_name, "暂无输入预览"));
    const metricValue = sortMetric === "duration"
      ? formatDuration(trace.duration_ms)
      : sortMetric === "errors"
        ? `${formatNumber(errors)} 次`
        : sortMetric === "latest"
          ? formatDateTime(pick(trace.updated_at, trace.started_at))
          : formatCompactNumber(trace.total_tokens);
    return `
       <button class="top-trace-row top-rank-row" type="button" data-trace-id="${escapeHtml(traceId)}" data-session-id="${escapeHtml(sessionId)}">
        <span class="rank-badge">${index + 1}</span>
        <span class="top-rank-main">
          <span class="row-title">
            <strong>${escapeHtml(pick(trace.root_span_name, trace.agent_name, "未知-trace"))}</strong>
            <code>${escapeHtml(traceId)}</code>
          </span>
          <span class="row-preview">${escapeHtml(preview)}</span>
        </span>
        <span class="row-metrics top-rank-metrics call-metrics">
          <span><small>${metricLabel}</small><strong>${metricValue}</strong></span>
          <span><small>LLM</small><strong>${formatNumber(trace.llm_call_count)}</strong></span>
          <span><small>Tool</small><strong>${formatNumber(trace.tool_call_count)}</strong></span>
          <span><small>知识库</small><strong>${formatNumber(trace.knowledge_call_count)}</strong></span>
          <span><small>Token</small><strong>${formatCompactNumber(trace.total_tokens)}</strong></span>
          <span><small>异常</small><strong class="${errors ? "danger" : ""}">${formatNumber(errors)}</strong></span>
        </span>
        <span class="row-time">${escapeHtml(formatDateTime(pick(trace.updated_at, trace.started_at)))}</span>
      </button>`;
  }).join("");
}

function renderAll() {
  renderHeader();
  renderSummary();
  renderTopSessions();
  renderSessionPage();
  renderTracePage();
  renderTopTraces();
}

async function loadSessionCard() {
  try {
    state.sessionCard = await fetchJson(API.sessionCard());
    state.sessionCardError = null;
  } catch (error) {
    state.sessionCard = null;
    state.sessionCardError = error instanceof Error ? error.message : String(error);
  }
}

async function loadTraceCard() {
  try {
    state.traceCard = await fetchJson(API.traceCard());
    state.traceCardError = null;
  } catch (error) {
    state.traceCard = null;
    state.traceCardError = error instanceof Error ? error.message : String(error);
  }
}

async function loadTokenCard() {
  try {
    state.tokenCard = await fetchJson(API.tokenCard());
    state.tokenCardError = null;
  } catch (error) {
    state.tokenCard = null;
    state.tokenCardError = error instanceof Error ? error.message : String(error);
  }
}

async function loadTopSessions() {
  try {
    const payload = await fetchJson(API.topSessions());
    state.topSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    state.topSessionsError = null;
  } catch (error) {
    state.topSessions = [];
    state.topSessionsError = error instanceof Error ? error.message : String(error);
  }
}

async function loadTopTraces() {
  try {
    const payload = await fetchJson(API.topTraces());
    state.topTraces = Array.isArray(payload.traces) ? payload.traces : [];
    state.topTracesError = null;
  } catch (error) {
    state.topTraces = [];
    state.topTracesError = error instanceof Error ? error.message : String(error);
  }
}

async function loadSessionPage() {
  state.loadingSessionPage = true;
  renderAll();
  try {
    const payload = await fetchJson(API.sessionPageSessions());
    state.sessionPageSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    state.sessionPageHasMore = Boolean(payload.meta?.has_more);
    state.sessionPageError = null;
  } catch (error) {
    state.sessionPageSessions = [];
    state.sessionPageHasMore = false;
    state.sessionPageError = error instanceof Error ? error.message : String(error);
  } finally {
    state.loadingSessionPage = false;
  }
  renderAll();
}

async function loadTracePage() {
  state.loadingTracePage = true;
  renderAll();
  try {
    const payload = await fetchJson(API.tracePageTraces());
    state.tracePageTraces = Array.isArray(payload.traces) ? payload.traces : [];
    state.tracePageHasMore = Boolean(payload.meta?.has_more);
    state.tracePageError = null;
  } catch (error) {
    state.tracePageTraces = [];
    state.tracePageHasMore = false;
    state.tracePageError = error instanceof Error ? error.message : String(error);
  } finally {
    state.loadingTracePage = false;
  }
  renderAll();
}

async function loadSessions({ silent = false } = {}) {
  if (!silent) state.loadingSessions = true;
  renderAll();
  try {
    const [payload] = await Promise.all([fetchJson(API.sessions()), loadSessionCard(), loadTraceCard(), loadTokenCard(), loadTopSessions(), loadTopTraces()]);
    state.sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    state.isFallback = false;
    state.apiError = null;
  } catch (error) {
    state.sessions = fallbackSessionsInRange();
    state.isFallback = true;
    state.apiError = error instanceof Error ? error.message : String(error);
  } finally {
    state.loadingSessions = false;
    state.lastRefreshed = new Date();
    state.bootstrapped = true;
  }
  const selectedStillExists = state.selectedSessionId && state.sessions.some((s) => s.session_id === state.selectedSessionId);
  if (!selectedStillExists) {
    state.selectedSessionId = null;
    state.selectedTraceId = null;
    state.selectedTraceDetail = null;
    state.traces = [];
  }
  renderAll();
}

async function loadTracesForSelected({ autoSelectTrace = true } = {}) {
  if (!state.selectedSessionId) return;
  state.loadingTraces = true;
  renderAll();
  try {
    if (state.isFallback) state.traces = fallbackTracesInRange(state.selectedSessionId);
    else {
      const payload = await fetchJson(API.search(state.selectedSessionId));
      state.traces = Array.isArray(payload.traces) ? payload.traces : [];
    }
    state.apiError = state.isFallback ? state.apiError : null;
  } catch (error) {
    state.traces = [];
    state.apiError = `加载 ${state.selectedSessionId} 的 Trace 失败：${error instanceof Error ? error.message : String(error)}`;
  } finally {
    state.loadingTraces = false;
  }
  const visibleTraces = filteredTraces();
  const selectedTraceStillExists = state.selectedTraceId && state.traces.some((t) => t.trace_id === state.selectedTraceId);
  if (!selectedTraceStillExists) {
    state.selectedTraceId = null;
    state.selectedTraceDetail = null;
  }
  if (autoSelectTrace && !state.selectedTraceId && visibleTraces.length) {
    state.selectedTraceId = visibleTraces[0].trace_id;
    state.selectedTraceDetail = null;
    renderAll();
    await selectTrace(state.selectedTraceId);
    return;
  }
  renderAll();
}

async function selectSession(sessionId) {
  if (!sessionId || sessionId === state.selectedSessionId) return;
  state.selectedSessionId = sessionId;
  state.selectedTraceId = null;
  state.selectedTraceDetail = null;
  state.traces = [];
  await loadTracesForSelected({ autoSelectTrace: true });
}

async function selectTrace(traceId) {
  if (!traceId) return;
  state.selectedTraceId = traceId;
  state.selectedTraceSpanId = null;
  state.loadingTraceDetail = true;
  state.selectedTraceDetail = state.selectedTraceDetail?.trace?.trace_id === traceId ? state.selectedTraceDetail : null;
  renderAll();
  try {
    if (state.isFallback) state.selectedTraceDetail = fallbackData.traceDetails?.[traceId] || null;
    else state.selectedTraceDetail = await fetchJson(API.trace(traceId));
    state.apiError = state.isFallback ? state.apiError : null;
  } catch (error) {
    state.selectedTraceDetail = null;
    state.apiError = `加载 Trace ${traceId} 失败：${error instanceof Error ? error.message : String(error)}`;
  } finally {
    state.loadingTraceDetail = false;
  }
  renderAll();
}

async function applyTimeRangeChange() {
  state.selectedSessionId = null;
  state.selectedTraceId = null;
  state.selectedTraceDetail = null;
  state.traces = [];
  state.sessionPagePage = 1;
  state.sessionPageSessions = [];
  state.sessionPageHasMore = false;
  state.tracePagePage = 1;
  state.tracePageTraces = [];
  state.tracePageHasMore = false;
  await loadSessions({ silent: false });
  const activePage = parseRoute(window.location.hash).page;
  if (activePage === "sessions") await loadSessionPage();
  if (activePage === "traces") await loadTracePage();
}

async function applyCustomTimeRange() {
  const from = fromDatetimeLocal($("custom-from")?.value);
  const to = fromDatetimeLocal($("custom-to")?.value);
  if (!from || !to || from >= to) {
    state.apiError = "自定义时间范围无效：开始时间必须早于结束时间。";
    renderAll();
    return;
  }
  state.timeRange.customFrom = from;
  state.timeRange.customTo = to;
  await applyTimeRangeChange();
}

const INTEGRATIONS = {
  hermes: {
    name: "Hermes Agent",
    badge: "Token 部分支持/支持",
    note: "Token 会自动从 LLM 调用结果中提取。prompt/output 默认只上传 preview，不上传全文。",
    codeId: "code-hermes-agent",
    code: (agent = selectedAgent()) => `cat > ~/.hermes/observability.yaml <<'YAML'
enabled: true
service_name: ${selectedAgentName()}
agent_name: ${selectedAgentName()}
endpoint: "${state.otlpEndpoint}"
headers:
  Authorization: "Bearer ${agentApiKeyValue(agent, { forCopy: true })}"
capture_content: false
preview_chars: 500
YAML`,
    restart: () => `# 如果 Hermes 运行在 gateway / WeChat 中
hermes gateway restart

# 如果是 CLI 会话，退出后重新启动 hermes
# /quit
# hermes`
  },
  claude: {
    name: "Claude Code",
    badge: "Token 部分支持",
    note: "Token 取决于 Claude Code telemetry 字段，AgentOTel 会自动归一化常见 token 字段。",
    codeId: "code-claude-code",
    code: (agent = selectedAgent()) => `export CLAUDE_CODE_ENABLE_TELEMETRY=1
export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}"
export OTEL_RESOURCE_ATTRIBUTES="service.name=claude-code,agent.name=${selectedAgentName()}"`
  },
  codex: { name: "Codex", service: "codex", command: 'codex "your task"', badge: "Token 不支持", note: "该方式记录一次 Agent 运行的开始/结束、时长、状态。默认不包含内部 LLM token 和 tool span。" },
  gemini: { name: "Gemini CLI", service: "gemini-cli", command: 'gemini -p "your task"', badge: "Token 不支持", note: "该方式记录一次 Agent 运行的开始/结束、时长、状态。默认不包含内部 LLM token 和 tool span。" },
  opencode: { name: "opencode", service: "opencode", command: 'opencode run "your task"', badge: "Token 不支持", note: "该方式记录一次 Agent 运行的开始/结束、时长、状态。默认不包含内部 LLM token 和 tool span。" },
  "qwen-code": { name: "Qwen Code", service: "qwen-code", command: 'qwen "your task"', badge: "Token 不支持", note: "该方式记录一次 Agent 运行的开始/结束、时长、状态。默认不包含内部 LLM token 和 tool span。" },
  "openai-agents": { name: "OpenAI Agents SDK", badge: "Token 支持", note: "使用 OpenTelemetry exporter，并透传 Authorization header。", codeId: "code-openai-agents", code: (agent = selectedAgent()) => `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}"
export OTEL_RESOURCE_ATTRIBUTES="service.name=openai-agents,agent.name=${selectedAgentName()}"
# 在 OpenAI Agents SDK 中启用 tracing / processor` },
  langgraph: { name: "LangGraph / LangChain", badge: "Token 部分支持", note: "Token 取决于回调/模型 provider 返回字段，AgentOTel 会归一化常见字段。", codeId: "code-langgraph", code: (agent = selectedAgent()) => `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}"
export OTEL_RESOURCE_ATTRIBUTES="service.name=langgraph,agent.name=${selectedAgentName()}"
# 配置 LangSmith / OTel callback 或自定义 span processor` },
  llamaindex: { name: "LlamaIndex", badge: "Token 部分支持", note: "Token 取决于 LlamaIndex callback 与模型返回字段。", codeId: "code-llamaindex", code: (agent = selectedAgent()) => `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}"
export OTEL_RESOURCE_ATTRIBUTES="service.name=llamaindex,agent.name=${selectedAgentName()}"
# 配置 LlamaIndex instrumentation / callback handler` },
  "crewai-autogen": { name: "CrewAI / AutoGen", badge: "Token 取决于 wrapper", note: "wrapper 可记录运行级 span；内部 token 取决于你注入的模型回调。", codeId: "code-crewai-autogen", code: (agent = selectedAgent()) => `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}" \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}" \
OTEL_RESOURCE_ATTRIBUTES="service.name=crewai,agent.name=${selectedAgentName()}" \
otel-cli exec --service crewai --name "agent run" -- python run_agents.py` }
};
function cliWrapperCode(config, agent = selectedAgent()) {
  return `OTEL_RESOURCE_ATTRIBUTES="service.name=${config.service},agent.name=${selectedAgentName()}" \
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${state.otlpEndpoint}" \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${agentApiKeyValue(agent, { forCopy: true })}" \
otel-cli exec --service ${config.service} --name "${config.service} run" -- ${config.command}`;
}
function renderIntegrationPanel() {
  const panel = $("integration-panel-dynamic");
  if (!panel) return;
  const key = activeIntegration();
  const config = INTEGRATIONS[key] || INTEGRATIONS.hermes;
  const agent = selectedAgent();
  const codeId = config.codeId || `code-${key}-wrapper`;
  const code = config.code ? config.code(agent) : cliWrapperCode(config, agent);
  const restartCodeId = `code-${key}-restart`;
  const verifyCodeId = `code-${key}-verify`;
  const restartCode = config.restart ? config.restart() : `# 重新运行一次 ${config.name} 任务，让新的 OTEL 环境变量生效
${config.command || "your-agent-command \"your task\""}`;
  const verifyCode = `# 运行任务后回到 AgentOTel 控制台
# 打开「总览 / 会话 / 任务」确认出现新的 Session、Trace 和 Span`;
  panel.innerHTML = `
    <div class="steps-grid">
      <article class="step-card">
        <div class="step-number">1</div>
        <div class="step-content">
          <p class="eyebrow">配置</p>
          <h3>修改配置</h3>
          <p>当前选择：${escapeHtml(selectedAgentName())}。下面配置已填入该 Agent 的 API Key。</p>
          <div class="code-block">
            <button class="copy-button" type="button" data-dynamic-copy-target="${escapeHtml(codeId)}">复制</button>
            <pre id="${escapeHtml(codeId)}"><code>${escapeHtml(code)}</code></pre>
          </div>
        </div>
      </article>
      <article class="step-card">
        <div class="step-number">2</div>
        <div class="step-content">
          <p class="eyebrow">重启</p>
          <h3>重启 Agent / Gateway</h3>
          <p>配置写入后需要重启，让 Agent 重新加载 OTEL 配置。</p>
          <div class="code-block">
            <button class="copy-button" type="button" data-dynamic-copy-target="${escapeHtml(restartCodeId)}">复制</button>
            <pre id="${escapeHtml(restartCodeId)}"><code>${escapeHtml(restartCode)}</code></pre>
          </div>
        </div>
      </article>
      <article class="step-card">
        <div class="step-number">3</div>
        <div class="step-content">
          <p class="eyebrow">验证</p>
          <h3>运行一次任务并检查数据</h3>
          <p>执行一次真实任务，然后回到控制台确认是否出现新的 Session、Trace 和 Span。</p>
          <div class="code-block">
            <button class="copy-button" type="button" data-dynamic-copy-target="${escapeHtml(verifyCodeId)}">复制</button>
            <pre id="${escapeHtml(verifyCodeId)}"><code>${escapeHtml(verifyCode)}</code></pre>
          </div>
        </div>
      </article>
    </div>`;
}
function activeIntegration() {
  return document.querySelector("[data-integration-tab].active")?.dataset.integrationTab || "hermes";
}

function setActiveIntegration(integration = "hermes") {
  const normalized = Object.prototype.hasOwnProperty.call(INTEGRATIONS, integration) ? integration : "hermes";
  document.querySelectorAll("[data-integration-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.integrationTab === normalized);
  });
  renderIntegrationPanel();
  return normalized;
}

function parseRoute(rawHash = "") {
  let raw = rawHash.replace("#", "");
  // Support sessions?q=xxx and traces?q=xxx
  if (raw.startsWith("sessions")) return { page: "sessions", integration: activeIntegration() };
  if (raw.startsWith("traces")) return { page: "traces", integration: activeIntegration() };
  if (raw === "overview") return { page: "overview", integration: activeIntegration() };
  if (raw === "sessions") return { page: "sessions", integration: activeIntegration() };
  if (raw === "traces") return { page: "traces", integration: activeIntegration() };
  if (raw === "settings") return { page: "settings", integration: activeIntegration() };
  if (raw.startsWith("integrations/")) return { page: "integrations", integration: raw.split("/")[1] || "hermes" };
  if (raw === "integrations") return { page: "integrations", integration: "hermes" };
  if (!raw) return { page: "overview", integration: activeIntegration() };
  return { page: "overview", integration: activeIntegration() };
}

function setActivePage(page, integration) {
  const route = parseRoute(page || "");
  const normalized = route.page === "overview" ? "overview" : route.page === "sessions" ? "sessions" : route.page === "traces" ? "traces" : route.page === "settings" ? "settings" : "integrations";
  const nextIntegration = normalized === "integrations" ? setActiveIntegration(integration || route.integration) : activeIntegration();
  $("integrations-page")?.toggleAttribute("hidden", normalized !== "integrations");
  $("overview-page")?.toggleAttribute("hidden", normalized !== "overview");
  $("sessions-page")?.toggleAttribute("hidden", normalized !== "sessions");
  $("traces-page")?.toggleAttribute("hidden", normalized !== "traces");
  $("settings-page")?.toggleAttribute("hidden", normalized !== "settings");
  document.querySelectorAll("[data-page]").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === normalized);
  });
  // Keep existing query params if present (sessions?q=xxx / traces?q=xxx)
  let nextHash;
  if (normalized === "overview") {
    nextHash = "#overview";
  } else if (normalized === "sessions" && window.location.hash.startsWith("#sessions?q=")) {
    nextHash = window.location.hash;
  } else if (normalized === "traces" && window.location.hash.startsWith("#traces?q=")) {
    nextHash = window.location.hash;
  } else {
    nextHash = normalized === "overview" ? "#overview" : normalized === "sessions" ? "#sessions" : normalized === "traces" ? "#traces" : normalized === "settings" ? "#settings" : `#integrations/${nextIntegration}`;
  }
  if (window.location.hash !== nextHash) {
    window.history.replaceState(null, "", `${window.location.pathname}${nextHash}`);
  }
  if (normalized === "sessions" && !state.loadingSessionPage && !state.sessionPageSessions.length) {
    loadSessionPage();
  }
  if (normalized === "traces" && !state.loadingTracePage && !state.tracePageTraces.length) {
    loadTracePage();
  }
}

async function copyText(value, button) {
  if (!value) return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
    else {
      const input = document.createElement("textarea");
      input.value = value;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    if (button) {
      const old = button.textContent;
      button.textContent = "已复制";
      button.classList.add("copied");
      setTimeout(() => { button.textContent = old; button.classList.remove("copied"); }, 900);
    }
  } catch (_) {
    /* 剪贴板失败不应阻塞控制台使用。 */
  }
}

function integrationCopyValue(targetId) {
  const target = $(targetId);
  const value = target?.innerText || target?.textContent || "";
  if (!targetId || String(targetId).startsWith("code-")) {
    const agent = selectedAgent();
    if (agent && (state.agentKeyPlaintexts[agent.id] || agent.apiKey?.plaintext || sessionStorage.getItem(agentPlaintextStorageKey(agent.id)))) return value;
    if (state.apiKeyPlaintext || sessionStorage.getItem(STORAGE.apiKeyPlaintext)) return value;
    return value.replace(/Bearer\s+[^"\s]+/g, "Bearer <请先在设置生成当前 Agent API Key>");
  }
  return value;
}

function bindEvents() {
  $("send-phone-code")?.addEventListener("click", async () => {
    try { await sendPhoneCode(); } catch (error) { authMessage(error instanceof Error ? error.message : String(error), "error"); }
  });
  $("phone-login-button")?.addEventListener("click", async () => {
    try { await phoneLogin(); } catch (error) { authMessage(error instanceof Error ? error.message : String(error), "error"); }
  });
  $("logout-button")?.addEventListener("click", logout);
  $("agent-menu-trigger")?.addEventListener("click", (event) => {
    event.stopPropagation();
    state.agentMenuOpen = !state.agentMenuOpen;
    renderAgentSelector();
  });
  $("agent-menu")?.addEventListener("click", async (event) => {
    event.stopPropagation();
    const selectButton = event.target.closest("[data-agent-menu-select]");
    const newButton = event.target.closest("#agent-menu-new");
    try {
      if (selectButton) {
        state.selectedAgentId = selectButton.dataset.agentMenuSelect || "";
        if (state.selectedAgentId) localStorage.setItem("agentotel_selected_agent_id", state.selectedAgentId);
        state.agentMenuOpen = false;
        await refreshForCurrentAgent();
      } else if (newButton) {
        await loadAgents();
        state.agentMenuOpen = false;
        setActivePage("settings");
        setTimeout(() => $("agent-name-input")?.focus(), 80);
      }
    } catch (error) {
      state.agentsError = error instanceof Error ? error.message : String(error);
      renderAgents();
    }
  });
  document.addEventListener("click", () => {
    let changed = false;
    if (state.agentMenuOpen) { state.agentMenuOpen = false; changed = true; }
    if (state.timeRange.menuOpen) { state.timeRange.menuOpen = false; changed = true; }
    if (!changed) return;
    renderAgentSelector();
    syncTimeRangeControls();
  });
  $("create-agent")?.addEventListener("click", async () => {
    try { await createAgent(); } catch (error) { state.agentsError = error instanceof Error ? error.message : String(error); renderAgents(); }
  });
  $("agent-list")?.addEventListener("click", async (event) => {
    const selectButton = event.target.closest("[data-agent-select]");
    const renameButton = event.target.closest("[data-agent-rename]");
    const deleteButton = event.target.closest("[data-agent-delete]");
    try {
      if (selectButton) {
        state.selectedAgentId = selectButton.dataset.agentSelect || "";
        if (state.selectedAgentId) localStorage.setItem("agentotel_selected_agent_id", state.selectedAgentId);
        await refreshForCurrentAgent();
      } else if (renameButton) {
        const agentId = renameButton.dataset.agentRename || "";
        const input = document.querySelector(`[data-agent-name-input="${CSS.escape(agentId)}"]`);
        await renameAgent(agentId, input?.value || "");
      } else if (deleteButton) {
        const agentId = deleteButton.dataset.agentDelete || "";
        if (window.confirm("删除后该 Agent 的 API Key 会失效，历史数据保留。继续？")) await deleteAgent(agentId);
      }
    } catch (error) {
      state.agentsError = error instanceof Error ? error.message : String(error);
      renderAgents();
    }
  });
  $("create-api-key")?.addEventListener("click", async () => {
    try { await createApiKey(); } catch (error) { state.apiKeysError = error instanceof Error ? error.message : String(error); renderApiKeys(); }
  });
  $("revoke-api-key")?.addEventListener("click", async () => {
    try { await revokeApiKey(); } catch (error) { state.apiKeysError = error instanceof Error ? error.message : String(error); renderApiKeys(); }
  });
  $("new-api-key-once")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-once-api-key-copy]");
    if (!button) return;
    const target = $(button.dataset.onceApiKeyCopy);
    copyText(target?.innerText || target?.textContent || "", button);
  });
  $("integration-panel-dynamic")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-dynamic-copy-target]");
    if (!button) return;
    const targetId = button.dataset.dynamicCopyTarget;
    copyText(integrationCopyValue(targetId), button);
  });
  $("refresh-button")?.addEventListener("click", () => loadSessions({ silent: false }));
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.page));
  });
  document.querySelectorAll("[data-integration-tab]").forEach((button) => {
    button.addEventListener("click", () => setActivePage("integrations", button.dataset.integrationTab));
  });
  document.querySelectorAll("[data-page-link]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.pageLink));
  });
  window.addEventListener("hashchange", () => {
    setActivePage(window.location.hash);
  });
  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(button.dataset.copyTarget);
      copyText(target?.innerText || target?.textContent || "", button);
    });
  });
  document.querySelectorAll("[data-top-session-sort]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextSort = button.dataset.topSessionSort || "tokens";
      if (nextSort === state.topSessionsSort) return;
      state.topSessionsSort = nextSort;
      state.topSessions = [];
      renderAll();
      await loadTopSessions();
      renderAll();
    });
  });
  document.querySelectorAll("[data-top-trace-sort]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextSort = button.dataset.topTraceSort || "tokens";
      if (nextSort === state.topTracesSort) return;
      state.topTracesSort = nextSort;
      state.topTraces = [];
      renderAll();
      await loadTopTraces();
      renderAll();
    });
  });
  document.querySelectorAll("[data-session-page-sort]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextSort = button.dataset.sessionPageSort || "latest";
      if (nextSort === state.sessionPageSort && state.sessionPageStatusFilter !== "errors") return;
      state.sessionPageSort = nextSort;
      state.sessionPageStatusFilter = nextSort === "errors" ? "errors" : "all";
      if (state.sessionPageStatusFilter === "all") state.sessionPageSort = nextSort;
      state.sessionPagePage = 1;
      state.sessionPageSessions = [];
      state.sessionPageHasMore = false;
      await loadSessionPage();
    });
  });
  document.querySelectorAll("[data-trace-page-sort]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextSort = button.dataset.tracePageSort || "latest";
      if (nextSort === state.tracePageSort && state.tracePageStatusFilter !== "errors") return;
      state.tracePageSort = nextSort;
      state.tracePageStatusFilter = nextSort === "errors" ? "errors" : "all";
      state.tracePagePage = 1;
      state.tracePageTraces = [];
      state.tracePageHasMore = false;
      await loadTracePage();
    });
  });
  $("session-page-search")?.addEventListener("input", debounce(async (event) => {
    state.sessionPageQuery = event.target.value || "";
    // Update hash to reflect current query
    if (state.sessionPageQuery.trim()) {
      window.history.replaceState(null, "", `${window.location.pathname}#sessions?q=${encodeURIComponent(state.sessionPageQuery.trim())}`);
    } else {
      window.history.replaceState(null, "", `${window.location.pathname}#sessions`);
    }
    state.sessionPagePage = 1;
    state.sessionPageSessions = [];
    state.sessionPageHasMore = false;
    await loadSessionPage();
  }, 260));
  $("trace-page-search")?.addEventListener("input", debounce(async (event) => {
    state.tracePageQuery = event.target.value || "";
    // Update hash to reflect current query
    if (state.tracePageQuery.trim()) {
      window.history.replaceState(null, "", `${window.location.pathname}#traces?q=${encodeURIComponent(state.tracePageQuery.trim())}`);
    } else {
      window.history.replaceState(null, "", `${window.location.pathname}#traces`);
    }
    state.tracePagePage = 1;
    state.tracePageTraces = [];
    state.tracePageHasMore = false;
    await loadTracePage();
  }, 260));

  document.querySelectorAll("[data-session-page-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextStatus = button.dataset.sessionPageStatus || "all";
      if (nextStatus === state.sessionPageStatusFilter) return;
      state.sessionPageStatusFilter = nextStatus;
      if (nextStatus === "errors") state.sessionPageSort = "errors";
      state.sessionPagePage = 1;
      state.sessionPageSessions = [];
      state.sessionPageHasMore = false;
      await loadSessionPage();
    });
  });
  document.querySelectorAll("[data-trace-page-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextStatus = button.dataset.tracePageStatus || "all";
      if (nextStatus === state.tracePageStatusFilter) return;
      state.tracePageStatusFilter = nextStatus;
      if (nextStatus === "errors") state.tracePageSort = "errors";
      state.tracePagePage = 1;
      state.tracePageTraces = [];
      state.tracePageHasMore = false;
      await loadTracePage();
    });
  });
  $("session-page-prev")?.addEventListener("click", async () => {
    if (state.sessionPagePage <= 1 || state.loadingSessionPage) return;
    state.sessionPagePage -= 1;
    state.sessionPageSessions = [];
    await loadSessionPage();
  });
  $("session-page-next")?.addEventListener("click", async () => {
    if (!state.sessionPageHasMore || state.loadingSessionPage) return;
    state.sessionPagePage += 1;
    state.sessionPageSessions = [];
    await loadSessionPage();
  });
  $("trace-page-prev")?.addEventListener("click", async () => {
    if (state.tracePagePage <= 1 || state.loadingTracePage) return;
    state.tracePagePage -= 1;
    state.tracePageTraces = [];
    await loadTracePage();
  });
  $("trace-page-next")?.addEventListener("click", async () => {
    if (!state.tracePageHasMore || state.loadingTracePage) return;
    state.tracePagePage += 1;
    state.tracePageTraces = [];
    await loadTracePage();
  });
  $("session-page-list")?.addEventListener("click", async (event) => {
    const traceRow = event.target.closest("[data-session-timeline-trace-id]");
    if (traceRow) {
      event.preventDefault();
      event.stopPropagation();
      const traceId = traceRow.dataset.sessionTimelineTraceId;
      // Jump to traces page with search and auto-expand
      setTimeout(() => {
        window.location.hash = `traces?q=${encodeURIComponent(traceId)}`;
      }, 0);
      return;
    }
    const row = event.target.closest("[data-session-id]");
    if (!row) return;
    const sessionId = row.dataset.sessionId;
    if (sessionId === state.selectedSessionId) {
      state.selectedSessionId = null;
      state.selectedTraceId = null;
      state.selectedTraceDetail = null;
      state.traces = [];
      renderAll();
      return;
    }
    state.selectedSessionId = sessionId;
    state.selectedTraceId = null;
    state.selectedTraceDetail = null;
    state.traces = [];
    await loadTracesForSelected({ autoSelectTrace: false });
  });
  $("trace-page-list")?.addEventListener("click", async (event) => {
    const spanRow = event.target.closest("[data-trace-span-id]");
    if (spanRow) {
      event.stopPropagation();
      state.selectedTraceSpanId = spanRow.dataset.traceSpanId;
      renderAll();
      // 1. scroll detail container into view
      const expandContainer = spanRow.closest(".trace-expand-detail");
      if (expandContainer) {
        expandContainer.scrollIntoView({ behavior: "smooth", block: "start" });
        // 2. scroll span detail block to top of its container
        requestAnimationFrame(() => {
          const detailAside = expandContainer.querySelector(".trace-span-detail");
          if (detailAside) detailAside.scrollTop = 0;
        });
      }
      return;
    }
    const row = event.target.closest("[data-trace-page-id]");
    if (!row) return;
    const sessionId = row.dataset.sessionId;
    const traceId = row.dataset.tracePageId;
    if (traceId === state.selectedTraceId) {
      state.selectedTraceId = null;
      state.selectedTraceDetail = null;
      state.selectedTraceSpanId = null;
      renderAll();
      return;
    }
    if (sessionId && sessionId !== state.selectedSessionId) {
      state.selectedSessionId = sessionId;
      state.selectedTraceDetail = null;
      state.selectedTraceSpanId = null;
      await loadTracesForSelected({ autoSelectTrace: false });
    }
    state.selectedTraceSpanId = null;
    await selectTrace(traceId);
    // after render, scroll expanded trace into view
    requestAnimationFrame(() => {
      if (row && row.closest(".trace-expand-card")) {
        const container = row.closest(".trace-expand-card")?.querySelector(".trace-expand-detail");
        container?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
  $("time-range-trigger")?.addEventListener("click", (event) => {
    event.stopPropagation();
    state.agentMenuOpen = false;
    state.timeRange.menuOpen = !state.timeRange.menuOpen;
    renderAgentSelector();
    syncTimeRangeControls();
  });
  $("time-range-menu")?.addEventListener("click", async (event) => {
    event.stopPropagation();
    const navButton = event.target.closest("#calendar-prev, #calendar-next");
    if (navButton) {
      const month = state.timeRange.calendarMonth instanceof Date ? state.timeRange.calendarMonth : new Date();
      state.timeRange.calendarMonth = new Date(month.getFullYear(), month.getMonth() + (navButton.id === "calendar-prev" ? -1 : 1), 1);
      renderCalendarGrid();
      return;
    }
    const presetButton = event.target.closest("[data-time-preset]");
    if (!presetButton) return;
    const nextPreset = presetButton.dataset.timePreset || "24h";
    state.timeRange.preset = nextPreset;
    if (nextPreset === "custom") {
      state.timeRange.picking = "from";
      const range = currentTimeRange();
      state.timeRange.customFrom = range.from;
      state.timeRange.customTo = range.to;
      state.timeRange.calendarMonth = new Date(range.from.getFullYear(), range.from.getMonth(), 1);
      const fromInput = $("custom-from");
      const toInput = $("custom-to");
      if (fromInput && !fromInput.value) fromInput.value = toDatetimeLocal(range.from);
      if (toInput && !toInput.value) toInput.value = toDatetimeLocal(range.to);
      syncTimeRangeControls();
      return;
    }
    state.timeRange.menuOpen = false;
    await applyTimeRangeChange();
  });
  $("apply-time-range")?.addEventListener("click", async (event) => {
    event.stopPropagation();
    state.timeRange.menuOpen = false;
    await applyCustomTimeRange();
  });
  $("custom-from")?.addEventListener("input", syncCustomDatesFromInputs);
  $("custom-to")?.addEventListener("input", syncCustomDatesFromInputs);
  document.querySelectorAll("[data-status-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.statusFilter = button.dataset.statusFilter || "all";
      document.querySelectorAll("[data-status-filter]").forEach((b) => b.classList.toggle("active", b === button));
      renderAll();
    });
  });
  $("top-sessions-list")?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-session-id]");
    if (row) selectSession(row.dataset.sessionId);
  });
  $("top-traces-list")?.addEventListener("click", async (event) => {
    const row = event.target.closest("[data-top-trace-id]");
    if (!row) return;
    const sessionId = row.dataset.sessionId;
    const traceId = row.dataset.topTraceId;
    if (sessionId && sessionId !== state.selectedSessionId) {
      state.selectedSessionId = sessionId;
      state.selectedTraceId = null;
      state.selectedTraceDetail = null;
      state.selectedTraceSpanId = null;
      await loadTracesForSelected({ autoSelectTrace: false });
    }
    await selectTrace(traceId);
  });
  $("sessions-list")?.addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy]");
    if (copy) { event.stopPropagation(); copyText(copy.dataset.copy, copy); return; }
    const row = event.target.closest("[data-session-id]");
    if (row) selectSession(row.dataset.sessionId);
  });
  // Top sessions / top traces click to jump
  // Use capture phase to get event BEFORE other handlers (session-page-list also listens [data-session-id])
  document.addEventListener("click", (event) => {
    const sessionRow = event.target.closest("[data-session-id]");
    if (sessionRow && sessionRow.closest("#top-sessions-list")) {
      event.preventDefault();
      event.stopPropagation();
      const sessionId = sessionRow.dataset.sessionId;
      // Jump via hash change, let hashchange handle the rest
      setTimeout(() => {
        window.location.hash = `sessions?q=${encodeURIComponent(sessionId)}`;
      }, 0);
      return;
    }
    const traceRow = event.target.closest("[data-trace-id]");
    if (traceRow && traceRow.closest("#top-traces-list")) {
      event.preventDefault();
      event.stopPropagation();
      const traceId = traceRow.dataset.traceId;
      setTimeout(() => {
        window.location.hash = `traces?q=${encodeURIComponent(traceId)}`;
      }, 0);
      return;
    }
  }, true);

  $("copy-current-trace")?.addEventListener("click", (event) => copyText(state.selectedTraceId, event.currentTarget));
}

async function bootstrapAuthenticatedApp() {
  setAuthenticatedShell(true);
  await Promise.all([loadCurrentUser(), loadProjects()]);
  renderAll();
  await Promise.all([loadApiKeys(), loadAgents(), loadSessions({ silent: false })]);
}
async function boot() {
  bindEvents();
  if (!authToken()) {
    setAuthenticatedShell(false);
    return;
  }
  const initialHash = window.location.hash;
  const initialPage = initialHash || (window.location.pathname.includes("overview") ? "#overview" : window.location.pathname.includes("claude") ? "#integrations/claude" : "#overview");
  setActivePage(initialPage);
  renderAll();
  try {
    await bootstrapAuthenticatedApp();
  } catch (error) {
    localStorage.removeItem(STORAGE.token);
    setAuthenticatedShell(false);
    authMessage(error instanceof Error ? error.message : String(error), "error");
  }
}
boot();
