import unittest
from datetime import datetime, timedelta, timezone

import app as hub


class TemplateFilterTests(unittest.TestCase):
    def test_timeago_formats_past_iso_dates(self):
        value = datetime.now(timezone.utc) - timedelta(days=2)
        self.assertEqual(hub.timeago_filter(value.isoformat()), '2 days ago')

    def test_datetimeformat_accepts_iso_dates(self):
        value = '2025-03-04T05:06:07+00:00'
        self.assertEqual(
            hub.datetimeformat_filter(value, '%Y/%m/%d'),
            '2025/03/04',
        )

    def test_invalid_template_dates_render_empty(self):
        self.assertEqual(hub.timeago_filter('not-a-date'), '')
        self.assertEqual(hub.datetimeformat_filter(None), '')


if __name__ == '__main__':
    unittest.main()
