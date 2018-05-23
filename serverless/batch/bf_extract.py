import os
import json
import logging
from uuid import uuid4
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

batch = boto3.client('batch')
ssm = boto3.client('ssm')


def register_bfu(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    import_uuid = event['importUuid']
    fileset = event['fileset']
    bioformats_reader = event['bioformatsReader']

    # Generate a uuid for this BFU
    bfu_uuid = str(uuid4())

    # Just print details instead of registering in the database for now
    # TODO Write to database
    print(json.dumps({
        'importUuid': import_uuid,
        'fileset': fileset,
        'bioformatsReader': bioformats_reader,
        'bfuUuid': bfu_uuid
    }))

    return bfu_uuid


def submit_job(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    try:
        # Get current job queue
        job_queue = ssm.get_parameter(
            Name='/{}/{}/batch/JobQueueARN'.format(STACK_PREFIX, STAGE)
        )['Parameter']['Value']

        # Get current job definition
        job_definition = ssm.get_parameter(
            Name='/{}/{}/batch/BFExtractJobDefinitionARN'.format(STACK_PREFIX,
                                                                 STAGE)
        )['Parameter']['Value']

        # Get tile bucket name from ARN
        bucket = ssm.get_parameter(
            Name='/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX,
                                                        STAGE)
        )['Parameter']['Value'].split(':')[-1]

        # Get parameters
        parameters = {
            'dir': event['importUuid'],
            'file': event['fileset'][0],
            'reader': event['bioformatsReader'],
            'bfuUuid': event['bfuUuid'],
            'bucket': bucket
        }

        print('Parameters:' + json.dumps(parameters, indent=2))

        job_name = 'bf_extract'

        # Submit a Batch Job
        response = batch.submit_job(
            jobQueue=job_queue,
            jobName=job_name,
            jobDefinition=job_definition,
            parameters=parameters
        )

        # Log response from AWS Batch
        print('Response: ' + json.dumps(response, indent=2))

        # Return the jobId
        return response['jobId']

    except Exception as e:
        print(e)
        message = 'Error submitting Batch Job'
        print(message)
        raise Exception(message)


def check_status_job(event, context):
    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    # Get jobId from the event
    job_id = event

    try:
        # Call DescribeJobs
        response = batch.describe_jobs(jobs=[job_id])

        # Log response from AWS Batch
        print('Response: ' + json.dumps(response, indent=2))

        # Return the jobtatus
        return response['jobs'][0]['status']

    except Exception as e:
        print(e)
        message = 'Error getting Batch Job status'
        print(message)
        raise Exception(message)
