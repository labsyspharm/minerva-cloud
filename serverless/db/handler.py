from typing import Any, Callable, Dict, List, Union, Optional
from functools import wraps
import os
import logging
import boto3
import json
import re
from io import BytesIO
import xml.etree.ElementTree as ET
from uuid import uuid4
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from minerva_db.sql.api import Client
from minerva_db.sql.api.utils import to_jsonapi

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Get environment variables
STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']
# TODO Handle different versions of the schema
OME_NS = 'http://www.openmicroscopy.org/Schemas/OME/2016-06'

s3 = boto3.client('s3')
ssm = boto3.client('ssm')
sts = boto3.client('sts')
sfn = boto3.client('stepfunctions')

read_policy = '''{{
    "Version": "2012-10-17",
    "Statement": [
        {{
            "Effect": "Allow",
            "Action": [
                "s3:Get*",
                "s3:ListMultipartUploadParts"
            ],
            "Resource": [
                "{0}/{1}/*",
                "{0}/{1}",
                "{0}/{2}/*",
                "{0}/{2}"
            ]
        }},
        {{
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:ListBucketByTags",
                "s3:ListBucketMultipartUploads",
                "s3:ListBucketVersions"
            ],
            "Resource": [
                "{0}"
            ],
            "Condition": {{
                "StringLike": {{
                    "s3:prefix": [
                        "{1}/*",
                        "{2}/*"
                    ]
                }}
            }}
        }}
    ]
}}'''

write_policy = '''{{
    "Version": "2012-10-17",
    "Statement": [
        {{
            "Effect": "Allow",
            "Action": [
                "s3:Get*",
                "s3:ListMultipartUploadParts",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:AbortMultipartUpload"
            ],
            "Resource": [
                "{0}/{1}/*",
                "{0}/{1}"
            ]
        }},
        {{
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:ListBucketByTags",
                "s3:ListBucketMultipartUploads",
                "s3:ListBucketVersions"
            ],
            "Resource": [
                "{0}"
            ],
            "Condition": {{
                "StringLike": {{
                    "s3:prefix": [
                        "{1}/*"
                    ]
                }}
            }}
        }}
    ]
}}'''


class AuthError(Exception):
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
    engine = create_engine(connection_string)
    global_sessionmaker = sessionmaker(bind=engine)
    return global_sessionmaker


DBSession = _setup_db()


def json_custom(obj: Any) -> str:
    '''JSON serializer for extra types.
    '''

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError('Type {} not serializable'.format(type(obj)))


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


# TODO What is the best typing for a decorator? typing hints at each level?
# TODO Should the documentation have an argument of `fn` even though the actual
# function does not?
# def is_match(_lambda, pattern):
#     def wrapper(f):
#         @wraps(f)
#         def wrapped(self, *f_args, **f_kwargs):
#             if callable(_lambda) and search(pattern, (_lambda(self) or '')):
#                 f(self, *f_args, **f_kwargs)
#         return wrapped
#     return wrapper

# TODO Refactor this as it is in multiple handlers
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
                logger.exception('Client error')
                return make_response(400, {'error': str(e)})
            except ValueError as e:
                logger.exception('Client error')
                return make_response(422, {'error': str(e)})
            except AuthError as e:
                logger.exception('Client error')
                return make_response(403, {'error': str(e)})
            except Exception as e:
                logger.exception('Unexpected server error')
                return make_response(500, {'error': str(e)})
            finally:
                self.session.close()

        return wrapped
    return wrapper


def _event_method(event):
    return event['httpMethod']


def _event_path(event):
    return event['resourcePath']


def _event_body(event):
    if 'body' in event and event['body'] is not None:
        try:
            return json.loads(event['body'])
        except Exception as e:
            logger.warning("Invalid JSON: %s", event['body'])
            return event['body']
    return {}


def _event_user(event):
    print(event)
    if 'claims' in event['requestContext']['authorizer']:
        uuid = event['requestContext']['authorizer']['claims']['cognito:username']
    else:
        uuid = event['requestContext']['authorizer']['principalId']
    _validate_uuid(uuid)
    return uuid


def _event_query_param(event, key, multi=False):
    if multi is True:
        return event['queryStringParameters'][key].split(',')
    return event['queryStringParameters'][key]


def _event_path_param(event, key):
    from urllib import parse
    return parse.unquote(event['pathParameters'][key])


_valid_name = re.compile('^[a-zA-Z][a-zA-Z0-9\\-_]+$')
_length_name = 128


def _validate_name(s):
    if len(s) > _length_name or _valid_name.match(s) is None:
        raise ValueError('Name is invalid. Valid names begin with a letter, '
                         'contain only alphanumeric characters, dash and '
                         'underscore. The maximum length '
                         'is {}'.format(_length_name))


_valid_uuid = re.compile(
    '^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$'
)


def _validate_uuid(u):
    if _valid_uuid.match(u) is None:
        raise ValueError('UUID is invalid. Valid uuids are of the form '
                         'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')


# TODO Drive from schema
def _validate_permission(p):
    if p not in ['Read', 'Write', 'Admin']:
        raise ValueError('Permission {} is invalid'.format(p))


def _validate_resource_type(resource_type: str):
    if resource_type.lower() not in ['repository', 'image']:
        raise ValueError('Invalid resource type {}'.format(resource_type))


class Handler:
    def __init__(self):
        self.count = 0

    def lazy_property(fn):
        '''Decorator that makes a property lazy-evaluated.
        '''
        attr_name = '_lazy_' + fn.__name__

        @property
        def _lazy_property(self):
            if not hasattr(self, attr_name):
                setattr(self, attr_name, fn(self))
            return getattr(self, attr_name)

        return _lazy_property

    # Get raw bucket
    @lazy_property
    def raw_bucket(self):
        return ssm.get_parameter(
            Name='/{}/{}/common/S3BucketRawARN'.format(STACK_PREFIX, STAGE)
            )['Parameter']['Value']

    @lazy_property
    def tile_bucket(self):
        return ssm.get_parameter(
            Name='/{}/{}/common/S3BucketTileARN'.format(STACK_PREFIX, STAGE)
            )['Parameter']['Value']

    @lazy_property
    def sync_sfn(self):
        return ssm.get_parameter(
            Name='/{}/{}/batch/S3EFSSyncStepARN'.format(STACK_PREFIX, STAGE)
            )['Parameter']['Value']

    @lazy_property
    def s3_assume_role_read(selfs):
        return ssm.get_parameter(
            Name='/{}/{}/common/AssumedS3RoleReadARN'.format(STACK_PREFIX, STAGE)
            )['Parameter']['Value']

    @lazy_property
    def s3_assume_role_write(self):
        return ssm.get_parameter(
            Name='/{}/{}/common/AssumedS3RoleWriteARN'.format(STACK_PREFIX, STAGE)
            )['Parameter']['Value']

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

    def _is_member(self, group: str, user: str,
                   membership_type: Optional[str] = 'Member'):
        '''Determine if the given user is a member of the given group.

        Args:
            group: The group UUID.
            user: The user UUID.
            membership_type: The required membership type.

        Raises:
            AuthError: If the user is not a member of the group (and does not
            have the required level of membership by implication).
        '''
        if not self.client.is_member(group, user, membership_type):
            raise AuthError('Permission Denied')

    @response(200)
    def cognito_details(self, event, context):
        self.count += 1
        return {
            'eventRequestContext': event['requestContext'],
            'count': self.count
        }

    @response(201)
    def create_group(self, event, context):
        name = self.body['name']
        _validate_name(name)
        uuid = str(uuid4())

        return self.client.create_group(uuid, name, self.user_uuid)

    @response(201)
    def create_repository(self, event, context):
        name = self.body['name']
        raw_storage = self.body.get('raw_storage')
        _validate_name(name)
        uuid = str(uuid4())

        return self.client.create_repository(uuid, name, self.user_uuid,
                                             raw_storage)

    @response(201)
    def create_image(self, event, context):
        name = self.body['name']
        repository_uuid = self.body['repository_uuid']
        pyramid_levels = self.body['pyramid_levels']
        _validate_name(name)
        uuid = str(uuid4())
        return self.client.create_image(uuid, name, pyramid_levels, fileset_uuid=None, repository_uuid=repository_uuid)

    @response(201)
    def create_import(self, event, context):
        name = self.body['name']
        repository_uuid = self.body['repository_uuid']
        _validate_name(name)
        _validate_uuid(repository_uuid)
        self._has_permission(self.user_uuid, 'Repository', repository_uuid,
                             'Write')
        uuid = str(uuid4())

        return self.client.create_import(uuid, name, repository_uuid)

    @response(201)
    def create_membership(self, event, context):
        group_uuid = _event_path_param(event, 'group_uuid')
        user_uuid = _event_path_param(event, 'user_uuid')
        membership_type = self.body.get('membership_type')
        _validate_uuid(group_uuid)
        _validate_uuid(user_uuid)
        self._is_member(group_uuid, self.user_uuid, 'Owner')
        return self.client.create_membership(group_uuid, user_uuid,
                                             membership_type)

    @response(200)
    def create_metadata(self, event, context):
        image_uuid = _event_path_param(event, 'uuid')
        _validate_uuid(image_uuid)
        self._has_permission(self.user_uuid, 'Image', image_uuid, 'Write')

        # Check that some basic values are found in xml
        # TODO ideally validate metadata according to OME schema
        e_root = ET.fromstring(self.body)
        e_image = e_root.find('ome:Image', {'ome': OME_NS})
        if e_image is None:
            raise ValueError('Invalid metadata: missing Image:' + image_uuid)
        e_image.set('ID', 'Image:{}'.format(image_uuid))
        e_pixels = e_image.find('ome:Pixels', {'ome': OME_NS})
        if e_pixels is None:
            raise ValueError('Invalid metadata: missing Pixels')
        size_x = e_pixels.get('SizeX')
        size_y = e_pixels.get('SizeY')
        if size_x is None or size_y is None or size_x < 0 or size_y < 0:
            raise ValueError('Invalid metadata: missing SizeX or SizeY')

        bucket = self.tile_bucket.split(':')[-1]
        s3.put_object(Bucket=bucket, Key=image_uuid + '/metadata.xml', Body=ET.tostring(e_root))

    @response(201)
    def create_rendering_settings(self, event, context):
        image_uuid = _event_path_param(event, 'uuid')
        _validate_uuid(image_uuid)
        self._has_permission(self.user_uuid, 'Image', image_uuid, 'Write')

        groups = self.body.get('groups')
        for group in groups:
            channels = group.get('channels')
            label = group.get('label')
            if 'uuid' not in group:
                uuid = str(uuid4())
                group['uuid'] = uuid
                self.client.create_rendering_settings(uuid, image_uuid, channels, label)
            else:
                self.client.update_rendering_settings(group['uuid'], channels, label)

        return self.body

    @response(200)
    def get_group(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._is_member(uuid, self.user_uuid)

        return self.client.get_group(uuid)

    @response(200)
    def get_user(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        # TODO Who can describe a user other than the user themselves?
        if uuid != self.user_uuid:
            raise AuthError(f'Can not describe user: {uuid}')

        return self.client.get_user(uuid)

    @response(200)
    def get_membership(self, event, context):
        group_uuid = _event_path_param(event, 'group_uuid')
        user_uuid = _event_path_param(event, 'user_uuid')
        _validate_uuid(group_uuid)
        _validate_uuid(user_uuid)
        # Check if the requesting user is a member of the group that they
        # are requesting a membership for
        self._is_member(group_uuid, self.user_uuid)

        return self.client.get_membership(group_uuid, user_uuid)

    @response(200)
    def get_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Read')

        return self.client.get_repository(uuid)

    @response(200)
    def get_import(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Import', uuid, 'Read')

        return self.client.get_import(uuid)

    @response(200)
    def get_import_credentials(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Import', uuid, 'Write')
        if self.client.get_import(uuid)['data']['complete'] is not False:
            raise AuthError(
                f'Import is complete and can not be written: {uuid}'
            )

        # TODO Better session name?
        response = sts.assume_role(
            RoleArn=self.s3_assume_role_write,
            RoleSessionName='{}@{}'.format(self.user_uuid, uuid)[:64],
            Policy=write_policy.format(self.raw_bucket, uuid)
        )

        return to_jsonapi({
            'url': 's3://{}/{}/'.format(self.raw_bucket.split(':')[-1], uuid),
            'credentials': response['Credentials']
        })

    @response(200)
    def update_import(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        name = self.body.get('name')
        complete = self.body.get('complete')
        if name is not None:
            _validate_name(name)
        self._has_permission(self.user_uuid, 'Import', uuid, 'Write')

        # Ensure the import is only marked complete once as this triggers
        # processing
        import_ = self.client.get_import(uuid)
        if complete is True and import_['data']['complete'] is True:
            raise ValueError(f'Import is already complete: {uuid}')
        else:
            # TODO Ensure the prefix is no longer writeable before processing
            # TODO Record the execution ARN somewhere for monitoring
            sfn.start_execution(
                stateMachineArn=self.sync_sfn,
                input=json.dumps({
                  'import_uuid': uuid
                })
            )

        return self.client.update_import(uuid, name, complete)

    @response(200)
    def get_fileset(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Fileset', uuid, 'Read')

        return self.client.get_fileset(uuid)

    # @response(200)
    # def get_fileset_metadata(self, event, context):
    #     uuid = _event_path_param(event, 'uuid')
    #     _validate_uuid(uuid)
    #     self._has_permission(self.user_uuid, 'Fileset', uuid, 'Read')
    #
    #     bucket = tile_bucket.split(':')[-1]
    #
    #     # TODO More specific query?
    #     image_details = client.describe_image(uuid)
    #
    #     obj = boto3.resource('s3').Object(bucket,
    #                                       f'{uuid}/metadata.xml')
    #     body = obj.get()['Body']
    #     data = body.read()
    #     stream = BytesIO(data)
    #     root = ET.fromstring(stream.getvalue().decode('UTF-8'))
    #
    #     image = root.find('ome:Image[@ID="Image:{}"]'.format(uuid),
    #                       {'ome': OME_NS})
    #     pixels = image.find('ome:Pixels', {'ome': OME_NS})
    #     channels = pixels.findall('ome:Channel', {'ome': OME_NS})
    #
    #     return {
    #         'pixels': {
    #             'SizeC': int(pixels.attrib['SizeC']),
    #             'SizeT': int(pixels.attrib['SizeT']),
    #             'SizeX': int(pixels.attrib['SizeX']),
    #             'SizeY': int(pixels.attrib['SizeY']),
    #             'SizeZ': int(pixels.attrib['SizeZ']),
    #             'channels': [{
    #                 'ID': channel.attrib['ID'],
    #                 'Name': channel.attrib['Name']} for channel in channels]
    #         }
    #     }

    @response(200)
    def get_image(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')

        return self.client.get_image(uuid)

    @response(200)
    def get_image_dimensions(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')

        bucket = self.tile_bucket.split(':')[-1]

        image = self.client.get_image(uuid)
        bucket_key = uuid
        fileset_uuid = image['data']['fileset_uuid']
        if fileset_uuid is not None:
            bucket_key = fileset_uuid
            fileset = self.client.get_fileset(fileset_uuid)

            if fileset['data']['complete'] is not True:
                raise ValueError(
                    f'Fileset has not had metadata extracted yet: {fileset_uuid}'
                )

        obj = boto3.resource('s3').Object(bucket,
                                          f'{bucket_key}/metadata.xml')
        body = obj.get()['Body']
        data = body.read()
        stream = BytesIO(data)
        e_root = ET.fromstring(stream.getvalue().decode('UTF-8'))
        e_image = e_root.find('ome:Image[@ID="Image:{}"]'.format(uuid),
                              {'ome': OME_NS})
        e_pixels = e_image.find('ome:Pixels', {'ome': OME_NS})
        e_channels = e_pixels.findall('ome:Channel', {'ome': OME_NS})

        return to_jsonapi(
            {
                'image_uuid': uuid,
                'pixels': {
                    'SizeC': int(e_pixels.attrib['SizeC']),
                    'SizeT': int(e_pixels.attrib['SizeT']),
                    'SizeX': int(e_pixels.attrib['SizeX']),
                    'SizeY': int(e_pixels.attrib['SizeY']),
                    'SizeZ': int(e_pixels.attrib['SizeZ']),
                    'channels': [
                        {
                            'ID': e_channel.attrib['ID'],
                            'Name': e_channel.attrib.get('Name')
                        } for e_channel in e_channels
                    ]
                }
            },
            {
                'images': [image['data']]
            }
        )

    @response(200)
    def get_image_credentials(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Write')

        # TODO Better session name?
        response = sts.assume_role(
            RoleArn=self.s3_assume_role_write,
            RoleSessionName='{}@{}'.format(self.user_uuid, uuid)[:64],
            Policy=write_policy.format(self.tile_bucket, uuid)
        )

        tile_bucket_name = self.tile_bucket.split(':')[-1]

        return to_jsonapi({
            'image_url': f's3://{tile_bucket_name}/{uuid}/',
            'credentials': response['Credentials']
        })

    @response(200)
    def list_imports_in_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Read')
        return self.client.list_imports_in_repository(uuid)

    @response(200)
    def list_filesets_in_import(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Import', uuid, 'Read')
        return self.client.list_filesets_in_import(uuid)

    @response(200)
    def list_keys_in_import(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Import', uuid, 'Read')
        return self.client.list_keys_in_import(uuid)

    @response(200)
    def list_images_in_fileset(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Fileset', uuid, 'Read')
        return self.client.list_images_in_fileset(uuid)

    @response(200)
    def list_images_in_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Read')
        return self.client.list_images_in_repository(uuid)

    @response(200)
    def list_keys_in_fileset(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Fileset', uuid, 'Read')
        return self.client.list_keys_in_fileset(uuid)

    @response(200)
    def list_incomplete_imports(self, event, context):
        return self.client.list_incomplete_imports()

    @response(200)
    def list_rendering_settings_for_image(self, event, context):
        image_uuid = _event_path_param(event, 'uuid')
        _validate_uuid(image_uuid)
        self._has_permission(self.user_uuid, 'Image', image_uuid, 'Read')
        rendering_settings = self.client.list_rendering_settings(image_uuid)
        return [r.as_dict() for r in rendering_settings]

    @response(200)
    def update_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        name = self.body.get('name')
        raw_storage = self.body.get('raw_storage')
        if name is not None:
            _validate_name(name)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Admin')

        access = None
        if 'access' in self.body:
            access = self.body.get('access')
            public_read_group = self.client.find_group('MinervaPublicRead')['data'][0]
            print(public_read_group)
            if access == 'PublicRead':
                self.client.grant_repository_to_subject(uuid, public_read_group["uuid"], "Read")
            elif access == 'Private':
                self.client.delete_grant(public_read_group["uuid"], uuid)

        return self.client.update_repository(uuid, name, raw_storage, access)

    @response(200)
    def update_membership(self, event, context):
        group_uuid = _event_path_param(event, 'group_uuid')
        user_uuid = _event_path_param(event, 'user_uuid')
        _validate_uuid(group_uuid)
        _validate_uuid(user_uuid)
        membership_type = self.body.get('membership_type')

        # Only an owner can change membership_type
        if membership_type is not None:
            self._is_member(group_uuid, self.user_uuid, 'Owner')
        return self.client.update_membership(group_uuid, user_uuid,
                                             membership_type)

    @response(204)
    def delete_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Admin')
        images = self.client.list_images_in_repository(uuid)
        if len(images["data"]) > 0:
            raise KeyError("Can not delete non-empty repository!")

        return self.client.delete_repository(uuid)

    @response(204)
    def delete_image(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Admin')
        return self.client.delete_image(uuid)

    @response(204)
    def restore_image(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Image', uuid, 'Admin')
        return self.client.restore_image(uuid)

    @response(204)
    def delete_membership(self, event, context):
        group_uuid = _event_path_param(event, 'group_uuid')
        user_uuid = _event_path_param(event, 'user_uuid')
        _validate_uuid(group_uuid)
        _validate_uuid(user_uuid)

        # Only an owner can delete a membership unless the requesting user
        # is the user subject of the membership
        # TODO Ensure that someone retains the ability to modify a group,
        # perhaps Organization Admin related
        if self.user_uuid != user_uuid:
            self._is_member(group_uuid, self.user_uuid, 'Owner')
        return self.client.delete_membership(group_uuid, user_uuid)

    # @response(200)
    # def list_files_in_fileset(self, event, context):
    #     pass
    #
    # @response(200)
    # def list_files_in_import(self, event, context):
    #     pass
    #
    @response(200)
    def list_repositories_for_user(self, event, context):
        user = _event_user(event)
        return self.client.list_repositories_for_user(user)

    @response(200)
    def list_grants_for_repository(self, event, context):
        repository_uuid = _event_path_param(event, 'uuid')
        _validate_uuid(repository_uuid)
        return self.client.list_grants_for_repository(repository_uuid)

    @response(200)
    def find_user(self, event, context):
        search = _event_path_param(event, 'search')
        logger.info(search)
        return self.client.find_user(search)

    @response(200)
    def find_group(self, event, context):
        search = _event_path_param(event, 'search')
        return self.client.find_group(search)

    # Rename method because this works for groups as well
    @response(204)
    def grant_resource_to_user(self, event, context):
        resource_uuid = self.body.get('uuid')
        resource_type = self.body.get('resource')
        _validate_resource_type(resource_type)
        _validate_uuid(resource_uuid)
        grantee = self.body.get('grantee')
        _validate_uuid(grantee)

        if grantee == self.user_uuid:
            raise ValueError("Can not change permissions for self")

        permissions = self.body.get('permissions')
        if isinstance(permissions, str):
            permissions = [permissions]

        for permission in permissions:
            _validate_permission(permission)

        for permission in permissions:
            if resource_type.lower() == 'repository':
                self._has_permission(self.user_uuid, 'Repository', resource_uuid, 'Admin')
                self.client.grant_repository_to_subject(resource_uuid, grantee, permission)
            else:
                raise ValueError("Grant not implemented yet for resource ", resource_type)

    @response(204)
    def delete_grant(self, event, context):
        resource_uuid = _event_path_param(event, 'uuid')
        subject_uuid = _event_path_param(event, 'subject_uuid')
        self._has_permission(self.user_uuid, 'Repository', resource_uuid, 'Admin')
        self.client.delete_grant(subject_uuid=subject_uuid, resource_uuid=resource_uuid)

    #
    # @response(200)
    # def list_users_in_group(self, event, context):
    #     user = _event_user(event)
    #     group = _event_path_param(event, 'uuid')
    #     _validate_uuid(group)
    #     _user_member(user, group)
    #     return client.list_users_in_group(group)
    #
    # @response(200)
    # def get_image_metadata(self, event, context):
    #     user = _event_user(event)
    #     uuid = _event_path_param(event, 'uuid')
    #     _validate_uuid(uuid)
    #     _user_permission(user, uuid, 'Read')
    #
    #     bucket = tile_bucket.split(':')[-1]
    #
    #     # TODO More specific query?
    #     image_details = client.describe_image(uuid)
    #
    #     obj = boto3.resource('s3').Object(
    #         bucket,
    #         image_details['fileset'] + '/metadata.xml'
    #     )
    #     body = obj.get()['Body']
    #     data = body.read()
    #     stream = BytesIO(data)
    #     root = ET.fromstring(stream.getvalue().decode('UTF-8'))
    #
    #     image = root.find('ome:Image[@ID="Image:{}"]'.format(uuid),
    #                       {'ome': OME_NS})
    #     pixels = image.find('ome:Pixels', {'ome': OME_NS})
    #     channels = pixels.findall('ome:Channel', {'ome': OME_NS})
    #
    #     return {
    #         'pixels': {
    #             'SizeC': int(pixels.attrib['SizeC']),
    #             'SizeT': int(pixels.attrib['SizeT']),
    #             'SizeX': int(pixels.attrib['SizeX']),
    #             'SizeY': int(pixels.attrib['SizeY']),
    #             'SizeZ': int(pixels.attrib['SizeZ']),
    #             'channels': [{
    #                 'ID': channel.attrib['ID'],
    #                 'Name': channel.attrib['Name']} for channel in channels]
    #         }
    #     }
    #



handler = Handler()
create_group = handler.create_group
cognito_details = handler.cognito_details
create_repository = handler.create_repository
create_image = handler.create_image
create_import = handler.create_import
create_membership = handler.create_membership
create_rendering_settings = handler.create_rendering_settings
create_metadata = handler.create_metadata
get_group = handler.get_group
get_membership = handler.get_membership
get_user = handler.get_user
get_repository = handler.get_repository
get_import = handler.get_import
get_import_credentials = handler.get_import_credentials
get_fileset = handler.get_fileset
get_image = handler.get_image
get_image_dimensions = handler.get_image_dimensions
get_image_credentials = handler.get_image_credentials
list_imports_in_repository = handler.list_imports_in_repository
list_filesets_in_import = handler.list_filesets_in_import
list_keys_in_import = handler.list_keys_in_import
list_images_in_fileset = handler.list_images_in_fileset
list_images_in_repository = handler.list_images_in_repository
list_keys_in_fileset = handler.list_keys_in_fileset
list_repositories_for_user = handler.list_repositories_for_user
list_incomplete_imports = handler.list_incomplete_imports
update_membership = handler.update_membership
update_import = handler.update_import
update_repository = handler.update_repository
delete_repository = handler.delete_repository
delete_membership = handler.delete_membership
delete_image = handler.delete_image
restore_image = handler.restore_image
list_grants_for_repository = handler.list_grants_for_repository
find_user = handler.find_user
find_group = handler.find_group
grant_resource_to_user = handler.grant_resource_to_user
delete_grant = handler.delete_grant
