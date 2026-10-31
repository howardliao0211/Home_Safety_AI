"""Exercise the actual CLI/wrapper subprocess chain against fake cloud tools."""

import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Fake CLIs preserve state and plan serials. They reject stale plans and a field
# reset, reproducing the teardown failures without credentials or cloud access.
FAKE_TOOL = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['TEST_DEPLOY_ROOT'])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps([tool, *args]) + '\\n')
directory = root / 'deploy/terraform'
state_file = directory / 'terraform.tfstate'
state = json.loads(state_file.read_text()) if state_file.exists() else {'serial': 0, 'resources': []}
service = root / 'service'
if tool == 'uv':
    sys.exit(0)
if tool == 'docker':
    sys.path.insert(0, str(root / 'scripts'))
    from gcp_image import source_hash
    print(source_hash())
    sys.exit(0)
if tool == 'gcloud':
    if args[:2] == ['auth', 'print-access-token']:
        print('fake-oauth')
    elif args[:2] == ['projects', 'describe']:
        print('123456')
    elif args[:3] == ['run', 'services', 'list']:
        region = next(a.split('=', 1)[1] for a in args if a.startswith('--region='))
        print('home-safety-demo' if service.exists() and service.read_text() == region else '')
    elif args[:3] == ['run', 'services', 'delete']:
        region = next(a.split('=', 1)[1] for a in args if a.startswith('--region='))
        assert service.read_text() == region, 'teardown must target the source region'
        service.unlink()
    elif args[:3] in (['tasks', 'queues', 'pause'], ['scheduler', 'jobs', 'pause']):
        pass
    elif args[:3] == ['run', 'services', 'describe']:
        if not service.exists():
            sys.exit(1)
        print(json.dumps({'status': {'traffic': []}}))
    else:
        raise AssertionError(args)
    sys.exit(0)
assert tool == 'terraform', tool
args = args[1:]  # -chdir
command = args[0]
variables = json.loads((directory / 'deploy.tfvars.json').read_text()) if (directory / 'deploy.tfvars.json').exists() else {}
region = variables.get('region', 'australia-southeast1')
config = {'project_id': 'test-project', 'region': region, 'service_name': 'home-safety-demo', 'annotation_worker_url': variables.get('annotation_worker_url', '')}
database = 'projects/test-project/databases/' + variables.get('firestore_database_id', '(default)')
queue = variables.get('annotation_queue_name', 'default')
resources = [
    {'type': kind, 'name': name, 'mode': 'managed', 'instances': [{'attributes': attributes}]}
    for kind, name, attributes in [
        ('google_firestore_database', 'assessments', {'id': database, 'location_id': region, 'project': 'test-project'}),
        ('google_firestore_field', 'annotation_dispatch', {'id': database + '/collectionGroups/assessments/fields/pending'}),
        ('google_cloud_tasks_queue', 'annotations', {'id': queue, 'name': queue, 'location': region}),
        ('google_secret_manager_secret', 'backend', {'id': 'home-safety-muse-api-key'}),
        ('google_identity_platform_config', 'accounts', {'id': 'projects/test-project/config'}),
    ]
]
targets = [a.split('=', 1)[1] for a in args if a.startswith('-target=')]
if command in ('init', 'validate'):
    pass
elif command == 'plan':
    destroy = '-destroy' in args
    if not destroy and not any(r['type'] == 'google_identity_platform_config' for r in state['resources']):
        assert variables.get('adopt_existing_identity_config'), 'existing identity config must be imported after stop'
    with (root / 'plans.jsonl').open('a') as log:
        log.write(json.dumps({'destroy': destroy, **variables}) + '\\n')
    selected = [r for r in state['resources'] if not targets or r['type'] + '.' + r['name'] in targets] if destroy else [r for r in resources if not any(s['type'] == r['type'] for s in state['resources']) or r['type'] not in ('google_secret_manager_secret', 'google_identity_platform_config')]
    changes = [{'address': r['type'] + '.' + r['name'], 'type': r['type'], 'change': {'actions': ['delete' if destroy else 'create'], 'before': r['instances'][0]['attributes'] if destroy else None}} for r in selected]
    plan = {'variables': {k: {'value': v} for k, v in config.items()}, 'resource_changes': changes, 'serial': state['serial'], 'destroy': destroy}
    filename = next(a.split('=', 1)[1] for a in args if a.startswith('-out='))
    (directory / filename).write_text(json.dumps(plan))
elif command == 'show':
    print((directory / args[-1]).read_text())
elif command == 'output':
    if not state.get('outputs'):
        sys.exit(1)
    print(json.dumps(state['outputs'][args[-1]]['value']))
elif command == 'state':
    assert args[1] == 'rm'
    state['resources'] = [r for r in state['resources'] if r['type'] + '.' + r['name'] not in args[2:]]
    state['serial'] += 1
    state_file.write_text(json.dumps(state))
elif command == 'apply':
    plan = json.loads((directory / args[-1]).read_text())
    assert state['serial'] == plan['serial'], 'stale plan'
    if plan['destroy']:
        assert not service.exists(), 'Cloud Run must be gone before dependencies'
        assert all(c['type'] != 'google_firestore_field' for c in plan['resource_changes']), 'field reset would hang'
    if plan['destroy']:
        removed = {c['address'] for c in plan['resource_changes']}
        kept = [r for r in state['resources'] if r['type'] + '.' + r['name'] not in removed]
        # Like Terraform, a targeted destroy leaves stale outputs behind.
        state = {'serial': state['serial'] + 1, 'resources': kept, 'outputs': state.get('outputs', {}) if kept else {}}
    else:
        shared = [r for r in state['resources'] if r['type'] in ('google_secret_manager_secret', 'google_identity_platform_config')]
        state = {'serial': state['serial'] + 1, 'resources': shared + [r for r in resources if r['type'] not in {s['type'] for s in shared}], 'outputs': {'deployment_config': {'value': config}}}
    state_file.write_text(json.dumps(state))
else:
    raise AssertionError(args)
"""

FAKE_BACKEND = """import os, sys
from pathlib import Path
root = Path(os.environ['TEST_DEPLOY_ROOT'])
command = next(a for a in sys.argv[1:] if not a.startswith('--'))
if command == 'release':
    import json
    variables = json.loads((root / 'deploy/terraform/deploy.tfvars.json').read_text())
    (root / 'service').write_text(variables.get('region', 'australia-southeast1'))
elif command == 'service-url':
    print(f"https://home-safety-demo-{(root / 'service').read_text()}.run.app")
elif command in ('verify', 'phone-env'):
    assert (root / 'service').exists()
elif command not in ('build', 'preflight', 'configure-auth', 'secrets'):
    raise AssertionError(command)
"""


class LifecycleTests(unittest.TestCase):
    def test_start_stop_restart_and_partial_state_teardown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("scripts", "bin", "deploy/terraform", "backend/app", "backend/.venv/bin"):
                (root / name).mkdir(parents=True)
            for name in ("deploy.py", "terraform-gcp.py", "gcp_image.py"):
                shutil.copyfile(ROOT / "scripts" / name, root / "scripts" / name)
            shutil.copyfile(
                ROOT / "deploy/terraform/variables.tf", root / "deploy/terraform/variables.tf"
            )
            shutil.copy2(ROOT / "bin/deploy", root / "bin/deploy")
            (root / "scripts/deploy-gcp.py").write_text(FAKE_BACKEND)
            for name in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock"):
                (root / "backend" / name).touch()
            python = root / "backend/.venv/bin/python"
            python.write_text(f'#!/bin/sh\nexec "{ROOT / "backend/.venv/bin/python"}" "$@"\n')
            python.chmod(0o700)
            for name in ("terraform", "gcloud", "docker", "uv"):
                executable = root / "bin" / name
                executable.write_text(FAKE_TOOL)
                executable.chmod(0o700)
            env = {
                **os.environ,
                "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                "TEST_DEPLOY_ROOT": str(root),
                "MUSE_MAIN_MODEL": "test-model",
                "MUSE_API_KEY": "fake-key",
            }

            def invoke(command, confirmation, *options, status=0):
                # Match a terminal: each child input() gets only the answer to
                # its own prompt, rather than buffering the next child's answer.
                master, slave = pty.openpty()
                output = ""
                answers = iter(confirmation.splitlines())
                answered = 0
                process = subprocess.Popen(
                    ["deploy", command, *options],
                    cwd="/tmp",
                    env=env,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                )
                os.close(slave)
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            try:
                                chunk = os.read(master, 65536)
                            except OSError:
                                break
                            if not chunk:
                                break
                            output += chunk.decode()
                            prompts = output.count(
                                "Type apply to apply this reviewed plan: "
                            ) + output.count(
                                "Type destroy to remove Cloud Run and apply this destroy plan: "
                            ) + output.count("deployment and its data: ")
                            while answered < prompts:
                                os.write(master, (next(answers) + "\n").encode())
                                answered += 1
                        elif process.poll() is not None:
                            break
                    self.assertEqual(process.wait(timeout=1), status, output)
                    return output
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)

            queues = []
            for _ in range(2):
                invoke("start", "apply\n" * 3)
                variables = json.loads((root / "deploy/terraform/deploy.tfvars.json").read_text())
                queues.append(variables["annotation_queue_name"])
                # Reproduce partial/legacy state with no release outputs.
                state_file = root / "deploy/terraform/terraform.tfstate"
                state = json.loads(state_file.read_text())
                state["outputs"] = {}
                state_file.write_text(json.dumps(state))
                invoke("stop", "destroy\n")
                self.assertEqual(json.loads(state_file.read_text())["resources"], [])
                self.assertFalse((root / "service").exists())
                invoke("stop", "destroy\n")
            self.assertNotEqual(*queues)
            commands = [
                json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                sum(c[:4] == ["gcloud", "run", "services", "delete"] for c in commands), 2
            )
            self.assertTrue(list((root / ".tools/terraform-state-backups").glob("*.tfstate")))

            # Region rebuild: a US deployment moves to Sydney, keeping shared resources.
            state_file = root / "deploy/terraform/terraform.tfstate"
            variables_file = root / "deploy/terraform/deploy.tfvars.json"
            invoke("start", "apply\n" * 3, "--region", "us-central1")
            us_queue = json.loads(variables_file.read_text())["annotation_queue_name"]
            shared = [
                r
                for r in json.loads(state_file.read_text())["resources"]
                if r["type"] in ("google_secret_manager_secret", "google_identity_platform_config")
            ]
            # A plain start, or a changed default, never moves the deployment.
            refused = invoke("start", "", "--region", "australia-southeast1", status=1)
            self.assertIn("deploy rebuild --region australia-southeast1", refused)
            invoke("start", "apply\n" * 3)  # Saved region: same-region restart.
            self.assertEqual((root / "service").read_text(), "us-central1")
            plans_before = len((root / "plans.jsonl").read_text().splitlines())
            output = invoke(
                "rebuild", "rebuild\n" + "apply\n" * 3, "--region", "australia-southeast1"
            )
            self.assertIn("region us-central1", output)
            state = json.loads(state_file.read_text())
            database = next(
                r for r in state["resources"] if r["type"] == "google_firestore_database"
            )
            self.assertEqual(
                database["instances"][0]["attributes"]["location_id"], "australia-southeast1"
            )
            for resource in shared:
                self.assertIn(resource, state["resources"])
            variables = json.loads(variables_file.read_text())
            self.assertEqual(variables["region"], "australia-southeast1")
            self.assertNotEqual(variables["annotation_queue_name"], us_queue)
            self.assertEqual(
                variables["annotation_worker_url"],
                "https://home-safety-demo-australia-southeast1.run.app",
            )
            self.assertEqual((root / "service").read_text(), "australia-southeast1")
            commands = [
                json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            deletes = [c for c in commands if c[:4] == ["gcloud", "run", "services", "delete"]]
            self.assertIn("--region=us-central1", deletes[-1])
            self.assertTrue(any(c[:3] == ["gcloud", "tasks", "queues"] for c in commands))
            plans = [
                json.loads(line)
                for line in (root / "plans.jsonl").read_text().splitlines()[plans_before:]
            ]
            # The teardown plan used the source region; no Sydney plan targets a US worker.
            self.assertEqual(plans[0]["region"], "us-central1")
            self.assertTrue(plans[0]["destroy"])
            teardown = [p for p in plans if p["destroy"]]
            self.assertTrue(all(p["region"] == "us-central1" for p in teardown))
            for plan in plans[len(teardown):]:
                self.assertFalse(plan["destroy"])
                self.assertEqual(plan["region"], "australia-southeast1")
                self.assertNotIn("us-central1", plan.get("annotation_worker_url", ""))
            # Resuming after completion skips teardown and redeploys in place.
            invoke("rebuild", "apply\n" * 3, "--region", "australia-southeast1")
            self.assertEqual((root / "service").read_text(), "australia-southeast1")


if __name__ == "__main__":
    unittest.main()
