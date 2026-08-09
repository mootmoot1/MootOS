const elements = {
  error: document.querySelector("#settingsError"),
  grid: document.querySelector("#settingsGrid"),
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

function statusCard(label, value, note) {
  const card = document.createElement("div");
  card.className = "panel-status-card";

  const labelEl = document.createElement("span");
  labelEl.className = "panel-field-label";
  labelEl.textContent = label;

  const valueEl = document.createElement("p");
  valueEl.className = "panel-status-value";
  valueEl.textContent = value;

  card.append(labelEl, valueEl);

  if (note) {
    const noteEl = document.createElement("p");
    noteEl.className = "panel-status-note";
    noteEl.textContent = note;
    card.appendChild(noteEl);
  }

  return card;
}

async function initialize() {
  try {
    const status = await apiRequest("/settings/status");
    elements.grid.replaceChildren(
      statusCard("Model provider", status.provider || "Not configured"),
      statusCard(
        "Model",
        status.model || "Not configured",
        status.provider ? null : "Set AI_PROVIDER and a matching model variable in Railway."
      ),
      statusCard("Database schema version", `Schema ${status.schema_version}`),
      statusCard("MootOS version", status.app_version)
    );
  } catch (error) {
    showError(error.message);
    elements.grid.replaceChildren();
  }
}

initialize();
