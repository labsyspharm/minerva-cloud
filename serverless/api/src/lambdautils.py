import logging
from typing import Any, Callable, Dict, Union, List
from functools import wraps
import base64
import re
import json
from datetime import date, datetime
import numpy as np


class AuthError(Exception):
    pass


class TileBoundError(Exception):
    pass


class AspectRatioError(Exception):
    pass


def response(code: int) -> Callable[..., Dict[str, Any]]:
    """Decorator for turning exceptions into responses.

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
    """

    def wrapper(fn):
        @wraps(fn)
        def wrapped(self, event, context):

            # Execute the requested function and make a response or error
            # response
            try:
                self.session is None
                self.body = event_body(event)
                self.user_uuid = event_user(event)
                self.content_type = "image/jpeg"
                binary = True
                if "accept" in event["headers"]:
                    accept = event["headers"]["accept"]
                    accept_values = accept.split(",")
                    if "application/json" in accept_values:
                        binary = False

                if binary:
                    return make_binary_response(
                        code, fn(self, event, context), content_type=self.content_type
                    )
                else:
                    return make_response(code, fn(self, event, context))

            except KeyError as e:
                return make_response(400, {"error": str(e)})
            except (ValueError, AspectRatioError) as e:
                return make_response(422, {"error": str(e)})
            except AuthError as e:
                return make_response(403, {"error": str(e)})
            except TileBoundError as e:
                return make_response(404, {"error": str(e)})
            except Exception as e:
                logging.exception(e)
                return make_response(500, {"error": str(e)})
            finally:
                if self.session is not None:
                    self.session.close()

        return wrapped

    return wrapper


def json_custom(obj: Any) -> str:
    """JSON serializer for extra types."""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def make_response(code: int, body: Union[Dict, List]) -> Dict[str, Any]:
    """Build a response.

    Args:
        code: HTTP response code.
        body: Python dictionary or list to jsonify.

    Returns:
        Response object compatible with AWS Lambda Proxy Integration
    """

    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        },
        "body": json.dumps(body, default=json_custom),
    }


def make_binary_response(
    code: int, body: np.ndarray, content_type="image/jpeg"
) -> Dict[str, Any]:
    """Build a binary response.

    Args:
        code: HTTP response code.
        body: Numpy array representing image.

    Returns:
        Response object compatible with AWS Lambda Proxy Integration
    """

    return {
        "statusCode": code,
        "headers": {
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        },
        "body": base64.b64encode(body).decode("utf-8"),
        "isBase64Encoded": True,
    }


def event_body(event):
    if "body" in event and event["body"] is not None:
        return json.loads(event["body"])
    return {}


def event_user(event):
    print(event)
    if "claims" in event["requestContext"]["authorizer"]:
        uuid = event["requestContext"]["authorizer"]["claims"]["cognito:username"]
    else:
        uuid = event["requestContext"]["authorizer"]["principalId"]
    validate_uuid(uuid)
    return uuid


def event_path_param(event, key):
    return event["pathParameters"][key]


def event_query_param(event, key, multi=False):
    if "queryStringParameters" not in event:
        return None
    if event["queryStringParameters"] is None:
        return None
    if key not in event["queryStringParameters"]:
        return None

    value = event["queryStringParameters"][key]
    if multi is True:
        return value.split(",")
    return value


_valid_uuid = re.compile(
    "^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$"
)


def validate_uuid(u):
    if _valid_uuid.match(u) is None:
        raise ValueError(
            "UUID is invalid. Valid uuids are of the form "
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
