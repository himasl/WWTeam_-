const $ = (id) => document.getElementById(id);

function cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
}

function rows(id, items, make) {
  $(id).replaceChildren(...items.map((item) => {
    const tr = document.createElement("tr");
    tr.append(...make(item));
    return tr;
  }));
  $(id + "-empty").hidden = items.length > 0;
  $(id).parentElement.hidden = items.length === 0;
}

function withTitle(o) {
  const td = cell(o.question);
  const small = document.createElement("small");
  small.textContent = o.title;
  td.append(small);
  return [td, cell(o.n, "n")];
}

fetch("/api/stats").then(async (r) => {
  const s = await r.json();
  if (!r.ok) throw { detail: s.detail };
  return s;
}).then((s) => {
  $("total").textContent = s.total;
  $("share").textContent = (s.total ? Math.round((s.known / s.total) * 100) : 0) + "%";
  if (s.rated) {
    $("helped").textContent = Math.round((s.helped / s.rated) * 100) + "%";
    $("helped-note").textContent = "ответов помогли, отметок: " + s.rated;
  }
  $("ms").textContent = (s.ms / 1000).toFixed(1).replace(".", ",") + " с";
  $("escalated").textContent = s.escalated;
  rows("gaps", s.gaps, (g) => {
    const td = cell(g.question);
    if (g.escalated) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "в поддержке";
      td.append(" ", tag);
    }
    return [td, cell(g.n, "n")];
  });
  rows("unhelpful", s.unhelpful, withTitle);
  rows("often", s.often, withTitle);
  rows("topics", s.topics, (t) => [cell(t.topic), cell(t.n, "n")]);
}).catch((e) => {
  $("error").hidden = false;
  $("error").textContent = e.detail || "Сервер не отвечает, обновите страницу позже.";
  $("content").hidden = true;
});
