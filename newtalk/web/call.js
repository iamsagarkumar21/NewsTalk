"use strict";

// Browser side of the Jiya call: WebSocket + audio queue + Web Speech recognition (barge-in).

const $ = (id) => document.getElementById(id);
const el = {
  avatar: $("avatar"), title: $("title"), state: $("state"), caption: $("caption"),
  answer: $("answer"), mute: $("mute"), hangup: $("hangup"),
  typeForm: $("typeForm"), typeInput: $("typeInput"), notes: $("notes"),
};

// The token travels in the URL fragment so it never reaches server logs or referrers.
const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);

const call = {
  ws: null,
  audio: new Audio(),            // one reused element: unlocked once by the Answer tap (iOS-safe)
  queue: [],                     // {index, text, blob}
  collecting: null,              // {kind: "sentence"|"answer", index, text, chunks:[]}
  playing: null,
  captionText: "",
  recog: null,
  recogWanted: false,
  muted: false,
  active: false,
  language: "en",
  sttLang: "en-IN",
  retryTimer: null,
  micStream: null,
  micCtx: null,
  micNode: null,
  sttMode: "server",
};

function setState(text, mode) {
  el.state.textContent = text;
  el.avatar.classList.toggle("speaking", mode === "speaking");
  el.avatar.classList.toggle("listening", mode === "listening");
}

function setCaption(text) {
  call.captionText = text || "";
  el.caption.textContent = call.captionText;
}

function silentWavUrl() {
  const samples = 800, buf = new ArrayBuffer(44 + samples * 2), v = new DataView(buf);
  const str = (o, x) => { for (let i = 0; i < x.length; i++) v.setUint8(o + i, x.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true); v.setUint32(28, 16000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples * 2, true);
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

// ── audio playback ───────────────────────────────────────────────────────────────────────────
function flushAudio() {
  call.queue.length = 0;
  call.collecting = null;
  call.playing = null;
  try { call.audio.pause(); } catch (_) { /* ignore */ }
  if (call.audio.src && call.audio.src.startsWith("blob:")) URL.revokeObjectURL(call.audio.src);
  call.audio.removeAttribute("src");
}

function playNext() {
  if (call.playing || !call.queue.length) {
    if (!call.playing && !call.queue.length && call.active) setState("Listening…", "listening");
    return;
  }
  const item = call.queue.shift();
  call.playing = item;
  const url = URL.createObjectURL(item.blob);
  call.audio.src = url;
  setCaption(item.text);
  setState("Jiya is speaking", "speaking");
  call.audio.play().then(() => {
    if (item.index !== null && call.ws && call.ws.readyState === 1) {
      call.ws.send(JSON.stringify({ type: "played", index: item.index }));
    }
  }).catch(() => {
    // autoplay blocked or decode error: skip so the call keeps moving
    call.playing = null;
    playNext();
  });
}

call.audio.addEventListener("ended", () => {
  if (call.audio.src.startsWith("blob:")) URL.revokeObjectURL(call.audio.src);
  call.playing = null;
  playNext();
});

function finishCollecting() {
  const c = call.collecting;
  call.collecting = null;
  if (!c || !c.chunks.length) return;
  call.queue.push({ index: c.index, text: c.text, blob: new Blob(c.chunks, { type: "audio/mpeg" }) });
  playNext();
}

// ── speech recognition (browser STT) ──────────────────────────────────────────────────────────
function normWords(s) {
  return s.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);
}
// Without headphones the mic can hear Jiya herself; ignore text that mostly matches what she is saying.
function looksLikeEcho(text) {
  const heard = normWords(text);
  if (heard.length < 1 || !call.captionText) return false;
  const spoken = new Set(normWords(call.captionText));
  const overlap = heard.filter((w) => spoken.has(w)).length / heard.length;
  return overlap >= 0.6 && (call.playing !== null || call.queue.length > 0);
}

function bargeIn() {
  flushAudio();
  setState("Listening…", "listening");
  if (call.ws && call.ws.readyState === 1) call.ws.send(JSON.stringify({ type: "speech_started" }));
}

function startRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    el.notes.textContent = "This browser can't listen. Jiya will read your briefing; use the box below to ask questions. Chrome on Android or desktop works best.";
    return;
  }
  const r = new SR();
  r.lang = call.sttLang;
  r.continuous = true;
  r.interimResults = true;
  let bargedThisUtterance = false;

  r.onresult = (event) => {
    if (call.muted) return;
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      const text = res[0].transcript.trim();
      if (!text || looksLikeEcho(text)) continue;
      if (!bargedThisUtterance) { bargedThisUtterance = true; bargeIn(); }
      if (res.isFinal) {
        bargedThisUtterance = false;
        sendTranscript(text);
      }
    }
  };
  r.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      el.notes.textContent = "Microphone is blocked. Allow it in your browser, or type your questions below.";
      call.recogWanted = false;
    }
  };
  r.onend = () => {
    bargedThisUtterance = false;
    if (call.recogWanted && call.active) { try { r.start(); } catch (_) { /* already started */ } }
  };
  call.recog = r;
  call.recogWanted = true;
  try { r.start(); } catch (_) { /* ignore */ }
}

function stopRecognition() {
  call.recogWanted = false;
  try { call.recog && call.recog.stop(); } catch (_) { /* ignore */ }
}

function sendTranscript(text) {
  if (call.ws && call.ws.readyState === 1) {
    call.ws.send(JSON.stringify({ type: "transcript", text }));
    setState("Jiya is thinking…", null);
  }
}

// ── microphone -> server (16 kHz PCM over the call WebSocket) ───────────────────────────────────
async function startMicStreaming() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  await ctx.audioWorklet.addModule("mic-worklet.js");
  const src = ctx.createMediaStreamSource(call.micStream);
  const node = new AudioWorkletNode(ctx, "mic-processor");
  node.port.onmessage = (e) => {
    if (call.ws && call.ws.readyState === 1 && call.active) call.ws.send(e.data);
  };
  const sink = ctx.createGain();
  sink.gain.value = 0; // keeps the graph pulled without playing the mic back
  src.connect(node);
  node.connect(sink);
  sink.connect(ctx.destination);
  call.micCtx = ctx;
  call.micNode = node;
}

function stopMicStreaming() {
  try { call.micStream && call.micStream.getTracks().forEach((t) => t.stop()); } catch (_) { /* ignore */ }
  try { call.micCtx && call.micCtx.close(); } catch (_) { /* ignore */ }
  call.micStream = null; call.micCtx = null; call.micNode = null;
}

// ── websocket ────────────────────────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/call`);
  ws.binaryType = "arraybuffer";
  call.ws = ws;

  ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token, stt: call.sttMode }));

  ws.onmessage = (msg) => {
    if (typeof msg.data !== "string") {
      if (call.collecting) call.collecting.chunks.push(msg.data);
      return;
    }
    let ev;
    try { ev = JSON.parse(msg.data); } catch (_) { return; }
    handleEvent(ev);
  };

  ws.onclose = () => { if (call.active) endCall("Call ended"); };
  ws.onerror = () => { setState("Connection problem", null); };
}

function handleEvent(ev) {
  switch (ev.type) {
    case "ready":
      call.active = true;
      call.sttMode = ev.stt || call.sttMode;
      setState("Connected", null);
      if (call.sttMode === "server" && call.micStream) {
        startMicStreaming().catch(() => {
          el.notes.textContent = "Couldn't start the microphone stream. Type your questions below.";
        });
      }
      break;
    case "flush":
      flushAudio();
      if (call.active) setState("Listening…", "listening");
      break;
    case "busy":
      setState("Lines are busy — retrying…", null);
      clearTimeout(call.retryTimer);
      call.retryTimer = setTimeout(connect, (ev.retry_after || 30) * 1000);
      break;
    case "error":
      endCall(ev.message || "Something went wrong");
      break;
    case "briefing_start":
      call.language = ev.language || "en";
      call.sttLang = ev.stt_lang || "en-IN";
      if (call.sttMode === "browser" && !call.recog) startRecognition();
      break;
    case "speaking":
      finishCollecting();
      call.collecting = { kind: "sentence", index: ev.sentence_index, text: ev.text, chunks: [] };
      break;
    case "sentence_end":
      if (call.collecting && call.collecting.kind === "sentence") finishCollecting();
      break;
    case "qa_response":
      flushAudio();
      call.collecting = { kind: "answer", index: null, text: ev.answer, chunks: [] };
      break;
    case "answer_end":
      if (call.collecting && call.collecting.kind === "answer") finishCollecting();
      break;
    case "goodbye":
      flushAudio();
      if (ev.text) call.collecting = { kind: "answer", index: null, text: ev.text, chunks: [] };
      break;
    case "call_end":
      finishCollecting();
      call.audio.addEventListener("ended", () => endCall("Call ended"), { once: true });
      if (!call.playing) endCall("Call ended");
      break;
    case "tts_error":
      el.notes.textContent = "Voice is unavailable right now — you can still read along.";
      break;
    case "briefing_done":
      el.notes.textContent = "That's the rundown. Ask me anything, or say bye.";
      break;
    default:
      break;
  }
}

function endCall(message) {
  call.active = false;
  stopRecognition();
  stopMicStreaming();
  flushAudio();
  try { call.ws && call.ws.close(); } catch (_) { /* ignore */ }
  setState(message, null);
  el.title.textContent = "Call ended";
  el.hangup.classList.add("hidden");
  el.mute.classList.add("hidden");
  el.typeForm.classList.add("hidden");
  el.answer.textContent = "Back to dashboard";
  el.answer.classList.remove("hidden");
  el.answer.onclick = () => { location.href = "/app/"; };
}

// ── wiring ───────────────────────────────────────────────────────────────────────────────────
el.answer.addEventListener("click", async () => {
  if (!token) { setState("This call link is missing or expired.", null); return; }
  el.answer.classList.add("hidden");
  el.hangup.classList.remove("hidden");
  el.mute.classList.remove("hidden");
  el.typeForm.classList.remove("hidden");
  el.title.textContent = "On call with Jiya";
  setState("Connecting…", null);
  el.notes.textContent = "Headphones recommended so Jiya doesn't hear herself.";
  // prime the audio element inside this user gesture (required by iOS Safari / Chrome autoplay)
  try {
    call.audio.src = silentWavUrl();
    await call.audio.play().catch(() => {});
    call.audio.pause();
    URL.revokeObjectURL(call.audio.src);
    call.audio.removeAttribute("src");
  } catch (_) { /* ignore */ }
  // ask for the microphone on this tap; keep the stream for server-side speech recognition
  try {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      call.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    }
  } catch (_) {
    el.notes.textContent = "Microphone not available — you can type your questions below.";
  }
  const canStream = !!(call.micStream && window.AudioWorklet);
  call.sttMode = canStream ? "server" : "browser";
  connect();
});

el.hangup.addEventListener("click", () => {
  try { call.ws && call.ws.send(JSON.stringify({ type: "stop" })); } catch (_) { /* ignore */ }
  endCall("Call ended");
});

el.mute.addEventListener("click", () => {
  call.muted = !call.muted;
  if (call.micNode) call.micNode.port.postMessage({ muted: call.muted });
  el.mute.textContent = call.muted ? "Unmute mic" : "Mute mic";
});

el.typeForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el.typeInput.value.trim();
  if (!text) return;
  el.typeInput.value = "";
  bargeIn();
  sendTranscript(text);
});

if (!token) {
  el.answer.disabled = true;
  setState("This call link is missing or expired. Open the dashboard to start a new call.", null);
}
