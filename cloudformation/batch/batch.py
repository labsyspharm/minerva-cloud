import sys
import argparse
from ruamel.yaml import YAML
import boto3

yaml = YAML()
cf = boto3.client('cloudformation')


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('configfile', type=argparse.FileType('r'),
                        help='YAML configuration filename')
    parser.add_argument('operation',
                        choices=['create', 'update', 'delete', 'validate'],
                        help='Operation')
    args = parser.parse_args()

    try:
        config = yaml.load(args.configfile)
    except Exception as e:
        print('Error reading configuration YAML: {}'.format(e))
        sys.exit(1)

    # Validate the number of subnets
    if len(config['Subnets']) != 6:
        print('Exactly 6 subnets required for EFS Stack')
        sys.exit(1)

    prefix = config['StackPrefix']
    stage = config['Stage']
    name = '{}-batch'.format(prefix)
    project_tag = config['ProjectTag']
    ami = config['BatchAMI']
    batch_service_role = config['BatchServiceRole']
    batch_instance_role = config['BatchInstanceRole']
    batch_spot_fleet_role = config['BatchSpotFleetRole']
    subnets = ','.join(config['Subnets'])

    with open('main.yml', 'r') as f:
        template_body = f.read()

    if args.operation == 'create':
        cf_method = cf.create_stack
    elif args.operation == 'update':
        cf_method = cf.update_stack
    else:
        print('Method not implemented')
        sys.exit(1)

    response = cf_method(
        StackName=name,
        TemplateBody=template_body,
        Parameters=[
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
            },
            {
                'ParameterKey': 'BatchAMI',
                'ParameterValue': ami
            },
            {
                'ParameterKey': 'BatchServiceRole',
                'ParameterValue': batch_service_role
            },
            {
                'ParameterKey': 'BatchInstanceRole',
                'ParameterValue': batch_instance_role
            },
            {
                'ParameterKey': 'BatchSpotFleetRole',
                'ParameterValue': batch_spot_fleet_role
            },
            {
                'ParameterKey': 'Subnets',
                'ParameterValue': subnets
            }
        ],
        Capabilities=[
            'CAPABILITY_NAMED_IAM',
        ],
        Tags=[{
            'Key': 'project',
            'Value': project_tag
        }]
    )

    print('Stack {} completed: {}'.format(args.operation, response['StackId']))


if __name__ == "__main__":
    main()
