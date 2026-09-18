import { planOffline, planWithLLM, validate, estimateSize } from "./planner.js";

const REPO = "puzzleboxsoftworks/ai-os-builder";
const EXAMPLES = [
  "a headless rescue and networking toolkit with ssh",
  "an xfce python data-science workstation",
  "a minimal kiosk that boots straight into a browser",
  "an i3 rust development box on ubuntu",
  "a firewall and router appliance",
];

const $ = (id) => document.getElementById(id);
const els = {
  prompt: $("prompt"), spec: $("spec"), plan: $("plan"), note: $("planner-note"),
  validation: $("validation"), estimate: $("estimate"), cli: $("cli-command"),
  apiKey: $("api-key"), baseUrl: $("base-url"), model: $("model"),
};

for (const [key, el] of [["aios_key", els.apiKey], ["aios_base", els.baseUrl], ["aios_model", els.model]]) {
  const saved = localStorage.getItem(key);
  if (saved) el.value = saved;
  el.addEventListener("change", () => localStorage.setItem(key, el.value));
}

$("examples").append(...EXAMPLES.map((text) => {
  const chip = document.createElement("button");
  chip.className = "chip";
  chip.textContent = text;
  chip.addEventListener("click", () => { els.prompt.value = text; generate(); });
  return chip;
}));

$("dispatch-link").href = `https://github.com/${REPO}/actions/workflows/build-iso.yml`;

function currentSpec() {
  try {
    return JSON.parse(els.spec.value);
  } catch (error) {
    return null;
  }
}

function refresh() {
  const spec = currentSpec();
  if (!spec) {
    els.validation.textContent = "spec is not valid JSON";
    els.validation.className = "validation bad";
    return;
  }
  const errors = validate(spec);
  els.validation.textContent = errors.length ? errors.join("\n") : "spec is valid";
  els.validation.className = "validation " + (errors.length ? "bad" : "good");
  els.estimate.textContent = `≈ ${estimateSize(spec)} MiB ISO`;
  document.documentElement.style.setProperty("--accent", spec.accent_color || "#4c7fff");
  els.cli.textContent = [
    "git clone https://github.com/" + REPO + " && cd ai-os-builder",
    "pip install -e .",
    `aios build spec.json -o ${spec.slug || "out"}.iso`,
    `aios run ${spec.slug || "out"}.iso`,
  ].join("\n");
}

function showSpec(spec) {
  els.spec.value = JSON.stringify(spec, null, 2);
  refresh();
}

async function generate() {
  const prompt = els.prompt.value.trim();
  if (!prompt) { els.prompt.focus(); return; }
  const apiKey = els.apiKey.value.trim();
  els.plan.disabled = true;
  try {
    if (apiKey) {
      els.note.textContent = `asking ${els.model.value}…`;
      try {
        showSpec(await planWithLLM(prompt, { apiKey, baseUrl: els.baseUrl.value, model: els.model.value }));
        els.note.textContent = `planned by ${els.model.value}`;
        return;
      } catch (error) {
        els.note.textContent = `LLM failed (${error.message.slice(0, 80)}) — used the offline planner`;
        showSpec(planOffline(prompt));
        return;
      }
    }
    showSpec(planOffline(prompt));
    els.note.textContent = "offline keyword planner — add a key below for an LLM";
  } finally {
    els.plan.disabled = false;
  }
}

async function copy(text, button) {
  await navigator.clipboard.writeText(text);
  const original = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = original; }, 1200);
}

els.plan.addEventListener("click", generate);
els.spec.addEventListener("input", refresh);
els.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) generate();
});
$("copy-spec").addEventListener("click", (event) => copy(els.spec.value, event.target));
$("copy-cli").addEventListener("click", (event) => copy(els.cli.textContent, event.target));
$("download").addEventListener("click", () => {
  const spec = currentSpec();
  const blob = new Blob([els.spec.value], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${spec?.slug || "spec"}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

els.prompt.value = EXAMPLES[0];
generate();
