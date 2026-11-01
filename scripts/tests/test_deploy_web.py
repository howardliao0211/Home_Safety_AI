"""Browser deployment boundaries; no cloud calls or paid model requests."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

SPEC = importlib.util.spec_from_file_location(
    "deploy_web", Path(__file__).resolve().parents[1] / "deploy-web.py"
)
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class WebDeploymentTests(unittest.TestCase):
    def test_build_excludes_emulators_and_unapproved_public_config(self):
        settings = {
            "EXPO_PUBLIC_FIREBASE_API_KEY": "cloud-public-key",
            "EXPO_PUBLIC_FIREBASE_APP_ID": "cloud-app",
            "EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN": "example.firebaseapp.com",
            "EXPO_PUBLIC_AUTH_EMULATOR_URL": "http://localhost:9099",
        }
        with patch.dict(os.environ, {"EXPO_PUBLIC_AUTH_EMULATOR_URL": "http://localhost:9099",
                                    "EXPO_PUBLIC_PREVIEW_SCENARIO": "failure"}):
            env = web.build_environment(settings, "example", "https://api.run.app/")
        self.assertNotIn("EXPO_PUBLIC_AUTH_EMULATOR_URL", env)
        self.assertNotIn("EXPO_PUBLIC_PREVIEW_SCENARIO", env)
        self.assertEqual(env["EXPO_NO_DOTENV"], "1")
        self.assertEqual(env["EXPO_PUBLIC_DATA_SOURCE"], "api")
        self.assertEqual(env["EXPO_PUBLIC_API_URL"], "https://api.run.app")

    def test_missing_cloud_key_fails_before_export(self):
        with self.assertRaisesRegex(ValueError, "API_KEY"):
            web.build_environment({}, "example", "https://api.run.app")

    def test_invalid_api_origins_are_rejected(self):
        for value in ("http://localhost:8000", "https://api.run.app/path",
                      "https://user:password@api.run.app", "https://api.run.app?key=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                web.https_origin(value)

    def test_preflight_must_allow_the_exact_origin(self):
        def response(request):
            self.assertEqual(request.method, "OPTIONS")
            self.assertEqual(request.headers["access-control-request-headers"], "authorization,content-type")
            return httpx.Response(200, headers={"access-control-allow-origin": "https://other.web.app"})
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            with self.assertRaisesRegex(ValueError, "did not allow"):
                web.check_cors(client, "https://api.run.app", "https://demo.web.app")

    def test_preflight_waits_for_route_propagation(self):
        replies = iter([
            httpx.Response(400, text="Disallowed CORS origin"),
            httpx.Response(200, headers={"access-control-allow-origin": "https://demo.web.app"}),
        ])
        with (
            httpx.Client(transport=httpx.MockTransport(lambda request: next(replies))) as client,
            patch.object(web.time, "sleep") as sleep,
        ):
            web.check_cors(client, "https://api.run.app", "https://demo.web.app")
        sleep.assert_called_once_with(2)

    def test_rejected_preflight_explains_the_origin(self):
        with (
            httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(400, text="Disallowed CORS origin"),
            )) as client,
            patch.object(web.time, "sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "preflight rejected https://demo.web.app"):
                web.check_cors(client, "https://api.run.app", "https://demo.web.app")

    def test_cloud_update_preserves_domains_origins_and_only_changes_cors(self):
        from argparse import Namespace
        args = Namespace(project="example", site="demo", service="backend", region="region", account=None)
        service = {"status": {"latestReadyRevisionName": "rev", "traffic": [
            {"revisionName": "rev", "percent": 100},
        ]}, "spec": {"template": {"spec": {"containers": [{"env": [
            {"name": "GOOGLE_CLOUD_PROJECT", "value": "example"},
            {"name": "CORS_ORIGINS", "value": '["https://existing.web.app"]'},
        ]}]}}}}
        requests = []
        def response(request):
            requests.append(request)
            if request.method == "GET" and request.url.path.endswith("/config"):
                return httpx.Response(200, json={"authorizedDomains": ["existing.web.app"]})
            return httpx.Response(200, json={})
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(web, "ROOT", Path(directory)),
            patch.object(web, "run", return_value="private-token"),
            patch.object(web, "cloud_json", side_effect=[
                {"status": {"latestReadyRevisionName": "rev", "latestCreatedRevisionName": "new"}},
                {"spec": {"containers": [{"env": [{"name": "CORS_ORIGINS", "value":
                    '["https://existing.web.app","https://local.web.app","https://demo.web.app"]'}]}]}},
                {},
            ]) as cloud,
            httpx.Client(transport=httpx.MockTransport(response)) as client,
        ):
            web.configure_cloud(args, client, service, {"CORS_ORIGINS": '["https://local.web.app"]'}, ["demo.web.app"])
            saved = web.dotenv_values(Path(directory) / ".env")
            self.assertEqual(json.loads(saved["CORS_ORIGINS"]), [
                "https://existing.web.app", "https://local.web.app", "https://demo.web.app",
            ])
            command = cloud.call_args_list[0].args
            self.assertIn('--update-env-vars=^|^CORS_ORIGINS=' + saved["CORS_ORIGINS"], command)
            self.assertFalse(any("--set-env-vars" in str(item) for item in command))
            self.assertEqual(cloud.call_args_list[1].args[1:4], ("run", "revisions", "describe"))
            self.assertIn("new", cloud.call_args_list[1].args)
            self.assertIn("--to-revisions=new=100", cloud.call_args_list[2].args)
        auth_patch = next(item for item in requests if item.method == "PATCH")
        self.assertEqual(json.loads(auth_patch.content)["authorizedDomains"], ["existing.web.app", "demo.web.app"])

    def test_split_traffic_is_rejected_before_any_mutation(self):
        service = {"status": {"traffic": [{"percent": 50}, {"percent": 50}]}}
        with self.assertRaisesRegex(ValueError, "pending/split"), patch.object(web, "run") as run:
            web.configure_cloud(None, None, service, {}, [])
        run.assert_not_called()

    def test_rerun_activates_saved_cors_when_serving_revision_is_old(self):
        from argparse import Namespace
        args = Namespace(project="example", site="demo", service="backend", region="region", account=None)
        env = [{"name": "GOOGLE_CLOUD_PROJECT", "value": "example"},
               {"name": "CORS_ORIGINS", "value": '["https://demo.web.app"]'}]
        service = {"status": {"latestReadyRevisionName": "old", "latestCreatedRevisionName": "new",
                              "traffic": [{"revisionName": "old", "percent": 100}]},
                   "spec": {"template": {"spec": {"containers": [{"env": env}]}}}}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(web, "ROOT", Path(directory)),
            patch.object(web, "run", return_value="private-token"),
            patch.object(web, "cloud_json", side_effect=[
                {"spec": {"containers": [{"env": []}]}},
                {"spec": {"containers": [{"env": env}]}},
                {},
            ]) as cloud,
            httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"authorizedDomains": ["demo.web.app"]}),
            )) as client,
        ):
            web.configure_cloud(args, client, service, {}, ["demo.web.app"])
        self.assertIn("old", cloud.call_args_list[0].args)
        self.assertIn("new", cloud.call_args_list[1].args)
        self.assertIn("--to-revisions=new=100", cloud.call_args_list[2].args)
        self.assertFalse(any(call.args[1:4] == ("run", "services", "update") for call in cloud.call_args_list))

    def test_build_only_never_contacts_cloud_or_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mobile").mkdir()
            (root / "mobile/eas.json").write_text(json.dumps({"build": {"preview": {"env": {
                "EXPO_PUBLIC_FIREBASE_PROJECT_ID": "example",
                "EXPO_PUBLIC_FIREBASE_API_KEY": "cloud-public-key",
                "EXPO_PUBLIC_FIREBASE_APP_ID": "cloud-app",
                "EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN": "example.firebaseapp.com",
                "EXPO_PUBLIC_API_URL": "https://api.run.app",
            }}}}))
            with (
                patch.object(web, "ROOT", root),
                patch.object(web, "OUTPUT", root / "output"),
                patch.object(web.sys, "argv", ["deploy-web.py", "--build-only"]),
                patch.dict(os.environ, {}, clear=True),
                patch.object(web.shutil, "which", return_value="node"),
                patch.object(web, "run") as run,
                patch.object(web, "cloud_json") as cloud,
                patch.object(web, "configure_cloud") as configure,
            ):
                web.main()
            cloud.assert_not_called()
            configure.assert_not_called()
            self.assertEqual(run.call_count, 1)
            self.assertIn("export", run.call_args.args[0])
            config = json.loads((root / "output/firebase.json").read_text())
            self.assertEqual(config["hosting"]["rewrites"][0]["destination"], "/index.html")
            self.assertEqual(config["hosting"]["headers"][0], {
                "source": "**", "headers": [{"key": "Cache-Control", "value": "no-cache"}],
            })


if __name__ == "__main__":
    unittest.main()
