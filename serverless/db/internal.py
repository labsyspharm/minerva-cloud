from functools import wraps
import os
import logging
import boto3
import json
import re
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from minerva_db.sql.api import Client
from minerva_db.sql.models import Base, User, Group, Membership


logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Get environment variables
STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')

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


def _setup_db():
    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string)
    return sessionmaker(bind=engine)


DBSession = _setup_db()
session = None
client = None


def in_session(fn):
    @wraps(fn)
    def wrapper(event, context):

        # Create a session and client to handle this request
        global session
        global client
        session = DBSession()
        client = Client(session)

        return fn(event, context)
    return wrapper


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
        raise ValueError('UUID is invalid. Valid uuids are of the form'
                         'abcdefgh-ijkl-mnop-qrst-uvwxyz012345')


# TODO Any active connection will block this. Use scoped sessions in all
# lambdas to overcome this
def _init_db_handler(event, context):
    _init_db('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)

def _init_db(drivername, username, password, host, port, database):
    connection_string = URL(drivername, username=username,
                            password=password, host=host, port=port,
                            database=database)
    engine = create_engine(connection_string)
    DBSession.close_all()

    # In case the schema has changed, drop the entire schema instead of
    # dropping tables
    # Base.metadata.drop_all(engine)
    with engine.connect() as conn:
        conn.execute('DROP SCHEMA public CASCADE')
        conn.execute('CREATE SCHEMA public')
        conn.execute(f'GRANT ALL ON SCHEMA public TO {username}')

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    # Get the list of currently confirmed users from Cognito
    user_pool_arn = ssm.get_parameter(
        Name='/{}/{}/common/CognitoUserPoolARN'.format(STACK_PREFIX, STAGE)
    )['Parameter']['Value']

    user_pool_id = user_pool_arn.split('/')[-1]

    idp = boto3.client('cognito-idp')
    response = idp.list_users(
        UserPoolId=user_pool_id,
        AttributesToGet=['preferred_username']
    )

    # Create the existing users
    print(response)
    users = []
    for cognito_user in response['Users']:
        user = User(cognito_user['Username'])
        if 'Attributes' in cognito_user:
            for name_value in cognito_user['Attributes']:
                if name_value['Name'] == 'preferred_username':
                    user.name = name_value['Value']

        users.append(user)

    session.add_all(users)
    session.commit()

    # Create Guest user
    guest = User("00000000-0000-0000-0000-000000000000", "Guest")
    session.add(guest)

    # Create public read group
    group_uuid = str(uuid4())
    public_read = Group(group_uuid, "MinervaPublicRead")
    session.add(public_read)

    # Make Guest user a member of public read group
    membership = Membership(public_read, guest)
    session.add(membership)

    session.commit()

def _query_db(event, context):
    connection_string = URL('postgresql', username=db_user,
                            password=db_password, host=db_host, port=db_port,
                            database=db_name)
    engine = create_engine(connection_string)

    with engine.connect() as conn:
        rows = conn.execute(event['query'])
        return {
            'query': event['query'],
            'results': json.dumps([[col for col in row] for row in rows])
        }


@in_session
def create_fileset(event, context):
    name = event['name']
    reader = event['reader']
    keys = event['keys']
    import_uuid = event['import_uuid']
    _validate_name(name)
    _validate_uuid(import_uuid)
    uuid = str(uuid4())

    return client.create_fileset(uuid, name, reader, keys, import_uuid)


@in_session
def add_keys_to_import(event, context):
    import_uuid = event['import_uuid']
    keys = event['keys']
    client.add_keys_to_import(keys, import_uuid)


@in_session
def set_fileset_complete(event, context):
    fileset_uuid = event['fileset_uuid']
    images = None
    if 'images' in event:
        images = event['images']

    complete = False
    if 'complete' in event and event['complete'] in ['True', 'true', '1']:
        complete = True

    progress = None
    if 'progress' in event:
        progress = event['progress']

    client.update_fileset(fileset_uuid, complete=complete, images=images, progress=progress)

@in_session
def create_user(event, context):
    # TODO Handle case where a number of users are imported which may
    #      already exist in the database
    # Register the user in the minerva database
    if event['triggerSource'] in ['PreSignUp_AdminCreateUser',
                                  'PostConfirmation_ConfirmSignUp']:
        uuid = event['userName']
        email = event['request']['userAttributes']['email']
        print(event)
        _validate_uuid(uuid)

        # Check if the user already exists. Cognito seems to have a retry
        # policy that can be triggered (potentially) by running this lambda
        # function when it is not hot. As a result, if the user is found, then
        # simply skip user creation
        try:
            client.get_user(uuid)
            return event
        except NoResultFound:
            print(f'User already exists, skipping creation: {uuid}')

        print(f'Creating user: {uuid}')
        client.create_user(uuid, name=email)

    return event
