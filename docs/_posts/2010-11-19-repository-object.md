---
category: Objects
title: 'Repository'

layout: null
---

Repository object describes an image repository, which is a collection of images. 

### Repository

| Attribute   | Description
| :----------- | :------------
| uuid        | Repository uuid (universally unique identifier)
| name        | Repository name (must be unique)
| raw_storage     | Controls whether original image is kept after importing (Archive, Live, Destroy)
| access      | Does repository control read access (Private, PublicRead)
