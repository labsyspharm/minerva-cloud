import boto3

class SSMParameterProvider:

    def __init__(self, stack_prefix, stage):
        self.ssm = boto3.client('ssm')
        self.stack_prefix = stack_prefix
        self.stage = stage
        self.parameters = None

    def get_parameter(self, key):
        if self.parameters is not None:
            return self.parameters.get(key, "")
        else:
            self.parameters = {}
            parameters_res = []
            #  10 parameters at most can be fetched in one request, use more and boto3 will throw an error
            #  Let's split the parameter fetching between "common" and "cache"
            #  TODO consolidate parameters to get all in one request
            response = self.ssm.get_parameters(
                Names=[
                    '/{}/{}/common/DBHost'.format(self.stack_prefix, self.stage),
                    '/{}/{}/common/DBPort'.format(self.stack_prefix, self.stage),
                    '/{}/{}/common/DBUser'.format(self.stack_prefix, self.stage),
                    '/{}/{}/common/DBPassword'.format(self.stack_prefix, self.stage),
                    '/{}/{}/common/DBName'.format(self.stack_prefix, self.stage),
                    '/{}/{}/common/S3BucketTileARN'.format(self.stack_prefix, self.stage)
                ]
            )
            parameters_res.extend(response['Parameters'])

            response = self.ssm.get_parameters(
                Names=[
                    '/{}/{}/cache/ElastiCacheHost'.format(self.stack_prefix, self.stage),
                    '/{}/{}/cache/ElastiCachePort'.format(self.stack_prefix, self.stage),
                    '/{}/{}/cache/ElastiCacheHostRaw'.format(self.stack_prefix, self.stage),
                    '/{}/{}/cache/ElastiCachePortRaw'.format(self.stack_prefix, self.stage),
                    '/{}/{}/cache/EnableRenderedCache'.format(self.stack_prefix, self.stage),
                    '/{}/{}/cache/EnableRawCache'.format(self.stack_prefix, self.stage)
                ]
            )
            parameters_res.extend(response['Parameters'])
            for p in parameters_res:
                _key = p['Name']
                _value = p['Value']
                self.parameters[_key] = _value

        return self.parameters.get(key, "")
