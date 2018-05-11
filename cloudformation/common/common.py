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
                        choices=['create', 'upgrade', 'delete', 'validate'],
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
    name = '{}-common'.format(prefix)
    project_tag = config['ProjectTag']
    subnets = ','.join(config['Subnets'])

    with open('main.yml', 'r') as f:
        template_body = f.read()

    if args.operation == 'create':
        # Create the stack
        response = cf.create_stack(
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
                    'ParameterKey': 'Subnets',
                    'ParameterValue': subnets
                }
            ],
            Tags=[{
                'Key': 'project',
                'Value': project_tag
            }]
        )

        print('Stack Created: {}'.format(response['StackId']))


if __name__ == "__main__":
    main()
