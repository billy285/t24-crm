"""Offline fresh-request and bounded reload propagation regression tests."""
from email.message import Message
import importlib.util
import json
from pathlib import Path
from unittest import mock
import unittest
import urllib.error
from io import BytesIO

spec=importlib.util.spec_from_file_location('resume_v2',Path(__file__).parent/'resume_private_deploy_v2.py')
resume=importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


import test_resume_private_deploy as shared_headers

class HeaderRegressionV2(shared_headers.HeaderRegression):
    def setUp(self):
        patch=mock.patch.object(shared_headers,'resume',resume)
        patch.start()
        self.addCleanup(patch.stop)

class VersionPropagation(unittest.TestCase):
    def test_request_keeps_lowercase_http_error_headers_and_forces_fresh_read(self):
        headers=Message()
        headers['cache-control']='no-store'
        error=urllib.error.HTTPError('https://fixture.invalid',401,'Unauthorized',headers,BytesIO(b'{}'))
        with mock.patch.object(resume.urllib.request,'urlopen',side_effect=error) as opener:
            status,actual,body=resume.request('https://fixture.invalid')
        self.assertIs(actual,headers)
        resume.require_private_auth(status,actual)
        request=opener.call_args.args[0]
        observed={key.lower():value for key,value in request.header_items()}
        self.assertEqual(observed['connection'],'close')
        self.assertEqual(observed['cache-control'],'no-cache')
        self.assertEqual(observed['pragma'],'no-cache')

    def test_old_worker_response_then_exact_new_version_succeeds(self):
        old=(200,{'cache-control':'no-store'},json.dumps({'version':'aaaaaaaaaaaa'}).encode())
        new=(200,{'cache-control':'no-store'},json.dumps({'version':'da84f72cdf00'}).encode())
        with mock.patch.object(resume,'request',side_effect=[old,new]), mock.patch.object(resume.time,'sleep'):
            proof=resume.wait_public_version('da84f72cdf00')
        self.assertEqual(proof['stage'],'PUBLIC_VERSION_AND_CACHE_VERIFIED')
        self.assertEqual(len(proof['attempts']),2)
        self.assertEqual(proof['attempts'][-1]['body_version'],'da84f72cdf00')

    def test_wait_expires_and_proof_never_echoes_sensitive_body(self):
        now=[0]
        proofs=[]
        def sleep(seconds): now[0]+=seconds
        unexpected=(200,{'cache-control':'no-store'},b'{"secret":"fixture-sensitive","version":"not-a-release"}')
        with mock.patch.object(resume,'request',return_value=unexpected), \
             mock.patch.object(resume.time,'monotonic',side_effect=lambda:now[0]), \
             mock.patch.object(resume.time,'sleep',side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError,'PUBLIC_VERSION_OR_CACHE_DRIFT'):
                resume.wait_public_version('da84f72cdf00',proofs.append,timeout=1)
        self.assertEqual(now[0],1)
        self.assertEqual(len(proofs),1)
        self.assertNotIn('fixture-sensitive',json.dumps(proofs))
        self.assertTrue(all(set(row)=={'status','body_version','no_store'} for row in proofs[0]['attempts']))

    def test_expected_version_without_no_store_never_passes(self):
        now=[0]
        def sleep(seconds): now[0]+=seconds
        response=(200,{'cache-control':'public, max-age=60'},b'{"version":"da84f72cdf00"}')
        with mock.patch.object(resume,'request',return_value=response), \
             mock.patch.object(resume.time,'monotonic',side_effect=lambda:now[0]), \
             mock.patch.object(resume.time,'sleep',side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError,'PUBLIC_VERSION_OR_CACHE_DRIFT'):
                resume.wait_public_version('da84f72cdf00',timeout=1)


if __name__=='__main__':
    unittest.main()
