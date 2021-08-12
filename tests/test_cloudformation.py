from os import path

from cloudformation.cloudformation import CloudFormationStack, operate_on_stack

from .fixtures import *  # noqa

RESOURCE_BASE_NAME ='minerva-test-cf'

def _matches_resource_name(stack, resource, actual_name):
    prefix = '-'.join([RESOURCE_BASE_NAME, stack, resource])
    return actual_name.startswith(prefix)


def _validate_resource_names(resource, expected_names, actual_names):
    for actual_name in actual_names:
        for stack in expected_names.keys():
            for name in expected_names[stack]:
                if _matches_resource_name(stack, name, actual_name):
                    expected_names[stack].remove(name)
                    break
            if not expected_names[stack]:
                expected_names.pop(stack)
                break
    assert not expected_names, f"Not all {resource} created."



def test_stack_templates():
    for s_name in CloudFormationStack.list_stacks():
        stack = CloudFormationStack.from_name(s_name)
        config_fpath = stack.get_template_path()
        assert path.exists(config_fpath)
        assert path.abspath(config_fpath) == config_fpath


def test_create_common_stack(s3, efs, ec2, rds, cf, iam, minerva_config):
    operate_on_stack(cf, 'create', 'common', minerva_config)

    # Test for s3 buckets.
    buckets = s3.list_buckets()
    _validate_resource_names("s3 buckets", {'common': ['rawbucket', 'tilebucket']},
                             [b["Name"] for b in buckets["Buckets"]])

    # Test for security groups
    security_groups = ec2.describe_security_groups()
    _validate_resource_names("security groups", {'common': ['GeneralSG']},
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


def test_create_author_stack(s3, efs, ec2, rds, cf, iam, minerva_config):
    # Create the author stack.
    operate_on_stack(cf, 'create', 'common', minerva_config)
    operate_on_stack(cf, 'create', 'author', minerva_config)

    # Check that everything was built correctly.
    buckets = s3.list_buckets()
    _validate_resource_names("s3 buckets", {'common': ['rawbucket', 'tilebucket'],
                                            'author': ['storybucket',
                                                       'minervastorybasebucket',
                                                       'publishedbucket']},
                             [b["Name"] for b in buckets["Buckets"]])
