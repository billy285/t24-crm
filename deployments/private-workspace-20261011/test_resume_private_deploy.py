"""Focused offline header tests: no production paths, Docker, or network."""
from email.message import Message
from io import BytesIO
import importlib.util
from pathlib import Path
from unittest import mock
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('resume',Path(__file__).parent/'resume_private_deploy.py')
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


class HeaderRegression(unittest.TestCase):
    def test_http_error_preserves_lowercase_http_message(self):
        headers = Message()
        headers['cache-control'] = 'no-store'
        error = urllib.error.HTTPError('https://fixture.invalid',401,'Unauthorized',headers,BytesIO(b'{}'))
        with mock.patch.object(resume.urllib.request,'urlopen',side_effect=error):
            status,actual,body = resume.request('https://fixture.invalid')
        self.assertIs(actual,headers)
        self.assertEqual(actual.get('Cache-Control'),'no-store')
        resume.require_private_auth(status,actual)

    def test_success_preserves_http_message_for_all_security_headers(self):
        headers = Message()
        expected = {'X-Frame-Options':'SAMEORIGIN','Content-Security-Policy':"default-src 'self'",
                    'Strict-Transport-Security':'max-age=31536000; includeSubDomains',
                    'Referrer-Policy':'strict-origin-when-cross-origin',
                    'Permissions-Policy':'camera=(), geolocation=(), microphone=(self)',
                    'X-Content-Type-Options':'nosniff'}
        for key,value in expected.items():
            headers[key.lower()] = value
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = headers
        response.read.return_value = b'{}'
        with mock.patch.object(resume.urllib.request,'urlopen',return_value=response):
            status,actual,body = resume.request('https://fixture.invalid')
        self.assertIs(actual,headers)
        self.assertTrue(all(resume.header(actual,key)==value for key,value in expected.items()))

    def test_accepts_actual_401_with_no_store_token_case_insensitively(self):
        resume.require_private_auth(401,{'cache-control':'private, No-Store, max-age=0'})

    def test_rejects_200_even_with_no_store(self):
        with self.assertRaisesRegex(RuntimeError,'401_OR_NO_STORE'):
            resume.require_private_auth(200,{'cache-control':'no-store'})

    def test_rejects_substring_that_is_not_no_store_token(self):
        for value in ('no-storex','x-no-store','no-store=1','max-age=0'):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError,'401_OR_NO_STORE'):
                resume.require_private_auth(401,{'Cache-Control':value})

    def test_rejects_conflicting_case_duplicate_headers(self):
        with self.assertRaisesRegex(RuntimeError,'AMBIGUOUS'):
            resume.require_private_auth(401,{'Cache-Control':'no-store','cache-control':'public'})

    def test_rejects_missing_cache_header(self):
        with self.assertRaisesRegex(RuntimeError,'401_OR_NO_STORE'):
            resume.require_private_auth(401,{})


if __name__ == '__main__':
    unittest.main()
