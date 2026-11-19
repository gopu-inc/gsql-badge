import unittest

import app as hub


class InstallerRedirectTests(unittest.TestCase):
    def setUp(self):
        self.client = hub.app.test_client()

    def test_installer_routes_redirect_to_official_raw_scripts(self):
        scripts = ('install.sh', 'install.ps1', 'update.sh', 'update.ps1')
        for script in scripts:
            with self.subTest(script=script):
                response = self.client.get('/' + script, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    response.headers['Location'],
                    'https://raw.githubusercontent.com/gopu-inc/goscript/refs/heads/main/'
                    + script,
                )


if __name__ == '__main__':
    unittest.main()
