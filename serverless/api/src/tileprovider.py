import time
import sys
import os
from io import BytesIO
import tifffile
import logging
import boto3
import zarr
import s3fs
import imagecodecs
from botocore.exceptions import ClientError

logger = logging.getLogger("minerva")

# Tile provider which loads tiles from a S3 bucket
class S3TileProvider:
    def __init__(
        self,
        tile_bucket,
        missing_tile_callback=None,
        cache_client=None,
        tile_size=1024,
        region="us-east-1",
    ):
        self.bucket = tile_bucket
        self.missing_tile_callback = missing_tile_callback
        self.cache_client = cache_client
        self.tile_size = tile_size
        self.region = region

    def get_tile(self, uuid, x, y, z, t, c, level, format="tiff"):
        """Fetch a specific tile from S3 and decode"""

        start = time.time()
        # Use the indices to build the key
        file_ext = ".tif" if format == "tiff" else f".{format}"
        key = f"{uuid}/C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}{file_ext}"

        try:
            image = self._get_cached_object(key)
            if image is None:
                if format == "zarr":
                    # ZARR
                    image = self._zarr_get(uuid, x, y, z, t, c, level)
                else:
                    data = self._s3_get(key)
                    stream = BytesIO(data)

                    if format == "tiff":
                        # Use tifffile to open TIFF formats
                        image = tifffile.imread(stream)
                    else:
                        # Use imagecodecs to open other formats, such as PNG
                        image = imagecodecs.imread(stream)

                self._put_cached_object(key, image)

            t = round((time.time() - start) * 1000)
            return image

        except ClientError as e:
            logger.error(e)
            logger.info("%s - Fetch COMPLETE %s ms", key, str(t))
            sys.stdout.flush()
            if (
                e.response["Error"]["Code"] == "NoSuchKey"
                and self.missing_tile_callback is not None
            ):
                self.missing_tile_callback(uuid, x, y, z, t, c, level)
            else:
                raise e
        except Exception as e:
            logger.error(e)
            raise e

    def _get_cached_object(self, key):
        data = None
        if self.cache_client is not None:
            logger.debug("Get cache START")
            data = self.cache_client.get(key)
            logger.debug("Get cache END")
        return data

    def _put_cached_object(self, key, data):
        if self.cache_client is not None:
            logger.debug("Put cache START")
            self.cache_client.set(key, data)
            logger.debug("Put cache END")

    def _s3_get(self, key):
        obj = boto3.resource("s3").Object(self.bucket, key)
        body = obj.get()["Body"]
        return body.read()

    def _zarr_get(self, uuid, x, y, z, t, c, level):
        s3 = s3fs.S3FileSystem(client_kwargs=dict(region_name=self.region))
        s3_store = s3fs.S3Map(root=f"{self.bucket}/{uuid}", s3=s3, check=False)
        group = zarr.hierarchy.open_group(store=s3_store)
        level = group.get(str(level))
        return level[
            t,
            c,
            z,
            y * self.tile_size : (y + 1) * self.tile_size,
            x * self.tile_size : (x + 1) * self.tile_size,
        ]


# Example of a tile provider which loads the tiles from file system (e.g. local hard drive or NFS)
class FSTileProvider:
    def __init__(self, base_dir, missing_tile_callback=None):
        self.base_dir = base_dir
        self.missing_tile_callback = missing_tile_callback

    def get_tile(self, uuid, x, y, z, t, c, level, format="tiff"):
        file_ext = ".tif" if format == "tiff" else f".{format}"
        filename = f"C{c}-T{t}-Z{z}-L{level}-Y{y}-X{x}{file_ext}"
        path = os.path.join(self.base_dir, uuid, filename)
        logger.debug("Opening path: %s", path)
        with open(path, mode="rb") as file:
            data = file.read()
            stream = BytesIO(data)
            if format == "tiff":
                return tifffile.imread(stream)
            else:
                return imagecodecs.imread(stream)
