---
category: API
url_path: '/image/{uuid}/render-tile/{x}/{y}/{z}/{t}/{level}/{channels+}'
title: 'Render tile'
type: 'GET'

layout: null
---

Render a tile from an image.

### Request

| Parameter   | Description
| :----------- | :------------
| uuid        | Image uuid
| x           | Tile X coordinate
| y           | Tile Y coordinate
| z           | Tile Z coordinate
| t           | Time, integer (use 0 for single images)
| level       | Pyramid level (0=highest detail)
| channels    | Channel rendering settings, see the details below.
|             |

#### Channel rendering settings

Pattern for settings is: **index1,color1,min1,max1/index2,color2,min2,max2/...**
`0,FFFFFF,0.1,0.9/1,00FF00,0.2,0.8`
* index - Index of the channel (integer, indexing starts from 0)
* color - RGB in hex format, e.g. the representation for color blue is `0000FF`
* min - Min intensity value (floating point 0-1.0)
* max - Max intensity value (floating point 0-1.0)

### Response

Image tile encoded as 8-bit JPEG (binary).

### Example

```bash
curl -X GET -H "Authorization: Bearer ID_TOKEN" https://DOMAIN/STAGE/image/123e4567-e89b-12d3-a456-426614174000/render-tile/1/2/0/0/1/0,FFFFFF,0.1,0.9/1,00FF00,0.2,0.8
```

This request will render the following tile:
* Image uuid 123e4567-e89b-12d3-a456-426614174000
* X = 1
* Y = 2
* Z = 0
* T = 0
* Level = 1
* Channel 0 as white with intensity scaled between 0.1-0.9
* Channel 1 as green with intensity scaled between 0.2-0.8
