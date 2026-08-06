const profileJsonInput = document.getElementById("profileJsonInput");
const profileFileInput = document.getElementById("profileFileInput");
const profileFileName = document.getElementById("profileFileName");
const profileInputError = document.getElementById("profileInputError");
const profileImportError = document.getElementById("profileImportError");
const profileSuccess = document.getElementById("profileSuccess");
const previewProfileButton = document.getElementById("previewProfileButton");
const clearProfileButton = document.getElementById("clearProfileButton");
const importProfileButton = document.getElementById("importProfileButton");
const profilePreviewEmpty = document.getElementById("profilePreviewEmpty");
const profilePreviewContent = document.getElementById("profilePreviewContent");
const profileCounts = document.getElementById("profileCounts");
const profileReadySection = document.getElementById("profileReadySection");
const profileReadyList = document.getElementById("profileReadyList");
const profileActiveSection = document.getElementById("profileActiveSection");
const profileActiveList = document.getElementById("profileActiveList");
const profileBlockedSection = document.getElementById("profileBlockedSection");
const profileBlockedList = document.getElementById("profileBlockedList");
const profileConfirmDialog = document.getElementById("profileConfirmDialog");
const profileConfirmForm = document.getElementById("profileConfirmForm");
const profileConfirmSummary = document.getElementById("profileConfirmSummary");
const cancelProfileImportButton = document.getElementById("cancelProfileImportButton");
const confirmProfileImportButton = document.getElementById("confirmProfileImportButton");

let reviewedManifest = null;
let reviewedPreview = null;

function hideBanner(element) {
  element.hidden = true;
  element.textContent = "";
}

function showBanner(element, message) {
  element.textContent = message;
  element.hidden = false;
}

function setBusy(button, busy, busyText, normalText) {
  button.disabled = busy;
  button.textContent = busy ? busyText : normalText;
}

function parseManifest() {
  const raw = profileJsonInput.value.trim();
  if (!raw) {
    throw new Error("Paste a reviewed profile manifest or choose a JSON file first.");
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_error) {
    throw new Error("The profile is not valid JSON. Check commas, quotes, and brackets.");
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("The profile manifest must be one JSON object.");
  }
  return parsed;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error("MootOS returned an unreadable response.");
  }

  if (!response.ok) {
    throw new Error(payload.detail || "MootOS could not complete the profile request.");
  }
  return payload;
}

function scopeLabel(entry) {
  return entry.project || "Global";
}

function renderEntries(container, entries) {
  container.replaceChildren();
  entries.forEach((entry) => {
    const card = document.createElement("article");
    card.className = "profile-entry";

    const scope = document.createElement("span");
    scope.className = "profile-entry-scope";
    scope.textContent = scopeLabel(entry);

    const content = document.createElement("p");
    content.className = "profile-entry-content";
    content.textContent = entry.content;

    card.append(scope, content);
    container.append(card);
  });
}

function renderCounts(counts) {
  profileCounts.replaceChildren();
  [
    ["Ready", counts.ready],
    ["Already active", counts.already_active],
    ["Blocked", counts.blocked],
    ["Total", counts.total],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "profile-count";
    const number = document.createElement("strong");
    number.textContent = String(value);
    const text = document.createElement("span");
    text.textContent = label;
    item.append(number, text);
    profileCounts.append(item);
  });
}

function renderPreview(preview) {
  profilePreviewEmpty.hidden = true;
  profilePreviewContent.hidden = false;
  renderCounts(preview.counts);

  profileReadySection.hidden = preview.ready.length === 0;
  profileActiveSection.hidden = preview.already_active.length === 0;
  profileBlockedSection.hidden = preview.blocked.length === 0;

  renderEntries(profileReadyList, preview.ready);
  renderEntries(profileActiveList, preview.already_active);
  renderEntries(profileBlockedList, preview.blocked);

  importProfileButton.disabled = !preview.can_import || preview.counts.ready === 0;
}

function resetPreview() {
  reviewedManifest = null;
  reviewedPreview = null;
  profilePreviewEmpty.hidden = false;
  profilePreviewContent.hidden = true;
  profileCounts.replaceChildren();
  profileReadyList.replaceChildren();
  profileActiveList.replaceChildren();
  profileBlockedList.replaceChildren();
  importProfileButton.disabled = true;
}

async function previewProfile() {
  hideBanner(profileInputError);
  hideBanner(profileImportError);
  hideBanner(profileSuccess);
  resetPreview();

  let manifest;
  try {
    manifest = parseManifest();
  } catch (error) {
    showBanner(profileInputError, error.message);
    return;
  }

  setBusy(previewProfileButton, true, "Previewing…", "Preview profile");
  try {
    const payload = await requestJson("/profile/preview", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(manifest),
    });
    reviewedManifest = manifest;
    reviewedPreview = payload.data;
    renderPreview(reviewedPreview);
    if (!reviewedPreview.can_import) {
      showBanner(
        profileImportError,
        "Import is blocked because one or more entries match archived or corrected memory history."
      );
    }
  } catch (error) {
    showBanner(profileInputError, error.message);
  } finally {
    setBusy(previewProfileButton, false, "Previewing…", "Preview profile");
  }
}

function openImportConfirmation() {
  hideBanner(profileImportError);
  hideBanner(profileSuccess);
  if (!reviewedManifest || !reviewedPreview || !reviewedPreview.can_import) {
    showBanner(profileImportError, "Preview the current profile before importing it.");
    return;
  }
  profileConfirmSummary.textContent = `${reviewedPreview.counts.ready} ready entr${reviewedPreview.counts.ready === 1 ? "y" : "ies"} will be imported and ${reviewedPreview.counts.already_active} already-active entr${reviewedPreview.counts.already_active === 1 ? "y" : "ies"} will be skipped.`;
  profileConfirmDialog.showModal();
}

async function importProfile(event) {
  event.preventDefault();
  if (!reviewedManifest) {
    profileConfirmDialog.close();
    showBanner(profileImportError, "Preview the profile again before importing.");
    return;
  }

  setBusy(confirmProfileImportButton, true, "Importing…", "Confirm import");
  try {
    const payload = await requestJson("/profile/import", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(reviewedManifest),
    });
    profileConfirmDialog.close();
    const counts = payload.data.counts;
    showBanner(
      profileSuccess,
      `Profile import complete: ${counts.imported} imported and ${counts.already_active} already active.`
    );
    await previewProfile();
  } catch (error) {
    profileConfirmDialog.close();
    showBanner(profileImportError, error.message);
  } finally {
    setBusy(confirmProfileImportButton, false, "Importing…", "Confirm import");
  }
}

profileFileInput.addEventListener("change", async () => {
  hideBanner(profileInputError);
  const [file] = profileFileInput.files;
  if (!file) {
    profileFileName.textContent = "No local file selected.";
    return;
  }
  if (file.size > 600000) {
    profileFileInput.value = "";
    profileFileName.textContent = "No local file selected.";
    showBanner(profileInputError, "That JSON file is too large for the Version 1 profile importer.");
    return;
  }
  try {
    profileJsonInput.value = await file.text();
    profileFileName.textContent = `Selected local file: ${file.name}`;
    resetPreview();
  } catch (_error) {
    showBanner(profileInputError, "The selected file could not be read.");
  }
});

profileJsonInput.addEventListener("input", () => {
  resetPreview();
  hideBanner(profileInputError);
  hideBanner(profileImportError);
  hideBanner(profileSuccess);
});

previewProfileButton.addEventListener("click", previewProfile);
clearProfileButton.addEventListener("click", () => {
  profileJsonInput.value = "";
  profileFileInput.value = "";
  profileFileName.textContent = "No local file selected.";
  hideBanner(profileInputError);
  hideBanner(profileImportError);
  hideBanner(profileSuccess);
  resetPreview();
  profileJsonInput.focus();
});
importProfileButton.addEventListener("click", openImportConfirmation);
profileConfirmForm.addEventListener("submit", importProfile);
cancelProfileImportButton.addEventListener("click", () => profileConfirmDialog.close());
profileConfirmDialog.addEventListener("click", (event) => {
  if (event.target === profileConfirmDialog) {
    profileConfirmDialog.close();
  }
});
