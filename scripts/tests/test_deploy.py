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
                        "resources": [
                            {
                                "type": "google_cloud_tasks_queue",
                                "instances": [{"attributes": {"name": "existing-queue"}}],
                            }
                        ],
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
                        "adopt_existing_identity_config": True,
                    },
                )
                release.assert_called_once_with(highlights=True)
                self.assertEqual(
                    save.call_args_list[1].kwargs, {"annotation_queue_name": "existing-queue"}
                )
                self.assertEqual(run.call_args.args[0][-1], "phone-env")

    def test_bootstrap_recovers_state_without_deployment_config_output(self):
        for saved_url in ("", "https://service.run.app"):
            with (
                self.subTest(saved_url=saved_url),
                tempfile.TemporaryDirectory() as directory,
            ):
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
                        "adopt_existing_identity_config": True,
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
                    deploy.Deployment,
                    "bootstrap",
                    side_effect=lambda: events.append("bootstrap"),
                ),
                patch.object(
                    deploy.Deployment,
                    "finish",
                    side_effect=lambda: events.append("finish"),
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
            patch.object(Path, "is_file", return_value=True),
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
        self.assertEqual(run.call_args_list[0].args[0][-1], "init")

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
            self.assertNotIn("uv", prerequisites)
            self.assertEqual(commands, [])

    def test_bootstrap_chooses_new_queue_after_destroy(self):
        names = []
        databases = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "deploy/terraform/terraform.tfstate"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"resources": []}))
            variables = state.parent / "deploy.tfvars.json"
            variables.write_text(
                json.dumps({"annotation_queue_name": "home-safety-annotations-old"})
            )
            with (
                patch.object(deploy, "ROOT", root),
                patch.object(deploy, "VARIABLES", variables),
                patch.object(
                    self.deployment,
                    "output",
                    return_value={
                        "project_id": "test",
                        "service_name": "test",
                        "region": "us-central1",
                    },
                ),
                patch.object(self.deployment, "apply"),
                patch.object(self.deployment, "release"),
                patch.object(deploy, "run", return_value="1234"),
            ):
                for _ in range(2):
                    self.deployment.bootstrap()
                    names.append(json.loads(variables.read_text())["annotation_queue_name"])
                    databases.append(json.loads(variables.read_text())["firestore_database_id"])
        self.assertNotEqual(names[0], "home-safety-annotations-old")
        self.assertNotEqual(names[0], names[1])
        self.assertNotEqual(databases[0], databases[1])

    def test_bootstrap_preserves_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "deploy/terraform/terraform.tfstate"
            state.parent.mkdir(parents=True)
            state.write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "type": "google_firestore_database",
                                "instances": [
                                    {
                                        "attributes": {
                                            "name": "existing-db",
                                            "id": "projects/p/databases/existing-db",
                                        }
                                    }
                                ],
                            }
                        ],
                        "outputs": {"deployment_config": {}},
                    }
                )
            )
            with (
                patch.object(deploy, "ROOT", root),
                patch.object(
                    self.deployment,
                    "output",
                    return_value={"annotation_worker_url": "https://service.run.app"},
                ),
                patch.object(self.deployment, "save_variables") as save,
                patch.object(self.deployment, "apply"),
                patch.object(self.deployment, "release"),
                patch.object(deploy, "run"),
            ):
                self.deployment.bootstrap()
            self.assertIn(
                {"firestore_database_id": "existing-db"}, [c.kwargs for c in save.call_args_list]
            )

    def test_start_preflights_auth_before_build_or_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if kwargs.get("capture"):
                    return json.dumps({"model": "muse-test", "has_key": True})
                if command[-1] == "preflight":
                    raise subprocess.CalledProcessError(1, command)

            with (
                patch.object(deploy, "ROOT", Path(directory)),
                patch("sys.argv", ["deploy.py", "start"]),
                patch.object(deploy.shutil, "which", return_value="installed"),
                patch.object(deploy, "run", side_effect=run),
                patch.object(deploy.Deployment, "bootstrap") as bootstrap,
            ):
                self.assertEqual(deploy.main(), 1)
                bootstrap.assert_not_called()
            self.assertTrue(any(c[-1] == "preflight" for c in commands))
            self.assertFalse(any(c[-1] in {"build", "init", "validate"} for c in commands))

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


class RegionTests(unittest.TestCase):
    def deployment(self, root, region=None, saved=None, state_region=None):
        terraform = root / "deploy/terraform"
        terraform.mkdir(parents=True, exist_ok=True)
        (terraform / "variables.tf").write_text(
            'variable "region" {\n  type    = string\n  default = "australia-southeast1"\n}\n'
        )
        if saved:
            (terraform / "deploy.tfvars.json").write_text(json.dumps({"region": saved}))
        if state_region:
            (terraform / "terraform.tfstate").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "type": "google_firestore_database",
                                "instances": [
                                    {"attributes": {"location_id": state_region, "project": "p"}}
                                ],
                            }
                        ]
                    }
                )
            )
        args = argparse.Namespace(account=None, model="m", start_expo=False, region=region)
        return deploy.Deployment(args)

    def run_in(self, root, action):
        with (
            patch.object(deploy, "ROOT", root),
            patch.object(deploy, "VARIABLES", root / "deploy/terraform/deploy.tfvars.json"),
        ):
            return action()

    def test_explicit_region_wins_over_saved_inputs_then_default(self):
        cases = [
            ("us-central1", "europe-west1", "us-central1"),
            (None, "us-central1", "us-central1"),
            (None, None, "australia-southeast1"),
        ]
        for explicit, saved, expected in cases:
            with self.subTest(explicit=explicit, saved=saved), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                deployment = self.deployment(root, explicit, saved)
                self.assertEqual(self.run_in(root, deployment.resolve_region), expected)

    def test_start_never_moves_an_existing_deployment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            deployment = self.deployment(root, state_region="us-central1")
            self.run_in(root, deployment.resolve_region)  # Default is now Sydney.
            with self.assertRaisesRegex(RuntimeError, "deploy rebuild --region"):
                self.run_in(root, deployment.check_region)
            same = self.deployment(root, region="us-central1", state_region="us-central1")
            self.run_in(root, same.resolve_region)
            self.run_in(root, same.check_region)

    def test_bootstrap_never_reuses_another_regions_worker_url(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            deployment = self.deployment(root, region="australia-southeast1")
            state = root / "deploy/terraform/terraform.tfstate"
            state.write_text(
                json.dumps(
                    {
                        "resources": [{"type": "google_service_account", "instances": [{}]}],
                        "outputs": {"deployment_config": {"value": {}}},
                    }
                )
            )
            us = {"region": "us-central1", "annotation_worker_url": "https://us.run.app"}
            with (
                patch.object(
                    deployment,
                    "output",
                    side_effect=[
                        us,
                        {
                            "project_id": "p",
                            "region": "australia-southeast1",
                            "service_name": "home-safety-demo",
                        },
                    ],
                ),
                patch.object(deployment, "save_variables") as save,
                patch.object(deployment, "apply"),
                patch.object(deployment, "release"),
                patch.object(deploy, "run", return_value="123"),
            ):
                self.run_in(root, deployment.resolve_region)
                self.run_in(root, deployment.bootstrap)
            first = save.call_args_list[0].kwargs
            self.assertEqual(first["annotation_worker_url"], "")
            self.assertEqual(first["region"], "australia-southeast1")
            # The provisional origin is derived from the Sydney service identity.
            self.assertEqual(
                save.call_args_list[-1].kwargs["annotation_worker_url"],
                "https://home-safety-demo-123.australia-southeast1.run.app",
            )

    def test_mixed_region_state_requires_finishing_the_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.deployment(root, state_region="us-central1")
            state = root / "deploy/terraform/terraform.tfstate"
            data = json.loads(state.read_text())
            data["resources"].append(
                {
                    "type": "google_cloud_tasks_queue",
                    "instances": [{"attributes": {"location": "australia-southeast1"}}],
                }
            )
            state.write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError, "rebuild"):
                self.run_in(root, deploy.deployed_region)


if __name__ == "__main__":
    unittest.main()
