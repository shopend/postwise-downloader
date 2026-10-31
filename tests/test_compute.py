import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import local_ai

class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'POSTWISE_IMPORT_TOKEN':'unit-test-token','HOST':'127.0.0.1','POSTWISE_ALLOWED_ORIGIN':'https://portal.example'})
        self.env.start()
        self.httpd=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.env.stop()
    def request(self,path='/connect',token='unit-test-token',origin='https://portal.example',method='POST'):
        req=Request('http://127.0.0.1:'+str(self.httpd.server_port)+path,data=b'{}' if method=='POST' else None,method=method,headers={'Origin':origin,'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urlopen(req) as r:return r.status,dict(r.headers),r.read()
        except HTTPError as e:return e.code,dict(e.headers),e.read()
    def test_authorization_and_origin(self):
        self.assertEqual(self.request()[0],200)
        self.assertEqual(self.request(token='wrong')[0],401)
        self.assertEqual(self.request(origin='https://attacker.example')[0],403)
    def test_private_network_preflight(self):
        status,headers,_=self.request(method='OPTIONS')
        self.assertEqual(status,204)
        self.assertEqual(headers['Access-Control-Allow-Origin'],'https://portal.example')
        self.assertEqual(headers['Access-Control-Allow-Private-Network'],'true')
    def test_local_ai_validation(self):
        with patch.object(local_ai,'models',return_value={'models':[{'name':'fixture'}]}),patch.object(local_ai,'request',return_value={}):
            with self.assertRaises(ValueError):local_ai.analyze({'model':'not-installed'})
            with self.assertRaises(ValueError):local_ai.analyze({'model':'fixture','images':['https://example.com/image.jpg']})
    def test_cloud_models_excluded(self):
        with patch.object(local_ai,'request',return_value={'models':[{'name':'local'},{'name':'remote:cloud'},{'name':'other','remote_host':'https://example.com'}]}):
            self.assertEqual(local_ai.models(),{'models':[{'name':'local'}]})

@unittest.skipUnless(importlib.util.find_spec('graphify'),'Optional Graphify dependency is not installed')
class GraphifyIntegrationTests(unittest.TestCase):
    def test_shared_topics_and_provenance(self):
        from knowledge_graph import build_graph,query_graph
        notes=[{'id':'a','title':'GPU rental','tags':['Utilization']},{'id':'b','title':'Hotel rooms','tags':[' utilization ']}]
        g=build_graph(notes)
        self.assertEqual(g['engine'],'Graphify')
        self.assertEqual(g['note_count'],2)
        self.assertTrue(any(e.get('confidence')=='INFERRED' for e in g['edges']))
        self.assertTrue(all(e.get('evidence_scope') for e in g['edges']))
        ids=[n['id'] for n in g['nodes'] if n.get('type')=='note']
        self.assertGreaterEqual(len(query_graph(g,start=ids[0],end=ids[1])['nodes']),2)
        self.assertTrue(query_graph(g,query='GPU')['nodes'])

if __name__=='__main__':unittest.main()
