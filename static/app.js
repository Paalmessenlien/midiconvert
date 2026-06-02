"use strict";

const $ = (sel) => document.querySelector(sel);

const fileInput = $("#file");
const drop = $("#drop");
const filenameEl = $("#filename");
const convertBtn = $("#convert");

const sections = {
  upload: $("#upload"),
  progress: $("#progress"),
  result: $("#result"),
  error: $("#error"),
};

let pollTimer = null;

function show(name) {
  for (const [key, el] of Object.entries(sections)) {
    el.hidden = key !== name;
  }
}

function setFile(file) {
  if (file && file.type === "application/pdf") {
    fileInput._file = file;
    filenameEl.textContent = file.name;
    convertBtn.disabled = false;
  } else if (file) {
    filenameEl.textContent = "Not a PDF — pick a .pdf file";
    convertBtn.disabled = true;
  }
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("over");
  })
);
drop.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) {
    fileInput.files = e.dataTransfer.files;
    setFile(file);
  }
});

convertBtn.addEventListener("click", startConversion);

async function startConversion() {
  const file = fileInput.files[0];
  if (!file) return;

  const form = new FormData();
  form.append("pdf", file);
  form.append("voice_program", $("#voice_program").value || "53");
  form.append("piano_program", $("#piano_program").value || "0");
  form.append("tempo_fix", $("#tempo_fix").checked ? "true" : "false");
  form.append("repair_rh", $("#repair_rh").checked ? "true" : "false");
  if ($("#eighth_bpm").value) form.append("eighth_bpm", $("#eighth_bpm").value);

  setProgress("Uploading…", 0);
  show("progress");

  let res;
  try {
    res = await fetch("/api/convert", { method: "POST", body: form });
  } catch (err) {
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
      const r = await fetch(`/api/jobs/${jobId}`);
      job = await r.json();
    } catch {
      return; // transient; try again next tick
    }
    if (job.state === "running" || job.state === "queued") {
      setProgress(job.step || "Working…", job.percent || 0);
    } else if (job.state === "done") {
      clearInterval(pollTimer);
      finish(jobId);
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

function finish(jobId) {
  setProgress("Done", 100);
  const midiUrl = `/api/jobs/${jobId}/midi`;
  const player = $("#player");
  player.src = midiUrl;
  $("#dl-midi").href = midiUrl;
  $("#dl-mxl").href = `/api/jobs/${jobId}/musicxml`;
  setupReadout(player);
  show("result");
}

// --- Live note read-out during playback -----------------------------------
// This score is flat-heavy (G-flat major), so spell pitch classes with flats.
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

  // html-midi-player dispatches a 'note' event per scheduled note.
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
  // Keep only notes currently sounding (started, not yet ended).
  activeNotes = activeNotes.filter((n) => n.endTime > t - 0.03);
  const sounding = activeNotes.filter((n) => n.startTime <= t + 0.03);
  const pitches = [...new Set(sounding.map((n) => n.pitch))].sort((a, b) => a - b);
  out.textContent = pitches.length ? pitches.map(pitchName).join("   ") : "—";
  readoutRaf = requestAnimationFrame(() => tickReadout(player, out));
}

function fail(message) {
  clearInterval(pollTimer);
  $("#error-msg").textContent = message;
  show("error");
}

function reset() {
  fileInput.value = "";
  filenameEl.textContent = "No file selected";
  convertBtn.disabled = true;
  const player = $("#player");
  if (player) player.stop && player.stop();
  show("upload");
}

$("#again").addEventListener("click", reset);
$("#retry").addEventListener("click", reset);
