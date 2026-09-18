"""OS specification: the contract between the AI planner and the ISO builder."""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUITES = {
    "bookworm": "https://deb.debian.org/debian",
    "trixie": "https://deb.debian.org/debian",
    "sid": "https://deb.debian.org/debian",
    "jammy": "http://archive.ubuntu.com/ubuntu",
    "noble": "http://archive.ubuntu.com/ubuntu",
}

DESKTOPS = {
    "none": [],
    "xfce": ["xorg", "xfce4", "xfce4-terminal", "lightdm", "dbus-x11"],
    "lxqt": ["xorg", "lxqt-core", "qterminal", "sddm", "dbus-x11"],
    "gnome": ["xorg", "gnome-core", "gdm3", "dbus-x11"],
    "i3": ["xorg", "i3", "xterm", "dmenu", "lightdm", "dbus-x11"],
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}$")
PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.:-]{0,63}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


class SpecError(ValueError):
    """Raised when a spec is structurally invalid or unsafe to build."""


@dataclass
class OSSpec:
    """A buildable description of a bootable Linux live system."""

    name: str = "AI OS"
    slug: str = "ai-os"
    version: str = "1.0"
    description: str = "An AI-generated Linux live system."
    suite: str = "bookworm"
    arch: str = "amd64"
    mirror: str = ""
    desktop: str = "none"
    packages: list[str] = field(default_factory=list)
    hostname: str = ""
    username: str = "user"
    password: str = "live"
    autologin: bool = True
    root_password: str = "root"
    locale: str = "en_US.UTF-8"
    timezone: str = "UTC"
    keyboard: str = "us"
    motd: str = ""
    accent_color: str = "#4c7fff"
    enable_services: list[str] = field(default_factory=list)
    disable_services: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    post_install: list[str] = field(default_factory=list)
    kernel_cmdline: str = "quiet"

    def __post_init__(self) -> None:
        self.slug = self.slug.strip().lower()
        self.hostname = (self.hostname or self.slug).strip().lower()
        self.mirror = self.mirror or SUITES.get(self.suite, "")
        if not self.motd:
            self.motd = f"{self.name} {self.version} — {self.description}"

    @property
    def all_packages(self) -> list[str]:
        base = [
            "linux-image-" + ("amd64" if self.suite in ("bookworm", "trixie", "sid") else "generic"),
            "live-boot",
            "systemd-sysv",
            "sudo",
            "locales",
            "ca-certificates",
            "dbus",
            "iproute2",
        ]
        if self.suite != "jammy":
            # split out of the systemd package in Debian 12+ / Ubuntu 24.04+
            base.append("systemd-resolved")
        merged = base + DESKTOPS[self.desktop] + list(self.packages)
        seen: dict[str, None] = {}
        for pkg in merged:
            seen.setdefault(pkg, None)
        return list(seen)

    def validate(self) -> None:
        if not NAME_RE.match(self.name):
            raise SpecError(f"invalid name: {self.name!r}")
        if not SLUG_RE.match(self.slug):
            raise SpecError(f"invalid slug: {self.slug!r}")
        if self.suite not in SUITES:
            raise SpecError(f"unknown suite {self.suite!r}; pick one of {sorted(SUITES)}")
        if self.arch not in ("amd64", "arm64"):
            raise SpecError(f"unsupported arch: {self.arch!r}")
        if self.desktop not in DESKTOPS:
            raise SpecError(f"unknown desktop {self.desktop!r}; pick one of {sorted(DESKTOPS)}")
        if not USER_RE.match(self.username):
            raise SpecError(f"invalid username: {self.username!r}")
        if not SLUG_RE.match(self.hostname):
            raise SpecError(f"invalid hostname: {self.hostname!r}")
        if not self.mirror.startswith(("http://", "https://")):
            raise SpecError(f"invalid mirror: {self.mirror!r}")
        for pkg in self.packages:
            if not PKG_RE.match(pkg):
                raise SpecError(f"invalid package name: {pkg!r}")
        for svc in [*self.enable_services, *self.disable_services]:
            if not PKG_RE.match(svc):
                raise SpecError(f"invalid service name: {svc!r}")
        for path in self.files:
            if not path.startswith("/") or ".." in path:
                raise SpecError(f"file paths must be absolute and free of '..': {path!r}")
        for cmd in self.post_install:
            if "\n" in cmd:
                raise SpecError("post_install commands must be single lines")
        if "\n" in self.kernel_cmdline:
            raise SpecError("kernel_cmdline must be a single line")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OSSpec":
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise SpecError(f"unknown spec fields: {sorted(unknown)}")
        spec = cls(**data)
        spec.validate()
        return spec

    @classmethod
    def load(cls, path: str | Path) -> "OSSpec":
        return cls.from_dict(json.loads(Path(path).read_text()))


SCHEMA_HINT = """{
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
}"""
