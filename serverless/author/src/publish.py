import boto3
import json
import math
import logging
import base64
import os
from concurrent.futures import ThreadPoolExecutor
from .storyhtml import create_story_html


class StoryPublisher:
    def __init__(self, bucket, get_image_lambda_name, render_tile_lambda_name):
        self.bucket = bucket
        self.lambda_client = boto3.client('lambda')
        self.s3_client = boto3.client('s3')
        self.executor = ThreadPoolExecutor(max_workers=20)
        self.get_image_lambda_name = get_image_lambda_name
        self.render_tile_lambda_name = render_tile_lambda_name

    def publish(self, story, user_uuid, base_bucket, minerva_browser_url):
        self._create_story(story, minerva_browser_url)
        self._render_tiles(story, user_uuid)

    def _create_story(self, story, minerva_browser_url):
        story_uuid = story["uuid"]
        story_json = json.dumps(story)

        html = create_story_html(story_json, minerva_browser_url)

        key = f"{story_uuid}/minerva-story/index.html"
        self.s3_client.put_object(Body=html,
                                  Bucket=self.bucket,
                                  Key=key,
                                  ContentType="text/html")

    def _render_tiles(self, story, user_uuid):
        image_uuid = story["imageUuid"]

        # Read image
        body = self._get_image(user_uuid, image_uuid)
        metadata = body["data"]
        image = body["included"]["images"][0]
        width = metadata["pixels"]["SizeX"]
        height = metadata["pixels"]["SizeY"]
        pyramid_levels = image["pyramid_levels"]
        tile_size = image["tile_size"]

        for group in story["groups"]:
            self._render_group(group, image_uuid, width, height, pyramid_levels, tile_size, user_uuid, story)

        self.executor.shutdown()

    def _render_group(self, group, image_uuid, width, height, pyramid_levels, tile_size, user_uuid, story):
        sample_name = story["sample_info"]["name"]
        channels = group["channels"]
        channel_params = [f"{channel['id']},{channel['color']},{channel['min']},{channel['max']}" for channel in channels]
        channel_params = "/".join(channel_params)

        group_label = group["label"]
        channel_labels = [f"{channel['id']}__{channel['label']}" for channel in channels]
        channel_labels = "--".join(channel_labels)
        group_key = f"{group_label}_{channel_labels}"
        group_key = group_key.replace(' ', '-')

        logging.info("Rendering channel group %s", group_key)
        story_uuid = story["uuid"]
        tiles_x = math.ceil(width / tile_size)
        tiles_y = math.ceil(height / tile_size)
        for level in range(pyramid_levels):
            logging.info("Level %s", level)
            for x in range(tiles_x):
                for y in range(tiles_y):
                    self.executor.submit(self._render_and_upload, user_uuid, image_uuid, x, y, 0, 0, level, channel_params, story_uuid, group_key, sample_name)

            tiles_x = math.ceil(tiles_x / 2)
            tiles_y = math.ceil(tiles_y / 2)

    def _render_and_upload(self, user_uuid, image_uuid, x, y, z, t, level, channel_params, story_uuid, group_label, sample_name):
        logging.info("x=%s y=%s ", x, y)
        tile_img = self._render_tile(user_uuid, image_uuid, x, y, z, t, level, channel_params)
        key = f"{story_uuid}/minerva-story/images/{sample_name}/{group_label}/{level}_{x}_{y}.jpg"
        self.s3_client.put_object(Body=tile_img, Bucket=self.bucket, Key=key)

    def _get_image(self, user_uuid, image_uuid):
        payload = {
            "pathParameters": {
                "uuid": image_uuid
            },
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "cognito:username": user_uuid
                    }
                }
            },
            "headers": {
                "Accept": "image/jpeg"
            }
        }
        res = self.lambda_client.invoke(
            FunctionName=self.get_image_lambda_name,
            Payload=json.dumps(payload)
        )
        data = json.loads(res["Payload"].read())
        body = json.loads(data["body"])
        return body

    def _render_tile(self, user_uuid, uuid, x, y, z, t, level, channels):
        payload = {
            "pathParameters": {
                "uuid": uuid,
                "x": x,
                "y": y,
                "z": z,
                "t": t,
                "level": level,
                "channels": channels
            },
            "queryStringParameters": {"gamma": "1"},
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "cognito:username": user_uuid
                    }
                }
            },
            "headers": {
                "Accept": "image/jpeg"
            }
        }
        res = self.lambda_client.invoke(
            FunctionName=self.render_tile_lambda_name,
            Payload=json.dumps(payload)
        )
        data = res["Payload"].read()
        body = json.loads(data)["body"]
        return base64.b64decode(body)