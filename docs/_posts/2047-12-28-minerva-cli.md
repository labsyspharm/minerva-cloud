---
title: 'Minerva CLI'

layout: null
---

### Minerva Command Line Interface

[Get Minerva CLI from GitHub](https://github.com/labsyspharm/minerva-cli)

Minerva CLI can be used to import images into Minerva Cloud from the command line.
Images can also be exported from Minerva Cloud into local disk.

### Examples

Import a directory into Minerva Cloud. All images within the directory will be imported.
The given repository will be created if it does not exist already.
```bash
python minerva.py import -r repository_name -d /home/user/images
```

Export an image from Minerva Cloud into local disk.
```bash
python minerva.py export --id 123e4567-e89b-12d3-a456-426614174000
```
