import os
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
        }

    def tearDown(self):
        hub.MCP_API_TOKEN = self.original_token
        hub.MCP_ALLOWED_ORIGINS = self.original_origins

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

    def test_tools_list_exposes_forum_and_contact_tools(self):
        response = self.client.post(
            '/mcp',
            headers={**self.headers, 'MCP-Protocol-Version': '2025-11-25'},
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
        }.issubset(names))

    def test_bearer_token_and_origin_are_required(self):
        response = self.client.post(
            '/mcp',
            headers={**self.headers, 'Authorization': 'Bearer wrong-token'},
            json={'jsonrpc': '2.0', 'id': 3, 'method': 'ping'},
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            '/mcp',
            headers={**self.headers, 'Origin': 'https://untrusted.example'},
            json={'jsonrpc': '2.0', 'id': 4, 'method': 'ping'},
        )
        self.assertEqual(response.status_code, 403)

    def test_create_topic_uses_service_author_and_persists(self):
        forum_db = {
            'topics': [],
            'categories': [{'name': 'general', 'label': 'General Discussion'}],
        }
        with patch.dict(os.environ, {'MCP_FORUM_AUTHOR': 'golem-assistant'}), \
                patch.object(hub.GitHubManager, 'read_from_github', return_value=forum_db), \
                patch.object(hub.GitHubManager, 'save_to_github', return_value=True) as save:
            result = hub._mcp_tool_call('forum.create_topic', {
                'title': 'A useful forum question',
                'category': 'general',
                'content': 'This is a sufficiently detailed topic body.',
                'tags': ['help'],
            })

        self.assertTrue(result['published'])
        self.assertEqual(result['author'], 'golem-assistant')
        self.assertEqual(save.call_args.args[0], 'forum/topics.json')
        self.assertEqual(forum_db['topics'][0]['content'], 'This is a sufficiently detailed topic body.')

    def test_reply_updates_topic_and_replies(self):
        forum_db = {
            'topics': [{'slug': 'existing-topic', 'locked': False, 'reply_count': 0}],
            'categories': [],
        }
        replies_db = {'replies': []}
        with patch.dict(os.environ, {'MCP_FORUM_AUTHOR': 'golem-assistant'}), \
                patch.object(
                    hub.GitHubManager, 'read_from_github',
                    side_effect=[forum_db, replies_db],
                ), \
                patch.object(
                    hub.GitHubManager, 'save_to_github', return_value=True
                ) as save:
            result = hub._mcp_tool_call('forum.reply', {
                'slug': 'existing-topic',
                'content': 'This is a helpful reply to the existing question.',
            })

        self.assertTrue(result['published'])
        self.assertEqual(len(replies_db['replies']), 1)
        self.assertEqual(forum_db['topics'][0]['reply_count'], 1)
        self.assertEqual(save.call_count, 2)

    def test_contact_tool_reports_missing_smtp_configuration(self):
        with patch.dict(os.environ, {
            'SMTP_HOST': '',
            'SMTP_USERNAME': '',
            'SMTP_PASSWORD': '',
        }):
            response = self.client.post(
                '/mcp',
                headers={**self.headers, 'MCP-Protocol-Version': '2025-11-25'},
                json={
                    'jsonrpc': '2.0',
                    'id': 5,
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
