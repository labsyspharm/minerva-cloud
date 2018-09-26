import sys
import os
import argparse
from ruamel.yaml import YAML
import boto3

yaml = YAML()


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

    region = config['Region']
    prefix = config['StackPrefix']
    stage = config['Stage']
    name = '{}-cf-cognito'.format(prefix)
    project_tag = config['ProjectTag']

    fn = os.path.join(os.path.dirname(__file__), 'main.yml')

    with open(fn, 'r') as f:
        template_body = f.read()

    cf = boto3.client('cloudformation', region_name=region)

    if args.operation == 'create':
        cf_method = cf.create_stack
    elif args.operation == 'update':
        print('Updating cognito not recommended because updating of a user '
              'pool requiring replacement will result in an empty pool')
        sys.exit(1)
        # cf_method = cf.update_stack
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
