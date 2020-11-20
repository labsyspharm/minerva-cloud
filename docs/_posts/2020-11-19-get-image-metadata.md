---
category: API
url_path: '/image/{uuid}/metadata'
title: 'Get image metadata'
type: 'GET'

layout: null
---

Get image OME metadata as OME-XML.

### Request

| Parameter   | Description
| :----------- | :------------
| uuid        | Image uuid

<br/>

### Response

```xml
<OME>
    <Image ID="Image">
        ...
    </Image>
</OME>
```