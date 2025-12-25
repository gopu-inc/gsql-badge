import re

def clean_slug(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9_-]", "", text)
    return text
