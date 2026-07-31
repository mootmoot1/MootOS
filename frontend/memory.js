const elements = {
  projectFilter: document.querySelector("#memoryProjectFilter"),
  refreshButton: document.querySelector("#refreshMemoriesButton"),
  memoryList: document.querySelector("#memoryList"),
  memorySummary: document.querySelector("#memorySummary"),
  memoryError: document.querySelector("#memoryError"),
};

let memoryRequestGeneration = 0;

function normalizeError(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item.msg || item.message || "Invalid request")
      .join(" ");
  }

  return fallback;
}

async function apiRequest(path) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(
      normalizeError(payload?.detail, `Request failed with status ${response.status}`)
    );
  }

  return payload?.data ?? payload;
}

function formatDate(value) {
  if (!value) {
    return "Unknown date";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown date";
  }

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function humanizeMemoryType(value) {
  if (!value) {
    return "Uncategorized";
  }

  if (value === "explicit_chat") {
    return "Chat save";
  }

  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function showError(message) {
  elements.memoryError.textContent = message;
  elements.memoryError.hidden = false;
}

function clearError() {
  elements.memoryError.textContent = "";
  elements.memoryError.hidden = true;
}

function setLoading(loading) {
  elements.projectFilter.disabled = loading;
  elements.refreshButton.disabled = loading;
  elements.memoryList.setAttribute("aria-busy", String(loading));

  if (!loading) {
    return;
  }

  elements.memorySummary.textContent = "Loading memories…";
  const loadingState = document.createElement("div");
  loadingState.className = "memory-loading-state";

  const dot = document.createElement("div");
  dot.className = "memory-loading-dot";
  dot.setAttribute("aria-hidden", "true");

  const message = document.createElement("p");
  message.textContent = "Loading saved memories…";

  loadingState.append(dot, message);
  elements.memoryList.replaceChildren(loadingState);
}

function createMetaItem(label, value) {
  const item = document.createElement("div");
  item.className = "memory-meta-item";

  const term = document.createElement("span");
  term.className = "memory-meta-label";
  term.textContent = label;

  const detail = document.createElement("span");
  detail.className = "memory-meta-value";
  detail.textContent = value;

  item.append(term, detail);
  return item;
}

function renderMemory(memory) {
  const card = document.createElement("article");
  card.className = "memory-card";

  const header = document.createElement("div");
  header.className = "memory-card-header";

  const scope = document.createElement("span");
  const isGlobal = !memory.project;
  scope.className = `memory-scope-badge ${isGlobal ? "global" : "project"}`;
  scope.textContent = isGlobal ? "Global" : memory.project;

  const created = document.createElement("time");
  created.className = "memory-card-date";
  created.dateTime = memory.created_at || "";
  created.textContent = formatDate(memory.created_at);

  const content = document.createElement("p");
  content.className = "memory-card-content";
  content.textContent = memory.content;

  const metadata = document.createElement("div");
  metadata.className = "memory-meta-grid";
  metadata.append(
    createMetaItem("Scope", isGlobal ? "Available across projects" : "Project only"),
    createMetaItem("Project", memory.project || "Global"),
    createMetaItem("Source", humanizeMemoryType(memory.memory_type)),
  );

  header.append(scope, created);
  card.append(header, content, metadata);
  return card;
}

function selectedFilterLabel() {
  const selected = elements.projectFilter.selectedOptions[0];
  return selected ? selected.textContent : "All memories";
}

function renderEmptyState() {
  const empty = document.createElement("section");
  empty.className = "memory-empty-state";

  const title = document.createElement("h2");
  title.textContent = "No memories found";

  const message = document.createElement("p");
  const filterValue = elements.projectFilter.value;
  if (filterValue === "global") {
    message.textContent = "No global memories have been saved yet.";
  } else if (filterValue.startsWith("project:")) {
    message.textContent = `No memories have been saved in ${selectedFilterLabel()} yet.`;
  } else {
    message.textContent = "Save a fact through chat, then return here to review it.";
  }

  empty.append(title, message);
  elements.memoryList.replaceChildren(empty);
}

function renderMemories(memories) {
  const count = memories.length;
  elements.memorySummary.textContent = `${count} ${count === 1 ? "memory" : "memories"} · ${selectedFilterLabel()}`;
  elements.memoryList.replaceChildren();

  if (!count) {
    renderEmptyState();
    return;
  }

  memories.forEach((memory) => {
    elements.memoryList.appendChild(renderMemory(memory));
  });
}

async function loadProjects() {
  const projects = await apiRequest("/projects");

  projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = `project:${project.name}`;
    option.textContent = project.name;
    elements.projectFilter.appendChild(option);
  });
}

async function loadMemories() {
  const requestGeneration = ++memoryRequestGeneration;
  const filterValue = elements.projectFilter.value;

  setLoading(true);
  clearError();

  try {
    let path = "/memories";

    if (filterValue.startsWith("project:")) {
      const project = filterValue.slice("project:".length);
      path += `?project=${encodeURIComponent(project)}`;
    }

    let memories = await apiRequest(path);
    if (requestGeneration !== memoryRequestGeneration) {
      return;
    }

    if (filterValue === "global") {
      memories = memories.filter((memory) => !memory.project);
    }

    renderMemories(memories);
  } catch (error) {
    if (requestGeneration !== memoryRequestGeneration) {
      return;
    }

    elements.memorySummary.textContent = "Unable to load memories";
    elements.memoryList.replaceChildren();
    showError(error.message);
  } finally {
    if (requestGeneration === memoryRequestGeneration) {
      setLoading(false);
    }
  }
}

async function initialize() {
  setLoading(true);
  clearError();

  try {
    await loadProjects();
    await loadMemories();
  } catch (error) {
    elements.memorySummary.textContent = "Unable to load memories";
    elements.memoryList.replaceChildren();
    showError(error.message);
    setLoading(false);
  }
}

elements.projectFilter.addEventListener("change", loadMemories);
elements.refreshButton.addEventListener("click", loadMemories);

initialize();
