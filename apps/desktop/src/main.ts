import { invoke } from "@tauri-apps/api/core";
import "./styles.css";

interface SidecarStatus {
  healthy: boolean;
  running: boolean;
  restart_count: number;
  restart_limit_reached: boolean;
}

interface SidecarHttpResponse {
  status: number;
  body: string;
  headers: Record<string, string>;
}

interface CurrentUser {
  id: string;
  username: string;
  role: string;
}

interface Task {
  id: string;
  goal: string;
  status: string;
  edition: string;
  created_at: string;
}

interface TaskStep {
  id: string;
  step_order: number;
  tool_name: string;
  args: Record<string, unknown> | null;
  risk_level: string;
  status: string;
  result: string | null;
  error: string | null;
}

interface TaskDetail {
  id: string;
  goal: string;
  status: string;
  edition: string;
  risk_level: string | null;
  created_at: string;
  error: string | null;
  steps: TaskStep[];
}

interface Approval {
  id: string;
  step_run_id: string;
  tool_name: string;
  risk_level: string;
  status: string;
  requester_principal_id: string;
  required_quorum: number;
  resolution_id?: string | null;
  sanitized_args?: Record<string, unknown> | null;
}

interface UnknownOutcome {
  effect_id: string;
  step_run_id: string;
  tool_name: string;
  effect_class: string;
  status: string;
  created_at: string | null;
  before_hash: string | null;
  after_hash: string | null;
}

interface UnknownOutcomeList {
  items: UnknownOutcome[];
  total: number;
}

interface DispatchAttempt {
  attempt_ordinal: number;
  lease_id: string;
  fencing_token: number;
  worker_id: string;
  adapter_name: string;
  dispatched_at: string | null;
  result_status: string | null;
}

interface EffectDetail {
  effect_id: string;
  step_run_id: string;
  status: string;
  effect_class: string;
  tool_name: string;
  before_hash: string | null;
  after_hash: string | null;
  created_at: string | null;
  finalized_at: string | null;
  dispatch_history: DispatchAttempt[];
}

interface GatewayApprovalList {
  items: Approval[];
  total: number;
}

let authToken: string | null = null;
let currentUser: CurrentUser | null = null;

const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector);
const messageEl = $("#message")!;

function fieldValue(selector: string) {
  return document.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector)!.value;
}

function setFieldValue(selector: string, value: string) {
  document.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector)!.value = value;
}

function setMessage(message: string, error = false) {
  messageEl.textContent = message;
  messageEl.style.color = error ? "#9c3030" : "";
}

function setSidecarState(state: "ready" | "error" | "starting" | "unknown", text: string) {
  const el = $("#sidecar-state")!;
  el.className = `status-pill status-${state}`;
  el.textContent = text;
}

async function sidecarRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  const response = await invoke<SidecarHttpResponse>("http_via_sidecar", {
    method,
    path,
    body,
    headers,
  });
  let parsed: T;
  try {
    parsed = JSON.parse(response.body || "{}") as T;
  } catch {
    throw new Error(`control-core returned invalid JSON (HTTP ${response.status})`);
  }
  if (response.status >= 400) {
    const data = parsed as { detail?: string; message?: string };
    throw new Error(data.detail ?? data.message ?? `HTTP ${response.status}`);
  }
  return parsed;
}

async function refreshSidecar() {
  try {
    const status = await invoke<SidecarStatus>("sidecar_status");
    if (!status.running || !status.healthy) {
      setSidecarState("error", status.restart_limit_reached ? "Restart limit reached" : "Sidecar unavailable");
      return;
    }
    const health = await sidecarRequest<{ version: string; api_ready?: boolean }>("GET", "/health");
    if (health.api_ready === false) {
      setSidecarState("starting", "Starting control-core");
      window.setTimeout(() => void refreshSidecar(), 250);
      return;
    }
    setSidecarState("ready", `Ready v${health.version}`);
    if (!authToken) setMessage("control-core is ready. Sign in to manage tasks.");
  } catch (error) {
    setSidecarState("error", "Sidecar unavailable");
    setMessage(String(error), true);
  }
}

function showWorkspace(user: CurrentUser) {
  currentUser = user;
  $("#auth-panel")!.classList.add("hidden");
  $("#workspace-panel")!.classList.remove("hidden");
  $("#current-user")!.textContent = `${user.username} (${user.role})`;
}

function showAuth() {
  currentUser = null;
  authToken = null;
  $("#auth-panel")!.classList.remove("hidden");
  $("#workspace-panel")!.classList.add("hidden");
}

async function login(username: string, password: string) {
  const response = await sidecarRequest<{ data: { token: string; user: CurrentUser } }>(
    "POST",
    "/api/v1/auth/login",
    { username, password },
  );
  authToken = response.data.token;
  showWorkspace(response.data.user);
  await refreshWorkspace();
  setMessage(`Signed in as ${response.data.user.username}.`);
}

async function register() {
  const username = fieldValue("#username").trim();
  const password = fieldValue("#password");
  if (!username || password.length < 8) throw new Error("Use a username and a password of at least 8 characters.");
  await sidecarRequest("POST", "/api/v1/auth/register", { username, password });
  await login(username, password);
}

async function loadTasks() {
  const response = await sidecarRequest<{ data: { items: Task[]; total: number } }>("GET", "/api/v1/tasks?page=1&page_size=50");
  const tasks = response.data.items ?? [];
  $("#task-count")!.textContent = String(response.data.total ?? tasks.length);
  const tbody = $("#tasks")!;
  tbody.replaceChildren();
  if (!tasks.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="4" class="empty">No tasks yet.</td>';
    tbody.append(row);
    return;
  }
  for (const task of tasks) {
    const row = document.createElement("tr");
    const created = new Date(task.created_at).toLocaleString();
    const canExecute = task.status === "pending";
    row.innerHTML = `
      <td>${escapeHtml(task.goal)}</td>
      <td><span class="status-tag ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span></td>
      <td>${escapeHtml(created)}</td>
      <td><div class="row-actions">
        <button class="button button-secondary button-small" data-action="detail" data-id="${escapeHtml(task.id)}" type="button">Detail</button>
        ${canExecute ? `<button class="button button-secondary button-small" data-action="execute" data-id="${escapeHtml(task.id)}" type="button">Execute</button>` : ""}
        ${["pending", "planning", "awaiting_approval"].includes(task.status) ? `<button class="button button-danger button-small" data-action="cancel" data-id="${escapeHtml(task.id)}" type="button">Cancel</button>` : ""}
      </div></td>`;
    tbody.append(row);
  }
}

async function loadApprovals() {
  const response = await sidecarRequest<GatewayApprovalList>("GET", "/api/v1/gateway-approvals?status=pending");
  const pending = response.items ?? [];
  $("#approval-count")!.textContent = String(response.total ?? pending.length);
  const list = $("#approvals")!;
  list.replaceChildren();
  if (!pending.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No pending approvals.";
    list.append(empty);
    return;
  }
  for (const approval of pending) {
    const item = document.createElement("div");
    item.className = "list-item";
    const argsBlock = approval.sanitized_args
      ? `<pre class="args-block">${escapeHtml(JSON.stringify(approval.sanitized_args, null, 2))}</pre>`
      : "";
    item.innerHTML = `
      <div class="list-item-title">${escapeHtml(approval.tool_name)} · step ${escapeHtml(approval.step_run_id)}</div>
      <div class="list-item-meta">Risk ${escapeHtml(approval.risk_level)} · quorum ${approval.required_quorum} · requested by ${escapeHtml(approval.requester_principal_id)}</div>
      ${argsBlock}
      <div class="list-item-actions">
        <button class="button button-primary button-small" data-approval="approve" data-id="${escapeHtml(approval.id)}" type="button">Vote approve</button>
        <button class="button button-danger button-small" data-approval="reject" data-id="${escapeHtml(approval.id)}" type="button">Vote reject</button>
      </div>`;
    list.append(item);
  }
}

async function loadTaskDetail(id: string) {
  const response = await sidecarRequest<{ data: TaskDetail }>("GET", `/api/v1/tasks/${encodeURIComponent(id)}`);
  const task = response.data;
  $("#task-detail-title")!.textContent = task.goal;
  const container = $("#task-detail")!;
  const created = new Date(task.created_at).toLocaleString();
  const rows = task.steps.map((step) => {
    const args = step.args ? JSON.stringify(step.args, null, 2) : "—";
    const outcome = step.error ? `<span class="error-text">${escapeHtml(step.error)}</span>` : escapeHtml(step.result ?? "—");
    return `
      <tr>
        <td>${step.step_order + 1}</td>
        <td>${escapeHtml(step.tool_name)}</td>
        <td><pre class="args-block">${escapeHtml(args)}</pre></td>
        <td><span class="status-tag ${escapeHtml(step.status)}">${escapeHtml(step.status)}</span></td>
        <td>${outcome}</td>
      </tr>`;
  }).join("");
  container.innerHTML = `
    <div class="list-item-meta">Task ${escapeHtml(task.id)} · ${escapeHtml(task.edition)} · risk ${escapeHtml(task.risk_level ?? "—")} · created ${escapeHtml(created)} · <span class="status-tag ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span></div>
    ${task.error ? `<div class="list-item-meta error-text">${escapeHtml(task.error)}</div>` : ""}
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>Tool</th><th>Args (sanitized)</th><th>Status</th><th>Result / error</th></tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="5" class="empty">No steps.</td></tr>'}</tbody>
      </table>
    </div>`;
  $("#task-detail-panel")!.classList.remove("hidden");
  $("#task-detail-panel")!.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadUnknownOutcomes() {
  const response = await sidecarRequest<UnknownOutcomeList>("GET", "/api/v1/effects/unknown-outcomes");
  const items = response.items ?? [];
  $("#unknown-count")!.textContent = String(response.total ?? items.length);
  const list = $("#unknown-outcomes")!;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No unknown-outcome effects.";
    list.append(empty);
    return;
  }
  for (const effect of items) {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <div class="list-item-title">${escapeHtml(effect.tool_name)} · ${escapeHtml(effect.effect_id)}</div>
      <div class="list-item-meta">step ${escapeHtml(effect.step_run_id)} · class ${escapeHtml(effect.effect_class)} · since ${escapeHtml(effect.created_at ?? "—")}</div>
      <div class="hash-line">before ${escapeHtml(effect.before_hash ?? "—")}</div>
      <div class="hash-line">after ${escapeHtml(effect.after_hash ?? "—")}</div>
      <div class="list-item-actions">
        <button class="button button-secondary button-small" data-effect="view" data-id="${escapeHtml(effect.effect_id)}" type="button">Detail</button>
        <button class="button button-primary button-small" data-effect="confirmed" data-id="${escapeHtml(effect.effect_id)}" type="button">Reconcile confirmed</button>
        <button class="button button-danger button-small" data-effect="failed" data-id="${escapeHtml(effect.effect_id)}" type="button">Reconcile failed</button>
      </div>`;
    list.append(item);
  }
}

async function showEffectDetail(id: string) {
  const effect = await sidecarRequest<EffectDetail>("GET", `/api/v1/effects/${encodeURIComponent(id)}`);
  $("#effect-detail-title")!.textContent = `${effect.tool_name} · ${effect.effect_id}`;
  const container = $("#effect-detail")!;
  const rows = effect.dispatch_history.map((a) => `
    <tr>
      <td>${a.attempt_ordinal}</td>
      <td>${escapeHtml(a.worker_id)}</td>
      <td>${escapeHtml(a.adapter_name)}</td>
      <td>${escapeHtml(a.lease_id)}</td>
      <td>${a.fencing_token}</td>
      <td>${escapeHtml(a.dispatched_at ?? "—")}</td>
      <td>${escapeHtml(a.result_status ?? "—")}</td>
    </tr>`).join("");
  const canReconcile = effect.status === "UNKNOWN_OUTCOME";
  container.innerHTML = `
    <div class="list-item-meta">step ${escapeHtml(effect.step_run_id)} · class ${escapeHtml(effect.effect_class)} · created ${escapeHtml(effect.created_at ?? "—")} · finalized ${escapeHtml(effect.finalized_at ?? "—")}</div>
    <div class="list-item-meta">status <span class="status-tag ${escapeHtml(effect.status.toLowerCase())}">${escapeHtml(effect.status)}</span></div>
    <div class="hash-line">before_hash ${escapeHtml(effect.before_hash ?? "—")}</div>
    <div class="hash-line">after_hash ${escapeHtml(effect.after_hash ?? "—")}</div>
    <div class="list-item-actions">
      ${canReconcile
        ? `<button class="button button-primary button-small" data-effect="confirmed" data-id="${escapeHtml(effect.effect_id)}" type="button">Reconcile confirmed</button>
           <button class="button button-danger button-small" data-effect="failed" data-id="${escapeHtml(effect.effect_id)}" type="button">Reconcile failed</button>`
        : `<span class="muted">Terminal state — reconcile returns 409.</span>`}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Worker</th><th>Adapter</th><th>Lease</th><th>Fencing</th><th>Dispatched</th><th>Result</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="empty">No dispatch attempts.</td></tr>'}</tbody>
      </table>
    </div>`;
  $("#effect-detail-panel")!.classList.remove("hidden");
  $("#effect-detail-panel")!.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function reconcileEffect(id: string, finalStatus: "confirmed" | "failed") {
  await sidecarRequest("POST", `/api/v1/effects/${encodeURIComponent(id)}/reconcile`, { final_status: finalStatus });
  setMessage(`Effect ${id} reconciled as ${finalStatus}.`);
  await loadUnknownOutcomes();
  const panel = $("#effect-detail-panel")!;
  if (!panel.classList.contains("hidden")) await showEffectDetail(id);
}

async function refreshWorkspace() {
  await Promise.all([loadTasks(), loadApprovals(), loadUnknownOutcomes()]);
}

async function createTask(event: SubmitEvent) {
  event.preventDefault();
  const goal = fieldValue("#task-goal").trim();
  const edition = fieldValue("#task-edition");
  if (!goal) throw new Error("Task goal is required.");
  await sidecarRequest("POST", "/api/v1/tasks", { goal, edition });
  setFieldValue("#task-goal", "");
  await refreshWorkspace();
  setMessage("Task created and queued.");
}

async function taskAction(action: string, id: string) {
  await sidecarRequest("POST", `/api/v1/tasks/${encodeURIComponent(id)}/${action}`);
  await refreshWorkspace();
  setMessage(`Task ${action} request completed.`);
}

async function resolveApproval(id: string, approved: boolean) {
  await sidecarRequest("POST", `/api/v1/gateway-approvals/${encodeURIComponent(id)}/vote`, {
    decision: approved ? "approve" : "reject",
    reason: approved ? "Approved in desktop control panel" : "Rejected in desktop control panel",
  });
  const resolution = await sidecarRequest<{ status: string }>(
    "POST",
    `/api/v1/gateway-approvals/${encodeURIComponent(id)}/resolve`,
  );
  await refreshWorkspace();
  setMessage(`Approval ${resolution.status}.`);
}

function escapeHtml(value: string) {
  return value.replace(/[&<>\'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char] ?? char));
}

function run(action: () => Promise<void>) {
  void action().catch((error) => setMessage(String(error), true));
}

window.addEventListener("DOMContentLoaded", () => {
  $("#auth-form")!.addEventListener("submit", (event) => {
    event.preventDefault();
    run(() => login(fieldValue("#username").trim(), fieldValue("#password")));
  });
  $("#register")!.addEventListener("click", () => run(register));
  $("#logout")!.addEventListener("click", () => {
    showAuth();
    setMessage("Signed out.");
  });
  $("#refresh-all")!.addEventListener("click", () => run(async () => {
    await refreshSidecar();
    if (authToken) await refreshWorkspace();
  }));
  $("#task-form")!.addEventListener("submit", (event) => run(() => createTask(event as SubmitEvent)));
  $("#tasks")!.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("button[data-action]");
    if (!button?.dataset.id || !button.dataset.action) return;
    if (button.dataset.action === "detail") {
      run(() => loadTaskDetail(button.dataset.id!));
    } else {
      run(() => taskAction(button.dataset.action!, button.dataset.id!));
    }
  });
  $("#approvals")!.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("button[data-approval]");
    if (button?.dataset.id) run(() => resolveApproval(button.dataset.id!, button.dataset.approval === "approve"));
  });
  $("#unknown-outcomes")!.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("button[data-effect]");
    if (!button?.dataset.id) return;
    const action = button.dataset.effect!;
    if (action === "view") run(() => showEffectDetail(button.dataset.id!));
    else run(() => reconcileEffect(button.dataset.id!, action as "confirmed" | "failed"));
  });
  $("#effect-detail")!.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("button[data-effect]");
    if (!button?.dataset.id) return;
    const action = button.dataset.effect!;
    if (action !== "view") run(() => reconcileEffect(button.dataset.id!, action as "confirmed" | "failed"));
  });
  $("#task-detail-close")!.addEventListener("click", () => $("#task-detail-panel")!.classList.add("hidden"));
  $("#effect-detail-close")!.addEventListener("click", () => $("#effect-detail-panel")!.classList.add("hidden"));
  showAuth();
  run(refreshSidecar);
});
