import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PiLoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.calls = self.root / "calls"
        for command in ("install", "systemctl", "journalctl", "cmp"):
            executable = self.root / command
            executable.write_text(
                "#!/bin/bash\n"
                'echo "${0##*/} $*" >> "$CALLS"\n'
                'case "${0##*/}" in\n'
                '  cmp) exit "${CMP_RESULT:-1}" ;;\n'
                '  journalctl) exit "${FLUSH_RESULT:-0}" ;;\n'
                "esac\n"
            )
            executable.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(self.calls),
        }

    def run_setup(self, **env):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/setup-pi-logging.sh")],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    def test_installs_configuration_restarts_and_flushes(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("install -d /var/log/journal /etc/systemd/journald.conf.d", calls)
        self.assertIn("systemd/posterpulse-journald.conf", calls)
        self.assertIn("/etc/systemd/journald.conf.d/posterpulse.conf", calls)
        self.assertIn("systemctl restart systemd-journald.service", calls)
        self.assertIn("journalctl --flush", calls)
        self.assertEqual(
            (ROOT / "systemd/posterpulse-journald.conf").read_text(),
            "[Journal]\nStorage=persistent\nSystemMaxUse=100M\n",
        )

    def test_unchanged_configuration_does_not_restart_journald(self):
        result = self.run_setup(CMP_RESULT="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertNotIn("systemctl restart", calls)
        self.assertNotIn("install -m", calls)
        self.assertIn("journalctl --flush", calls)

    def test_flush_failure_is_reported(self):
        result = self.run_setup(FLUSH_RESULT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("configured", result.stdout)

    def test_both_pi_setups_call_logging_helper(self):
        for script in ("setup-pi-eink.sh", "setup-pi-lcd.sh"):
            with self.subTest(script=script):
                self.assertIn(
                    'bash "${SCRIPT_DIR}/setup-pi-logging.sh"',
                    (ROOT / "scripts" / script).read_text(),
                )


if __name__ == "__main__":
    unittest.main()
