const who = (() => {
  const KEY = "wpomoshnik.person";
  let me = null;
  let waiting = null;
  try { me = JSON.parse(localStorage.getItem(KEY)); } catch (e) { me = null; }

  const box = document.createElement("dialog");
  box.className = "who";
  box.innerHTML = `
    <form method="dialog">
      <h2>Кто работает с помощником?</h2>
      <p>Вход не нужен. Имя нужно, чтобы встречи и вопросы коллегам сохранялись за вами.</p>
      <div class="people"></div>
      <label class="field"><span>Имя и фамилия</span><input name="name" maxlength="60" autocomplete="name"></label>
      <div class="roles">
        <label><input type="radio" name="role" value="сотрудник" checked><span>Сотрудник</span></label>
        <label><input type="radio" name="role" value="наставник"><span>Наставник</span></label>
      </div>
      <p class="err" hidden></p>
      <div class="row">
        <button type="button" class="plain" value="cancel">Отмена</button>
        <button type="submit" class="go">Готово</button>
      </div>
    </form>`;
  document.body.append(box);
  const form = box.querySelector("form");
  const err = box.querySelector(".err");

  function label() {
    const btn = document.getElementById("who-btn");
    if (!btn) return;
    btn.replaceChildren();
    if (me) {
      const full = document.createElement("span");
      const short = document.createElement("span");
      full.className = "long";
      short.className = "short";
      full.textContent = me.name;
      short.textContent = me.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
      btn.append(full, short);
    } else {
      btn.textContent = "Кто вы?";
    }
    btn.title = me ? me.role + ", нажмите, чтобы сменить" : "Выберите себя, чтобы встречи сохранялись за вами";
  }

  function set(person) {
    me = person;
    try { localStorage.setItem(KEY, JSON.stringify(person)); } catch (e) { }
    label();
    box.close();
    if (waiting) { const done = waiting; waiting = null; done(person); }
  }

  async function open(then) {
    waiting = then || null;
    err.hidden = true;
    form.name.value = "";
    const list = box.querySelector(".people");
    list.replaceChildren();
    try {
      const people = await fetch("/api/people").then((r) => r.json());
      list.replaceChildren(...people.map((p) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = me && me.id === p.id ? "on" : "";
        b.innerHTML = "<span></span><small></small>";
        b.firstChild.textContent = p.name;
        b.lastChild.textContent = p.role;
        b.onclick = () => set(p);
        return b;
      }));
    } catch (e) { }
    box.showModal();
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    const name = form.name.value.trim();
    if (!name) { err.textContent = "Введите имя или выберите себя из списка"; err.hidden = false; return; }
    try {
      const res = await fetch("/api/people", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, role: form.role.value }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      set(data);
    } catch (e2) {
      err.textContent = e2.message || "Сервер не отвечает, попробуйте ещё раз";
      err.hidden = false;
    }
  };
  box.querySelector('[value="cancel"]').onclick = () => { waiting = null; box.close(); };
  const btn = document.getElementById("who-btn");
  if (btn) btn.onclick = () => open();
  label();
  fetch("/api/people").then((r) => r.json()).then((people) => {
    if (me && !people.some((p) => p.id === me.id && p.name === me.name)) {
      me = null;
      try { localStorage.removeItem(KEY); } catch (e) { }
      label();
    }
  }).catch(() => { });

  return {
    get: () => me,
    id: () => (me ? me.id : null),
    open,
    need: () => new Promise((resolve) => (me ? resolve(me) : open(resolve))),
  };
})();
