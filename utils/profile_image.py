from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PROFILE_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PROFILE_IMAGE_PIXELS = 20_000_000
_EXTENSIONS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


def normalize_profile_image(content):
    if not content or len(content) > MAX_PROFILE_IMAGE_BYTES:
        return None

    try:
        with Image.open(BytesIO(content)) as source:
            image_format = source.format
            if image_format not in _EXTENSIONS:
                return None
            if source.width * source.height > MAX_PROFILE_IMAGE_PIXELS:
                return None

            image = ImageOps.exif_transpose(source)
            if image_format == 'JPEG':
                image = image.convert('RGB')
            elif image.mode not in ('RGB', 'RGBA'):
                has_alpha = 'A' in image.getbands() or 'transparency' in image.info
                image = image.convert('RGBA' if has_alpha else 'RGB')

            output = BytesIO()
            options = {'optimize': True}
            if image_format in ('JPEG', 'WEBP'):
                options['quality'] = 88
            image.save(output, format=image_format, **options)
            normalized = output.getvalue()
            if not normalized or len(normalized) > MAX_PROFILE_IMAGE_BYTES:
                return None

            return _EXTENSIONS[image_format], normalized
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
