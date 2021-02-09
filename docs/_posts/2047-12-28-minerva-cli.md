---
title: 'Minerva CLI'

layout: null
---

### Minerva Command Line Interface

Minerva CLI can be used to import images into Minerva Cloud from the command line.
Images can also be exported from Minerva Cloud into local disk.

#### Install Minerva CLI
```bash
# Use Python >= 3.7
pip install minerva-cli
minerva configure
```

#### Importing

Import a directory into Minerva Cloud. All images within the directory will be imported.
The given repository will be created if it does not exist already.
By default the image will be processed server side.
```bash
minerva import -r repository_name -d /home/user/images
```

Optionally when importing OME-TIFF files, the image can be processed client side by passing the argument --local.
Local import can be faster when importing just a single or few files.
```bash
minerva import --local -r repository_name -f /home/user/images/single_image.ome.tif
```

Check importing process status.
```bash
minerva status
```

#### Exporting

Export an image from Minerva Cloud into local disk. Image uuid has to be given with argument --id.
```bash
minerva export --id 123e4567-e89b-12d3-a456-426614174000
```

[Minerva CLI code is available from GitHub](https://github.com/labsyspharm/minerva-cli)
