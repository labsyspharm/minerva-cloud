from datetime import datetime

def create_story_html(exhibit_json, minerva_browser_url):
    last_modified = datetime.now().isoformat()
    return f"""<html>
<head>
<title>Minerva Story</title>
<meta charset="utf-8"/>
<meta name="description" content="Minerva Story" />
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="last-modified" content="{last_modified}">
<link rel="icon" href="favicon.png">
<script defer src="https://use.fontawesome.com/releases/v5.2.0/js/all.js" integrity="sha384-4oV5EgaV02iISL2ban6c/RmotsABqE4yZxZLcYMAdG7FAPsyHYAPpywE9PJo+Khy" crossorigin="anonymous"></script>
<script type="text/javascript" src="{minerva_browser_url}"></script>
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
        var exhibit = {exhibit_json}
        MinervaStory.default.build_page({{
          exhibit: exhibit,
          id: "minerva-story-div",
          embedded: true,
          speech_bucket: ''
        }});
    </script>
</body>
</html>

    """
