def create_story_html(story_json, minerva_browser_url):
    return f"""

<html>
<head>
<title>Minerva Story</title>
<meta charset="utf-8"/>
<meta name="description" content="Minerva Story" />
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="text/javascript" src="{minerva_browser_url}" />
<style>
html, body, #minerva-story-div {{
  height: 100vh;
  width: 100vw;
}}
</style>
</head>
<body>
    <div id="minerva-story-div"></div>
    <script type="text/javascript">
        var storyObject = {story_json}
        var minervaStory = new MinervaStory({{
            id: "minerva-story-div",
            story: storyObject
        }});
    </script>
</body>
</html>

    """
