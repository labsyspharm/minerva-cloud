import os
import sys
from ruamel.yaml import YAML
import boto3
import time


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


class BuildFailure(Exception):
    def __init__(self, cf, stack_id):
        res = cf.describe_stack_events(StackName=stack_id)
        lines = []
        for event in res["StackEvents"]:
            if "FAILED" in event["ResourceStatus"]:
                lines.append(event["ResourceStatus"])
                lines.append(event["ResourceStatusReason"])
        failure_log = '\n'.join(lines)
        msg = f"Failed to build stack:\n{failure_log}"
        super(BuildFailure, self).__init__(msg)


class Stack:
    @classmethod
    def from_name(cls, name):
        for s in cls.__subclasses__():
            if s.name() == name:
                return s
        raise ValueError(f"Invalid stack name: \"{name}\".")

    @classmethod
    def list_stacks(cls):
        return [s.name() for s in cls.__subclasses__()]

    @staticmethod
    def string_configs_to_parameters(config, keys):
        return [make_parameter(key, str(config[key])) for key in keys]

    @classmethod
    def name(cls):
        return cls.__name__.lower()

    @classmethod
    def get_template_path(cls):
        return os.path.join(os.path.dirname(__file__), f'{cls.name()}.yml')

    @classmethod
    def prepare_parameters(cls, config):
        parameters = cls.string_configs_to_parameters(config, [
            'StackPrefix',
            'Stage',
            'ProjectTag'
        ])
        return parameters


class Common(Stack):
    @classmethod
    def prepare_parameters(cls, config):
        parameters = super(Common, cls).prepare_parameters()
        parameters += cls.string_configs_to_parameters(config, [
            'VpcId',
            'DatabasePassword',
            'EnableRenderedCache',
            'EnableRawCache'
        ])
        parameters.append(make_parameter('SubnetsPublic',
                                         ','.join(config['SubnetsPublic'])))
        return parameters


class Cognito(Stack):
    pass


class Batch(Stack):
    @classmethod
    def prepare_parameters(cls, config):
        parameters = super(Batch, cls).prepare_parameters()
        parameters += cls.string_configs_to_parameters(config, [
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


class Cache(Stack):
    @classmethod
    def prepare_parameters(cls, config):
        parameters = super(Cache, cls).prepare_parameters()
        return parameters + cls.string_configs_to_parameters(config, [
            'DefaultSecurityGroup',
            'CacheNodeType',
            'RawCacheNodeType'
        ])


class Author(Stack):
    pass


def operate_on_stack(operation, stack_name, config):
    # Load the configuration file
    config = load_config(config)

    # Get config parameters needed to configure the operation itself
    region = config['Region']
    prefix = config['StackPrefix']
    project_tag = config['ProjectTag']
    aws_profile = config['Profile']
    if aws_profile == 'default':
        aws_profile = None

    # Select the appropriate cloudformation operation
    session = boto3.Session(profile_name=aws_profile)
    cf = session.client('cloudformation', region_name=region)
    cf_methods = {
        'create': cf.create_stack,
        'update': cf.update_stack,
        'delete': cf.delete_stack
    }
    cf_method = cf_methods[operation]

    # Build a prefixed name for this stack
    cf_name = f'{prefix}-cf-{stack_name}'

    # Trigger the operation
    if operation in ['create', 'update']:
        stack = Stack.from_name(stack_name)
        template_path = stack.get_template_path()
        with open(template_path, 'r') as f:
            template_body = f.read()
        parameters = stack.prepare_parameters(config)
        response = cf_method(
            StackName=cf_name,
            TemplateBody=template_body,
            Parameters=parameters,
            Capabilities=[
                'CAPABILITY_NAMED_IAM',
            ],
            Tags=[{
                'Key': 'project',
                'Value': project_tag
            }]
        )
    elif operation == 'delete':
        response = cf_method(
            StackName=cf_name
        )
    else:
        raise ValueError(f"Invalid operation: \"{operation}\".")

    print(response)

    if 'StackId' in response:
        stack_id = response['StackId']
        print(f'Stack {stack_name} {operation} completed: {stack_id}')
        poll_progress = True
    else:
        stack_id = None
        poll_progress = False

    status = ""
    print('Waiting for stack update to complete')
    rollback = False
    while poll_progress:
        sys.stdout.write('-')
        time.sleep(2)
        response = cf.describe_stacks(StackName=stack_id)

        for stack_name in response['Stacks']:
            if stack_name['StackId'] == stack_id:
                if stack_name['StackStatus'] != status:
                    status = stack_name['StackStatus']
                    sys.stdout.write('>' + status)
                    poll_progress = 'IN_PROGRESS' in status

                if 'ROLLBACK' in stack_name['StackStatus']:
                    rollback = True

        sys.stdout.flush()

    print("")
    print("Stack status: ", status)

    if rollback:
        raise BuildFailure(cf, stack_id)

    return


if __name__ == '__main__':

    class Stack(Enum):
        common = 'common'
        cognito = 'cognito'
        batch = 'batch'
        cache = 'cache'
        author = 'author'

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

    exit_code = main(opts.operation, str(opts.stack), opts.config)
    sys.exit(exit_code)
