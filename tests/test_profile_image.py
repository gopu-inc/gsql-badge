import unittest
from io import BytesIO

from PIL import Image

from utils.profile_image import MAX_PROFILE_IMAGE_BYTES, normalize_profile_image


class ProfileImageTests(unittest.TestCase):
    def make_image(self, image_format):
        image = Image.new('RGB', (12, 8), color=(100, 160, 210))
        output = BytesIO()
        image.save(output, format=image_format)
        return output.getvalue()

    def test_normalizes_png_and_preserves_format(self):
        result = normalize_profile_image(self.make_image('PNG'))
        self.assertIsNotNone(result)
        extension, content = result
        self.assertEqual(extension, 'png')
        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (12, 8))

    def test_normalizes_jpeg(self):
        result = normalize_profile_image(self.make_image('JPEG'))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'jpg')

    def test_normalizes_webp(self):
        result = normalize_profile_image(self.make_image('WEBP'))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'webp')

    def test_rejects_non_image_and_corrupt_image(self):
        self.assertIsNone(normalize_profile_image(b'<svg></svg>'))
        self.assertIsNone(normalize_profile_image(b'\x89PNG\r\n\x1a\nnot-an-image'))

    def test_rejects_empty_and_oversized_content(self):
        self.assertIsNone(normalize_profile_image(b''))
        self.assertIsNone(normalize_profile_image(b'x' * (MAX_PROFILE_IMAGE_BYTES + 1)))


if __name__ == '__main__':
    unittest.main()
