import { invoke } from "@tauri-apps/api/core";

let greetInputEl: HTMLInputElement | null;
let greetMsgEl: HTMLElement | null;
let sidecarMsgEl: HTMLElement | null;

async function greet() {
  if (greetInputEl && greetMsgEl) {
    greetMsgEl.textContent = await invoke("greet", { name: greetInputEl.value });
  }
}

async function checkSidecar() {
  if (!sidecarMsgEl) return;
  try {
    const status = await invoke("sidecar_status");
    const echo = await invoke("sidecar_echo", { message: "ping" });
    sidecarMsgEl.textContent = `Sidecar ${JSON.stringify(status)} | echo ${echo}`;
  } catch (error) {
    sidecarMsgEl.textContent = `Sidecar error: ${String(error)}`;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  greetInputEl = document.querySelector("#greet-input");
  greetMsgEl = document.querySelector("#greet-msg");
  sidecarMsgEl = document.querySelector("#sidecar-msg");
  document.querySelector("#greet-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void greet();
  });
  document.querySelector("#sidecar-check")?.addEventListener("click", () => void checkSidecar());
});
