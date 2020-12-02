
import os
import base64
import json
import logging
import sys
import time

import boto3

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
logging.getLogger().setLevel(logging.INFO)

os.environ['STACK_PREFIX'] = 'minerva-test'
os.environ['STAGE'] = 'dev'
os.environ['AWS_REGION'] = 'us-east-1'

logging.info("Start api_handler imports")
from api.src.handler import handler as api_handler
logging.info("End api_handler imports")
logging.info("Start db_handler imports")
from db.handler import handler as db_handler
logging.info("End db_handler imports")
#from db.internal import _init_db as init_db
#from auth.authorizer import handler as auth_handler

from lambda_helpers import EventBuilder


def prerendered_tile(image_uuid, level, x, y, channel_group):
    parameters = {
        "uuid": image_uuid,
        "x": x,
        "y": y,
        "z": 0,
        "t": 0,
        "level": level,
        "channel_group": channel_group
    }
    event = EventBuilder().path_parameters(parameters).build()

    res = api_handler.prerendered_tile(event, None)
    if res['statusCode'] != 200:
        print(res)

    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    filename = f"./tile_L{level}_X{x}_Y{y}.jpg"
    print("Saving image to disk: ", filename)
    with open(filename, 'wb') as f:
        f.write(img)

def histogram(uuid, channels="4,5,6,7", method="histogram"):
    parameters = {
        "uuid": uuid,
        "channels": channels
    }
    q = {
        "method": method
    }
    event = EventBuilder().path_parameters(parameters).query_parameters(q).build()
    event["headers"]["accept"] = "application/json"
    res = api_handler.get_histogram(event, None)
    print(res)

def raw_tile(uuid, x=0, y=0, level=0, channel=0):
    parameters = {
        "uuid": uuid,
        "x": x,
        "y": y,
        "z": 0,
        "t": 0,
        "level": level,
        "channels": channel
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = api_handler.raw_tile(event, None)
    if res['statusCode'] != 200:
        print(res)

    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    filename = "{}-C{}-T0-Z0-L{}-Y{}-X{}.png".format(uuid, channel, level, y, x)

    filename = os.path.join('images', filename)
    with open(filename, 'wb') as f:
        f.write(img)

def render_tile(uuid, x=0, y=0, level=0, channels="0,FFFFFF,0,1", filename=None):
    parameters = {
        "uuid": uuid,
        "x": x,
        "y": y,
        "z": 0,
        "t": 0,
        "level": level,
        "channels": channels
    }
    query_params = {
        "gamma": 1
    }
    event = EventBuilder().path_parameters(parameters).query_parameters(query_params).build()
    res = api_handler.render_tile(event, None)
    if res['statusCode'] != 200:
        print(res)
    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    channel = channels.split(',')[0]
    if filename is None:
        filename = "{}-C{}-T0-Z0-L{}-Y{}-X{}.jpg".format(uuid, channel, level, y, x)

    filename = os.path.join('images', filename)
    print("Writing tile: ", filename)
    with open(filename, 'wb') as f:
        f.write(img)

def omero_render_tile(uuid, x=0, y=0, level=0, c="1|0:65535$FF0000", filename=None):
    parameters = {
        "uuid": uuid,
        "z": 0,
        "t": 0
    }
    query_params = {
        "c": c,
        "tile": "{},{},{},1024,1024".format(level, x, y)
    }
    event = EventBuilder().path_parameters(parameters).query_parameters(query_params).build()
    res = api_handler.omero_render_tile(event, None)
    if res['statusCode'] != 200:
        print(res)
    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    if filename is None:
        filename = "OMERO-C_-T0-Z0-L{}-Y{}-X{}.jpg".format(level, y, x)

    with open(filename, 'wb') as f:
        f.write(img)

def get_image_credentials(uuid):
    parameters = {
        "uuid": uuid
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.get_image_credentials(event, None)
    return res

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

def get_image(uuid):
    parameters = {
        "uuid": uuid
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.get_image(event, None)
    print(res)

def create_image(name, pyramid_levels, repository_uuid):
    body = {
        "name": name,
        "pyramid_levels": pyramid_levels,
        "repository_uuid": repository_uuid,
        "format": "tiff",
        "compression": "zstd",
        "tile_size": 1024,
        "rgb": False
    }
    body_json = json.dumps(body)
    event = EventBuilder().body(body_json).build()

    res = db_handler.create_image(event, None)
    print(res)

def list_images_in_repository(repository_uuid):
    parameters = {
        "uuid": repository_uuid
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.list_images_in_repository(event, None)
    print(res)

def list_grants_for_repository(repository_uuid):
    parameters = {
        "uuid": repository_uuid
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.list_grants_for_repository(event, None)
    print(res)

def find_user(search):
    parameters = {
        "search": search
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.find_user(event, None)
    print(res)

def grant_repository_to_user(repository_uuid, user_uuid):
    body = {
        "uuid": repository_uuid,
        "resource": "repository",
        "grantee": user_uuid,
        "permissions": "Read"
    }
    event = EventBuilder().body(body).build()
    res = db_handler.grant_resource_to_user(event, None)
    print(res)

def update_repository(uuid, data):
    event = EventBuilder().path_parameters({"uuid": uuid}).body(data).build()
    res = db_handler.update_repository(event, None)
    print(res)

def mark_import_finished(import_uuid):
    body = {
        "complete": True
    }
    event = EventBuilder().path_parameters({"uuid": import_uuid}).body(body).build()
    db_handler.update_import(event, None)

def get_metadata(image_uuid):
    parameters = {
        "uuid": image_uuid
    }
    event = EventBuilder().path_parameters(parameters).build()
    res = db_handler.get_image_metadata(event, None)
    print(res)

def create_metadata(image_uuid):
    xml = """<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" UUID="urn:uuid:7e6a38a4-d28c-4efe-b519-48d1314bad67" xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
    <Image>
        <Pixels BigEndian="false" DimensionOrder="XYZCT" ID="Pixels:0" Interleaved="false" PhysicalSizeX="0.649999976158" PhysicalSizeXUnit="µm" PhysicalSizeY="0.649999976158" PhysicalSizeYUnit="µm" SignificantBits="16" SizeC="36" SizeT="1" SizeX="11392" SizeY="9600" SizeZ="1" Type="uint16">
            <Channel ID="Channel:0:0" Name="DNA" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:1" Name="A488 background" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:2" Name="A555 background" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:3" Name="A647 background" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:4" Name="DNA 2" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:5" Name="S100" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:6" Name="VEGFR2" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:7" Name="SMA" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:8" Name="DNA 3" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:9" Name="KI67" SamplesPerPixel="1">
                <LightPath />
            </Channel>
            <Channel ID="Channel:0:10" Name="VIMENTIN" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:11" Name="PDL1" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:12" Name="DNA 4" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:13" Name="CD4" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:14" Name="CD3" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:15" Name="CD8" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:16" Name="DNA 5" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:17" Name="CD45RO" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:18" Name="FOXP3" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:19" Name="PD1" SamplesPerPixel="1">
                <LightPath />
            </Channel>
            <Channel ID="Channel:0:20" Name="DNA 6" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:21" Name="ECAD" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:22" Name="A555" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:23" Name="CATENIN" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:24" Name="DNA 7" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:25" Name="cJUN" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:26" Name="pRB" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:27" Name="NGFR" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:28" Name="DNA 8" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:29" Name="MITF" SamplesPerPixel="1">
                <LightPath />
            </Channel>             
			<Channel ID="Channel:0:30" Name="KERATIN" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:31" Name="HES1" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:32" Name="DNA 9" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:33" Name="pS6" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:34" Name="CD45" SamplesPerPixel="1">
                <LightPath />
            </Channel>
			<Channel ID="Channel:0:35" Name="pERKz" SamplesPerPixel="1">
                <LightPath />
            </Channel>
        </Pixels>
    </Image>
</OME>  
    """
    parameters = {
        "uuid": image_uuid
    }
    event = EventBuilder().path_parameters(parameters).body(xml).build()
    res = db_handler.create_metadata(event, None)
    print(res)

#list_images_in_repository("48001701-d606-4fc8-b3fd-51dcf64296ef")
create_image("Testi", 3, "8778bc8b-605d-499b-a9d9-97cc3f8d55e9")
#get_image("9a45c19a-3292-4eee-a848-5282657ae5d7")

#res = get_image_credentials("aec99d4d-e259-4ae8-a3b5-923ad7beed27")
#print(res)

#for x in range(1, 5):
#    prerendered_tile(image_uuid="4b7274d1-44de-4bda-989d-9ed48d24c1ac", level=1, x=x, y=0, channel_group="5c7274d1-44de-4bda-989d-9ed48d24c1bd")

#render_tile("540fa7e9-2579-4496-84a7-9f525552d502z", x=2, y=1, level=1, channels="12,0000FF,0.30518044,1")
#render_tile("540fa7e9-2579-4496-84a7-9f525552d502", x=2, y=1, level=1, channels="17,00FF00,0.045777066,0.534065766")
#render_tile("540fa7e9-2579-4496-84a7-9f525552d502", x=2, y=1, level=1, channels="13,FF0000,0.061036088,0.228885328")
#render_tile("a86af320-ea86-4d81-8608-3fb4519b251c", x=0, y=0, level=0, channels="0,FF0000,0.001036088,0.994065766")

#from line_profiler import LineProfiler
#profile = LineProfiler()
#from minerva_lib import render
#profile.add_function(render.composite_channel)

#histogram("ba9eb627-c7e0-429c-a126-108d85a3f02f", "0,18,35", method="histogram")
#histogram("0dd7f3c2-8719-419a-86ed-3be20c89de5b", "0,6,10,11", method="gaussian")
#render_tile("deff258c-efa3-4843-9e0b-cdde2918d3e6", x=1, y=5, level=0, channels="4,ffffff,0.01,1/5,ff0000,0.01,0.33/6,00ff00,0.01,0.33/7,0000ff,0.01,0.33")
# Request URL: https://nldzj7hd69.execute-api.us-east-1.amazonaws.com/dev/image/deff258c-efa3-4843-9e0b-cdde2918d3e6/render-tile/1/5/0/0/0/4,ffffff,0.01,1/5,ff0000,0.01,0.33/6,00ff00,0.01,0.33/7,0000ff,0.01,0.33?gamma=1

#render_tile("b4727bc6-89c3-4398-b6d9-057fa4d9ed3a", x=5, y=5, level=1, channels="0,FF0000,0,1/1,00FF00,0,1/2,0000FF,0,1")
#omero_render_tile("5063c599-aad7-42fe-a2c9-15870a0440da", x=0, y=0, level=5, c="1|0:65535$FF0000,2|0:65535$00FF00,3|0:65535$0000FF,-4|0:65535$FF0000,-5|0:65535$00FF00,-6|0:65535$0000FF,-7|0:65535$FF0000,-8|0:65535$00FF00,-9|0:65535$0000FF,-10|0:65535$FF0000,-11|0:65535$00FF00,-12|0:65535$0000FF,-13|0:65535$FF0000,-14|0:65535$00FF00,-15|0:65535$0000FF,-16|0:65535$FF0000,-17|0:65535$00FF00,-18|0:65535$0000FF,-19|0:65535$FF0000,-20|0:65535$00FF00,-21|0:65535$0000FF,-22|0:65535$FF0000,-23|0:65535$00FF00,-24|0:65535$0000FF,-25|0:65535$FF0000,-26|0:65535$00FF00,-27|0:65535$0000FF,-28|0:65535$FF0000,-29|0:65535$00FF00,-30|0:65535$0000FF,-31|0:65535$FF0000,-32|0:65535$00FF00,-33|0:65535$0000FF,-34|0:65535$FF0000,-35|0:65535$00FF00,-36|0:65535$0000FF")
#omero_render_tile("5063c599-aad7-42fe-a2c9-15870a0440da", x=11, y=5, level=0, c="-1|3000:45000$0000FF,-2|3000:30000$00FF00,-3|3000:30000$FFFFFF,-4|3000:30000$FF0000,-5|3000:30000$0000FF,-6|4000:40000$00FF00,-7|3000:30000$FFFFFF,-8|5000:40000$FF0000,-9|3000:45000$0000FF,-10|3000:30000$00FF00,-11|3000:30000$FFFFFF,-12|4000:45000$FF0000,-13|3000:40000$0000FF,-14|3000:30000$00FF00,-15|1500:10000$FFFFFF,-16|3000:45000$FF0000,-17|3000:45000$0000FF,-18|3000:30000$00FF00,-19|3000:30000$FFFFFF,-20|2500:10000$FF0000,21|3000:45000$0000FF,22|3000:30000$00FF00,23|0:65535$FFFFFF,24|0:65535$FF0000,-25|0:65535$0000FF,-26|0:65535$00FF00,-27|0:65535$FFFFFF,-28|0:65535$FF0000,-29|0:65535$0000FF,-30|0:65535$00FF00,-31|0:65535$FFFFFF,-32|0:65535$FF0000,-33|0:65535$0000FF,-34|0:65535$00FF00,-35|0:65535$FFFFFF,-36|0:65535$FF0000")

#render_tile("fedf8ea0-96bf-47d6-88ed-16275d4dadc9", x=0, y=0, level=4, channels="0,FF0000,0,1/1,0000FF,0,1")

#render_tile("fedf8ea0-96bf-47d6-88ed-16275d4dadc9", x=1, y=1, level=0, channels="0,FF0000,0,0.000001")

#profile.dump_stats("profile.lprof")
#render_tile("540fa7e9-2579-4496-84a7-9f525552d502", x=2, y=1, level=1, channels="12,0000FF,0.30518044,1/17,00FF00,0.045777066,0.534065766/13,FF0000,0.061036088,0.228885328/18,FFFFFF,0.061036088,0.534065766", filename="tile_blended.jpg")

#create_metadata("aec99d4d-e259-4ae8-a3b5-923ad7beed27")
#prerendered_tile("9a45c19a-3292-4eee-a848-5282657ae5d7", 1, 4, 2, "0073d26e-df25-4b58-b3bf-41e6085121f1")
#get_metadata("dfd24119-393f-4ad8-a4dd-e99ee159ae37")

#res = db_handler.delete_repository(EventBuilder().path_parameters({ "uuid": "48001701-d606-4fc8-b3fd-51dcf64296ef"}).build(), None)
#print(res)

#res = db_handler.delete_image(EventBuilder().path_parameters({ "uuid": "74cdd47f-0d4c-4f4e-8050-dd43061745ee"}).build(), None)
#print(res)

#create_rendering_settings()
#list_rendering_settings()

#list_grants_for_repository("d3c20894-5831-4273-b2f5-1be266a1a8cb")
#grant_repository_to_user("d3c20894-5831-4273-b2f5-1be266a1a8cb", "de09a291-1c75-442d-b8f8-e257dd455232")
#find_user("juha")

# event = {
#     'authorizationToken': 'Bearer eyJraWQiOiJkdld5SFBwa2hPQWxrOTVEMUlmaWZ5RzFZSDNLanEyc2tRaHRTdlwvaHIrWT0iLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJkOWU4Y2FjMC01YjA4LTQzZDYtODRmYi04MzAzNDQ3NzgzYTYiLCJhdWQiOiJjdnV1dXVvZ2g2bm1xbTg0OTFpaXUxbGg1IiwiZXZlbnRfaWQiOiI5NmFlY2I3MC02ZDQ2LTQ5ZjMtYjcxYy1jYzZmNzMwNTc0ZDMiLCJ0b2tlbl91c2UiOiJpZCIsImF1dGhfdGltZSI6MTU4NDA0NjcxMSwiaXNzIjoiaHR0cHM6XC9cL2NvZ25pdG8taWRwLnVzLWVhc3QtMS5hbWF6b25hd3MuY29tXC91cy1lYXN0LTFfZDNXdXN4NnFwIiwiY29nbml0bzp1c2VybmFtZSI6ImQ5ZThjYWMwLTViMDgtNDNkNi04NGZiLTgzMDM0NDc3ODNhNiIsImV4cCI6MTU4NTA1NzUzMCwiaWF0IjoxNTg1MDUzOTMwLCJlbWFpbCI6Imp1aGFfcnVva29uZW5AaG1zLmhhcnZhcmQuZWR1In0.cQIlziOeAG00TMz855_os1hejT9Gk-3IuBvDOZtGYmGh8gHZ_3EDklZXdi-FqDxeCTnZBFoSZ0w7iw41GfMwjkMQyd4DE5-p0GgA-mM2hPzuaGtu6dxy6d0gxH8qDRuqCfES0uaC3N3JhJFsGszHHRWZ1z7hylboya6sOlo9PJ4H_Lfob6jVpeqdm5TM2kdJ6sIKYUgNLk3SvJNTjmJxiQY8Uu47HuQvwAaDXpbGeXyfpnOEeRLmPalwQ3vLE7tNlhSvAIb-Yb0sUURb6E4JG4B64coh7ryTDr9UZ7iA-WiWHSIE9Jiq23kBj5rnzmmnAXpcDaowFzFyVUfbj8OvUw',
#     'methodArn': 'arn:aws:execute-api:us-east-1:292075781285:3v21j4dh1d/dev/GET/authtest'
# }
# auth_handler.authorize_request(event, None)

#event = {
#     'authorizationToken': 'Bearer eyJraWQiOiJYT0E0b01xV1RsMzFBbGRMQUh3UXNzREoyWEg5ZnFlU015MVJaVXdSb2dvPSIsImFsZyI6IlJTMjU2In0.eyJzdWIiOiJiYjA4N2RjNi0wNTA2LTRjOTYtYjFiZS0wMDdiZDc0ZDk0NWYiLCJhdWQiOiI2Y3RzbmpqZ2xtdG5hMnE1Zmd0cmp1ZzQ3ayIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ0b2tlbl91c2UiOiJpZCIsImF1dGhfdGltZSI6MTU4ODAxNzQyNiwiaXNzIjoiaHR0cHM6XC9cL2NvZ25pdG8taWRwLnVzLWVhc3QtMS5hbWF6b25hd3MuY29tXC91cy1lYXN0LTFfWXVURjlTVDRKIiwibmFtZSI6Imp1aGFfcnVva29uZW5AaG1zLmhhcnZhcmQuZWR1IiwiY29nbml0bzp1c2VybmFtZSI6ImJiMDg3ZGM2LTA1MDYtNGM5Ni1iMWJlLTAwN2JkNzRkOTQ1ZiIsInByZWZlcnJlZF91c2VybmFtZSI6Imp1aGFfcnVva29uZW5AaG1zLmhhcnZhcmQuZWR1IiwiZXhwIjoxNTg4MTY1NTcxLCJpYXQiOjE1ODgxNjE5NzEsImVtYWlsIjoianVoYV9ydW9rb25lbkBobXMuaGFydmFyZC5lZHUifQ.jl_ewfVyCem-7tQUGLsgQ_YLIMSQ07ojv8-Tq-dBQlIr_UKiIl7Hbj0cj54H1zsVTZicQm1YPCpwk_VqbIzpQGMRU2S4rmDjbkYgH-yVIBvlk8n2PLjl9FV4eFCzvhaZ4wDAMSuP7-6mtTOYjAYuGwWb_f7ejVni5EdrUEfi0qhn7Y-qtBixxU_SJ2bEJEtNWpdeGKbbBmXCW46R8cbXFinPxvztOSLOy5vLoA4AX18IvfmwdoDUIWiUrOaVckItJvKOOecVV6nPGtqKAXzipLzGOW8B130AySbeNaJ8HH6JqiMR705LI_jfuUfn41lqArzHqzq9wGy8dXkhhP8Cqg',
#     'methodArn': 'arn:aws:execute-api:us-east-1:292075781285:3v21j4dh1d/dev/GET/authtest'
# }

#auth_handler.authorize_request(event, None)

#init_db('postgresql', 'minerva_test', 'minerva_test', 'localhost', 5432, 'minerva_test')

#update_repository("5611b0c8-b565-4e08-9e8a-b1b27c974d12", {"raw_storage": "Destroy", "access": "Private"})

#mark_import_finished("d8702810-5f2a-4d17-a899-37ad42eb3bce")

#raw_tile("a86af320-ea86-4d81-8608-3fb4519b251c")