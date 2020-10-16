import os
from .lambdautils import *
from .parameterprovider import SSMParameterProvider
from .tileprovider import S3TileProvider
from minerva_lib import autosettings
from multiprocessing.dummy import Pool as ThreadPool

STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

parameter_provider = SSMParameterProvider(STACK_PREFIX, STAGE)
bucket = parameter_provider.get_parameter('/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE))
pool = ThreadPool(6)

class AutoSettings:

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

autosettings = AutoSettings()
get_autosettings = autosettings.get_autosettings