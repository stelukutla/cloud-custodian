# Copyright 2020 Kapil Thangavelu
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Functional Tests for the Docker

The uses here is a little specialized to be invoked by tools/dev/dockerpkg.py
during image building.
"""
import json
import os

import pytest
import yaml

try:
    import docker
except ImportError:
    docker = None

TEST_DOCKER = docker and os.environ.get("TEST_DOCKER", "no") == "yes"

CUSTODIAN_ORG_IMAGE = os.environ.get("CUSTODIAN_ORG_IMAGE")
CUSTODIAN_IMAGE = os.environ.get("CUSTODIAN_CLI_IMAGE")
CUSTODIAN_MAILER_IMAGE = os.environ.get(
    "CUSTODIAN_MAILER_IMAGE", "cloudcustodian/mailer:latest"
)
CUSTODIAN_PSTREAM_IMAGE = os.environ.get(
    "CUSTODIAN_POLICYSTREAM_IMAGE", "cloudcustodian/policystream:latest"
)


@pytest.fixture
def custodian_org_dir(tmpdir):
    with open(os.path.join(tmpdir, "accounts.json"), "w") as fh:
        fh.write(
            json.dumps(
                {
                    "accounts": [
                        {
                            "account_id": "644160558196",
                            "name": "c7n-test",
                            "role": "arn:aws:iam::644160558196:role/Github-CI",
                            "region": [
                                "us-east-1",
                                "us-east-2",
                                "us-west-2",
                                "eu-west-1",
                            ],
                        }
                    ]
                }
            )
        )

    with open(os.path.join(tmpdir, "policies-aws.json"), "w") as fh:
        fh.write(
            json.dumps(
                {
                    "policies": [
                        {"name": "dynamo", "resource": "aws.dynamodb-table"},
                        {"name": "lambda", "resource": "aws.ecr"},
                    ]
                }
            )
        )

    os.chmod(tmpdir, 0o777)
    return tmpdir


@pytest.fixture
def custodian_env_creds():
    env = get_env_creds()
    docker_env_list = []
    for k, v in env.items():
        docker_env_list.append("%s=%s" % (k, v))
    return docker_env_list


def get_env_creds(check_aws=False, check_azure=False, check_gcp=False):
    aws_keys = (
        check_aws,
        ["AWS_DEFAULT_REGION", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID"],
    )
    azure_keys = (check_azure, ["AZURE_SUBSCRIPTION_ID", "AZURE_ACCESS_TOKEN"])
    gcp_keys = (check_gcp, ["GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"])
    env_set = (aws_keys, azure_keys, gcp_keys)
    env = {}

    for (check, key_set) in env_set:
        key_env = {}
        for k in key_set:
            if k in os.environ:
                key_env[k] = os.environ[k]
        if check:
            return set(key_env) == set(key_set)
        env.update(key_env)
    return env


@pytest.mark.skipif(
    not (TEST_DOCKER and CUSTODIAN_ORG_IMAGE and get_env_creds(check_aws=True)),
    reason="docker testing not requested",
)
def test_org_run_aws(custodian_org_dir, custodian_env_creds):
    client = docker.from_env()
    client.containers.run(
        CUSTODIAN_ORG_IMAGE,
        (
            "run -v -a c7n -c {dir}/accounts.json"
            " -s {dir}/output"
            " --region=all"
            " -u {dir}/policies-aws.json"
        ).format(dir="/home/custodian/"),
        environment=custodian_env_creds,
        remove=True,
        stderr=True,
        volumes={custodian_org_dir: {"bind": "/home/custodian", "mode": "rw"}},
    )


@pytest.mark.skipif(
    not (TEST_DOCKER and CUSTODIAN_IMAGE), reason="docker testing not requested"
)
def test_cli_providers_available():
    providers = os.environ.get("CUSTODIAN_PROVIDERS", None)
    if providers is None:
        providers = {"aws", "azure", "gcp", "k8s"}
    elif providers == "":
        providers = {"aws"}
    else:
        providers = set(providers.split())

    client = docker.from_env()
    output = client.containers.run(CUSTODIAN_IMAGE, "schema", stderr=True)
    resources = yaml.safe_load(output.strip())["resources"]
    found_providers = {r.split(".", 1)[0] for r in resources}
    assert providers == found_providers


@pytest.mark.skipif(
    not (TEST_DOCKER and CUSTODIAN_IMAGE and get_env_creds(check_aws=True)),
    reason="docker testing not requested",
)
def test_cli_run_aws(custodian_org_dir, custodian_env_creds):
    client = docker.from_env()
    output = client.containers.run(
        CUSTODIAN_IMAGE,
        ("run -v" " -s {dir}/output" " {dir}/policies-aws.json").format(
            dir="/home/custodian"
        ),
        environment=custodian_env_creds,
        remove=True,
        stderr=True,
        volumes={custodian_org_dir: {"bind": "/home/custodian", "mode": "rw"}},
    )
    print()
    print(output.decode("utf8"))


@pytest.mark.skipif(
    not (TEST_DOCKER and CUSTODIAN_IMAGE and get_env_creds(check_aws=True)),
    reason="docker testing not requested",
)
def test_cli_run_aws_sans_home_dir(custodian_org_dir, custodian_env_creds):
    # Specifically targeting #5581 and distroless containers that we don't
    # have errors about creating cache directories
    client = docker.from_env()
    output = client.containers.run(
        CUSTODIAN_IMAGE,
        ("run -v -s {dir}/output {dir}/policies-aws.json").format(dir="/run"),
        environment=custodian_env_creds,
        remove=True,
        stderr=True,
        volumes={custodian_org_dir: {"bind": "/run", "mode": "rw"}},
    )
    print()
    print(output.decode("utf8"))
    assert "Permission denied" not in output.decode("utf8")
