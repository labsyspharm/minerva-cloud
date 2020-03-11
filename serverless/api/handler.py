import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

from typing import Any, Callable, Dict, Union, List
from functools import wraps, lru_cache
import os
from multiprocessing.dummy import Pool as ThreadPool
from io import BytesIO
import base64
import boto3
import math
from botocore.exceptions import ClientError
import re
import json
from datetime import date, datetime
import simplejpeg
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
import xml.etree.ElementTree as ET
from minerva_db.sql.api import Client
from minerva_lib import render
import time
import imageio

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


class AuthError(Exception):
    pass


class TileBoundError(Exception):
    pass


class AspectRatioError(Exception):
    pass


global_sessionmaker = None


def _setup_db():
    global global_sessionmaker
    if global_sessionmaker is not None:
        return global_sessionmaker

    response = ssm.get_parameters(
        Names=[
            '/{}/{}/common/DBHost'.format(STACK_PREFIX, STAGE),
            '/{}/{}/common/DBPort'.format(STACK_PREFIX, STAGE),
            '/{}/{}/common/DBUser'.format(STACK_PREFIX, STAGE),
            '/{}/{}/common/DBPassword'.format(STACK_PREFIX, STAGE),
            '/{}/{}/common/DBName'.format(STACK_PREFIX, STAGE)
        ]
    )
    def get_value(name):
        for p in response['Parameters']:
            if p['Name'].endswith(name):
                return p['Value']
        raise ValueError('Value not found for Parameter ' + name)

    db_host = get_value('DBHost')
    db_port = get_value('DBPort')
    db_user = get_value('DBUser')
    db_password = get_value('DBPassword')
    db_name = get_value('DBName')

    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string, pool_size=1)
    global_sessionmaker = sessionmaker(bind=engine)
    return global_sessionmaker


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
            'Content-Type': 'image/jpeg',
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
            except (ValueError, AspectRatioError) as e:
                return make_response(422, {'error': str(e)})
            except AuthError as e:
                return make_response(403, {'error': str(e)})
            except TileBoundError as e:
                return make_response(404, {'error': str(e)})
            except Exception as e:
                logger.exception(e)
                return make_response(500, {'error': str(e)})
            finally:
                self.session.close()

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


def _event_query_param(event, key, multi=False):
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


# TODO Refactor the meat of this as it's largely taken from db handler
def handle_missing_tile(client, uuid, x, y, z, t, c, level, key):

    image = client.get_image(uuid)
    fileset_uuid = image['fileset_uuid']
    fileset = client.get_fileset(fileset_uuid)

    if fileset['complete'] is not True:
        raise ValueError(
            f'Image has not been processed yet: {uuid}'
        )

    obj = boto3.resource('s3').Object(bucket.split(':')[-1],
                                      f'{fileset_uuid}/metadata.xml')
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

    start = time.time()
    # Use the indices to build the key
    key = f'{uuid}/C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}.png'

    try:
        logger.info("Fetching tile %s/%s", bucket, key)
        obj = boto3.resource('s3').Object(bucket, key)
        body = obj.get()['Body']
        data = body.read()
        t = round((time.time() - start) * 1000)

        stream = BytesIO(data)
        image = imageio.imread(stream, format="png")
        logger.info("%s - Fetch COMPLETE %s ms", key, str(t))
        return image

    except ClientError as e:
        logger.error(e)
        if e.response['Error']['Code'] == 'NoSuchKey':
            handle_missing_tile(client, uuid, x, y, z, t, c, level, key)
        else:
            raise e
    except Exception as e:
        logger.error(e)
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


def _channels_json_to_params(channels):
    params = []
    for channel in channels:
        params.append({
            'index': int(channel["id"]),
            'color': np.float32([c / 255 for c in _hex_to_bgr(channel["color"])]),
            'min': np.float32(channel["min"]),
            'max':  np.float32(channel["max"])
        })
    return params


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

        return self._render_tile(uuid, x, y, z, t, level, channels)

    @response(200)
    def prerendered_tile(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')

        x = int(_event_path_param(event, 'x'))
        y = int(_event_path_param(event, 'y'))
        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))
        level = int(_event_path_param(event, 'level'))
        channel_group_uuid = _event_path_param(event, 'channel_group')

        logger.info("Render tile L=%s X=%s Y=%s CG_uuid=%s START", level, x, y, channel_group_uuid)

        return self._prerendered_tile_cached(uuid, x, y, z, t, level, channel_group_uuid)

    @lru_cache(maxsize=512)
    def _prerendered_tile_cached(self, uuid, x, y, z, t, level, channel_group_uuid):
        rendering_settings = self.client.get_image_channel_group(channel_group_uuid)
        channels = _channels_json_to_params(rendering_settings.channels)

        return self._render_tile(uuid, x, y, z, t, level, channels)

    def _render_tile(self, uuid, x, y, z, t, level, channels):
        total_start = time.time()
        # Prepare for blending
        args = [(self.client, bucket.split(':')[-1], uuid, x, y, z, t,
                 channel['index'], level) for channel in channels]

        # TODO Blend images as they are received instead of waiting for all.
        # Either prepare in parallel (might be worth it as we get more vCPUs
        # with higher memory reservations) then blend in a thread safe manner
        # or at least start processing each tile as it comes in
        # UPDATE: Tried starting blending parallel with S3 downloads, but it
        # didn't gain speed, it was actually a bit slower..

        # Fetch raw tiles in parallel
        logger.info("Start fetching images for channel tiles from S3")
        start = time.time()
        try:
            pool = ThreadPool(len(channels))
            images = pool.starmap(_s3_get, args)
        finally:
            pool.close()

        t = round((time.time() - start) * 1000)
        logger.info("All channel tiles fetched in %s ms", t)
        # Update channel dictionary with image data
        for channel, image in zip(channels, images):
            channel['image'] = image

        # Blend the raw tiles
        composite_start = time.time()
        composite = render.composite_channels(channels)
        composite_time = round((time.time() - composite_start) * 1000)
        logger.info("composite_channels time: %s ms", composite_time)

        # CV2 requires 0 - 255 values
        composite *= 255
        composite = composite.astype(np.uint8, copy=False)

        # Encode rendered image as JPG
        #encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        #img = cv2.imencode('.jpg', composite, encode_param)[1]
        img = simplejpeg.encode_jpeg(composite, quality=90, colorspace="BGR")
        print(len(img))
        total_time = round((time.time() - total_start) * 1000)
        logger.info("Render tile L=%s X=%s Y=%s DONE, total time: %s ms", level, x, y, total_time)
        return img

    @response(200)
    def render_region(self, event, context):
        '''Render the specified region with the given settings'''

        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')

        x = int(_event_path_param(event, 'x'))
        y = int(_event_path_param(event, 'y'))
        width = int(_event_path_param(event, 'width'))
        height = int(_event_path_param(event, 'height'))
        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))

        # Split the channels path parameters
        channel_path_params = event['pathParameters']['channels'].split('/')

        # Read the path parameter for the channels and convert
        channels = [_parse_channel_params(param)
                    for param in channel_path_params]

        # Read the optional query parameters for output shape
        output_width = event['queryStringParameters'].get('output-width')
        output_height = event['queryStringParameters'].get('output-height')
        output_width = int(output_width) if output_width is not None else None
        output_height = (int(output_height)
                         if output_height is not None else None)

        # Set prefer_higher_resolution from query parameter
        prefer_higher_resolution = (
            event['queryStringParameters'].get('prefer-higher-resolution')
        )
        prefer_higher_resolution = (prefer_higher_resolution.lower() == 'true'
                                    if prefer_higher_resolution is not None
                                    else False)

        # Query the shape of the full image
        image = self.client.get_image(uuid)
        fileset_uuid = image['data']['fileset_uuid']
        fileset = self.client.get_fileset(fileset_uuid)

        if fileset['data']['complete'] is not True:
            raise ValueError(
                f'Fileset has not had metadata extracted yet: {fileset_uuid}'
            )

        obj = boto3.resource('s3').Object(bucket.split(':')[-1],
                                          f'{fileset_uuid}/metadata.xml')
        body = obj.get()['Body']
        data = body.read()
        stream = BytesIO(data)
        e_root = ET.fromstring(stream.getvalue().decode('UTF-8'))
        e_image = e_root.find('ome:Image[@ID="Image:{}"]'.format(uuid),
                              {'ome': OME_NS})
        e_pixels = e_image.find('ome:Pixels', {'ome': OME_NS})

        image_shape = (int(e_pixels.attrib['SizeX']),
                       int(e_pixels.attrib['SizeY']))

        # Query the number of levels available
        level_count = image['data']['pyramid_levels']

        # Create shape tuples
        tile_shape = (1024, 1024)
        target_shape = (height, width)

        # Get the optimum level of the pyramid from which to use tiles
        try:
            output_max = max(
                [d for d in (output_height, output_width) if d is not None]
            )
            level = render.get_optimum_pyramid_level(image_shape, level_count,
                                                     output_max,
                                                     prefer_higher_resolution)
        except ValueError:
            level = 0

        # Transform origin and shape of target region into that required for
        # the pyramid level being used
        origin = render.transform_coordinates_to_level((x, y), level)
        shape = render.transform_coordinates_to_level(
            target_shape,
            level
        )

        # Calculate the scaling factor
        if output_width is not None:
            if output_height is not None:
                # Use both supplied scaling factors
                scaling_factor = (output_height / shape[0],
                                  output_width / shape[1])
            else:
                # Calculate scaling factor from output_width only
                scaling_factor = output_width / shape[1]
        else:
            if output_height is not None:
                # Calcuate scaling factor from output_height only
                scaling_factor = output_height / shape[0]
            else:
                # No scaling
                scaling_factor = 1

        args = []
        tiles = []
        for channel in channels:

            color = channel['color']
            _id = channel['index']
            _min = channel['min']
            _max = channel['max']

            for indices in render.select_grids(tile_shape, origin, shape):

                (i, j) = indices

                # Disallow negative tiles
                if i < 0 or j < 0:
                    continue

                # Add to list of tiles to fetch
                args.append((self.client,
                             bucket.split(':')[-1],
                             uuid,
                             i,
                             j,
                             z,
                             t,
                             _id,
                             level))

                # Add to list of tiles
                tiles.append({
                    'grid': (i, j),
                    'color': color,
                    'min': _min,
                    'max': _max
                })

        # Fetch raw tiles in parallel
        try:
            pool = ThreadPool(len(args))
            images = pool.starmap(_s3_get, args)
        finally:
            pool.close()

        # Update tiles dictionary with image data
        for image_tile, image in zip(tiles, images):
            image_tile['image'] = image

        # Blend the raw tiles
        composite = render.composite_subtiles(tiles, tile_shape, origin, shape)

        # Rescale for desired output size
        if scaling_factor != 1:
            scaled = render.scale_image_nearest_neighbor(composite,
                                                         scaling_factor)
        else:
            scaled = composite

        #  requires 0 - 255 values
        scaled *= 255
        scaled = scaled.astype(np.uint8, copy=False)

        # Encode rendered image as JPG
        img = simplejpeg.encode_jpeg(scaled, quality=90, colorspace="BGR")
        return img


handler = Handler()
render_tile = handler.render_tile
render_region = handler.render_region
prerendered_tile = handler.prerendered_tile
