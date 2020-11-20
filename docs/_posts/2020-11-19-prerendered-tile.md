---
category: API
url_path: '/image/{uuid}/prerendered-tile/{x}/{y}/{z}/{t}/{level}/{rs_uuid}'
title: 'Prerendered tile'
type: 'GET'

layout: null
---

Get a prerendered tile from an image.

This endpoint is similar to render-tile, but it uses rendering settings stored in the database.
This allows caching frequently used tiles and rendering settings. 

### Request

| Parameter   | Description
| :----------- | :------------
| uuid        | Image uuid
| x           | Tile X coordinate
| y           | Tile Y coordinate
| z           | Tile Z coordinate
| t           | Time, integer (use 0 for single images)
| level       | Pyramid level (0=highest detail)
| rs_uuid    | Rendering settings uuid

<br/>

### Response

Image tile encoded as 8-bit JPEG (binary).

### Example

```bash
curl -X GET -H "Authorization: Bearer ID_TOKEN" https://DOMAIN/STAGE/image/123e4567-e89b-12d3-a456-426614174000/prerendered-tile/1/2/0/0/1/123e4567-e89b-12d3-a456-426614174000
```
