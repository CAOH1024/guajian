"""Validate freshly extracted Windows packages without account authentication."""
import hashlib,json,pathlib,subprocess,tempfile,time,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip(); dist=ROOT/'dist'
def run(args): subprocess.run([str(arg) for arg in args],check=True,timeout=60)
with tempfile.TemporaryDirectory(prefix='shuangling-verify-') as temporary:
    work=pathlib.Path(temporary); installed=work/'中文 安装'
    run([dist/('ShuanglingQuota-'+version+'-Setup.exe'),'--extract',installed])
    manifest=json.loads((installed/'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        assert hashlib.sha256((installed/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    run([installed/'ShuanglingQuota.exe','--check'])
    try:
        run([installed/'ShuanglingQuota.exe','--preview',ROOT/'docs/example-quota.json','--render-preview',work/'preview.png'])
    except subprocess.CalledProcessError:
        log=installed/'runtime/state/startup-error.log'
        if log.exists(): print(log.read_text(encoding='utf-8'),flush=True)
        diagnostic=subprocess.run([str(installed/'runtime/python.exe'),str(installed/'runtime/launcher.py'),'--preview',str(ROOT/'docs/example-quota.json'),'--render-preview',str(work/'preview.png')],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
        print('Portable Python diagnostic:',diagnostic.returncode,diagnostic.stdout,diagnostic.stderr,flush=True)
        raise
    assert (work/'preview.png').stat().st_size>1000
    assert not (installed/'runtime/state').exists()
    # Exercise the installed receiver without installing or trusting global hooks.
    receiver=installed/'runtime/codex_hooks.py'
    def hook(event,**fields):
        payload={'hook_event_name':event,'session_id':'package-self-test','turn_id':'test-turn',**fields}
        result=subprocess.run([str(installed/'runtime/python.exe'),str(receiver),'--receive'],
                              input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=10)
        assert result.returncode==0 and not result.stdout and not result.stderr,result
    hook('PreToolUse',tool_name='request_user_input',tool_input={'questions':[{'question':'Package test question'}]})
    notices=installed/'runtime/state/notifications'
    assert any(json.loads(path.read_text(encoding='utf-8'))['kind']=='question' for path in notices.glob('*.json'))
    hook('Stop')
    values=[json.loads(path.read_text(encoding='utf-8')) for path in notices.glob('*.json')]
    assert len(values)==1 and values[0]['kind']=='completed'
for path in dist.glob('*.zip'):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            parts=pathlib.PurePosixPath(name).parts
            assert not any(part in ('state','__pycache__','.git') for part in parts),name
            assert parts[-1] not in ('auth.json','last-quota.json','settings.json'),name
report={'ok':True,'installer_extraction_unicode_path':True,'all_manifest_hashes_match':True,
        'exe_preview_render':True,'packaged_hook_receiver':True,'private_state_excluded':True,'live_account_read_tested_in_ci':False,
        'signature':'unsigned','verified_at_unix':time.time()}
(dist/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
with (dist/'SHA256SUMS.txt').open('a',encoding='ascii') as stream:
    stream.write(hashlib.sha256((dist/'verification.json').read_bytes()).hexdigest()+'  verification.json\n')
print(json.dumps(report,indent=2))
