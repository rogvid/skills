"use strict";

let tickets = [];
let selectedId = null;

const listEl = document.getElementById("ticket-list");
const detailEl = document.getElementById("detail");
const liveEl = document.getElementById("live-status");
const modalEl = document.getElementById("assign-modal");

function statusPill(status) {
  return `<span class="pill pill-${status}">${status}</span>`;
}

function renderList() {
  listEl.innerHTML = tickets
    .map(
      (t) => `
      <li>
        <button class="ticket" type="button" data-id="${t.id}"
                aria-current="${t.id === selectedId}">
          <span class="ticket-id">${t.id}</span>
          <span class="ticket-title">${t.title}</span>
          ${statusPill(t.status)}
        </button>
      </li>`
    )
    .join("");
}

function renderDetail() {
  const t = tickets.find((x) => x.id === selectedId);
  if (!t) {
    detailEl.innerHTML =
      '<p class="detail-empty">Select a ticket to see the detail.</p>';
    return;
  }
  detailEl.innerHTML = `
    <h2>${t.title}</h2>
    ${statusPill(t.status)}
    <dl>
      <dt>Ticket</dt><dd>${t.id}</dd>
      <dt>Requester</dt>
      <dd class="requester">
        <span class="requester-email">${t.requester}</span>
        <button class="copy-email" type="button"
                title="Copy ${t.requester}">Copy</button>
      </dd>
      <dt>Opened</dt><dd>${t.opened}</dd>
    </dl>
    <p class="detail-body">${t.body}</p>
    <details>
      <summary>Raw payload</summary>
      <pre>${JSON.stringify(t, null, 2)}</pre>
    </details>
    <div class="detail-actions">
      <button id="open-assign" type="button">Assign…</button>
    </div>`;
}

function render() {
  renderList();
  renderDetail();
}

listEl.addEventListener("click", (ev) => {
  const button = ev.target.closest(".ticket");
  if (!button) return;
  selectedId = button.dataset.id;
  render();
});

detailEl.addEventListener("click", (ev) => {
  if (ev.target.closest(".copy-email")) {
    liveEl.textContent = "Requester address copied.";
    return;
  }
  if (ev.target.closest("#open-assign")) {
    modalEl.hidden = false;
  }
});

document.getElementById("assign-cancel").addEventListener("click", () => {
  modalEl.hidden = true;
});

document.getElementById("assign-confirm").addEventListener("click", () => {
  modalEl.hidden = true;
  liveEl.textContent = "Ticket assigned.";
});

fetch("/api/tickets")
  .then((r) => r.json())
  .then((data) => {
    tickets = data;
    render();
  });
