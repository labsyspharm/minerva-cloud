import logging

logger = logging.getLogger("minerva")
logger.setLevel(logging.INFO)

import os
from multiprocessing.dummy import Pool as ThreadPool
from io import BytesIO
import boto3
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from minerva_db.sql.miniclient.miniclient import MiniClient
from minerva_lib import render
from .tileprovider import S3TileProvider
from .parameterprovider import SSMParameterProvider
from .lambdautils import *
import imagecodecs

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']
# TODO Handle different versions of the schema
OME_NS = 'http://www.openmicroscopy.org/Schemas/OME/2016-06'

# TODO Fully document types expected in API documentation
PATH_ERROR = ('Path must conform to format:'
              'x/y/z/t/l/c,color,min,max/c,color,min,max/...')

parameter_provider = SSMParameterProvider(STACK_PREFIX, STAGE)

bucket = parameter_provider.get_parameter('/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE))
pool = ThreadPool(6)

# Initialize Redis cache for prerendered tiles
cache_host = parameter_provider.get_parameter('/{}/{}/cache/ElastiCacheHost'.format(STACK_PREFIX, STAGE))
cache_port = parameter_provider.get_parameter('/{}/{}/cache/ElastiCachePort'.format(STACK_PREFIX, STAGE))
enable_rendered_cache = parameter_provider.get_parameter('/{}/{}/cache/EnableRenderedCache'.format(STACK_PREFIX, STAGE))
redis_client = None
if cache_host is not None and enable_rendered_cache == "1" and os.environ.get("AWS_EXECUTION_ENV") is not None:
    logger.info("Connecting to prerendered tiles Redis host: %s:%s", cache_host, cache_port)
    import redis
    redis_client = redis.Redis(host=cache_host, port=cache_port, socket_connect_timeout=1)
else:
    logger.info("Rendered tiles cache is disabled")
# Initialize Redis cache for raw tiles
cache_host_raw = parameter_provider.get_parameter('/{}/{}/cache/ElastiCacheHostRaw'.format(STACK_PREFIX, STAGE))
cache_port_raw = parameter_provider.get_parameter('/{}/{}/cache/ElastiCachePortRaw'.format(STACK_PREFIX, STAGE))
enable_raw_cache = parameter_provider.get_parameter('/{}/{}/cache/EnableRawCache'.format(STACK_PREFIX, STAGE))
redis_client_raw = None
if cache_host is not None and enable_raw_cache == "1" and os.environ.get("AWS_EXECUTION_ENV") is not None:
    logger.info("Connecting to raw tiles Redis host: %s:%s", cache_host_raw, cache_port_raw)
    import redis
    redis_client_raw = redis.Redis(host=cache_host_raw, port=cache_port_raw, socket_connect_timeout=1)
else:
    logger.info("Raw tiles cache is disabled")

image_permissions_cache = {}

class AuthError(Exception):
    pass


class TileBoundError(Exception):
    pass


class AspectRatioError(Exception):
    pass

def _setup_db():
    db_host = parameter_provider.get_parameter('/{}/{}/common/DBHost'.format(STACK_PREFIX, STAGE))
    db_port = parameter_provider.get_parameter('/{}/{}/common/DBPort'.format(STACK_PREFIX, STAGE))
    db_user = parameter_provider.get_parameter('/{}/{}/common/DBUser'.format(STACK_PREFIX, STAGE))
    db_password = parameter_provider.get_parameter('/{}/{}/common/DBPassword'.format(STACK_PREFIX, STAGE))
    db_name = parameter_provider.get_parameter('/{}/{}/common/DBName'.format(STACK_PREFIX, STAGE))

    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string, pool_size=1)
    global_sessionmaker = sessionmaker(bind=engine)
    return global_sessionmaker

DBSession = _setup_db()


# TODO Refactor the meat of this as it's largely taken from db handler
def handle_missing_tile(uuid, x, y, z, t, c, level):
    raise TileBoundError(
        f'Requested tile not found uuid={uuid} c={c} x={x} y={y} z={z} t={t} level={level}'
    )

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
    # level, x, y
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
        self.user_uuid = None

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
        if key in image_permissions_cache:
            permitted = bool(image_permissions_cache[key])

        elif redis_client_raw is not None:
            permitted = redis_client_raw.get(key)
            if permitted is not None:
                permitted = bool(permitted)

        if permitted is None:
            self._open_session()
            permitted = self.client.has_image_permission(user, resource, permission)
            image_permissions_cache[key] = int(permitted)
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
                logger.debug("Redis cache HIT")
            else:
                logger.debug("Redis cache MISS")
            return tile_data
        except Exception as e:
            logger.error(e)
            logger.warning("Disabling cache")
            redis_client = None

    def _set_prerendered_to_cache(self, uuid, x, y, z, t, level, channel_group_uuid, tile_data):
        global redis_client
        if redis_client is None:
            return
        key = f'{uuid}/T{t}-Z{z}-L{level}-Y{y}-X{x}/{channel_group_uuid}'
        redis_client.set(key, tile_data)

    @response(200)
    def raw_tile(self, event, context):
        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(event_path_param(event, 'x'))
        y = int(event_path_param(event, 'y'))
        z = int(event_path_param(event, 'z'))
        t = int(event_path_param(event, 't'))
        level = int(event_path_param(event, 'level'))
        channel = int(event_path_param(event, 'channels'))

        tile_provider = S3TileProvider(bucket.split(':')[-1],
                                       missing_tile_callback=handle_missing_tile,
                                       cache_client=redis_client_raw)
        tile = tile_provider.get_tile(uuid, x, y, z, t, channel, level)

        # Encode rendered image as PNG
        img = BytesIO()
        imagecodecs.imwrite(img, tile, codec="png", level=1)
        img.seek(0)

        return img.read()

    @response(200)
    def render_tile(self, event, context):
        '''Render the specified tile with arbitrary channels and color settings'''

        warmup = event_query_param(event, 'warmup')
        if warmup is not None:
            return b''

        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(event_path_param(event, 'x'))
        y = int(event_path_param(event, 'y'))
        z = int(event_path_param(event, 'z'))
        t = int(event_path_param(event, 't'))
        level = int(event_path_param(event, 'level'))
        gamma = event_query_param(event, 'gamma')
        if gamma is not None:
            gamma = float(gamma)
        else:
            gamma = 1.0

        # Split the channels path parameters
        channel_path_params = event['pathParameters']['channels'].split('/')

        # Read the path parameter for the channels and convert
        channels = [_parse_channel_params(param)
                    for param in channel_path_params]

        return self._render_tile(uuid, x, y, z, t, level, channels, gamma=gamma, codec='jpg')

    @response(200)
    def omero_render_tile(self, event, context):
        '''Same as render_tile but accepts Omero/Pathviewer style url'''
        # Example:
        # c=channel|min:max$color,channel|min:max$color, ...
        # c=-1|500:30000$0000FF,-2|500:10000$00FF00,-3|500:10000$FFFFFF,-4|500:10000$FF0000, ... '''
        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        z = int(event_path_param(event, 'z'))
        t = int(event_path_param(event, 't'))
        tile = event_query_param(event, 'tile')
        level, x, y = _parse_omero_tile(tile)
        c = event_query_param(event, 'c')
        channels = _parse_omero_channels(c)
        if not channels:
            #  TODO if all channels are off, should return HTTP status "No content"
            return np.zeros(shape=(1, 1, 3), dtype=np.uint8)

        return self._render_tile(uuid, x, y, z, t, level, channels, gamma=1, codec='jpg')

    @response(200)
    def prerendered_tile(self, event, context):
        '''Render the specified tile with previously saved rendering settings'''

        warmup = event_query_param(event, 'warmup')
        if warmup is not None:
            return b''

        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(event_path_param(event, 'x'))
        y = int(event_path_param(event, 'y'))
        z = int(event_path_param(event, 'z'))
        t = int(event_path_param(event, 't'))
        level = int(event_path_param(event, 'level'))
        channel_group_uuid = event_path_param(event, 'channel_group')

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

    def _render_tile(self, uuid, x, y, z, t, level, channels, gamma=1, codec='jpg'):
        # Prepare for blending
        args = [(uuid, x, y, z, t,
                 channel['index'], level) for channel in channels]

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
        composite = render.composite_channels(channels, gamma=gamma)

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

        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)
        self._has_image_permission(self.user_uuid, uuid, 'Read')

        x = int(event_path_param(event, 'x'))
        y = int(event_path_param(event, 'y'))
        width = int(event_path_param(event, 'width'))
        height = int(event_path_param(event, 'height'))
        z = int(event_path_param(event, 'z'))
        t = int(event_path_param(event, 't'))

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
                args.append((uuid,
                             j,
                             i,
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

        #Rescale for desired output size
        if scaling_factor != 1:
            scaled = render.scale_image_nearest_neighbor(composite, scaling_factor)
        else:
            scaled = composite

        #  requires 0 - 255 values
        scaled *= 255
        scaled = scaled.astype(np.uint8, copy=False)

        # Encode rendered image as JPG
        img = BytesIO()
        imagecodecs.imwrite(img, scaled, codec="jpg")
        img.seek(0)
        return img.read()

    @response(200)
    def get_autosettings(self, event, context):
        uuid = event_path_param(event, 'uuid')
        validate_uuid(uuid)

        from minerva_db.sql.api import Client as db_client
        self._open_session()
        client = db_client(self.session)

        self._has_image_permission(self.user_uuid, uuid, 'Read')
        image = client.get_image(uuid)
        max_level = image["data"]["pyramid_levels"] - 1

        channel_ids = event['pathParameters']['channels'].split(',')
        method = event_query_param(event, 'method')

        tile_provider = S3TileProvider(bucket.split(':')[-1],
                                       missing_tile_callback=None,
                                       cache_client=None)

        args = [(uuid, channel, tile_provider, 0, 0, 0, 0, max_level, method) for channel in channel_ids]
        res = {
            "channels": pool.starmap(self._autosettings_channel, args)
        }
        return res

    def _autosettings_channel(self, uuid, channel, tile_provider, x, y, z, t, level, method="histogram"):
        from minerva_lib import autosettings

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
raw_tile = handler.raw_tile
