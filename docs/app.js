import { planOffline, planWithLLM, validate, estimateSize } from "./planner.js";
import { dispatchBuild, watchRun, downloadArtifact } from "./dispatch.js";

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
  repo: $("repo"), token: $("token"), build: $("build"),
  buildStatus: $("build-status"), runLink: $("run-link"), artifacts: $("artifacts"),
};

for (const [key, el] of [
  ["aios_key", els.apiKey], ["aios_base", els.baseUrl], ["aios_model", els.model],
  ["aios_repo", els.repo], ["aios_token", els.token],
]) {
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

function buildStatus(text, kind = "") {
  els.buildStatus.textContent = text;
  els.buildStatus.className = "validation " + kind;
}

async function build() {
  const spec = currentSpec();
  if (!spec) return buildStatus("spec is not valid JSON", "bad");
  const errors = validate(spec);
  if (errors.length) return buildStatus("fix the spec first:\n" + errors.join("\n"), "bad");

  const repo = els.repo.value.trim();
  const token = els.token.value.trim();
  if (!token) { els.token.focus(); return buildStatus("a GitHub token is required", "bad"); }

  els.build.disabled = true;
  els.artifacts.replaceChildren();
  els.runLink.hidden = true;
  try {
    buildStatus("dispatching workflow…");
    const run = await dispatchBuild({ repo, token, spec: JSON.stringify(spec) });
    els.runLink.href = run.html_url;
    els.runLink.hidden = false;

    const started = Date.now();
    const { run: finished, artifacts } = await watchRun({
      repo, token, runId: run.id,
      onUpdate: (current) => buildStatus(
        `run #${current.run_number}: ${current.status}` +
        ` (${Math.round((Date.now() - started) / 1000)}s)`,
      ),
    });

    if (finished.conclusion !== "success") {
      return buildStatus(`build ${finished.conclusion} — see the run log`, "bad");
    }
    buildStatus("build succeeded", "good");
    for (const artifact of artifacts) {
      const button = document.createElement("button");
      button.textContent = `Download ${artifact.name} (${Math.round(artifact.size_in_bytes / 1048576)} MiB zip)`;
      button.addEventListener("click", async () => {
        button.disabled = true;
        const label = button.textContent;
        button.textContent = "Downloading…";
        try {
          const href = await downloadArtifact({ repo, token, artifactId: artifact.id });
          const link = document.createElement("a");
          link.href = href;
          link.download = `${artifact.name}.zip`;
          link.click();
          URL.revokeObjectURL(href);
        } catch (error) {
          buildStatus(`download failed: ${error.message}`, "bad");
        } finally {
          button.textContent = label;
          button.disabled = false;
        }
      });
      els.artifacts.append(button);
    }
  } catch (error) {
    buildStatus(error.message, "bad");
  } finally {
    els.build.disabled = false;
  }
}

els.build.addEventListener("click", build);

els.prompt.value = EXAMPLES[0];
generate();
