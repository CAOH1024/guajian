"""Build Windows x64 releases with plain Python + separate Qt DLLs + C# EXEs.

No credentials/state are read or copied. --runtime-template accepts an existing
compatible plain-Python runtime for an offline rebuild; normal builds collect
dependencies from the active Python environment.
"""
from __future__ import annotations
import argparse,hashlib,importlib.metadata,json,os,pathlib,shutil,subprocess,sys,tempfile,zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
SKIP={'__pycache__','.git','.venv','venv','dist','build','state'}

def command(args):
    subprocess.run([str(arg) for arg in args],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def copy_tree(source,target):
    for directory,children,files in os.walk(source):
        children[:]=[name for name in children if name not in SKIP]
        relative=pathlib.Path(directory).relative_to(source)
        for name in files:
            if name.endswith(('.pyc','.pyo','.log')): continue
            destination=target/relative/name; destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(pathlib.Path(directory)/name,destination)

def zip_tree(source,target,prefix=''):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(source.rglob('*')):
            relative=path.relative_to(source)
            if path.is_file() and not any(part in SKIP for part in relative.parts) and path.suffix not in ('.pyc','.pyo','.log'):
                archive.write(path,prefix+relative.as_posix())
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None

def collect_runtime(target,work):
    import PySide6
    qt=pathlib.Path(PySide6.__file__).parent
    # PyInstaller is a dependency collector only; its executable is discarded.
    collector=work/'collector.spec'
    collector.write_text('''from pathlib import Path
import PySide6
QT=Path(PySide6.__file__).parent
a=Analysis([%r],pathex=[%r],binaries=[],datas=[],hiddenimports=[],excludes=['matplotlib','scipy','cv2','pandas','numpy','torch'])
a.binaries=[row for row in a.binaries if Path(row[0]).name.lower() not in {'icuuc.dll','icuin.dll','icudt.dll'}]
runtime_names={'msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','vcruntime140.dll','vcruntime140_1.dll'}
for i,row in enumerate(a.binaries):
    name=Path(row[0]).name
    if name.lower() in runtime_names and (QT/name).is_file(): a.binaries[i]=(row[0],str(QT/name),row[2])
destinations={row[0].lower() for row in a.binaries}
for name in runtime_names:
    if name not in destinations and (QT/name).is_file(): a.binaries.append((name,str(QT/name),'BINARY'))
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='collector',console=False)
coll=COLLECT(exe,a.binaries,a.datas,name='collector')
''' % (str(ROOT/'src/launcher.py'),str(ROOT/'src')),encoding='utf-8')
    command([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',work/'collected','--workpath',work/'pyi',collector])
    copy_tree(work/'collected/collector/_internal',target/'_internal')
    base=pathlib.Path(sys.base_prefix)
    abi='python'+str(sys.version_info.major)+str(sys.version_info.minor)
    for name in ('python.exe','pythonw.exe',abi+'.dll'):
        shutil.copy2(base/name,target/name)
    with zipfile.ZipFile(target/'stdlib.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for directory,children,files in os.walk(base/'Lib'):
            children[:]=[name for name in children if name not in SKIP|{'site-packages','test','tests','idlelib','tkinter','turtledemo','ensurepip'}]
            for name in files:
                if name.endswith('.py'):
                    path=pathlib.Path(directory)/name; archive.write(path,path.relative_to(base/'Lib').as_posix())
    (target/(abi+'._pth')).write_text('.\n_internal\nstdlib.zip\n',encoding='ascii')
    for package in ('PySide6','shiboken6'):
        distribution=importlib.metadata.distribution(package)
        package_root=pathlib.Path(distribution.locate_file(package))
        for path in package_root.rglob('*.py'):
            relative=path.relative_to(package_root)
            if any(part in {'scripts','examples','__pycache__','glue'} for part in relative.parts): continue
            destination=target/'_internal'/package/relative; destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)
    for name in ('LICENSE.txt','LICENSE_PYTHON.txt'):
        if (base/name).exists():
            shutil.copy2(base/name,target.parent/'licenses/Python-License.txt'); break

def trim_plugins(runtime):
    # This app only paints PNG/ICO and uses Windows platform integration. Avoid
    # bundling unrelated QML, PDF, virtual-keyboard and network/TLS plugins.
    qt=runtime/'_internal/PySide6'
    plugins=qt/'plugins'
    keep={'platforms/qwindows.dll','platforms/qoffscreen.dll','imageformats/qico.dll','styles/qmodernwindowsstyle.dll'}
    if plugins.exists():
        for path in plugins.rglob('*.dll'):
            if path.relative_to(plugins).as_posix() not in keep: path.unlink()
    required={'qt6core.dll','qt6gui.dll','qt6widgets.dll','qt6network.dll'}
    for path in qt.glob('Qt6*.dll'):
        if path.name.lower() not in required: path.unlink()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--runtime-template',type=pathlib.Path)
    parser.add_argument('--output',type=pathlib.Path,default=ROOT/'dist')
    args=parser.parse_args()
    if os.name!='nt': raise SystemExit('Build on Windows x64.')
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    csc=pathlib.Path(os.environ.get('WINDIR',r'C:\Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not csc.is_file(): raise SystemExit('.NET Framework C# compiler not found.')
    portable=output/('ShuanglingQuota-'+VERSION+'-windows-x64')
    if portable.exists(): raise SystemExit('Output directory already exists; choose a fresh --output directory.')
    portable.mkdir(); runtime=portable/'runtime'; runtime.mkdir(); (portable/'licenses').mkdir()
    with tempfile.TemporaryDirectory(prefix='shuangling-build-') as temporary:
        work=pathlib.Path(temporary)
        if args.runtime_template: copy_tree(args.runtime_template.resolve(),runtime)
        else: collect_runtime(runtime,work)
        trim_plugins(runtime)
        for name in ('launcher.py','widget.py','quota_source.py'): shutil.copy2(ROOT/'src'/name,runtime/name)
        copy_tree(ROOT/'assets',runtime/'assets')
        for name in ('README.md','LICENSE','THIRD_PARTY.md'): shutil.copy2(ROOT/name,portable/name)
        copy_tree(ROOT/'licenses',portable/'licenses'); copy_tree(ROOT/'docs',portable/'docs')
        (portable/'assets').mkdir()
        shutil.copy2(ROOT/'assets/LICENSE.md',portable/'assets/LICENSE.md')
        for package in ('PySide6','shiboken6'):
            distribution=importlib.metadata.distribution(package)
            for item in distribution.files or []:
                if '/licenses/' in str(item).replace('\\','/'):
                    relative=str(item).replace('\\','/').split('/licenses/',1)[1]
                    destination=portable/'licenses'/package/relative; destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(distribution.locate_file(item),destination)
        info={'version':VERSION,'python':subprocess.check_output([str(runtime/'python.exe'),'-c','import sys;print(sys.version)'],text=True).strip(),
              'PySide6':importlib.metadata.version('PySide6'),'launcher':'C# .NET Framework, plain Python runtime',
              'architecture':'x64','unsigned':True,'account_data_included':False}
        (portable/'BUILD-INFO.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
        references=['/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll']
        common=[csc,'/nologo','/target:winexe','/platform:x64','/optimize+','/win32icon:'+str(ROOT/'assets/dragon.ico')]
        command([*common,*references,'/out:'+str(portable/'ShuanglingQuota.exe'),ROOT/'windows/Launcher.cs'])
        for name,argument in (('启用跟随启动.cmd','--install-autostart'),('解除跟随启动.cmd','--uninstall-autostart')):
            (portable/name).write_bytes(('@echo off\r\nstart "" "%~dp0ShuanglingQuota.exe" '+argument+'\r\n').encode('ascii'))
        source=output/('ShuanglingQuota-'+VERSION+'-source.zip'); zip_tree(ROOT,source,'ShuanglingQuota/')
        shutil.copy2(source,portable/'SourceCode.zip')
        files=[]
        for path in sorted(portable.rglob('*')):
            if path.is_file(): files.append({'path':path.relative_to(portable).as_posix(),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (portable/'manifest.json').write_text(json.dumps({'files':files,'state_excluded':True},indent=2),encoding='utf-8')
        payload=work/'payload.zip'; zip_tree(portable,payload)
        setup=output/('ShuanglingQuota-'+VERSION+'-Setup.exe')
        command([*common,*references,'/resource:'+str(payload)+',payload.zip','/out:'+str(setup),ROOT/'windows/Setup.cs'])
        archive=output/('ShuanglingQuota-'+VERSION+'-windows-x64.zip'); zip_tree(portable,archive,portable.name+'/')
    products=[setup,archive,source]
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n' for path in products),encoding='ascii')
    command([portable/'ShuanglingQuota.exe','--check'])
    print(json.dumps({'ok':True,'products':[{'name':path.name,'bytes':path.stat().st_size} for path in products]},indent=2))

if __name__=='__main__': main()
