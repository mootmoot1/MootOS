const elements = {
  searchForm: document.querySelector("#memorySearchForm"),
  searchInput: document.querySelector("#memorySearchInput"),
  searchButton: document.querySelector("#searchMemoriesButton"),
  clearSearchButton: document.querySelector("#clearMemorySearchButton"),
  statusFilter: document.querySelector("#memoryStatusFilter"),
  projectFilter: document.querySelector("#memoryProjectFilter"),
  refreshButton: document.querySelector("#refreshMemoriesButton"),
  memoryList: document.querySelector("#memoryList"),
  memorySummary: document.querySelector("#memorySummary"),
  memorySuccess: document.querySelector("#memorySuccess"),
  memoryError: document.querySelector("#memoryError"),
  correctionDialog: document.querySelector("#memoryCorrectionDialog"),
  correctionForm: document.querySelector("#memoryCorrectionForm"),
  correctionCurrent: document.querySelector("#memoryCorrectionCurrent"),
  correctionContent: document.querySelector("#memoryCorrectionContent"),
  correctionError: document.querySelector("#memoryCorrectionError"),
  cancelCorrectionButton: document.querySelector("#cancelMemoryCorrectionButton"),
  dismissCorrectionButton: document.querySelector("#dismissMemoryCorrectionButton"),
  saveCorrectionButton: document.querySelector("#saveMemoryCorrectionButton"),
  lifecycleDialog: document.querySelector("#memoryLifecycleDialog"),
  lifecycleForm: document.querySelector("#memoryLifecycleForm"),
  lifecycleEyebrow: document.querySelector("#memoryLifecycleEyebrow"),
  lifecycleTitle: document.querySelector("#memoryLifecycleTitle"),
  lifecycleCurrent: document.querySelector("#memoryLifecycleCurrent"),
  lifecycleExplainer: document.querySelector("#memoryLifecycleExplainer"),
  lifecycleError: document.querySelector("#memoryLifecycleError"),
  cancelLifecycleButton: document.querySelector("#cancelMemoryLifecycleButton"),
  dismissLifecycleButton: document.querySelector("#dismissMemoryLifecycleButton"),
  confirmLifecycleButton: document.querySelector("#confirmMemoryLifecycleButton"),
};

let memoryRequestGeneration = 0;
let selectedMemory = null;
let selectedLifecycleMemory = null;
let selectedLifecycleAction = null;

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

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
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

function showSuccess(message) {
  elements.memorySuccess.textContent = message;
  elements.memorySuccess.hidden = false;
}

function clearSuccess() {
  elements.memorySuccess.textContent = "";
  elements.memorySuccess.hidden = true;
}

function showCorrectionError(message) {
  elements.correctionError.textContent = message;
  elements.correctionError.hidden = false;
}

function clearCorrectionError() {
  elements.correctionError.textContent = "";
  elements.correctionError.hidden = true;
}

function showLifecycleError(message) {
  elements.lifecycleError.textContent = message;
  elements.lifecycleError.hidden = false;
}

function clearLifecycleError() {
  elements.lifecycleError.textContent = "";
  elements.lifecycleError.hidden = true;
}

function setLoading(loading) {
  elements.searchInput.disabled = loading;
  elements.searchButton.disabled = loading;
  elements.clearSearchButton.disabled = loading;
  elements.statusFilter.disabled = loading;
  elements.projectFilter.disabled = loading;
  elements.refreshButton.disabled = loading;
  elements.memoryList.setAttribute("aria-busy", String(loading));

  if (!loading) {
    return;
  }

  const statusLabel = elements.statusFilter.value === "archived" ? "archived" : "active";
  elements.memorySummary.textContent = `Loading ${statusLabel} memories…`;
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

function setCorrectionSubmitting(submitting) {
  elements.correctionContent.disabled = submitting;
  elements.cancelCorrectionButton.disabled = submitting;
  elements.dismissCorrectionButton.disabled = submitting;
  elements.saveCorrectionButton.disabled = submitting;
  elements.saveCorrectionButton.textContent = submitting
    ? "Saving correction…"
    : "Save correction";
}

function setLifecycleSubmitting(submitting) {
  elements.cancelLifecycleButton.disabled = submitting;
  elements.dismissLifecycleButton.disabled = submitting;
  elements.confirmLifecycleButton.disabled = submitting;

  if (submitting) {
    elements.confirmLifecycleButton.textContent =
      selectedLifecycleAction === "restore" ? "Restoring…" : "Forgetting…";
    return;
  }

  elements.confirmLifecycleButton.textContent =
    selectedLifecycleAction === "restore" ? "Restore memory" : "Forget memory";
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

function openCorrectionDialog(memory) {
  selectedMemory = memory;
  clearCorrectionError();
  elements.correctionCurrent.textContent = memory.content;
  elements.correctionContent.value = memory.content;
  setCorrectionSubmitting(false);

  if (!elements.correctionDialog.open) {
    elements.correctionDialog.showModal();
  }
  elements.correctionContent.focus();
  elements.correctionContent.select();
}

function closeCorrectionDialog() {
  if (elements.correctionDialog.open) {
    elements.correctionDialog.close();
  }
  selectedMemory = null;
  elements.correctionForm.reset();
  clearCorrectionError();
  setCorrectionSubmitting(false);
}

function openLifecycleDialog(memory, action) {
  selectedLifecycleMemory = memory;
  selectedLifecycleAction = action;
  clearLifecycleError();
  elements.lifecycleCurrent.textContent = memory.content;

  if (action === "restore") {
    elements.lifecycleEyebrow.textContent = "Recoverable memory";
    elements.lifecycleTitle.textContent = "Restore this memory?";
    elements.lifecycleExplainer.textContent =
      "Restore returns this memory to active status so it can appear in normal recall again.";
    elements.confirmLifecycleButton.classList.remove("danger-button");
  } else {
    elements.lifecycleEyebrow.textContent = "Recoverable forget";
    elements.lifecycleTitle.textContent = "Forget this memory?";
    elements.lifecycleExplainer.textContent =
      "Forget removes this memory from normal recall and moves it to Archived. It can be restored later.";
    elements.confirmLifecycleButton.classList.add("danger-button");
  }

  setLifecycleSubmitting(false);
  if (!elements.lifecycleDialog.open) {
    elements.lifecycleDialog.showModal();
  }
  elements.confirmLifecycleButton.focus();
}

function closeLifecycleDialog() {
  if (elements.lifecycleDialog.open) {
    elements.lifecycleDialog.close();
  }
  selectedLifecycleMemory = null;
  selectedLifecycleAction = null;
  clearLifecycleError();
  elements.confirmLifecycleButton.classList.remove("danger-button");
  setLifecycleSubmitting(false);
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
    createMetaItem("Scope", isGlobal ? "Available across projects" : "Project focus"),
    createMetaItem("Project", memory.project || "Global"),
    createMetaItem("Source", humanizeMemoryType(memory.memory_type)),
    createMetaItem("Version", memory.replaces_memory_id ? "Corrected" : "Original"),
    createMetaItem("Status", memory.status === "archived" ? "Archived" : "Active"),
  );

  const actions = document.createElement("div");
  actions.className = "memory-card-actions";

  if (memory.status === "archived") {
    const restoreButton = document.createElement("button");
    restoreButton.className = "secondary-button memory-restore-button";
    restoreButton.type = "button";
    restoreButton.textContent = "Restore";
    restoreButton.addEventListener("click", () =>
      openLifecycleDialog(memory, "restore")
    );
    actions.appendChild(restoreButton);
  } else {
    const correctButton = document.createElement("button");
    correctButton.className = "secondary-button memory-correct-button";
    correctButton.type = "button";
    correctButton.textContent = "Correct";
    correctButton.addEventListener("click", () => openCorrectionDialog(memory));

    const forgetButton = document.createElement("button");
    forgetButton.className = "secondary-button danger-button memory-forget-button";
    forgetButton.type = "button";
    forgetButton.textContent = "Forget";
    forgetButton.addEventListener("click", () =>
      openLifecycleDialog(memory, "archive")
    );

    actions.append(correctButton, forgetButton);
  }

  header.append(scope, created);
  card.append(header, content, metadata, actions);
  return card;
}

function selectedFilterLabel() {
  const selected = elements.projectFilter.selectedOptions[0];
  return selected ? selected.textContent : "All memories";
}

function selectedStatusLabel() {
  return elements.statusFilter.value === "archived" ? "archived" : "active";
}

function selectedSearchQuery() {
  return elements.searchInput.value.trim();
}

function renderEmptyState() {
  const empty = document.createElement("section");
  empty.className = "memory-empty-state";

  const title = document.createElement("h2");
  const statusLabel = selectedStatusLabel();
  const searchQuery = selectedSearchQuery();
  if (searchQuery) {
    title.textContent = "No matching memories";
  } else {
    title.textContent = statusLabel === "archived" ? "No archived memories" : "No memories found";
  }

  const message = document.createElement("p");
  const filterValue = elements.projectFilter.value;
  if (searchQuery) {
    message.textContent = `No ${statusLabel} memories matched “${searchQuery}” in ${selectedFilterLabel()}.`;
  } else if (statusLabel === "archived") {
    message.textContent =
      "Forgotten memories will appear here and can be restored to normal recall.";
  } else if (filterValue === "global") {
    message.textContent = "No active global memories have been saved yet.";
  } else if (filterValue.startsWith("project:")) {
    message.textContent = `No active memories have been saved in ${selectedFilterLabel()} yet.`;
  } else {
    message.textContent = "Save a fact through chat, then return here to review it.";
  }

  empty.append(title, message);
  elements.memoryList.replaceChildren(empty);
}

function renderMemories(memories) {
  const count = memories.length;
  const statusLabel = selectedStatusLabel();
  const searchQuery = selectedSearchQuery();
  const searchLabel = searchQuery ? ` · Search: “${searchQuery}”` : "";
  elements.memorySummary.textContent = `${count} ${statusLabel} ${count === 1 ? "memory" : "memories"} · ${selectedFilterLabel()}${searchLabel}`;
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

async function loadMemories({ preserveSuccess = false, throwOnError = false } = {}) {
  const requestGeneration = ++memoryRequestGeneration;
  const filterValue = elements.projectFilter.value;
  const memoryStatus = elements.statusFilter.value;
  const searchQuery = selectedSearchQuery();

  setLoading(true);
  clearError();
  if (!preserveSuccess) {
    clearSuccess();
  }

  try {
    const params = new URLSearchParams({ status: memoryStatus });
    if (filterValue.startsWith("project:")) {
      params.set("project", filterValue.slice("project:".length));
    }
    if (searchQuery) {
      params.set("q", searchQuery);
    }

    let memories = await apiRequest(`/memories?${params.toString()}`);
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
    if (throwOnError) {
      throw error;
    }
  } finally {
    if (requestGeneration === memoryRequestGeneration) {
      setLoading(false);
    }
  }
}

async function reloadAfterMutation(successMessage) {
  clearSuccess();
  try {
    await loadMemories({ preserveSuccess: true, throwOnError: true });
    showSuccess(successMessage);
  } catch (error) {
    clearSuccess();
    showError("The change was saved, but the memory list could not be refreshed. Press Refresh to try again.");
  }
}

async function submitCorrection(event) {
  event.preventDefault();
  clearCorrectionError();

  if (!selectedMemory) {
    showCorrectionError("Select a memory before saving a correction.");
    return;
  }

  const correctedContent = elements.correctionContent.value.trim();
  if (!correctedContent) {
    showCorrectionError("Corrected memory content cannot be empty.");
    return;
  }
  if (correctedContent === selectedMemory.content.trim()) {
    showCorrectionError("Change the content before saving a correction.");
    return;
  }

  setCorrectionSubmitting(true);
  try {
    await apiRequest(`/memories/${encodeURIComponent(selectedMemory.id)}/corrections`, {
      method: "POST",
      body: JSON.stringify({ content: correctedContent }),
    });
    closeCorrectionDialog();
    await reloadAfterMutation(
      "Correction saved. The previous version remains preserved in history."
    );
  } catch (error) {
    showCorrectionError(error.message);
    setCorrectionSubmitting(false);
  }
}

async function submitLifecycle(event) {
  event.preventDefault();
  clearLifecycleError();

  if (!selectedLifecycleMemory || !selectedLifecycleAction) {
    showLifecycleError("Select a memory before continuing.");
    return;
  }

  const memoryId = selectedLifecycleMemory.id;
  const action = selectedLifecycleAction;
  setLifecycleSubmitting(true);

  try {
    await apiRequest(`/memories/${encodeURIComponent(memoryId)}/${action}`, {
      method: "POST",
    });
    closeLifecycleDialog();
    await reloadAfterMutation(
      action === "restore"
        ? "Memory restored to active recall."
        : "Memory moved to Archived and removed from normal recall."
    );
  } catch (error) {
    showLifecycleError(error.message);
    setLifecycleSubmitting(false);
  }
}

function submitSearch(event) {
  event.preventDefault();
  loadMemories();
}

function clearSearch() {
  if (!elements.searchInput.value) {
    return;
  }
  elements.searchInput.value = "";
  loadMemories();
  elements.searchInput.focus();
}

async function initialize() {
  setLoading(true);
  clearError();
  clearSuccess();

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

elements.searchForm.addEventListener("submit", submitSearch);
elements.clearSearchButton.addEventListener("click", clearSearch);
elements.statusFilter.addEventListener("change", loadMemories);
elements.projectFilter.addEventListener("change", loadMemories);
elements.refreshButton.addEventListener("click", loadMemories);
elements.correctionForm.addEventListener("submit", submitCorrection);
elements.cancelCorrectionButton.addEventListener("click", closeCorrectionDialog);
elements.dismissCorrectionButton.addEventListener("click", closeCorrectionDialog);
elements.correctionDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeCorrectionDialog();
});
elements.lifecycleForm.addEventListener("submit", submitLifecycle);
elements.cancelLifecycleButton.addEventListener("click", closeLifecycleDialog);
elements.dismissLifecycleButton.addEventListener("click", closeLifecycleDialog);
elements.lifecycleDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeLifecycleDialog();
});

initialize();
