// Browser port of aios/planner.py + aios/spec.py defaults. Keep the two in sync.

export const SUITES = {
  bookworm: "https://deb.debian.org/debian",
  trixie: "https://deb.debian.org/debian",
  sid: "https://deb.debian.org/debian",
  jammy: "http://archive.ubuntu.com/ubuntu",
  noble: "http://archive.ubuntu.com/ubuntu",
};

export const DESKTOPS = ["none", "xfce", "lxqt", "gnome", "i3"];

const KEYWORD_PACKAGES = [
  [/\bpython\b|\bml\b|data science|machine learning/, ["python3", "python3-pip", "python3-venv"]],
  [/\bnode|javascript|typescript|npm\b/, ["nodejs", "npm"]],
  [/\brust\b|cargo/, ["rustc", "cargo"]],
  [/\bgo(lang)?\b/, ["golang"]],
  [/\bc\+\+|gcc|compiler|build|kernel dev/, ["build-essential", "gdb"]],
  [/\bdocker|container/, ["docker.io"]],
  [/\bgit\b|version control|dev(eloper)?\b|coding|programming/, ["git", "vim", "tmux", "curl", "less"]],
  [/\bssh|server|headless|remote/, ["openssh-server"]],
  [/\bnetwork|pentest|security|nmap|sniff/, ["nmap", "tcpdump", "netcat-openbsd", "iproute2"]],
  [/\brescue|recovery|repair|forensic|disk/, ["gdisk", "parted", "testdisk", "smartmontools", "rsync"]],
  [/\bfirewall|router|gateway/, ["nftables", "iproute2", "dnsmasq"]],
  [/\bmedia|music|audio|video|player/, ["mpv", "alsa-utils"]],
  [/\bbrowser|web|kiosk|internet/, ["firefox-esr"]],
  [/\bretro|game|gaming|fun/, ["bsdgames", "cmatrix"]],
  [/\bmonitor|observability|metrics|htop|ops|sre/, ["htop", "iotop", "sysstat"]],
  [/\bwrit(ing|er)|office|document/, ["vim", "pandoc"]],
];

const DESKTOP_KEYWORDS = [
  [/\bi3|tiling|window manager\b/, "i3"],
  [/\bgnome\b/, "gnome"],
  [/\blxqt|lightweight desktop|low.?resource desktop/, "lxqt"],
  [/\bxfce|desktop|gui|graphical|kiosk|browser/, "xfce"],
];

const SUITE_KEYWORDS = [
  [/\bubuntu 24|noble\b/, "noble"],
  [/\bubuntu\b|jammy/, "jammy"],
  [/\btrixie|debian 13\b/, "trixie"],
  [/\bsid|unstable\b/, "sid"],
];

const STOPWORDS = new Set(["a", "an", "the", "os", "linux", "distro", "distribution", "system",
  "with", "and", "for", "that", "this", "build", "make", "create", "me", "my", "of", "to", "in",
  "on", "is", "it", "small", "tiny", "lightweight", "minimal"]);

const slugify = (text) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32).replace(/-$/, "") || "ai-os";

function nameFromPrompt(prompt) {
  const words = (prompt.match(/[A-Za-z0-9]+/g) || []).filter((w) => !STOPWORDS.has(w.toLowerCase()));
  const picked = words.slice(0, 2).map((w) => w.slice(0, 16).charAt(0).toUpperCase() + w.slice(1, 16).toLowerCase());
  return ((picked.length ? picked.join(" ") : "Ai").slice(0, 44)) + " OS";
}

export function planOffline(prompt) {
  const text = prompt.toLowerCase();
  let packages = [];
  for (const [pattern, pkgs] of KEYWORD_PACKAGES) if (pattern.test(text)) packages.push(...pkgs);

  let desktop = "none";
  for (const [pattern, value] of DESKTOP_KEYWORDS) if (pattern.test(text)) { desktop = value; break; }

  let suite = "bookworm";
  for (const [pattern, value] of SUITE_KEYWORDS) if (pattern.test(text)) { suite = value; break; }

  if (!packages.length) packages = ["vim", "curl", "htop"];
  packages = [...new Set(packages)];

  const name = nameFromPrompt(prompt);
  const slug = slugify(name);
  return {
    name,
    slug,
    version: "1.0",
    description: prompt.trim().slice(0, 160) || "An AI-generated Linux live system.",
    suite,
    arch: "amd64",
    mirror: SUITES[suite],
    desktop,
    packages,
    hostname: slug,
    username: "user",
    password: "live",
    autologin: true,
    root_password: "root",
    locale: "en_US.UTF-8",
    timezone: "UTC",
    keyboard: "us",
    motd: "",
    accent_color: "#4c7fff",
    enable_services: packages.includes("openssh-server") ? ["ssh"] : [],
    disable_services: [],
    files: {},
    post_install: [],
    kernel_cmdline: "quiet",
  };
}

const SCHEMA_HINT = `{
  "name": "Display name, e.g. 'Forge Linux'",
  "slug": "lowercase-dashed-id",
  "version": "1.0",
  "description": "One sentence about the OS",
  "suite": "bookworm | trixie | jammy | noble",
  "arch": "amd64",
  "desktop": "none | xfce | lxqt | gnome | i3",
  "packages": ["extra", "apt", "packages"],
  "username": "user",
  "password": "live",
  "autologin": true,
  "locale": "en_US.UTF-8",
  "timezone": "UTC",
  "keyboard": "us",
  "motd": "Login banner text",
  "accent_color": "#rrggbb",
  "enable_services": ["ssh"],
  "disable_services": [],
  "files": {"/etc/example.conf": "file contents"},
  "post_install": ["single-line shell commands run inside the chroot"],
  "kernel_cmdline": "quiet"
}`;

const SYSTEM_PROMPT = `You design bootable Linux live systems.
Given a user's description, reply with ONLY a JSON object matching this shape:

${SCHEMA_HINT}

Rules:
- Every package must exist in the chosen Debian/Ubuntu suite.
- Never include a kernel, live-boot, systemd-sysv or sudo; the builder adds them.
- Keep the image lean: only packages the description actually implies.
- post_install commands run as root inside the chroot, one line each, no network.`;

export async function planWithLLM(prompt, { apiKey, baseUrl, model }) {
  const response = await fetch(baseUrl.replace(/\/$/, "") + "/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: prompt },
      ],
    }),
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const body = await response.json();
  const content = body.choices[0].message.content;
  const start = content.indexOf("{");
  const end = content.lastIndexOf("}");
  if (start === -1 || end === -1) throw new Error("model response contained no JSON object");
  const spec = JSON.parse(content.slice(start, end + 1));
  spec.mirror = spec.mirror || SUITES[spec.suite] || SUITES.bookworm;
  return spec;
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;
const PKG_RE = /^[a-z0-9][a-z0-9+.:-]{0,63}$/;
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}$/;
const USER_RE = /^[a-z_][a-z0-9_-]{0,31}$/;

/** Mirrors OSSpec.validate so the site rejects a spec before it reaches CI. */
export function validate(spec) {
  const errors = [];
  if (!NAME_RE.test(spec.name || "")) errors.push(`invalid name: ${JSON.stringify(spec.name)}`);
  if (!SLUG_RE.test(spec.slug || "")) errors.push(`invalid slug: ${JSON.stringify(spec.slug)}`);
  if (!(spec.suite in SUITES)) errors.push(`unknown suite: ${JSON.stringify(spec.suite)}`);
  if (!DESKTOPS.includes(spec.desktop)) errors.push(`unknown desktop: ${JSON.stringify(spec.desktop)}`);
  if (!USER_RE.test(spec.username || "")) errors.push(`invalid username: ${JSON.stringify(spec.username)}`);
  if (spec.hostname && !SLUG_RE.test(spec.hostname)) errors.push(`invalid hostname: ${JSON.stringify(spec.hostname)}`);
  for (const pkg of spec.packages || []) if (!PKG_RE.test(pkg)) errors.push(`invalid package: ${JSON.stringify(pkg)}`);
  for (const svc of [...(spec.enable_services || []), ...(spec.disable_services || [])]) {
    if (!PKG_RE.test(svc)) errors.push(`invalid service: ${JSON.stringify(svc)}`);
  }
  for (const path of Object.keys(spec.files || {})) {
    if (!path.startsWith("/") || path.includes("..")) errors.push(`invalid file path: ${JSON.stringify(path)}`);
  }
  for (const cmd of spec.post_install || []) {
    if (cmd.includes("\n")) errors.push("post_install commands must be single lines");
  }
  return errors;
}

/** Rough ISO size estimate in MiB, anchored on a measured 223 MiB headless Debian build. */
export function estimateSize(spec) {
  const desktopCost = { none: 0, i3: 260, lxqt: 420, xfce: 520, gnome: 1400 }[spec.desktop] ?? 0;
  return Math.round(215 + desktopCost + (spec.packages || []).length * 6);
}
