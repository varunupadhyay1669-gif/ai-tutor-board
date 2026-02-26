const dom = {
  htmlInput: document.getElementById("htmlInput"),
  imageInput: document.getElementById("imageInput"),
  imageList: document.getElementById("imageList"),
  dropZone: document.getElementById("dropZone"),
  btnParseSections: document.getElementById("btnParseSections"),
  btnUpdatePreview: document.getElementById("btnUpdatePreview"),
  btnPrint: document.getElementById("btnPrint"),
  btnDownloadHtml: document.getElementById("btnDownloadHtml"),
  btnReset: document.getElementById("btnReset"),
  previewFrame: document.getElementById("previewFrame"),
  parseStatus: document.getElementById("parseStatus"),
  tplImageItem: document.getElementById("tplImageItem"),
  pageSize: document.getElementById("pageSize"),
  pageMargin: document.getElementById("pageMargin"),
};

/** @type {{ id: string, name: string, size: number, type: string, dataUrl: string, caption: string, afterSection: number }[]} */
let images = [];

/** @type {{ label: string }[]} */
let sections = [];

function setStatus(message, kind = "ok") {
  dom.parseStatus.textContent = message;
  dom.parseStatus.classList.toggle("is-error", kind === "error");
  dom.parseStatus.classList.toggle("is-ok", kind === "ok");
}

function humanFileSize(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function stripDangerousNodes(root) {
  const selectors = ["script", "iframe", "object", "embed"];
  for (const sel of selectors) {
    for (const node of Array.from(root.querySelectorAll(sel))) node.remove();
  }

  for (const el of Array.from(root.querySelectorAll("*"))) {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value || "";
      if (name.startsWith("on")) el.removeAttribute(attr.name);
      if ((name === "src" || name === "href") && value.trim().toLowerCase().startsWith("javascript:")) {
        el.removeAttribute(attr.name);
      }
    }
  }
}

function extractBodyHtml(rawHtml) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(rawHtml || "", "text/html");
  stripDangerousNodes(doc);
  return doc.body ? doc.body.innerHTML : rawHtml || "";
}

function parseSectionsFromHtml(rawHtml) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(rawHtml || "", "text/html");
  stripDangerousNodes(doc);

  const headings = Array.from(doc.querySelectorAll("h1,h2,h3,h4,h5,h6"));
  const found = headings.map((h) => {
    const level = h.tagName.toUpperCase();
    const text = (h.textContent || "").trim().replace(/\s+/g, " ");
    return { label: text ? `${level}: ${text}` : `${level}: (untitled)` };
  });

  return [{ label: "Top of document" }, ...found, { label: "End of document" }];
}

function getSectionOptionsHtml() {
  return sections
    .map((s, idx) => `<option value="${idx}">${escapeHtml(s.label)}</option>`)
    .join("");
}

function escapeHtml(text) {
  return (text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function makeId() {
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
}

function renderImageList() {
  dom.imageList.innerHTML = "";
  const optionsHtml = getSectionOptionsHtml();

  for (const img of images) {
    const node = dom.tplImageItem.content.firstElementChild.cloneNode(true);
    const thumb = node.querySelector(".thumb");
    const filename = node.querySelector(".filename");
    const filesize = node.querySelector(".filesize");
    const btnRemove = node.querySelector(".btn-remove");
    const sectionSelect = node.querySelector(".sectionSelect");
    const captionInput = node.querySelector(".captionInput");

    thumb.src = img.dataUrl;
    thumb.alt = img.name;
    filename.textContent = img.name;
    filesize.textContent = `${humanFileSize(img.size)} • ${img.type || "image"}`;

    sectionSelect.innerHTML = optionsHtml;
    sectionSelect.value = String(img.afterSection);
    sectionSelect.addEventListener("change", () => {
      img.afterSection = Number(sectionSelect.value);
      schedulePreviewUpdate();
    });

    captionInput.value = img.caption;
    captionInput.addEventListener("input", () => {
      img.caption = captionInput.value;
      schedulePreviewUpdate();
    });

    btnRemove.addEventListener("click", () => {
      images = images.filter((x) => x.id !== img.id);
      renderImageList();
      schedulePreviewUpdate();
    });

    dom.imageList.appendChild(node);
  }
}

function buildCombinedHtml() {
  if (!sections.length) {
    sections = parseSectionsFromHtml(dom.htmlInput.value.trim());
  }

  const notesBodyHtml = extractBodyHtml(dom.htmlInput.value);

  const pageSize = (dom.pageSize.value || "A4").trim();
  const marginMm = Math.max(5, Math.min(30, Number(dom.pageMargin.value || 16)));
  const printCss = `
@page { size: ${pageSize}; margin: ${marginMm}mm; }
html, body { height: auto; }
body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: #111; }
#notes { max-width: 860px; margin: 0 auto; padding: 18px; }
#notes :is(h1,h2,h3) { margin-top: 1.1em; }
#notes img { max-width: 100%; height: auto; }
figure.screenshot { margin: 16px 0; padding: 10px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; break-inside: avoid; }
figure.screenshot img { display: block; width: 100%; }
figure.screenshot figcaption { margin-top: 8px; font-size: 12px; color: #374151; }
@media print {
  #notes { max-width: none; padding: 0; }
  a { color: inherit; text-decoration: none; }
}
`;

  const base = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Notes</title>
    <style>${printCss}</style>
  </head>
  <body>
    <div id="notes"></div>
  </body>
</html>`;

  const parser = new DOMParser();
  const doc = parser.parseFromString(base, "text/html");
  const notes = doc.getElementById("notes");
  notes.innerHTML = notesBodyHtml;
  stripDangerousNodes(notes);

  const headings = Array.from(notes.querySelectorAll("h1,h2,h3,h4,h5,h6"));
  const endIndex = sections.length - 1; // last option is End of document

  const bySection = new Map();
  for (const img of images) {
    const key = Number.isFinite(img.afterSection) ? img.afterSection : endIndex;
    if (!bySection.has(key)) bySection.set(key, []);
    bySection.get(key).push(img);
  }

  const lastInsertedAfterHeading = new Map();
  let lastInsertedAtTop = null;

  // Insert in stable order (by original selection order)
  for (const [sectionIdx, imgs] of Array.from(bySection.entries()).sort((a, b) => a[0] - b[0])) {
    for (const img of imgs) {
      const figure = doc.createElement("figure");
      figure.className = "screenshot";

      const imageEl = doc.createElement("img");
      imageEl.src = img.dataUrl;
      imageEl.alt = img.caption ? img.caption : img.name;
      figure.appendChild(imageEl);

      const captionText = (img.caption || "").trim();
      if (captionText) {
        const figcaption = doc.createElement("figcaption");
        figcaption.textContent = captionText;
        figure.appendChild(figcaption);
      }

      if (sectionIdx === 0) {
        if (lastInsertedAtTop) {
          lastInsertedAtTop.insertAdjacentElement("afterend", figure);
        } else {
          notes.insertAdjacentElement("afterbegin", figure);
        }
        lastInsertedAtTop = figure;
        continue;
      }

      if (sectionIdx >= endIndex) {
        notes.appendChild(figure);
        continue;
      }

      const headingIndex = sectionIdx - 1; // because sectionIdx includes "Top of document" at 0
      const heading = headings[headingIndex];
      if (!heading) {
        notes.appendChild(figure);
        continue;
      }

      const anchor = lastInsertedAfterHeading.get(heading) || heading;
      anchor.insertAdjacentElement("afterend", figure);
      lastInsertedAfterHeading.set(heading, figure);
    }
  }

  return `<!doctype html>\n${doc.documentElement.outerHTML}`;
}

function updatePreview() {
  const rawHtml = dom.htmlInput.value.trim();
  if (!rawHtml) {
    dom.previewFrame.srcdoc = `<!doctype html><html><body style="font-family:system-ui;padding:24px;color:#111;">Paste notes HTML to see a preview.</body></html>`;
    return;
  }

  if (!sections.length) {
    sections = parseSectionsFromHtml(rawHtml);
    renderImageList();
  }

  const combined = buildCombinedHtml();
  dom.previewFrame.srcdoc = combined;
  setStatus("Preview updated.", "ok");
}

let previewTimer = null;
function schedulePreviewUpdate() {
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    previewTimer = null;
    updatePreview();
  }, 250);
}

function openPrintWindow() {
  const combined = buildCombinedHtml();
  const w = window.open("", "_blank", "noopener,noreferrer");
  if (!w) {
    setStatus("Popup blocked. Allow popups, then try again.", "error");
    return;
  }

  w.document.open();
  w.document.write(combined);
  w.document.close();

  const tryPrint = () => {
    try {
      w.focus();
      w.print();
    } catch {
      // Ignore
    }
  };

  w.addEventListener("load", () => {
    window.setTimeout(tryPrint, 150);
  });
}

function downloadCombinedHtml() {
  const combined = buildCombinedHtml();
  const blob = new Blob([combined], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "notes-with-screenshots.html";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function resetAll() {
  if (!window.confirm("Clear notes + screenshots?")) return;
  dom.htmlInput.value = "";
  images = [];
  sections = [];
  dom.imageInput.value = "";
  dom.imageList.innerHTML = "";
  dom.previewFrame.srcdoc = "";
  setStatus("Reset.", "ok");
}

async function onImagesSelected(fileList) {
  const files = Array.from(fileList || []).filter((f) => f && f.type && f.type.startsWith("image/"));
  if (!files.length) return;

  if (!sections.length) {
    const raw = dom.htmlInput.value.trim();
    sections = parseSectionsFromHtml(raw);
  }

  const endIndex = Math.max(0, sections.length - 1);

  const added = [];
  for (const file of files) {
    const dataUrl = await readFileAsDataUrl(file);
    added.push({
      id: makeId(),
      name: file.name,
      size: file.size,
      type: file.type,
      dataUrl,
      caption: "",
      afterSection: endIndex,
    });
  }

  images = [...images, ...added];
  renderImageList();
  schedulePreviewUpdate();
}

dom.btnParseSections.addEventListener("click", () => {
  const raw = dom.htmlInput.value.trim();
  sections = parseSectionsFromHtml(raw);
  renderImageList();
  setStatus(`Found ${Math.max(0, sections.length - 2)} heading section(s).`, "ok");
  schedulePreviewUpdate();
});

dom.btnUpdatePreview.addEventListener("click", () => updatePreview());
dom.btnPrint.addEventListener("click", () => openPrintWindow());
dom.btnDownloadHtml.addEventListener("click", () => downloadCombinedHtml());
dom.btnReset.addEventListener("click", () => resetAll());

dom.htmlInput.addEventListener("input", () => {
  setStatus("Edits pending… click “Update preview” when ready.", "ok");
});

dom.imageInput.addEventListener("change", async (e) => {
  try {
    await onImagesSelected(e.target.files);
  } catch (err) {
    setStatus(err?.message || "Failed to add images.", "error");
  } finally {
    dom.imageInput.value = "";
  }
});

// Drag and drop handling
if (dom.dropZone) {
  dom.dropZone.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dom.dropZone.classList.add("is-dragging");
  });

  dom.dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dom.dropZone.classList.add("is-dragging");
  });

  dom.dropZone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    if (!dom.dropZone.contains(e.relatedTarget)) {
      dom.dropZone.classList.remove("is-dragging");
    }
  });

  dom.dropZone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dom.dropZone.classList.remove("is-dragging");
    try {
      await onImagesSelected(e.dataTransfer.files);
    } catch (err) {
      setStatus(err?.message || "Failed to add images.", "error");
    }
  });
}

// Clipboard paste support for screenshots (Cmd+V / Ctrl+V)
async function handlePasteImages(e) {
  const items = Array.from(e.clipboardData?.items || []);
  const imageFiles = items
    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
    .map((item) => {
      const file = item.getAsFile();
      // Clipboard images often have no name, give them a friendly one
      if (file && (!file.name || file.name === "image.png")) {
        const timestamp = new Date().toLocaleTimeString("en-US", { hour12: false }).replace(/:/g, "-");
        const ext = file.type.split("/")[1] || "png";
        return new File([file], `screenshot-${timestamp}.${ext}`, { type: file.type });
      }
      return file;
    })
    .filter(Boolean);

  if (!imageFiles.length) return; // No images in clipboard, let other paste handlers work

  e.preventDefault(); // Only prevent default if we found images
  try {
    await onImagesSelected(imageFiles);
    setStatus(`Pasted ${imageFiles.length} screenshot(s) from clipboard.`, "ok");

    // Flash the drop zone to give visual feedback
    if (dom.dropZone) {
      dom.dropZone.classList.add("is-dragging");
      setTimeout(() => dom.dropZone.classList.remove("is-dragging"), 600);
    }
  } catch (err) {
    setStatus(err?.message || "Failed to paste image.", "error");
  }
}

// Listen for paste globally — works anywhere on the page
document.addEventListener("paste", handlePasteImages);

// Initial state
setStatus("Paste notes HTML, then add screenshots.", "ok");
updatePreview();
