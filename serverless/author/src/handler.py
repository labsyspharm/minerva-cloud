import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from typing import Any, Callable, Dict, Union, List
from functools import wraps
import os
import boto3
import re
import json
from datetime import date, datetime
import uuid
from .storage import AuthorS3Storage
from .publish import StoryPublisher
import datetime

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')
s3 = boto3.client('s3')

bucket_parameter = ssm.get_parameter(Name='/{}/{}/author/S3BucketStoryARN'.format(STACK_PREFIX, STAGE))
bucket = bucket_parameter["Parameter"]["Value"].split(':')[-1]
storage = AuthorS3Storage(bucket)

bucket_parameter = ssm.get_parameter(Name='/{}/{}/author/S3BucketPublishedARN'.format(STACK_PREFIX, STAGE))
published_bucket = bucket_parameter["Parameter"]["Value"].split(':')[-1]

def json_custom(obj: Any) -> str:
    '''JSON serializer for extra types.
    '''

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def make_response(code: int, body: Union[Dict, List]) -> Dict[str, Any]:
    '''Build a response.

        Args:
            code: HTTP response code.
            body: Python dictionary or list to jsonify.

        Returns:
            Response object compatible with AWS Lambda Proxy Integration
    '''

    return {
        'statusCode': code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true'
        },
        'body': json.dumps(body, default=json_custom)
    }

def response(code: int) -> Callable[..., Dict[str, Any]]:
    '''Decorator for turning exceptions into responses.

    KeyErrors are assumed to be missing parameters (either query or path) and
    mapped to 400.

    ValueErrors are assumed to be parameters (either query or path) that fail
    validation and mapped to 422.

    AuthError is mapped to 403.

    Any other Exceptions are unknown and mapped to 500.

    Args:
        code: HTTP status code.

    Returns:
        Function which returns a response object compatible with AWS Lambda
        Proxy Integration.
    '''

    def wrapper(fn):
        @wraps(fn)
        def wrapped(self, event, context):

            # Execute the requested function and make a response or error
            # response
            try:
                self.body = _event_body(event)
                self.user_uuid = _event_user(event)
                self.content_type = "application/json"

                return make_response(code, fn(self, event, context))
            except ValueError as e:
                logger.debug(e)
                return make_response(400, {'error': str(e)})
            except Exception as e:
                logger.exception(e)
                return make_response(500, {'error': str(e)})

        return wrapped
    return wrapper


def _event_body(event):
    if 'body' in event and event['body'] is not None:
        return json.loads(event['body'])
    return {}


def _event_user(event):
    print(event)
    if 'claims' in event['requestContext']['authorizer']:
        uuid = event['requestContext']['authorizer']['claims']['cognito:username']
    else:
        uuid = event['requestContext']['authorizer']['principalId']
    _validate_uuid(uuid)
    return uuid


def _event_path_param(event, key):
    return event['pathParameters'][key]


def _event_query_param(event, key, multi=False):
    if 'queryStringParameters' not in event:
        return None
    if event['queryStringParameters'] is None:
        return None
    if key not in event['queryStringParameters']:
        return None

    value = event['queryStringParameters'][key]
    if multi is True:
        return value.split(',')
    return value


_valid_uuid = re.compile(
    '^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$'
)


def _validate_uuid(u):
    if _valid_uuid.match(u) is None:
        raise ValueError('UUID is invalid. Valid uuids are of the form '
                         'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')


class Handler:

    def __init__(self):
        self.session = None
        self.client = None

    @response(201)
    def save_story(self, event, context):
        story = self.body
        self._validate_story(story)
        story_uuid = uuid.uuid4()
        story["uuid"] = str(story_uuid)
        story["last_updated"] = datetime.datetime.now().isoformat()
        story["author_uuid"] = self.user_uuid
        storage.save_story(json.dumps(story), story_uuid)
        return story

    @response(200)
    def update_story(self, event, context):
        story = self.body
        self._validate_story(story)
        story_uuid = story["uuid"]
        _validate_uuid(story_uuid)
        old_story = storage.get_story(story_uuid)
        story["last_updated"] = datetime.datetime.now().isoformat()
        story["author_uuid"] = old_story["author_uuid"]
        storage.save_story(json.dumps(story), story_uuid)
        return story

    @response(200)
    def get_story(self, event, context):
        story_uuid = _event_path_param(event, "uuid")
        _validate_uuid(story_uuid)
        story = storage.get_story(story_uuid)
        return story

    @response(200)
    def list_stories(self, event, context):
        stories = storage.list_stories()
        own_stories = {
            "stories": [story for story in stories["stories"] if story["author_uuid"] == self.user_uuid]
        }
        return own_stories

    @response(200)
    def publish_story(self, event, context):
        story_uuid = _event_path_param(event, "uuid")
        _validate_uuid(story_uuid)
        lambda_client = boto3.client("lambda")
        payload = {
            "story_uuid": story_uuid,
            "user_uuid": self.user_uuid
        }
        res = lambda_client.invoke(
            FunctionName="minerva-test-dev-publishStoryInternal",
            InvocationType="Event",
            Payload=json.dumps(payload)
        )
        #story = storage.get_story(story_uuid)
        #publisher = StoryPublisher(published_bucket)
        #publisher.publish(story, self.user_uuid)

    def publish_story_internal(self, event, context):
        story_uuid = event["story_uuid"]
        user_uuid = event["user_uuid"]
        _validate_uuid(story_uuid)
        story = storage.get_story(story_uuid)
        publisher = StoryPublisher(published_bucket)
        publisher.publish(story, user_uuid)

    def _validate_story(self, story):
        errors = []
        print("Validating story: " + str(story))
        if "imageUuid" not in story:
            errors.append("imageUuid missing")
        if "sample_info" not in story:
            errors.append("sample_info missing")
        if "waypoints" not in story:
            errors.append("waypoints missing")
        if "groups" not in story:
            errors.append("groups missing")

        if len(errors) > 0:
            error_message = ", ".join(errors)
            error_message = "Invalid story: " + error_message
            raise ValueError(error_message)

handler = Handler()
save_story = handler.save_story
update_story = handler.update_story
get_story = handler.get_story
list_stories = handler.list_stories
publish_story = handler.publish_story
publish_story_internal = handler.publish_story_internal
