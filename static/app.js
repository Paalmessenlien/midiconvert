"use strict";

const $ = (sel) => document.querySelector(sel);

const AUDIO_EXTS = ["mp3", "wav", "flac", "m4a", "ogg", "aac", "aif", "aiff"];

const fileInput = $("#file");
const drop = $("#drop");
const filenameEl = $("#filename");
const badgeEl = $("#kind-badge");
const convertBtn = $("#convert");

const sections = {
  upload: $("#upload"),
  progress: $("#progress"),
  result: $("#result"),
  error: $("#error"),
};

let pollTimer = null;
let selectedKind = null; // "pdf" | "audio"

function show(name) {
  for (const [key, el] of Object.entries(sections)) el.hidden = key !== name;
}

function kindOf(filename) {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  if (ext === "pdf") return "pdf";
  if (AUDIO_EXTS.includes(ext)) return "audio";
  return null;
}

function setFile(file) {
  if (!file) return;
  const kind = kindOf(file.name);
  selectedKind = kind;
  filenameEl.textContent = file.name;

  // Toggle the relevant advanced-options group.
  $("#adv-pdf").hidden = kind !== "pdf";
  $("#adv-audio").hidden = kind !== "audio";
  $("#adv-hint").hidden = kind !== null;

  if (kind) {
    badgeEl.hidden = false;
    badgeEl.textContent = kind === "pdf" ? "PDF · sheet music" : "Audio · transcription";
    badgeEl.className = "badge " + kind;
    convertBtn.disabled = false;
  } else {
    badgeEl.hidden = false;
    badgeEl.textContent = "Unsupported — pick a PDF or audio file";
    badgeEl.className = "badge bad";
    convertBtn.disabled = true;
  }
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); })
);
drop.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) { fileInput.files = e.dataTransfer.files; setFile(file); }
});

convertBtn.addEventListener("click", startConversion);

async function startConversion() {
  const file = fileInput.files[0];
  if (!file || !selectedKind) return;

  const form = new FormData();
  form.append("file", file);
  if (selectedKind === "pdf") {
    form.append("voice_program", $("#voice_program").value || "53");
    form.append("piano_program", $("#piano_program").value || "0");
    form.append("tempo_fix", $("#tempo_fix").checked ? "true" : "false");
    form.append("repair_rh", $("#repair_rh").checked ? "true" : "false");
    if ($("#eighth_bpm").value) form.append("eighth_bpm", $("#eighth_bpm").value);
  } else {
    form.append("onset_threshold", $("#onset_threshold").value || "0.5");
    form.append("frame_threshold", $("#frame_threshold").value || "0.3");
    form.append("melody_min", $("#melody_min").value || "55");
    form.append("melody_max", $("#melody_max").value || "84");
    form.append("melody_min_ms", $("#melody_min_ms").value || "120");
  }

  setProgress("Uploading…", 0);
  show("progress");

  let res;
  try {
    res = await fetch("/api/convert", { method: "POST", body: form });
  } catch {
    return fail("Could not reach the server. Is it still running?");
  }
  const data = await res.json();
  if (!res.ok) return fail(data.error || "Upload rejected.");
  poll(data.job_id);
}

function poll(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    let job;
    try {
      job = await (await fetch(`/api/jobs/${jobId}`)).json();
    } catch { return; }
    if (job.state === "running" || job.state === "queued") {
      setProgress(job.step || "Working…", job.percent || 0);
    } else if (job.state === "done") {
      clearInterval(pollTimer);
      finish(jobId, job);
    } else if (job.state === "error") {
      clearInterval(pollTimer);
      fail(job.error || "Unknown error.");
    }
  }, 1500);
}

function setProgress(label, percent) {
  $("#bar-fill").style.width = `${Math.max(2, Math.min(100, percent))}%`;
  $("#step").textContent = `${label}  ·  ${Math.round(percent)}%`;
}

function artifactUrl(jobId, logical) {
  return `/api/jobs/${jobId}/f/${logical}`;
}

function finish(jobId, job) {
  setProgress("Done", 100);
  const player = $("#player");

  $("#result-title").textContent =
    job.kind === "audio" ? "Audio → MIDI" : "Sheet music → MIDI";

  // Player source toggle (e.g. Melody / Full for audio).
  const toggle = $("#player-toggle");
  toggle.innerHTML = "";
  const players = job.player || [];
  if (players.length > 1) {
    toggle.hidden = false;
    players.forEach((p, i) => {
      const b = document.createElement("button");
      b.className = "toggle-btn" + (i === 0 ? " active" : "");
      b.textContent = p.label;
      b.addEventListener("click", () => {
        toggle.querySelectorAll(".toggle-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        player.stop && player.stop();
        player.src = artifactUrl(jobId, p.logical);
      });
      toggle.appendChild(b);
    });
  } else {
    toggle.hidden = true;
  }

  if (players.length) player.src = artifactUrl(jobId, players[0].logical);

  // Download buttons.
  const dl = $("#downloads");
  dl.innerHTML = "";
  (job.downloads || []).forEach((d, i) => {
    const a = document.createElement("a");
    a.className = i === 0 ? "primary" : "ghost";
    a.textContent = d.label;
    a.href = artifactUrl(jobId, d.logical);
    a.setAttribute("download", "");
    dl.appendChild(a);
  });

  $("#result-note").textContent = job.info || "";
  setupReadout(player);
  show("result");
}

function fail(message) {
  clearInterval(pollTimer);
  $("#error-msg").textContent = message;
  show("error");
}

function reset() {
  fileInput.value = "";
  filenameEl.textContent = "No file selected";
  badgeEl.hidden = true;
  selectedKind = null;
  $("#adv-pdf").hidden = true;
  $("#adv-audio").hidden = true;
  $("#adv-hint").hidden = false;
  convertBtn.disabled = true;
  const player = $("#player");
  if (player && player.stop) player.stop();
  show("upload");
}

$("#again").addEventListener("click", reset);
$("#retry").addEventListener("click", reset);

// --- Live note read-out during playback -----------------------------------
const PITCH_NAMES = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"];
function pitchName(midi) {
  return PITCH_NAMES[midi % 12] + (Math.floor(midi / 12) - 1);
}

let activeNotes = [];
let readoutRaf = null;

function setupReadout(player) {
  const out = $("#readout-notes");
  if (player._readoutWired) return;
  player._readoutWired = true;

  player.addEventListener("note", (e) => {
    const n = e.detail && e.detail.note;
    if (n) activeNotes.push(n);
  });
  player.addEventListener("start", () => {
    activeNotes = [];
    cancelAnimationFrame(readoutRaf);
    tickReadout(player, out);
  });
  const end = () => {
    cancelAnimationFrame(readoutRaf);
    readoutRaf = null;
    activeNotes = [];
    out.textContent = "—";
  };
  player.addEventListener("stop", end);
}

function tickReadout(player, out) {
  const t = player.currentTime || 0;
  activeNotes = activeNotes.filter((n) => n.endTime > t - 0.03);
  const sounding = activeNotes.filter((n) => n.startTime <= t + 0.03);
  const pitches = [...new Set(sounding.map((n) => n.pitch))].sort((a, b) => a - b);
  out.textContent = pitches.length ? pitches.map(pitchName).join("   ") : "—";
  readoutRaf = requestAnimationFrame(() => tickReadout(player, out));
}
