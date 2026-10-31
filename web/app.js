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
  scenes: [],
  scene: null,
  view: null,
  facts: {},
  marks: {},
  at: 0,
  started: 0,
  finished: null,
};
const FIT = { yes: "Подходит", no: "Не подходит", maybe: "Уточните" };

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Сервер вернул ошибку " + res.status);
  return data;
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
    let note = h.data.known ? h.data.sources[0].title : "нет ответа в базе";
    if (h.colleague) note = h.colleague.status === "answered" ? "ответил наставник " + (h.colleague.mentor_name || "") : "ждёт ответа коллег";
    b.append(el("span", h.q), el("small", note, h.data.known || h.colleague ? "" : "no"));
    b.onclick = () => { show(h); scrollToAnswer(); };
    return b;
  }));
}

function scrollToAnswer() {
  if (narrow.matches) $("answer").scrollIntoView({ block: "start" });
  else if (state.scene) $("answer").scrollIntoView({ block: "nearest", behavior: "smooth" });
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
      body: JSON.stringify({ q, novice: $("novice").checked, product: $("product").value, person: who.id() }),
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
  const entry = { q, data, rated: null, colleague: null, step: stepNow() };
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
  $("colleague").hidden = true;
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
  renderColleague(entry);
  if (!data.known) {
    const reply = entry.colleague && entry.colleague.status === "answered";
    $("answer").className = "card answer " + (reply ? "mentor" : "unknown");
    $("text").textContent = reply ? entry.colleague.answer : "В базе знаний нет ответа на этот вопрос. Не отвечайте клиенту наугад, спросите коллег.";
    if (reply) {
      $("foot").append(el("strong", "Ответил наставник " + (entry.colleague.mentor_name || "")));
      $("foot").append(el("span", "Ответ дал человек, в базе знаний его пока нет"));
      $("colleague").hidden = true;
      $("meta").textContent = "";
    } else {
      $("foot").append(el("span", "Вопрос попадёт к наставникам и в список пробелов базы знаний."));
    }
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
      renderColleague(entry);
    };
  });
}

function renderColleague(entry) {
  const box = $("colleague");
  const c = entry.colleague;
  box.hidden = entry.data.known && entry.rated !== false && !c;
  box.className = "colleague" + (c && c.status === "answered" ? " got" : "");
  if (c && c.status === "answered") {
    box.replaceChildren(el("strong", "Наставник " + (c.mentor_name || "") + " ответил"), el("p", c.answer));
    return;
  }
  if (c) {
    box.replaceChildren(el("span", "Вопрос у наставников. Ответ появится здесь, можно продолжать встречу.", "wait"));
    return;
  }
  const btn = el("button", "Спросить коллег", "go");
  btn.type = "button";
  const note = el("span", entry.data.known ? "Ответ не подошёл? Наставник ответит сюда же." : "Наставник ответит сюда же, можно продолжать встречу.");
  btn.onclick = async () => {
    const me = await who.need();
    btn.disabled = true;
    try {
      entry.colleague = await post("/api/asks", {
        q: entry.q, person: me.id, scenario: state.scene ? state.scene.id : "", step: entry.step, log_id: entry.data.id,
      });
    } catch (e) {
      note.textContent = e.message === "Нет такого сотрудника" ? "Выберите себя заново и попробуйте ещё раз" : "Не удалось отправить, попробуйте ещё раз";
      btn.disabled = false;
      return;
    }
    if (state.current === entry) show(entry);
    renderHistory();
  };
  box.replaceChildren(btn, note);
}

async function poll() {
  const waiting = state.history.filter((h) => h.colleague && h.colleague.status === "open");
  for (const h of waiting) {
    try {
      const fresh = await fetch("/api/asks/" + h.colleague.id).then((r) => r.json());
      if (fresh.status !== "answered") continue;
      h.colleague = fresh;
      if (state.current === h && !$("answer").hidden) show(h);
      else news(h);
      renderHistory();
    } catch (e) { }
  }
}

function news(entry) {
  const b = el("button", "Открыть", "plain");
  b.type = "button";
  b.onclick = () => { $("news").hidden = true; show(entry); scrollToAnswer(); };
  $("news").replaceChildren(el("span", "Наставник ответил на вопрос «" + entry.q + "»"), b);
  $("news").hidden = false;
}

function stepNow() {
  if (!state.scene || state.finished) return "";
  const step = state.view.steps[state.at];
  return step ? step.id : "";
}

function renderScenes() {
  $("scenes-box").hidden = state.scenes.length === 0;
  $("free-title").className = state.scenes.length ? "sub" : "";
  $("scenes").replaceChildren(...state.scenes.map((s) => {
    const b = el("button");
    b.type = "button";
    b.append(el("b", s.title), el("span", s.about), el("small", s.steps + " шагов" + (s.draft ? ", черновик" : "")));
    b.onclick = () => startScene(s.id);
    return b;
  }));
}

async function startScene(id) {
  try {
    const res = await fetch("/api/scenarios/" + id);
    if (!res.ok) throw new Error();
    state.scene = await res.json();
    state.facts = {};
    state.marks = {};
    state.at = 0;
    state.finished = null;
    state.started = Date.now();
    await refresh();
  } catch (e) {
    state.scene = null;
    $("scope-yes").textContent = "Не удалось открыть сценарий. Проверьте, что сервер запущен.";
    return;
  }
  $("product").value = state.scene.product;
  renderIntro();
  syncList();
  $("intro").hidden = true;
  $("scene").hidden = false;
  $("steps-box").hidden = false;
  $("check-box").hidden = true;
  document.querySelector('.tabs [data-tab="steps"]').hidden = false;
  document.querySelector('.tabs [data-tab="check"]').hidden = true;
  pickTab("steps");
  renderScene();
  window.scrollTo(0, 0);
}

async function refresh() {
  const view = await post("/api/scenarios/" + state.scene.id + "/state", { facts: state.facts });
  const asked = new Set(view.steps.filter((s) => s.type === "question").map((s) => s.fact));
  const stale = Object.keys(state.facts).filter((f) => !asked.has(f));
  if (stale.length) {
    stale.forEach((f) => delete state.facts[f]);
    return refresh();
  }
  state.view = view;
}

function ticks(step) {
  const marks = state.marks[step.id] || (state.marks[step.id] = {});
  return step.items.map((x) => Boolean(marks[x.text]));
}

function stepDone(step, i) {
  if (step.type === "question") return step.fact in state.facts;
  if (step.type === "check" || step.type === "say") return ticks(step).every(Boolean);
  return i < state.at || Boolean(state.finished);
}

function stepNote(step) {
  if (step.type === "question") {
    const o = step.options.find((x) => x.value === state.facts[step.fact]);
    return o ? o.label : "";
  }
  if (step.type === "check" || step.type === "say") {
    const t = ticks(step);
    return t.filter(Boolean).length + " из " + t.length;
  }
  return "";
}

function renderStepList() {
  $("scene-steps").replaceChildren(...state.view.steps.map((s, i) => {
    const li = el("li", "", i === state.at && !state.finished ? "now" : (stepDone(s, i) ? "done" : ""));
    const b = el("button");
    b.type = "button";
    b.append(el("span", s.title));
    const note = stepNote(s);
    if (note) b.append(el("small", note));
    b.onclick = () => go(i);
    li.append(b);
    return li;
  }));
}

function go(i) {
  state.finished = null;
  state.at = Math.max(0, Math.min(i, state.view.steps.length - 1));
  renderScene();
  if (narrow.matches) $("scene").scrollIntoView({ block: "start" });
}

function nextLabel(step) {
  if (state.at === state.view.steps.length - 1) return "Завершить встречу";
  if (step.type === "question" && !(step.fact in state.facts)) return "Пропустить";
  if ((step.type === "check" || step.type === "say") && !ticks(step).every(Boolean)) return "Дальше без отметки";
  return "Далее";
}

function renderScene() {
  const steps = state.view.steps;
  $("scene-name").textContent = state.scene.title;
  $("scene-draft").hidden = !state.scene.draft;
  renderStepList();
  if (state.finished) return renderFinish();
  const step = steps[state.at];
  $("scene-count").textContent = "Шаг " + (state.at + 1) + " из " + steps.length;
  $("scene-meter").style.width = (state.at / steps.length * 100) + "%";
  const body = $("scene-body");
  body.replaceChildren(el("h2", step.title));
  if (step.hint) body.append(el("p", step.hint, "hint"));
  if (step.type === "question") {
    const opts = el("div", "", "options");
    step.options.forEach((o) => {
      const b = el("button", o.label, state.facts[step.fact] === o.value ? "on" : "");
      b.type = "button";
      b.onclick = () => answer(step, o.value);
      opts.append(b);
    });
    body.append(opts);
  }
  if (step.type === "check" || step.type === "say") {
    if (step.type === "say") body.append(el("p", "Отметьте, когда проговорили. Цифры взяты из базы знаний.", "hint"));
    const list = el("div", "", "ticks");
    const marks = state.marks[step.id] || (state.marks[step.id] = {});
    step.items.forEach((x) => {
      const label = el("label");
      const box = el("input");
      box.type = "checkbox";
      box.checked = Boolean(marks[x.text]);
      box.onchange = () => {
        marks[x.text] = box.checked;
        setNext(nextLabel(step));
        renderStepList();
      };
      const text = el("span");
      text.append(el("span", x.text));
      if (x.where) text.append(el("small", x.where));
      label.append(box, text);
      list.append(label);
    });
    body.append(list);
  }
  if (step.type === "tips") {
    step.items.forEach((x) => {
      const tip = el("div", "", "tip");
      tip.append(el("b", x.text), el("p", x.reply));
      body.append(tip);
    });
  }
  if (step.type === "verdict") {
    body.append(verdictList(state.view.verdict));
    if (state.scene.draft) body.append(el("p", "Правила составлены командой проекта по открытым тарифам банка. Перед оформлением сверьтесь с регламентом.", "hint"));
  }
  $("scene-back").hidden = false;
  $("scene-back").textContent = "Назад";
  $("scene-back").disabled = state.at === 0;
  $("scene-ask").hidden = false;
  setNext(nextLabel(step));
}

function setNext(label) {
  $("scene-next").textContent = label;
  $("scene-next").className = label === "Пропустить" || label === "Дальше без отметки" ? "plain" : "go";
}

function verdictList(items) {
  const list = el("div", "", "offers");
  items.forEach((v) => {
    const card = el("div", "", "offer " + v.fit);
    card.append(el("span", FIT[v.fit], "badge"), el("b", v.product), el("p", v.reason));
    list.append(card);
  });
  return list;
}

async function answer(step, value) {
  state.facts[step.fact] = value;
  try {
    await refresh();
  } catch (e) {
    $("scene-body").append(el("p", "Сервер не отвечает, ответ не учтён. Попробуйте ещё раз.", "err"));
    return;
  }
  state.at = Math.min(state.at + 1, state.view.steps.length - 1);
  renderScene();
}

async function finish() {
  const checks = {};
  state.view.steps.filter((s) => s.type === "check" || s.type === "say").forEach((s) => { checks[s.id] = ticks(s); });
  $("scene-next").disabled = true;
  try {
    state.finished = await post("/api/runs", {
      scenario: state.scene.id, person: who.id(), facts: state.facts, checks, ms: Date.now() - state.started,
    });
  } catch (e) {
    state.finished = { error: e.message, missed: [], verdict: state.view.verdict };
  }
  $("scene-next").disabled = false;
  renderScene();
}

function renderFinish() {
  const done = state.finished;
  $("scene-count").textContent = "Встреча завершена";
  $("scene-meter").style.width = "100%";
  const body = $("scene-body");
  body.replaceChildren(el("h2", "Итог встречи"));
  if (done.error) {
    body.append(el("p", "Не удалось сохранить встречу: " + done.error, "err"));
  } else {
    const me = who.get();
    body.append(el("p", me ? "Встреча сохранена за сотрудником " + me.name + "." : "Встреча сохранена без имени. Нажмите «Кто вы?» вверху, чтобы следующие встречи сохранялись за вами.", "hint"));
  }
  body.append(verdictList(done.verdict));
  if (!done.error && done.missed.length === 0) {
    body.append(el("p", "Все пункты отмечены, ничего не забыто.", "allgood"));
  }
  if (done.missed.length) {
    body.append(el("h3", "Не отмечено"));
    const list = el("ul", "", "missed");
    done.missed.forEach((m) => {
      const li = el("li");
      const b = el("button");
      b.type = "button";
      b.append(el("span", m.item), el("small", m.step));
      b.onclick = () => go(state.view.steps.findIndex((s) => s.title === m.step));
      li.append(b);
      list.append(li);
    });
    body.append(list);
  }
  $("scene-back").hidden = false;
  $("scene-back").disabled = false;
  $("scene-back").textContent = "К шагам";
  $("scene-ask").hidden = true;
  setNext(done.error ? "Сохранить ещё раз" : "Новая встреча");
}

function endScene() {
  state.scene = null;
  state.view = null;
  state.finished = null;
  $("scene").hidden = true;
  $("steps-box").hidden = true;
  $("check-box").hidden = false;
  document.querySelector('.tabs [data-tab="steps"]').hidden = true;
  document.querySelector('.tabs [data-tab="check"]').hidden = false;
}

function resetMeeting() {
  if (state.controller) state.controller.abort();
  state.history = [];
  state.current = null;
  state.ticks = {};
  endScene();
  $("news").hidden = true;
  $("q").placeholder = "Вопрос клиента";
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
$("scene-back").onclick = () => {
  if (state.finished) go(state.view.steps.length - 1);
  else go(state.at - 1);
};
$("scene-next").onclick = () => {
  if (state.finished && !state.finished.error) return resetMeeting();
  if (state.finished || state.at === state.view.steps.length - 1) return finish();
  go(state.at + 1);
};
$("scene-ask").onclick = () => {
  const step = state.view.steps[state.at];
  $("q").placeholder = "Вопрос по шагу «" + step.title + "»";
  $("q").focus();
};
setInterval(poll, 4000);
$("product").onchange = () => { renderIntro(); syncList(); };
$("list-pick").onchange = renderList;
document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => pickTab(b.dataset.tab); });

Promise.all([
  fetch("/api/products").then((r) => r.json()),
  fetch("/api/checklists").then((r) => r.json()),
  fetch("/api/scenarios").then((r) => r.json()).catch(() => ({ scenarios: [] })),
]).then(([catalog, lists, scenes]) => {
  state.catalog = catalog;
  state.lists = lists;
  state.scenes = scenes.scenarios;
  renderScenes();
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
