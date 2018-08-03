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

```bash
cd cloudformation/common
python common.py ../../../minerva-configs/test/config.yml
```

2. Deploy the cognito cloudformation infrastructure

```bash
cd cloudformation/cognito
python cognito.py ../../../minerva-configs/test/config.yml
```

3. Build the Batch AMI

```bash
cd ami-builder
python build.py ../../../minerva-configs/test/config.yml
```

4. Deploy the Batch cloudformation infrastructure

```bash
cd cloudformation/batch
python batch.py ../../../minerva-configs/test/config.yml
```

5. Deploy the db serverless infrastructure

```bash
cd serverless/db
serverless deploy --config ../../../minerva-configs/test/config.yml
```

6. Deploy the batch serverless infrastructure

```bash
cd serverless/batch
serverless deploy --config ../../../minerva-configs/test/config.yml
```

7. Deploy the api serverless infrastructure

```bash
cd serverless/api
serverless deploy --config ../../../minerva-configs/test/config.yml
```

8. Run AWS lambda `initdb` method to initialise the database

9. Create some users using the AWS Cognito console
