from typing import Any, Callable, Dict, Union, List
from functools import wraps
import os
from multiprocessing.pool import ThreadPool
from io import BytesIO
import base64
import logging
import boto3
import math
from botocore.exceptions import ClientError
import re
import json
from datetime import date, datetime
import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
import xml.etree.ElementTree as ET
from minerva_db.sql.api import Client
from minerva_lib import blend

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']
# TODO Handle different versions of the schema
OME_NS = 'http://www.openmicroscopy.org/Schemas/OME/2016-06'

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


class TileBoundError(Exception):
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


def make_binary_response(code: int, body: np.ndarray) -> Dict[str, Any]:
    '''Build a binary response.

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
                return make_binary_response(code, fn(self, event, context))
            except KeyError as e:
                return make_response(400, {'error': str(e)})
            except ValueError as e:
                return make_response(422, {'error': str(e)})
            except AuthError as e:
                return make_response(403, {'error': str(e)})
            except TileBoundError as e:
                return make_response(404, {'error': str(e)})
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


# TODO Refactor the meat of this as it's largely taken from db handler
def handle_missing_tile(client, uuid, x, y, z, t, c, level, key):

    image = client.get_image(uuid)
    bfu_uuid = image['bfu_uuid']
    bfu = client.get_bfu(bfu_uuid)

    if bfu['complete'] is not True:
        raise ValueError(
            f'Image has not been processed yet: {uuid}'
        )

    obj = boto3.resource('s3').Object(bucket.split(':')[-1],
                                      f'{bfu_uuid}/metadata.xml')
    body = obj.get()['Body']
    data = body.read()
    stream = BytesIO(data)
    e_root = ET.fromstring(stream.getvalue().decode('UTF-8'))
    e_image = e_root.find('ome:Image[@ID="Image:{}"]'.format(uuid),
                          {'ome': OME_NS})
    e_pixels = e_image.find('ome:Pixels', {'ome': OME_NS})

    size_c = int(e_pixels.attrib['SizeC'])
    size_t = int(e_pixels.attrib['SizeT'])
    size_x = math.ceil(int(e_pixels.attrib['SizeX']) / 1024)
    size_y = math.ceil(int(e_pixels.attrib['SizeY']) / 1024)
    size_z = int(e_pixels.attrib['SizeZ'])
    size_level = image['pyramid_levels']

    if 0 > c or c >= size_c:
        raise TileBoundError(
            f'Requested channel index ({c}) outside range (0 - {size_c})'
        )
    elif 0 > t or t >= size_t:
        raise TileBoundError(
            f'Requested t index ({t}) outside range (0 - {size_t})'
        )
    elif 0 > x or x >= size_x:
        raise TileBoundError(
            f'Requested x index ({x}) outside range (0 - {size_x})'
        )
    elif 0 > y or y >= size_y:
        raise TileBoundError(
            f'Requested y index ({y}) outside range (0 - {size_y})'
        )
    elif 0 > z or z >= size_z:
        raise TileBoundError(
            f'Requested z index ({z}) outside range (0 - {size_z})'
        )
    elif 0 > level or level >= size_level:
        raise TileBoundError(
            f'Requested level index ({level}) outside range (0 - {size_level})'
        )
    else:
        raise Exception(f'Internal Server Error: Requested tile ({key}) not'
                        'found, but should exist')


def _s3_get(client, bucket, uuid, x, y, z, t, c, level):
    '''Fetch a specific PNG from S3 and decode'''

    # Use the indices to build the key
    key = f'{uuid}/C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}.png'

    try:
        obj = boto3.resource('s3').Object(bucket, key)
        body = obj.get()['Body']
        data = body.read()
        stream = BytesIO(data)
        image = cv2.imdecode(np.fromstring(stream.getvalue(),
                                           dtype=np.uint8), 0)
        return image

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            handle_missing_tile(client, uuid, x, y, z, t, c, level, key)
        else:
            raise e


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

        # Prepare for blending
        args = [(self.client, bucket.split(':')[-1], uuid, x, y, z, t,
                 channel['index'], level) for channel in channels]

        # TODO Blend images as they are received instead of waiting for all.
        # Either prepare in parallel (might be worth it as we get more vCPUs
        # with higher memory reservations) then blend in a thread safe manner
        # or at least start processing each tile as it comes in

        # Fetch raw tiles in parallel
        try:
            pool = ThreadPool(processes=len(channels))
            images = pool.starmap(_s3_get, args)
        finally:
            pool.close()

        # Update channel dictionary with image data
        for channel, image in zip(channels, images):
            channel['image'] = image

        # Blend the raw tiles
        composite = blend.composite_channels(channels)

        # CV2 requires 0 - 255 values
        composite *= 255

        # Encode rendered image as PNG
        return cv2.imencode('.png', composite)[1]


handler = Handler()
render_tile = handler.render_tile
