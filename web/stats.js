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

fetch("/api/stats").then(async (r) => {
  const s = await r.json();
  if (!r.ok) throw { detail: s.detail };
  return s;
}).then((s) => {
  $("total").textContent = s.total;
  $("share").textContent = (s.total ? Math.round((s.known / s.total) * 100) : 0) + "%";
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
  rows("often", s.often, (o) => {
    const td = cell(o.question);
    const small = document.createElement("small");
    small.textContent = o.title;
    td.append(small);
    return [td, cell(o.n, "n")];
  });
  rows("topics", s.topics, (t) => [cell(t.topic), cell(t.n, "n")]);
}).catch((e) => {
  const p = document.createElement("p");
  p.className = "lead";
  p.textContent = e.detail || "Сервер не отвечает, обновите страницу позже.";
  document.querySelector(".tiles").replaceWith(p);
  document.querySelector(".cols").hidden = true;
});
