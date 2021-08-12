import boto3

ssm = boto3.client("ssm")


def write_event(event, context):
    # Just print and return the event
    print(event)

    response = ssm.get_parameter(Name="/minerva-test/dev/batch/LambdaWriteEvent")

    print(response)

    return event
