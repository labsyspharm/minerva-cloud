---
category: Objects
title: 'Image'

layout: null
---

Image object describes a single image. Does not contain pixel data (which is stored in S3 object storage).

### Image

| Attribute   | Description
| :----------- | :------------
| uuid        | Image uuid (universally unique identifier)
| name        | Image name
| deleted     | Image has been marked for deletion
| format      | File format of the underlying object storage (tiff, zarr, etc.)
| compression | Method used for compressing raw image data (zstd, png, etc.)
| tile_size   | Tile size for the image pyramid (default 1024)
| pyramid_levels | Number of detail levels in the image pyramid
| fileset_uuid | Fileset uuid, can be null
| repository_uuid | Repository uuid