const state = {
  conversationId: null,
  project: "",
  sending: false,
};

const elements = {
  sidebar: document.querySelector("#sidebar"),
  sidebarBackdrop: document.querySelector("#sidebarBackdrop"),
  openSidebar: document.querySelector("#openSidebar"),
  closeSidebar: document.querySelector("#closeSidebar"),
  newChatButton: document.querySelector("#newChatButton"),
  headerNewChatButton: document.querySelector("#headerNewChatButton"),
  projectSelect: document.querySelector("#projectSelect"),
  refreshHistoryButton: document.querySelector("#refreshHistoryButton"),
  conversationList: document.querySelector("#conversationList"),
  conversationTitle: document.querySelector("#conversationTitle"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  messages: document.querySelector("#messages"),
  emptyState: document.querySelector("#emptyState"),
  errorBanner: document.querySelector("#errorBanner"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
};

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
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
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

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.hidden = false;
}

function clearError() {
  elements.errorBanner.hidden = true;
  elements.errorBanner.textContent = "";
}

function setServerStatus(online, text) {
  elements.statusDot.classList.toggle("online", online);
  elements.statusDot.classList.toggle("offline", !online);
  elements.statusText.textContent = text;
}

function openSidebar() {
  elements.sidebar.classList.add("open");
  elements.sidebarBackdrop.hidden = false;
}

function closeSidebar() {
  elements.sidebar.classList.remove("open");
  elements.sidebarBackdrop.hidden = true;
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
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function clearMessages() {
  elements.messages.querySelectorAll(".message-row").forEach((node) => node.remove());
}

function setEmptyState(visible) {
  elements.emptyState.hidden = !visible;
}

function addMessage(role, content, options = {}) {
  setEmptyState(false);

  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  if (options.id) {
    row.id = options.id;
  }

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  if (options.typing) {
    bubble.setAttribute("aria-label", "MootOS is thinking");
    const typing = document.createElement("span");
    typing.className = "typing";
    typing.innerHTML = "<span></span><span></span><span></span>";
    bubble.appendChild(typing);
  } else {
    bubble.textContent = content;
  }

  row.appendChild(bubble);
  elements.messages.appendChild(row);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return row;
}

const TOOL_DISPLAY_NAMES = {
  "tasks.create": "Create task",
};

const OPERATION_ARGUMENT_LABELS = {
  title: "Title",
  project: "Project",
  due_at: "Due",
};

function toolDisplayName(toolName) {
  return TOOL_DISPLAY_NAMES[toolName] || toolName;
}

function formatOperationArgumentLabel(key) {
  if (OPERATION_ARGUMENT_LABELS[key]) {
    return OPERATION_ARGUMENT_LABELS[key];
  }
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatOperationArgumentValue(key, value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (key === "due_at") {
    return formatDate(value) || String(value);
  }
  return String(value);
}

function setApprovalCardStatus(statusElement, variant, text) {
  statusElement.hidden = false;
  statusElement.textContent = text;
  statusElement.classList.remove("succeeded", "rejected", "failed");
  statusElement.classList.add(variant);
}

function addApprovalCard(operation) {
  setEmptyState(false);

  const row = document.createElement("div");
  row.className = "message-row assistant";

  const card = document.createElement("div");
  card.className = "approval-card";

  const eyebrow = document.createElement("p");
  eyebrow.className = "approval-card-eyebrow";
  eyebrow.textContent = "Needs your approval";

  const title = document.createElement("p");
  title.className = "approval-card-title";
  title.textContent = toolDisplayName(operation.tool_name);

  const details = document.createElement("dl");
  details.className = "approval-card-details";
  Object.entries(operation.arguments || {}).forEach(([key, value]) => {
    const term = document.createElement("dt");
    term.textContent = formatOperationArgumentLabel(key);
    const definition = document.createElement("dd");
    definition.textContent = formatOperationArgumentValue(key, value);
    details.append(term, definition);
  });

  const status = document.createElement("p");
  status.className = "approval-card-status";
  status.hidden = true;

  const actions = document.createElement("div");
  actions.className = "approval-card-actions";

  const approveButton = document.createElement("button");
  approveButton.type = "button";
  approveButton.className = "primary-button approval-approve-button";
  approveButton.textContent = "Approve";

  const rejectButton = document.createElement("button");
  rejectButton.type = "button";
  rejectButton.className = "text-button approval-reject-button";
  rejectButton.textContent = "Reject";

  let deciding = false;
  async function decide(action) {
    if (deciding) {
      return;
    }
    deciding = true;
    approveButton.disabled = true;
    rejectButton.disabled = true;

    try {
      const updated = await apiRequest(
        `/tool-operations/${encodeURIComponent(operation.id)}/${action}`,
        { method: "POST" }
      );
      actions.remove();
      if (updated.status === "succeeded") {
        setApprovalCardStatus(status, "succeeded", "Approved — this action ran successfully.");
      } else if (updated.status === "rejected") {
        setApprovalCardStatus(status, "rejected", "Rejected — nothing was run.");
      } else {
        setApprovalCardStatus(status, "failed", "This action did not complete. Nothing was run.");
      }
    } catch (error) {
      deciding = false;
      approveButton.disabled = false;
      rejectButton.disabled = false;
      setApprovalCardStatus(status, "failed", error.message);
    }
  }

  approveButton.addEventListener("click", () => decide("approve"));
  rejectButton.addEventListener("click", () => decide("reject"));

  actions.append(approveButton, rejectButton);
  card.append(eyebrow, title, details, status, actions);
  row.appendChild(card);
  elements.messages.appendChild(row);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return row;
}

function autoResizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(
    elements.messageInput.scrollHeight,
    180
  )}px`;
}

function setBusy(busy) {
  state.sending = busy;
  elements.sendButton.disabled = busy;
  elements.messageInput.disabled = busy;
  elements.projectSelect.disabled = busy || Boolean(state.conversationId);
}

function startNewChat(options = {}) {
  state.conversationId = null;
  clearMessages();
  setEmptyState(true);
  clearError();
  elements.conversationTitle.textContent = "New conversation";
  elements.projectSelect.disabled = false;
  elements.conversationList
    .querySelectorAll(".conversation-button")
    .forEach((button) => button.classList.remove("active"));

  if (!options.keepProject) {
    state.project = elements.projectSelect.value;
  }

  localStorage.removeItem("mootosConversationId");
  elements.messageInput.focus();
  closeSidebar();
}

function renderConversationHistory(conversations) {
  elements.conversationList.replaceChildren();

  if (!conversations.length) {
    const empty = document.createElement("p");
    empty.className = "muted small";
    empty.textContent = "No conversations yet.";
    elements.conversationList.appendChild(empty);
    return;
  }

  conversations.forEach((conversation) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-button";
    button.dataset.conversationId = conversation.id;
    button.classList.toggle("active", conversation.id === state.conversationId);

    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title || "New conversation";

    const meta = document.createElement("span");
    meta.className = "conversation-meta";
    const project = conversation.project || "No project";
    const date = formatDate(conversation.updated_at);
    meta.textContent = date ? `${project} · ${date}` : project;

    button.append(title, meta);
    button.addEventListener("click", () => loadConversation(conversation.id));
    elements.conversationList.appendChild(button);
  });
}

async function loadProjects() {
  const projects = await apiRequest("/projects");
  const currentValue = elements.projectSelect.value;

  projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.name;
    option.textContent = project.name;
    elements.projectSelect.appendChild(option);
  });

  if ([...elements.projectSelect.options].some((option) => option.value === currentValue)) {
    elements.projectSelect.value = currentValue;
  }
}

async function loadConversationHistory() {
  const selectedProject = elements.projectSelect.value;
  const query = selectedProject
    ? `?project=${encodeURIComponent(selectedProject)}`
    : "";
  const conversations = await apiRequest(`/conversations${query}`);
  renderConversationHistory(conversations);
  return conversations;
}

async function loadConversation(conversationId) {
  clearError();

  try {
    const conversation = await apiRequest(
      `/conversations/${encodeURIComponent(conversationId)}`
    );
    state.conversationId = conversation.id;
    state.project = conversation.project || "";
    elements.projectSelect.value = state.project;
    elements.projectSelect.disabled = true;
    elements.conversationTitle.textContent =
      conversation.title || "New conversation";

    clearMessages();
    conversation.messages.forEach((message) => {
      addMessage(message.role, message.content);
    });
    setEmptyState(conversation.messages.length === 0);

    localStorage.setItem("mootosConversationId", conversation.id);
    await loadConversationHistory();
    closeSidebar();
  } catch (error) {
    showError(error.message);
  }
}

async function sendMessage(message) {
  if (state.sending || !message.trim()) {
    return;
  }

  clearError();
  const cleanMessage = message.trim();
  const userRow = addMessage("user", cleanMessage);
  const typingRow = addMessage("assistant", "", {
    id: "typingMessage",
    typing: true,
  });

  elements.messageInput.value = "";
  autoResizeInput();
  setBusy(true);

  const requestBody = { message: cleanMessage };
  if (state.conversationId) {
    requestBody.conversation_id = state.conversationId;
  } else if (elements.projectSelect.value) {
    requestBody.project = elements.projectSelect.value;
  }

  let result;
  try {
    result = await apiRequest("/chat", {
      method: "POST",
      body: JSON.stringify(requestBody),
    });
  } catch (error) {
    typingRow.remove();
    userRow.remove();
    elements.messageInput.value = cleanMessage;
    autoResizeInput();
    setEmptyState(elements.messages.querySelectorAll(".message-row").length === 0);
    showError(error.message);
    setBusy(false);
    elements.messageInput.focus();
    return;
  }

  try {
    typingRow.remove();
    state.conversationId = result.conversation_id;
    state.project = result.project || "";
    elements.projectSelect.value = state.project;
    elements.projectSelect.disabled = true;
    elements.conversationTitle.textContent =
      elements.conversationTitle.textContent === "New conversation"
        ? cleanMessage.slice(0, 80)
        : elements.conversationTitle.textContent;

    addMessage("assistant", result.assistant_message.content);
    if (result.approval_required && result.operation) {
      addApprovalCard(result.operation);
    }
    localStorage.setItem("mootosConversationId", state.conversationId);

    try {
      await loadConversationHistory();
    } catch (error) {
      showError(
        "Message was saved, but the conversation list could not refresh. " +
          "Refresh the page to reload it."
      );
    }
  } finally {
    setBusy(false);
    elements.messageInput.focus();
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) {
      throw new Error("Server unavailable");
    }
    setServerStatus(true, "Online");
  } catch (error) {
    setServerStatus(false, "Offline");
  }
}

async function initialize() {
  try {
    await Promise.all([loadProjects(), checkHealth()]);
    const conversations = await loadConversationHistory();
    const savedConversationId = localStorage.getItem("mootosConversationId");

    if (
      savedConversationId &&
      conversations.some((conversation) => conversation.id === savedConversationId)
    ) {
      await loadConversation(savedConversationId);
    } else {
      startNewChat({ keepProject: true });
    }
  } catch (error) {
    setServerStatus(false, "Setup error");
    showError(error.message);
  }
}

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(elements.messageInput.value);
});

elements.messageInput.addEventListener("input", autoResizeInput);
elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(elements.messageInput.value);
  }
});

elements.projectSelect.addEventListener("change", async () => {
  state.project = elements.projectSelect.value;
  startNewChat({ keepProject: true });
  try {
    await loadConversationHistory();
  } catch (error) {
    showError(error.message);
  }
});

elements.newChatButton.addEventListener("click", () => startNewChat());
elements.headerNewChatButton.addEventListener("click", () => startNewChat());
elements.refreshHistoryButton.addEventListener("click", async () => {
  try {
    await loadConversationHistory();
  } catch (error) {
    showError(error.message);
  }
});

elements.openSidebar.addEventListener("click", openSidebar);
elements.closeSidebar.addEventListener("click", closeSidebar);
elements.sidebarBackdrop.addEventListener("click", closeSidebar);

document.querySelectorAll(".starter").forEach((button) => {
  button.addEventListener("click", () => {
    elements.messageInput.value = button.textContent.trim();
    autoResizeInput();
    elements.messageInput.focus();
  });
});

initialize();
