<img width="500px" src="./Minerva-Cloud_HorizLogo_RGB.svg" />

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# Minerva Cloud - AWS backend infrastructure

This repository contains the templates necessary to deploy the Minerva Cloud platform in AWS.
It contains CloudFormation templates for creating the AWS infrastructure (S3 buckets, database, Cognito userpool etc.),
and Serverless Framework configurations for creating various serverless applications.

## API Documentation

[Minerva API](https://labsyspharm.github.io/minerva-cloud/)

## Prerequisites
These need to be created manually in AWS console or with the AWS CLI:
- A VPC in the desired AWS region.
- A pair of public subnets in the VPC.
- A pair of private subnets with NAT gateways configured in the VPC.
- A default security group which allows communication in/out from itself.
- A security group which allows SSH communication to EC2 instances as required.
- A yaml configuration file with these and some other properties.
- A deployment bucket for Serverless Framework.

## Black

The code is formatted using black. This was implemented all-at-once, and for the most useful git blame, we suggest
you run

```
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## AWS Profile

If you need to use a different aws profile from the default one, to be able to access aws resources,
this can be setup with:
- export AWS_PROFILE=profile_name

## Configuration File

There is an example configuration file included in the repository: minerva-config.example.yml
You need to update the vpc, subnets and other values in the configuration file.

## Instructions

You can later update the stacks by replacing word "create" with "update"
Instructions below presume you have the configuration file in a folder named minerva-configs,
which is a sibling to the minerva-cloud project root directory.

Before deploying the various serverless applications, you should install the needed node packages by running within each serverless/* directory:
```bash
npm install
```

1. Deploy the common cloudformation infrastructure

```bash
# Run in /cloudformation
python cloudformation.py create common ../../minerva-configs/test/config.yml
```

2. Deploy the cognito cloudformation infrastructure

```bash
# Run in /cloudformation
python cloudformation.py create cognito ../../minerva-configs/test/config.yml
```

3. Build the Batch AMI (Amazon Machine Image)

```bash
# Run in /ami-builder
python build.py ../../minerva-configs/test/config.yml
```
After the image has been created, the Batch AMI ID must be added to config.yml.

4. Deploy the Batch cloudformation infrastructure

```bash
# Run in /cloudformation
python cloudformation.py create batch ../../minerva-configs/test/config.yml
```

5. Deploy the auth serverless infrastructure

```bash
# Run in /serverless/auth
serverless deploy --configfile ../../../minerva-configs/test/config.yml
```

6. Deploy the db serverless infrastructure

```bash
# Run in /serverless/db
serverless deploy --configfile ../../../minerva-configs/test/config.yml
```

7. Deploy the batch serverless infrastructure

```bash
# Run in /serverless/batch
serverless deploy --configfile ../../../minerva-configs/test/config.yml
```

8. Deploy the api serverless infrastructure

```bash
# Run in /serverless/api
serverless deploy --configfile ../../../minerva-configs/test/config.yml
```

9. Deploy the author serverless infrastructure (OPTIONAL)
* This is only for integrating Minerva Author with Minerva Cloud
```bash
# Run in /cloudformation
python cloudformation.py create author ../../minerva-configs/test/config.yml
# Run in /serverless/author
serverless deploy --configfile ../../../minerva-configs/test/config.yml
```

10. Run AWS lambda `initdb` function to initialise the database
* Find the function name (e.g. minerva-test-dev-initDb) from AWS Lambda console
* Open the function and click "Test"

11. Create some users using the AWS Cognito console
* The new users are automatically created in Minerva database by a Cognito trigger.
* The password has to be updated on the first sign-in
