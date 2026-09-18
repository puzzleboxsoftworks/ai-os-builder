"""Command line interface: prompt in, bootable ISO out."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import Builder, BuildError, check_tools, run_iso
from .planner import plan
from .spec import OSSpec, SpecError


def _default_workdir(spec: OSSpec) -> Path:
    return Path("build") / spec.slug


def cmd_plan(args: argparse.Namespace) -> int:
    spec, planner = plan(args.prompt, offline=args.offline)
    out = Path(args.output) if args.output else None
    print(f"[aios] planner: {planner}", file=sys.stderr)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(spec.to_json())
        print(f"[aios] wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(spec.to_json())
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    spec = OSSpec.load(args.spec)
    output = Path(args.output) if args.output else Path(f"{spec.slug}-{spec.version}.iso")
    builder = Builder(spec, Path(args.workdir) if args.workdir else _default_workdir(spec))
    builder.build(output)
    return 0


def cmd_make(args: argparse.Namespace) -> int:
    spec, planner = plan(args.prompt, offline=args.offline)
    print(f"[aios] planner: {planner}", file=sys.stderr)
    sys.stderr.write(spec.to_json())
    if args.spec_out:
        spec_out = Path(args.spec_out)
        spec_out.parent.mkdir(parents=True, exist_ok=True)
        spec_out.write_text(spec.to_json())
    output = Path(args.output) if args.output else Path(f"{spec.slug}-{spec.version}.iso")
    builder = Builder(spec, Path(args.workdir) if args.workdir else _default_workdir(spec))
    builder.build(output)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return run_iso(Path(args.iso), memory=args.memory, headless=not args.gui, timeout=args.timeout)


def cmd_doctor(_: argparse.Namespace) -> int:
    missing = check_tools()
    if missing:
        print("missing tools: " + ", ".join(missing))
        print("install with: sudo apt-get install debootstrap squashfs-tools xorriso "
              "grub-pc-bin grub-efi-amd64-bin mtools")
        return 1
    print("all required build tools are present")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aios", description="AI-driven bootable Linux ISO builder")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="turn a prompt into an OS spec (JSON)")
    p_plan.add_argument("prompt")
    p_plan.add_argument("-o", "--output")
    p_plan.add_argument("--offline", action="store_true", help="skip the LLM, use the keyword planner")
    p_plan.set_defaults(func=cmd_plan)

    p_build = sub.add_parser("build", help="build an ISO from a spec file")
    p_build.add_argument("spec")
    p_build.add_argument("-o", "--output")
    p_build.add_argument("-w", "--workdir")
    p_build.set_defaults(func=cmd_build)

    p_make = sub.add_parser("make", help="plan and build in one step")
    p_make.add_argument("prompt")
    p_make.add_argument("-o", "--output")
    p_make.add_argument("-w", "--workdir")
    p_make.add_argument("--spec-out")
    p_make.add_argument("--offline", action="store_true")
    p_make.set_defaults(func=cmd_make)

    p_run = sub.add_parser("run", help="boot an ISO in QEMU")
    p_run.add_argument("iso")
    p_run.add_argument("-m", "--memory", type=int, default=2048)
    p_run.add_argument("--gui", action="store_true")
    p_run.add_argument("--timeout", type=int)
    p_run.set_defaults(func=cmd_run)

    p_doctor = sub.add_parser("doctor", help="check that the host has the build toolchain")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SpecError, BuildError) as exc:
        print(f"[aios] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
