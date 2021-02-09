---
title: 'Importing images'

layout: null
---

### About importing images

This section describes the **low-level mechanics** of image importing. The easiest way to import images is to use either Minerva Cloud web interface or **Minerva CLI**.

Multichannel microscopy images tend to be large, a typical image might be in the range of 10-200 GBs. Importing them takes several minutes to one hour. AWS Lambda timeout is not enough and therefore the image importing process is run in a background AWS Batch job. The import process generates a tiled image pyramid (or uses an existing pyramid) and stores it in S3 as OME-ZARR, a highly scalable tile structure. The original image file is either discarded or it can be archived in low-cost S3 Glacier.

### Import steps

#### 1. Create a repository

Create a new repository to put the image in. You can skip this step when using an existing repository.

```bash
curl -X POST -H "Content-Type: application/json" -d '{"name": "Repository 1", "raw_storage": "Destroy"}' https://$BASE_URL/repository
```

The response will contain a repository uuid which must be used in the next step.

#### 2. Create an import

First we need a new import object which will be used for tracking the progress.

```bash
curl -X POST -H "Content-Type: application/json" -d '{"name": "Import 1", "repository_uuid": "123e4567-e89b-12d3-a456-426614174000"}' https://$BASE_URL/import
```

The response will contain an import uuid which must be used in the next step.

#### 3. Get S3 credentials for the import key

Next we must request temporary AWS credentials to obtain upload access to Minerva's S3 bucket.

```bash
curl -X GET https://$BASE_URL/import/{import_uuid}/credentials
```

The response will contain AWS credentials, S3 bucket name and key to upload the import into.

#### 4. Upload the image to the S3 bucket/key

Upload the image to the given S3 bucket and key, using the provided **AWS temporary credentials** (NOT the user's credentials). You can use e.g. AWS CLI or any programmatic client like boto3 for Python.

```python
import boto3

# Replace values of AccessKeyId, SecretAccessKey, SessionToken, Bucket, Key with values obtained from the previous step.

s3 = boto3.client("s3", aws_access_key_id="AccessKeyId",
                    aws_secret_access_key="SecretAccessKey",
                    aws_session_token="SessionToken",
                    region_name="us-east-1")

s3.upload_file("/images/image1.ome.tif", "Bucket", "Key/Image_Name.ome.tif")
```

#### 5. After the upload has finished, mark the import complete

Marking the import complete will trigger the AWS Batch Job, so it must be done only after uploading has finished.

```bash
curl -X PUT -H "Content-Type: application/json" -d '{"complete": true }' https://$BASE_URL/import/{import_uuid}
```

#### 6. Wait for the import Batch Job to finish

The import Batch Job may take around 10-60 mins, depending on image size and EC2 instance availability. The status of the import can be checked with:

```bash
curl -X GET https://$BASE_URL/import/{import_uuid}/filesets
```