import sys
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

    # Validate the number of subnets
    if len(config['SubnetsPublic']) != 2:
        print('Exactly 2 public subnets required')
        sys.exit(1)

    region = config['Region']
    prefix = config['StackPrefix']
    stage = config['Stage']
    name = '{}-cf-batch'.format(prefix)
    project_tag = config['ProjectTag']
    ami = config['BatchAMI']
    batch_cluster_ec2_min_cpus = config['BatchClusterEC2MinCpus']
    batch_cluster_ec2_max_cpus = config['BatchClusterEC2MaxCpus']
    batch_cluster_ec2_desired_cpus = config['BatchClusterEC2DesiredCpus']
    batch_cluster_spot_min_cpus = config['BatchClusterSpotMinCpus']
    batch_cluster_spot_max_cpus = config['BatchClusterSpotMaxCpus']
    batch_cluster_spot_desired_cpus = config['BatchClusterSpotDesiredCpus']
    batch_cluster_spot_bid_percentage = config['BatchClusterSpotBidPercentage']
    subnets_public = ','.join(config['SubnetsPublic'])

    with open('main.yml', 'r') as f:
        template_body = f.read()

    cf = boto3.client('cloudformation', region_name=region)

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
