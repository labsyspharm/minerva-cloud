import moto
import boto3
import pytest
from os import path, environ
from cloudformation.cloudformation import CloudFormationStack, operate_on_stack


@pytest.fixture(scope='function')
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    environ['AWS_ACCESS_KEY_ID'] = 'testing'
    environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    environ['AWS_SECURITY_TOKEN'] = 'testing'
    environ['AWS_SESSION_TOKEN'] = 'testing'


@pytest.fixture(scope='function')
def s3(aws_credentials):
    with moto.mock_s3():
        yield boto3.client('s3', region_name='us-east-1')


@pytest.fixture(scope='function')
def cf(aws_credentials):
    with moto.mock_cloudformation():
        yield boto3.client('cloudformation', region_name='us-east-1')


def test_stack_templates():
    for s_name in CloudFormationStack.list_stacks():
        stack = CloudFormationStack.from_name(s_name)
        config_fpath = stack.get_template_path()
        assert path.exists(config_fpath)
        assert path.abspath(config_fpath) == config_fpath


def test_create_common_stack(cf):
    with open('minerva-config.example.yml', 'r') as conf:
        operate_on_stack(cf, 'create', 'common', conf)
    assert True
