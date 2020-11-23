---
title: 'Response status codes'

layout: null
---

### Success

Successful request will return
```Status: 200 OK```

If a new resource is created as a result of the request, the response may be
```Status: 201 Created```

### Error

In case of error, the response will contain an object with a detailed error message.

```Status: 403 Forbidden```
```
{
    error: 'Unauthorized operation',
}
```

### Status codes

| Status code   | Description
| :----------- | :------------
| 200        | Request OK       
| 400        | Request is invalid or malformed
| 403        | No permission for the image or other operation
| 404     | Image or tile not found
| 422      | Request is invalid
| 500      | Server error