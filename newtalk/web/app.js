"use strict";

// ── tiny helpers ────────────────────────────────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const err = new Error(detailText(data) || res.statusText);
    err.status = res.status;
    err.fields = fieldErrors(data);
    throw err;
  }
  return data;
}

function detailText(data) {
  if (!data || !data.detail) return "";
  if (typeof data.detail === "string") return data.detail;
  return data.detail.map((d) => d.msg.replace(/^Value error, /, "")).join(" ");
}
function fieldErrors(data) {
  const out = {};
  if (data && Array.isArray(data.detail)) {
    for (const d of data.detail) out[(d.loc || []).slice(1).join(".")] = d.msg.replace(/^Value error, /, "");
  }
  return out;
}

let toastTimer;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4500);
}

// ── interface language (EN / हिन्दी) ───────────────────────────────────────────────────────────
const I18N = {
  en: {
    tagline: "your daily news call",
    signOut: "Sign out",
    signInTitle: "Welcome",
    signInHint: "Enter the invite code you were given. It's yours alone, and it also signs you back in later.",
    code: "Invite code",
    continue: "Continue",
    detailsTitle: "About you",
    callName: "What should Jiya call you?",
    language: "Language",
    callTime: "Daily call time",
    tz: "Time zone",
    topics: "What do you want to hear about?",
    topicsHint: "Pick as many as you like. Jiya only talks about what you pick, plus one can't-miss story if something huge happens.",
    freeText: "Anything specific? (optional)",
    freeTextHint: "E.g. \"SEBI and IPOs, Indian startups, IPL\"",
    understood: "Jiya understood",
    save: "Save",
    saved: "Saved",
    telegramTitle: "Get your call on Telegram",
    telegramHint: "Jiya rings you with a Telegram message. Tap Answer and the call opens in your browser.",
    telegramLinked: "Connected",
    telegramNot: "Not connected",
    connect: "Connect Telegram",
    disconnect: "Disconnect",
    consentTitle: "Consent",
    consentText: "I agree that Jiya may call me every day with AI-generated news summaries, and that the text of my briefings and questions is stored for 30 days. Summaries can contain mistakes.",
    consentGrant: "I agree",
    consentWithdraw: "Withdraw consent",
    pause: "Pause calls",
    resume: "Resume calls",
    tryTitle: "Try it now",
    tryHint: "Get a briefing right away. You can do this 3 times a day.",
    callNow: "Call me now",
    recentTitle: "Recent calls",
    none: "Nothing yet.",
    dangerTitle: "Delete my account",
    dangerHint: "Erases your profile, preferences, transcripts and history. This can't be undone.",
    delete: "Delete everything",
    confirmDelete: "Delete your account and all your data permanently?",
    needConsent: "Please agree to the consent first.",
    needProfile: "Save your details first.",
    st: { ready: "ready", rung: "rang", answered: "answered", completed: "completed", missed: "missed", failed: "failed", undeliverable: "no Telegram", pending: "pending" },
  },
  hi: {
    tagline: "आपकी रोज़ की न्यूज़ कॉल",
    signOut: "साइन आउट",
    signInTitle: "स्वागत है",
    signInHint: "आपको जो invite code मिला है वह डालिए। यह सिर्फ़ आपका है और दोबारा साइन इन भी इसी से होगा।",
    code: "Invite code",
    continue: "आगे बढ़ें",
    detailsTitle: "आपके बारे में",
    callName: "Jiya आपको क्या कहकर बुलाए?",
    language: "भाषा",
    callTime: "रोज़ की कॉल का समय",
    tz: "टाइम ज़ोन",
    topics: "आप किस बारे में सुनना चाहते हैं?",
    topicsHint: "जितने चाहें चुनिए। Jiya सिर्फ़ वही बताएगी जो आप चुनेंगे, और कोई बहुत बड़ी खबर हो तो वह भी।",
    freeText: "कुछ ख़ास? (वैकल्पिक)",
    freeTextHint: "जैसे \"SEBI और IPO, Indian startups, IPL\"",
    understood: "Jiya ने ये समझा",
    save: "सेव करें",
    saved: "सेव हो गया",
    telegramTitle: "Telegram पर कॉल पाएँ",
    telegramHint: "Jiya आपको Telegram संदेश से रिंग करेगी। Answer दबाइए, कॉल ब्राउज़र में खुल जाएगी।",
    telegramLinked: "जुड़ा हुआ",
    telegramNot: "जुड़ा नहीं है",
    connect: "Telegram जोड़ें",
    disconnect: "हटाएँ",
    consentTitle: "सहमति",
    consentText: "मैं सहमत हूँ कि Jiya मुझे रोज़ AI-जनित न्यूज़ सारांश के साथ कॉल कर सकती है, और मेरी briefing व सवालों का टेक्स्ट 30 दिन तक रखा जाएगा। सारांश में गलतियाँ हो सकती हैं।",
    consentGrant: "मैं सहमत हूँ",
    consentWithdraw: "सहमति वापस लें",
    pause: "कॉल रोकें",
    resume: "कॉल फिर शुरू करें",
    tryTitle: "अभी आज़माएँ",
    tryHint: "तुरंत briefing पाइए। दिन में 3 बार कर सकते हैं।",
    callNow: "अभी कॉल करो",
    recentTitle: "हाल की कॉल",
    none: "अभी कुछ नहीं।",
    dangerTitle: "मेरा अकाउंट हटाएँ",
    dangerHint: "आपकी प्रोफ़ाइल, पसंद, ट्रांसक्रिप्ट और इतिहास मिट जाएगा। वापस नहीं आएगा।",
    delete: "सब कुछ मिटाएँ",
    confirmDelete: "क्या आप अपना अकाउंट और सारा डेटा हमेशा के लिए मिटाना चाहते हैं?",
    needConsent: "पहले सहमति दीजिए।",
    needProfile: "पहले अपनी जानकारी सेव करें।",
    st: { ready: "तैयार", rung: "रिंग हुई", answered: "उठाई", completed: "पूरी", missed: "छूटी", failed: "असफल", undeliverable: "Telegram नहीं", pending: "बाकी" },
  },
};
let uiLang = (navigator.language || "").startsWith("hi") ? "hi" : "en";
try { uiLang = localStorage.getItem("ui") || uiLang; } catch (_) { /* private mode */ }
const t = (key) => I18N[uiLang][key] ?? I18N.en[key] ?? key;

// ── state ───────────────────────────────────────────────────────────────────────────────────
const state = { topics: [], languages: [], me: null, draft: null, telegram: null, calls: null, pollTimer: null };

const TZ_ALIASES = { "Asia/Calcutta": "Asia/Kolkata", "Asia/Katmandu": "Asia/Kathmandu", "Asia/Saigon": "Asia/Ho_Chi_Minh" };
function detectTimezone(fallback) {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz ? (TZ_ALIASES[tz] || tz) : fallback;
  } catch (_) { return fallback; }
}

// ── views ───────────────────────────────────────────────────────────────────────────────────
function render() {
  document.documentElement.lang = uiLang === "hi" ? "hi" : "en";
  $("#tagline").textContent = state.me ? "" : ` · ${t("tagline")}`;
  $("#langToggle").textContent = uiLang === "hi" ? "EN" : "हिं";
  const out = $("#signOut");
  out.textContent = t("signOut");
  out.classList.toggle("hidden", !state.me);

  const root = $("#app");
  root.replaceChildren(state.me ? dashboard() : signIn());
}

function signIn() {
  const input = h("input", {
    type: "text", id: "code", class: "big-input", autocomplete: "one-time-code",
    autocapitalize: "characters", spellcheck: "false", maxlength: "64", "aria-label": t("code"),
  });
  const error = h("p", { class: "hint", style: "color:var(--bad)", role: "alert" });
  const btn = h("button", { class: "primary", type: "submit" }, t("continue"));
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true; error.textContent = "";
      try {
        await api("POST", "/session", { code: input.value.trim() });
        await loadAll();
        render();
      } catch (err) {
        error.textContent = err.status === 429 ? err.message : (err.message || "Invalid code");
      } finally { btn.disabled = false; }
    },
  }, input, error, btn);
  return h("section", { class: "card" }, h("h2", {}, t("signInTitle")), h("p", { class: "hint" }, t("signInHint")), form);
}

function dashboard() {
  const me = state.me;
  const draft = state.draft;
  const frag = document.createDocumentFragment();

  // — details —
  const errs = {};
  const nameInput = h("input", { type: "text", id: "callName", maxlength: "40", value: draft.call_name, autocomplete: "given-name" });
  const timeInput = h("input", { type: "time", id: "callTime", step: "300", value: draft.call_time });
  const freeText = h("textarea", { id: "freeText", maxlength: "300", placeholder: t("freeTextHint") });
  freeText.value = draft.free_text || "";
  const formError = h("p", { class: "hint", style: "color:var(--bad)", role: "alert" });

  const langSeg = h("div", { class: "seg", role: "group", "aria-label": t("language") },
    state.languages.map((l) => h("button", {
      type: "button", "aria-pressed": String(draft.language === l.code),
      onclick: () => { draft.language = l.code; syncPressed(langSeg, (b, i) => state.languages[i].code === draft.language); },
    }, l.label_native)));

  const topicWrap = h("div", { class: "chips", role: "group", "aria-label": t("topics") },
    state.topics.map((tp) => h("button", {
      type: "button", class: "chip", "aria-pressed": String(draft.interests.includes(tp.slug)),
      onclick: (e) => {
        const on = draft.interests.includes(tp.slug);
        draft.interests = on ? draft.interests.filter((s) => s !== tp.slug) : [...draft.interests, tp.slug];
        e.currentTarget.setAttribute("aria-pressed", String(!on));
      },
    }, uiLang === "hi" ? tp.label_hi : tp.label)));

  const saveBtn = h("button", { class: "primary", type: "button" }, t("save"));
  saveBtn.addEventListener("click", async () => {
    formError.textContent = "";
    draft.call_name = nameInput.value;
    draft.call_time = timeInput.value || null;
    draft.free_text = freeText.value;
    saveBtn.disabled = true;
    try {
      state.me = await api("PUT", "/me", {
        call_name: draft.call_name, interests: draft.interests, free_text: draft.free_text || null,
        call_time: draft.call_time, language: draft.language, timezone: draft.timezone,
      });
      state.draft = draftFrom(state.me);
      toast(t("saved"));
      render();
      refreshUnderstood();
    } catch (err) {
      const fields = Object.entries(err.fields || {}).map(([f, m]) => m);
      formError.textContent = fields.length ? fields.join(" ") : err.message;
    } finally { saveBtn.disabled = false; }
  });

  const understood = me.profile && me.profile.understood;
  const understoodBox = understood
    ? h("div", { class: "understood" }, `${t("understood")}: `,
        [...(understood.categories || []), ...(understood.keywords || [])].join(", ") || "-")
    : (me.profile && me.profile.free_text ? h("div", { class: "understood", id: "understoodPending" }, "…") : null);

  frag.append(h("section", { class: "card" },
    h("h2", {}, t("detailsTitle")),
    h("label", { class: "field" }, t("callName"), nameInput),
    h("div", { class: "field" }, t("language"), langSeg),
    h("label", { class: "field" }, t("callTime"), timeInput,
      h("span", { class: "hint" }, ` ${t("tz")}: ${draft.timezone}`)),
    h("div", { class: "field" }, t("topics"), h("p", { class: "hint" }, t("topicsHint")), topicWrap),
    h("label", { class: "field" }, t("freeText"), freeText),
    understoodBox, formError, h("div", { class: "row", style: "margin-top:12px" }, saveBtn)));

  // — telegram —
  const tg = state.telegram || { linked: false, link_url: null };
  frag.append(h("section", { class: "card" },
    h("div", { class: "row" }, h("h2", { class: "spacer" }, t("telegramTitle")),
      h("span", { class: "status " + (tg.linked ? "ok" : "warn") }, tg.linked ? t("telegramLinked") : t("telegramNot"))),
    h("p", { class: "hint" }, t("telegramHint")),
    tg.linked
      ? h("button", { class: "ghost", onclick: async () => { await api("DELETE", "/me/telegram"); await refreshTelegram(); render(); } }, t("disconnect"))
      : (tg.link_url
          ? h("a", { href: tg.link_url, target: "_blank", rel: "noopener" }, h("button", { class: "primary", type: "button", onclick: startTelegramPolling }, t("connect")))
          : h("p", { class: "hint" }, "Telegram bot is not configured on this server."))));

  // — consent / pause —
  const consented = me.consented;
  const consentCard = h("section", { class: "card" }, h("h2", {}, t("consentTitle")), h("p", { class: "hint" }, t("consentText")));
  const consentBtn = h("button", { class: consented ? "ghost" : "primary", type: "button" }, consented ? t("consentWithdraw") : t("consentGrant"));
  consentBtn.addEventListener("click", async () => {
    if (!me.profile) { toast(t("needProfile"), true); return; }
    try { state.me = await api("POST", "/me/consent", { granted: !consented }); render(); }
    catch (err) { toast(err.message, true); }
  });
  const row = h("div", { class: "row" }, consentBtn);
  if (consented) {
    row.append(h("button", { class: "ghost", type: "button", onclick: async () => {
      try { state.me = await api("POST", "/me/pause", { paused: !me.paused }); render(); } catch (err) { toast(err.message, true); }
    } }, me.paused ? t("resume") : t("pause")));
  }
  consentCard.append(row);
  frag.append(consentCard);

  // — try now —
  const callBtn = h("button", { class: "primary", type: "button" }, t("callNow"));
  callBtn.addEventListener("click", async () => {
    if (!me.profile) { toast(t("needProfile"), true); return; }
    if (!consented) { toast(t("needConsent"), true); return; }
    callBtn.disabled = true;
    try {
      const r = await api("POST", "/me/call");
      location.href = r.call_path;
    } catch (err) { toast(err.message, true); callBtn.disabled = false; }
  });
  frag.append(h("section", { class: "card" }, h("h2", {}, t("tryTitle")), h("p", { class: "hint" }, t("tryHint")), callBtn));

  // — recent calls & transcripts —
  frag.append(callsCard());

  // — danger zone —
  frag.append(h("section", { class: "card" }, h("h2", {}, t("dangerTitle")), h("p", { class: "hint" }, t("dangerHint")),
    h("button", { class: "danger", type: "button", onclick: async () => {
      if (!confirm(t("confirmDelete"))) return;
      try { await api("DELETE", "/me", { confirm: true }); state.me = null; render(); } catch (err) { toast(err.message, true); }
    } }, t("delete"))));

  return frag;
}

function syncPressed(container, isOn) {
  [...container.children].forEach((b, i) => b.setAttribute("aria-pressed", String(isOn(b, i))));
}

function slotLabel(slot) {
  if (slot === "scheduled") return uiLang === "hi" ? "रोज़ की कॉल" : "Daily call";
  if (slot === "reminder") return uiLang === "hi" ? "रिमाइंडर" : "Reminder";
  return uiLang === "hi" ? "टेस्ट कॉल" : "Test call";
}

function callsCard() {
  const card = h("section", { class: "card" }, h("h2", {}, t("recentTitle")));
  const calls = state.calls;
  if (!calls || (!calls.attempts.length && !calls.transcripts.length)) {
    card.append(h("p", { class: "hint" }, t("none")));
    return card;
  }
  for (const a of calls.attempts) {
    const cls = { completed: "ok", answered: "ok", rung: "warn", ready: "warn", pending: "warn" }[a.status] || "bad";
    card.append(h("div", { class: "attempt" },
      h("span", {}, `${a.date} · ${slotLabel(a.slot)}`),
      h("span", { class: "status " + cls }, t("st")[a.status] || a.status)));
  }
  for (const tr of calls.transcripts) {
    card.append(h("details", { class: "transcript" },
      h("summary", {}, `${tr.date || ""} · ${tr.story_count ?? 0}`),
      h("div", { class: "script" }, tr.script),
      tr.qa.map((qa) => h("div", { class: "qa" }, h("b", {}, "Q: "), qa.q, h("br"), h("b", {}, "Jiya: "), qa.a))));
  }
  return card;
}

// ── data loading ──────────────────────────────────────────────────────────────────────────────
function draftFrom(me) {
  const p = me.profile;
  return {
    call_name: p ? p.call_name : "",
    interests: p ? [...p.interests] : [],
    free_text: p ? p.free_text : "",
    call_time: p ? p.call_time || "21:30" : "21:30",
    language: p ? p.language : me.defaults.language,
    timezone: p ? p.timezone : detectTimezone(me.defaults.timezone),
  };
}

async function refreshTelegram() { state.telegram = await api("GET", "/me/telegram"); }
async function refreshCalls() { state.calls = await api("GET", "/me/calls"); }

async function loadAll() {
  state.me = await api("GET", "/me");
  state.draft = draftFrom(state.me);
  await Promise.all([refreshTelegram(), refreshCalls()]);
}

function startTelegramPolling() {
  clearInterval(state.pollTimer);
  let n = 0;
  state.pollTimer = setInterval(async () => {
    n += 1;
    try {
      await refreshTelegram();
      if (state.telegram.linked) { clearInterval(state.pollTimer); render(); toast(t("telegramLinked")); }
    } catch (_) { /* transient */ }
    if (n > 60) clearInterval(state.pollTimer);
  }, 3000);
}

async function refreshUnderstood() {
  // the interest normalizer runs in the background; poll briefly for its result
  if (!state.me || !state.me.profile || !state.me.profile.free_text) return;
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    try {
      const me = await api("GET", "/me");
      if (me.profile && me.profile.understood) { state.me = me; render(); return; }
    } catch (_) { return; }
  }
}

// ── boot ────────────────────────────────────────────────────────────────────────────────────
$("#langToggle").addEventListener("click", () => {
  uiLang = uiLang === "hi" ? "en" : "hi";
  try { localStorage.setItem("ui", uiLang); } catch (_) { /* ignore */ }
  render();
});
$("#signOut").addEventListener("click", async () => {
  try { await api("DELETE", "/session"); } catch (_) { /* ignore */ }
  state.me = null; render();
});

(async function boot() {
  try {
    const topics = await api("GET", "/topics");
    state.topics = topics.topics; state.languages = topics.languages;
  } catch (err) { toast(err.message, true); }
  try { await loadAll(); } catch (_) { state.me = null; }
  render();
})();
