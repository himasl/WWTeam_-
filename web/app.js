const $ = (id) => document.getElementById(id);
const samples = [
  "Сколько стоит обслуживание карты?",
  "Какой льготный период по кредитной карте?",
  "Сколько можно снять наличных без комиссии?",
  "Какая ставка по накопительному счёту?",
  "Как перевести пенсию в ВТБ?",
  "Клиент сомневается, что я из банка",
];
let product = "";
let lastId = 0;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function fill(listId, items) {
  const list = $(listId);
  list.replaceChildren(...items.map((x) => el("li", x)));
  $(listId + "-empty").hidden = items.length > 0;
}

async function ask(text) {
  const q = (text || $("q").value).trim();
  if (!q) return;
  $("q").value = q;
  $("send").disabled = true;
  $("send").textContent = "Ищу ответ";
  let data;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q, novice: $("novice").checked, product }),
    });
    data = await res.json();
    if (!res.ok) data = { error: data.detail || "Сервер вернул ошибку " + res.status };
  } catch (e) {
    data = { error: "Сервер не отвечает. Проверьте, что он запущен, и задайте вопрос ещё раз." };
  }
  $("send").disabled = false;
  $("send").textContent = "Спросить";
  show(q, data);
}

function show(q, data) {
  $("examples").hidden = true;
  $("answer").hidden = false;
  $("asked").textContent = q;
  $("foot").replaceChildren();
  $("more").hidden = true;
  $("terms-box").hidden = true;
  if (data.error) {
    $("answer").className = "answer unknown";
    $("text").textContent = data.error;
    $("meta").textContent = "";
    fill("ask", []);
    fill("offer", []);
    return;
  }
  lastId = data.id;
  fill("ask", data.ask);
  fill("offer", data.offer);
  $("meta").textContent = "Ответ за " + (data.ms / 1000).toFixed(1).replace(".", ",") + " с, режим: " + data.engine;
  if (!data.known) {
    $("answer").className = "answer unknown";
    $("text").textContent = "В базе знаний нет ответа на этот вопрос. Не отвечайте клиенту наугад.";
    const btn = el("button", lastId ? "Передать вопрос в поддержку" : "Журнал недоступен, передать нельзя");
    btn.disabled = !lastId;
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/escalate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: lastId }),
        });
        if (!res.ok) throw new Error();
        btn.textContent = "Вопрос передан в поддержку";
      } catch (e) {
        btn.textContent = "Не удалось передать, попробуйте ещё раз";
        btn.disabled = false;
      }
    };
    $("foot").append(btn, el("span", "Вопрос попадёт в список пробелов базы знаний."));
    return;
  }
  $("answer").className = "answer";
  $("text").textContent = data.answer;
  const src = data.sources[0];
  $("foot").append(el("strong", src.title + ", раздел «" + src.section + "»"));
  $("foot").append(el("span", "Источник: " + src.source + (src.actual ? ", данные на " + src.actual : "")));
  if (src.url) {
    const a = el("a", "Открыть источник");
    a.href = src.url;
    a.target = "_blank";
    a.rel = "noopener";
    $("foot").append(a);
  }
  const rest = data.sources.slice(1);
  $("more").hidden = rest.length === 0;
  $("more").lastElementChild.replaceChildren(...rest.map((s) => {
    const b = el("button");
    b.append(el("span", s.quote[0]), el("small", s.title + ", раздел «" + s.section + "»"));
    b.onclick = () => {
      $("text").textContent = s.quote.join(" ");
      $("foot").firstChild.textContent = s.title + ", раздел «" + s.section + "»";
    };
    return b;
  }));
  if (data.terms.length) {
    $("terms-box").hidden = false;
    $("terms").replaceChildren(...data.terms.flatMap((t) => [el("dt", t.term), el("dd", t.meaning)]));
  }
}

$("form").onsubmit = (e) => {
  e.preventDefault();
  ask();
};

$("examples").lastElementChild.replaceChildren(...samples.map((s) => {
  const b = el("button", s);
  b.onclick = () => ask(s);
  return b;
}));

fetch("/api/products").then((r) => r.json()).then((items) => {
  ["Любой", ...items].forEach((name, i) => {
    const b = el("button", name, "chip" + (i === 0 ? " on" : ""));
    b.type = "button";
    b.onclick = () => {
      product = i === 0 ? "" : name;
      document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
    };
    $("products").append(b);
  });
});

fetch("/api/checklists").then((r) => r.json()).then((lists) => {
  const pick = $("list-pick");
  Object.keys(lists).forEach((name) => pick.append(new Option(name, name)));
  const draw = () => {
    $("list").replaceChildren(...lists[pick.value].map((step) => {
      const label = el("label");
      const box = el("input");
      box.type = "checkbox";
      label.append(box, el("span", step));
      return label;
    }));
  };
  pick.onchange = draw;
  draw();
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
    $("mic").setAttribute("aria-label", "Голосовой ввод");
  };
  rec.onerror = rec.onend;
  $("mic").onclick = () => {
    if (live) return rec.stop();
    live = true;
    $("q").value = "";
    $("mic").classList.add("live");
    $("mic").setAttribute("aria-label", "Остановить запись");
    rec.start();
  };
} else {
  $("mic").disabled = true;
  $("mic").title = "Этот браузер не поддерживает голосовой ввод. Откройте страницу в Chrome или Safari.";
}
