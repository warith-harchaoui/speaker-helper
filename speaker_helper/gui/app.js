// speaker-helper GUI logic.
// Vanilla ES, no framework. Every request is same-origin (relative paths),
// so there is no base URL and no CORS to configure.

"use strict";

// ---- tiny DOM helpers -------------------------------------------------------
const $ = (id) => document.getElementById(id);

/** Show an inline red banner for a section (never alert()). */
function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}
/** Clear a section's error banner. */
function clearError(el) {
  el.textContent = "";
  el.hidden = true;
}

/** Decode a base64 string into a WAV Blob (audio/wav).
 *  atob() gives a binary string; we copy each char code into a byte array so
 *  URL.createObjectURL() can turn it into a playable object URL. */
function base64ToWavBlob(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: "audio/wav" });
}

/** Best-effort extraction of a `detail` message from an error Response. */
async function readDetail(resp) {
  try {
    const data = await resp.json();
    if (data && data.detail) return data.detail;
  } catch (_) {
    /* body was not JSON */
  }
  return `HTTP ${resp.status}`;
}

// ---- health badge (polled once on load) ------------------------------------
async function pollHealth() {
  const dot = $("health-dot");
  const text = $("health-text");
  try {
    const resp = await fetch("/health");
    const data = await resp.json();
    const status = data.status || "unknown";
    text.textContent = `${status}${data.backend ? " · " + data.backend : ""}`;
    // ok = green, degraded = amber, anything else = red.
    dot.className =
      "h-2 w-2 rounded-full " +
      (status === "ok" ? "bg-green-500" : status === "degraded" ? "bg-amber-500" : "bg-red-500");
  } catch (err) {
    text.textContent = "unreachable";
    dot.className = "h-2 w-2 rounded-full bg-red-500";
  }
}

// ---- 1. Synthesize: offline (POST /synth) ----------------------------------
async function speakOffline() {
  const errEl = $("synth-error");
  const meta = $("synth-meta");
  const audio = $("synth-audio");
  clearError(errEl);
  meta.textContent = "Synthesizing…";

  const text = $("synth-text").value.trim();
  const language = $("synth-lang").value.trim() || null;
  if (!text) {
    showError(errEl, "Please enter some text.");
    meta.textContent = "";
    return;
  }

  const btn = $("btn-speak");
  btn.disabled = true;
  try {
    const resp = await fetch("/synth", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!resp.ok) {
      showError(errEl, await readDetail(resp));
      meta.textContent = "";
      return;
    }
    // Response body is a raw audio/wav binary — wrap the Blob in an object URL.
    const blob = await resp.blob();
    audio.src = URL.createObjectURL(blob);
    audio.hidden = false;
    // duration + RTF ride along as response headers (no decode needed).
    const dur = resp.headers.get("X-Audio-Duration-S");
    const rtf = resp.headers.get("X-Audio-RTF");
    meta.textContent = `duration: ${dur ?? "?"} s · RTF: ${rtf ?? "?"}`;
  } catch (err) {
    showError(errEl, String(err));
    meta.textContent = "";
  } finally {
    btn.disabled = false;
  }
}

// ---- 1. Synthesize: streaming (POST /synth/stream, SSE over fetch) ----------
async function speakStream() {
  const errEl = $("synth-error");
  const meta = $("synth-meta");
  const audio = $("synth-audio");
  clearError(errEl);
  meta.textContent = "Streaming…";
  audio.hidden = true;

  const text = $("synth-text").value.trim();
  const language = $("synth-lang").value.trim() || null;
  if (!text) {
    showError(errEl, "Please enter some text.");
    meta.textContent = "";
    return;
  }

  const btn = $("btn-stream");
  btn.disabled = true;

  // We must POST a JSON body, which EventSource cannot do — so we read the SSE
  // stream ourselves from a fetch() ReadableStream and parse frames by hand.
  try {
    const resp = await fetch("/synth/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!resp.ok || !resp.body) {
      showError(errEl, await readDetail(resp));
      meta.textContent = "";
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ""; // accumulates bytes until we have complete SSE frames

    // Chunks are queued and played strictly in `seq` order (one at a time).
    const queue = [];
    let playing = false;
    let ttfa = null;
    const rtfs = [];

    function playNext() {
      if (playing || queue.length === 0) return;
      playing = true;
      const url = queue.shift();
      audio.src = url;
      audio.hidden = false;
      audio.play().catch(() => {}); // autoplay may be blocked; controls remain
      // When one chunk finishes, release its URL and advance the queue.
      audio.onended = () => {
        URL.revokeObjectURL(url);
        playing = false;
        playNext();
      };
    }

    // Handle one parsed SSE frame (a block of "field: value" lines).
    function handleFrame(frame) {
      let eventName = "message";
      const dataLines = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) return;
      const json = JSON.parse(dataLines.join("\n"));

      // A terminal error frame surfaces the failure detail inline.
      if (eventName === "error") {
        showError(errEl, json.detail || "stream error");
        return;
      }

      // Normal chunk: decode its base64 WAV and enqueue it in seq order.
      if (json.ttfa_s != null && ttfa == null) ttfa = json.ttfa_s;
      if (json.rtf != null) rtfs.push(json.rtf);
      const blob = base64ToWavBlob(json.audio);
      queue.push(URL.createObjectURL(blob));
      playNext();

      const lastRtf = rtfs.length ? rtfs[rtfs.length - 1] : "?";
      meta.textContent =
        `TTFA: ${ttfa ?? "?"} s · chunk ${json.seq} RTF: ${lastRtf}` +
        (json.is_final ? " · done" : "");
    }

    // Read the stream: split on the blank line ("\n\n") that terminates frames.
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        if (frame.trim()) handleFrame(frame);
      }
    }
    // Flush any trailing frame that had no closing blank line.
    if (buffer.trim()) handleFrame(buffer);
  } catch (err) {
    showError(errEl, String(err));
    meta.textContent = "";
  } finally {
    btn.disabled = false;
  }
}

// ---- 2. Voices (GET /voices) -----------------------------------------------
async function listVoices() {
  const errEl = $("voices-error");
  const body = $("voices-body");
  clearError(errEl);
  body.innerHTML = "";

  const engine = $("voices-engine").value.trim();
  const btn = $("btn-voices");
  btn.disabled = true;
  try {
    const url = engine ? `/voices?engine=${encodeURIComponent(engine)}` : "/voices";
    const resp = await fetch(url);
    if (!resp.ok) {
      showError(errEl, await readDetail(resp));
      return;
    }
    const data = await resp.json();
    const voices = data.voices || [];
    if (voices.length === 0) {
      body.innerHTML =
        `<tr><td colspan="5" class="py-3 text-slate-500 dark:text-slate-400">No voices.</td></tr>`;
      return;
    }
    for (const v of voices) {
      const tr = document.createElement("tr");
      for (const key of ["voice_id", "name", "language", "gender", "engine"]) {
        const td = document.createElement("td");
        td.className = "py-2 pr-4";
        td.textContent = v[key] ?? "";
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  } catch (err) {
    showError(errEl, String(err));
  } finally {
    btn.disabled = false;
  }
}

// ---- 3. Clone voice (POST /clone, multipart) -------------------------------
async function cloneVoice() {
  const errEl = $("clone-error");
  const result = $("clone-result");
  clearError(errEl);
  result.textContent = "";

  const name = $("clone-name").value.trim();
  const files = $("clone-files").files;
  if (!name) {
    showError(errEl, "Please enter a name.");
    return;
  }
  if (!files || files.length === 0) {
    showError(errEl, "Please select at least one audio file.");
    return;
  }

  // Build multipart form data: name, repeated files, optional repeated transcripts.
  const form = new FormData();
  form.append("name", name);
  for (const f of files) form.append("files", f);
  const transcripts = $("clone-texts").value
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  for (const t of transcripts) form.append("reference_texts", t);

  const btn = $("btn-clone");
  btn.disabled = true;
  result.textContent = "Cloning…";
  try {
    const resp = await fetch("/clone", { method: "POST", body: form });
    if (!resp.ok) {
      showError(errEl, await readDetail(resp));
      result.textContent = "";
      return;
    }
    const data = await resp.json();
    result.textContent = `voice_id: ${data.voice_id}`;
  } catch (err) {
    showError(errEl, String(err));
    result.textContent = "";
  } finally {
    btn.disabled = false;
  }
}

// ---- 4. Router (POST /route) -----------------------------------------------
async function routeEngine() {
  const errEl = $("route-error");
  const card = $("route-card");
  clearError(errEl);
  card.hidden = true;
  card.innerHTML = "";

  const condition = $("route-condition").value;
  const language = $("route-lang").value.trim() || "fr";
  const ceilingRaw = $("route-ceiling").value.trim();

  const payload = { condition, language };
  // Only send rtf_ceiling when provided; otherwise let the server default (0.8).
  if (ceilingRaw !== "") payload.rtf_ceiling = Number(ceilingRaw);

  const btn = $("btn-route");
  btn.disabled = true;
  try {
    const resp = await fetch("/route", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      // 400 carries a human-readable {detail}.
      showError(errEl, await readDetail(resp));
      return;
    }
    const d = await resp.json();

    // Colour-code confidence: high=green, medium=amber, low=red.
    const conf = String(d.confidence || "").toLowerCase();
    const confClass =
      conf === "high"
        ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
        : conf === "medium"
        ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";

    const meanRtf = d.mean_rtf != null ? d.mean_rtf : "?";

    card.innerHTML = `
      <div class="flex flex-wrap items-center gap-2">
        <span class="rounded-md bg-indigo-600 px-2 py-1 text-sm font-semibold text-white">${escapeHtml(d.engine ?? "?")}</span>
        <span class="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-700">mode: ${escapeHtml(d.mode ?? "?")}</span>
        <span class="rounded-md px-2 py-1 text-sm font-medium ${confClass}">confidence: ${escapeHtml(d.confidence ?? "?")}</span>
      </div>
      <dl class="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div class="flex justify-between gap-4"><dt class="text-slate-500 dark:text-slate-400">backend</dt><dd>${escapeHtml(d.backend ?? "?")}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-slate-500 dark:text-slate-400">quality</dt><dd>${escapeHtml(String(d.quality ?? "?"))} <span class="text-slate-400">(${escapeHtml(d.quality_source ?? "?")})</span></dd></div>
        <div class="flex justify-between gap-4"><dt class="text-slate-500 dark:text-slate-400">mean RTF</dt><dd>${escapeHtml(String(meanRtf))} <span class="text-slate-400">(${escapeHtml(d.rtf_source ?? "?")})</span></dd></div>
        <div class="flex justify-between gap-4"><dt class="text-slate-500 dark:text-slate-400">first-chunk sentences</dt><dd>${escapeHtml(String(d.first_chunk_sentences ?? "?"))}</dd></div>
      </dl>
      <p class="mt-3 rounded-md bg-white p-3 text-sm leading-relaxed text-slate-700 shadow-sm dark:bg-slate-900 dark:text-slate-200">${escapeHtml(d.justification ?? "")}</p>
    `;
    card.hidden = false;
  } catch (err) {
    showError(errEl, String(err));
  } finally {
    btn.disabled = false;
  }
}

/** Escape text before injecting into innerHTML (server strings are untrusted UI). */
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---- wire up ----------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  pollHealth();
  $("btn-speak").addEventListener("click", speakOffline);
  $("btn-stream").addEventListener("click", speakStream);
  $("btn-voices").addEventListener("click", listVoices);
  $("btn-clone").addEventListener("click", cloneVoice);
  $("btn-route").addEventListener("click", routeEngine);
});
