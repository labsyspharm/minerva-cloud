import boto3
import json
from concurrent.futures import ThreadPoolExecutor

s3 = boto3.client('s3')

def _create_key(story_uuid):
    return f"{str(story_uuid)}/story.json"

class AuthorS3Storage:

    def __init__(self, bucket):
        self.bucket = bucket

    def save_story(self, story, story_uuid):
        key = _create_key(story_uuid)
        s3.put_object(Body=story, Bucket=self.bucket, Key=key)

    def list_stories(self):
        res = s3.list_objects(Bucket=self.bucket)
        stories = {
            "stories": []
        }
        if "Contents" not in res:
            return stories

        executor = ThreadPoolExecutor(max_workers=10)
        for item in res['Contents']:
            story_uuid = item["Key"].split("/")[0]
            executor.submit(self._get_story_summary, story_uuid, stories)

        executor.shutdown(wait=True)
        return stories

    def _get_story_summary(self, story_uuid, stories):
        story = self.get_story(story_uuid)
        summary = {
            "uuid": story["uuid"],
            "imageUuid": story["imageUuid"],
            "sample_info": story["sample_info"],
            "last_updated": story["last_updated"],
            "image_name": story["image_name"],
            "author_name": story.get("author_name", ""),
            "author_uuid": story.get("author_uuid", "")
        }
        stories["stories"].append(summary)

    def get_story(self, story_uuid):
        key = _create_key(story_uuid)
        data = s3.get_object(Bucket=self.bucket, Key=key)
        story_dict = json.loads(data['Body'].read().decode('utf-8'))
        return story_dict
