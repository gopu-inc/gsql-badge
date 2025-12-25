import base64

def image_to_base64(file):
    return base64.b64encode(file.read()).decode("utf-8")
