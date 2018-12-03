import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']
JOB_QUEUE = f'/{STACK_PREFIX}/{STAGE}/batch/JobQueueARN'
JOB_DEF_SCAN = f'/{STACK_PREFIX}/{STAGE}/batch/BFScanJobDefinitionARN'
JOB_DEF_EXTRACT = f'/{STACK_PREFIX}/{STAGE}/batch/BFExtractJobDefinitionARN'

batch = boto3.client('batch')
ssm = boto3.client('ssm')


def submit_job(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    try:
        # Get SSM parameters
        ssm_response = ssm.get_parameters(Names=[
            JOB_QUEUE,
            JOB_DEF_SCAN,
            JOB_DEF_EXTRACT
        ])

        ssm_params = {
            param['Name']: param['Value']
            for param in ssm_response['Parameters']
        }

        job_queue = ssm_params[JOB_QUEUE]
        job_def_scan = ssm_params[JOB_DEF_SCAN]
        job_def_extract = ssm_params[JOB_DEF_EXTRACT]

        # Set parameters
        parameters = {
            'dir': event['import_uuid'],
            'extract_job_definition_arn': job_def_extract
        }

        print('Parameters:' + json.dumps(parameters, indent=2))

        job_name = 'bf_scan'

        # Submit a Batch Job
        response = batch.submit_job(
            jobQueue=job_queue,
            jobName=job_name,
            jobDefinition=job_def_scan,
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
