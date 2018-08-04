import os
import json
import logging
import boto3
from functools import wraps
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from minerva_db.sql.api import Client

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

batch = boto3.client('batch')
ssm = boto3.client('ssm')
sfn = boto3.client('stepfunctions')
s3r = boto3.resource('s3')

raw_bucket = ssm.get_parameter(
    Name='/{}/{}/common/S3BucketRawARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

db_host = ssm.get_parameter(
    Name='/{}/{}/common/DBHost'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

db_port = ssm.get_parameter(
    Name='/{}/{}/common/DBPort'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

db_user = ssm.get_parameter(
    Name='/{}/{}/common/DBUser'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

db_password = ssm.get_parameter(
    Name='/{}/{}/common/DBPassword'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

db_name = ssm.get_parameter(
    Name='/{}/{}/common/DBName'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']


def _setup_db():
    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string)
    return sessionmaker(bind=engine)


DBSession = _setup_db()
session = None
client = None


def in_session(fn):
    @wraps(fn)
    def wrapper(event, context):

        # Create a session and client to handle this request
        global session
        global client
        session = DBSession()
        client = Client(session)

        return fn(event, context)
    return wrapper


@in_session
def addS3ManifestKeysToImport(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    import_uuid = event['import_uuid']
    prefix = f'{import_uuid}/'
    bucket = s3r.Bucket(raw_bucket.split(':')[-1])
    keys = [
        item.key.strip(prefix)
        for item
        in bucket.objects.filter(Prefix=prefix)
    ]
    client.add_keys_to_import(keys, import_uuid)


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
            Name='/{}/{}/batch/SyncJobDefinitionARN'.format(STACK_PREFIX,
                                                            STAGE)
        )['Parameter']['Value']

        # Get parameters
        bucket = raw_bucket.split(':')[-1]
        import_uuid = event['import_uuid']
        parameters = {
            's3uri': f's3://{bucket}/{import_uuid}',
            'dir': import_uuid
        }

        print('Parameters:' + json.dumps(parameters, indent=2))

        job_name = 'sync_s3_efs'

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


def start_scan_sfn(event, context):
    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    # Get the import_uuid from the event
    import_uuid = event

    try:

        # Get current job definition
        scan_sfn = ssm.get_parameter(
            Name='/{}/{}/batch/BFScanStepARN'.format(STACK_PREFIX, STAGE)
        )['Parameter']['Value']

        response = sfn.start_execution(
            stateMachineArn=scan_sfn,
            input=json.dumps({
              "import_uuid": import_uuid
            })
        )

        return response['executionArn']

    except Exception as e:
        print(e)
        message = 'Error starting Scan Step Function'
        print(message)
        raise Exception(message)
