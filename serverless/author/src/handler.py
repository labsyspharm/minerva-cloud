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

def _get_ssm_parameter(name):
    bucket_parameter = ssm.get_parameter(Name='/{}/{}/author/{}'.format(STACK_PREFIX, STAGE, name))
    return bucket_parameter["Parameter"]["Value"].split(':')[-1]


bucket = _get_ssm_parameter("S3BucketStoryARN")
storage = AuthorS3Storage(bucket)
published_bucket = _get_ssm_parameter("S3BucketPublishedARN")
minerva_story_base_bucket = _get_ssm_parameter("S3MinervaStoryBaseBucketARN")
published_story_url = _get_ssm_parameter("URLPublishedStoryARN")

publisher = StoryPublisher(published_bucket,
                           get_image_lambda_name=f"{STACK_PREFIX}-{STAGE}-getImageDimensions",
                           render_tile_lambda_name=f"{STACK_PREFIX}-{STAGE}-renderTile",
                           render_group_lambda_name=f"{STACK_PREFIX}-{STAGE}-publishGroupInternal"
                           )

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
        if "author_uuid" not in old_story:
            story["author_uuid"] = self.user_uuid
        elif self.user_uuid not in old_story.get("author_uuid", ""):
            story["author_uuid"] = ",".join([old_story["author_uuid"], story["author_uuid"]])
        else:
            story["author_uuid"] = old_story.get("author_uuid", self.user_uuid)

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
            "stories": [story for story in stories["stories"] if self.user_uuid in story["author_uuid"]]
        }
        return own_stories

    @response(200)
    def publish_story(self, event, context):
        story_uuid = _event_path_param(event, "uuid")
        _validate_uuid(story_uuid)
        url = f"http:{published_story_url}/{story_uuid}/minerva-story/index.html"

        no_render_param = _event_query_param(event, "norender")
        render_images = no_render_param not in ["true", "1"]
        story = storage.get_story(story_uuid)
        minerva_browser_url = _get_ssm_parameter("MinervaBrowserURL")

        publisher.publish(story, self.user_uuid, minerva_browser_url, render_images)

        return {
            "bucket": published_bucket,
            "key": story_uuid,
            "url": url
        }

    @response(200)
    def get_published_status(self, event, context):
        story_uuid = _event_path_param(event, "uuid")
        status = publisher.get_published_status(story_uuid)
        url = f"http:{published_story_url}/{story_uuid}/minerva-story/index.html"
        return {
            "status": status,
            "url": url
        }

    def publish_group_internal(self, event, context):
        group = event["group"]
        image = event["image"]
        user_uuid = event["user_uuid"]
        sample_name = event["sample_name"]
        story_uuid = event["story_uuid"]

        publisher.render_group(context, group, image, user_uuid, sample_name, story_uuid)

    def _validate_story(self, story):
        # TODO - JSON schema validation
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
publish_group_internal = handler.publish_group_internal
get_published_status = handler.get_published_status
