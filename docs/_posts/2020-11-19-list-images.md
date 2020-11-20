---
category: API
url_path: '/repository/{uuid}/images'
title: 'List images in a repository'
type: 'GET'

layout: null
---

Lists all images in a repository.

### Request

| Parameter   | Description
| :----------- | :------------
| uuid        | Repository uuid


### Response

Returns a list of Image objects.

```json
{
  "data": [
    {
      "repository_uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "tile_size": 1024, 
      "format": "tiff", 
      "pyramid_levels": 6, 
      "fileset_uuid": "123e4567-e89b-12d3-a456-426614174000",
      "uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "name": "image.ome", 
      "deleted": false, 
      "compression": "zstd"
    }
  ],
  "included": {}
}
```