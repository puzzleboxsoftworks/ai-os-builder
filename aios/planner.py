"""Turn a natural-language prompt into an :class:`OSSpec`.

Uses an OpenAI-compatible chat completions endpoint when an API key is
available, and falls back to a deterministic keyword planner otherwise so the
builder works fully offline.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .spec import SCHEMA_HINT, OSSpec, SpecError

SYSTEM_PROMPT = f"""You design bootable Linux live systems.
Given a user's description, reply with ONLY a JSON object matching this shape:

{SCHEMA_HINT}

Rules:
- Every package must exist in the chosen Debian/Ubuntu suite.
- Never include a kernel, live-boot, systemd-sysv or sudo; the builder adds them.
- Keep the image lean: only packages the description actually implies.
- post_install commands run as root inside the chroot, one line each, no network.
"""

KEYWORD_PACKAGES: list[tuple[str, list[str]]] = [
    (r"\bpython\b|\bml\b|data science|machine learning", ["python3", "python3-pip", "python3-venv"]),
    (r"\bnode|javascript|typescript|npm\b", ["nodejs", "npm"]),
    (r"\brust\b|cargo", ["rustc", "cargo"]),
    (r"\bgo(lang)?\b", ["golang"]),
    (r"\bc\+\+|gcc|compiler|build|kernel dev", ["build-essential", "gdb"]),
    (r"\bdocker|container", ["docker.io"]),
    (r"\bgit\b|version control|dev(eloper)?\b|coding|programming", ["git", "vim", "tmux", "curl", "less"]),
    (r"\bssh|server|headless|remote", ["openssh-server"]),
    (r"\bnetwork|pentest|security|nmap|sniff", ["nmap", "tcpdump", "netcat-openbsd", "iproute2"]),
    (r"\brescue|recovery|repair|forensic|disk", ["gdisk", "parted", "testdisk", "smartmontools", "rsync"]),
    (r"\bfirewall|router|gateway", ["nftables", "iproute2", "dnsmasq"]),
    (r"\bmedia|music|audio|video|player", ["mpv", "alsa-utils"]),
    (r"\bbrowser|web|kiosk|internet", ["firefox-esr"]),
    (r"\bretro|game|gaming|fun", ["bsdgames", "cmatrix"]),
    (r"\bmonitor|observability|metrics|htop|ops|sre", ["htop", "iotop", "sysstat"]),
    (r"\bwrit(ing|er)|office|document", ["vim", "pandoc"]),
]

DESKTOP_KEYWORDS: list[tuple[str, str]] = [
    (r"\bi3|tiling|window manager\b", "i3"),
    (r"\bgnome\b", "gnome"),
    (r"\blxqt|lightweight desktop|low.?resource desktop", "lxqt"),
    (r"\bxfce|desktop|gui|graphical|kiosk|browser", "xfce"),
]

SUITE_KEYWORDS: list[tuple[str, str]] = [
    (r"\bubuntu 24|noble\b", "noble"),
    (r"\bubuntu\b|jammy", "jammy"),
    (r"\btrixie|debian 13\b", "trixie"),
    (r"\bsid|unstable\b", "sid"),
]

STOPWORDS = {
    "a", "an", "the", "os", "linux", "distro", "distribution", "system", "with",
    "and", "for", "that", "this", "build", "make", "create", "me", "my", "of",
    "to", "in", "on", "is", "it", "small", "tiny", "lightweight", "minimal",
}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32].strip("-")
    return slug or "ai-os"


def _name_from_prompt(prompt: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", prompt) if w.lower() not in STOPWORDS]
    picked = [w[:16].capitalize() for w in words[:2]] or ["Ai"]
    return " ".join(picked)[:44] + " OS"


def plan_offline(prompt: str) -> OSSpec:
    """Deterministic, network-free planner used as the fallback."""
    text = prompt.lower()
    packages: list[str] = []
    for pattern, pkgs in KEYWORD_PACKAGES:
        if re.search(pattern, text):
            packages.extend(pkgs)

    desktop = "none"
    for pattern, name in DESKTOP_KEYWORDS:
        if re.search(pattern, text):
            desktop = name
            break

    suite = "bookworm"
    for pattern, name in SUITE_KEYWORDS:
        if re.search(pattern, text):
            suite = name
            break

    if not packages:
        packages = ["vim", "curl", "htop"]

    name = _name_from_prompt(prompt)
    deduped = list(dict.fromkeys(packages))
    spec = OSSpec(
        name=name,
        slug=_slugify(name),
        description=prompt.strip()[:160] or "An AI-generated Linux live system.",
        suite=suite,
        desktop=desktop,
        packages=deduped,
        enable_services=["ssh"] if "openssh-server" in deduped else [],
    )
    spec.validate()
    return spec


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise SpecError("model response contained no JSON object")
    return json.loads(text[start : end + 1])


def plan_with_llm(prompt: str, *, api_key: str, base_url: str, model: str, timeout: int = 120) -> OSSpec:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read())
    content = body["choices"][0]["message"]["content"]
    return OSSpec.from_dict(_extract_json(content))


def plan(prompt: str, *, offline: bool = False) -> tuple[OSSpec, str]:
    """Return ``(spec, planner_name)`` for a prompt."""
    api_key = os.environ.get("AIOS_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if offline or not api_key:
        return plan_offline(prompt), "offline"
    base_url = os.environ.get("AIOS_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("AIOS_MODEL", "gpt-4o-mini")
    try:
        return plan_with_llm(prompt, api_key=api_key, base_url=base_url, model=model), f"llm:{model}"
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, SpecError) as exc:
        print(f"[aios] LLM planning failed ({exc}); falling back to the offline planner")
        return plan_offline(prompt), "offline"
