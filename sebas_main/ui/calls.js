/* Sebas on a call: live captions, taking over, and passing on a message silently.
   The panel opens from the "Calls" button, or by itself when a call mode starts. */
const Calls = (() => {
  const $ = (s) => document.querySelector(s);
  const panel = $("#call"), lines = $("#call-lines");
  const take = $("#call-take"), caps = $("#call-captions");
  const asWho = $("#call-as");
  let state = "off", pinned = false, names = [];
  const MAX_LINES = 8;
  const a = () => window.pywebview && window.pywebview.api;

  const TITLES = { off: "Calls", captions: "Captions · you are speaking", handling: "Sebas has the call" };

  function render() {
    panel.dataset.state = state;
    $("#call-title").textContent = TITLES[state] || "Calls";
    take.textContent = state === "handling" ? "Step back" : "Take the call";
    // several names (Krishiv, Hermit): one button each, so Sebas knows whose assistant he is
    const choose = state !== "handling" && names.length > 1;
    take.hidden = choose;
    asWho.hidden = !choose;
    if (choose && asWho.dataset.names !== names.join("|")) {
      asWho.dataset.names = names.join("|");
      asWho.textContent = "";
      names.forEach((n) => {
        const b = document.createElement("button");
        b.className = "game-btn"; b.textContent = `As ${n}`;
        b.addEventListener("click", () => takeAs(n));
        asWho.appendChild(b);
      });
    }
    caps.textContent = state === "captions" ? "Captions off" : "Captions";
    caps.disabled = state === "handling";
    panel.classList.toggle("on", pinned || state !== "off");
  }

  function apply(c) {
    if (!c) return;
    $("#call-route").textContent = c.route === "clean" ? "clean · VB-Cable" : "speaker";
    $("#call-warn").hidden = c.route === "clean";
    if (Array.isArray(c.names)) { names = c.names; render(); }
    if (c.state && c.state !== state) { state = c.state; render(); }
  }

  function setState(evt) {
    const was = state;
    state = evt.state || "off";
    apply(evt);
    if (state !== "off" && was === "off") lines.textContent = "";
    render();
  }

  function line(who, text) {
    const li = document.createElement("li");
    li.className = who;
    const tag = document.createElement("b");
    tag.textContent = who === "caller" ? "Caller" : who === "sebas" ? "Sebas" : "Summary";
    li.append(tag, document.createTextNode(text));
    lines.appendChild(li);
    while (lines.children.length > MAX_LINES) lines.firstChild.remove();
    lines.scrollTop = lines.scrollHeight;
  }

  async function takeAs(name) {
    if (!a()) { setState({ state: "handling" }); return; }
    const note = await a().call_take("", name);
    if (note) addEntry("notice", note);
  }

  function askName(list) {  // "take this call" typed, with several names: choose here
    if (Array.isArray(list)) names = list;
    pinned = true; render();
    panel.classList.remove("ask"); void panel.offsetWidth; panel.classList.add("ask");
  }

  function summary(text) {
    pinned = true; render();
    line("summary", text);
  }

  take.addEventListener("click", async () => {
    if (!a()) { setState({ state: state === "handling" ? "off" : "handling" }); return; }
    const note = state === "handling" ? await a().call_back() : await a().call_take("");
    if (note) addEntry("notice", note);
  });
  caps.addEventListener("click", async () => {
    if (!a()) { setState({ state: state === "captions" ? "off" : "captions" }); return; }
    const note = await a().call_captions(state !== "captions");
    if (note) addEntry("notice", note);
  });
  $("#call-relay").addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = $("#call-relay-text"), text = box.value.trim();
    if (!text) return;
    box.value = "";
    if (a()) { const note = await a().call_relay(text); if (note) addEntry("notice", note); }
    else line("sebas", `Pardon me. I am asked to say: ${text}`);
  });
  $("#call-test").addEventListener("click", () => { if (a()) a().send_text("test call audio"); });
  $("#call-close").addEventListener("click", () => { pinned = false; render(); });
  document.querySelector('.quick button[data-call]').addEventListener("click", () => { pinned = !pinned; render(); });

  // ?call=captions|handling previews the panel in a browser
  const preview = new URLSearchParams(location.search).get("call");
  if (preview) setTimeout(() => {
    setState({ state: preview === "summary" ? "off" : preview, route: "speaker", names: ["Krishiv", "Hermit"] });
    line("caller", "Hi, I wanted to ask about the project files.");
    line("sebas", "Good afternoon. This is Sebas, a personal assistant. May I take a message?");
    if (preview === "summary") summary("Rahul called about the project files and would like them tonight. Sebas said the message would be passed on.");
  }, 600);

  render();
  return { apply, setState, line, summary, askName };
})();
