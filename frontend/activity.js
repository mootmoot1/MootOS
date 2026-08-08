const elements = {
  error: document.querySelector("#activityError"),
  runsSummary: document.querySelector("#runsSummary"),
  runsList: document.querySelector("#runsList"),
  tasksSummary: document.querySelector("#tasksSummary"),
  tasksList: document.querySelector("#tasksList"),
  memoriesSummary: document.querySelector("#memoriesSummary"),
  memoriesList: document.querySelector("#memoriesList"),
};

const RECENT_MEMORY_LIMIT = 15;

function normalizeError(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || item.message || "Invalid request").join(" ");
  }
  return fallback;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(normalizeError(payload?.detail, `Request failed with status ${response.status}`));
  }

  return payload?.data ?? payload;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
}

function formatDate(value) {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown time";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function emptyCard(text) {
  const empty = document.createElement("div");
  empty.className = "panel-empty-state";
  empty.textContent = text;
  return empty;
}

function renderRuns(runs) {
  elements.runsList.replaceChildren();
  if (!runs.length) {
    elements.runsList.appendChild(emptyCard("No recorded AI runs yet."));
    return;
  }

  runs.forEach((run) => {
    const card = document.createElement("article");
    card.className = "panel-card";

    const header = document.createElement("div");
    header.className = "panel-card-header";

    const title = document.createElement("h3");
    title.className = "panel-card-title";
    title.textContent = run.provider && run.model ? `${run.provider} · ${run.model}` : "Model run";

    const badge = document.createElement("span");
    badge.className = `panel-badge ${run.status}`;
    badge.textContent = run.status;

    header.append(title, badge);

    const meta = document.createElement("p");
    meta.className = "panel-card-meta";
    const duration = run.duration_ms != null ? `${run.duration_ms} ms` : "in progress";
    const started = formatDate(run.started_at);
    meta.textContent = `Started ${started} · ${duration}${run.error_class ? ` · ${run.error_class}` : ""}`;

    card.append(header, meta);
    elements.runsList.appendChild(card);
  });
}

function renderTasks(tasks) {
  elements.tasksList.replaceChildren();
  if (!tasks.length) {
    elements.tasksList.appendChild(emptyCard("No tasks yet."));
    return;
  }

  tasks.forEach((task) => {
    const card = document.createElement("article");
    card.className = "panel-card";

    const header = document.createElement("div");
    header.className = "panel-card-header";

    const title = document.createElement("h3");
    title.className = "panel-card-title";
    title.textContent = task.title;

    const badge = document.createElement("span");
    badge.className = `panel-badge ${task.status}`;
    badge.textContent = task.status;

    header.append(title, badge);

    const meta = document.createElement("p");
    meta.className = "panel-card-meta";
    meta.textContent = `${task.project || "Global"} · Created ${formatDate(task.created_at)}`;

    card.append(header, meta);
    elements.tasksList.appendChild(card);
  });
}

function renderMemories(memories) {
  elements.memoriesList.replaceChildren();
  if (!memories.length) {
    elements.memoriesList.appendChild(emptyCard("No memories yet."));
    return;
  }

  memories.slice(0, RECENT_MEMORY_LIMIT).forEach((memory) => {
    const card = document.createElement("article");
    card.className = "panel-card";

    const header = document.createElement("div");
    header.className = "panel-card-header";

    const title = document.createElement("h3");
    title.className = "panel-card-title";
    title.textContent = memory.content;

    const badge = document.createElement("span");
    badge.className = "panel-badge";
    badge.textContent = memory.memory_type || "memory";

    header.append(title, badge);

    const meta = document.createElement("p");
    meta.className = "panel-card-meta";
    meta.textContent = `${memory.project || "Global"} · Saved ${formatDate(memory.created_at)}`;

    card.append(header, meta);
    elements.memoriesList.appendChild(card);
  });
}

async function loadRuns() {
  try {
    const runs = await apiRequest("/activity/runs?limit=25");
    renderRuns(runs);
    elements.runsSummary.textContent = `${runs.length} recent run${runs.length === 1 ? "" : "s"}`;
  } catch (error) {
    showError(error.message);
    elements.runsSummary.textContent = "Could not load recent runs.";
  }
}

async function loadTasks() {
  try {
    const tasks = await apiRequest("/tasks?limit=15");
    renderTasks(tasks);
    elements.tasksSummary.textContent = `${tasks.length} recent task${tasks.length === 1 ? "" : "s"}`;
  } catch (error) {
    showError(error.message);
    elements.tasksSummary.textContent = "Could not load recent tasks.";
  }
}

async function loadMemories() {
  try {
    const memories = await apiRequest("/memories?status=active");
    const recent = memories.slice(0, RECENT_MEMORY_LIMIT);
    renderMemories(memories);
    elements.memoriesSummary.textContent =
      `${recent.length} of ${memories.length} active memories shown`;
  } catch (error) {
    showError(error.message);
    elements.memoriesSummary.textContent = "Could not load recent memories.";
  }
}

Promise.all([loadRuns(), loadTasks(), loadMemories()]);
