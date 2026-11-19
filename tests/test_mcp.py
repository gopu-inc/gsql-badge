import base64
import hashlib
import io
import os
import tarfile
import unittest
from unittest.mock import patch

import app as hub


class MCPProtocolTests(unittest.TestCase):
    def setUp(self):
        self.original_token = hub.MCP_API_TOKEN
        self.original_origins = hub.MCP_ALLOWED_ORIGINS
        hub.MCP_API_TOKEN = 'test-token-' + ('x' * 48)
        hub.MCP_ALLOWED_ORIGINS = {'https://client.example'}
        self.client = hub.app.test_client()
        self.headers = {
            'Authorization': f'Bearer {hub.MCP_API_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': '2025-11-25',
        }

    def tearDown(self):
        hub.MCP_API_TOKEN = self.original_token
        hub.MCP_ALLOWED_ORIGINS = self.original_origins

    @property
    def admin(self):
        return hub._mcp_principal_for_token(hub.MCP_API_TOKEN)

    def test_initialize_negotiates_protocol_version(self):
        response = self.client.post('/mcp', headers=self.headers, json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-11-25',
                'capabilities': {},
                'clientInfo': {'name': 'test-client', 'version': '1'},
            },
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['result']['protocolVersion'], '2025-11-25')
        self.assertIn('tools', response.json['result']['capabilities'])

    def test_tools_list_includes_bot_management_and_package_tools(self):
        response = self.client.post(
            '/mcp',
            headers=self.headers,
            json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        )

        self.assertEqual(response.status_code, 200)
        names = {tool['name'] for tool in response.json['result']['tools']}
        self.assertTrue({
            'forum.search_topics',
            'forum.get_topic',
            'forum.create_topic',
            'forum.reply',
            'contact.send_message',
            'bots.register',
            'bots.list',
            'bots.revoke',
            'golem.scaffold_package',
            'golem.publish_package',
        }.issubset(names))

    def test_docs_resources_are_listed_and_readable(self):
        listed = self.client.post('/mcp', headers=self.headers, json={
            'jsonrpc': '2.0', 'id': 3, 'method': 'resources/list',
        })
        self.assertEqual(listed.status_code, 200)
        uris = {resource['uri'] for resource in listed.json['result']['resources']}
        self.assertEqual(uris, {'zarch://docs/goscript', 'zarch://docs/golem'})

        read = self.client.post('/mcp', headers=self.headers, json={
            'jsonrpc': '2.0',
            'id': 4,
            'method': 'resources/read',
            'params': {'uri': 'zarch://docs/golem'},
        })
        self.assertEqual(read.status_code, 200)
        self.assertIn('golem build', read.json['result']['contents'][0]['text'])

    def test_bearer_token_and_origin_are_required(self):
        with patch.object(hub.GitHubManager, 'read_from_github', return_value={'bots': []}):
            response = self.client.post(
                '/mcp',
                headers={**self.headers, 'Authorization': 'Bearer wrong-token'},
                json={'jsonrpc': '2.0', 'id': 5, 'method': 'ping'},
            )
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            '/mcp',
            headers={**self.headers, 'Origin': 'https://untrusted.example'},
            json={'jsonrpc': '2.0', 'id': 6, 'method': 'ping'},
        )
        self.assertEqual(response.status_code, 403)

    def test_create_topic_uses_authenticated_bot_identity(self):
        forum_db = {
            'topics': [],
            'categories': [{'name': 'general', 'label': 'General Discussion'}],
        }
        bot = {
            'type': 'bot',
            'username': 'bot_0123456789abcdef',
            'label': 'Forum Writer',
            'display_name': '~Forum Writer [bot]',
            'bot_id': 'idbot_0123456789abcdef01234567',
            'scopes': ['forum:write'],
        }
        with patch.object(hub.GitHubManager, 'read_from_github', return_value=forum_db), \
                patch.object(hub.GitHubManager, 'save_to_github', return_value=True) as save:
            result = hub._mcp_tool_call('forum.create_topic', {
                'title': 'A useful forum question',
                'category': 'general',
                'content': 'This is a sufficiently detailed topic body.',
                'tags': ['help'],
            }, bot)

        self.assertTrue(result['published'])
        self.assertEqual(result['author'], bot['username'])
        self.assertEqual(result['author_display'], bot['display_name'])
        self.assertEqual(forum_db['topics'][0]['bot_id'], bot['bot_id'])
        self.assertTrue(forum_db['topics'][0]['author_is_bot'])
        self.assertEqual(save.call_args.args[0], 'forum/topics.json')

    def test_reply_updates_topic_with_bot_identity(self):
        forum_db = {
            'topics': [{'slug': 'existing-topic', 'locked': False, 'reply_count': 0}],
            'categories': [],
        }
        replies_db = {'replies': []}
        bot = {
            'type': 'bot',
            'username': 'bot_0123456789abcdef',
            'label': 'Forum Writer',
            'display_name': '~Forum Writer [bot]',
            'bot_id': 'idbot_0123456789abcdef01234567',
            'scopes': ['forum:write'],
        }
        with patch.object(
            hub.GitHubManager, 'read_from_github',
            side_effect=[forum_db, replies_db],
        ), patch.object(
            hub.GitHubManager, 'save_to_github', return_value=True,
        ):
            result = hub._mcp_tool_call('forum.reply', {
                'slug': 'existing-topic',
                'content': 'This is a helpful reply to the existing question.',
            }, bot)

        self.assertTrue(result['published'])
        self.assertEqual(result['author_display'], bot['display_name'])
        self.assertEqual(len(replies_db['replies']), 1)
        self.assertEqual(replies_db['replies'][0]['bot_id'], bot['bot_id'])
        self.assertEqual(forum_db['topics'][0]['last_reply_by'], bot['username'])
        self.assertTrue(forum_db['topics'][0]['last_reply_is_bot'])
        self.assertEqual(forum_db['topics'][0]['last_reply_bot_id'], bot['bot_id'])

    def test_bot_token_is_scoped_and_revocation_disables_it(self):
        token = 'bot_sktok_test-only-secret'
        bot_record = {
            'bot_id': 'idbot_0123456789abcdef01234567',
            'username': 'bot_0123456789abcdef',
            'label': 'Docs Reader',
            'token_hash': hashlib.sha256(token.encode()).hexdigest(),
            'scopes': ['docs:read'],
            'enabled': True,
        }
        bots_db = {'bots': [bot_record]}
        with patch.object(hub.GitHubManager, 'read_from_github', return_value=bots_db), \
                patch.object(hub.GitHubManager, 'save_to_github', return_value=True):
            principal = hub._mcp_principal_for_token(token)
            listed = self.client.post(
                '/mcp',
                headers={**self.headers, 'Authorization': f'Bearer {token}'},
                json={'jsonrpc': '2.0', 'id': 7, 'method': 'tools/list'},
            )
            hub._mcp_revoke_bot({'bot_id': bot_record['bot_id']}, self.admin)
            revoked_principal = hub._mcp_principal_for_token(token)

        self.assertEqual(principal['type'], 'bot')
        self.assertEqual(principal['scopes'], ['docs:read'])
        self.assertEqual(
            {tool['name'] for tool in listed.json['result']['tools']},
            set(),
        )
        self.assertIsNone(revoked_principal)
        self.assertFalse(bot_record['enabled'])

    def test_bot_registration_stores_only_token_hash(self):
        bots_db = {'bots': []}
        with patch.object(hub.GitHubManager, 'read_from_github', return_value=bots_db), \
                patch.object(hub.GitHubManager, 'save_to_github', return_value=True):
            result = hub._mcp_tool_call('bots.register', {
                'label': 'Package Builder',
                'scopes': ['docs:read', 'packages:create', 'packages:publish'],
            }, self.admin)

        self.assertTrue(result['token'].startswith('bot_sktok_'))
        self.assertRegex(result['bot_id'], r'^idbot_[a-f0-9]{24}$')
        self.assertRegex(result['username'], r'^bot_[a-f0-9]{16}$')
        self.assertNotIn('token', bots_db['bots'][0])
        self.assertEqual(
            bots_db['bots'][0]['token_hash'],
            hashlib.sha256(result['token'].encode()).hexdigest(),
        )

    def test_scaffold_uses_bot_username_and_returns_golem_files(self):
        bot = {
            'type': 'bot',
            'username': 'bot_0123456789abcdef',
            'label': 'Package Builder',
            'display_name': '~Package Builder [bot]',
            'bot_id': 'idbot_0123456789abcdef01234567',
            'scopes': ['packages:create'],
        }
        result = hub._mcp_tool_call('golem.scaffold_package', {
            'name': 'sample-lib',
            'version': '1.2.3',
            'description': 'A sample library.',
        }, bot)

        self.assertEqual(result['author'], bot['username'])
        self.assertEqual(set(result['files']), {
            'Manifest.toml', '__self__.gjs', 'main.gjs', 'README.md',
        })
        self.assertIn('name = "sample-lib"', result['files']['Manifest.toml'])

    @staticmethod
    def _package_archive(name='sample-lib', version='1.0.0', extra_path=None):
        manifest = (
            '[metadata]\n'
            f'name = "{name}"\n'
            f'version = "{version}"\n'
            'release = "r0"\n'
            'arch = "x86_64"\n'
            'scope = "public"\n'
        ).encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for path, content in (
                ('Manifest.toml', manifest),
                ('__self__.gjs', b'pub fn sample() { ret 1 }\n'),
            ):
                info = tarfile.TarInfo(path)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            if extra_path:
                info = tarfile.TarInfo(extra_path)
                info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
        return buffer.getvalue()

    def test_publish_validates_archive_and_records_bot_owner(self):
        archive = self._package_archive()
        bot = {
            'type': 'bot',
            'username': 'bot_0123456789abcdef',
            'label': 'Package Builder',
            'display_name': '~Package Builder [bot]',
            'bot_id': 'idbot_0123456789abcdef01234567',
            'scopes': ['packages:publish'],
        }
        registry = {'packages': []}
        with patch.object(
            hub.GitHubManager, 'read_from_github', return_value=registry,
        ), patch.object(
            hub.GitHubManager, 'save_to_github', return_value=True,
        ) as save:
            result = hub._mcp_tool_call('golem.publish_package', {
                'name': 'sample-lib',
                'version': '1.0.0',
                'archive_base64': base64.b64encode(archive).decode(),
            }, bot)

        self.assertTrue(result['published'])
        self.assertEqual(result['package']['author'], bot['username'])
        self.assertEqual(result['package']['bot_id'], bot['bot_id'])
        self.assertEqual(len(registry['packages']), 1)
        self.assertEqual(save.call_args_list[0].args[0],
                         'packages/public/sample-lib/sample-lib-1.0.0-r0-x86_64.tar.bool')

    def test_publish_rejects_unsafe_archive_paths(self):
        archive = self._package_archive(extra_path='../outside.txt')
        bot = {
            'type': 'bot',
            'username': 'bot_0123456789abcdef',
            'label': 'Package Builder',
            'display_name': '~Package Builder [bot]',
            'bot_id': 'idbot_0123456789abcdef01234567',
            'scopes': ['packages:publish'],
        }
        with self.assertRaises(hub.MCPToolError):
            hub._mcp_tool_call('golem.publish_package', {
                'name': 'sample-lib',
                'version': '1.0.0',
                'archive_base64': base64.b64encode(archive).decode(),
            }, bot)

    def test_contact_tool_reports_missing_smtp_configuration(self):
        with patch.dict(os.environ, {
            'SMTP_HOST': '',
            'SMTP_USERNAME': '',
            'SMTP_PASSWORD': '',
        }):
            response = self.client.post(
                '/mcp',
                headers=self.headers,
                json={
                    'jsonrpc': '2.0',
                    'id': 8,
                    'method': 'tools/call',
                    'params': {
                        'name': 'contact.send_message',
                        'arguments': {
                            'name': 'Ada',
                            'email': 'ada@example.com',
                            'subject': 'Question',
                            'message': 'Please help me with this package.',
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['result']['isError'])
        self.assertIn('not configured', response.json['result']['content'][0]['text'])

    def test_legacy_forum_category_is_displayed_as_golem(self):
        forum_db = {
            'categories': [{'name': 'gpm', 'label': 'GPM Package Manager'}],
            'topics': [{'category': 'gpm'}],
        }

        hub._normalize_forum_categories(forum_db)

        self.assertEqual(forum_db['categories'][0]['name'], 'golem')
        self.assertEqual(forum_db['categories'][0]['label'], 'Golem Package Manager')
        self.assertEqual(forum_db['topics'][0]['category'], 'golem')


if __name__ == '__main__':
    unittest.main()
