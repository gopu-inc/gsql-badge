import hashlib
import re
import unittest
from unittest.mock import patch

import app as hub


class BotPanelTests(unittest.TestCase):
    def setUp(self):
        self.client = hub.app.test_client()
        self.headers = {'Authorization': 'Bearer test-user-token'}
        self.user = {'username': 'alice'}
        self.csrf_pattern = re.compile(r'name="csrf_token" value="([^"]+)"')

    def _csrf(self, response):
        match = self.csrf_pattern.search(response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def test_panel_only_lists_bots_owned_by_signed_in_user(self):
        bots_db = {'bots': [
            {
                'bot_id': 'idbot_aaaaaaaaaaaaaaaaaaaaaaaa',
                'username': 'bot_aaaaaaaaaaaaaaaa',
                'label': 'Alice bot',
                'owner': 'alice',
                'token_hash': 'a' * 64,
                'scopes': ['docs:read'],
                'enabled': True,
            },
            {
                'bot_id': 'idbot_bbbbbbbbbbbbbbbbbbbbbbbb',
                'username': 'bot_bbbbbbbbbbbbbbbb',
                'label': 'Bob bot',
                'owner': 'bob',
                'token_hash': 'b' * 64,
                'scopes': ['forum:write'],
                'enabled': True,
            },
        ]}
        with patch.object(
            hub.SecurityUtils, 'validate_token', return_value=self.user,
        ), patch.object(
            hub.GitHubManager, 'read_from_github', return_value=bots_db,
        ):
            response = self.client.get('/settings/bots', headers=self.headers)

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Alice bot', page)
        self.assertNotIn('Bob bot', page)
        self.assertNotIn('a' * 64, page)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_create_shows_new_secret_once_and_stores_only_hash(self):
        bots_db = {'bots': []}
        with patch.object(hub, 'MCP_API_TOKEN', 'server-token-' + ('x' * 40)), \
                patch.object(
                    hub.SecurityUtils, 'validate_token', return_value=self.user,
                ), patch.object(
                    hub.GitHubManager, 'read_from_github', return_value=bots_db,
                ), patch.object(
                    hub.GitHubManager, 'save_to_github', return_value=True,
                ):
            initial = self.client.get('/settings/bots', headers=self.headers)
            csrf_token = self._csrf(initial)
            response = self.client.post(
                '/settings/bots',
                headers=self.headers,
                data={
                    'csrf_token': csrf_token,
                    'action': 'create',
                    'label': 'Package builder',
                    'scopes': ['docs:read', 'packages:publish'],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(bots_db['bots']), 1)
        bot = bots_db['bots'][0]
        page = response.get_data(as_text=True)
        self.assertIn('bot_sktok_', page)
        self.assertEqual(bot['owner'], 'alice')
        self.assertNotIn('token', bot)
        self.assertEqual(
            bot['token_hash'],
            hashlib.sha256(re.search(r'bot_sktok_[A-Za-z0-9_-]+', page).group(0).encode()).hexdigest(),
        )
        self.assertEqual(bot['scopes'], ['docs:read', 'packages:publish'])

    def test_revoke_rejects_another_users_bot(self):
        bot = {
            'bot_id': 'idbot_bbbbbbbbbbbbbbbbbbbbbbbb',
            'username': 'bot_bbbbbbbbbbbbbbbb',
            'label': 'Bob bot',
            'owner': 'bob',
            'token_hash': 'b' * 64,
            'scopes': ['forum:write'],
            'enabled': True,
        }
        bots_db = {'bots': [bot]}
        with patch.object(
            hub.SecurityUtils, 'validate_token', return_value=self.user,
        ), patch.object(
            hub.GitHubManager, 'read_from_github', return_value=bots_db,
        ), patch.object(
            hub.GitHubManager, 'save_to_github', return_value=True,
        ) as save:
            initial = self.client.get('/settings/bots', headers=self.headers)
            response = self.client.post(
                '/settings/bots',
                headers=self.headers,
                data={
                    'csrf_token': self._csrf(initial),
                    'action': 'revoke',
                    'bot_id': bot['bot_id'],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(bot['enabled'])
        save.assert_not_called()
        self.assertIn('Bot key not found for this account.', response.get_data(as_text=True))

    def test_post_without_csrf_token_is_rejected(self):
        with patch.object(
            hub.SecurityUtils, 'validate_token', return_value=self.user,
        ):
            response = self.client.post(
                '/settings/bots',
                headers=self.headers,
                data={'action': 'create', 'label': 'Unauthorized bot', 'scopes': 'docs:read'},
            )

        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
