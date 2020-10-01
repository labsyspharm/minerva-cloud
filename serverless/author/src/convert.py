def convert_to_exhibit(story, image, bucket):
    exhibit = {
        "Name": story["sample_info"].get("name", "unnamed"),
        "Header": story["sample_info"].get("text", ""),
        "Images": _build_images(story, image, bucket),
        "Layout": {
            "Grid": [["i0"]]
        },
        "Groups": _build_groups(story),
        "Stories": _build_stories(story),
        "Rotation": 0
    }
    return exhibit


def _build_images(story, image, bucket):
    base_url = f"https://s3.amazonaws.com/{bucket}/{story['uuid']}/minerva-story/images"
    return [
         {
             "Name": "i0",
             "Description": story["sample_info"].get("name", "unnamed"),
             "Provider": "default",
             "Path": base_url,
             "Width": image["width"],
             "Height": image["height"],
             "MaxLevel": image["pyramid_levels"]
         }
    ]

def _build_groups(story):
    groups = []
    for group in story["groups"]:
        sample_name = story["sample_info"]["name"]
        channels = group["channels"]

        group_label = group["label"]
        channel_labels = [f"{channel['id']}__{channel['label']}" for channel in channels]
        channel_labels = "--".join(channel_labels)
        group_key = f"{group_label}_{channel_labels}"
        group_key = group_key.replace(' ', '-')

        path = f"{sample_name}/{group_key}"
        groups.append({
            "Path": path,
            "Name": group.get("label", ""),
            "Colors": _build_colors(group),
            "Channels": _build_channels(group)
        })
    return groups

def _build_colors(group):
    return [channel["color"] for channel in group["channels"]]

def _build_channels(group):
    return [channel["label"] for channel in group["channels"]]

def _build_stories(story):
    stories = [{
        "Name": story["sample_info"].get("name", ""),
        "Waypoints": []
    }]
    for waypoint in story["waypoints"]:
        stories[0]["Waypoints"].append({
            "Name": waypoint["name"],
            "Description": waypoint["text"],
            "Arrows": _build_arrows(waypoint),
            "Overlays": _build_overlays(waypoint),
            "Group": waypoint["group"],
            "Zoom": waypoint["zoom"],
            "Pan": waypoint["pan"]
        })
    return stories

def _build_arrows(waypoint):
    arrows = []
    for arrow in waypoint["arrows"]:
        arrows.append({
            "Text": arrow["text"],
            "HideArrow": arrow["hide"],
            "Point": arrow["position"],
            "Angle": waypoint.get("angle", 0)
        })
    return arrows

def _build_overlays(waypoint):
    overlays = []
    for overlay in waypoint["overlays"]:
        overlays.append({
            "x": overlay[0],
            "y": overlay[1],
            "width": overlay[2],
            "height": overlay[3]
        })
    return overlays