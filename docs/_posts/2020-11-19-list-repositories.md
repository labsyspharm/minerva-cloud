---
category: API
url_path: '/repository'
title: 'List repositories'
type: 'GET'

layout: null
---

Lists all repositories which the user is authorized to access.

### Request

### Response

Returns a list of repository UUIDs and the user's permission levels.
The response includes a full list of Repository objects.

```json
{
  "data": [
    {
      "subject_uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "repository_uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "permission": "Admin"
    }, 
    {
      "subject_uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "repository_uuid": "123e4567-e89b-12d3-a456-426614174000", 
      "permission": "Read"
    }
  ], 
  "included": 
    {
      "repositories": [
        {
          "uuid": "123e4567-e89b-12d3-a456-426614174000", 
          "name": "Repository 1", 
          "raw_storage": "Destroy", 
          "access": "Private"
        },
        {
          "uuid": "123e4567-e89b-12d3-a456-426614174000", 
          "name": "Repository 2", 
          "raw_storage": "Destroy",
          "access": "PublicRead"
        }
      ]
    }
}
```