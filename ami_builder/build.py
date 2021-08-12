import sys
from ruamel.yaml import YAML
import time
import boto3
import click
from botocore.exceptions import ClientError

yaml = YAML()

SLEEP = 30
INSTANCE_TYPE = 't2.micro'


@click.group()
def ami():
    """Build AMIs for AWS."""


@ami.command('build')
@click.argument('configfile')
def build_ami(configfile):
    """Build an EC2 instance AMI from the given config file.

    Build an AMI for Batch use with EFS. Common cloudformation infrastructure
    must already be deployed.
    """
    try:
        config = yaml.load(configfile)
    except Exception as e:
        print('Error reading configuration YAML: {}'.format(e))
        sys.exit(1)

    # Validate the number of subnets
    if len(config['SubnetsPublic']) != 2:
        print('Exactly 2 public subnets required')
        sys.exit(1)

    region = config['Region']
    prefix = config['StackPrefix']
    stage = config['Stage']
    base_ami = config['BaseAMI']
    subnet_public = config['SubnetsPublic'][0]
    ssh_key_name = config['SSHKeyName']
    ssh_security_group = config['SSHSecurityGroup']
    tags = [{
        'Key': 'project',
        'Value': config['ProjectTag']
    }]
    aws_profile = config['Profile']
    if aws_profile == 'default':
        aws_profile = None

    # AMI output details
    NAME = '{}-{}-efs-{}'
    DESCRIPTION = 'Automatically mount the {} EFS share for {}-{}'

    session = boto3.Session(profile_name=aws_profile)
    ssm = session.client('ssm', region_name=region)
    ec2 = session.client('ec2', region_name=region)

    # Get the ID of the EFS volume
    efs_id = ssm.get_parameter(
        Name='/{}/{}/common/EFSID'.format(prefix, stage)
    )['Parameter']['Value']

    # Get the ID of the General Security Group
    general_sg_id = ssm.get_parameter(
        Name='/{}/{}/common/GeneralSGID'.format(prefix, stage)
    )['Parameter']['Value']

    security_groups = [ssh_security_group, general_sg_id]

    # Build the user data
    user_data = '''#!/usr/bin/env bash
    sudo yum install -y amazon-efs-utils
    sudo mkdir /mnt/efs
    sudo echo  >> /etc/fstab
    echo "{} /mnt/efs	efs	defaults,_netdev 0   0" \
        | sudo tee --append /etc/fstab
    '''.format(efs_id)

    # Format the AMI output details
    description = DESCRIPTION.format(efs_id, prefix, stage)
    name = NAME.format(prefix, stage, efs_id)

    # Check that this image does not already exist
    images = ec2.describe_images(
        Filters=[
            {
                'Name': 'name',
                'Values': [name]
            }
        ]
    )['Images']

    if len(images) > 0:
        print('An image with the name "{}" already exists:'.format(name))
        sys.exit(1)

    # Launch an EC2 instance
    instance_id = ec2.run_instances(
        # Suppress ECS default 22GB EBS
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/xvdcz',
                'NoDevice': ''
            }
        ],
        ImageId=base_ami,
        InstanceType=INSTANCE_TYPE,
        KeyName=ssh_key_name,
        MaxCount=1,
        MinCount=1,
        SecurityGroupIds=security_groups,
        SubnetId=subnet_public,
        UserData=user_data,
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': tags
            },
            {
                'ResourceType': 'volume',
                'Tags': tags
            }
        ]
    )['Instances'][0]['InstanceId']

    print('Instance starting: {}'.format(instance_id))

    # Wait for status 2/2 as an indicator of readiness for creating AMI
    while True:

        try:
            statuses = ec2.describe_instance_status(
                InstanceIds=[instance_id]
            )['InstanceStatuses']
        except ClientError:
            statuses = None

        if statuses is not None and len(statuses) > 0:
            status = statuses[0]
            if (
                status['InstanceState']['Name'] == 'running'
                and status['InstanceStatus']['Status'] == 'ok'
                and status['SystemStatus']['Status'] == 'ok'
            ):
                break

        print('\tWaiting for instance to start...')
        time.sleep(SLEEP)

    # Create an AMI from the instance
    image_id = ec2.create_image(
        Description=description,
        InstanceId=instance_id,
        Name=name
    )['ImageId']

    print('Instance started, creating image: {}'.format(image_id))

    # Wait for image creation to complete
    while True:
        try:
            images = ec2.describe_images(
                ImageIds=[image_id]
            )['Images']
        except ClientError:
            images = None

        if images is not None and len(images) > 0:
            image = images[0]
            if image['State'] == 'available':
                break

        print('\tWaiting for image creation...')
        time.sleep(SLEEP)

    print('Image created, terminating instance.')

    # Wait for instance to terminate
    while True:
        try:
            instances = ec2.terminate_instances(
                InstanceIds=[instance_id]
            )['TerminatingInstances']
        except ClientError:
            instances = None

        if instances is not None and len(instances) > 0:
            instance = instances[0]
            if instance['CurrentState']['Name'] == 'terminated':
                break

        print('\tWaiting for instance to terminate...')
        time.sleep(SLEEP)

    print('Instance terminated!')
