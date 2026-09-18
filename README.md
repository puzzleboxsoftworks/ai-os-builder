# ai-os-builder

Describe an operating system in English, get a **real bootable Linux ISO** (hybrid BIOS + UEFI).

```bash
aios make "a headless rescue and networking toolkit" -o dist/rescue.iso
aios run dist/rescue.iso            # boot it in QEMU on the serial console
```

The prompt goes to an LLM that emits a validated JSON *OS spec*; the builder then
debootstraps a Debian/Ubuntu root filesystem, installs and configures the
packages the spec asks for, squashes it, and wraps it in a GRUB rescue image.
No LLM key? The keyword planner produces a spec offline, so the pipeline always runs.

## Web app

<https://puzzleboxsoftworks.github.io/ai-os-builder/> — type a prompt, get a validated
spec in the browser (offline planner, or your own OpenAI-compatible key, which never
leaves your browser), then hit **Build ISO in Actions**: the page dispatches the
`build-iso` workflow with your spec, follows the run, and downloads the finished ISO
artifact for you. That needs a fine-grained GitHub token for this repo with
*Actions: read and write*, also kept only in your browser.

Pages can't run `debootstrap`/`chroot`, so the build itself happens in CI (or locally
with the CLI); you can also download the spec and run `aios build spec.json` yourself.

## Install

```bash
sudo apt-get install debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools qemu-system-x86
pip install -e .
aios doctor          # verifies the toolchain
```

Building needs `sudo` (debootstrap, chroot, mksquashfs). Python 3.10+, stdlib only.

## Commands

| Command | Purpose |
| --- | --- |
| `aios plan "<prompt>" -o spec.json` | prompt → OS spec, no build |
| `aios build spec.json -o out.iso` | spec → ISO (hand-edit the spec first if you like) |
| `aios make "<prompt>" -o out.iso` | plan + build in one step |
| `aios run out.iso [--gui]` | boot the ISO in QEMU |
| `aios doctor` | check host build tools |

## LLM configuration

Any OpenAI-compatible endpoint works:

```bash
export AIOS_API_KEY=sk-...                        # or OPENAI_API_KEY
export AIOS_BASE_URL=https://api.openai.com/v1    # optional
export AIOS_MODEL=gpt-4o-mini                     # optional
```

Without a key (or with `--offline`), the deterministic keyword planner is used.

## The spec

```json
{
  "name": "Forge Linux",
  "slug": "forge",
  "suite": "bookworm",
  "desktop": "xfce",
  "packages": ["git", "build-essential"],
  "username": "user",
  "autologin": true,
  "files": {"/etc/forge.conf": "hello"},
  "post_install": ["echo built > /etc/forge-stamp"],
  "enable_services": ["ssh"]
}
```

Everything is optional. Suites: `bookworm`, `trixie`, `sid`, `jammy`, `noble`.
Desktops: `none`, `xfce`, `lxqt`, `gnome`, `i3`. Specs are validated before any
build starts — package, service, user and path names are pattern-checked, and
`files` paths must be absolute.

## What the ISO contains

- `/live/filesystem.squashfs` — xz-compressed root filesystem
- `/live/vmlinuz`, `/live/initrd.img` — kernel and a `live-boot` initramfs
- GRUB config with a normal entry, a `nomodeset` entry, and serial console
  output on `ttyS0` so headless QEMU/IPMI boots are debuggable

The live user is auto-logged in on tty1 and ttyS0 (configurable), networking is
DHCP via `systemd-networkd`. A headless Debian build is ~220 MiB and takes about
3 minutes on a warm bootstrap cache (cached per suite/arch in `build/cache`).

## Writing to a USB stick

```bash
sudo dd if=dist/rescue.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

## Tests

```bash
python -m unittest discover tests
```

The unit tests cover spec validation, the offline planner and the generated
chroot/GRUB scripts; they do not build an ISO (that needs root and a network).
