from typing import Any, Callable, Dict
from functools import wraps
import os
from multiprocessing.pool import ThreadPool
from io import BytesIO
import base64
import logging
import boto3
import re
import json
from datetime import date, datetime
import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from minerva_db.sql.api import Client
from minerva_lib import blend

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')

# TODO Fully document types expected in API documentation
PATH_ERROR = ('Path must conform to format:'
              'x/y/z/t/l/c,color,min,max/c,color,min,max/...')

bucket = ssm.get_parameter(
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


class AuthError(Exception):
    pass


def _setup_db():
    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string)
    return sessionmaker(bind=engine)


DBSession = _setup_db()


def json_custom(obj: Any) -> str:
    '''JSON serializer for extra types.
    '''

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def make_response(code: int, body: np.ndarray) -> Dict[str, Any]:
    '''Build a response.

        Args:
            code: HTTP response code.
            body: Numpy array representing image.

        Returns:
            Response object compatible with AWS Lambda Proxy Integration
    '''

    return {
        'statusCode': code,
        'headers': {
            'Content-Type': 'image/png',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true'
        },
        'body': base64.b64encode(body).decode('utf-8'),
        'isBase64Encoded': True
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

            # Create a session and client to handle this request
            self.session = DBSession()
            self.client = Client(self.session)

            # Execute the requested function and make a response or error
            # response
            try:
                self.body = _event_body(event)
                self.user_uuid = _event_user(event)
                return make_response(code, fn(self, event, context))
            except KeyError as e:
                return make_response(400, {'error': str(e)})
            except ValueError as e:
                return make_response(422, {'error': str(e)})
            except AuthError as e:
                return make_response(403, {'error': str(e)})
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
    uuid = event['requestContext']['authorizer']['claims']['cognito:username']
    _validate_uuid(uuid)
    return uuid


def _event_path_param(event, key):
    return event['pathParameters'][key]


_valid_uuid = re.compile(
    '^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$'
)


def _validate_uuid(u):
    if _valid_uuid.match(u) is None:
        raise ValueError('UUID is invalid. Valid uuids are of the form '
                         'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')


def _s3_get(bucket, key):
    '''Fetch a specific PNG from S3 and decode'''

    obj = boto3.resource('s3').Object(bucket, key)
    body = obj.get()['Body']
    data = body.read()
    stream = BytesIO(data)
    image = cv2.imdecode(np.fromstring(stream.getvalue(), dtype=np.uint8), 0)
    return image


def _hex_to_bgr(color):
    '''Convert hex color to BGR'''

    # Check for the right format of hex value
    if len(color) != 6:
        raise ValueError('Hex color value {} invalid'.format(color))

    # Convert to BGR
    try:
        return tuple(int(color[i:i + 2], 16) for i in (4, 2, 0))
    except ValueError:
        raise ValueError('Hex color value {} invalid'.format(color))


def _parse_channel_params(channel_path_param):
    '''Parse index and rendering settings for a channel'''

    # Split the channel path parameter into individual parameters
    params = channel_path_param.split(',')

    # Check that the channel has the correct number of parameters
    if len(params) != 4:
        raise ValueError('Incorrect rendering setting:'
                         ' {}'.format(channel_path_param))

    # Convert index and rendering settings and return
    return {
        'index': int(params[0]),
        'color': np.float32([c / 255 for c in _hex_to_bgr(params[1])]),
        'min': np.float32(params[2]),
        'max':  np.float32(params[3])
    }


class Handler:

    def _has_permission(self, user: str, resource_type: str, resource: str,
                        permission: str):
        '''Determine if the given user has the required permission.

        Args:
            user: The user UUID.
            resource_type: The type of the resource.
            resource: The resource UUID.
            permission: The required permission.

        Raises:
            AuthError: If the user does not have permission.
        '''
        if not self.client.has_permission(user, resource_type, resource,
                                          permission):
            raise AuthError('Permission Denied')

    @response(200)
    def render_tile(self, event, context):
        '''Render the specified tile with the given settings'''

        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')

        x = int(_event_path_param(event, 'x'))
        y = int(_event_path_param(event, 'y'))
        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))
        level = int(_event_path_param(event, 'level'))

        # Split the channels path parameters
        channel_path_params = event['pathParameters']['channels'].split('/')

        # Read the path parameter for the channels and convert
        channels = [_parse_channel_params(param)
                    for param in channel_path_params]

        # Use the indices to build the key base
        key_base = (
            f'{uuid}/'
            'C{}'
            f'-T{t}-Z{z}-L{level}-Y{y}-X{x}.png'
        )

        # Prepare for blending
        args = [(bucket.split(':')[-1], key_base.format(channel['index']))
                for channel in channels]

        # TODO Blend images as they are received instead of waiting for all.
        # Either prepare in parallel (might be worth it as we get more vCPUs
        # with higher memory reservations) then blend in a thread safe manner
        # or at least start processing each tile as it comes in

        # Fetch raw tiles in parallel
        pool = ThreadPool(processes=len(channels))
        images = pool.starmap(_s3_get, args)
        pool.close()

        # Update channel dictionary with image data
        for channel, image in zip(channels, images):
            channel['image'] = image

        # Blend the raw tiles
        composite = blend.composite_channels(channels)

        # Encode rendered image as PNG
        return cv2.imencode('.png', composite)[1]


handler = Handler()
render_tile = handler.render_tile
