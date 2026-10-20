import json, pathlib, sys, tempfile, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"src"))
from quota_source import CodexClient, QuotaError, normalize_quota

class QuotaTests(unittest.TestCase):
    def test_remaining_and_window_order(self):
        data=normalize_quota({'rateLimits':{'primary':{'usedPercent':58,'windowDurationMins':10080},'secondary':{'usedPercent':67,'windowDurationMins':300}}})
        self.assertEqual([(w['label'],w['remaining_percent']) for w in data['windows']],[('5小时',33),('本周',42)])
        self.assertIsNone(data['windows'][0]['resets_at'])
        self.assertIsNone(data['credits_balance'])
    def test_prefer_multibucket(self):
        data=normalize_quota({'rateLimits':{'primary':{'usedPercent':99}},'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':4,'windowDurationMins':300}}}})
        self.assertEqual(data['windows'][0]['remaining_percent'],96)
    def test_missing_is_not_zero(self):
        for payload in ({},{'rateLimits':{'primary':None}},{'rateLimits':{'primary':{'usedPercent':None}}},{'rateLimits':{'primary':{'usedPercent':float('nan')}}}):
            with self.subTest(payload=payload),self.assertRaises(QuotaError): normalize_quota(payload)
    def test_clamp_and_preserve_expired_reset(self):
        data=normalize_quota({'rateLimits':{'primary':{'usedPercent':110,'resetsAt':1},'secondary':{'usedPercent':-5}}})
        self.assertEqual([w['remaining_percent'] for w in data['windows']],[0,100])
        self.assertEqual(data['windows'][0]['resets_at'],1)
    def test_real_subprocess_rpc_and_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); fake=root/'server.py'; log=root/'methods.jsonl'
            fake.write_text('''import sys,json
log=open(sys.argv[1],'a',encoding='utf-8')
for line in sys.stdin:
    m=json.loads(line); log.write(json.dumps(m)+'\\n'); log.flush()
    if m['method']=='initialize':
        print(json.dumps({'method':'noise','params':{}}),flush=True)
        print(json.dumps({'id':m['id'],'result':{'ok':True}}),flush=True)
    if m['method']=='account/rateLimits/read':
        print(json.dumps({'id':m['id'],'result':{'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300}}}}),flush=True)
''',encoding='utf-8')
            client=CodexClient([sys.executable,str(fake),str(log)])
            try:
                self.assertEqual(client.read()['windows'][0]['remaining_percent'],80)
                with self.assertRaises(QuotaError): client.request('no-reply',timeout=0.05)
                process=client.process
            finally: client.close()
            self.assertIsNotNone(process.poll())
            messages=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([m['method'] for m in messages],['initialize','initialized','account/rateLimits/read','no-reply'])
            self.assertEqual(messages[0]['params']['clientInfo']['name'],'shuangling_quota_widget')

if __name__=='__main__': unittest.main(verbosity=2)
