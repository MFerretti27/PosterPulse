import os
import signal
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup-pi-lcd.sh"


class LcdSetupSshTests(unittest.TestCase):
    script = SCRIPT
    connection_error = "Could not connect"
    setup_args = ()

    def run_deployment(self, failure=""):
        with tempfile.TemporaryDirectory(prefix="posterpulse ssh test ") as directory:
            root = Path(directory)
            calls = root / "calls"
            for command in ("ssh", "scp", "tar"):
                executable = root / command
                executable.write_text(
                    "#!/bin/sh\n"
                    'printf "%s\\n" "---${0##*/}" "$@" >> "$CALLS"\n'
                    "for arg do\n"
                    '    if [ -n "$FAILURE" ] && [ "$arg" = "$FAILURE" ]; then\n'
                    "        exit 23\n"
                    "    fi\n"
                    "done\n"
                    'case "$*" in\n'
                    '    *"tar -xzf"*) cat >/dev/null ;;\n'
                    "esac\n"
                )
                executable.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(self.script),
                    "-ip=example.test",
                    "-user=matt",
                    "-port=2222",
                    *self.setup_args,
                ],
                check=False,
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
        for stage in ("[1/3]", "[2/3]", "[3/3]", "Remote Deployment Complete!"):
            self.assertIn(stage, result.stdout)
        self.assert_shared_connection_cleaned_up(commands)

    def test_connection_failure_stops_deployment_and_cleans_up(self):
        result, commands = self.run_deployment("-fN")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.connection_error, result.stdout + result.stderr)
        self.assertEqual(len(commands), 2)
        self.assert_shared_connection_cleaned_up(commands)

    def test_setup_failure_preserves_exit_status_and_cleans_up(self):
        result, commands = self.run_deployment(
            f"cd ~/PosterPulse && sudo bash scripts/{self.script.name} --local -user=matt"
            + "".join(f" {arg}" for arg in self.setup_args)
        )
        self.assertEqual(result.returncode, 23)
        self.assertNotIn("Remote Deployment Complete!", result.stdout)
        self.assert_shared_connection_cleaned_up(commands)


class EinkSetupSshTests(LcdSetupSshTests):
    script = SCRIPT.with_name("setup-pi-eink.sh")
    connection_error = "Failed to connect"
    setup_args = ("--display=4in0e",)

    def test_selected_model_is_forwarded_to_remote_setup(self):
        for model in ("4in0e", "7in3e"):
            with self.subTest(model=model):
                self.setup_args = (f"--display={model}",)
                result, commands = self.run_deployment()
                self.assertEqual(result.returncode, 0, result.stderr)
                setup = next(call[-1] for call in commands if "sudo bash" in call[-1])
                self.assertIn(f"--display={model}", setup)

    def test_env_transfer_failure_stops_setup_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            script_dir = repo / "scripts"
            script_dir.mkdir()
            script = script_dir / self.script.name
            script.write_text(self.script.read_text())
            (repo / ".env").touch()
            self.script = script
            result, commands = self.run_deployment(
                "matt@example.test:~/PosterPulse/.env"
            )
        self.assertEqual(result.returncode, 23)
        self.assertFalse(any("sudo bash" in call[-1] for call in commands))
        self.assert_shared_connection_cleaned_up(commands)


class EinkDisplaySelectionTests(unittest.TestCase):
    script = SCRIPT.with_name("setup-pi-eink.sh")

    def test_missing_or_invalid_display_is_rejected_before_setup(self):
        for args in (
            ["--local"],
            ["-ip=example.test"],
            ["--local", "--display=unknown"],
            ["--local", "--display="],
            ["--local", "--display"],
            ["--display", "--local"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(self.script), *args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--display", result.stderr)
                self.assertNotIn("==>", result.stdout)

    def test_help_does_not_require_display(self):
        result = subprocess.run(
            ["bash", str(self.script), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--display", result.stdout)

    def test_selected_model_sets_matching_panel_configuration(self):
        source = self.script.read_text()
        argument_parsing = source[: source.index("# Mode A:")]
        configuration = source[
            source.index("ensure_env_var()") : source.index('chown "${CURRENT_USER}')
        ]
        for model, width, height, pin in (
            ("4in0e", "400", "600", "18"),
            ("7in3e", "800", "480", "27"),
        ):
            for flag in ([f"--display={model}"], ["--display", model]):
                with (
                    self.subTest(model=model, flag=flag),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    env_file = Path(directory) / ".env"
                    env_file.touch()
                    script = Path(directory) / self.script.name
                    script.write_text(argument_parsing + "\n" + configuration)
                    result = subprocess.run(
                        [
                            "bash",
                            str(script),
                            *flag,
                        ],
                        env={**os.environ, "ENV_FILE": str(env_file)},
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    values = dict(
                        line.split("=", 1) for line in env_file.read_text().splitlines()
                    )
                    self.assertEqual(values["EINK_MODEL"], model)
                    self.assertEqual(values["EINK_WIDTH"], width)
                    self.assertEqual(values["EINK_HEIGHT"], height)
                    self.assertEqual(values["EINK_PWR_PIN"], pin)
                    self.assertEqual(values["DISPLAY_TYPE"], "eink")
                    self.assertEqual(result.stdout.count("Selected E-Ink Display"), 2)
                    for label in (
                        f"Model:      {model}",
                        f"Resolution: {width}x{height}",
                        f"Power pin:  BCM {pin}",
                    ):
                        self.assertEqual(result.stdout.count(label), 2)
                    self.assertIn(
                        f"Display configuration saved to {env_file}:",
                        result.stdout,
                    )


class LcdSetupOutputTests(unittest.TestCase):
    def test_missing_credentials_skip_launch_and_print_next_steps(self):
        source = SCRIPT.read_text()
        start = source.index('echo "==> [5/5]')
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.touch()
            socket_path = Path(directory) / "X0"
            source = source.replace("/tmp/.X11-unix/X0", str(socket_path))
            with socket.socket(socket.AF_UNIX) as display_socket:
                display_socket.bind(str(socket_path))
                result = subprocess.run(
                    ["bash", "-eu", "-c", source[start:]],
                    check=False,
                    env={
                        **os.environ,
                        "ENV_FILE": str(env_file),
                        "REPO_DIR": directory,
                        "VENV_DIR": str(Path(directory) / ".venv"),
                        "USER_HOME": directory,
                        "CURRENT_USER": "matt",
                        "AUTOSTART_FILE": str(Path(directory) / "posterpulse.desktop"),
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipping the immediate launch", result.stdout)
        self.assertIn("Next Steps:", result.stdout)
        self.assertNotIn("Started PosterPulse", result.stdout)

    def test_local_summary_has_desktop_specific_next_steps(self):
        source = SCRIPT.read_text()
        start = source.index(
            '\necho ""\necho "======', source.index("if [[ -S /tmp/.X11")
        )
        result = subprocess.run(
            ["bash", "-eu", "-c", source[start:]],
            check=False,
            env={
                **os.environ,
                "ENV_FILE": "/home/matt/PosterPulse/.env",
                "USER_HOME": "/home/matt",
                "AUTOSTART_FILE": "/home/matt/.config/autostart/posterpulse.desktop",
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in (
            "Setup Completed Successfully!",
            "Next Steps:",
            "nano /home/matt/PosterPulse/.env",
            "/home/matt/.config/autostart/posterpulse.desktop",
            "tail -f /home/matt/.local/state/posterpulse/regular.log",
            "log out and back in",
        ):
            self.assertIn(text, result.stdout)
        self.assertNotIn("sudo systemctl", result.stdout)
        self.assertNotIn("sudo reboot", result.stdout)

    def test_remote_summary_has_lcd_log_command_and_custom_port(self):
        result, _ = LcdSetupSshTests().run_deployment()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ssh -p 2222 matt@example.test", result.stdout)
        self.assertIn("tail -f ~/.local/state/posterpulse/regular.log", result.stdout)
        self.assertNotIn("journalctl", result.stdout)


class LcdSetupLaunchTests(unittest.TestCase):
    def run_launcher(self, app, blocked_log=False):
        source = SCRIPT.read_text()
        start = source.index('    runuser -u "$CURRENT_USER" -- sh -c')
        end_marker = (
            '    echo "Started PosterPulse in the current graphical session. '
            'Log: ${LOG_FILE}"'
        )
        end = source.index(end_marker, start) + len(end_marker)
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
            python.write_text('#!/bin/sh\nprintf "%s" "$$" > "$PID_FILE"\n' + app)
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
                    check=False,
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
