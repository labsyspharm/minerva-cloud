import moto
import boto3
import pytest
from os import path, environ

from jinja2 import Template

from cloudformation.cloudformation import CloudFormationStack, operate_on_stack


RESOURCE_BASE_NAME_COMMON ='minerva-test-cf-common-'


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
def efs(aws_credentials):
    with moto.mock_efs():
        yield boto3.client('efs', region_name='us-east-1')



@pytest.fixture(scope='function')
def cf(aws_credentials):
    with moto.mock_cloudformation():
        yield boto3.client('cloudformation', region_name='us-east-1')

@pytest.fixture(scope='function')
def rds(aws_credentials):
    with moto.mock_rds():
        yield boto3.client('rds', region_name='us-east-1')

@pytest.fixture(scope='function')
def ec2(aws_credentials):
    with moto.mock_ec2():
        ec2 = boto3.client('ec2', region_name='us-east-1')
        yield ec2


@pytest.fixture(scope='function')
def minerva_config(cf, s3, ec2):
    with open('minerva-config.example.yml', 'r') as f:
        template = Template(f.read())
    vpc_resp = ec2.describe_vpcs()
    vpc_id = vpc_resp['Vpcs'][0]['VpcId']
    subnets = ec2.describe_subnets()['Subnets']
    public_subnets = [sn['SubnetId'] for sn in subnets[:2]]
    private_subnets = [sn['SubnetId'] for sn in subnets[2:4]]
    default_sgs = ec2.describe_security_groups()['SecurityGroups']
    ssh_sg_resp = ec2.create_security_group(GroupName='ssh-sg',
                                            Description='A Security Group for ssh-ing.')
    yield template.render(vpc_id=vpc_id,
                          public_subnet_1=public_subnets[0],
                          public_subnet_2=public_subnets[1],
                          private_subnet_1=private_subnets[0],
                          private_subnet_2=private_subnets[1],
                          ssh_sg=ssh_sg_resp['GroupId'],
                          default_sg=default_sgs[0]['GroupId'])


def _validate_resource_names(resource, expected_names, actual_names):
    expected_names = expected_names[:]
    for actual_name in actual_names:
        for name in expected_names:
            if actual_name.startswith(RESOURCE_BASE_NAME_COMMON + name):
                expected_names.remove(name)
                break
    assert not expected_names, f"Not all {resource} created."



def test_stack_templates():
    for s_name in CloudFormationStack.list_stacks():
        stack = CloudFormationStack.from_name(s_name)
        config_fpath = stack.get_template_path()
        assert path.exists(config_fpath)
        assert path.abspath(config_fpath) == config_fpath


def test_create_common_stack(s3, efs, ec2, rds, cf, minerva_config):
    operate_on_stack(cf, 'create', 'common', minerva_config)

    # Test for s3 buckets.
    buckets = s3.list_buckets()
    _validate_resource_names("s3 buckets", ['rawbucket', 'tilebucket'],
                             [b["Name"] for b in buckets["Buckets"]])

    # Test for security groups
    security_groups = ec2.describe_security_groups()
    _validate_resource_names("security groups", ['GeneralSG'],
                             [sg['GroupName']
                              for sg in security_groups['SecurityGroups']])

    # Test for the RDS instance.
    rds_instances = rds.describe_db_instances()
    assert [dbi['DBInstanceIdentifier'] for dbi in rds_instances['DBInstances']] \
           == ['minerva-test-dev-database']

    # Test for the EFS volumes
    file_systems = efs.describe_file_systems()
    assert len(file_systems['FileSystems']) == 1
    fs_info = file_systems['FileSystems'][0]
    assert fs_info['NumberOfMountTargets'] == 2

    # Test for the mount targets
    mount_targets = efs.describe_mount_targets(FileSystemId=fs_info['FileSystemId'])
    assert len(mount_targets['MountTargets']) == 2
