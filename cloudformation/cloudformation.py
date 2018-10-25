#!/usr/bin/env python

import argparse
from enum import Enum
import os
import sys
from ruamel.yaml import YAML
import boto3


def load_config(config):

    yaml = YAML()

    try:
        parsed_config = yaml.load(config)

        if len(parsed_config['SubnetsPublic']) != 2:
            print('Exactly 2 public subnets required')
            sys.exit(1)
        return parsed_config

    except Exception as e:
        print('Error reading configuration YAML: {}'.format(e))
        sys.exit(1)


def make_parameter(key, value):

    return {
        'ParameterKey': key,
        'ParameterValue': value
    }


def string_configs_to_parameters(config, keys):

    return [make_parameter(key, str(config[key])) for key in keys]


def get_stack_template_path(stack):

    return os.path.join(os.path.dirname(__file__), '{}.yml'.format(stack))


def prepare_common_parameters(config):

    parameters = string_configs_to_parameters(config, [
        'VpcId',
        'DatabasePassword'
    ])

    parameters.append(make_parameter('SubnetsPublic',
                                     ','.join(config['SubnetsPublic'])))

    return parameters


def prepare_batch_parameters(config):

    parameters = string_configs_to_parameters(config, [
        'BatchAMI',
        'BatchClusterEC2MinCpus',
        'BatchClusterEC2MaxCpus',
        'BatchClusterEC2DesiredCpus',
        'BatchClusterSpotMinCpus',
        'BatchClusterSpotMaxCpus',
        'BatchClusterSpotDesiredCpus',
        'BatchClusterSpotBidPercentage'
    ])

    parameters.append(make_parameter('SubnetsPublic',
                                     ','.join(config['SubnetsPublic'])))

    return parameters


def prepare_cognito_parameters(config):

    return []


def main(operation, stack, config):

    # Load the configuration file
    config = load_config(config)

    # Get config parameters needed to configure the operation itself
    region = config['Region']
    prefix = config['StackPrefix']
    project_tag = config['ProjectTag']

    # Select the appropriate cloudformation operation
    cf = boto3.client('cloudformation', region_name=region)
    if operation == 'create':
        cf_method = cf.create_stack
    elif operation == 'update':
        cf_method = cf.update_stack
    else:
        print(f'Operation "{operation}" is not implemented')
        sys.exit(1)

    # Build a prefixed name for this stack
    name = f'{prefix}-cf-{stack}'

    # Read the template
    template_path = get_stack_template_path(stack)
    with open(template_path, 'r') as f:
        template_body = f.read()

    # Prepare the parameters common to all stacks
    shared_parameters = string_configs_to_parameters(config, [
        'StackPrefix',
        'Stage',
        'ProjectTag'
    ])

    print(stack)
    print(type(str(stack)))

    # Prepare the parameters specific to the requested stack
    if stack == 'common':
        parameters = prepare_common_parameters(config)
    elif stack == 'cognito':
        parameters = prepare_cognito_parameters(config)
    elif stack == 'batch':
        parameters = prepare_batch_parameters(config)

    # Trigger the operation
    response = cf_method(
        StackName=name,
        TemplateBody=template_body,
        Parameters=shared_parameters + parameters,
        Capabilities=[
            'CAPABILITY_NAMED_IAM',
        ],
        Tags=[{
            'Key': 'project',
            'Value': project_tag
        }]
    )

    stack_id = response['StackId']
    print(f'Stack {stack} {operation} completed: {stack_id}')


if __name__ == '__main__':

    class Stack(Enum):
        common = 'common'
        cognito = 'cognito'
        batch = 'batch'

        def __str__(self):
            return self.value

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='operation')
    parser_create = subparsers.add_parser('create', help='Create stack')
    parser_update = subparsers.add_parser('update', help='Update stack')
    parser_delete = subparsers.add_parser('delete', help='Delete stack')
    parser.add_argument('stack', type=Stack, choices=list(Stack))
    parser.add_argument('config', type=argparse.FileType('r'),
                        help='YAML configuration file path')

    opts = parser.parse_args()

    main(opts.operation, str(opts.stack), opts.config)
