# Minerva Infrastructure

This repository contains the templates necessary to deploy the minerva platform.
It is comprised of some cloudformation and serverless configurations.

## Prerequisites
- A VPC in the desired region.
- A pair of public subnets in the VPC.
- A pair of private subnets with NAT gateways configured in the VPC.
- A default security group which allows communication in/out from itself.
- A security group which allows SSH communication to EC2 instances as required.
- A Cognito user pool.
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
# ECS optimised AMI upon which to build the BatchAMI
BaseAMI: ami-5253c32d
# EFS Volume specific AMI (built on ECS optimized AMI) to use for Batch
BatchAMI: ami-12345678
# SSH Key Name to use for any instances
SSHKeyName: ec2_ssh_id
# SSH Security Group to use for an instances
SSHSecurityGroup: sg-12345678
# Use existing subnets
SubnetsPublic:
  - subnet-12345678
  - subnet-87654321
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
# Cognito User Pool ARN
CognitoUserPool: arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_12345678
# Database password
DatabasePassword: password
```

## Hardcoded properties

These are currently hardcoded, but should really be driven from the
configuration file.

- serverless, db, service
- serverless, db, Default VPC for SSM
- serverless, db, subnetIds
- serverless, db, deploymentBucket
- serverless, db, STACK_PREFIX
- serverless, db, STAGE
- serverless, batch, service
- serverless, batch, Default VPC for SSM
- serverless, batch, subnetIds
- serverless, batch, deploymentBucket
- serverless, batch, STACK_PREFIX
- serverless, batch, STAGE
- serverless, api, service
- serverless, api, Default VPC for SSM
- serverless, api, subnetIds
- serverless, api, deploymentBucket
- serverless, api, STACK_PREFIX
- serverless, api, STAGE
- serverless, api, restApiId
- serverless, api, restApiRootResourceId
- serverless, api, /image/{uuid}

## Instructions

1. Deploy the common cloudformation infrastructure
2. Build the Batch AMI
3. Deploy the Batch cloudformation infrastructure
4. Deploy the db serverless infrastructure
5. Deploy the batch serverless infrastructure
6. Deploy the api serverless infrastructure
7. Run AWS lambda `initdb` method to initialise the database
