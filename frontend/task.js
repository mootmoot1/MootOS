const elements = {
  createForm: document.querySelector("#taskCreateForm"),
  titleInput: document.querySelector("#taskTitleInput"),
  projectSelect: document.querySelector("#taskProjectSelect"),
  dueInput: document.querySelector("#taskDueInput"),
  statusFilter: document.querySelector("#taskStatusFilter"),
  projectFilter: document.querySelector("#taskProjectFilter"),
  refreshButton: document.querySelector("#refreshTasksButton"),
  summary: document.querySelector("#taskSummary"),
  success: document.querySelector("#taskSuccess"),
  error: document.querySelector("#taskError"),
  list: document.querySelector("#taskList"),
};

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

function clearBanners() {
  elements.error.hidden = true;
  elements.error.textContent = "";
  elements.success.hidden = true;
  elements.success.textContent = "";
}

function showSuccess(message) {
  elements.success.textContent = message;
  elements.success.hidden = false;
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

async function loadProjectOptions() {
  const projects = await apiRequest("/projects");

  [elements.projectSelect, elements.projectFilter].forEach((select) => {
    const keepValue = select.value;
    const placeholderCount = select === elements.projectFilter ? 1 : 1;
    while (select.options.length > placeholderCount) {
      select.remove(select.options.length - 1);
    }
    projects.forEach((project) => {
      const option = document.createElement("option");
      option.value = project.name;
      option.textContent = project.name;
      select.appendChild(option);
    });
    if ([...select.options].some((option) => option.value === keepValue)) {
      select.value = keepValue;
    }
  });
}

function taskCard(task) {
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
  const scope = task.project || "Global";
  const due = task.due_at ? `Due ${formatDate(task.due_at)}` : "No due date";
  const created = `Created ${formatDate(task.created_at)}`;
  meta.textContent = `${scope} · ${due} · ${created}`;

  card.append(header, meta);

  if (task.status === "open") {
    const actions = document.createElement("div");
    actions.className = "panel-card-actions";

    const completeButton = document.createElement("button");
    completeButton.className = "primary-button";
    completeButton.type = "button";
    completeButton.textContent = "Complete";
    completeButton.addEventListener("click", () => finishTask(task.id, "complete"));

    const cancelButton = document.createElement("button");
    cancelButton.className = "secondary-button";
    cancelButton.type = "button";
    cancelButton.textContent = "Cancel";
    cancelButton.addEventListener("click", () => finishTask(task.id, "cancel"));

    actions.append(completeButton, cancelButton);
    card.appendChild(actions);
  }

  return card;
}

async function finishTask(taskId, action) {
  clearBanners();
  try {
    await apiRequest(`/tasks/${encodeURIComponent(taskId)}/${action}`, { method: "POST" });
    showSuccess(action === "complete" ? "Task completed." : "Task cancelled.");
    await loadTasks();
  } catch (error) {
    showError(error.message);
  }
}

async function loadTasks() {
  const status = elements.statusFilter.value;
  const project = elements.projectFilter.value;
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }
  if (project) {
    params.set("project", project);
  }
  const query = params.toString() ? `?${params.toString()}` : "";

  elements.list.setAttribute("aria-busy", "true");
  try {
    const tasks = await apiRequest(`/tasks${query}`);
    elements.list.replaceChildren();

    if (!tasks.length) {
      const empty = document.createElement("div");
      empty.className = "panel-empty-state";
      empty.textContent = "No tasks match this view yet.";
      elements.list.appendChild(empty);
    } else {
      tasks.forEach((task) => elements.list.appendChild(taskCard(task)));
    }

    elements.summary.textContent = `${tasks.length} task${tasks.length === 1 ? "" : "s"} shown`;
  } catch (error) {
    showError(error.message);
    elements.summary.textContent = "Could not load tasks.";
  } finally {
    elements.list.setAttribute("aria-busy", "false");
  }
}

function dueInputToUtcIso(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

elements.createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearBanners();

  const title = elements.titleInput.value.trim();
  if (!title) {
    return;
  }

  const body = { title };
  if (elements.projectSelect.value) {
    body.project = elements.projectSelect.value;
  }
  const dueAt = dueInputToUtcIso(elements.dueInput.value);
  if (dueAt) {
    body.due_at = dueAt;
  }

  try {
    await apiRequest("/tasks", { method: "POST", body: JSON.stringify(body) });
    elements.titleInput.value = "";
    elements.dueInput.value = "";
    showSuccess("Task created.");
    await loadTasks();
  } catch (error) {
    showError(error.message);
  }
});

elements.statusFilter.addEventListener("change", loadTasks);
elements.projectFilter.addEventListener("change", loadTasks);
elements.refreshButton.addEventListener("click", loadTasks);

async function initialize() {
  try {
    await loadProjectOptions();
  } catch (error) {
    showError(error.message);
  }
  await loadTasks();
}

initialize();
