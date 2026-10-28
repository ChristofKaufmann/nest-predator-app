// Drag & drop field that sends images one by one to the app's upload route. The server analyses each image right
// away and never holds more than a few of them, even for the content of a whole SD card.

const IMAGE_SUFFIXES = new Set(["jpg", "jpeg", "png", "bmp", "tif", "tiff", "webp"]);
const PARALLEL_UPLOADS = 2;  // one image is analysed while the next one is transferred
// elements of upload.html and their keys in the texts that come from Python (i18n.TEXTS)
const LABELS = [[".title", "title"], [".hint", "hint"], [".pick-files", "pickFiles"], [".pick-folder", "pickFolder"],
  [".cancel", "cancel"]];

// One upload job per page, independent of the mounted field: if Streamlit mounts the field anew while images are being
// uploaded, the new field shows the running job instead of losing it.
const job = {
  queue: [], collecting: 0, running: false, cancelled: false,
  total: 0, done: 0, skipped: 0, duplicates: 0, failed: [],
  keys: new Set(),  // keys of all images sent in this session, see fileKey()
  api: null, texts: null, setStateValue: null, ui: null,
};

// Dropping files next to the field would make the browser open them and thereby leave the app.
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
window.addEventListener("beforeunload", (event) => {
  if (job.running) event.preventDefault();
});

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  // this function runs again when the data (a new session after "Start over", another language) or the theme changes
  if (job.ui?.root !== parentElement) job.ui = setup(parentElement);
  const api = new URL(data.api, document.baseURI);
  if (api.href !== job.api?.href) job.keys.clear();  // a new session knows no images yet
  job.api = api;
  job.texts = data.texts;
  for (const [selector, key] of LABELS) parentElement.querySelector(selector).textContent = data.texts[key];
  job.setStateValue = setStateValue;
  render();
  const ui = job.ui;
  return () => {
    if (job.ui === ui) job.ui = null;
  };
}

function setup(root) {
  const $ = (selector) => root.querySelector(selector);
  const zone = $(".zone");
  zone.ondragover = (event) => {
    event.preventDefault();
    zone.classList.add("active");
  };
  zone.ondragleave = () => zone.classList.remove("active");
  zone.ondrop = (event) => {
    event.preventDefault();
    zone.classList.remove("active");
    // the entries are only available during the event, the folders are read afterwards
    const entries = [...event.dataTransfer.items].map((item) => item.webkitGetAsEntry()).filter(Boolean);
    add(readEntries(entries));
  };
  for (const [button, input] of [[".pick-files", ".files"], [".pick-folder", ".folder"]]) {
    $(button).onclick = () => $(input).click();
    $(input).onchange = (event) => {
      const found = { images: [], skipped: 0 };
      for (const file of event.target.files) {
        if (isImage(file.name)) found.images.push({ file, path: file.webkitRelativePath || file.name });
        else found.skipped++;
      }
      event.target.value = "";
      add(Promise.resolve(found));
    };
  }
  $(".cancel").onclick = () => {
    job.cancelled = true;
    // images that were not sent yet can be uploaded again later, the ones being sent are still analysed
    for (const item of job.queue.splice(0)) job.keys.delete(item.key);
    render();
  };
  return {
    root, status: $(".status"), bar: $(".bar > div"), text: $(".text"), details: $(".details"), cancel: $(".cancel"),
  };
}

function isImage(name) {
  return IMAGE_SUFFIXES.has(name.split(".").pop().toLowerCase());
}

// Identifies an image without reading it. The folder is not part of it, so an image is recognized whether it was
// chosen on its own or comes with a folder.
function fileKey(file) {
  return `${file.name}|${file.size}|${file.lastModified}`;
}

async function readEntries(entries) {
  const found = { images: [], skipped: 0 };
  for (const entry of entries) await walk(entry, found);
  return found;
}

async function walk(entry, found) {
  if (entry.isFile) {
    if (isImage(entry.name)) {
      // only the file's metadata is read here, its content when it is uploaded
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      found.images.push({ file, path: entry.fullPath.replace(/^\//, "") });
    } else {
      found.skipped++;
    }
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    // a directory is read in chunks (100 entries in Chrome) until an empty chunk comes back
    for (let chunk; (chunk = await new Promise((resolve, reject) => reader.readEntries(resolve, reject))).length;) {
      for (const child of chunk) await walk(child, found);
    }
  }
}

async function add(finding) {
  if (!job.running && !job.collecting) {
    Object.assign(job, { total: 0, done: 0, skipped: 0, duplicates: 0, failed: [], cancelled: false });
  }
  job.collecting++;
  render();
  try {
    const found = await finding;
    const known = [];
    for (const item of found.images) {
      item.key = fileKey(item.file);
      if (job.keys.has(item.key)) {
        job.duplicates++;
        known.push({ key: item.key, path: item.path });
      } else {
        job.keys.add(item.key);
        job.queue.push(item);
        job.total++;
      }
    }
    job.skipped += found.skipped;
    if (known.length) reportPaths(known);
  } catch (error) {
    job.failed.push(say("folderError", 0, { error: error.message }));
  }
  job.collecting--;
  if (!job.running && job.queue.length) run();
  else render();
}

// Already uploaded images may come with more of their folders now, e.g. first on their own, then with their folder.
// The server keeps the most complete path for display. If this fails, only the displayed path is affected.
function reportPaths(known) {
  fetch(new URL("paths", job.api), {
    method: "POST",
    body: JSON.stringify(known),
    headers: { "Content-Type": "application/json" },
  }).catch(() => {});
}

async function run() {
  job.running = true;
  job.started = performance.now();
  job.doneBefore = job.done;
  job.setStateValue("uploading", true);
  render();
  await Promise.all(Array.from({ length: PARALLEL_UPLOADS }, uploadNext));
  job.running = false;
  job.setStateValue("uploading", false);
  render();
}

async function uploadNext() {
  for (let item; (item = job.queue.shift());) {
    try {
      const response = await fetch(new URL("upload", job.api), {
        method: "POST",
        body: item.file,
        headers: {
          "Content-Type": "application/octet-stream",
          "X-File-Path": encodeURIComponent(item.path),
          "X-File-Key": encodeURIComponent(item.key),
        },
      });
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) fail(item, job.texts.errors[answer.error] ?? answer.error ?? response.statusText);
      else if (answer.duplicate) job.duplicates++;
    } catch (error) {
      fail(item, error.message);
    }
    job.done++;
    render();
  }
}

function fail(item, reason) {
  job.failed.push(`${item.path}: ${reason}`);
  job.keys.delete(item.key);  // so that the image can be uploaded again
}

function count(n) {
  return n.toLocaleString(job.texts.locale);
}

// A text in the user's language with {placeholders} filled in. Texts with a count are pairs of singular and plural.
function say(key, n, values = {}) {
  const text = job.texts[key];
  const template = Array.isArray(text) ? text[n === 1 ? 0 : 1] : text;
  return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
}

function render() {
  const ui = job.ui;
  if (!ui) return;
  const { total, done } = job;
  ui.status.hidden = !(job.collecting || total || job.skipped || job.duplicates || job.failed.length);
  ui.bar.style.width = `${total ? (100 * done) / total : 0}%`;
  ui.cancel.hidden = !job.running || job.cancelled;
  if (job.collecting) {
    ui.text.textContent = say("searching");
  } else if (job.running) {
    ui.text.textContent = say("progress", total, { done: count(done), total: count(total) }) + remaining();
  } else if (job.cancelled) {
    ui.text.textContent = say("cancelled", total, { done: count(done), total: count(total) });
  } else if (!total) {
    ui.text.textContent = say("noNew");
  } else {
    ui.text.textContent = say("done", done, { count: count(done) });
  }
  const details = [];
  if (job.skipped) details.push(say("skipped", job.skipped, { count: count(job.skipped) }));
  if (job.duplicates) details.push(say("duplicates", job.duplicates, { count: count(job.duplicates) }));
  if (job.failed.length) {
    details.push(say("failed", job.failed.length, { count: count(job.failed.length) }), ...job.failed.slice(0, 5));
  }
  ui.details.replaceChildren(...details.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
}

function remaining() {
  const processed = job.done - job.doneBefore;
  if (processed < 3) return "";
  const seconds = ((performance.now() - job.started) / 1000 / processed) * (job.total - job.done);
  return seconds < 90 ? say("remainingSeconds", 0, { count: Math.ceil(seconds / 10) * 10 })
    : say("remainingMinutes", 0, { count: Math.round(seconds / 60) });
}
