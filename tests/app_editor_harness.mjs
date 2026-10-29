/** In-memory models mirroring static/app.js editor + compose behavior. */
const posts = [];
let loaded = false;
let current = "readme.md";
const ta = { value: "", disabled: true };
let original = "";
let workOn = true;
const ss = {};
const ssSet = (k, v) => { if (v) ss[k] = v; else delete ss[k]; };
const workKey = "aesop.work.c1";
const draftKey = "aesop.draft.c1";

async function api(method, path, body) {
  posts.push({ method, path, body });
  if (path.includes("/file") && method === "POST") {
    await new Promise((r) => setTimeout(r, 5));
    return { path: body.path, content: body.content, chars: body.content.length };
  }
  return { path: current, content: "hello\n", chars: 6 };
}

async function save() {
  if (!current || !loaded || ta.disabled) return;
  const path = current, sent = ta.value;
  await api("POST", "/api/projects/p/file", { path, content: sent });
  if (current === path) original = sent;
}

function applyPendingCompose(pending, taVal, confirmFn) {
  let workOnLocal = workOn;
  const cur = taVal;
  const replace = cur.trim() && cur !== (pending.text || "");
  if (replace && !confirmFn("Replace your unsent chat draft with text from the editor?")) {
    return { applied: false, workOn: workOnLocal, text: cur };
  }
  if (pending.work) { workOnLocal = true; ssSet(workKey, "1"); }
  else { workOnLocal = false; ssSet(workKey, ""); }
  return { applied: true, workOn: workOnLocal, text: pending.text || "" };
}

function editorDirty(state) {
  return state.loaded && state.path && state.value !== state.original;
}

async function testSaveBeforeLoad() {
  const postsSave = () => posts.filter((p) => p.method === "POST");
  await save();
  if (postsSave().length !== 0) throw new Error("expected no save before load");
  const pending = (async () => {
    loaded = false;
    const f = await api("GET", "/api/projects/p/file?path=readme.md");
    ta.disabled = false;
    ta.value = f.content;
    original = f.content;
    loaded = true;
  })();
  await save();
  if (postsSave().length !== 0) throw new Error("expected no save while load pending");
  await pending;
  await save();
  if (postsSave().length !== 1) throw new Error("expected one POST after load");
}

async function testA3SaveBaselineUsesSentContent() {
  loaded = true;
  current = "a.txt";
  original = "old";
  ta.value = "sent-body";
  const path = current, sent = ta.value;
  ta.value = "mutated-during-await";
  if (current === path) original = sent;
  if (original !== "sent-body") throw new Error(`expected sent baseline, got ${original}`);
}

function testA2AskTurnsWorkOff() {
  workOn = true;
  ssSet(workKey, "1");
  const pending = { text: "ask prompt", work: false };
  const out = applyPendingCompose(pending, "", () => true);
  if (out.workOn !== false) throw new Error("ask should turn work off");
  if (ss[workKey]) throw new Error("work key should be cleared");
  const workPending = { text: "work prompt", work: true };
  const out2 = applyPendingCompose(workPending, "", () => true);
  if (out2.workOn !== true) throw new Error("work should turn work on");
}

function testA4EditorDirty() {
  const st = { loaded: true, path: "f.txt", original: "a", value: "b" };
  if (!editorDirty(st)) throw new Error("expected dirty");
  st.value = "a";
  if (editorDirty(st)) throw new Error("expected clean");
}

function testA5DraftReplaceCancel() {
  workOn = true;
  ssSet(workKey, "1");
  const pending = { text: "from editor", work: true };
  const out = applyPendingCompose(pending, "existing draft", () => false);
  if (out.applied) throw new Error("cancel should not apply");
  if (out.text !== "existing draft") throw new Error("draft should remain");
  if (out.workOn !== true) throw new Error("work state should remain");
}

async function run() {
  posts.length = 0;
  await testSaveBeforeLoad();
  posts.length = 0;
  loaded = false;
  ta.value = "";
  ta.disabled = true;
  original = "";
  await testA3SaveBaselineUsesSentContent();
  testA2AskTurnsWorkOff();
  testA4EditorDirty();
  testA5DraftReplaceCancel();
  console.log("ok");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
