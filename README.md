# Minerva Infrastructure

This repository contains the templates necessary to deploy the minerva platform.
It is comprised of some cloudformation and serverless configurations.

## Prerequisites
- A VPC in the desired region.
- A pair of public subnets in the VPC.
- A pair of private subnets with NAT gateways configured in the VPC.
- A default security group which allows communication in/out from itself.
- A security group which allows SSH communication to EC2 instances as required.
- A configuration file with these and some other properties.
- Standard roles for `BatchServiceRole`, `BatchInstanceRole` and
  `BatchSpotFleetRole`.
- A deployment bucket for serverless.

## Configuration File

```YAML
Region: us-east-1
StackPrefix: minerva-test
Stage: dev
ProjectTag: myproject
# Bucket that serverless will use as a staging area for deployment
DeploymentBucket: bucket-name
# VPC ID
VpcId: vpc-12345678
# ECS optimised AMI upon which to build the BatchAMI
BaseAMI: ami-5253c32d
# EFS Volume specific AMI (built on ECS optimized AMI) to use for Batch
BatchAMI: ami-12345678
# SSH Key Name to use for any instances
SSHKeyName: ec2_ssh_id
# SSH Security Group to use for an instances
DefaultSecurityGroup: sg-12345678
# SSH Security Group to use for an instances
SSHSecurityGroup: sg-87654321
# Use existing subnets
SubnetsPublic:
  - subnet-12345678
  - subnet-23456789
SubnetsPrivate:
  - subnet-34567890
  - subnet-45678901
# Use existing batch roles
BatchServiceRole: arn:aws:iam::123456789012:role/service-role/AWSBatchServiceRole
BatchInstanceRole: arn:aws:iam::123456789012:instance-profile/ecsInstanceRole
BatchSpotFleetRole: arn:aws:iam::123456789012:role/aws-ec2-spot-fleet-role
# Batch compute environments
BatchClusterEC2MinCpus: 0
BatchClusterEC2MaxCpus: 4
BatchClusterEC2DesiredCpus: 0
BatchClusterSpotMinCpus: 0
BatchClusterSpotMaxCpus: 16
BatchClusterSpotDesiredCpus: 0
BatchClusterSpotBidPercentage: 50
# Database password
DatabasePassword: password
```

## Instructions

1. Deploy the common cloudformation infrastructure
2. Deploy the cognito cloudformation infrastructure
3. Build the Batch AMI
4. Deploy the Batch cloudformation infrastructure
5. Deploy the db serverless infrastructure
6. Deploy the batch serverless infrastructure
7. Deploy the api serverless infrastructure
8. Run AWS lambda `initdb` method to initialise the database
