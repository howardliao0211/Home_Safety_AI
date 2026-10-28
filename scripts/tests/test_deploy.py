"""Deployment stage ordering and failure boundaries; no cloud calls."""

import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "guided_deploy", Path(__file__).resolve().parents[1] / "deploy.py"
)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(
            account="operator@example.com",
            model="muse-test",
            start_expo=False,
        )
        self.deployment = deploy.Deployment(self.args)

    def test_finish_checks_readiness_before_any_changes(self):
        with (
            patch.object(
                deploy,
                "run",
                side_effect=[
                    "https://service.run.app",
                    subprocess.CalledProcessError(1, ["verify"]),
                ],
            ),
            patch.object(self.deployment, "save_variables") as save,
            patch.object(self.deployment, "apply") as apply,
            patch.object(self.deployment, "release") as release,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                self.deployment.finish()
            save.assert_not_called()
            apply.assert_not_called()
            release.assert_not_called()

    def test_finish_applies_recovery_before_release_and_phone_configuration(self):
        events = []

        def run(command, **kwargs):
            events.append(command)
            if command[-1] == "service-url":
                return "https://service.run.app\n"

        with (
            patch.object(deploy, "run", side_effect=run),
            patch.object(
                self.deployment,
                "save_variables",
                side_effect=lambda **values: events.append(values),
            ),
            patch.object(self.deployment, "apply", side_effect=lambda: events.append("apply")),
        ):
            self.deployment.finish()
        self.assertEqual(events[0][-1], "service-url")
        self.assertEqual(events[1][-1], "verify")
        self.assertEqual(events[2]["annotation_worker_url"], "https://service.run.app")
        self.assertEqual(events[3], "apply")
        self.assertEqual(events[4][-2:], ["--segmentation-model", "sam-3.1"])
        self.assertEqual(events[5][-1], "verify")
        self.assertEqual(events[6][-1], "phone-env")
        self.assertIn("--account=operator@example.com", events[4])

    def test_repeated_bootstrap_preserves_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "deploy/terraform/terraform.tfstate"
            state.parent.mkdir(parents=True)
            state.write_text(
                json.dumps(
                    {
                        "resources": [{"type": "google_cloud_tasks_queue"}],
                        "outputs": {"deployment_config": {"value": {}}},
                    }
                )
            )
            with (
                patch.object(deploy, "ROOT", root),
                patch.object(
                    self.deployment,
                    "output",
                    return_value={
                        "annotation_worker_url": "https://service.run.app",
                    },
                ),
                patch.object(self.deployment, "save_variables") as save,
                patch.object(self.deployment, "apply"),
                patch.object(self.deployment, "release") as release,
                patch.object(deploy, "run") as run,
            ):
                self.deployment.bootstrap()
                self.assertEqual(
                    save.call_args_list[0].kwargs,
                    {
                        "annotation_worker_url": "https://service.run.app",
                    },
                )
                release.assert_called_once_with(highlights=True)
                self.assertEqual(run.call_args.args[0][-1], "phone-env")

    def test_bootstrap_recovers_state_without_deployment_config_output(self):
        for saved_url in ("", "https://service.run.app"):
            with self.subTest(saved_url=saved_url), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "deploy/terraform/terraform.tfstate"
                state.parent.mkdir(parents=True)
                state.write_text(
                    json.dumps(
                        {
                            "resources": [{"type": "google_storage_bucket"}],
                            "outputs": {"project_id": {"value": "home-safety-ai"}},
                        }
                    )
                )
                variables = state.parent / "deploy.tfvars.json"
                variables.write_text(json.dumps({"annotation_worker_url": saved_url}))
                with (
                    patch.object(deploy, "ROOT", root),
                    patch.object(deploy, "VARIABLES", variables),
                    patch.object(
                        self.deployment,
                        "output",
                        return_value={
                            "project_id": "home-safety-ai",
                            "service_name": "home-safety-demo",
                            "region": "us-central1",
                        },
                    ),
                    patch.object(self.deployment, "save_variables") as save,
                    patch.object(self.deployment, "apply") as apply,
                    patch.object(self.deployment, "release") as release,
                    patch.object(deploy, "run", return_value="123456"),
                ):
                    self.deployment.bootstrap()
                self.assertEqual(
                    save.call_args_list[0].kwargs,
                    {
                        "annotation_worker_url": saved_url,
                    },
                )
                self.assertEqual(apply.call_count, 1 if saved_url else 2)
                release.assert_called_once_with(highlights=True)

    def test_private_variables_preserve_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deploy.tfvars.json"
            path.write_text(json.dumps({"project_id": "custom-project"}))
            with patch.object(deploy, "VARIABLES", path):
                self.deployment.save_variables(annotation_worker_url="https://service.run.app")
            self.assertEqual(
                json.loads(path.read_text()),
                {
                    "project_id": "custom-project",
                    "annotation_worker_url": "https://service.run.app",
                },
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_finish_rejects_invalid_service_url_before_changes(self):
        with (
            patch.object(deploy, "run", return_value="http://unexpected.example"),
            patch.object(self.deployment, "save_variables") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "valid HTTPS service URL"):
                self.deployment.finish()
            save.assert_not_called()

    def test_start_runs_all_stages_again(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []

            def run(command, **kwargs):
                if kwargs.get("capture"):
                    return json.dumps({"model": "muse-test", "has_key": True})
                events.append(command[-1])

            with (
                patch.object(deploy, "ROOT", Path(directory)),
                patch("sys.argv", ["deploy.py", "start"]),
                patch.object(deploy.shutil, "which", return_value="installed"),
                patch.object(deploy, "run", side_effect=run),
                patch.object(
                    deploy.Deployment, "bootstrap", side_effect=lambda: events.append("bootstrap")
                ),
                patch.object(
                    deploy.Deployment, "finish", side_effect=lambda: events.append("finish")
                ),
            ):
                self.assertEqual(deploy.main(), 0)
                self.assertEqual(deploy.main(), 0)
            self.assertEqual(events.count("bootstrap"), 2)
            self.assertEqual(events.count("finish"), 2)
            self.assertEqual(events[-2:], ["bootstrap", "finish"])

    def test_stop_passes_managed_variables_to_guarded_destroy(self):
        with (
            patch.object(deploy, "run") as run,
            patch.object(Path, "exists", return_value=True),
        ):
            self.deployment.stop()
        self.assertEqual(
            run.call_args.args[0],
            [
                *self.deployment.terraform,
                "destroy",
                f"-var-file={deploy.VARIABLES}",
            ],
        )

    def test_stop_needs_no_docker_model_or_image_build(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            prerequisites = []
            with (
                patch.object(deploy, "ROOT", Path(directory)),
                patch("sys.argv", ["deploy.py", "stop"]),
                patch.object(
                    deploy.shutil,
                    "which",
                    side_effect=lambda name: prerequisites.append(name) or name,
                ),
                patch.object(deploy, "run", side_effect=lambda command: commands.append(command)),
                patch.object(deploy.Deployment, "stop") as stop,
            ):
                self.assertEqual(deploy.main(), 0)
            stop.assert_called_once()
            self.assertNotIn("docker", prerequisites)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][:2], ["uv", "sync"])

    def test_bootstrap_can_restart_after_destroy_emptied_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "deploy/terraform/terraform.tfstate"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"resources": []}))
            with (
                patch.object(deploy, "ROOT", root),
                patch.object(
                    self.deployment,
                    "output",
                    return_value={
                        "project_id": "home-safety-ai",
                        "service_name": "home-safety-demo",
                        "region": "us-central1",
                    },
                ) as output,
                patch.object(self.deployment, "save_variables"),
                patch.object(self.deployment, "apply"),
                patch.object(self.deployment, "release") as release,
                patch.object(deploy, "run", return_value="123456"),
            ):
                self.deployment.bootstrap()
                output.assert_called_once_with("deployment_config")
                release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
