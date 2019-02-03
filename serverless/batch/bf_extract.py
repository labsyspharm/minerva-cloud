import os
import json
import logging
from uuid import uuid4
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
JOB_QUEUE = f'/{STACK_PREFIX}/{STAGE}/batch/JobQueueARN'

batch = boto3.client('batch')
ssm = boto3.client('ssm')
s3 = boto3.client('s3')

raw_bucket = ssm.get_parameter(
    Name='/{}/{}/common/S3BucketRawARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

tile_bucket = ssm.get_parameter(
    Name='/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE)
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
def register_fileset(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    import_uuid = event['import_uuid']
    files = event['files']
    reader = event['reader']
    reader_software = event['reader_software']
    reader_version = event['reader_version']

    # Generate a uuid for this fileset
    uuid = str(uuid4())

    # TODO Call the fileset something more sensible than just the first 128
    # characters of the last path component of the entrypoint
    entrypoint = files[0].split('/')[-1][:128]

    client.create_fileset(uuid, entrypoint, reader, reader_software,
                          reader_version, files, import_uuid)

    return uuid


def prepare_environment(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    try:
        # Get SSM parameters
        ssm_response = ssm.get_parameters(Names=[
            JOB_QUEUE
        ])

        ssm_params = {
            param['Name']: param['Value']
            for param in ssm_response['Parameters']
        }

        job_queue = ssm_params[JOB_QUEUE]
        job_definition = event['extract_job_definition_arn']

        # Set parameters
        batch_parameters = {
            'dir': event['import_uuid'],
            'file': event['files'][0],
            'reader': event['reader'],
            'reader_software': event['reader_software'],
            'reader_version': event['reader_version'],
            'fileset_uuid': event['fileset_uuid'],
            'bucket': tile_bucket.split(':')[-1]
        }

        # Pass this to the step function to allow it to be upgraded to
        # something more useful later
        job_name = 'bf_extract'

        return {
            'job_queue': job_queue,
            'job_name': job_name,
            'job_definition': job_definition,
            'batch_parameters': batch_parameters
        }

    except Exception as e:
        print(e)
        message = 'Error preparing extraction environment'
        print(message)
        raise Exception(message)


def _chunk(l, n):
    for i in range(0, len(l), n):
        yield l[i:i+n]


@in_session
def handle_raw_storage_level(event, context):

    # Log the received event
    print('Received event: ' + json.dumps(event, indent=2))

    import_uuid = event['import_uuid']
    files = event['files']

    # TODO client methods to get an ancestor
    import_ = client.get_import(import_uuid)['data']
    repository = client.get_repository(import_['repository_uuid'])['data']
    storage_level = repository['raw_storage']
    bucket = raw_bucket.split(':')[-1]

    if storage_level in ('Destroy', 'Archive'):
        keys = [f'{import_uuid}/{file}' for file in files]

        if storage_level == 'Destroy':
            logger.info('Destroying: ' + ', '.join(keys))
            objs = [{'Key': key} for key in keys]
            for chunk in _chunk(objs, 1000):
                response = s3.delete_objects(
                    Bucket=bucket,
                    Delete={
                        'Objects': chunk,
                        'Quiet': True
                    }
                )
                logger.error(str(response))
        elif storage_level == 'Archive':
            logger.info('Archiving: ' + ', '.join(keys))
            tagging = {
                'TagSet': [
                    {
                        'Key': 'archive',
                        'Value': 'true'
                    }
                ]
            }
            for key in keys:
                s3.put_object_tagging(
                    Bucket=bucket,
                    Key=key,
                    Tagging=tagging
                )
