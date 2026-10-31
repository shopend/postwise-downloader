import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import server

class SecurityTests(unittest.TestCase):
    def test_reject_non_instagram_and_credentials(self):
        for url in ['https://127.0.0.1/p/abc/','https://instagram.com.evil.test/p/abc/',
                    'https://user:pw@instagram.com/p/abc/','https://instagram.com:8443/p/abc/']:
            with self.assertRaises(ValueError): server.shortcode(url)
        self.assertEqual(server.shortcode('https://www.instagram.com/reel/abc/?igsh=x'),'abc')
    def test_reject_private_dns(self):
        with patch.object(server.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): server.media_host('https://cdninstagram.com/a')
        with self.assertRaises(ValueError): server.media_host('https://cdninstagram.com.evil.test/a')
    def test_session_permissions_and_json(self):
        loader=MagicMock()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json'
            path.write_text(json.dumps({'username':'tester','cookies':{'sessionid':'fixture'}}))
            path.chmod(0o644)
            with self.assertRaises(ValueError): server.load_session(loader,'tester',path)
            path.chmod(0o600)
            server.load_session(loader,'tester',path)
            loader.context.load_session.assert_called_once_with('tester',{'sessionid':'fixture'})
            path.write_bytes(b'not JSON or pickle')
            with self.assertRaises(ValueError): server.load_session(loader,'tester',path)
    def test_import_timeout_kills_group(self):
        process=MagicMock(pid=999999)
        process.communicate.side_effect=server.subprocess.TimeoutExpired('worker',210)
        with patch.object(server.subprocess,'Popen',return_value=process),patch.object(server.os,'killpg') as kill:
            with self.assertRaisesRegex(ValueError,'210 seconds'):server.isolated_import('https://instagram.com/p/abc/')
            kill.assert_called_once_with(999999,server.signal.SIGKILL)
            process.wait.assert_called_once()
    def test_local_host_rebinding_blocked(self):
        handler=object.__new__(server.Handler)
        handler.server=MagicMock(server_port=8765)
        handler.headers={'Host':'attacker.example:8765'}
        with patch.dict(os.environ,{'HOST':'127.0.0.1'}):
            self.assertFalse(handler.allowed_origin())
            handler.headers={'Host':'127.0.0.1:8765'}
            self.assertTrue(handler.allowed_origin())
    def test_reject_oversized_stream(self):
        import requests
        response=MagicMock(is_redirect=False,headers={})
        response.__enter__.return_value=response
        response.iter_content.return_value=[b'abcd',b'efgh']
        client=MagicMock();client.get.return_value=response
        client.__enter__.return_value=client
        with tempfile.TemporaryDirectory() as folder,patch.object(requests,'Session',return_value=client),patch.object(server.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            with self.assertRaisesRegex(ValueError,'size or time'):
                server.download(None,'https://cdninstagram.com/a',Path(folder)/'media',5)
    def test_block_redirect_before_second_request(self):
        import requests
        response=MagicMock(is_redirect=True,headers={'Location':'http://127.0.0.1/secret'})
        response.__enter__.return_value=response
        client=MagicMock();client.get.return_value=response
        client.__enter__.return_value=client
        with patch.object(requests,'Session',return_value=client),patch.object(server.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            with self.assertRaises(ValueError):server.download(None,'https://cdninstagram.com/a','unused',100)
            self.assertEqual(client.get.call_count,1)
            self.assertFalse(client.get.call_args.kwargs['allow_redirects'])

if __name__=='__main__': unittest.main()
