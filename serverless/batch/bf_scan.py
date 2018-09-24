import os
import json
import logging
import boto3
from batch_utils import submit_batch_job, check_status_batch_job

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')

def submit_job(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    # Get parameters
    job_parameters = {
        'dir': event['import_uuid']
    }

    job_project = 'batch'
    job_name = 'bf_scan'
    job_arn = 'BFScanJobDefinitionARN'

    return submit_batch_job(STACK_PREFIX, STAGE, job_project, job_name, job_arn, job_parameters)


def check_status_job(event, context):
    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    # Get jobId from the event
    job_id = event

    return check_status_batch_job(job_id)

