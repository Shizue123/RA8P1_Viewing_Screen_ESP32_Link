const $ = (id) => document.getElementById(id);
const REMEMBERED_ACCOUNTS_KEY = "vela.rememberedAccounts";
const WIFI_PROFILES_KEY_PREFIX = "vela.wifiProfiles";
const MODEL_PRESETS = {
  qwen: {
    label: "千问 DashScope",
    provider: "qwen",
    model: "qwen-plus",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  gemini: {
    label: "Gemini",
    provider: "gemini",
    model: "gemini-2.5-flash",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
  },
  xiaomi: {
    label: "小米 MiMo",
    provider: "xiaomi",
    model: "mimo",
    base_url: "https://你的网关域名/v1",
  },
  custom: {
    label: "自定义模型",
    provider: "custom",
    model: "",
    base_url: "https://api.example.com/v1",
  },
};

if (window.location.search) {
  window.history.replaceState({}, document.title, `${window.location.pathname}${window.location.hash}`);
}

const state = {
  user: null,
  csrf: "",
  context: null,
  devices: [],
  activeDeviceId: localStorage.getItem("vela.activeDeviceId") || "",
  sending: false,
  creatingConversation: false,
  pendingSession: null,
  conversations: [],
  activeConversationId: "",
  conversationRequest: 0,
  conversationAbortController: null,
  contextRefreshTimer: null,
  modelConfig: null,
  messageCache: new Map(),
  searchQuery: "",
  provisionPort: null,
  provisionReader: null,
  provisionReadLoopActive: false,
  provisionBuffer: "",
  pendingWifiPassword: "",
};

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  if (state.csrf && !["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(`/api${path}`, { ...options, method, headers });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function rememberedAccounts() {
  try {
    const value = JSON.parse(localStorage.getItem(REMEMBERED_ACCOUNTS_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}

function rememberAccount(username) {
  const accounts = [username, ...rememberedAccounts().filter((item) => item.toLowerCase() !== username.toLowerCase())];
  localStorage.setItem(REMEMBERED_ACCOUNTS_KEY, JSON.stringify(accounts.slice(0, 8)));
}

function wifiProfilesKey() {
  const username = state.user?.username || state.pendingSession?.user?.username || "anonymous";
  return `${WIFI_PROFILES_KEY_PREFIX}.${username}`;
}

function savedWifiProfiles() {
  try {
    const value = JSON.parse(localStorage.getItem(wifiProfilesKey()) || "[]");
    return Array.isArray(value)
      ? value.filter((item) => item && typeof item.ssid === "string").slice(0, 12)
      : [];
  } catch {
    return [];
  }
}

function saveWifiProfile(ssid, password) {
  const cleanSsid = String(ssid || "").trim();
  if (!cleanSsid) return;
  const profiles = savedWifiProfiles().filter((item) => item.ssid !== cleanSsid);
  profiles.unshift({
    ssid: cleanSsid,
    password: String(password || ""),
    updated_at: Date.now(),
  });
  localStorage.setItem(wifiProfilesKey(), JSON.stringify(profiles.slice(0, 12)));
  renderSavedWifiProfiles();
}

function deleteWifiProfile(ssid) {
  const profiles = savedWifiProfiles().filter((item) => item.ssid !== ssid);
  localStorage.setItem(wifiProfilesKey(), JSON.stringify(profiles));
  renderSavedWifiProfiles();
}

function renderAccountChooser() {
  const current = state.pendingSession?.user?.username || "";
  const accounts = rememberedAccounts().filter((username) => username.toLowerCase() !== current.toLowerCase());
  $("rememberedAccounts").innerHTML = accounts.map((username) => `
    <button class="remembered-account" type="button" data-username="${escapeHtml(username)}">
      <span class="account-avatar">${escapeHtml(username.slice(0, 1).toUpperCase())}</span>
      <span><strong>${escapeHtml(username)}</strong><small>需要输入密码</small></span>
      <b>选择</b>
    </button>`).join("");
  document.querySelectorAll(".remembered-account").forEach((button) => {
    button.addEventListener("click", () => {
      $("usernameInput").value = button.dataset.username || "";
      $("passwordInput").focus();
    });
  });
  $("continueSessionButton").hidden = !state.pendingSession;
  if (state.pendingSession) {
    $("sessionUsername").textContent = current;
    $("sessionInitial").textContent = current.slice(0, 1).toUpperCase();
  }
}

function showAuth(bootstrapRequired = false) {
  $("appView").hidden = true;
  $("authView").hidden = false;
  $("authTitle").textContent = bootstrapRequired ? "创建管理员" : "选择账户";
  $("authHint").textContent = bootstrapRequired ? "完成初始账户设置。" : "继续使用已保存的账户，或登录其他账户。";
  $("authSubmit").textContent = bootstrapRequired ? "创建并进入" : "登录";
  $("authForm").dataset.mode = bootstrapRequired ? "bootstrap" : "login";
  $("passwordInput").autocomplete = bootstrapRequired ? "new-password" : "current-password";
  renderAccountChooser();
}

async function inspectSession({ enterApp = false } = {}) {
  const session = await api("/auth/session");
  if (!session.authenticated) {
    state.pendingSession = null;
    showAuth(session.bootstrap_required);
    return;
  }
  state.pendingSession = session;
  rememberAccount(session.user.username);
  if (enterApp) await enterWorkspace(session);
  else showAuth(false);
}

async function enterWorkspace(session) {
  state.user = session.user;
  state.csrf = session.csrf_token;
  state.pendingSession = session;
  $("appView").hidden = true;
  renderUser();
  await Promise.all([loadContext(), loadConversations()]);
  if (state.user.role === "admin") await loadUsers();
  startContextRefresh();
  $("authView").hidden = true;
  $("appView").hidden = false;
}

function renderUser() {
  const { username, role } = state.user;
  $("railUsername").textContent = username;
  $("railRole").textContent = role;
  $("railUserInitial").textContent = username.slice(0, 1).toUpperCase();
  $("accountName").textContent = username;
  $("accountRole").textContent = role === "admin" ? "管理员" : "成员";
  $("userAdminCard").hidden = role !== "admin";
}

function pickPreferredDevice(devices) {
  const candidates = (devices || []).filter((device) => device?.device_id && device.device_id !== "ra8p1_demo_001");
  if (!candidates.length) return null;
  return candidates
    .slice()
    .sort((left, right) => {
      const onlineDelta = Number(Boolean(right?.online)) - Number(Boolean(left?.online));
      if (onlineDelta !== 0) return onlineDelta;
      const seenDelta = Number(right?.last_seen || 0) - Number(left?.last_seen || 0);
      if (seenDelta !== 0) return seenDelta;
      return String(left?.device_id || "").localeCompare(String(right?.device_id || ""));
    })[0];
}

async function loadContext({ silent = false } = {}) {
  try {
    const suffix = state.activeDeviceId ? `?device_id=${encodeURIComponent(state.activeDeviceId)}` : "";
    state.context = await api(`/web/context${suffix}`);
    state.devices = state.context.devices || state.devices || [];
    const currentDevice = state.devices.find((device) => device.device_id === state.context.device_id);
    const preferredDevice = pickPreferredDevice(state.devices);
    if (
      preferredDevice &&
      preferredDevice.device_id !== state.context.device_id &&
      currentDevice &&
      !currentDevice.online &&
      state.context.device_id === "ra8p1_demo_001"
    ) {
      state.activeDeviceId = preferredDevice.device_id;
      localStorage.setItem("vela.activeDeviceId", state.activeDeviceId);
      state.context = await api(`/web/context?device_id=${encodeURIComponent(state.activeDeviceId)}`);
      state.devices = state.context.devices || state.devices || [];
    }
    state.activeDeviceId = state.context.device_id || state.activeDeviceId;
    if (state.activeDeviceId) localStorage.setItem("vela.activeDeviceId", state.activeDeviceId);
    state.modelConfig = state.context.model_config || state.modelConfig;
    renderDeviceSwitcher();
    renderSignals(state.context.signal_topology);
    renderModelConfig();
  } catch (error) {
    if (state.activeDeviceId && String(error.message || "").includes("device not registered")) {
      localStorage.removeItem("vela.activeDeviceId");
      state.activeDeviceId = "";
      return loadContext({ silent });
    }
    if (!silent) throw error;
    renderDeviceSwitcher();
    renderSignals(state.context?.signal_topology, error);
  }
}

function renderDeviceSwitcher() {
  const select = $("deviceSelect");
  const dot = $("deviceStatusDot");
  if (!select || !dot) return;
  const devices = state.devices || [];
  if (!devices.length) {
    select.innerHTML = `<option>${escapeHtml(state.activeDeviceId || "无设备")}</option>`;
    select.disabled = true;
    dot.classList.toggle("online", false);
    dot.classList.toggle("offline", true);
    return;
  }
  select.disabled = false;
  select.innerHTML = devices.map((device) => {
    const label = `${device.label || device.device_id}${device.online ? " · 在线" : " · 离线"}`;
    return `<option value="${escapeHtml(device.device_id)}">${escapeHtml(label)}</option>`;
  }).join("");
  select.value = state.activeDeviceId || state.context?.device_id || devices[0].device_id;
  const active = devices.find((device) => device.device_id === select.value);
  dot.classList.toggle("online", Boolean(active?.online));
  dot.classList.toggle("offline", !active?.online);
  select.title = active
    ? `当前设备：${active.device_id}${active.ra8p1_uid ? ` / RA8P1 ${active.ra8p1_uid}` : ""}${active.esp32_mac ? ` / ESP32 ${active.esp32_mac}` : ""}`
    : "切换当前设备";
}

function startContextRefresh() {
  if (state.contextRefreshTimer) clearInterval(state.contextRefreshTimer);
  state.contextRefreshTimer = setInterval(() => {
    if (state.user) {
      loadContext({ silent: true }).catch(() => {});
      refreshActiveConversationMessages().catch(() => {});
    }
  }, 6000);
}

async function refreshActiveConversationMessages() {
  const conversationId = state.activeConversationId;
  if (!conversationId) return;
  const data = await api(`/web/conversations/${encodeURIComponent(conversationId)}/messages`);
  if (conversationId !== state.activeConversationId) return;
  const messages = data.messages || [];
  const cached = state.messageCache.get(conversationId) || [];
  const last = messages[messages.length - 1];
  const cachedLast = cached[cached.length - 1];
  if (
    messages.length === cached.length &&
    last?.id === cachedLast?.id &&
    last?.content === cachedLast?.content
  ) return;
  state.messageCache.set(conversationId, messages);
  displayMessages(messages);
  const list = await api("/web/conversations");
  state.conversations = list.conversations || [];
  renderConversations();
}

function renderSignals(topology, error = null) {
  const channels = topology?.channels || [];
  const deviceState = state.context?.device_state || {};
  const deviceOnline = Boolean(deviceState.online);
  const ageText = deviceState.age_sec === null || deviceState.age_sec === undefined
    ? "等待云端设备上报"
    : `${deviceOnline ? "最近上报" : "离线"} ${escapeHtml(formatDuration(deviceState.age_sec))}前`;
  const timeAlignment = deviceState.time_alignment || {};
  const timeText = timeAlignment.device_time
    ? `设备时间 ${escapeHtml(timeAlignment.device_time)} · 与 Web 偏差 ${escapeHtml(String(timeAlignment.skew_sec))} 秒${timeAlignment.aligned ? " · 已对齐" : " · 待校时"}`
    : "等待设备上报完整年月日时间";
  const summary = `
    <article class="signal-overview">
      <div><span class="status-dot-mini ${deviceOnline ? "online" : "offline"}"></span><strong>${escapeHtml(state.context?.device_id || topology?.device_id || "ra8p1_demo_001")}</strong></div>
      <span>${ageText}</span>
      <span>${escapeHtml((deviceState.channels || []).join(" / ") || "status / telemetry / event")}</span>
      <span>${timeText}</span>
    </article>`;
  const errorNote = error ? `<p class="signal-error">刷新失败：${escapeHtml(error.message)}</p>` : "";
  $("signalList").innerHTML = `${summary}${errorNote}${channels.map((channel) => {
    const stateInfo = channel.state || {};
    const endpoints = channel.hardware || [];
    const wires = (channel.signals || []).map((signal) => `
      <div class="signal-wire">
        <strong>${escapeHtml(signal.name)}</strong>
        <span>${escapeHtml(signal.direction)} · ${escapeHtml(signal.pin || "未指定引脚")}</span>
      </div>`).join("");
    return `
      <article class="signal-card">
        <div class="signal-head">
          <div>
            <p class="kicker">${escapeHtml(channel.protocol)}</p>
            <h3>${escapeHtml(channel.name)}</h3>
          </div>
          <div class="signal-status-stack">
            <span class="status-pill ${statusClass(stateInfo.status)}">${escapeHtml(statusLabel(stateInfo.status))}</span>
            <small>${escapeHtml(channelTopologyLabel(channel, endpoints.length))} · ${escapeHtml(sourceLabel(channel.source))}</small>
          </div>
        </div>
        <div class="signal-pair">${wires}</div>
        <div class="signal-diagnostics">
          <span>诊断 ${escapeHtml(stateInfo.diagnostic || "unknown")}</span>
          <span>模块 ${escapeHtml(moduleClassLabel(stateInfo.interpretation || "unknown"))}</span>
          <span>激活 ${escapeHtml(activationLabel(stateInfo.activation || "unknown"))}</span>
          <span>${stateInfo.last_seen ? `上报 ${escapeHtml(formatTimestamp(stateInfo.last_seen))}` : "尚无上报时间"}</span>
        </div>
        ${renderChannelStructureNote(channel, endpoints)}
        ${endpoints.length ? renderEndpointGroups(channel, endpoints) : `<p class="endpoint-note">等待真实设备状态。云端收到 RA8P1/ESP32 的 status 或 telemetry 后，这里会显示端点、能力和读数。</p>`}
      </article>`;
  }).join("")}`;
  attachModuleBindingActions();
}

function channelTopologyLabel(channel, endpointCount) {
  const protocol = String(channel?.protocol || "").toUpperCase();
  if (protocol === "I2C") return `1 条物理总线 · ${endpointCount} 个挂载端点`;
  return `1 个物理通道 · ${endpointCount} 个端点`;
}

function renderChannelStructureNote(channel, endpoints) {
  const protocol = String(channel?.protocol || "").toUpperCase();
  if (protocol !== "I2C" || endpoints.length <= 1) return "";
  return `<p class="signal-structure-note">${escapeHtml(channel.name)} 是 1 条共享 I2C 总线。下面列出的 ${String(endpoints.length)} 个卡片是挂在这条总线上的总线设备或模块，不是新增的独立物理口。</p>`;
}

function renderEndpointGroups(channel, endpoints) {
  const groups = endpointGroups(channel, endpoints);
  return groups.map((group) => `
    <section class="endpoint-section">
      <div class="endpoint-section-head">
        <strong>${escapeHtml(group.title)}</strong>
        <span>${escapeHtml(group.description)}</span>
      </div>
      <div class="endpoint-grid">${group.items.map(renderEndpoint).join("")}</div>
    </section>`).join("");
}

function endpointGroups(channel, endpoints) {
  const protocol = String(channel?.protocol || "").toUpperCase();
  if (protocol !== "I2C") {
    return [{
      title: "通道端点",
      description: "这个物理通道当前承载的端点。",
      items: endpoints,
    }];
  }
  const busDevices = endpoints.filter((endpoint) => endpointCategory(endpoint) === "bus");
  const modules = endpoints.filter((endpoint) => endpointCategory(endpoint) !== "bus");
  const groups = [];
  if (busDevices.length) {
    groups.push({
      title: "总线设备",
      description: "这类器件负责扩展或组织总线本身，例如 MUX。",
      items: busDevices,
    });
  }
  if (modules.length) {
    groups.push({
      title: "挂载模块",
      description: "这些是真正接在这条总线上的传感器或功能模块。",
      items: modules,
    });
  }
  return groups.length ? groups : [{
    title: "挂载端点",
    description: "这条总线当前上报的端点。",
    items: endpoints,
  }];
}

function renderEndpoint(endpoint) {
  const readings = endpoint.readings || [];
  const capabilities = endpoint.capabilities || [];
  const controlMethods = endpoint.control_methods || [];
  const metadata = endpoint.metadata || {};
  const category = endpointCategory(endpoint);
  const displayTitle = metadata.display_title || moduleClassLabel(metadata.module_class) || endpoint.hardware_type || "待识别模块";
  const displayModel = metadata.display_model || "";
  const headerSubline = [displayModel, endpoint.address || ""].filter(Boolean).join(" · ") || "direct-pin";
  const userBinding = metadata.user_binding && typeof metadata.user_binding === "object" ? metadata.user_binding : null;
  const subtitle = [
    confirmationStateLabel(metadata.confirmation_state || ""),
    userBinding?.model_label
      ? `已选 ${userBinding.model_label}`
      : (metadata.model_state ? `型号${modelStateLabel(metadata.model_state)}` : ""),
    userBinding
      ? `来源 ${bindingSourceLabel("user_confirmed")}`
      : (metadata.binding_source ? `来源 ${bindingSourceLabel(metadata.binding_source)}` : ""),
  ].filter(Boolean).join(" · ");
  return `
    <section class="endpoint-card ${category === "bus" ? "endpoint-card-bus" : ""}">
      <div class="endpoint-title">
        <div>
          <span class="endpoint-kind">${escapeHtml(endpointKindLabel(category))}</span>
          <strong>${escapeHtml(displayTitle)}</strong>
          <span>${escapeHtml(headerSubline)}</span>
        </div>
        <span class="status-pill ${statusClass(endpoint.status)}">${escapeHtml(statusLabel(endpoint.status))}</span>
      </div>
      ${subtitle ? `<p class="endpoint-meta">${escapeHtml(subtitle)}</p>` : ""}
      ${readings.length ? `<div class="reading-grid">${readings.map((item) => `<div class="reading-item"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(formatReading(item.value))}${escapeHtml(item.unit || "")}</strong></div>`).join("")}</div>` : ""}
      ${capabilities.length ? `<div class="capability-row">${capabilities.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      ${controlMethods.length ? `<div class="capability-row">${controlMethods.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      ${renderModuleBindingPanel(metadata)}
      ${renderEndpointMeta(metadata)}
    </section>`;
}

function endpointCategory(endpoint) {
  const metadata = endpoint?.metadata && typeof endpoint.metadata === "object" ? endpoint.metadata : {};
  const moduleClass = String(metadata.module_class || "").toLowerCase();
  const hardwareType = String(endpoint?.hardware_type || "").toUpperCase();
  if (moduleClass === "i2c.mux" || hardwareType.includes("MUX")) return "bus";
  return "module";
}

function endpointKindLabel(category) {
  return {
    bus: "总线设备",
    module: "挂载模块",
  }[category] || "端点";
}

function renderModuleBindingPanel(metadata) {
  if (!metadata || typeof metadata !== "object") return "";
  const options = Array.isArray(metadata.binding_options) ? metadata.binding_options : [];
  const userBinding = metadata.user_binding && typeof metadata.user_binding === "object" ? metadata.user_binding : null;
  const canConfirm = Boolean(metadata.can_confirm_module) && options.length > 0;
  if (!canConfirm && !userBinding && !metadata.needs_user_confirmation) return "";
  const token = bindingToken(metadata.port_id || "", metadata.binding_key || metadata.port_id || "");
  const selectedOption = userBinding?.option_id || options[0]?.id || "";
  const statusText = userBinding
    ? `当前按“${userBinding.title || "模块"}${userBinding.model_label ? ` / ${userBinding.model_label}` : ""}”使用`
    : metadata.needs_user_confirmation
      ? "需要确认当前接入模块"
      : "可更新当前模块配置";
  const hint = metadata.confirmation_hint || "";
  return `
    <div class="binding-panel ${metadata.needs_user_confirmation ? "pending" : ""}">
      <div class="binding-summary">
        <strong>${escapeHtml(statusText)}</strong>
        ${hint ? `<span>${escapeHtml(hint)}</span>` : ""}
      </div>
      ${canConfirm ? `
        <div class="binding-controls">
          <select data-binding-select="${escapeHtml(token)}">
            ${options.map((option) => {
              const parts = [option.title || "", option.model_label || ""].filter(Boolean);
              const label = parts.join(" / ") || option.id || "未命名模块";
              return `<option value="${escapeHtml(option.id || "")}" ${option.id === selectedOption ? "selected" : ""}>${escapeHtml(label)}</option>`;
            }).join("")}
          </select>
          <button
            class="secondary-action"
            type="button"
            data-confirm-module="${escapeHtml(token)}"
            data-port-id="${escapeHtml(metadata.port_id || "")}"
            data-binding-key="${escapeHtml(metadata.binding_key || metadata.port_id || "")}"
          >确认模块</button>
        </div>` : ""}
      <p class="binding-message" data-binding-message="${escapeHtml(token)}">${userBinding?.updated_at ? `最近确认 ${escapeHtml(formatTimestamp(userBinding.updated_at))}` : ""}</p>
    </div>`;
}

function bindingToken(portId, bindingKey) {
  return `${portId || ""}::${bindingKey || portId || ""}`;
}

function attachModuleBindingActions() {
  document.querySelectorAll("[data-confirm-module]").forEach((button) => {
    button.addEventListener("click", async () => {
      const panel = button.closest(".binding-panel");
      const select = panel?.querySelector(`[data-binding-select="${button.dataset.confirmModule || ""}"]`);
      const message = panel?.querySelector(`[data-binding-message="${button.dataset.confirmModule || ""}"]`);
      const optionId = select?.value || "";
      if (!optionId) return;
      button.disabled = true;
      if (message) message.textContent = "正在同步模块确认…";
      try {
        await api("/web/module-bindings/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            device_id: state.context?.device_id || state.activeDeviceId || "",
            port_id: button.dataset.portId || "",
            binding_key: button.dataset.bindingKey || "",
            option_id: optionId,
          }),
        });
        $("chatStatus").textContent = "模块确认已同步";
        await loadContext({ silent: true });
      } catch (error) {
        if (message) message.textContent = `同步失败：${error.message}`;
      } finally {
        button.disabled = false;
      }
    });
  });
}

function renderEndpointMeta(metadata) {
  if (!metadata || typeof metadata !== "object") return "";
  const parts = [];
  if (metadata.port_id) parts.push(`port=${metadata.port_id}`);
  if (metadata.physical_port) parts.push(`物理口=${metadata.physical_port}`);
  if (metadata.diag) parts.push(`diag=${metadata.diag}`);
  if (metadata.activation) parts.push(`激活=${activationLabel(metadata.activation)}`);
  if (metadata.crc_ok !== undefined && metadata.crc_ok !== null) parts.push(`crc=${metadata.crc_ok ? "ok" : "fail"}`);
  if (metadata.physical_detection === "not_supported_pwm_no_feedback") parts.push("physical=not detectable");
  if (metadata.device_key) parts.push(`key=${metadata.device_key}`);
  const execution = metadata.last_execution && typeof metadata.last_execution === "object" ? metadata.last_execution : null;
  if (execution?.state) parts.push(`exec=${execution.state}`);
  if (execution?.reason) parts.push(`reason=${execution.reason}`);
  if (!parts.length && metadata.source) parts.push(`source=${metadata.source}`);
  return parts.length ? `<p class="endpoint-meta">${escapeHtml(parts.join(" · "))}</p>` : "";
}

function sourceLabel(value) {
  return value === "device_state" ? "实时设备状态" : "配置基线";
}

function moduleClassLabel(value) {
  const key = String(value || "").toLowerCase();
  return {
    "env.th": "温湿度模块",
    "env.light": "光照模块",
    "env.multi": "环境传感模块",
    "i2c.mux": "I2C 复用器",
    "display.i2c": "I2C 显示模块",
    "storage.eeprom": "EEPROM 模块",
    motion_time: "运动/时序模块",
    actuator_channel: "执行通道",
    "act.servo": "舵机模块",
    "bridge.uart": "桥接模块",
    reserved: "预留口",
    none: "未接入",
    unknown: "待识别模块",
  }[key] || value || "待识别模块";
}

function activationLabel(value) {
  const key = String(value || "").toLowerCase();
  return {
    confirmed: "已确认",
    channel_active: "通道已激活",
    inactive: "未激活",
    reserved: "预留",
    unknown: "未知",
  }[key] || value || "未知";
}

function modelStateLabel(value) {
  const key = String(value || "").toLowerCase();
  return {
    exact: "已确认",
    candidate: "待确认",
    unknown: "未知",
    reserved: "预留",
    none: "未接入",
  }[key] || value || "未知";
}

function bindingSourceLabel(value) {
  const key = String(value || "").toLowerCase();
  return {
    auto_exact: "自动精确识别",
    auto_detected: "自动探测",
    user_confirmed: "用户确认",
    system_fixed: "系统固定",
    reserved: "预留",
    none: "无",
  }[key] || value || "未知";
}

function confirmationStateLabel(value) {
  const key = String(value || "").toLowerCase();
  return {
    user_confirmed: "用户已确认",
    auto_exact: "自动精确识别",
    pending: "等待确认",
    reported: "仅按板端上报展示",
  }[key] || "";
}

function statusClass(value) {
  const status = String(value || "").toLowerCase();
  if (["online", "present", "available", "execution_feedback", "detected", "degraded"].includes(status)) return "online";
  if (["offline", "error", "blocked"].includes(status)) return "offline";
  if (["configured", "channel_ready", "waiting", "unknown"].includes(status)) return "waiting";
  return "waiting";
}

function statusLabel(value) {
  return {
    online: "在线",
    present: "已识别",
    available: "可用",
    detected: "已检测",
    execution_feedback: "有执行反馈",
    degraded: "降级",
    channel_ready: "通道就绪",
    configured: "已配置",
    waiting: "等待",
    not_inserted: "未接入",
    empty: "空闲",
    offline: "离线",
    error: "异常",
    blocked: "阻塞",
    unknown: "未知",
  }[String(value || "unknown").toLowerCase()] || value || "未知";
}

function formatReading(value) {
  return typeof value === "number" ? value.toFixed(1).replace(/\.0$/, "") : value;
}

function formatTimestamp(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  const ms = numeric > 1000000000000 ? numeric : numeric * 1000;
  return new Date(ms).toLocaleString();
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "";
  if (value < 60) return `${Math.max(0, Math.floor(value))} 秒`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  return `${Math.floor(hours / 24)} 天`;
}

async function createConversation() {
  const data = await api("/web/conversations", { method: "POST" });
  return data.conversation;
}

async function loadConversations(preferredId = "") {
  const data = await api("/web/conversations");
  state.conversations = data.conversations || [];
  if (!state.conversations.length) state.conversations = [await createConversation()];
  const candidate = preferredId || state.activeConversationId;
  const active = state.conversations.find((item) => item.id === candidate) || state.conversations[0];
  renderConversations();
  await selectConversation(active.id, { force: true });
}

function renderConversations() {
  closeConversationMenu();
  const query = state.searchQuery.trim().toLocaleLowerCase();
  const conversations = state.conversations.filter((conversation) => (
    !query || conversation.title.toLocaleLowerCase().includes(query)
  ));
  $("conversationList").innerHTML = conversations.map((conversation) => `
    <div class="conversation-row ${conversation.id === state.activeConversationId ? "active" : ""}">
      <button class="conversation-item" type="button" data-conversation-id="${escapeHtml(conversation.id)}" title="${escapeHtml(conversation.title)}">${conversation.is_pinned ? "⌖ " : ""}${escapeHtml(conversation.title)}</button>
      <button class="conversation-delete" type="button" data-menu-conversation="${escapeHtml(conversation.id)}" aria-label="对话选项" title="对话选项">⋮</button>
    </div>`).join("");
  document.querySelectorAll(".conversation-item").forEach((button) => {
    button.addEventListener("click", async () => {
      await selectConversation(button.dataset.conversationId);
      selectView("chat");
      $("chatInput").focus();
    });
  });
  document.querySelectorAll(".conversation-delete").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openConversationMenu(button.dataset.menuConversation, button);
    });
  });
}

function closeConversationMenu() {
  document.querySelector(".conversation-menu")?.remove();
}

function openConversationMenu(conversationId, anchor) {
  closeConversationMenu();
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (!conversation) return;
  const menu = document.createElement("div");
  menu.className = "conversation-menu";
  menu.innerHTML = `
    <button type="button" data-action="pin">${conversation.is_pinned ? "取消固定" : "固定"}</button>
    <button type="button" data-action="rename">重命名</button>
    <button class="danger" type="button" data-action="delete">删除</button>`;
  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.right + 8, window.innerWidth - 202)}px`;
  menu.style.top = `${Math.min(rect.top - 10, window.innerHeight - menu.offsetHeight - 12)}px`;
  menu.addEventListener("click", async (event) => {
    const action = event.target.closest("button")?.dataset.action;
    if (action === "delete") await deleteConversation(conversationId);
    if (action === "rename") beginConversationRename(conversationId);
    if (action === "pin") await setConversationPinned(conversationId, !conversation.is_pinned);
  });
}

function beginConversationRename(conversationId) {
  closeConversationMenu();
  const conversation = state.conversations.find((item) => item.id === conversationId);
  const button = document.querySelector(`[data-conversation-id="${CSS.escape(conversationId)}"]`);
  if (!conversation || !button) return;
  const input = document.createElement("input");
  input.className = "conversation-rename";
  input.value = conversation.title;
  button.replaceWith(input);
  input.focus();
  input.select();
  let finished = false;
  const finish = async (save) => {
    if (finished) return;
    finished = true;
    const title = input.value.trim();
    if (save && title && title !== conversation.title) {
      await updateConversation(conversationId, { title });
    } else {
      renderConversations();
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

async function updateConversation(conversationId, updates) {
  const data = await api(`/web/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  state.conversations = state.conversations.map((item) => (
    item.id === conversationId ? { ...item, ...data.conversation } : item
  ));
  if ("is_pinned" in updates) {
    const list = await api("/web/conversations");
    state.conversations = list.conversations || state.conversations;
  }
  renderConversations();
}

async function setConversationPinned(conversationId, isPinned) {
  closeConversationMenu();
  await updateConversation(conversationId, { is_pinned: isPinned });
}

function displayMessages(messages) {
  $("chatStream").innerHTML = "";
  messages.forEach(renderMessage);
  updateEmptyChat();
  scrollChat(false);
}

async function selectConversation(conversationId, { force = false } = {}) {
  if (!conversationId || (!force && conversationId === state.activeConversationId)) return;
  const requestId = ++state.conversationRequest;
  state.conversationAbortController?.abort();
  state.conversationAbortController = new AbortController();
  state.activeConversationId = conversationId;
  renderConversations();
  const cached = state.messageCache.get(conversationId);
  if (cached) displayMessages(cached);
  $("chatScroll").classList.add("switching");
  try {
    const data = await api(`/web/conversations/${encodeURIComponent(conversationId)}/messages`, {
      signal: state.conversationAbortController.signal,
    });
    if (requestId !== state.conversationRequest || conversationId !== state.activeConversationId) return;
    const messages = data.messages || [];
    state.messageCache.set(conversationId, messages);
    displayMessages(messages);
  } catch (error) {
    if (error.name !== "AbortError") throw error;
  } finally {
    if (requestId === state.conversationRequest) $("chatScroll").classList.remove("switching");
  }
}

async function deleteConversation(conversationId) {
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (!conversation) return;
  closeConversationMenu();
  await api(`/web/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
  state.messageCache.delete(conversationId);
  const list = await api("/web/conversations");
  state.conversations = list.conversations || [];
  if (!state.conversations.length) state.conversations = [await createConversation()];
  const nextId = conversationId === state.activeConversationId ? state.conversations[0].id : state.activeConversationId;
  state.activeConversationId = "";
  renderConversations();
  await selectConversation(nextId, { force: true });
}

function renderMessage(message) {
  const article = document.createElement("article");
  article.className = `message ${message.role}`;
  const time = message.created_at ? new Date(message.created_at * 1000).toLocaleString() : "";
  const hardware = renderHardwareControl(message.hardware_control);
  article.innerHTML = message.role === "assistant"
    ? `<div class="message-card"><img class="message-avatar" src="/assets/vela-mark.svg" alt="" /><div class="message-content">${escapeHtml(message.content)}${hardware}<div class="message-meta">${escapeHtml(time)}</div></div></div>`
    : `<div class="message-card"><div class="message-content">${escapeHtml(message.content)}<div class="message-meta">${escapeHtml(time)}</div></div></div>`;
  $("chatStream").appendChild(article);
}

function renderHardwareControl(control) {
  if (!control || control.action_kind === "none") return "";
  const label = control.delivery_stage_label || control.delivery_stage || "已规划";
  const requestId = control.request_id ? `<span>请求 ${escapeHtml(control.request_id)}</span>` : "";
  const deviceId = control.device_id ? `<span>设备 ${escapeHtml(control.device_id)}</span>` : "";
  return `<div class="hardware-control-card"><strong>${escapeHtml(label)}</strong>${requestId}${deviceId}</div>`;
}

function emptyConversation() {
  return state.conversations.find((item) => Number(item.message_count || 0) === 0);
}

async function openReusableNewConversation() {
  const reusable = emptyConversation();
  if (reusable) {
    await selectConversation(reusable.id, { force: reusable.id === state.activeConversationId });
    selectView("chat");
    $("chatInput").focus();
    return reusable;
  }
  const conversation = await createConversation();
  state.conversations = [conversation, ...state.conversations];
  renderConversations();
  await selectConversation(conversation.id, { force: true });
  selectView("chat");
  $("chatInput").focus();
  return conversation;
}

function updateEmptyChat() {
  $("emptyChat").hidden = $("chatStream").children.length > 0;
}

function scrollChat(smooth = true) {
  window.requestAnimationFrame(() => {
    const viewport = $("chatScroll");
    if (!$("chatStream").children.length) {
      viewport.scrollTop = 0;
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  });
}

async function sendMessage(text) {
  if (state.sending || !state.activeConversationId) return;
  state.sending = true;
  const conversationId = state.activeConversationId;
  $("sendButton").disabled = true;
  $("chatStatus").textContent = "正在处理…";
  const optimistic = { role: "user", content: text, created_at: Math.floor(Date.now() / 1000) };
  const cached = [...(state.messageCache.get(conversationId) || []), optimistic];
  state.messageCache.set(conversationId, cached);
  if (state.activeConversationId === conversationId) displayMessages(cached);
  try {
    const data = await api("/web/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, conversation_id: conversationId, device_id: state.activeDeviceId || state.context?.device_id || "" }),
    });
    const completed = [...cached, { role: "assistant", content: data.assistant_message, created_at: data.created_at, hardware_control: data.hardware_control }];
    state.messageCache.set(conversationId, completed);
    if (state.activeConversationId === conversationId) displayMessages(completed);
    $("chatStatus").textContent = "在线";
    const list = await api("/web/conversations");
    state.conversations = list.conversations || state.conversations;
    renderConversations();
  } catch (error) {
    const failed = [...cached, { role: "assistant", content: `处理失败：${error.message}`, created_at: Math.floor(Date.now() / 1000) }];
    state.messageCache.set(conversationId, failed);
    if (state.activeConversationId === conversationId) displayMessages(failed);
    $("chatStatus").textContent = "连接异常";
  } finally {
    state.sending = false;
    $("sendButton").disabled = false;
  }
}

async function loadUsers() {
  const data = await api("/auth/users");
  const users = data.users || [];
  const activeAdminCount = users.filter((user) => user.role === "admin" && user.is_active).length;
  $("userList").innerHTML = users.map((user) => {
    const isSelf = user.id === state.user?.id;
    const isLastAdmin = user.role === "admin" && user.is_active && activeAdminCount <= 1;
    const deleteHint = isSelf ? "当前登录账户不能删除" : (isLastAdmin ? "至少保留一个管理员" : "删除该账户");
    const lastLogin = user.last_login_at ? `最近登录 ${formatTimestamp(user.last_login_at)}` : "尚未登录";
    return `
      <div class="user-row">
        <div>
          <strong>${escapeHtml(user.username)}</strong>
          <small>${escapeHtml(lastLogin)}</small>
        </div>
        <span>${user.role === "admin" ? "管理员" : "成员"}</span>
        <span>${user.is_active ? "已启用" : "已停用"}</span>
        <div class="user-actions">
          <button
            class="secondary-action danger-soft"
            type="button"
            data-delete-user-id="${escapeHtml(user.id)}"
            data-delete-username="${escapeHtml(user.username)}"
            ${isSelf || isLastAdmin ? "disabled" : ""}
            title="${escapeHtml(deleteHint)}"
          >删除</button>
        </div>
      </div>`;
  }).join("");
  document.querySelectorAll("[data-delete-user-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await deleteUser(button.dataset.deleteUserId, button.dataset.deleteUsername || "");
    });
  });
}

function renderModelConfig() {
  const list = $("modelConfigList");
  renderChatModelSelect();
  if (!list) return;
  const config = state.modelConfig;
  if (!config) {
    $("activeModelBadge").textContent = "读取中";
    list.innerHTML = "";
    return;
  }
  const active = config.active || {};
  const configured = config.configured || [];
  $("activeModelBadge").innerHTML = `<strong>${escapeHtml(active.label || active.provider || "当前模型")}</strong><span>${escapeHtml(active.version || active.model || "-")}</span>`;
  list.innerHTML = configured.map((item) => {
    const isActive = item.provider === active.provider && item.model === active.model;
    return `
      <article class="model-option ${isActive ? "active" : ""}">
        <div class="model-option-main">
          <span class="model-provider">${escapeHtml(item.label || item.provider)}</span>
          <strong>${escapeHtml(item.model)}</strong>
          <p>${escapeHtml(item.description || "")}</p>
          <div class="model-tags">
            <span>${escapeHtml(item.tier || "model")}</span>
            <span>${escapeHtml(item.key_status || "")}</span>
          </div>
        </div>
        <button class="${isActive ? "secondary-action" : "primary-action"}" type="button" data-model-provider="${escapeHtml(item.provider)}" data-model-name="${escapeHtml(item.model)}" ${isActive || !item.ready ? "disabled" : ""}>${isActive ? "当前使用" : "切换"}</button>
        ${item.custom ? `<button class="secondary-action model-delete" type="button" data-delete-model-provider="${escapeHtml(item.provider)}" data-delete-model-name="${escapeHtml(item.model)}">删除</button>` : ""}
      </article>`;
  }).join("");
  document.querySelectorAll("[data-model-provider]").forEach((button) => {
    button.addEventListener("click", () => switchModel(button.dataset.modelProvider, button.dataset.modelName));
  });
  document.querySelectorAll("[data-delete-model-provider]").forEach((button) => {
    button.addEventListener("click", () => deleteModelProfile(button.dataset.deleteModelProvider, button.dataset.deleteModelName));
  });
}

function renderChatModelSelect() {
  const select = $("chatModelSelect");
  if (!select) return;
  const config = state.modelConfig;
  const active = config?.active || null;
  const configured = (config?.configured || []).filter((item) => item.ready);
  if (!active || !configured.length) {
    select.innerHTML = `<option>模型读取中</option>`;
    select.disabled = true;
    select.title = "正在读取当前模型配置";
    return;
  }
  select.disabled = false;
  select.innerHTML = configured.map((item) => {
    const label = `${item.label || item.provider} · ${item.version || item.model}`;
    const value = `${item.provider}:::${item.model}`;
    return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
  }).join("");
  select.value = `${active.provider}:::${active.model}`;
  select.title = "切换当前对话使用的模型";
}

async function loadModelConfig() {
  const data = await api("/web/model-config");
  state.modelConfig = data.model_config;
  renderModelConfig();
}

async function switchModel(provider, model, { source = "model_page" } = {}) {
  const message = $("modelConfigMessage");
  if (message) message.textContent = "正在切换模型…";
  $("chatModelSelect").disabled = true;
  try {
    const data = await api("/web/model-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model }),
    });
    state.modelConfig = data.model_config;
    renderModelConfig();
    if (message) message.textContent = source === "chat" ? "已切换当前对话模型。" : "模型配置已更新，后续请求将使用新的模型。";
  } catch (error) {
    renderModelConfig();
    if (message) message.textContent = `切换失败：${error.message}`;
  }
}

function applyModelPreset(name) {
  const preset = MODEL_PRESETS[name] || MODEL_PRESETS.custom;
  $("modelLabelInput").value = preset.label;
  $("modelProviderInput").value = preset.provider;
  $("modelNameInput").value = preset.model;
  $("modelBaseUrlInput").value = preset.base_url;
}

async function saveModelProfile() {
  $("modelConfigMessage").textContent = "正在保存模型配置…";
  const payload = {
    label: $("modelLabelInput").value.trim(),
    provider: $("modelProviderInput").value.trim(),
    model: $("modelNameInput").value.trim(),
    base_url: $("modelBaseUrlInput").value.trim(),
    api_key: $("modelApiKeyInput").value,
    protocol: "openai_compatible",
    description: `${$("modelLabelInput").value.trim()} OpenAI-compatible 模型配置。`,
  };
  try {
    const data = await api("/web/model-config/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.modelConfig = data.model_config;
    $("modelApiKeyInput").value = "";
    renderModelConfig();
    $("modelConfigMessage").textContent = "模型已保存，可以在列表中切换使用。";
  } catch (error) {
    $("modelConfigMessage").textContent = `保存失败：${error.message}`;
  }
}

async function deleteModelProfile(provider, model) {
  $("modelConfigMessage").textContent = "正在删除模型配置…";
  try {
    const data = await api(`/web/model-config/profiles/${encodeURIComponent(provider)}/${encodeURIComponent(model)}`, {
      method: "DELETE",
    });
    state.modelConfig = data.model_config;
    renderModelConfig();
    $("modelConfigMessage").textContent = "模型配置已删除。";
  } catch (error) {
    $("modelConfigMessage").textContent = `删除失败：${error.message}`;
  }
}

function setProvisionStatus(primary, secondary = "") {
  const badge = $("provisionStatusBadge");
  if (!badge) return;
  badge.innerHTML = `<strong>${escapeHtml(primary)}</strong>${secondary ? `<span>${escapeHtml(secondary)}</span>` : ""}`;
}

function appendProvisionLog(message) {
  const log = $("provisionLog");
  if (!log) return;
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  log.textContent = `${log.textContent}${time}  ${message}\n`;
  log.scrollTop = log.scrollHeight;
}

function renderWifiNetworks(networks = []) {
  const list = $("wifiNetworkList");
  if (!list) return;
  if (!networks.length) {
    list.innerHTML = `<p class="muted">暂无扫描结果</p>`;
    return;
  }
  list.innerHTML = networks.map((network) => `
    <div class="wifi-network-item">
      <div><strong>${escapeHtml(network.ssid || "(隐藏网络)")}</strong><span>${escapeHtml(`${network.rssi ?? "-"} dBm · ${network.secure ? "加密" : "开放"}`)}</span></div>
      <button class="secondary-action" type="button" data-wifi-ssid="${escapeHtml(network.ssid || "")}">填入</button>
    </div>`).join("");
  document.querySelectorAll("[data-wifi-ssid]").forEach((button) => {
    button.addEventListener("click", () => {
      $("wifiSsidInput").value = button.dataset.wifiSsid || "";
      $("wifiPasswordInput").focus();
    });
  });
}

function renderSavedWifiProfiles() {
  const list = $("savedWifiList");
  if (!list) return;
  const profiles = savedWifiProfiles();
  if (!profiles.length) {
    list.innerHTML = `<p class="muted">当前账户在此浏览器还没有保存过 WiFi。</p>`;
    return;
  }
  list.innerHTML = profiles.map((profile) => `
    <div class="wifi-network-item saved-wifi-item">
      <div>
        <strong>${escapeHtml(profile.ssid)}</strong>
        <span>${escapeHtml(profile.password ? "已保存密码 · 仅本浏览器" : "未保存密码")} · ${escapeHtml(formatTimestamp(Math.floor((profile.updated_at || Date.now()) / 1000)))}</span>
      </div>
      <div class="wifi-item-actions">
        <button class="secondary-action" type="button" data-use-wifi-ssid="${escapeHtml(profile.ssid)}">选用</button>
        <button class="secondary-action danger-soft" type="button" data-delete-wifi-ssid="${escapeHtml(profile.ssid)}">删除</button>
      </div>
    </div>`).join("");
  document.querySelectorAll("[data-use-wifi-ssid]").forEach((button) => {
    button.addEventListener("click", () => {
      const profile = savedWifiProfiles().find((item) => item.ssid === button.dataset.useWifiSsid);
      if (!profile) return;
      $("wifiSsidInput").value = profile.ssid;
      $("wifiPasswordInput").value = profile.password || "";
      $("wifiProvisionMessage").textContent = `已选用 ${profile.ssid}，确认后点击“写入并连接”。`;
    });
  });
  document.querySelectorAll("[data-delete-wifi-ssid]").forEach((button) => {
    button.addEventListener("click", () => deleteWifiProfile(button.dataset.deleteWifiSsid || ""));
  });
}

function handleProvisionLine(line) {
  if (!line.trim()) return;
  let data = null;
  try {
    data = JSON.parse(line);
  } catch {
    appendProvisionLog(line);
    return;
  }

  if (data.type === "wifi.status") {
    const wifi = data.wifi === "connected" ? "WiFi 已连接" : "WiFi 未连接";
    const detail = data.ssid && data.ssid !== "-" ? `${data.ssid} · ${data.ip || "-"}` : (data.saved_ssid ? `已保存 ${data.saved_ssid}` : "未保存 SSID");
    setProvisionStatus(wifi, detail);
    $("wifiProvisionMessage").textContent = `设备 ${data.device_id || "-"}，MQTT ${data.mqtt || "unknown"}。`;
    appendProvisionLog(`status wifi=${data.wifi || "-"} ssid=${data.ssid || "-"} mqtt=${data.mqtt || "-"}`);
    return;
  }

  if (data.type === "wifi.scan.result") {
    renderWifiNetworks(data.networks || []);
    $("wifiProvisionMessage").textContent = `扫描完成，共 ${data.count || 0} 个网络。`;
    appendProvisionLog(`scan result count=${data.count || 0}`);
    return;
  }

  if (data.type === "wifi.set.result") {
    $("wifiProvisionMessage").textContent = data.ok ? `已写入 ${data.ssid || "SSID"}，正在等待 ESP32 联网。` : "写入失败。";
    appendProvisionLog(`set ${data.ok ? "ok" : "failed"} ssid=${data.ssid || "-"}`);
    if (data.ok) saveWifiProfile(data.ssid || $("wifiSsidInput").value, state.pendingWifiPassword || "");
    state.pendingWifiPassword = "";
    setTimeout(() => sendProvisionCommand({ type: "wifi.status" }).catch(() => {}), 2500);
    return;
  }

  if (data.type === "wifi.clear.result") {
    $("wifiProvisionMessage").textContent = data.ok ? "已清除 ESP32 保存的 WiFi。" : "清除失败。";
    appendProvisionLog(`clear ${data.ok ? "ok" : "failed"}`);
    setProvisionStatus("未连接", "已清除配置");
    return;
  }

  if (data.type === "wifi.error") {
    $("wifiProvisionMessage").textContent = `设备返回错误：${data.message || "unknown"}`;
    appendProvisionLog(`error ${data.message || "unknown"}`);
    return;
  }

  appendProvisionLog(line);
}

function handleProvisionChunk(chunk) {
  state.provisionBuffer += chunk;
  const lines = state.provisionBuffer.split("\n");
  state.provisionBuffer = lines.pop() || "";
  lines.forEach((line) => handleProvisionLine(line.replace(/\r$/, "")));
}

function isProvisionPortOpen() {
  return Boolean(state.provisionPort?.readable && state.provisionPort?.writable);
}

function markProvisionDisconnected(message = "USB 串口已断开，页面显示的是最后一次读取到的 WiFi 状态。") {
  state.provisionReader = null;
  state.provisionPort = null;
  state.provisionReadLoopActive = false;
  setProvisionStatus("USB 已断开", "最后一次 WiFi 状态");
  $("wifiProvisionMessage").textContent = message;
  appendProvisionLog("serial disconnected");
}

async function readProvisionLoop() {
  const decoder = new TextDecoder();
  state.provisionReadLoopActive = true;
  try {
    while (state.provisionPort?.readable) {
      state.provisionReader = state.provisionPort.readable.getReader();
      try {
        while (true) {
          const { value, done } = await state.provisionReader.read();
          if (done) break;
          if (value) handleProvisionChunk(decoder.decode(value, { stream: true }));
        }
      } finally {
        state.provisionReader.releaseLock();
        state.provisionReader = null;
      }
    }
  } catch (error) {
    appendProvisionLog(`serial read stopped: ${error.message}`);
    markProvisionDisconnected();
  } finally {
    state.provisionReadLoopActive = false;
  }
}

async function resetProvisionPort() {
  try {
    await state.provisionReader?.cancel();
  } catch {}
  try {
    if (state.provisionPort?.readable || state.provisionPort?.writable) {
      await state.provisionPort.close();
    }
  } catch {}
  state.provisionReader = null;
  state.provisionPort = null;
  state.provisionReadLoopActive = false;
}

function serialOpenErrorMessage(error) {
  const raw = error?.message || "unknown";
  if (raw.includes("Failed to open serial port") || raw.includes("open")) {
    return "串口打开失败：请关闭 Arduino IDE 的串口监视器/其他串口工具，拔插或复位 ESP32 后重试。";
  }
  return `连接失败：${raw}`;
}

async function connectProvisionPort() {
  if (!("serial" in navigator)) {
    $("wifiProvisionMessage").textContent = "当前浏览器不支持 Web Serial。";
    setProvisionStatus("不可用", "请使用 Chrome / Edge");
    return false;
  }
  if (isProvisionPortOpen()) return true;
  const port = state.provisionPort || await navigator.serial.requestPort();
  state.provisionPort = port;
  try {
    await port.open({ baudRate: 115200 });
  } catch (error) {
    await resetProvisionPort();
    const message = serialOpenErrorMessage(error);
    $("wifiProvisionMessage").textContent = message;
    setProvisionStatus("连接失败", "USB Serial");
    appendProvisionLog(message);
    throw error;
  }
  setProvisionStatus("USB 已连接", "ESP32 Serial");
  appendProvisionLog("serial connected baud=115200");
  if (!state.provisionReadLoopActive) readProvisionLoop();
  await sendProvisionCommand({ type: "wifi.status" });
  return true;
}

async function sendProvisionCommand(command) {
  if (!isProvisionPortOpen()) {
    await resetProvisionPort();
    throw new Error("请先点击“连接 USB”，选择 ESP32 串口后再操作。");
  }
  const writer = state.provisionPort.writable.getWriter();
  try {
    const text = `${JSON.stringify(command)}\n`;
    await writer.write(new TextEncoder().encode(text));
    appendProvisionLog(`> ${command.type}`);
  } catch (error) {
    await resetProvisionPort();
    throw error;
  } finally {
    writer.releaseLock();
  }
}

function selectView(name) {
  const titles = { chat: "对话", signals: "信号通道", models: "模型配置", provision: "设备配网", account: "账户" };
  document.querySelectorAll("[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  document.querySelectorAll(".view").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  $("viewTitle").textContent = titles[name];
  if (name === "signals") loadContext({ silent: true }).catch(() => {});
  if (name === "models") loadModelConfig().catch((error) => {
    $("modelConfigMessage").textContent = `读取失败：${error.message}`;
  });
  if (name === "provision") {
    setProvisionStatus(isProvisionPortOpen() ? "USB 已连接" : "未连接", isProvisionPortOpen() ? "ESP32 Serial" : "");
  }
}

async function leaveWorkspace({ keepSession = false } = {}) {
  if (!keepSession && state.csrf) {
    await api("/auth/logout", { method: "POST" });
    state.pendingSession = null;
  } else if (keepSession) {
    state.pendingSession = { user: state.user, csrf_token: state.csrf };
  }
  state.user = null;
  state.csrf = "";
  state.activeConversationId = "";
  if (state.contextRefreshTimer) clearInterval(state.contextRefreshTimer);
  state.contextRefreshTimer = null;
  state.messageCache.clear();
  showAuth(false);
}

function setSecretFieldVisibility(input, visible) {
  input.type = visible ? "text" : "password";
  const wrapper = input.closest(".secret-field");
  const button = wrapper?.querySelector(".secret-toggle");
  if (!button) return;
  button.textContent = visible ? "隐藏" : "显示";
  button.setAttribute("aria-label", visible ? "隐藏密码" : "显示密码");
  button.setAttribute("aria-pressed", visible ? "true" : "false");
}

function enhanceSecretFields() {
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.dataset.secretToggleReady === "true") return;
    input.dataset.secretToggleReady = "true";
    const wrapper = document.createElement("div");
    wrapper.className = "secret-field";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secret-toggle";
    button.addEventListener("click", () => setSecretFieldVisibility(input, input.type === "password"));
    wrapper.appendChild(button);
    setSecretFieldVisibility(input, false);
  });
}

function resetSecretFields(scope = document) {
  scope.querySelectorAll(".secret-field input").forEach((input) => setSecretFieldVisibility(input, false));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

async function deleteUser(userId, username) {
  const userAdminMessage = $("userAdminMessage");
  if (!userId) return;
  if (!window.confirm(`确认删除用户 ${username || userId} 吗？`)) return;
  userAdminMessage.textContent = "正在删除用户…";
  try {
    await api(`/auth/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
    userAdminMessage.textContent = `已删除用户 ${username || userId}。`;
    await loadUsers();
  } catch (error) {
    userAdminMessage.textContent = `删除失败：${error.message}`;
  }
}

function resetUserDialog() {
  const form = $("userForm");
  form.reset();
  $("userFormError").textContent = "";
  resetSecretFields(form);
}

$("authForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("authError").textContent = "";
  const mode = event.currentTarget.dataset.mode || "login";
  const username = $("usernameInput").value.trim();
  try {
    await api(`/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password: $("passwordInput").value }),
    });
    rememberAccount(username);
    $("passwordInput").value = "";
    await inspectSession({ enterApp: true });
  } catch (error) {
    $("authError").textContent = error.message;
  }
});

$("continueSessionButton").addEventListener("click", () => {
  if (state.pendingSession) enterWorkspace(state.pendingSession);
});

$("newChatButton").addEventListener("click", async () => {
  if (state.creatingConversation) return;
  state.creatingConversation = true;
  $("newChatButton").disabled = true;
  try {
    await openReusableNewConversation();
  } finally {
    state.creatingConversation = false;
    $("newChatButton").disabled = false;
  }
});

$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("chatInput").value.trim();
  if (!text) return;
  $("chatInput").value = "";
  $("chatInput").style.height = "auto";
  await sendMessage(text);
});

$("chatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});

$("chatInput").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 170)}px`;
});

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
$("railAccountButton").addEventListener("click", () => selectView("account"));
$("searchChatButton").addEventListener("click", () => {
  $("searchPanel").hidden = !$("searchPanel").hidden;
  if (!$("searchPanel").hidden) $("conversationSearch").focus();
});
$("conversationSearch").addEventListener("input", (event) => {
  state.searchQuery = event.target.value;
  renderConversations();
});
$("modelPresetSelect").addEventListener("change", (event) => applyModelPreset(event.target.value));
$("modelProfileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveModelProfile();
});
$("chatModelSelect").addEventListener("change", async (event) => {
  const [provider, model] = String(event.target.value || "").split(":::");
  if (!provider || !model) return;
  await switchModel(provider, model, { source: "chat" });
});
$("deviceSelect").addEventListener("change", async (event) => {
  state.activeDeviceId = event.target.value || "";
  if (state.activeDeviceId) localStorage.setItem("vela.activeDeviceId", state.activeDeviceId);
  $("chatStatus").textContent = "切换设备…";
  try {
    await loadContext({ silent: true });
    $("chatStatus").textContent = "在线";
  } catch {
    $("chatStatus").textContent = "设备刷新失败";
  }
});
$("connectSerialButton").addEventListener("click", async () => {
  try {
    await connectProvisionPort();
  } catch (error) {
    $("wifiProvisionMessage").textContent = serialOpenErrorMessage(error);
    setProvisionStatus("连接失败", "USB Serial");
  }
});
$("scanWifiButton").addEventListener("click", async () => {
  try {
    await sendProvisionCommand({ type: "wifi.scan" });
  } catch (error) {
    $("wifiProvisionMessage").textContent = `扫描失败：${error.message}`;
  }
});
$("wifiStatusButton").addEventListener("click", async () => {
  try {
    await sendProvisionCommand({ type: "wifi.status" });
  } catch (error) {
    $("wifiProvisionMessage").textContent = `状态读取失败：${error.message}`;
  }
});
$("clearWifiButton").addEventListener("click", async () => {
  try {
    await sendProvisionCommand({ type: "wifi.clear" });
  } catch (error) {
    $("wifiProvisionMessage").textContent = `清除失败：${error.message}`;
  }
});
$("wifiProvisionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const ssid = $("wifiSsidInput").value.trim();
  if (!ssid) return;
  const password = $("wifiPasswordInput").value;
  try {
    state.pendingWifiPassword = password;
    await sendProvisionCommand({
      type: "wifi.set",
      ssid,
      password,
    });
    $("wifiPasswordInput").value = "";
  } catch (error) {
    state.pendingWifiPassword = "";
    $("wifiProvisionMessage").textContent = `写入失败：${error.message}`;
  }
});
applyModelPreset("qwen");
renderWifiNetworks([]);
renderSavedWifiProfiles();
$("collapseRailButton").addEventListener("click", () => {
  $("appView").classList.add("rail-collapsed");
  $("expandRailButton").hidden = false;
});
$("expandRailButton").addEventListener("click", () => {
  $("appView").classList.remove("rail-collapsed");
  $("expandRailButton").hidden = true;
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".conversation-menu") && !event.target.closest(".conversation-delete")) closeConversationMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeConversationMenu();
});
$("switchAccountButton").addEventListener("click", () => leaveWorkspace({ keepSession: true }));
$("logoutButton").addEventListener("click", () => leaveWorkspace());

$("passwordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("passwordMessage").textContent = "";
  try {
    await api("/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("currentPassword").value, new_password: $("newPassword").value }),
    });
    $("passwordMessage").textContent = "密码已更新，请重新登录。";
    state.pendingSession = null;
    setTimeout(() => {
      state.user = null;
      state.csrf = "";
      state.activeConversationId = "";
      state.messageCache.clear();
      showAuth(false);
    }, 700);
  } catch (error) {
    $("passwordMessage").textContent = error.message;
  }
});

$("addUserButton").addEventListener("click", () => {
  resetUserDialog();
  $("userDialog").showModal();
});
$("cancelUserButton").addEventListener("click", () => {
  resetUserDialog();
  $("userDialog").close();
});
$("userForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  $("userFormError").textContent = "";
  $("userAdminMessage").textContent = "";
  try {
    await api("/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("newUsername").value.trim(), password: $("newUserPassword").value, role: $("newUserRole").value }),
    });
    form.reset();
    resetSecretFields(form);
    $("userDialog").close();
    await loadUsers();
    $("userAdminMessage").textContent = "用户已创建。";
  } catch (error) {
    $("userFormError").textContent = error.message;
  }
});

enhanceSecretFields();
inspectSession().catch((error) => {
  state.pendingSession = null;
  showAuth(false);
  $("authError").textContent = `连接失败：${error.message}`;
});
