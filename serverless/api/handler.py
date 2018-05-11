import os
from multiprocessing.pool import ThreadPool
from io import BytesIO
import base64
import logging
import boto3
import cv2
import numpy as np
from minerva_lib import blend

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')

# TODO Fully document types expected in API documentation
PATH_ERROR = ('Path must conform to format:'
              'x/y/z/t/l/c,color,min,max/c,color,min,max/...')


def __s3_get(bucket, key):
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


def _parse_path_params(path_params):
    '''Parse tile indices and rendering settings

    Format: imageUuid/x/y/z/t/l/c,color,min,max/c,color,min,max/...
    '''

    # Read the path parameters for the indices and convert
    imageUuid = int(path_params['imageUuid'])
    x = int(path_params['x'])
    y = int(path_params['y'])
    z = int(path_params['z'])
    t = int(path_params['t'])
    level = int(path_params['level'])

    # Split the channels path parameters
    channel_path_params = path_params['channels'].split('/')

    # Read the path parameter for the channels and convert
    channels = [_parse_channel_params(param) for param in channel_path_params]

    return {
        'imageUuid': imageUuid,
        'x': x,
        'y': y,
        'z': z,
        't': t,
        'level': level,
        'channels': channels
    }


def linear_rgb(event, context):
    '''Render the specified tile with the given settings'''

    # Get bucket
    bucket = ssm.get_parameter(
        Name='/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE)
    )['Parameter']['Value']

    # Attempt to parse required parameters
    try:
        path_params = event['pathParameters']
        indices_and_settings = _parse_path_params(path_params)
    except KeyError as e:
        return {
            'statusCode': 400,
            'body': PATH_ERROR
        }
    except ValueError as e:
        return {
            'statusCode': 400,
            'body': str(e)
        }

    # Use the indices to build the key base
    key_base = (
        '{imageUuid}/C{}'
        + '-T{t}-Z{z}-L{level}-Y{y}-X{x}.png'.format_map(indices_and_settings)
    )

    # Prepare for blending
    channels = indices_and_settings['channels']
    args = [(bucket, key_base.format(channel['index']))
            for channel in channels]

    # Fetch raw tiles in parallel
    # TODO Blend images as they are received instead of waiting for all.
    # Either prepare in parallel (might be worth it as we get more vCPUs with
    # higher memory reservations) then blend in a thread safe manner or at
    # least start processing each tile as it comes in
    pool = ThreadPool(processes=len(channels))
    images = pool.starmap(__s3_get, args)
    pool.close()

    # Update channel dictionary with image data
    for channel, image in zip(channels, images):
        channel['image'] = image

    # Blend the raw tiles
    merged = blend.linear_bgr(channels)

    # Encode rendered image as PNG
    retval, image = cv2.imencode('.png', merged)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'image/png',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true'
        },
        'body': base64.b64encode(image).decode('utf-8'),
        'isBase64Encoded': True
    }
