"""Keep ordered, confirmed teardown when supplying deployment variables."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("terraform_gcp", SCRIPTS / "terraform-gcp.py")
terraform = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    SPEC.loader.exec_module(terraform)


class DestroyTests(unittest.TestCase):
    def execute(self, extra, confirmation="destroy"):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="oauth-token")

        with (
            patch.object(sys, "argv", ["terraform-gcp.py", "destroy", *extra]),
            patch.object(terraform.subprocess, "run", side_effect=run),
            patch.object(terraform, "inspect_plan"),
            patch.object(terraform, "backup_state"),
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
        delete = next(i for i, command in enumerate(calls) if "delete-service" in command)
        apply = next(i for i, command in enumerate(calls) if "apply" in command)
        self.assertLess(delete, apply)

    def test_declined_confirmation_deletes_nothing(self):
        status, calls = self.execute([], confirmation="no")
        self.assertEqual(status, 1)
        self.assertFalse(any("delete-service" in command or "apply" in command for command in calls))

    def test_destroy_rejects_approval_bypass_and_targeting(self):
        for argument in ("-auto-approve", "-target=google_storage_bucket.photos", "-var-file="):
            with self.subTest(argument=argument):
                status, calls = self.execute([argument])
                self.assertEqual(status, 1)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
