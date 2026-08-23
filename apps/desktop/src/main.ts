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

interface Approval {
  id: string;
  step_run_id: string;
  tool_name: string;
  risk_level: string;
  status: string;
  requester_principal_id: string;
  required_quorum: number;
  resolution_id?: string | null;
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
    item.innerHTML = `
      <div class="list-item-title">${escapeHtml(approval.tool_name)} · step ${escapeHtml(approval.step_run_id)}</div>
      <div class="list-item-meta">Risk ${escapeHtml(approval.risk_level)} · requested by ${escapeHtml(approval.requester_principal_id)}</div>
      <div class="list-item-actions">
        <button class="button button-primary button-small" data-approval="approve" data-id="${escapeHtml(approval.id)}" type="button">Vote approve</button>
        <button class="button button-danger button-small" data-approval="reject" data-id="${escapeHtml(approval.id)}" type="button">Vote reject</button>
      </div>`;
    list.append(item);
  }
}

async function refreshWorkspace() {
  await Promise.all([loadTasks(), loadApprovals()]);
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
    if (button?.dataset.id && button.dataset.action) run(() => taskAction(button.dataset.action!, button.dataset.id!));
  });
  $("#approvals")!.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("button[data-approval]");
    if (button?.dataset.id) run(() => resolveApproval(button.dataset.id!, button.dataset.approval === "approve"));
  });
  showAuth();
  run(refreshSidecar);
});
