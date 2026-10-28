import importlib.util
import json
import subprocess
import sys

import httpx
import pytest
from conftest import MemoryPhotos, MemoryRepository, StubProvider
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app

spec = importlib.util.spec_from_file_location("deploy_gcp", ROOT / "scripts/deploy-gcp.py")
deploy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = deploy
spec.loader.exec_module(deploy)


@pytest.fixture
def config():
    return deploy.Config(
        project_id="test-project",
        region="us-central1",
        service_name="test-service",
        repository="us-central1-docker.pkg.dev/test-project/home-safety",
        service_account="runtime@test-project.iam.gserviceaccount.com",
        photos_bucket="test-photos",
        database_id="(default)",
        groq_secret="groq-secret",
        annotation_worker_url="https://test.run.app",
        annotation_tasks_queue="projects/test-project/locations/us-central1/queues/highlights",
    )


@pytest.fixture
def production(settings):
    return Settings(
        _env_file=None,
        environment="production",
        groq_api_key="fake-key",
        groq_model="fake-model",
        annotation_worker_url="https://test.run.app",
        annotation_worker_service_account="worker@test",
        annotation_tasks_queue="queue",
    )


def test_production_disables_docs_and_enforces_api_auth(production):
    with TestClient(
        create_app(production, MemoryRepository(), MemoryPhotos(), StubProvider())
    ) as client:
        assert client.get("/health").status_code == 200
        assert (
            client.get(
                "/v1/assessments/latest", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        client.headers["Authorization"] = "Bearer fake-demo-token"
        assert client.get("/health").json() == {"status": "ok"}
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert client.get(path).status_code == 404


def test_release_verifier_exercises_real_auth_upload_scoping_and_cleanup(production, monkeypatch):
    repository, photos, provider = MemoryRepository(), MemoryPhotos(), StubProvider()
    real_client = httpx.Client
    with TestClient(create_app(production, repository, photos, provider)) as api:

        def forward(request):
            response = api.request(
                request.method,
                request.url.raw_path.decode(),
                headers=request.headers,
                content=request.content,
            )
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers=response.headers,
                request=request,
            )

        monkeypatch.setattr(
            deploy.httpx,
            "Client",
            lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(forward)),
        )
        deploy.Deployer.verify_url(
            "https://candidate---service.run.app", "11111111-1111-4111-8111-111111111111"
        )
    assert repository.records == {} and photos.objects == {} and provider.calls == []


class FakeRelease(deploy.Deployer):
    def __init__(self, config, fail_at=None):
        super().__init__(config)
        self.commands = []
        self.checks = []
        self.fail_at = fail_at

    def smoke_token(self):
        return "test-user-token"

    def latest_version(self, secret, **kwargs):
        return "3" if secret == self.config.groq_secret else "7"

    def secret_value(self, secret, version):
        return "fake-private-token"

    def describe(self, **kwargs):
        return {
            "status": {
                "url": "https://service.run.app",
                "traffic": [{"revisionName": "old", "percent": 100}],
            }
        }

    def gcloud(self, *args, **kwargs):
        self.commands.append(args)
        if args[:2] == ("run", "deploy"):
            tag = next(a.split("=", 1)[1] for a in args if a.startswith("--tag="))
            return json.dumps(
                {
                    "status": {
                        "traffic": [
                            {"tag": tag, "url": "https://candidate.run.app", "revisionName": "new"}
                        ]
                    }
                }
            )
        return ""

    def verify_url(self, url, token):
        self.checks.append(url)
        if url == self.fail_at:
            raise deploy.DeploymentError("Injected health failure")


def test_candidate_failure_does_not_promote_or_expose_secrets(config):
    runner = FakeRelease(config, fail_at="https://candidate.run.app")
    with pytest.raises(deploy.DeploymentError, match="Injected health failure"):
        runner.release(model="qwen/test", image=config.repository + "/backend@sha256:" + "a" * 64)
    assert len(runner.commands) == 1
    command = runner.commands[0]
    assert "--no-traffic" in command
    assert "fake-private-token" not in " ".join(command)
    assert "--set-secrets=GROQ_API_KEY=groq-secret:3" in command
    env = next(arg for arg in command if arg.startswith("--set-env-vars="))
    assert "ENVIRONMENT=production" in env and "EMULATOR" not in env


def test_failure_after_promotion_restores_old_revision(config):
    runner = FakeRelease(config, fail_at="https://service.run.app")
    with pytest.raises(deploy.DeploymentError):
        runner.release(model="qwen/test", image=config.repository + "/backend@sha256:" + "a" * 64)
    promotions = [
        a for command in runner.commands for a in command if a.startswith("--to-revisions=")
    ]
    assert promotions == ["--to-revisions=new=100", "--to-revisions=old=100"]


def test_secret_values_use_stdin_and_existing_demo_token_is_reused(
    config, tmp_path, monkeypatch, capsys
):
    file = tmp_path / ".env"
    file.write_text("GROQ_API_KEY=fake-groq-secret\n")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs.get("input")))
        if "add" in command:
            return subprocess.CompletedProcess(
                command, 0, "projects/test/secrets/groq/versions/4", ""
            )
        return subprocess.CompletedProcess(command, 0, "projects/test/secrets/demo/versions/2", "")

    monkeypatch.setattr(deploy.subprocess, "run", run)
    deploy.Deployer(config).publish_secrets(file)
    uploads = [
        (command, value)
        for command, value in calls
        if command[1:4] == ["secrets", "versions", "add"]
    ]
    assert len(uploads) == 1 and uploads[0][1] == "fake-groq-secret"
    assert all("fake-groq-secret" not in " ".join(command) for command, _ in calls)
    assert "fake-groq-secret" not in capsys.readouterr().out


def test_rollback_rejects_legacy_demo_auth_revision(config, monkeypatch):
    runner = deploy.Deployer(config)
    monkeypatch.setattr(
        runner,
        "gcloud",
        lambda *args, **kwargs: json.dumps(
            {
                "metadata": {"labels": {"serving.knative.dev/service": config.service_name}},
                "spec": {
                    "containers": [
                        {
                            "env": [
                                {"name": "ENVIRONMENT", "value": "production"},
                                {"name": "DEMO_BEARER_TOKEN", "value": "old"},
                            ]
                        }
                    ]
                },
            }
        ),
    )
    with pytest.raises(deploy.DeploymentError, match="Legacy demo-auth"):
        runner.revision_token("old-revision")


def test_container_entrypoint_honors_port(monkeypatch):
    from app import serve

    calls = []
    monkeypatch.setenv("PORT", "8095")
    monkeypatch.setattr(serve.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    serve.main()
    assert calls[0]["host"] == "0.0.0.0" and calls[0]["port"] == 8095


def test_muse_release_pins_key_and_wires_durable_highlighting(config):
    from dataclasses import replace

    configured = replace(
        config,
        muse_secret="muse-secret",
        annotation_tasks_queue="projects/test-project/locations/us-central1/queues/highlights",
        annotation_worker_url="https://test.run.app",
    )
    release = FakeRelease(configured)
    release.release(
        model="muse-main",
        provider="muse",
        segmentation_model="sam-3.1",
        image=config.repository + "/backend@sha256:" + "a" * 64,
    )
    command = next(c for c in release.commands if "deploy" in c)
    environment = next(item for item in command if item.startswith("--set-env-vars="))
    assert "MODEL_PROVIDER=muse" in environment
    assert "MUSE_MAIN_MODEL=muse-main" in environment
    assert "MUSE_SEGMENTATION_MODEL=sam-3.1" in environment
    assert "ANNOTATION_WORKER_URL=https://test.run.app" in environment
    secrets = next(item for item in command if item.startswith("--set-secrets="))
    assert "MUSE_API_KEY=muse-secret:7" in secrets
    assert "GROQ_API_KEY" not in secrets


def test_capacity_admits_twelve_concurrent_highlight_attempts(config):
    import re
    from pathlib import Path

    release = FakeRelease(config)
    release.release(
        model="model", provider="groq", image=config.repository + "/backend@sha256:" + "a" * 64
    )
    command = next(c for c in release.commands if "deploy" in c)

    def flag(name):
        return int(next(a for a in command if a.startswith(f"--{name}=")).split("=")[1])

    # One assessment's 12 attempts overlap while the API still serves requests.
    assert flag("concurrency") * flag("max") >= 12 + 2
    terraform = (Path(__file__).parents[2] / "deploy/terraform/main.tf").read_text()
    queue = terraform[terraform.index('resource "google_cloud_tasks_queue"') :]
    assert int(re.search(r"max_concurrent_dispatches\s*=\s*(\d+)", queue).group(1)) >= 12
    assert int(re.search(r"max_dispatches_per_second\s*=\s*(\d+)", queue).group(1)) >= 12


def test_phone_env_refreshes_service_url_and_pinned_token(config, tmp_path, monkeypatch, capsys):
    from dotenv import dotenv_values

    env_file = tmp_path / ".env"
    env_file.write_text("MUSE_API_KEY=private-model-key\nUNRELATED=keep-me\n")
    runner = deploy.Deployer(config)
    checks = []
    monkeypatch.setattr(runner, "verify_url", lambda url, token: checks.append((url, token)))
    for url, token in (
        ("https://first-service.run.app", "first-pinned-token"),
        ("https://recreated-service.run.app", "second-pinned-token"),
    ):
        monkeypatch.setattr(
            runner,
            "describe",
            lambda url=url: {
                "status": {"url": url, "traffic": [{"revisionName": "serving", "percent": 100}]},
            },
        )
        monkeypatch.setattr(runner, "revision_token", lambda revision, token=token: token)
        runner.configure_phone(env_file)
        values = dotenv_values(env_file)
        assert values["EXPO_PUBLIC_API_URL"] == url
        assert values["EXPO_PUBLIC_DATA_SOURCE"] == "api"
        assert "EXPO_PUBLIC_DEMO_TOKEN" not in values
        assert "DEMO_BEARER_TOKEN" not in values
        assert values["EXPO_PUBLIC_FIREBASE_PROJECT_ID"] == config.project_id
        assert values["MUSE_API_KEY"] == "private-model-key"
        assert values["UNRELATED"] == "keep-me"
        assert checks[-1] == (url, token)
    assert env_file.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert "pinned-token" not in output
    assert "private-model-key" not in output


def test_phone_env_failure_preserves_previous_frontend_settings(config, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    original = "EXPO_PUBLIC_API_URL=https://previous.run.app\n"
    env_file.write_text(original)
    runner = FakeRelease(config, fail_at="https://service.run.app")
    monkeypatch.setattr(runner, "revision_token", lambda revision: "pinned-token")
    with pytest.raises(deploy.DeploymentError, match="Injected health failure"):
        runner.configure_phone(env_file)
    assert env_file.read_text() == original
