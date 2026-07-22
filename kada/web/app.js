// kada frontend. No build step, no framework: it boots from /api/config, decides
// whether to show a login screen, and renders one view at a time into #app.

const app = document.getElementById("app");
const whoami = document.getElementById("whoami");

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    boot();
    throw new Error("login_required");
  }
  return res;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  for (const c of children) node.append(c);
  return node;
}

function clear() {
  app.replaceChildren();
}

async function boot() {
  const cfg = await (await fetch("/api/config")).json();
  if (!cfg.user) {
    whoami.textContent = "";
    return cfg.login_enabled ? renderLogin() : renderLocked();
  }
  whoami.textContent = cfg.user.name;
  renderHome();
}

function renderLocked() {
  clear();
  app.append(
    el("div", { className: "card" },
      el("p", {}, "Du må logge inn for å bruke kada."),
    ),
  );
}

function renderLogin() {
  clear();
  const name = el("input", { type: "text", placeholder: "Navnet ditt", maxLength: 24 });
  const go = el("button", {}, "Logg inn");
  const err = el("p", { className: "muted" });
  go.onclick = async () => {
    const res = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ name: name.value }),
    });
    if (res.ok) return boot();
    err.textContent = "Prøv et annet navn.";
  };
  app.append(el("div", { className: "card" }, el("p", { className: "prompt" }, "Hvem er du?"), name, el("div", {}, go), err));
}

async function renderHome() {
  clear();
  const [{ quizzes }, { attempts }] = await Promise.all([
    (await api("/api/quizzes")).json(),
    (await api("/api/me/attempts")).json(),
  ]);

  const list = el("ul", { className: "quizzes" });
  for (const q of quizzes) {
    const start = el("button", {}, "Start");
    start.onclick = () => renderQuiz(q.id);
    list.append(el("li", {}, el("span", {}, `${q.title} (${q.questions})`), start));
  }
  app.append(el("div", { className: "card" }, el("p", { className: "prompt" }, "Velg en quiz"), quizzes.length ? list : el("p", { className: "muted" }, "Ingen quizer enda.")));

  if (attempts.length) {
    const hist = el("div", { className: "card" }, el("p", { className: "prompt" }, "Tidligere forsøk"));
    for (const a of attempts.slice(0, 10)) {
      hist.append(el("p", { className: "muted" }, `${a.quiz_title}: ${a.score}/${a.total}`));
    }
    app.append(hist);
  }
}

async function renderQuiz(id) {
  clear();
  const quiz = await (await api(`/api/quizzes/${id}`)).json();
  const inputs = new Map();
  const card = el("div", { className: "card" }, el("p", { className: "prompt" }, quiz.title));

  for (const q of quiz.questions) {
    const block = el("div", { className: "question" }, el("p", { className: "prompt" }, q.prompt));
    block.append(renderInput(q, inputs));
    card.append(block);
  }

  const submit = el("button", {}, "Lever");
  submit.onclick = async () => {
    const answers = {};
    for (const [qid, read] of inputs) answers[qid] = read();
    const res = await api(`/api/quizzes/${id}/submit`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    });
    renderResult(quiz, await res.json());
  };
  const back = el("button", { className: "ghost" }, "Tilbake");
  back.onclick = renderHome;
  card.append(el("div", {}, submit, " ", back));
  app.append(card);
}

function renderInput(q, inputs) {
  if (q.type === "multiple_choice") {
    const wrap = el("div", { className: "choices" });
    q.choices.forEach((c, i) => {
      const radio = el("input", { type: "radio", name: q.id, value: String(i) });
      wrap.append(el("label", { className: "choice" }, radio, c));
    });
    inputs.set(q.id, () => {
      const sel = wrap.querySelector("input:checked");
      return sel ? Number(sel.value) : null;
    });
    return wrap;
  }
  if (q.type === "true_false") {
    const wrap = el("div", {});
    const yes = el("input", { type: "radio", name: q.id, value: "true" });
    const no = el("input", { type: "radio", name: q.id, value: "false" });
    wrap.append(el("label", { className: "tf" }, yes, "Sant"), el("label", { className: "tf" }, no, "Usant"));
    inputs.set(q.id, () => {
      const sel = wrap.querySelector("input:checked");
      return sel ? sel.value === "true" : null;
    });
    return wrap;
  }
  if (q.type === "numeric") {
    const input = el("input", { type: "number" });
    inputs.set(q.id, () => (input.value === "" ? null : Number(input.value)));
    return input;
  }
  const input = el("input", { type: "text" });
  inputs.set(q.id, () => input.value);
  return input;
}

function renderResult(quiz, result) {
  clear();
  const card = el("div", { className: "card" });
  card.append(el("p", { className: "score" }, `Du fikk ${result.score} av ${result.total}!`));
  for (const q of quiz.questions) {
    const r = result.results[q.id] || {};
    const line = el("p", { className: `result ${r.correct ? "correct" : "wrong"}` });
    line.textContent = `${r.correct ? "✓" : "✗"} ${q.prompt}` + (r.correct ? "" : `  → ${formatAnswer(q, r.correct_answer)}`);
    card.append(line);
  }
  const home = el("button", {}, "Til forsiden");
  home.onclick = renderHome;
  card.append(home);
  app.append(card);
}

function formatAnswer(q, a) {
  if (q.type === "multiple_choice") return q.choices[a];
  if (Array.isArray(a)) return a.join(" / ");
  if (a === true) return "Sant";
  if (a === false) return "Usant";
  return String(a);
}

boot().catch((e) => {
  if (e.message !== "login_required") {
    app.replaceChildren(el("div", { className: "card" }, el("p", { className: "muted" }, "Noe gikk galt. Last siden på nytt.")));
  }
});
