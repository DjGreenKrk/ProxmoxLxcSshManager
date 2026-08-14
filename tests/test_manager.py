import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app" / "ProxmoxLxcSshManager.py"
SPEC = importlib.util.spec_from_file_location("proxmox_manager", APP_PATH)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class VersionTests(unittest.TestCase):
    def test_source_version_matches_version_file(self):
        self.assertEqual(manager.APP_VERSION, (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip())


class SettingsMigrationTests(unittest.TestCase):
    def test_legacy_hosts_and_prefix_are_migrated(self):
        legacy = {
            "hosts": ["192.168.0.9", "pve.example.test"],
            "proxmox_user": "operator",
            "lxc_ip_prefix": "10.20.0.",
        }
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps(legacy), encoding="utf-8")
            with patch.object(manager, "CONFIG_FILE", config):
                settings = manager.load_settings()

        self.assertEqual(
            settings["hosts"],
            [
                {"address": "192.168.0.9", "user": "operator", "port": 22},
                {"address": "pve.example.test", "user": "operator", "port": 22},
            ],
        )
        self.assertEqual(settings["lxc_ip_prefixes"], ["10.20.0."])
        self.assertNotIn("proxmox_user", settings)

    def test_current_host_name_is_preserved(self):
        current = {
            "hosts": [
                {
                    "address": "192.168.1.100",
                    "user": "root",
                    "port": 2222,
                    "name": "pve-one.example.test",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps(current), encoding="utf-8")
            with patch.object(manager, "CONFIG_FILE", config):
                settings = manager.load_settings()

        self.assertEqual(settings["hosts"], current["hosts"])


class SshCommandTests(unittest.TestCase):
    def test_run_ssh_script_uses_profile_port_and_user(self):
        completed = SimpleNamespace(returncode=0, stdout=b"")
        with patch.object(manager.subprocess, "run", return_value=completed) as run:
            result = manager.run_ssh_script("pve.example.test", "true\n", "operator", 2222, 9)

        self.assertEqual(result.returncode, 0)
        command = run.call_args.args[0]
        self.assertIn("operator@pve.example.test", command)
        self.assertEqual(command[command.index("-p") + 1], "2222")
        self.assertIn("ConnectTimeout=9", command)
        self.assertEqual(run.call_args.kwargs["input"], b"true\n")

    def test_unknown_host_key_is_classified_as_trust_required(self):
        completed = SimpleNamespace(returncode=255, stdout=b"Host key verification failed")
        with patch.object(manager.subprocess, "run", return_value=completed):
            status, _ = manager.check_ssh_access("192.0.2.10")
        self.assertEqual(status, "wymaga zaufania")

    def test_accept_new_policy_is_only_used_when_requested(self):
        completed = SimpleNamespace(returncode=0, stdout=b"")
        commands = []

        def capture(command, **_kwargs):
            commands.append(command)
            return completed

        with patch.object(manager.subprocess, "run", side_effect=capture):
            manager.check_ssh_access("192.0.2.10", accept_new=False)
            manager.check_ssh_access("192.0.2.10", accept_new=True)

        self.assertIn("StrictHostKeyChecking=yes", commands[0])
        self.assertIn("StrictHostKeyChecking=accept-new", commands[1])

    def test_configure_script_supports_common_package_and_service_managers(self):
        for command in ("apt-get install", "apk add", "dnf install"):
            self.assertIn(command, manager.CONFIGURE_SCRIPT)
        for service_manager in ("systemctl", "rc-service"):
            self.assertIn(service_manager, manager.CONFIGURE_SCRIPT)


class DryRunTests(unittest.TestCase):
    def test_upload_preview_does_not_call_scp_or_require_existing_key(self):
        messages = []
        fake = SimpleNamespace(
            key_path=SimpleNamespace(get=lambda: "missing-preview-key.pub"),
            dry_run=SimpleNamespace(get=lambda: True),
            validated_remote_key_path=lambda: "/root/access.pub",
            validated_timeout=lambda: 8,
            host_address=lambda host: host["address"],
            log=messages.append,
        )
        hosts = [{"address": "192.0.2.10", "user": "root", "port": 22}]

        with patch.object(manager.subprocess, "run") as run:
            manager.ProxmoxManager.upload_keys(fake, hosts)

        run.assert_not_called()
        self.assertTrue(any("PODGLĄD" in message for message in messages))


class FormattingTests(unittest.TestCase):
    def test_host_label_includes_discovered_name(self):
        profile = {"address": "192.168.1.100", "user": "root", "port": 22, "name": "pve-one"}
        self.assertEqual(
            manager.ProxmoxManager.host_label(profile),
            "pve-one — root@192.168.1.100:22",
        )

    def test_filename_part_replaces_windows_invalid_characters(self):
        self.assertEqual(manager.safe_filename_part('lxc:<test>|?*'), "lxc__test____")


if __name__ == "__main__":
    unittest.main()
