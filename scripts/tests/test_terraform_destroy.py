"""Keep ordered, confirmed teardown when supplying deployment variables."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("terraform_gcp", SCRIPTS / "terraform-gcp.py")
terraform = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    SPEC.loader.exec_module(terraform)


class DestroyTests(unittest.TestCase):
    def execute(
        self,
        extra,
        confirmation="destroy",
        changes=None,
        service="home-safety-demo",
        fail_delete=False,
        replanned_changes=None,
        command="destroy",
    ):
        calls = []

        plan = {
            "variables": {
                "project_id": {"value": "partial-project"},
                "region": {"value": "australia-southeast1"},
            },
            "resource_changes": changes or [],
        }

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == "gcloud" and command[1:4] == ["run", "services", "list"]:
                return subprocess.CompletedProcess(command, 0, stdout=service)
            if command[0] == "gcloud" and "delete" in command and fail_delete:
                raise subprocess.CalledProcessError(1, command)
            if "show" in command and "-json" in command:
                current = plan
                if replanned_changes is not None and sum("plan" in c for c in calls) > 1:
                    current = {**plan, "resource_changes": replanned_changes}
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(current))
            return subprocess.CompletedProcess(command, 0, stdout="oauth-token")

        with (
            patch.object(sys, "argv", ["terraform-gcp.py", command, *extra]),
            patch.object(terraform.subprocess, "run", side_effect=run),
            patch.object(terraform, "backup_state"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(terraform, "require_current_image") as image,
            patch("builtins.input", return_value=confirmation),
        ):
            status = terraform.main()
            image.assert_not_called()
        return status, calls

    def test_destroy_uses_variables_and_removes_service_before_infrastructure(self):
        status, calls = self.execute(["-var-file=/private/deploy.tfvars.json"])
        self.assertEqual(status, 0)
        plan = next(command for command in calls if "plan" in command)
        self.assertIn("-var-file=/private/deploy.tfvars.json", plan)
        delete = next(i for i, command in enumerate(calls) if "delete" in command)
        apply = next(i for i, command in enumerate(calls) if "apply" in command)
        self.assertLess(delete, apply)
        self.assertIn("--project=partial-project", calls[delete])
        self.assertIn("--region=australia-southeast1", calls[delete])
        self.assertFalse(any("output" in c or "delete-service" in c for c in calls))

    def test_already_absent_service_does_not_block_destroy(self):
        status, calls = self.execute([], service="")
        self.assertEqual(status, 0)
        self.assertFalse(any("delete" in c for c in calls))
        self.assertTrue(any("apply" in c for c in calls))

    def test_failed_service_deletion_does_not_destroy_dependencies(self):
        status, calls = self.execute([], fail_delete=True)
        self.assertEqual(status, 1)
        self.assertFalse(any("apply" in c for c in calls))

    def test_whole_database_teardown_skips_field_reset_and_replans(self):
        database = "projects/partial-project/databases/(default)"

        def change(address, kind, attributes):
            return {
                "address": address,
                "type": kind,
                "change": {"actions": ["delete"], "before": attributes},
            }

        changes = [
            change(
                "google_firestore_database.assessments",
                "google_firestore_database",
                {"id": database},
            ),
            change(
                "google_firestore_field.annotation_dispatch",
                "google_firestore_field",
                {"id": database + "/collectionGroups/assessments/fields/pending"},
            ),
        ]
        status, calls = self.execute([], changes=changes)
        self.assertEqual(status, 0)
        detach = next(i for i, c in enumerate(calls) if "rm" in c)
        self.assertIn("google_firestore_field.annotation_dispatch", calls[detach])
        replans = [i for i, c in enumerate(calls) if "plan" in c]
        self.assertEqual(len(replans), 2)
        self.assertLess(detach, replans[-1])

    def test_missing_state_refuses_destroy(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(terraform, "DIRECTORY", Path(directory)),
            patch.object(sys, "argv", ["terraform-gcp.py", "destroy"]),
            patch.object(terraform.subprocess, "run") as run,
        ):
            self.assertEqual(terraform.main(), 1)
            run.assert_not_called()

    def test_field_reset_is_skipped_only_when_its_database_is_being_deleted(self):
        field = {
            "address": "google_firestore_field.field",
            "type": "google_firestore_field",
            "change": {
                "actions": ["delete"],
                "before": {"id": "projects/p/databases/keep/collectionGroups/c/fields/f"},
            },
        }
        status, calls = self.execute([], changes=[field])
        self.assertEqual(status, 0)
        self.assertFalse(any("rm" in c for c in calls))

    def test_replanned_teardown_cannot_introduce_unreviewed_deletions(self):
        database = "projects/p/databases/(default)"
        changes = [
            {
                "address": "google_firestore_database.db",
                "type": "google_firestore_database",
                "change": {"actions": ["delete"], "before": {"id": database}},
            },
            {
                "address": "google_firestore_field.field",
                "type": "google_firestore_field",
                "change": {
                    "actions": ["delete"],
                    "before": {"id": database + "/collectionGroups/c/fields/f"},
                },
            },
        ]
        updated = [
            {
                "address": "google_storage_bucket.unreviewed",
                "type": "google_storage_bucket",
                "change": {"actions": ["delete"], "before": {"id": "unreviewed"}},
            }
        ]
        status, calls = self.execute([], changes=changes, replanned_changes=updated)
        self.assertEqual(status, 1)
        self.assertFalse(any("apply" in c for c in calls))

    def test_declined_confirmation_deletes_nothing(self):
        status, calls = self.execute([], confirmation="no")
        self.assertEqual(status, 1)
        self.assertFalse(
            any("delete-service" in command or "apply" in command for command in calls)
        )

    def test_destroy_rejects_approval_bypass_and_targeting(self):
        for argument in (
            "-auto-approve",
            "-target=google_storage_bucket.photos",
            "-var-file=",
        ):
            with self.subTest(argument=argument):
                status, calls = self.execute([argument])
                self.assertEqual(status, 1)
                self.assertEqual(calls, [])


class RegionTeardownTests(DestroyTests):
    def regional(self, address, before=None):
        kind, name = address.split(".")
        return {
            "address": address,
            "type": kind,
            "change": {"actions": ["delete"], "before": before or {"id": name}},
        }

    def test_region_teardown_targets_only_regional_resources_in_order(self):
        changes = [
            self.regional("google_cloud_tasks_queue.annotations", {"id": "q", "name": "q1"}),
            self.regional("google_cloud_scheduler_job.annotation_recovery[0]", {"name": "job"}),
            self.regional("google_storage_bucket.photos"),
        ]
        status, calls = self.execute(
            ["-var-file=/private/deploy.tfvars.json"],
            confirmation="rebuild",
            changes=changes,
            command="region-teardown",
        )
        self.assertEqual(status, 0)
        plan = next(c for c in calls if "plan" in c)
        self.assertIn("-target=google_storage_bucket.photos", plan)
        self.assertFalse(any("secret" in a or "identity" in a for a in plan))
        order = [
            next(i for i, c in enumerate(calls) if c[:3] == ["gcloud", "tasks", "queues"]),
            next(i for i, c in enumerate(calls) if c[:3] == ["gcloud", "scheduler", "jobs"]),
            next(i for i, c in enumerate(calls) if c[:4] == ["gcloud", "run", "services", "delete"]),
            next(i for i, c in enumerate(calls) if "apply" in c),
        ]
        self.assertEqual(order, sorted(order))
        self.assertIn("--region=australia-southeast1", calls[order[2]])

    def test_region_teardown_refuses_plans_that_touch_shared_resources(self):
        for address in (
            "google_secret_manager_secret.backend",
            "google_identity_platform_config.accounts",
            "google_service_account.backend",
        ):
            with self.subTest(address=address):
                status, calls = self.execute(
                    [],
                    confirmation="rebuild",
                    changes=[self.regional(address)],
                    command="region-teardown",
                )
                self.assertEqual(status, 1)
                self.assertFalse(any("apply" in c or "delete" in c for c in calls))

    def test_region_teardown_requires_its_own_confirmation(self):
        status, calls = self.execute(
            [], confirmation="destroy", changes=[], command="region-teardown"
        )
        self.assertEqual(status, 1)
        self.assertFalse(any("apply" in c for c in calls))


if __name__ == "__main__":
    unittest.main()
