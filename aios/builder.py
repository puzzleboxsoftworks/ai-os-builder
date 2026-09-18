"""Build a bootable hybrid (BIOS + UEFI) live ISO from an :class:`OSSpec`."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .spec import OSSpec

UBUNTU_SUITES = {"jammy", "noble"}
REQUIRED_TOOLS = ["debootstrap", "mksquashfs", "xorriso", "grub-mkrescue"]


class BuildError(RuntimeError):
    pass


def _log(message: str) -> None:
    print(f"[aios] {message}", flush=True)


def _run(cmd: list[str], **kwargs) -> None:
    _log("$ " + " ".join(shlex.quote(part) for part in cmd))
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise BuildError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def _sudo(cmd: list[str], **kwargs) -> None:
    _run(["sudo"] + cmd, **kwargs)


def check_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def _write_root_file(path: Path, content: str, mode: str = "0644") -> None:
    subprocess.run(["sudo", "install", "-D", "-m", mode, "/dev/stdin", str(path)],
                   input=content.encode(), check=True)


def _apt_sources(spec: OSSpec) -> str:
    if spec.suite in UBUNTU_SUITES:
        comps = "main universe multiverse restricted"
        return (
            f"deb {spec.mirror} {spec.suite} {comps}\n"
            f"deb {spec.mirror} {spec.suite}-updates {comps}\n"
        )
    return (
        f"deb {spec.mirror} {spec.suite} main contrib non-free non-free-firmware\n"
        f"deb {spec.mirror} {spec.suite}-updates main contrib non-free non-free-firmware\n"
    )


def _customize_script(spec: OSSpec) -> str:
    packages = " ".join(shlex.quote(pkg) for pkg in spec.all_packages)
    lines = [
        "#!/bin/sh",
        "set -eu",
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update",
        f"apt-get install -y --no-install-recommends {packages}",
        f"echo {shlex.quote(spec.hostname)} > /etc/hostname",
        f"printf '127.0.0.1\\tlocalhost\\n127.0.1.1\\t%s\\n' {shlex.quote(spec.hostname)} > /etc/hosts",
        f"ln -sf /usr/share/zoneinfo/{shlex.quote(spec.timezone)} /etc/localtime",
        f"echo {shlex.quote(spec.locale + ' UTF-8')} > /etc/locale.gen",
        "locale-gen || true",
        f"echo LANG={shlex.quote(spec.locale)} > /etc/default/locale",
        f"id -u {shlex.quote(spec.username)} >/dev/null 2>&1 || "
        f"useradd -m -s /bin/bash -G sudo {shlex.quote(spec.username)}",
        f"echo {shlex.quote(spec.username + ':' + spec.password)} | chpasswd",
        f"echo {shlex.quote('root:' + spec.root_password)} | chpasswd",
    ]

    if spec.autologin:
        override = (
            "[Service]\nExecStart=\nExecStart=-/sbin/agetty --noclear "
            f"--autologin {spec.username} %I $TERM\n"
        )
        serial_override = (
            "[Service]\nExecStart=\nExecStart=-/sbin/agetty --keep-baud 115200,38400,9600 "
            f"--autologin {spec.username} %I $TERM\n"
        )
        lines += [
            "mkdir -p /etc/systemd/system/getty@tty1.service.d "
            "/etc/systemd/system/serial-getty@ttyS0.service.d",
            f"cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'AIOS_EOF'\n{override}AIOS_EOF",
            "cat > /etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf "
            f"<<'AIOS_EOF'\n{serial_override}AIOS_EOF",
        ]

    network = "[Match]\nName=en* eth*\n\n[Network]\nDHCP=yes\n"
    lines += [
        "mkdir -p /etc/network/interfaces.d /etc/systemd/network",
        f"cat > /etc/systemd/network/20-dhcp.network <<'AIOS_EOF'\n{network}AIOS_EOF",
        "systemctl enable systemd-networkd || true",
        "systemctl enable systemd-resolved || true",
        "systemctl enable systemd-networkd-wait-online || true",
        "ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf",
    ]

    os_release = (
        f'PRETTY_NAME="{spec.name} {spec.version}"\n'
        f'NAME="{spec.name}"\n'
        f'VERSION="{spec.version}"\n'
        f"ID={spec.slug}\n"
        f"ID_LIKE=debian\n"
        f'ANSI_COLOR="0;36"\n'
        f'HOME_URL="https://example.invalid/{spec.slug}"\n'
    )
    lines += [
        f"cat > /etc/os-release <<'AIOS_EOF'\n{os_release}AIOS_EOF",
        f"cat > /etc/motd <<'AIOS_EOF'\n{spec.motd}\n\nBuilt by ai-os-builder. Accent: {spec.accent_color}\nAIOS_EOF",
        f"cat > /etc/issue <<'AIOS_EOF'\n{spec.name} {spec.version} \\n \\l\n\nAIOS_EOF",
    ]

    for path, content in spec.files.items():
        lines.append(f"mkdir -p {shlex.quote(str(Path(path).parent))}")
        lines.append(f"cat > {shlex.quote(path)} <<'AIOS_EOF'\n{content.rstrip()}\nAIOS_EOF")

    for service in spec.enable_services:
        lines.append(f"systemctl enable {shlex.quote(service)} || true")
    for service in spec.disable_services:
        lines.append(f"systemctl disable {shlex.quote(service)} || true")

    lines += spec.post_install
    lines += [
        "update-initramfs -u",
        "apt-get clean",
        "rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*",
    ]
    return "\n".join(lines) + "\n"


def _grub_cfg(spec: OSSpec) -> str:
    cmdline = f"boot=live components {spec.kernel_cmdline}"
    title = f"{spec.name} {spec.version}"
    return f"""set default=0
set timeout=5
serial --unit=0 --speed=115200
terminal_input console serial
terminal_output console serial

menuentry "{title} (live)" {{
    linux /live/vmlinuz {cmdline} console=tty0 console=ttyS0,115200
    initrd /live/initrd.img
}}

menuentry "{title} (safe graphics)" {{
    linux /live/vmlinuz {cmdline} nomodeset
    initrd /live/initrd.img
}}
"""


class Builder:
    def __init__(self, spec: OSSpec, workdir: Path, cache_dir: Path | None = None) -> None:
        self.spec = spec
        self.workdir = Path(workdir).resolve()
        self.rootfs = self.workdir / "rootfs"
        self.isodir = self.workdir / "iso"
        self.cache_dir = Path(cache_dir) if cache_dir else self.workdir.parent / "cache"

    # -- stages ---------------------------------------------------------
    def bootstrap(self) -> None:
        cache = self.cache_dir / f"{self.spec.suite}-{self.spec.arch}.tar"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _sudo(["rm", "-rf", str(self.rootfs)])
        self.rootfs.mkdir(parents=True)
        if cache.exists():
            _log(f"restoring bootstrap cache {cache.name}")
            _sudo(["tar", "-xf", str(cache), "-C", str(self.rootfs)])
            return
        _log(f"debootstrapping {self.spec.suite}/{self.spec.arch} (this takes a few minutes)")
        _sudo(["debootstrap", "--arch", self.spec.arch, "--variant=minbase",
               self.spec.suite, str(self.rootfs), self.spec.mirror])
        _sudo(["tar", "-cf", str(cache), "-C", str(self.rootfs), "."])

    def customize(self) -> None:
        _write_root_file(self.rootfs / "etc/apt/sources.list", _apt_sources(self.spec))
        _write_root_file(self.rootfs / "etc/resolv.conf", "nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
        _write_root_file(self.rootfs / "usr/sbin/policy-rc.d", "#!/bin/sh\nexit 101\n", mode="0755")
        _write_root_file(self.rootfs / "tmp/aios-customize.sh", _customize_script(self.spec), mode="0755")
        try:
            self._mount_pseudo()
            _sudo(["chroot", str(self.rootfs), "/tmp/aios-customize.sh"])
        finally:
            self._umount_pseudo()
        _sudo(["rm", "-f", str(self.rootfs / "usr/sbin/policy-rc.d"),
               str(self.rootfs / "tmp/aios-customize.sh")])

    def _mount_pseudo(self) -> None:
        for source, target, fstype in (
            ("proc", "proc", "proc"),
            ("sysfs", "sys", "sysfs"),
            ("devtmpfs", "dev", "devtmpfs"),
            ("devpts", "dev/pts", "devpts"),
        ):
            _sudo(["mount", "-t", fstype, source, str(self.rootfs / target)])

    def _umount_pseudo(self) -> None:
        for target in ("dev/pts", "dev", "sys", "proc"):
            subprocess.run(["sudo", "umount", "-lf", str(self.rootfs / target)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def assemble(self, output: Path) -> Path:
        _sudo(["rm", "-rf", str(self.isodir)])
        (self.isodir / "live").mkdir(parents=True)
        (self.isodir / "boot/grub").mkdir(parents=True)

        boot = self.rootfs / "boot"
        vmlinuz = sorted(boot.glob("vmlinuz-*"))
        initrd = sorted(boot.glob("initrd.img-*"))
        if not vmlinuz or not initrd:
            raise BuildError("no kernel/initrd found in the root filesystem")
        _sudo(["cp", str(vmlinuz[-1]), str(self.isodir / "live/vmlinuz")])
        _sudo(["cp", str(initrd[-1]), str(self.isodir / "live/initrd.img")])
        _sudo(["chmod", "0644", str(self.isodir / "live/vmlinuz"), str(self.isodir / "live/initrd.img")])

        _log("compressing root filesystem (squashfs)")
        _sudo(["mksquashfs", str(self.rootfs), str(self.isodir / "live/filesystem.squashfs"),
               "-comp", "xz", "-noappend", "-e", "boot"])
        _write_root_file(self.isodir / "boot/grub/grub.cfg", _grub_cfg(self.spec))

        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        _log(f"writing {output}")
        _sudo(["grub-mkrescue", "--output", str(output), str(self.isodir),
               "--", "-volid", self.spec.slug.upper().replace("-", "_")[:32]])
        _sudo(["chown", f"{os.getuid()}:{os.getgid()}", str(output)])
        return output

    def build(self, output: Path) -> Path:
        started = time.time()
        missing = check_tools()
        if missing:
            raise BuildError(f"missing required tools: {', '.join(missing)}")
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.bootstrap()
        self.customize()
        iso = self.assemble(output)
        size_mb = iso.stat().st_size / 1024 / 1024
        _log(f"done in {time.time() - started:.0f}s — {iso} ({size_mb:.0f} MiB)")
        return iso


def run_iso(iso: Path, *, memory: int = 2048, headless: bool = True, timeout: int | None = None) -> int:
    """Boot an ISO in QEMU. Headless mode uses the serial console."""
    cmd = ["qemu-system-x86_64", "-m", str(memory), "-cdrom", str(iso), "-boot", "d"]
    if shutil.which("kvm") or Path("/dev/kvm").exists():
        cmd += ["-enable-kvm"]
    cmd += ["-nographic"] if headless else ["-display", "gtk"]
    _log("$ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"[aios] qemu stopped after {timeout}s", file=sys.stderr)
        return 0
