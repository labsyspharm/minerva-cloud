import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ["STACK_PREFIX"]
STAGE = os.environ["STAGE"]
JOB_QUEUE = f"/{STACK_PREFIX}/{STAGE}/batch/JobQueueARN"
JOB_DEF_SCAN = f"/{STACK_PREFIX}/{STAGE}/batch/BFScanJobDefinitionARN"
JOB_DEF_EXTRACT = f"/{STACK_PREFIX}/{STAGE}/batch/BFExtractJobDefinitionARN"

batch = boto3.client("batch")
ssm = boto3.client("ssm")


def prepare_environment(event, context):

    # Log the received event
    print("Received event: " + json.dumps(event, indent=2))

    try:
        # Get SSM parameters
        ssm_response = ssm.get_parameters(
            Names=[JOB_QUEUE, JOB_DEF_SCAN, JOB_DEF_EXTRACT]
        )

        ssm_params = {
            param["Name"]: param["Value"] for param in ssm_response["Parameters"]
        }

        job_queue = ssm_params[JOB_QUEUE]
        job_def_scan = ssm_params[JOB_DEF_SCAN]
        job_def_extract = ssm_params[JOB_DEF_EXTRACT]

        # Pass this to the step function to allow it to be upgraded to
        # something more useful later
        job_name = "bf_scan"

        # Set parameters
        batch_parameters = {
            "dir": event["import_uuid"],
            "extract_job_definition_arn": job_def_extract,
        }

        return {
            "job_queue": job_queue,
            "job_name": job_name,
            "job_definition": job_def_scan,
            "batch_parameters": batch_parameters,
        }

    except Exception as e:
        print(e)
        message = "Error preparing scan environment"
        print(message)
        raise Exception(message)
