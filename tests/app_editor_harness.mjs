/** In-memory model of inspEditor save/load guards (mirrors static/app.js). */
const posts = [];
let loaded = false;
let current = "readme.md";
const ta = { value: "", disabled: true };

async function api(method, path, body) {
  posts.push({ method, path, body });
  return { path: current, content: "hello\n", chars: 6 };
}

async function save() {
  if (!current || !loaded || ta.disabled) return;
  await api("POST", "/api/projects/p/file", { path: current, content: ta.value });
}

async function openFile() {
  loaded = false;
  const f = await api("GET", `/api/projects/p/file?path=${encodeURIComponent(current)}`);
  ta.disabled = false;
  ta.value = f.content;
  loaded = true;
}

async function run() {
  const postsSave = () => posts.filter((p) => p.method === "POST");
  await save();
  if (postsSave().length !== 0) {
    console.error("expected no save before load, got", postsSave().length);
    process.exit(1);
  }
  const pending = openFile();
  await save();
  if (postsSave().length !== 0) {
    console.error("expected no save while load pending");
    process.exit(1);
  }
  await pending;
  await save();
  if (postsSave().length !== 1) {
    console.error("expected one POST after load", postsSave());
    process.exit(1);
  }
  console.log("ok");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
