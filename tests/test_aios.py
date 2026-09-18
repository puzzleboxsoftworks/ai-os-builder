import unittest

from aios.builder import _apt_sources, _customize_script, _grub_cfg
from aios.planner import plan_offline
from aios.spec import OSSpec, SpecError


class SpecTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        OSSpec().validate()

    def test_roundtrip(self):
        spec = OSSpec(name="Forge Linux", slug="forge", packages=["git"])
        self.assertEqual(OSSpec.from_dict(spec.to_dict()).to_dict(), spec.to_dict())

    def test_rejects_bad_input(self):
        for kwargs in (
            {"slug": "Not A Slug"},
            {"suite": "windows"},
            {"desktop": "kde"},
            {"packages": ["git; rm -rf /"]},
            {"username": "1nvalid"},
            {"files": {"relative/path": "x"}},
            {"files": {"/etc/../root/x": "x"}},
            {"post_install": ["echo a\necho b"]},
        ):
            with self.subTest(**kwargs), self.assertRaises(SpecError):
                OSSpec(**kwargs).validate()

    def test_unknown_field_rejected(self):
        with self.assertRaises(SpecError):
            OSSpec.from_dict({"name": "X", "sudo_everything": True})

    def test_base_packages_added_once(self):
        packages = OSSpec(desktop="xfce", packages=["sudo", "git"]).all_packages
        self.assertEqual(packages.count("sudo"), 1)
        self.assertIn("linux-image-amd64", packages)
        self.assertIn("live-boot", packages)
        self.assertIn("xfce4", packages)

    def test_ubuntu_kernel_name(self):
        self.assertIn("linux-image-generic", OSSpec(suite="jammy").all_packages)


class PlannerTests(unittest.TestCase):
    def test_keywords_drive_packages(self):
        spec = plan_offline("a rust dev box with ssh")
        self.assertIn("cargo", spec.packages)
        self.assertIn("openssh-server", spec.packages)
        self.assertEqual(spec.enable_services, ["ssh"])
        self.assertEqual(spec.desktop, "none")

    def test_desktop_inferred(self):
        self.assertEqual(plan_offline("a graphical browser kiosk").desktop, "xfce")
        self.assertEqual(plan_offline("an i3 tiling setup").desktop, "i3")

    def test_suite_inferred(self):
        self.assertEqual(plan_offline("an ubuntu based server").suite, "jammy")
        self.assertEqual(plan_offline("a debian server").suite, "bookworm")

    def test_always_valid(self):
        for prompt in ("", "!!!", "a" * 500, "ubuntu gnome workstation for python"):
            plan_offline(prompt).validate()


class ScriptTests(unittest.TestCase):
    def test_customize_script_shape(self):
        spec = OSSpec(slug="forge", name="Forge", files={"/etc/forge.conf": "hi"},
                      post_install=["touch /etc/stamp"], enable_services=["ssh"])
        script = _customize_script(spec)
        self.assertTrue(script.startswith("#!/bin/sh\nset -eu\n"))
        self.assertIn("apt-get install -y --no-install-recommends", script)
        self.assertIn("/etc/forge.conf", script)
        self.assertIn("touch /etc/stamp", script)
        self.assertIn("systemctl enable ssh", script)
        self.assertIn("update-initramfs -u", script)

    def test_autologin_optional(self):
        self.assertIn("--autologin", _customize_script(OSSpec(autologin=True)))
        self.assertNotIn("--autologin", _customize_script(OSSpec(autologin=False)))

    def test_apt_sources_per_distro(self):
        self.assertIn("universe", _apt_sources(OSSpec(suite="jammy")))
        self.assertIn("non-free-firmware", _apt_sources(OSSpec(suite="bookworm")))

    def test_grub_cfg(self):
        cfg = _grub_cfg(OSSpec(name="Forge", version="2.0", kernel_cmdline="quiet splash"))
        self.assertIn("linux /live/vmlinuz boot=live components quiet splash", cfg)
        self.assertIn("initrd /live/initrd.img", cfg)
        self.assertIn("nomodeset", cfg)
        self.assertIn("serial --unit=0", cfg)


if __name__ == "__main__":
    unittest.main()
