
import os
import base64
import json

os.environ['STACK_PREFIX'] = 'minerva-juha'
os.environ['STAGE'] = 'dev'

from api.handler import handler as api_handler
from db.handler import handler as db_handler
from lambda_helpers import EventBuilder


def prerendered_tile():
    parameters = {
        "uuid": "0c18ba28-872c-4d83-9904-ecb8b12b514d",
        "x": 0,
        "y": 0,
        "z": 0,
        "t": 0,
        "level": 2,
        "channel_group": "8d55b264-051a-498b-a9c5-f6e7be7e00fd"
    }
    event = EventBuilder().path_parameters(parameters).build()

    res = api_handler.prerendered_tile(event, None)
    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    with open('./prerendered_tile_test.jpg', 'wb') as f:
        f.write(img)


def render_tile():
    parameters = {
        "uuid": "0c18ba28-872c-4d83-9904-ecb8b12b514d",
        "x": 0,
        "y": 0,
        "z": 0,
        "t": 0,
        "level": 2,
        "channels": "0,FFFFFF,0.01,0.994"
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = api_handler.render_tile(event, None)
    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    with open('./render_tile_test.jpg', 'wb') as f:
        f.write(img)


def create_rendering_settings():
    parameters = {
        "uuid": "0c18ba28-872c-4d83-9904-ecb8b12b514d"
    }
    body = {
        "groups": [{
            "label": "First Group",
            "channels": [
                {
                    "color": "007fff",
                    "min": 0,
                    "max": 1,
                    "label": "Channel 4",
                    "id": 4
                },
                {
                    "color": "ff0000",
                    "min": 0.1,
                    "max": 0.82,
                    "label": "Channel 5",
                    "id": 5
                }
            ]
        },
        {
            "label": "Second Group",
            "id": "f2b61d82-b7ad-4fa3-8f40-130a6846e4f5",
            "channels": [
                {
                    "color": "007fff",
                    "min": 0,
                    "max": 1,
                    "label": "Channel 4",
                    "id": 4
                },
                {
                    "color": "ff0000",
                    "min": 0.1,
                    "max": 0.82,
                    "label": "Channel 5",
                    "id": 5
                }
            ]
        }
        ]
    }
    body_json = json.dumps(body)
    event = EventBuilder().path_parameters(parameters).body(body_json).build()
    res = db_handler.create_rendering_settings(event, None)
    print(res)


def list_rendering_settings():
    parameters = {
        "uuid": "0c18ba28-872c-4d83-9904-ecb8b12b514d"
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.list_rendering_settings_for_image(event, None)
    print(res)


#render_tile()
prerendered_tile()
#create_rendering_settings()
#list_rendering_settings()