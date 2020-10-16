import time
import sys
import os
from io import BytesIO
import tifffile
import logging
import boto3
from botocore.exceptions import ClientError

# Tile provider which loads tiles from a S3 bucket
class S3TileProvider:
    def __init__(self, tile_bucket, missing_tile_callback=None, cache_client=None):
        self.bucket = tile_bucket
        self.missing_tile_callback = missing_tile_callback
        self.cache_client = cache_client

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
            logging.error(e)
            logging.info("%s - Fetch COMPLETE %s ms", key, str(t))
            sys.stdout.flush()
            if e.response['Error']['Code'] == 'NoSuchKey' and self.missing_tile_callback is not None:
                self.missing_tile_callback(uuid, x, y, z, t, c, level)
            else:
                raise e
        except Exception as e:
            logging.error(e)
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