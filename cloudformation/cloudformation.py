#!/usr/bin/env python

"""
Command details:
    batch           Init Elastic Search.
    tracking             Run the application using the Flask Development.

Usage:
    cloudformation.py batch OPERATION CONFIG 
    cloudformation.py common OPERATION CONFIG
    cloudformation.py cognito OPERATION CONFIG

Arguments:
    OPETATION  operation to execute on stack (create or update)
    CONFIG  path to config file
"""

from functools import wraps
import os
import sys
import json
from docopt import docopt
from ruamel.yaml import YAML
import boto3


OPTIONS = docopt(__doc__) if __name__ == '__main__' else dict()

STACK_OPERATION_WHITELIST = {
    "common": ["create", "update"],
    "batch": ["create", "update"],
    "cognito": ["create"]
}


def command(func):
    @wraps(func)
    def wrapped():
        return func()

    if func.__name__ not in OPTIONS:
        raise KeyError('Cannot register {}, not mentioned in docstring/docopt.'.format(func.__name__))
    if OPTIONS[func.__name__]:
        command.chosen = func

    return wrapped

def load_config(config_file):
    yaml = YAML()

    try:
        with open(config_file, 'r') as c:
            config = yaml.load(c)
        
            if len(config['SubnetsPublic']) != 2:
                print('Exactly 2 public subnets required')
                sys.exit(1)
            return config
    
    except Exception as e:
        print('Error reading configuration YAML: {}'.format(e))
        sys.exit(1)

def stack_template_file(stack_name):
    return os.path.join(os.path.dirname(__file__), '{}.yml'.format(stack_name))

def _cf_method(cf, stack_name, operation):
    allowed_operations = STACK_OPERATION_WHITELIST.get(stack_name, [])
    if operation in allowed_operations:
        cf_method = None
        if operation == 'create':
            cf_method = cf.create_stack
        elif operation == 'update':
            cf_method = cf.update_stack

        return cf_method    
    else:
        print('Operation {} is not implemented or allowed'.format(operation))
        sys.exit(1)
          

def run(operation, stack_name, config, template_file, parameters):
    region = config['Region']
    prefix = config['StackPrefix']
    stage = config['Stage']

    cf = boto3.client('cloudformation', region_name=region)
    cf_method = _cf_method(cf, stack_name, operation) 


    name = '{}-cf-{}'.format(prefix, stack_name)

    project_tag = config['ProjectTag']

    with open(template_file, 'r') as f:
        template_body = f.read()


    default_parameters = [
        {
            'ParameterKey': 'StackPrefix',
            'ParameterValue': prefix
        },
        {
            'ParameterKey': 'Stage',
            'ParameterValue': stage
        },
        {
            'ParameterKey': 'ProjectTag',
            'ParameterValue': project_tag
        }
    ]
    
    response = cf_method(
        StackName=name,
        TemplateBody=template_body,
        Parameters=default_parameters + parameters,
        Capabilities=[
            'CAPABILITY_NAMED_IAM',
        ],
        Tags=[{
            'Key': 'project',
            'Value': project_tag
        }]
    )

    print('Stack {} completed: {}'.format(operation, response['StackId']))


@command
def common():
    operation = OPTIONS["OPERATION"]
    config_file = OPTIONS["CONFIG"]
    
    config = load_config(config_file)

    stack_name = "common"

    vpc_id = config['VpcId']
    subnets_public = ','.join(config['SubnetsPublic'])
    database_password = config['DatabasePassword']

    parameters = [
        {
            'ParameterKey': 'VpcId',
            'ParameterValue': vpc_id
        },
        {
            'ParameterKey': 'SubnetsPublic',
            'ParameterValue': subnets_public
        },
        {
            'ParameterKey': 'DatabasePassword',
            'ParameterValue': database_password
        }
    ]
    run(operation, stack_name, config, stack_template_file(stack_name), parameters)


@command
def batch():
    operation = OPTIONS["OPERATION"]
    config_file = OPTIONS["CONFIG"]
    
    config = load_config(config_file)

    stack_name = "batch"

    ami = config['BatchAMI']
    batch_cluster_ec2_min_cpus = config['BatchClusterEC2MinCpus']
    batch_cluster_ec2_max_cpus = config['BatchClusterEC2MaxCpus']
    batch_cluster_ec2_desired_cpus = config['BatchClusterEC2DesiredCpus']
    batch_cluster_spot_min_cpus = config['BatchClusterSpotMinCpus']
    batch_cluster_spot_max_cpus = config['BatchClusterSpotMaxCpus']
    batch_cluster_spot_desired_cpus = config['BatchClusterSpotDesiredCpus']
    batch_cluster_spot_bid_percentage = config['BatchClusterSpotBidPercentage']
    subnets_public = ','.join(config['SubnetsPublic'])

    parameters = [
        {
            'ParameterKey': 'BatchAMI',
            'ParameterValue': ami
        },
        {
            'ParameterKey': 'BatchClusterEC2MinCpus',
            'ParameterValue': str(batch_cluster_ec2_min_cpus)
        },
        {
            'ParameterKey': 'BatchClusterEC2MaxCpus',
            'ParameterValue': str(batch_cluster_ec2_max_cpus)
        },
        {
            'ParameterKey': 'BatchClusterEC2DesiredCpus',
            'ParameterValue': str(batch_cluster_ec2_desired_cpus)
        },
        {
            'ParameterKey': 'BatchClusterSpotMinCpus',
            'ParameterValue': str(batch_cluster_spot_min_cpus)
        },
        {
            'ParameterKey': 'BatchClusterSpotMaxCpus',
            'ParameterValue': str(batch_cluster_spot_max_cpus)
        },
        {
            'ParameterKey': 'BatchClusterSpotDesiredCpus',
            'ParameterValue': str(batch_cluster_spot_desired_cpus)
        },
        {
            'ParameterKey': 'BatchClusterSpotBidPercentage',
            'ParameterValue': str(batch_cluster_spot_bid_percentage)
        },
        {
            'ParameterKey': 'SubnetsPublic',
            'ParameterValue': subnets_public
        }
    ]
    run(operation, stack_name, config, stack_template_file(stack_name), parameters)



@command
def cognito():
    operation = OPTIONS["OPERATION"]
    config_file = OPTIONS["CONFIG"]

    config = load_config(config_file)

    stack_name = "cognito"

    parameters = []
    run(operation, stack_name, config, stack_template_file(stack_name), parameters)

if __name__ == '__main__':
    getattr(command, 'chosen')()
