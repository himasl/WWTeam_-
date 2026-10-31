const $ = (id) => document.getElementById(id);
const drafts = {};
const STEPS = {};

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function ago(ts) {
  const min = Math.round((Date.now() / 1000 - ts) / 60);
  if (min < 1) return "только что";
  if (min < 60) return min + " мин назад";
  return new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
}

function where(a) {
  const parts = [a.name || "без имени", ago(a.ts)];
  if (a.scenario) parts.push("встреча «" + (STEPS[a.scenario] ? STEPS[a.scenario].title : a.scenario) + "»");
  if (a.scenario && a.step && STEPS[a.scenario] && STEPS[a.scenario].steps[a.step]) parts.push("шаг «" + STEPS[a.scenario].steps[a.step] + "»");
  return parts.join(", ");
}

function openCard(a) {
  const card = el("form", "", "ask");
  card.append(el("b", a.question), el("small", where(a)));
  const text = el("textarea");
  text.rows = 3;
  text.placeholder = "Ответ для сотрудника";
  text.value = drafts[a.id] || "";
  text.oninput = () => { drafts[a.id] = text.value; };
  const btn = el("button", "Ответить", "go");
  const note = el("span", "", "err");
  card.append(text, btn, note);
  card.onsubmit = async (e) => {
    e.preventDefault();
    if (!text.value.trim()) { note.textContent = "Напишите ответ"; return; }
    const me = await who.need();
    btn.disabled = true;
    try {
      const res = await fetch("/api/asks/" + a.id + "/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: text.value, mentor: me.id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      delete drafts[a.id];
      load();
    } catch (e2) {
      note.textContent = e2.message || "Сервер не отвечает, попробуйте ещё раз";
      btn.disabled = false;
    }
  };
  return card;
}

function doneCard(a) {
  const card = el("div", "", "ask done");
  card.append(el("b", a.question), el("small", where(a)), el("p", a.answer), el("small", "Ответил " + (a.mentor_name || "наставник") + ", " + ago(a.answered_ts)));
  return card;
}

async function load() {
  try {
    const items = await fetch("/api/asks").then((r) => { if (!r.ok) throw new Error(); return r.json(); });
    const open = items.filter((a) => a.status === "open");
    const done = items.filter((a) => a.status === "answered");
    const typing = document.activeElement && document.activeElement.tagName === "TEXTAREA";
    if (!typing) $("open").replaceChildren(...open.map(openCard));
    $("done").replaceChildren(...done.map(doneCard));
    $("open-empty").hidden = open.length > 0;
    $("done-empty").hidden = done.length > 0;
    $("open-count").textContent = open.length ? open.length : "";
    $("error").hidden = true;
  } catch (e) {
    $("error").textContent = "Сервер не отвечает. Проверьте, что он запущен.";
    $("error").hidden = false;
  }
}

fetch("/api/scenarios").then((r) => r.json()).then(async (data) => {
  for (const s of data.scenarios) {
    const full = await fetch("/api/scenarios/" + s.id).then((r) => r.json());
    STEPS[s.id] = { title: s.title, steps: Object.fromEntries(full.steps.map((x) => [x.id, x.title])) };
  }
}).catch(() => { }).finally(load);
setInterval(load, 5000);
