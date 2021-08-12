__all__ = [
    "aws_credentials",
    "s3",
    "efs",
    "cf",
    "rds",
    "ec2",
    "ssm",
    "iam",
    "minerva_config",
]

from os import path, environ

import boto3
import moto
import pytest
from jinja2 import Template


HERE = path.dirname(path.abspath(__file__))


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    environ["AWS_ACCESS_KEY_ID"] = "testing"
    environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    environ["AWS_SECURITY_TOKEN"] = "testing"
    environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture(scope="function")
def s3(aws_credentials):
    with moto.mock_s3():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.fixture(scope="function")
def efs(aws_credentials):
    with moto.mock_efs():
        yield boto3.client("efs", region_name="us-east-1")


@pytest.fixture(scope="function")
def cf(aws_credentials):
    with moto.mock_cloudformation():
        yield boto3.client("cloudformation", region_name="us-east-1")


@pytest.fixture(scope="function")
def rds(aws_credentials):
    with moto.mock_rds():
        yield boto3.client("rds", region_name="us-east-1")


@pytest.fixture(scope="function")
def ec2(aws_credentials):
    with moto.mock_ec2():
        yield boto3.client("ec2", region_name="us-east-1")


@pytest.fixture(scope="function")
def ssm(aws_credentials):
    with moto.mock_ssm():
        yield boto3.client("ssm", region_name="us-east-1")


@pytest.fixture(scope="function")
def iam(aws_credentials):
    with moto.mock_iam():
        yield boto3.client("iam", region_name="us-east-1")


@pytest.fixture(scope="function")
def minerva_config(cf, s3, ec2):
    with open(path.join(HERE, "minerva-config.example.yml"), "r") as f:
        template = Template(f.read())
    vpc_resp = ec2.describe_vpcs()
    vpc_id = vpc_resp["Vpcs"][0]["VpcId"]
    subnets = ec2.describe_subnets()["Subnets"]
    public_subnets = [sn["SubnetId"] for sn in subnets[:2]]
    private_subnets = [sn["SubnetId"] for sn in subnets[2:4]]
    default_sgs = ec2.describe_security_groups()["SecurityGroups"]
    ssh_sg_resp = ec2.create_security_group(
        GroupName="ssh-sg", Description="A Security Group for ssh-ing."
    )
    yield template.render(
        vpc_id=vpc_id,
        public_subnet_1=public_subnets[0],
        public_subnet_2=public_subnets[1],
        private_subnet_1=private_subnets[0],
        private_subnet_2=private_subnets[1],
        ssh_sg=ssh_sg_resp["GroupId"],
        default_sg=default_sgs[0]["GroupId"],
    )
