const $ = (id) => document.getElementById(id);
const narrow = window.matchMedia("(max-width: 999px)");

const state = {
  catalog: { products: [], examples: [], unknown: [] },
  lists: {},
  ticks: {},
  history: [],
  current: null,
  controller: null,
  timer: 0,
};

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function product() {
  return state.catalog.products.find((p) => p.title === $("product").value);
}

function fill(listId, items) {
  $(listId).replaceChildren(...items.map((x) => el("li", x)));
  $(listId + "-empty").hidden = items.length > 0;
}

function seconds(ms) {
  return (ms / 1000).toFixed(1).replace(".", ",") + " с";
}

function pickTab(tab) {
  $("side").dataset.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
}

function renderIntro() {
  const p = product();
  $("scope-yes").textContent = state.catalog.known;
  $("scope-no").textContent = "Пока не знаю: " + state.catalog.unknown.join(", ") + ". Если ответа нет в базе знаний, так и скажу.";
  const items = p ? p.examples : state.catalog.examples;
  $("examples").replaceChildren(...items.map((q) => {
    const b = el("button", q);
    b.type = "button";
    b.onclick = () => ask(q);
    return b;
  }));
}

function renderList() {
  const name = $("list-pick").value;
  const steps = state.lists[name] || [];
  const ticks = state.ticks[name] || (state.ticks[name] = []);
  const progress = () => {
    const done = ticks.filter(Boolean).length;
    $("list-progress").textContent = "Выполнено " + done + " из " + steps.length;
  };
  $("list").replaceChildren(...steps.map((step, i) => {
    const label = el("label");
    const box = el("input");
    box.type = "checkbox";
    box.checked = Boolean(ticks[i]);
    box.onchange = () => { ticks[i] = box.checked; progress(); };
    label.append(box, el("span", step));
    return label;
  }));
  progress();
}

function syncList() {
  const p = product();
  if (p && p.checklist && state.lists[p.checklist]) {
    $("list-pick").value = p.checklist;
    renderList();
  }
}

function renderHistory() {
  const old = state.history.filter((h) => h !== state.current).reverse();
  $("history").hidden = old.length === 0;
  $("history").lastElementChild.replaceChildren(...old.map((h) => {
    const b = el("button");
    b.type = "button";
    const note = h.data.known ? h.data.sources[0].title : "нет ответа в базе";
    b.append(el("span", h.q), el("small", note, h.data.known ? "" : "no"));
    b.onclick = () => { show(h); scrollToAnswer(); };
    return b;
  }));
}

function scrollToAnswer() {
  if (narrow.matches) $("answer").scrollIntoView({ block: "start" });
}

function setStep(id, mode) {
  $(id).className = mode;
}

function startStatus(q) {
  $("intro").hidden = true;
  $("answer").hidden = true;
  $("more").hidden = true;
  $("status").hidden = false;
  $("status-q").textContent = q;
  $("found-list").textContent = "";
  $("found-label").textContent = "Подбираю разделы";
  $("step-model").hidden = false;
  setStep("step-search", "active");
  setStep("step-found", "");
  setStep("step-model", "");
  const start = performance.now();
  clearInterval(state.timer);
  state.timer = setInterval(() => { $("timer").textContent = seconds(performance.now() - start); }, 100);
  $("timer").textContent = "0,0 с";
}

function stopStatus() {
  clearInterval(state.timer);
  $("status").hidden = true;
}

function onFound(event) {
  setStep("step-search", "done");
  setStep("step-found", "done");
  const names = [...new Set(event.sections.map((s) => "«" + s.section + "»"))];
  $("found-label").textContent = "Нашёл в базе знаний";
  $("found-list").textContent = names.join(", ");
  $("step-model").hidden = !event.model;
  setStep("step-model", event.model ? "active" : "");
}

async function ask(text) {
  const q = (text || $("q").value).trim().replace(/\s+/g, " ");
  if (!q || state.controller) return;
  $("q").value = "";
  $("q").blur();
  $("send").disabled = true;
  startStatus(q);
  state.controller = new AbortController();
  let data = null;
  try {
    const res = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q, novice: $("novice").checked, product: $("product").value }),
      signal: state.controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      data = { error: err.detail || "Сервер вернул ошибку " + res.status };
    } else {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (!data) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, cut).trim();
          buf = buf.slice(cut + 1);
          if (!line) continue;
          const event = JSON.parse(line);
          if (event.stage === "found") onFound(event);
          if (event.stage === "done") data = event;
          if (event.stage === "error") data = { error: event.detail };
        }
      }
      if (!data) data = { error: "Ответ оборвался. Задайте вопрос ещё раз." };
    }
  } catch (e) {
    if (e.name === "AbortError") {
      state.controller = null;
      $("send").disabled = false;
      stopStatus();
      if (state.current) show(state.current); else $("intro").hidden = false;
      return;
    }
    data = { error: "Сервер не отвечает. Проверьте, что он запущен, и задайте вопрос ещё раз." };
  }
  state.controller = null;
  $("send").disabled = false;
  stopStatus();
  const entry = { q, data, rated: null, escalated: false };
  if (!data.error) state.history.push(entry);
  show(entry);
  scrollToAnswer();
}

function show(entry) {
  const { q, data } = entry;
  state.current = data.error ? state.current : entry;
  $("intro").hidden = true;
  $("answer").hidden = false;
  $("asked").textContent = q;
  $("foot").replaceChildren();
  $("more").hidden = true;
  $("rate").hidden = true;
  $("terms-box").hidden = true;
  document.querySelector('.tabs [data-tab="terms"]').hidden = true;
  if ($("side").dataset.tab === "terms") pickTab("ask");
  renderHistory();
  if (data.error) {
    $("answer").className = "card answer error";
    $("text").textContent = data.error;
    $("meta").textContent = "";
    return;
  }
  fill("ask", data.ask);
  fill("offer", data.offer);
  $("meta").textContent = "Ответ за " + seconds(data.ms) + ", " + (data.engine === "модель" ? "сформулировала модель по базе знаний" : "собран из базы знаний без модели");
  if (!data.known) {
    $("answer").className = "card answer unknown";
    $("text").textContent = "В базе знаний нет ответа на этот вопрос. Не отвечайте клиенту наугад.";
    const btn = el("button", entry.escalated ? "Вопрос передан в поддержку" : (data.id ? "Передать вопрос в поддержку" : "Журнал недоступен, передать нельзя"));
    btn.type = "button";
    btn.disabled = entry.escalated || !data.id;
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/escalate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: data.id }),
        });
        if (!res.ok) throw new Error();
        entry.escalated = true;
        btn.textContent = "Вопрос передан в поддержку";
      } catch (e) {
        btn.textContent = "Не удалось передать, попробуйте ещё раз";
        btn.disabled = false;
      }
    };
    $("foot").append(btn, el("span", "Вопрос попадёт в список пробелов базы знаний."));
    return;
  }
  $("answer").className = "card answer";
  $("text").textContent = data.answer;
  const src = data.sources[0];
  $("foot").append(el("strong", src.title + ", раздел «" + src.section + "»"));
  $("foot").append(el("span", "Источник: " + src.source + (src.actual ? ", данные на " + src.actual : "")));
  if (src.url) {
    const a = el("a", "Проверить в источнике");
    a.href = src.url;
    a.target = "_blank";
    a.rel = "noopener";
    $("foot").append(a);
  }
  renderRate(entry);
  const rest = data.sources.slice(1);
  $("more").hidden = rest.length === 0;
  $("more").lastElementChild.replaceChildren(...rest.map((s) => {
    const b = el("button");
    b.type = "button";
    b.append(el("span", s.quote[0]), el("small", s.title + ", раздел «" + s.section + "»"));
    b.onclick = () => {
      $("text").textContent = s.quote.join(" ");
      $("foot").firstChild.textContent = s.title + ", раздел «" + s.section + "»";
    };
    return b;
  }));
  if (data.terms.length) {
    $("terms-box").hidden = false;
    document.querySelector('.tabs [data-tab="terms"]').hidden = false;
    $("terms").replaceChildren(...data.terms.flatMap((t) => [el("dt", t.term), el("dd", t.meaning)]));
  }
}

function renderRate(entry) {
  const box = $("rate");
  box.hidden = !entry.data.id;
  const label = box.querySelector("span");
  label.textContent = entry.rated === null ? "Ответ помог?" : "Спасибо, отметили";
  box.querySelectorAll("button").forEach((b) => {
    const value = b.dataset.helpful === "1";
    b.classList.toggle("picked", entry.rated === value);
    b.disabled = entry.rated !== null;
    b.onclick = async () => {
      box.querySelectorAll("button").forEach((x) => { x.disabled = true; });
      try {
        const res = await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: entry.data.id, helpful: value }),
        });
        if (!res.ok) throw new Error();
        entry.rated = value;
      } catch (e) {
        label.textContent = "Не удалось отметить, попробуйте ещё раз";
        box.querySelectorAll("button").forEach((x) => { x.disabled = false; });
        return;
      }
      renderRate(entry);
    };
  });
}

function resetMeeting() {
  if (state.controller) state.controller.abort();
  state.history = [];
  state.current = null;
  state.ticks = {};
  $("answer").hidden = true;
  $("more").hidden = true;
  $("history").hidden = true;
  $("intro").hidden = false;
  fill("ask", []);
  fill("offer", []);
  $("terms-box").hidden = true;
  document.querySelector('.tabs [data-tab="terms"]').hidden = true;
  pickTab("ask");
  renderList();
  window.scrollTo(0, 0);
}

$("form").onsubmit = (e) => {
  e.preventDefault();
  ask();
};
$("cancel").onclick = () => { if (state.controller) state.controller.abort(); };
$("reset").onclick = resetMeeting;
$("product").onchange = () => { renderIntro(); syncList(); };
$("list-pick").onchange = renderList;
document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => pickTab(b.dataset.tab); });

Promise.all([
  fetch("/api/products").then((r) => r.json()),
  fetch("/api/checklists").then((r) => r.json()),
]).then(([catalog, lists]) => {
  state.catalog = catalog;
  state.lists = lists;
  const groups = {};
  catalog.products.forEach((p) => {
    if (!groups[p.topic]) {
      groups[p.topic] = document.createElement("optgroup");
      groups[p.topic].label = p.topic;
      $("product").append(groups[p.topic]);
    }
    groups[p.topic].append(new Option(p.title, p.title));
  });
  Object.keys(lists).forEach((name) => $("list-pick").append(new Option(name, name)));
  renderIntro();
  renderList();
}).catch(() => {
  $("scope-yes").textContent = "Сервер не отвечает. Проверьте, что он запущен, и обновите страницу.";
});

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Speech) {
  const rec = new Speech();
  rec.lang = "ru-RU";
  rec.interimResults = true;
  let live = false;
  rec.onresult = (e) => {
    const last = e.results[e.results.length - 1];
    $("q").value = last[0].transcript;
    if (last.isFinal) ask();
  };
  rec.onend = () => {
    live = false;
    $("mic").classList.remove("live");
    $("mic").setAttribute("aria-label", "Сказать вопрос голосом");
    $("q").placeholder = "Вопрос клиента";
  };
  rec.onerror = rec.onend;
  $("mic").onclick = () => {
    if (live) return rec.stop();
    live = true;
    $("q").value = "";
    $("q").placeholder = "Слушаю…";
    $("mic").classList.add("live");
    $("mic").setAttribute("aria-label", "Остановить запись");
    rec.start();
  };
} else {
  $("mic").disabled = true;
  $("mic").title = "Этот браузер не поддерживает голосовой ввод. Откройте страницу в Chrome или Safari.";
}
