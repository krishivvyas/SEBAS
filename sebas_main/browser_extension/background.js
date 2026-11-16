// Sebas Browser Hands: the browser's end of the link to Sebas (custom_tools/browser.py).
//
// It connects to Sebas on this computer only (127.0.0.1) and carries out the
// commands he sends, in ONE tab: the tab it opened for him. It never reads or
// touches any other tab. All judgment (what to click, what needs the user's
// yes, what must never be typed) is made on Sebas's side; this file only looks
// and acts.

const PORT = 47615;
const RETRY_MINUTES = 0.5;      // the shortest alarm an extension may set
let socket = null;

// ---- the link ---------------------------------------------------------------
function connect() {
  if (socket && socket.readyState <= 1) return;  // connecting or open
  try { socket = new WebSocket(`ws://127.0.0.1:${PORT}`); } catch { socket = null; return; }
  socket.onopen = () => setBadge(true);
  socket.onclose = () => { socket = null; setBadge(false); };
  socket.onerror = () => {};  // onclose follows
  socket.onmessage = async (event) => {
    let message; try { message = JSON.parse(event.data); } catch { return; }
    if (message.cmd === "ping") { send({ id: message.id, ok: true, result: "pong" }); return; }
    try { send({ id: message.id, ok: true, result: await run(message.cmd, message.args || {}) }); }
    catch (error) { send({ id: message.id, ok: false, error: String(error && error.message || error) }); }
  };
}
function send(data) { if (socket && socket.readyState === 1) socket.send(JSON.stringify(data)); }
function setBadge(on) {
  chrome.action.setBadgeText({ text: on ? "on" : "" });
  chrome.action.setTitle({ title: on ? "Sebas Browser Hands: connected to Sebas" : "Sebas Browser Hands: Sebas is not running" });
}
// Sebas pings every 20 s while connected, which keeps this worker awake. When he
// is not running, the alarm wakes it to try again.
chrome.alarms.create("sebas-retry", { periodInMinutes: RETRY_MINUTES });
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();

// ---- the one tab --------------------------------------------------------------
async function tabId() {
  const { sebasTab } = await chrome.storage.session.get("sebasTab");
  if (sebasTab == null) throw new Error("no-tab");
  try { await chrome.tabs.get(sebasTab); } catch { throw new Error("tab-closed"); }
  return sebasTab;
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function settled(id, ms = 9000) {
  // An action may or may not start a page load: give it a moment to begin, wait
  // for the tab to finish loading (or `ms`, for a page that never settles), then
  // a little longer for scripts to draw the page.
  const until = Date.now() + ms;
  await sleep(400);
  while (Date.now() < until) {
    let tab; try { tab = await chrome.tabs.get(id); } catch { return; }
    if (tab.status === "complete") break;
    await sleep(250);
  }
  await sleep(500);
}
async function inPage(func, args = []) {
  const id = await tabId();
  const [frame] = await chrome.scripting.executeScript({ target: { tabId: id }, func, args });
  // An exception thrown inside the page does not reject this call (seen live: a
  // refused password field was reported as success), so page functions report
  // failure as {sebasError: "..."} instead of throwing.
  if (frame && frame.result && frame.result.sebasError) throw new Error(frame.result.sebasError);
  return frame ? frame.result : null;
}

async function run(cmd, args) {
  if (cmd === "open") {
    if (!/^https?:\/\//i.test(args.url || "")) throw new Error("only http and https pages can be opened");
    const tab = await chrome.tabs.create({ url: args.url, active: true });
    await chrome.storage.session.set({ sebasTab: tab.id });
    await settled(tab.id);
    return true;
  }
  const id = await tabId();
  if (cmd === "goto") {
    if (!/^https?:\/\//i.test(args.url || "")) throw new Error("only http and https pages can be opened");
    await chrome.tabs.update(id, { url: args.url }); await settled(id); return true;
  }
  // (chrome.tabs.goBack failed in Edge 157 with "Cannot find a next page in history"; the page's own history works)
  if (cmd === "back") { await inPage(() => history.back()); await settled(id, 5000); return true; }
  if (cmd === "close") { await chrome.tabs.remove(id); await chrome.storage.session.remove("sebasTab"); return true; }
  if (cmd === "snapshot") return inPage(snapshot, [args.maxText || 6000, args.maxElements || 80]);
  if (cmd === "scroll") { await inPage((down) => window.scrollBy(0, (down ? 1 : -1) * innerHeight * 0.8), [args.up ? false : true]); return true; }
  if (cmd === "click") { const r = await inPage(click, [args.n]); await settled(id, 6000); return r; }
  if (cmd === "type") { const r = await inPage(type, [args.n, args.text || "", !!args.enter]); if (args.enter) await settled(id, 6000); return r; }
  throw new Error(`unknown command ${cmd}`);
}

// ---- functions that run inside the page ---------------------------------------
// (Each is self-contained: it is sent to the page as source text.)
function snapshot(maxText, maxElements) {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && st.visibility !== "hidden" && st.display !== "none" && st.opacity !== "0";
  };
  const labelOf = (el) => {
    let text = el.getAttribute("aria-label") || "";
    if (!text && el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) text = l.innerText; }
    if (!text && el.closest("label")) text = el.closest("label").innerText;
    if (!text) text = el.innerText || el.value || el.placeholder || el.title || el.name || el.alt || "";
    if (!text && el.querySelector && el.querySelector("img[alt]")) text = el.querySelector("img[alt]").alt;
    return clean(text).slice(0, 90);
  };
  document.querySelectorAll("[data-sebas-n]").forEach((el) => el.removeAttribute("data-sebas-n"));
  const found = [...document.querySelectorAll(
    "a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [contenteditable=true]")]
    .filter(visible);
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; };
  found.sort((a, b) => Number(inView(b)) - Number(inView(a)));  // what is on screen first; order otherwise kept
  const elements = [];
  for (const el of found) {
    if (elements.length >= maxElements) break;
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute("type") || "").toLowerCase();
    const kind = tag === "a" || el.getAttribute("role") === "link" ? "link"
      : tag === "select" ? "select"
      : tag === "textarea" || el.isContentEditable || (tag === "input" && !["submit", "button", "checkbox", "radio", "image", "reset", "file"].includes(type)) ? "field"
      : tag === "input" && (type === "checkbox" || type === "radio") ? type : "button";
    const label = labelOf(el);
    if (!label && kind !== "field") continue;
    const form = el.closest("form");
    const item = { n: elements.length + 1, kind, label };
    if (kind === "field") {
      item.type = type || (tag === "textarea" ? "textarea" : "text");
      item.autocomplete = el.getAttribute("autocomplete") || "";
      item.name = clean(el.getAttribute("name") || el.id || "").slice(0, 40);
      if (el.value && type !== "password") item.value = clean(el.value).slice(0, 60);
    }
    if (kind === "link") { try { item.href = new URL(el.getAttribute("href"), location.href).href.slice(0, 200); } catch {} }
    if (form) {
      const fields = [...form.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select")];
      item.form = {
        // a search box: marked as one, or a single text field with a search-like name
        search: form.getAttribute("role") === "search" || !!form.querySelector("input[type=search]") ||
          /search|find|query/i.test((form.getAttribute("action") || "") + " " + (form.id || "") + " " + (form.className || "")) ||
          (fields.length === 1 && /^(q|s|k|query|search|keyword|keywords|field-keywords|search_query)$/i.test(fields[0].name || "")),
        fields: fields.length,
        password: !!form.querySelector("input[type=password]"),
      };
      if (kind === "button") item.submits = tag === "input" ? ["submit", "image"].includes(type) : (type === "submit" || (tag === "button" && !type));
    }
    el.setAttribute("data-sebas-n", String(item.n));
    elements.push(item);
  }
  const main = document.querySelector("main, article, [role=main]") || document.body;
  let text = clean(main ? main.innerText : "");
  if (text.length < 400 && document.body) text = clean(document.body.innerText);
  return { url: location.href, title: clean(document.title).slice(0, 150), text: text.slice(0, maxText),
           truncated: text.length > maxText, elements, scrolled: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight) };
}
function click(n) {
  const el = document.querySelector(`[data-sebas-n="${n}"]`);
  if (!el) return { sebasError: "stale: that element is no longer on the page" };
  el.scrollIntoView({ block: "center" });
  el.click();
  return true;
}
function type(n, text, enter) {
  const el = document.querySelector(`[data-sebas-n="${n}"]`);
  if (!el) return { sebasError: "stale: that element is no longer on the page" };
  if ((el.getAttribute("type") || "").toLowerCase() === "password") return { sebasError: "refused: password field" };
  el.scrollIntoView({ block: "center" });
  el.focus();
  if (el.isContentEditable) { el.textContent = text; }
  else if (el.tagName === "SELECT") {
    const option = [...el.options].find((o) => o.text.trim().toLowerCase() === text.trim().toLowerCase() || o.value === text);
    if (!option) return { sebasError: "no such option: " + [...el.options].map((o) => o.text.trim()).slice(0, 15).join(" | ") };
    el.value = option.value;
  } else {
    // through the element's own setter, so pages built with React and the like notice
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, text);
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  if (enter) {
    const key = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true };
    const proceed = el.dispatchEvent(new KeyboardEvent("keydown", key));
    el.dispatchEvent(new KeyboardEvent("keyup", key));
    if (proceed && el.form) { if (el.form.requestSubmit) el.form.requestSubmit(); else el.form.submit(); }
  }
  return true;
}
