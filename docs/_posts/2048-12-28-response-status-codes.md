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

```Status: 403 Forbidden```
```
{
    error: 'Unauthorized operation',
}
```
