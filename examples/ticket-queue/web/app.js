"use strict";

let tickets = [];
let selectedId = null;
let activeStatus = "all";
let searchTerm = "";

const listEl = document.getElementById("ticket-list");
const headingEl = document.getElementById("queue-heading");
const filterEl = document.getElementById("status-filter");
const searchEl = document.getElementById("queue-search");
const clearEl = document.getElementById("clear-search");
const detailEl = document.getElementById("detail");
const liveEl = document.getElementById("live-status");
const modalEl = document.getElementById("assign-modal");

function statusPill(status) {
  return `<span class="pill pill-${status}">${status}</span>`;
}

function visibleTickets() {
  const term = searchTerm.trim().toLowerCase();
  return tickets.filter(
    (t) =>
      (activeStatus === "all" || t.status === activeStatus) &&
      (term === "" ||
        t.title.toLowerCase().includes(term) ||
        t.id.toLowerCase().includes(term) ||
        // The requester is searchable *and* rendered on the row below. A match
        // on a field the queue does not show is indistinguishable from a bug:
        // the viewer sees a row survive a term that appears nowhere on it.
        t.requester.toLowerCase().includes(term))
  );
}

function renderList() {
  const shown = visibleTickets();
  headingEl.textContent = `Support queue (${shown.length})`;
  // An empty array maps to an empty string, which renders as blank space —
  // indistinguishable from a queue that failed to load. Say what happened.
  if (shown.length === 0) {
    listEl.innerHTML =
      '<li class="queue-empty">No tickets match this filter.</li>';
    return;
  }
  listEl.innerHTML = shown
    .map(
      (t) => `
      <li>
        <button class="ticket" type="button" data-id="${t.id}"
                aria-current="${t.id === selectedId}">
          <span class="ticket-id">${t.id}</span>
          <span class="ticket-text">
            <span class="ticket-title">${t.title}</span>
            <span class="ticket-requester">${t.requester}</span>
          </span>
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

filterEl.addEventListener("click", (ev) => {
  const button = ev.target.closest("button[data-status]");
  if (!button) return;
  activeStatus = button.dataset.status;
  for (const b of filterEl.querySelectorAll("button[data-status]")) {
    b.setAttribute("aria-pressed", String(b.dataset.status === activeStatus));
  }
  render();
});

// Only the list depends on the term — re-rendering the detail on every
// keystroke would replay its aria-live region for a panel that did not change.
searchEl.addEventListener("input", () => {
  searchTerm = searchEl.value;
  clearEl.hidden = searchEl.value === "";
  renderList();
});

clearEl.addEventListener("click", () => {
  searchEl.value = "";
  searchTerm = "";
  clearEl.hidden = true;
  renderList();
});

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
