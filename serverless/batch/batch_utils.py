import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

batch = boto3.client('batch')
ssm = boto3.client('ssm')


def submit_job(stack_prefix, 
               stage,
               job_project,
               job_name,
               job_arn,
               job_parameters):

    try:
        # Get current job queue
        job_queue = ssm.get_parameter(
            Name='/{}/{}/batch/JobQueueARN'.format(stack_prefix, stage)
        )['Parameter']['Value']

        # Get current job definition
        job_definition = ssm.get_parameter(
            Name='/{}/{}/{}/{}'.format(stack_prefix, stage, job_project, job_arn)
        )['Parameter']['Value']

        print('Parameters:' + json.dumps(job_parameters, indent=2))

        # Submit a Batch Job
        response = batch.submit_job(
            jobQueue=job_queue,
            jobName=job_name,
            jobDefinition=job_definition,
            parameters=job_parameters
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


def check_status_job(job_id):
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

