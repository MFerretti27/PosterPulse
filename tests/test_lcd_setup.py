import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "setup-pi-lcd.sh"


class LcdSetupSshTests(unittest.TestCase):
    script = SCRIPT
    connection_error = "Could not connect"

    def run_deployment(self, failure=""):
        with tempfile.TemporaryDirectory(prefix="posterpulse ssh test ") as directory:
            root = Path(directory)
            calls = root / "calls"
            for command in ("ssh", "scp", "tar"):
                executable = root / command
                executable.write_text(
                    '#!/bin/sh\n'
                    'printf "%s\\n" "---${0##*/}" "$@" >> "$CALLS"\n'
                    'for arg do\n'
                    '    if [ -n "$FAILURE" ] && [ "$arg" = "$FAILURE" ]; then\n'
                    '        exit 23\n'
                    '    fi\n'
                    'done\n'
                    'case "$*" in\n'
                    '    *"tar -xzf"*) cat >/dev/null ;;\n'
                    'esac\n'
                )
                executable.chmod(0o755)
            result = subprocess.run(
                ["bash", str(self.script), "-ip=example.test", "-user=matt", "-port=2222"],
                env={
                    **os.environ,
                    "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                    "CALLS": str(calls),
                    "FAILURE": failure,
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            commands = [
                call.splitlines() for call in calls.read_text().split("---") if call
            ]
            return result, commands

    def assert_shared_connection_cleaned_up(self, commands):
        ssh_calls = [call for call in commands if call[0] == "ssh"]
        master = ssh_calls[0]
        self.assertIn("ControlMaster=yes", master)
        self.assertIn("BatchMode=no", master)
        self.assertIn("-fN", master)
        control = next(arg for arg in master if arg.startswith("ControlPath="))
        for call in commands:
            if call[0] in ("ssh", "scp"):
                self.assertIn(control, call)
                self.assertIn("2222", call)
                if call is not master:
                    self.assertIn("BatchMode=yes", call)
                    self.assertIn("ControlMaster=no", call)
        self.assertIn("-O", ssh_calls[-1])
        self.assertIn("exit", ssh_calls[-1])
        self.assertFalse(Path(control.removeprefix("ControlPath=")).parent.exists())

    def test_deployment_reuses_connection_and_cleans_up(self):
        result, commands = self.run_deployment()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("sudo bash" in call[-1] for call in commands))
        self.assert_shared_connection_cleaned_up(commands)

    def test_connection_failure_stops_deployment_and_cleans_up(self):
        result, commands = self.run_deployment("-fN")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.connection_error, result.stdout + result.stderr)
        self.assertEqual(len(commands), 2)
        self.assert_shared_connection_cleaned_up(commands)

    def test_setup_failure_preserves_exit_status_and_cleans_up(self):
        result, commands = self.run_deployment(
            f"cd ~/PosterPulse && sudo bash .github/{self.script.name} --local -user=matt"
        )
        self.assertEqual(result.returncode, 23)
        self.assert_shared_connection_cleaned_up(commands)


class EinkSetupSshTests(LcdSetupSshTests):
    script = SCRIPT.with_name("setup-pi-eink.sh")
    connection_error = "Failed to connect"

    def test_env_transfer_failure_stops_setup_and_cleans_up(self):
        result, commands = self.run_deployment("matt@example.test:~/PosterPulse/.env")
        self.assertEqual(result.returncode, 23)
        self.assertFalse(any("sudo bash" in call[-1] for call in commands))
        self.assert_shared_connection_cleaned_up(commands)


class LcdSetupLaunchTests(unittest.TestCase):
    def run_launcher(self, app, blocked_log=False):
        source = SCRIPT.read_text()
        start = source.index('    runuser -u "$CURRENT_USER" -- sh -c')
        end = source.index("\nelse\n", start)
        launch = source[start:end]

        with tempfile.TemporaryDirectory(prefix="posterpulse setup ") as directory:
            root = Path(directory)
            log = root / "regular.log"
            pid_file = root / "app.pid"
            if blocked_log:
                log.mkdir()

            runuser = root / "runuser"
            runuser.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
            runuser.chmod(0o755)
            venv = root / ".venv"
            (venv / "bin").mkdir(parents=True)
            python = venv / "bin" / "python"
            python.write_text(
                '#!/bin/sh\nprintf "%s" "$$" > "$PID_FILE"\n' + app
            )
            python.chmod(0o755)

            environment = {
                **os.environ,
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CURRENT_USER": "desktop-user",
                "REPO_DIR": str(root),
                "VENV_DIR": str(venv),
                "LOG_FILE": str(log),
                "PID_FILE": str(pid_file),
            }
            try:
                result = subprocess.run(
                    ["bash", "-eu", "-c", launch],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = log.read_text() if log.is_file() else ""
                launched = pid_file.exists()
            finally:
                if pid_file.exists():
                    pid = int(pid_file.read_text())
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            return result, output, launched

    def test_running_app_logs_and_reports_success(self):
        result, output, launched = self.run_launcher(
            'printf "display=%s cwd=%s\\n" "$DISPLAY" "$PWD"\nexec sleep 30\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(launched)
        self.assertIn("display=:0 cwd=", output)
        self.assertIn("Started PosterPulse", result.stdout)
        self.assertIn("regular.log", result.stdout)

    def test_early_exit_reports_log_without_success(self):
        result, output, launched = self.run_launcher(
            'echo "display initialization failed"\nexit 1\n'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(launched)
        self.assertIn("display initialization failed", output)
        self.assertIn("display initialization failed", result.stderr)
        self.assertIn("exited during startup", result.stderr)
        self.assertNotIn("Started PosterPulse", result.stdout)

    def test_unwritable_log_prevents_launch_without_success(self):
        result, _, launched = self.run_launcher("exec sleep 30\n", blocked_log=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(launched)
        self.assertIn("regular.log", result.stderr)
        self.assertNotIn("Started PosterPulse", result.stdout)


if __name__ == "__main__":
    unittest.main()
