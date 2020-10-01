import boto3
import json
import math
import logging
import base64
from concurrent.futures import ThreadPoolExecutor
from .storyhtml import create_story_html
from .convert import convert_to_exhibit
import time


class StoryPublisher:
    def __init__(self, bucket, get_image_lambda_name, render_tile_lambda_name, render_group_lambda_name):
        self.bucket = bucket
        self.lambda_client = boto3.client('lambda')
        self.s3_client = boto3.client('s3')
        self.get_image_lambda_name = get_image_lambda_name
        self.render_tile_lambda_name = render_tile_lambda_name
        self.render_group_lambda_name = render_group_lambda_name
        self.metadata = None
        self.image = None

    def publish(self, story, user_uuid, minerva_browser_url, render_images=True):
        logging.info("Publishing story uuid=%s render_images=%s", story["uuid"], render_images)
        self._load_image(user_uuid, story["imageUuid"])
        self._create_story(story, minerva_browser_url)
        if render_images:
            self._render_tiles(story, user_uuid)

    def get_published_status(self, story_uuid):
        res = self.s3_client.list_objects(Bucket=self.bucket, Prefix=story_uuid)
        if "Contents" not in res:
            return "unpublished"

        res = self.s3_client.list_objects(Bucket=self.bucket, Prefix=f"{story_uuid}/log")

        if "Contents" in res:
            for item in res['Contents']:
                if "SUCCESS" in item["Key"]:
                    return "published"
                if "FAILURE" in item["Key"]:
                    return "failure"

        return "processing"

    def _load_image(self, user_uuid, image_uuid):
        body = self._get_image(user_uuid, image_uuid)
        self.metadata = body["data"]
        self.image = body["included"]["images"][0]

    def _create_story(self, story, minerva_browser_url):
        print("Creating story")
        story_uuid = story["uuid"]
        img = {
            "width": self.metadata["pixels"]["SizeX"],
            "height": self.metadata["pixels"]["SizeY"],
            "pyramid_levels": self.image["pyramid_levels"]
        }
        story_json = json.dumps(convert_to_exhibit(story, img, self.bucket))

        html = create_story_html(story_json, minerva_browser_url)

        key = f"{story_uuid}/minerva-story/index.html"
        self.s3_client.put_object(Body=html,
                                  Bucket=self.bucket,
                                  Key=key,
                                  ContentType="text/html")

        try:
            key = f"{story_uuid}/minerva-story/favicon.png"
            self.s3_client.upload_file("images/favicon.png",
                                       Bucket=self.bucket,
                                       Key=key)
        except Exception as e:
            print(e)

    def _render_tiles(self, story, user_uuid):
        print("Rendering tiles")
        img = {
            "uuid": story["imageUuid"],
            "width": self.metadata["pixels"]["SizeX"],
            "height": self.metadata["pixels"]["SizeY"],
            "pyramid_levels": self.image["pyramid_levels"],
            "tile_size": self.image["tile_size"]
        }
        # Maximum timeout for lambda is 15min. To prevent rendering from timeouting,
        # we execute each group in a separate lambda run.
        for group in story["groups"]:
            self._start_render_lambda(group, img, user_uuid, story["sample_info"]["name"], story["uuid"])

    def _start_render_lambda(self, group, img, user_uuid, sample_name, story_uuid):
        payload = {
            "group": group,
            "image": img,
            "user_uuid": user_uuid,
            "sample_name": sample_name,
            "story_uuid": story_uuid
        }
        res = self.lambda_client.invoke(
            FunctionName=self.render_group_lambda_name,
            InvocationType="Event",
            Payload=json.dumps(payload)
        )
        if res["StatusCode"] not in [200, 202, 204]:
            print(res)
            raise Exception("Error in invoking lambda publishGroupInternal")

    def render_group(self, context, group, image, user_uuid, sample_name, story_uuid):
        start_time = time.time()
        num_tiles = 0
        channels = group["channels"]
        channel_params = [f"{channel['id']},{channel['color']},{channel['min']},{channel['max']}" for channel in channels]
        channel_params = "/".join(channel_params)

        group_label = group["label"]
        channel_labels = [f"{channel['id']}__{channel['label']}" for channel in channels]
        channel_labels = "--".join(channel_labels)
        group_key = f"{group_label}_{channel_labels}"
        group_key = group_key.replace(' ', '-')

        logging.info("Rendering channel group %s", group_key)
        tiles_x = math.ceil(image["width"] / image["tile_size"])
        tiles_y = math.ceil(image["height"] / image["tile_size"])

        executor = ThreadPoolExecutor(max_workers=15)
        pyramid = []
        for number in range(image["pyramid_levels"]):
            pyramid.append({
                "tiles_x": tiles_x,
                "tiles_y": tiles_y,
                "number": number
            })
            tiles_x = math.ceil(tiles_x / 2)
            tiles_y = math.ceil(tiles_y / 2)

        # Render highest pyramid levels (lowest detail) first, in that way the user can
        # open the story faster and see the image.
        for level in reversed(pyramid):
            logging.info("Level %s", level["number"])
            for x in range(level["tiles_x"]):
                for y in range(level["tiles_y"]):
                    num_tiles += 1
                    executor.submit(self._render_and_upload, user_uuid, image["uuid"], x, y, 0, 0, level["number"], channel_params, story_uuid, group_key, sample_name)

                    if context.get_remaining_time_in_millis() < 1000:
                        run_time = time.time() - start_time
                        self._mark_group_success(False, story_uuid, group["label"], run_time, num_tiles)

        executor.shutdown()
        run_time = time.time() - start_time
        self._mark_group_success(True, story_uuid, group["label"], run_time, num_tiles)

    def _render_and_upload(self, user_uuid, image_uuid, x, y, z, t, level, channel_params, story_uuid, group_label, sample_name):
        logging.info("x=%s y=%s ", x, y)
        tile_img = self._render_tile(user_uuid, image_uuid, x, y, z, t, level, channel_params)
        key = f"{story_uuid}/minerva-story/images/{sample_name}/{group_label}/{level}_{x}_{y}.jpg"
        self.s3_client.put_object(Body=tile_img, Bucket=self.bucket, Key=key)

    def _mark_group_success(self, success, story_uuid, group_name, run_time, num_tiles):
        status = "SUCCESS" if success else "FAILURE"
        key = f"{story_uuid}/log/publishGroupInternal_{status}_{group_name}.json"
        marker = {
            "group": group_name,
            "success": success,
            "duration": run_time,
            "tiles": num_tiles
        }
        self.s3_client.put_object(Body=json.dumps(marker), Bucket=self.bucket, Key=key)

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