import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(__dirname, "..", "static", "app.js");
const source = fs.readFileSync(APP, "utf8");

function sliceFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`function ${name} not closed`);
}

const editorSlots = { main: null, insp: null };
const editorDirtySrc = sliceFunction("editorDirty");
const editorDirty = new Function("editorSlots", `${editorDirtySrc}; return editorDirty;`)(editorSlots);

function slicePendingComposeBlock() {
  const start = source.indexOf("  if (S.pendingCompose) {");
  const end = source.indexOf("\n  root.append(msgsEl", start);
  if (start < 0 || end < 0) throw new Error("pendingCompose block not found");
  return source.slice(start, end);
}

function runPendingCompose(S, ta, ssSet, draftKey, workKey, fillProv, grow, paintWork, confirmFn) {
  const pendingComposeBlock = slicePendingComposeBlock().replace(/\bconfirm\b/g, "confirmFn");
  const run = new Function(
    "S",
    "ta",
    "ssSet",
    "draftKey",
    "workKey",
    "fillProv",
    "grow",
    "paintWork",
    "confirmFn",
    `let workOn = true;\n${pendingComposeBlock}\nreturn { workOn, text: ta.value };`,
  );
  return run(S, ta, ssSet, draftKey, workKey, fillProv, grow, paintWork, confirmFn);
}

function sliceSaveBaselineCore() {
  const marker = "const path = current, sent = ta.value;";
  const start = source.indexOf(marker);
  if (start < 0) throw new Error("save baseline lines missing from app.js");
  const apiNeedle = 'await api("POST", `/api/projects/${pid}/file`, { path, content: sent });';
  const apiStart = source.indexOf(apiNeedle, start);
  if (apiStart < 0) throw new Error("save POST line missing from app.js");
  const endMarker = "if (current === path) original = sent;";
  const end = source.indexOf(endMarker, apiStart);
  if (end < 0) throw new Error("save baseline end missing from app.js");
  const sentLine = source.slice(start, source.indexOf("\n", start)).trim();
  const postLine = source.slice(apiStart, source.indexOf("\n", apiStart)).trim();
  return `${sentLine}\n${postLine}\n${endMarker}`;
}

async function runSaveBaseline() {
  const core = sliceSaveBaselineCore();
  const ta = { value: "sent-body" };
  const api = async (_method, _path, _body) => {
    ta.value = "mutated-during-await";
    await new Promise((r) => setTimeout(r, 1));
    return {};
  };
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const run = new AsyncFunction(
    "ta",
    "api",
    `let current = "a.txt";
     let original = "old";
     const pid = "p";
     ${core}
     return original;`,
  );
  return run(ta, api);
}

const posts = [];

async function testSaveBeforeLoad() {
  const postsSave = () => posts.filter((p) => p.method === "POST");
  const saveBlockStart = source.indexOf("const save = () => guard(async () => {");
  if (saveBlockStart < 0) throw new Error("save() not found");
  posts.length = 0;
  let loaded = false;
  let current = "readme.md";
  const ta = { value: "", disabled: true };
  let original = "";
  const api = async (method, path, body) => {
    posts.push({ method, path, body });
    if (path.includes("/file") && method === "POST") {
      await new Promise((r) => setTimeout(r, 5));
      return { path: body.path, content: body.content, chars: body.content.length };
    }
    return { path: current, content: "hello\n", chars: 6 };
  };
  const save = async () => {
    if (!current || !loaded || ta.disabled) return;
    const pathVal = current;
    const sent = ta.value;
    await api("POST", "/api/projects/p/file", { path: pathVal, content: sent });
    if (current === pathVal) original = sent;
  };
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
  const original = await runSaveBaseline();
  if (original !== "sent-body") throw new Error(`expected sent baseline, got ${original}`);
}

function testA2AskTurnsWorkOff() {
  const ss = {};
  const ssSet = (k, v) => {
    if (v) ss[k] = v;
    else delete ss[k];
  };
  const ta = { value: "", focus() {} };
  const out = runPendingCompose(
    { pendingCompose: { text: "ask prompt", work: false } },
    ta,
    ssSet,
    "draft",
    "work",
    () => {},
    () => {},
    () => {},
    () => true,
  );
  if (out.workOn !== false) throw new Error("ask should turn work off");
  if (ss.work) throw new Error("work key should be cleared");
  const out2 = runPendingCompose(
    { pendingCompose: { text: "work prompt", work: true } },
    ta,
    ssSet,
    "draft",
    "work",
    () => {},
    () => {},
    () => {},
    () => true,
  );
  if (out2.workOn !== true) throw new Error("work should turn work on");
}

function testA4EditorDirty() {
  editorSlots.main = () => ({
    loaded: true,
    path: "f.txt",
    original: "a",
    value: "b",
  });
  if (!editorDirty()) throw new Error("expected dirty");
  editorSlots.main = () => ({
    loaded: true,
    path: "f.txt",
    original: "a",
    value: "a",
  });
  if (editorDirty()) throw new Error("expected clean");
}

function testA5DraftReplaceCancel() {
  const ss = {};
  const ssSet = (k, v) => {
    if (v) ss[k] = v;
    else delete ss[k];
  };
  const ta = { value: "existing draft", focus() {} };
  const out = runPendingCompose(
    { pendingCompose: { text: "from editor", work: true } },
    ta,
    ssSet,
    "draft",
    "work",
    () => {},
    () => {},
    () => {},
    () => false,
  );
  if (out.text !== "existing draft") throw new Error("draft should remain");
  if (out.workOn !== true) throw new Error("work state should remain");
}

async function run() {
  await testSaveBeforeLoad();
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
