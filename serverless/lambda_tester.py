
import os
import base64
import json
import logging
import time
import statistics

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
logging.getLogger().setLevel(logging.INFO)

os.environ['STACK_PREFIX'] = 'minerva-juha'
os.environ['STAGE'] = 'dev'

from api.handler import handler as api_handler
from db.handler import handler as db_handler
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
    img_base64 = res["body"]
    img = base64.b64decode(img_base64)

    filename = f"./tile_L{level}_X{x}_Y{y}.jpg"
    print("Saving image to disk: ", filename)
    with open(filename, 'wb') as f:
        f.write(img)


def render_tile(uuid, color="FFFFFF"):
    parameters = {
        "uuid": uuid,
        "x": 0,
        "y": 0,
        "z": 0,
        "t": 0,
        "level": 0,
        "channels": "0," + color + ",0,1"
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
        "repository_uuid": repository_uuid
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

list_images_in_repository("48001701-d606-4fc8-b3fd-51dcf64296ef")
#create_image("Testi", 3, "48001701-d606-4fc8-b3fd-51dcf64296ef")
#get_image("4b7274d1-44de-4bda-989d-9ed48d24c1ac")

#for x in range(1, 5):
#    prerendered_tile(image_uuid="4b7274d1-44de-4bda-989d-9ed48d24c1ac", level=1, x=x, y=0, channel_group="5c7274d1-44de-4bda-989d-9ed48d24c1bd")

#render_tile("ada68902-4cac-49ca-9866-cc46bfff66b4", "0000FF")
#create_metadata("aec99d4d-e259-4ae8-a3b5-923ad7beed27")
#prerendered_tile("aec99d4d-e259-4ae8-a3b5-923ad7beed27", 4, 0, 0, "12c99d4d-e259-4ae8-a3b5-923ad7beed00")

#res = db_handler.delete_repository(EventBuilder().path_parameters({ "uuid": "48001701-d606-4fc8-b3fd-51dcf64296ef"}).build(), None)
#print(res)

#res = db_handler.delete_image(EventBuilder().path_parameters({ "uuid": "74cdd47f-0d4c-4f4e-8050-dd43061745ee"}).build(), None)
#print(res)

#create_rendering_settings()
#list_rendering_settings()