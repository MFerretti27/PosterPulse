import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WifiRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "disconnected"
        self.calls = self.root / "calls"
        self.uptime = self.root / "uptime"
        source = (ROOT / "scripts/pi-wifi-watchdog.sh").read_text()
        self.script = self.root / "watchdog"
        self.script.write_text(source.replace("/proc/uptime", str(self.uptime)))
        nmcli = self.root / "nmcli"
        nmcli.write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$CALLS"\n'
            'case "$*" in\n'
            '  *"radio wifi off") echo disabled > "$RADIO_FILE"; exit "${OFF_RESULT:-0}" ;;\n'
            '  *"radio wifi on") if [[ "${ON_RESULT:-0}" != 0 ]]; then exit "$ON_RESULT"; fi; '
            'echo enabled > "$RADIO_FILE" ;;\n'
            '  *"radio wifi") if [[ -f "$RADIO_FILE" ]]; then cat "$RADIO_FILE"; '
            'else echo "${RADIO:-enabled}"; fi; exit "${RADIO_RESULT:-0}" ;;\n'
            '  *"device status") printf "%s\\n" "$DEVICES"; '
            'exit "${PROBE_RESULT:-0}" ;;\n'
            "  *) exit 99 ;;\n"
            "esac\n"
        )
        nmcli.chmod(0o755)
        sleep = self.root / "sleep"
        sleep.write_text(
            '#!/bin/bash\necho "sleep $*" >> "$CALLS"\nexit "${SLEEP_RESULT:-0}"\n'
        )
        sleep.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
            "STATE_DIR": str(self.root),
            "RECOVERY_DIR": str(self.root),
            "CALLS": str(self.calls),
            "RADIO_FILE": str(self.root / "radio"),
            "DEVICES": "wlan0:wifi:disconnected",
        }

    def run_check(self, now, **env):
        self.uptime.write_text(f"{now}.00 0.00\n")
        return subprocess.run(
            ["bash", str(self.script)],
            env={**self.env, **env},
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )

    def test_waits_five_minutes_then_cycles_and_restarts_wait(self):
        for now in range(0, 300, 30):
            self.assertEqual(self.run_check(now).returncode, 0)
        self.assertNotIn("wifi off", self.calls.read_text())
        result = self.run_check(300)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("five minutes", result.stdout)
        self.assertEqual(
            self.calls.read_text().splitlines()[-4:],
            [
                "--wait 10 radio wifi off",
                "sleep 5",
                "--wait 10 radio wifi on",
                "--wait 10 radio wifi",
            ],
        )
        self.assertFalse(self.state.exists())
        for now in range(330, 630, 30):
            self.assertEqual(self.run_check(now).returncode, 0)
        self.assertEqual(self.calls.read_text().count("wifi off"), 1)
        self.assertEqual(self.run_check(630).returncode, 0)
        self.assertEqual(self.calls.read_text().count("wifi off"), 2)

    def test_connection_or_disabled_radio_clears_outage(self):
        for env in (
            {"DEVICES": "wlan0:wifi:connected"},
            {"DEVICES": "wlan0:wifi:connected (externally)"},
            {"DEVICES": "wlan0:wifi:disconnected\nwlan1:wifi:connected"},
            {"RADIO": "disabled"},
            {"DEVICES": "wlan0:wifi:unmanaged"},
            {"DEVICES": "eth0:ethernet:disconnected"},
        ):
            with self.subTest(env=env):
                self.state.write_text("0 270\n")
                result = self.run_check(300, **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.state.exists())
        self.assertNotIn("wifi off", self.calls.read_text())

    def test_stale_invalid_and_rebooted_state_restarts_wait(self):
        for contents in ("0 100\n", "invalid\n", "", "500 600\n"):
            with self.subTest(contents=contents):
                self.state.write_text(contents)
                result = self.run_check(300)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.state.read_text(), "300 300\n")
        self.assertNotIn("wifi off", self.calls.read_text())

    def test_failed_probe_does_not_cycle_or_count_unknown_time(self):
        for env in ({"PROBE_RESULT": "1"}, {"RADIO_RESULT": "1"}):
            with self.subTest(env=env):
                self.state.write_text("0 270\n")
                result = self.run_check(300, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Could not read", result.stderr)
                self.assertFalse(self.state.exists())
        self.assertNotIn("wifi off", self.calls.read_text())

    def test_interrupted_cycle_restores_radio_and_limits_retries(self):
        for env in ({"OFF_RESULT": "1"}, {"SLEEP_RESULT": "1"}, {"ON_RESULT": "1"}):
            with self.subTest(env=env):
                self.state.write_text("0 270\n")
                result = self.run_check(300, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Restoring Wi-Fi", result.stdout)
                self.assertIn("radio wifi on", self.calls.read_text())
                self.assertEqual(self.state.read_text(), "300 300\n")
                before = self.calls.read_text().count("wifi off")
                self.assertEqual(self.run_check(330).returncode, 0)
                self.assertEqual(self.calls.read_text().count("wifi off"), before)

    def test_failed_radio_restoration_is_retried_on_later_checks(self):
        self.state.write_text("0 270\n")
        result = self.run_check(300, ON_RESULT="1")
        self.assertNotEqual(result.returncode, 0)
        pending = self.root / "restore-pending"
        self.assertTrue(pending.exists())
        self.assertEqual((self.root / "radio").read_text().strip(), "disabled")
        result = self.run_check(330, ON_RESULT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(pending.exists())
        result = self.run_check(360)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Retrying pending", result.stdout)
        self.assertFalse(pending.exists())
        self.assertEqual((self.root / "radio").read_text().strip(), "enabled")
        self.assertEqual(self.calls.read_text().count("wifi off"), 1)

    def test_setup_installs_and_enables_timer_only_with_networkmanager(self):
        for command in ("install", "systemctl"):
            executable = self.root / command
            executable.write_text(
                "#!/bin/bash\n"
                'echo "${0##*/} $*" >> "$CALLS"\n'
                'if [[ "$*" == "is-active --quiet NetworkManager" ]]; then\n'
                '  exit "${NM_RESULT:-0}"\n'
                "fi\n"
            )
            executable.chmod(0o755)
        installer = ROOT / "scripts/setup-pi-wifi.sh"
        result = subprocess.run(
            ["bash", str(installer)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("install -m 0755", calls)
        for source in (
            ROOT / "scripts/pi-wifi-watchdog.sh",
            ROOT / "systemd/posterpulse-wifi.service",
            ROOT / "systemd/posterpulse-wifi.timer",
        ):
            self.assertTrue(source.is_file())
            self.assertIn(str(source), calls)
        self.assertIn("systemctl daemon-reload", calls)
        self.assertIn("systemctl enable --now posterpulse-wifi.timer", calls)
        self.calls.unlink()
        result = subprocess.run(
            ["bash", str(installer)],
            env={**self.env, "NM_RESULT": "3"},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Warning:", result.stderr)
        self.assertNotIn("install ", self.calls.read_text())
        for setup in ("setup-pi-eink.sh", "setup-pi-lcd.sh"):
            self.assertIn(
                'bash "${SCRIPT_DIR}/setup-pi-wifi.sh"',
                (ROOT / "scripts" / setup).read_text(),
            )


if __name__ == "__main__":
    unittest.main()
