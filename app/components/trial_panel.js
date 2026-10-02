// 問題画面・確信度の画面の部品（docs/plans/phase3.md）。
//
// data.format: "choice"（選択式）/ "numeric"（数値入力式）/ "scale"（確信度の段階。横に並べる）
// 問題文・選択肢・数値入力欄・回答ボタン・残り時間を描画し、操作イベントをブラウザ内に蓄積して
// 回答確定（submit）または時間切れ（timeout）のときにまとめて送る。
// - 文字列はすべて textContent で表示する（HTML として解釈しない）
// - 座標は問題領域（.cx-root）を基準に正規化する（領域外は 0 未満・1 超）
// - 再描画で関数が再度呼ばれても状態が失われないよう、試行ごとの状態を window 上に保持する
// - イベント種別は src/cogexp/domain/client_log.py の許可リストと一致させること

const STORE = (window.__cogexpTrials = window.__cogexpTrials || {});
const NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

// サーバー側 cogexp.domain.scoring.parse_numeric と同じ規則（tests/harness/test_trial_panel_js.py で一致を検査）
export function parseNumeric(text) {
  const s = text.normalize("NFKC").trim().replace(/[,円\s]/g, "").replace(/−/g, "-");
  if (!NUMBER.test(s)) return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
}

function browserFamily() {
  const ua = navigator.userAgent;
  if (/Edg\//.test(ua)) return "edge";
  if (/Firefox\//.test(ua)) return "firefox";
  if (/Chrome\//.test(ua)) return "chrome";
  if (/Safari\//.test(ua)) return "safari";
  return "other";
}

function osFamily() {
  const ua = navigator.userAgent;
  if (/Windows/.test(ua)) return "windows";
  if (/iPhone|iPad|iPod/.test(ua)) return "ios";
  if (/Android/.test(ua)) return "android";
  if (/Mac OS X/.test(ua)) return "macos";
  if (/Linux/.test(ua)) return "linux";
  return "other";
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

const round4 = (v) => Math.round(v * 10000) / 10000;

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  if (!data || !data.trial_id) return;

  // 送信済みの古い試行の状態は捨てる
  for (const id of Object.keys(STORE)) {
    if (id !== data.trial_id && STORE[id].sent) delete STORE[id];
  }
  const st = (STORE[data.trial_id] = STORE[data.trial_id] || {
    shownMs: performance.now(),
    deadlineMs: data.remaining_ms == null ? null : performance.now() + data.remaining_ms,
    events: [],
    selected: data.initial_choice ?? null,
    prefilled: data.initial_choice != null,
    text: data.initial_text ?? "",
    changes: 0,
    deletions: 0,
    pointerTypes: [],
    sent: false,
    errorSeq: 0,
    layoutLogged: false,
  });
  // サーバーが送信を受け付けなかった場合（入力の再確認など）は再送できるようにする
  if (data.error && data.error_seq !== st.errorSeq) {
    st.errorSeq = data.error_seq;
    st.sent = false;
  }

  const old = parentElement.querySelector(".cx-root");
  if (old) old.remove();
  const root = el("div", "cx-root");
  // 確信度の段階（scale）は選択式と同じ操作・記録で、並べ方だけが横になる
  const isChoice = data.format === "choice" || data.format === "scale";

  // --- 描画 -----------------------------------------------------------------
  if (data.caption) root.appendChild(el("div", "cx-caption", data.caption));
  let countdownText = null;
  let countdownBar = null;
  if (st.deadlineMs != null && data.show_countdown) {
    const box = el("div", "cx-countdown");
    countdownBar = el("div", "cx-countdown-bar");
    const track = el("div", "cx-countdown-track");
    track.appendChild(countdownBar);
    countdownText = el("div", "cx-countdown-text");
    box.append(countdownText, track);
    root.appendChild(box);
  }
  const prompt = el("div", "cx-prompt", data.prompt);
  prompt.dataset.region = "prompt";
  root.appendChild(prompt);
  if (data.initial_note) root.appendChild(el("div", "cx-note", data.initial_note));

  const controls = [];
  const choiceLabels = [];
  let input = null;
  if (isChoice) {
    const group = el("fieldset", data.format === "scale" ? "cx-choices cx-scale" : "cx-choices");
    group.appendChild(el("legend", "cx-sr-only", "回答"));
    for (const c of data.choices) {
      const label = el("label", "cx-choice");
      label.dataset.choiceId = c.id;
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `cx-${data.trial_id}`;
      radio.value = c.id;
      radio.checked = st.selected === c.id;
      label.append(radio, el("span", "cx-choice-text", c.text));
      group.appendChild(label);
      choiceLabels.push(label);
      controls.push(radio);
    }
    root.appendChild(group);
  } else {
    const label = el("label", "cx-input-label", data.input_label);
    input = document.createElement("input");
    input.type = "text";
    input.inputMode = "decimal";
    input.autocomplete = "off";
    input.className = "cx-input";
    input.value = st.text;
    input.dataset.region = "input";
    label.appendChild(input);
    root.appendChild(label);
    controls.push(input);
  }
  const error = el("div", "cx-error");
  error.setAttribute("role", "alert");
  if (data.error) error.textContent = data.error;
  root.appendChild(error);
  const button = el("button", "cx-submit", data.submit_label || "回答する");
  button.type = "button";
  button.dataset.region = "submit";
  root.appendChild(button);
  parentElement.appendChild(root);

  // --- 記録 -----------------------------------------------------------------
  const listeners = [];
  const on = (target, type, fn, opts) => {
    target.addEventListener(type, fn, opts);
    listeners.push(() => target.removeEventListener(type, fn, opts));
  };
  const push = (type, extra) => {
    if (!st.sent) st.events.push({ t: performance.now(), type, ...(extra || {}) });
  };
  const norm = (clientX, clientY) => {
    const r = root.getBoundingClientRect();
    if (!r.width || !r.height) return { x: null, y: null };
    return { x: round4((clientX - r.left) / r.width), y: round4((clientY - r.top) / r.height) };
  };
  const notePointer = (type) => {
    if (type && ["mouse", "touch", "pen"].includes(type) && !st.pointerTypes.includes(type)) {
      st.pointerTypes.push(type);
    }
  };
  const regionOf = (event) => {
    for (const node of event.composedPath()) {
      if (!(node instanceof HTMLElement)) continue;
      if (node.dataset.choiceId) return node.dataset.choiceId;
      if (node.dataset.region === "input" || node.dataset.region === "submit") {
        return node.dataset.region;
      }
      if (node === root) return null;
    }
    return null;
  };

  const updateButton = () => {
    const ready = isChoice ? st.selected != null : st.text.trim() !== "";
    button.disabled = st.sent || !ready;
    for (const c of controls) c.disabled = st.sent;
  };

  // 移動は画面更新ごとに最新の位置だけを記録する（動いていない間は記録しない）
  let lastMove = null;
  let lastPushed = null;
  let raf = 0;
  const frame = () => {
    if (lastMove && lastMove !== lastPushed) {
      push("move", norm(lastMove.x, lastMove.y));
      lastPushed = lastMove;
    }
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  on(document, "pointermove", (e) => {
    notePointer(e.pointerType);
    lastMove = { x: e.clientX, y: e.clientY };
  }, { passive: true });
  on(document, "pointerdown", (e) => {
    notePointer(e.pointerType);
    push("pointerdown", {
      ...norm(e.clientX, e.clientY),
      target: regionOf(e),
      payload: { pointer: e.pointerType || "unknown", button: e.button },
    });
  }, { passive: true });
  on(document, "visibilitychange", () => {
    push("visibility", { payload: { state: document.visibilityState } });
  });
  on(window, "blur", () => push("window_blur"));
  on(window, "focus", () => push("window_focus"));
  on(root, "keydown", (e) => {
    const k = e.key;
    const cls = k === "Enter" ? "enter" : k === "Tab" ? "tab" : k.startsWith("Arrow") ? "arrow"
      : k === "Backspace" || k === "Delete" ? "delete" : "other";
    push("key", { payload: { class: cls } });
    if (k === "Enter" && !isChoice) {
      e.preventDefault();
      submit();
    }
  });

  for (const label of choiceLabels) {
    const id = label.dataset.choiceId;
    on(label, "pointerenter", () => push("choice_enter", { target: id }));
    on(label, "pointerleave", () => push("choice_leave", { target: id }));
  }
  for (const c of controls) {
    if (isChoice) {
      on(c, "change", () => {
        if (!c.checked) return;
        st.selected = c.value;
        st.changes += 1;
        push("choice_change", { target: c.value });
        updateButton();
      });
    } else {
      on(c, "input", (e) => {
        const t = e.inputType || "";
        const op = t.startsWith("delete") ? "delete" : t.startsWith("insert") ? "insert" : "other";
        if (op === "delete") st.deletions += 1;
        st.text = c.value;
        error.textContent = "";
        push("input_edit", { payload: { op } });
        updateButton();
      });
    }
  }

  // 表示直後の各要素の位置（軌跡の図で選択肢の位置を示すため）
  if (!st.layoutLogged) {
    requestAnimationFrame(() => {
      const r = root.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const rect = (node) => {
        const b = node.getBoundingClientRect();
        return [
          round4((b.left - r.left) / r.width), round4((b.top - r.top) / r.height),
          round4((b.right - r.left) / r.width), round4((b.bottom - r.top) / r.height),
        ];
      };
      const rects = { prompt: rect(prompt), submit: rect(button) };
      for (const label of choiceLabels) rects[`choice:${label.dataset.choiceId}`] = rect(label);
      if (input) rects.input = rect(input);
      push("layout", { payload: { rects } });
      st.layoutLogged = true;
    });
  }

  // --- 送信 -----------------------------------------------------------------
  const send = (kind) => {
    const r = root.getBoundingClientRect();
    push(kind);
    const revision = isChoice
      ? (st.prefilled ? st.changes : Math.max(0, st.changes - 1))
      : st.deletions;
    const payload = {
      kind,
      trial_id: data.trial_id,
      choice_id: kind === "submit" && isChoice ? st.selected : null,
      raw_value: kind === "submit" && !isChoice ? st.text.slice(0, 64) : null,
      shown_ms: st.shownMs,
      sent_ms: performance.now(),
      revision_count: revision,
      client: {
        browser: browserFamily(),
        os: osFamily(),
        pointer_types: st.pointerTypes,
        viewport_w: Math.round(window.innerWidth),
        viewport_h: Math.round(window.innerHeight),
        panel_w: Math.round(r.width),
        panel_h: Math.round(r.height),
        dpr: window.devicePixelRatio || 1,
      },
      events: st.events.splice(0),
    };
    st.sent = true;
    updateButton();
    setTriggerValue(kind, payload);
  };

  function submit() {
    if (st.sent) return;
    if (!isChoice && parseNumeric(st.text) === null) {
      push("invalid_submit");
      error.textContent = "数字で入力してください。";
      return;
    }
    if (isChoice && st.selected == null) return;
    send("submit");
  }
  on(button, "click", submit);

  // --- 残り時間（表示と、ブラウザ側での時間切れ通知。判定はサーバーが行う） ------------
  let timer = 0;
  if (st.deadlineMs != null) {
    const tick = () => {
      const remaining = Math.max(0, st.deadlineMs - performance.now());
      if (countdownText) {
        countdownText.textContent = `残り ${Math.ceil(remaining / 1000)} 秒`;
        countdownBar.style.width = `${(100 * remaining) / data.time_limit_ms}%`;
      }
      if (remaining <= 0 && !st.sent) send("timeout");
    };
    tick();
    timer = setInterval(tick, 100);
  }

  updateButton();
  if (input && !st.sent) input.focus();

  return () => {
    cancelAnimationFrame(raf);
    clearInterval(timer);
    for (const off of listeners) off();
  };
}
