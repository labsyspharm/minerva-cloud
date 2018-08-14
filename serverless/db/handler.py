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

# Get raw bucket
raw_bucket = ssm.get_parameter(
    Name='/{}/{}/common/S3BucketRawARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

tile_bucket = ssm.get_parameter(
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

sync_sfn = ssm.get_parameter(
    Name='/{}/{}/batch/S3EFSSyncStepARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

s3_assume_role_read = ssm.get_parameter(
    Name='/{}/{}/common/AssumedS3RoleReadARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']

s3_assume_role_write = ssm.get_parameter(
    Name='/{}/{}/common/AssumedS3RoleWriteARN'.format(STACK_PREFIX, STAGE)
)['Parameter']['Value']


class AuthError(Exception):
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
                return make_response(400, {'error': str(e)})
            except ValueError as e:
                return make_response(422, {'error': str(e)})
            except AuthError as e:
                return make_response(403, {'error': str(e)})
            except Exception as e:
                logger.exception('Unexpected server error')
                return make_response(500, {'error': str(e)})

        return wrapped
    return wrapper


def _event_method(event):
    return event['httpMethod']


def _event_path(event):
    return event['resourcePath']


def _event_body(event):
    if 'body' in event and event['body'] is not None:
        return json.loads(event['body'])
    return {}


def _event_user(event):
    uuid = event['requestContext']['authorizer']['claims']['cognito:username']
    _validate_uuid(uuid)
    return uuid


def _event_query_param(event, key, multi=False):
    if multi is True:
        return event['queryStringParameters'][key].split(',')
    return event['queryStringParameters'][key]


def _event_path_param(event, key):
    return event['pathParameters'][key]


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


class Handler:
    # @classmethod
    # def get_handler(cls, *args, **kwargs):
    #     def handler(event, context):
    #         return cls(*args, **kwargs).handle(event, context)
    #     return handler
    #
    def __init__(self):
        self.count = 0

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

    # def handle(self, event, context) -> str:
    #     '''Based on route, trigger the relevant method.
    #
    #     Args:
    #         event: API Gateway event.
    #         context: API Gateway context.
    #
    #     Returns:
    #         API Gateway compatable JSON string response.
    #     '''
    #
    #     # Create a session to handle this request
    #     self.session = DBSession()
    #     self.client = Client(self.session)
    #
    #     # # TODO Handle route
    #     # path = _event_path(event)
    #     # fn = getattr(self, path)
    #     # return fn(event, context)
    #     # if path = '/cognito_details':
    #     #     return self.cognito_details(event, context)
    #
    #
    #     # return self.create_group(event, context)

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
            RoleArn=s3_assume_role_write,
            RoleSessionName='{}@{}'.format(self.user_uuid, uuid)[:64],
            Policy=write_policy.format(raw_bucket, uuid)
        )

        return to_jsonapi({
            'url': 's3://{}/{}/'.format(raw_bucket.split(':')[-1], uuid),
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
                stateMachineArn=sync_sfn,
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

        bucket = tile_bucket.split(':')[-1]

        image = self.client.get_image(uuid)
        fileset_uuid = image['data']['fileset_uuid']
        fileset = self.client.get_fileset(fileset_uuid)

        if fileset['data']['complete'] is not True:
            raise ValueError(
                f'Fileset has not had metadata extracted yet: {fileset_uuid}'
            )

        obj = boto3.resource('s3').Object(bucket,
                                          f'{fileset_uuid}/metadata.xml')
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
        self._has_permission(self.user_uuid, 'Image', uuid, 'Read')
        image = self.client.get_image(uuid)
        fileset_uuid = image['data']['fileset_uuid']

        # TODO Better session name?
        response = sts.assume_role(
            RoleArn=s3_assume_role_read,
            RoleSessionName='{}@{}'.format(self.user_uuid, uuid)[:64],
            Policy=read_policy.format(tile_bucket, uuid, fileset_uuid)
        )

        tile_bucket_name = tile_bucket.split(':')[-1]

        return to_jsonapi({
            'image_url': f's3://{tile_bucket_name}/{uuid}/',
            'fileset_url': f's3://{tile_bucket_name}/{fileset_uuid}/',
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
    def list_keys_in_fileset(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        self._has_permission(self.user_uuid, 'Fileset', uuid, 'Read')
        return self.client.list_keys_in_fileset(uuid)

    @response(200)
    def update_repository(self, event, context):
        uuid = _event_path_param(event, 'uuid')
        _validate_uuid(uuid)
        name = self.body.get('name')
        raw_storage = self.body.get('raw_storage')
        if name is not None:
            _validate_name(name)
        self._has_permission(self.user_uuid, 'Repository', uuid, 'Admin')
        return self.client.update_repository(uuid, name, raw_storage)

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
        return self.client.delete_repository(uuid)

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
    # @response(200)
    # def list_repositories_for_user(self, event, context):
    #     user = _event_user(event)
    #     return client.list_repositories_for_user(user)
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
    # @response(201)
    # def grant_repository_to_user(self, event, context):
    #     user = _event_user(event)
    #     repository = _event_path_param(event, 'uuid')
    #     grantee = _event_path_param(event, 'grantee')
    #     permissions = _event_query_param(event, 'permissions', True)
    #     for permission in permissions:
    #         _validate_permission(permission)
    #     _user_permission(user, repository, 'Admin')
    #     client.add_user_to_repository(repository, grantee, permissions)
    #     return {}


handler = Handler()
create_group = handler.create_group
cognito_details = handler.cognito_details
create_repository = handler.create_repository
create_import = handler.create_import
create_membership = handler.create_membership
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
list_keys_in_fileset = handler.list_keys_in_fileset
update_membership = handler.update_membership
update_import = handler.update_import
update_repository = handler.update_repository
delete_repository = handler.delete_repository
delete_membership = handler.delete_membership
