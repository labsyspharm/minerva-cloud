import logging
import sys

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from typing import Any, Callable, Dict, Union, List
from functools import wraps
import os
from multiprocessing.dummy import Pool as ThreadPool
from io import BytesIO
import base64
import boto3
from botocore.exceptions import ClientError
import re
import json
from datetime import date, datetime
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from minerva_db.sql.miniclient.miniclient import MiniClient
from minerva_lib import render, autosettings
import time
import tifffile
import imagecodecs
import redis

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']
# TODO Handle different versions of the schema
OME_NS = 'http://www.openmicroscopy.org/Schemas/OME/2016-06'

ssm = boto3.client('ssm')

# TODO Fully document types expected in API documentation
PATH_ERROR = ('Path must conform to format:'
              'x/y/z/t/l/c,color,min,max/c,color,min,max/...')

_parameters = None
def get_parameter(key):
    global _parameters
    if _parameters is None:
        _parameters = {}
        parameters_res = []
        #  10 parameters at most can be fetched in one request, use more and boto3 will throw an error
        #  Let's split the parameter fetching between "common" and "cache"
        #  TODO consolidate parameters to get all in one request
        response = ssm.get_parameters(
            Names=[
                '/{}/{}/common/DBHost'.format(STACK_PREFIX, STAGE),
                '/{}/{}/common/DBPort'.format(STACK_PREFIX, STAGE),
                '/{}/{}/common/DBUser'.format(STACK_PREFIX, STAGE),
                '/{}/{}/common/DBPassword'.format(STACK_PREFIX, STAGE),
                '/{}/{}/common/DBName'.format(STACK_PREFIX, STAGE),
                '/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE)
            ]
        )
        parameters_res.extend(response['Parameters'])

        response = ssm.get_parameters(
            Names=[
                '/{}/{}/cache/ElastiCacheHost'.format(STACK_PREFIX, STAGE),
                '/{}/{}/cache/ElastiCachePort'.format(STACK_PREFIX, STAGE),
                '/{}/{}/cache/ElastiCacheHostRaw'.format(STACK_PREFIX, STAGE),
                '/{}/{}/cache/ElastiCachePortRaw'.format(STACK_PREFIX, STAGE),
                '/{}/{}/cache/EnableRenderedCache'.format(STACK_PREFIX, STAGE),
                '/{}/{}/cache/EnableRawCache'.format(STACK_PREFIX, STAGE)
            ]
        )
        parameters_res.extend(response['Parameters'])
        for p in parameters_res:
            _key = p['Name']
            _value = p['Value']
            _parameters[_key] = _value

    return _parameters[key]


bucket = get_parameter('/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE))
pool = ThreadPool(6)

# Initialize Redis cache for prerendered tiles
cache_host = get_parameter('/{}/{}/cache/ElastiCacheHost'.format(STACK_PREFIX, STAGE))
cache_port = get_parameter('/{}/{}/cache/ElastiCachePort'.format(STACK_PREFIX, STAGE))
enable_rendered_cache = get_parameter('/{}/{}/cache/EnableRenderedCache'.format(STACK_PREFIX, STAGE))
redis_client = None
if cache_host is not None and enable_rendered_cache == "1" and os.environ.get("AWS_EXECUTION_ENV") is not None:
    logging.info("Connecting to prerendered tiles Redis host: %s:%s", cache_host, cache_port)
    redis_client = redis.Redis(host=cache_host, port=cache_port, socket_connect_timeout=1)
else:
    logging.info("Rendered tiles cache is disabled")
# Initialize Redis cache for raw tiles
cache_host_raw = get_parameter('/{}/{}/cache/ElastiCacheHostRaw'.format(STACK_PREFIX, STAGE))
cache_port_raw = get_parameter('/{}/{}/cache/ElastiCachePortRaw'.format(STACK_PREFIX, STAGE))
enable_raw_cache = get_parameter('/{}/{}/cache/EnableRawCache'.format(STACK_PREFIX, STAGE))
redis_client_raw = None
if cache_host is not None and enable_raw_cache == "1" and os.environ.get("AWS_EXECUTION_ENV") is not None:
    logging.info("Connecting to raw tiles Redis host: %s:%s", cache_host_raw, cache_port_raw)
    redis_client_raw = redis.Redis(host=cache_host_raw, port=cache_port_raw, socket_connect_timeout=1)
else:
    logging.info("Raw tiles cache is disabled")

class AuthError(Exception):
    pass


class TileBoundError(Exception):
    pass


class AspectRatioError(Exception):
    pass

def _setup_db():
    db_host = get_parameter('/{}/{}/common/DBHost'.format(STACK_PREFIX, STAGE))
    db_port = get_parameter('/{}/{}/common/DBPort'.format(STACK_PREFIX, STAGE))
    db_user = get_parameter('/{}/{}/common/DBUser'.format(STACK_PREFIX, STAGE))
    db_password = get_parameter('/{}/{}/common/DBPassword'.format(STACK_PREFIX, STAGE))
    db_name = get_parameter('/{}/{}/common/DBName'.format(STACK_PREFIX, STAGE))

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


def make_binary_response(code: int, body: np.ndarray, content_type="image/jpeg") -> Dict[str, Any]:
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
            'Content-Type': content_type,
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

            # Execute the requested function and make a response or error
            # response
            try:
                self.body = _event_body(event)
                self.user_uuid = _event_user(event)
                print(event)
                self.content_type = "image/jpeg"
                binary = True
                if "accept" in event["headers"]:
                    accept = event["headers"]["accept"]
                    accept_values = accept.split(',')
                    if "application/json" in accept_values:
                        binary = False
                    # Disable webp for now because compression is slow
                    #if "image/webp" in accept_values:
                    #    self.content_type = "image/webp"

                if binary:
                    return make_binary_response(code, fn(self, event, context), content_type=self.content_type)
                else:
                    return make_response(code, fn(self, event, context))

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
                if self.session is not None:
                    self.session.close()

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


# TODO Refactor the meat of this as it's largely taken from db handler
def handle_missing_tile(uuid, x, y, z, t, c, level):
    raise TileBoundError(
        f'Requested tile not found uuid={uuid} c={c} x={x} y={y} z={z} t={t} level={level}'
    )

class S3TileProvider:
    def __init__(self, tile_bucket, missing_tile_callback=None, cache_client=None, compress=True):
        self.bucket = tile_bucket
        self.missing_tile_callback = missing_tile_callback
        self.cache_client = cache_client
        self.compress = compress

    def get_tile(self, uuid, x, y, z, t, c, level):
        '''Fetch a specific Tiff from S3 and decode'''

        start = time.time()
        # Use the indices to build the key
        key = f'{uuid}/C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}.tif'

        try:
            data = self._get_cached_object(key)
            if data is None:
                data = self._s3_get_object(key)
                self._put_cached_object(key, data)

            t = round((time.time() - start) * 1000)

            stream = BytesIO(data)
            image = tifffile.imread(stream)

            return image

        except ClientError as e:
            logger.error(e)
            logger.info("%s - Fetch COMPLETE %s ms", key, str(t))
            sys.stdout.flush()
            if e.response['Error']['Code'] == 'NoSuchKey' and self.missing_tile_callback is not None:
                self.missing_tile_callback(uuid, x, y, z, t, c, level)
            else:
                raise e
        except Exception as e:
            logger.error(e)
            raise e

    def _get_cached_object(self, key):
        data = None
        if self.cache_client is not None:
            logging.info("Get cache START")
            data = self.cache_client.get(key)
            logging.info("Get cache END")
        return data

    def _put_cached_object(self, key, data):
        if self.cache_client is not None:
            logging.info("Put cache START")
            self.cache_client.set(key, data)
            logging.info("Put cache END")

    def _s3_get_object(self, key):
        obj = boto3.resource('s3').Object(self.bucket, key)
        body = obj.get()['Body']
        return body.read()

# Example of a tile provider which loads the tiles from file system (e.g. local hard drive or NFS)
class FSTileProvider:
    def __init__(self, base_dir, missing_tile_callback=None, file_ext="tif"):
        self.base_dir = base_dir
        self.missing_tile_callback = missing_tile_callback
        self.file_ext = file_ext

    def get_tile(self, uuid, x, y, z, t, c, level):
        filename = f'C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}.{self.file_ext}'
        path = os.path.join(self.base_dir, uuid, filename)
        print(path)
        with open(path, mode='rb') as file:
            data = file.read()
            stream = BytesIO(data)
            image = tifffile.imread(stream)
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

def _hex_to_rgb(color):
    '''Convert hex color to RGB'''

    # Check for the right format of hex value
    if len(color) != 6:
        raise ValueError('Hex color value {} invalid'.format(color))

    # Convert to RGB
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
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
        'color': np.float32([c / 255 for c in _hex_to_rgb(params[1])]),
        'min': np.float32(params[2]),
        'max':  np.float32(params[3])
    }


def _channels_json_to_params(channels):
    params = []
    for channel in channels:
        params.append({
            'index': int(channel["id"]),
            'color': np.float32([c / 255 for c in _hex_to_rgb(channel["color"])]),
            'min': np.float32(channel["min"]),
            'max':  np.float32(channel["max"])
        })

    return params

def _parse_omero_tile(tile):
    t = tile.split(',')
    # level, x, y, width, height
    return int(t[0]), int(t[1]), int(t[2])

def _parse_omero_channels(c):
    # c=1|0:65535$FF0000,2|0:65535$00FF00...
    channels = []

    channels_str = c.split(',')
    for channel_str in channels_str:
        channel_id = int(channel_str.split('|')[0])
        if channel_id < 0:
            continue  # Channel is off

        settings = channel_str.split('|')[1]

        min_and_max = settings.split('$')[0]
        cmin = int(min_and_max.split(':')[0])
        cmax = int(min_and_max.split(':')[1])

        color = settings.split('$')[1]

        channel = {
            'index': channel_id-1,  # Omero channel indexing starts from 1
            'color': np.float32([c / 255 for c in _hex_to_rgb(color)]),
            'min': np.float32(cmin / 65535),
            'max': np.float32(cmax / 65535)
        }
        channels.append(channel)

    return channels

class Handler:

    def __init__(self):
        self.session = None
        self.client = None

    def _open_session(self):
        if self.session is None:
            # Create a session and client to handle this request
            self.session = DBSession()
            self.client = MiniClient(self.session)

    def _has_image_permission(self, user: str, resource: str,
                              permission: str):
        '''Determine if the given user has the required permission.

        Args:
            user: The user UUID.
            resource: The resource UUID.
            permission: The required permission.

        Raises:
            AuthError: If the user does not have permission.
        '''
        key = "{}/{}/{}".format(user, resource, permission)
        permitted = None
        if redis_client_raw is not None:
            permitted = redis_client_raw.get(key)
            if permitted is not None:
                permitted = bool(permitted)

        if permitted is None:
            self._open_session()
            permitted = self.client.has_image_permission(user, resource, permission)
            if redis_client_raw is not None:
                redis_client_raw.set(key, int(permitted), ex=300)

        if not permitted:
            raise AuthError('Permission Denied')

    def _get_prerendered_from_cache(self, uuid, x, y, z, t, level, channel_group_uuid):
        global redis_client
        if redis_client is None:
            return None
        key = f'{uuid}/T{t}-Z{z}-L{level}-Y{y}-X{x}/{channel_group_uuid}'
        try:
            tile_data = redis_client.get(key)
            if tile_data is not None:
                logging.debug("Redis cache HIT")
            else:
                logging.debug("Redis cache MISS")
            return tile_data
        except Exception as e:
            logging.error(e)
            logging.warning("Disabling cache")
            redis_client = None

    def _set_prerendered_to_cache(self, uuid, x, y, z, t, level, channel_group_uuid, tile_data):
        global redis_client
        if redis_client is None:
            return
        key = f'{uuid}/T{t}-Z{z}-L{level}-Y{y}-X{x}/{channel_group_uuid}'
        redis_client.set(key, tile_data)

    @response(200)
    def render_tile(self, event, context):
        '''Render the specified tile with arbitrary channels and color settings'''

        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(_event_path_param(event, 'x'))
        y = int(_event_path_param(event, 'y'))
        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))
        level = int(_event_path_param(event, 'level'))
        gamma = _event_query_param(event, 'gamma')
        if gamma is not None:
            gamma = float(gamma)

        # Split the channels path parameters
        channel_path_params = event['pathParameters']['channels'].split('/')

        # Read the path parameter for the channels and convert
        channels = [_parse_channel_params(param)
                    for param in channel_path_params]

        return self._render_tile(uuid, x, y, z, t, level, channels, gamma=gamma, codec='jpg')

    @response(200)
    def omero_render_tile(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))
        tile = _event_query_param(event, 'tile')
        level, x, y = _parse_omero_tile(tile)
        c = _event_query_param(event, 'c')
        channels = _parse_omero_channels(c)
        if not channels:
            #  TODO if all channels are off, should return HTTP status "No content"
            return np.zeros(shape=(1, 1, 3), dtype=np.uint8)

        return self._render_tile(uuid, x, y, z, t, level, channels, gamma=1, codec='jpg')

    @response(200)
    def prerendered_tile(self, event, context):
        '''Render the specified tile with previously saved rendering settings'''
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(_event_path_param(event, 'x'))
        y = int(_event_path_param(event, 'y'))
        z = int(_event_path_param(event, 'z'))
        t = int(_event_path_param(event, 't'))
        level = int(_event_path_param(event, 'level'))
        channel_group_uuid = _event_path_param(event, 'channel_group')

        logger.info("Render tile L=%s X=%s Y=%s CG_uuid=%s START", level, x, y, channel_group_uuid)

        tile_data = self._get_prerendered_from_cache(uuid, x, y, z, t, level, channel_group_uuid)
        if tile_data is not None:
            return tile_data

        self._open_session()
        rendering_settings = self.client.get_image_channel_group(channel_group_uuid)
        channels = _channels_json_to_params(rendering_settings.channels)

        # Always encode as jpg so that cached tiles are in consistent format
        image = self._render_tile(uuid, x, y, z, t, level, channels, gamma=1, codec='jpg')
        self._set_prerendered_to_cache(uuid, x, y, z, t, level, channel_group_uuid, image)
        return image

    def _render_tile(self, uuid, x, y, z, t, level, channels, gamma=None, codec='jpg'):
        # Prepare for blending
        args = [(uuid, x, y, z, t,
                 channel['index'], level) for channel in channels]

        # TODO Blend images as they are received instead of waiting for all.
        # Either prepare in parallel (might be worth it as we get more vCPUs
        # with higher memory reservations) then blend in a thread safe manner
        # or at least start processing each tile as it comes in
        # UPDATE: Tried starting blending parallel with S3 downloads, but it
        # didn't gain speed, it was actually a bit slower..

        # Fetch raw tiles in parallel
        tile_provider = S3TileProvider(bucket.split(':')[-1],
                                       missing_tile_callback=handle_missing_tile,
                                       cache_client=redis_client_raw)
        try:
            images = pool.starmap(tile_provider.get_tile, args)
        finally:
            pass

        # Update channel dictionary with image data
        for channel, image in zip(channels, images):
            channel['image'] = image

        # Blend the raw tiles
        logging.info("Composite START")
        composite = render.composite_channels(channels, gamma=gamma)
        logging.info("Composite END")
        # CV2 requires 0 - 255 values

        # Encode rendered image as JPG
        img = BytesIO()
        imagecodecs.imwrite(img, composite, codec=codec, level=85)
        img.seek(0)

        return img.read()

    @response(200)
    def render_region(self, event, context):
        from minerva_db.sql.api import Client as db_client
        self._open_session()
        client = db_client(self.session)

        '''Render the specified region with the given settings'''

        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

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
        image = client.get_image(uuid)
        fileset_uuid = image['data']['fileset_uuid']
        fileset = client.get_fileset(fileset_uuid)

        if fileset['data']['complete'] is not True:
            raise ValueError(
                f'Fileset has not had metadata extracted yet: {fileset_uuid}'
            )

        obj = boto3.resource('s3').Object(bucket.split(':')[-1],
                                          f'{fileset_uuid}/metadata.xml')
        body = obj.get()['Body']
        data = body.read()
        stream = BytesIO(data)
        import xml.etree.ElementTree as ET
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
                args.append((client,
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
        s3_tile_provider = S3TileProvider(bucket.split(':')[-1],
                                          missing_tile_callback=handle_missing_tile)
        try:
            pool = ThreadPool(len(args))
            images = pool.starmap(s3_tile_provider.get_tile, args)
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
        img = BytesIO()
        if self.content_type == "image/webp":
            imagecodecs.imwrite(img, scaled, codec="webp")
        else:
            imagecodecs.imwrite(img, scaled, codec="jpg")
        return img.read()

    @response(200)
    def get_autosettings(self, event, context):

        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)

        from minerva_db.sql.api import Client as db_client
        self._open_session()
        client = db_client(self.session)

        self._has_image_permission(self.user_uuid, uuid, 'Read')
        image = client.get_image(uuid)
        max_level = image["data"]["pyramid_levels"] - 1

        channel_ids = event['pathParameters']['channels'].split(',')
        method = _event_query_param(event, 'method')

        tile_provider = S3TileProvider(bucket.split(':')[-1],
                                       missing_tile_callback=handle_missing_tile,
                                       cache_client=redis_client_raw)

        args = [(uuid, channel, tile_provider, 0, 0, 0, 0, max_level, method) for channel in channel_ids]
        res = {
            "channels": pool.starmap(self._autosettings_channel, args)
        }
        return res

    def _autosettings_channel(self, uuid, channel, tile_provider, x, y, z, t, level, method="histogram"):
        data = tile_provider.get_tile(uuid, x, y, z, t, channel, level)
        if method == "gaussian":
            min, max = autosettings.gaussian(data, n_components=3, n_sigmas=2, subsampling=3)
        else:
            h, b = autosettings.calc_histogram(data)
            min, max = autosettings.calc_min_max(h, b, 0.0005)

        return {
            "id": channel,
            "min": min,
            "max": max
        }


handler = Handler()
render_tile = handler.render_tile
render_region = handler.render_region
prerendered_tile = handler.prerendered_tile
omero_render_tile = handler.omero_render_tile
get_autosettings = handler.get_autosettings
