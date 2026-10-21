"""Export explicit demo states from the app painter; no account data is read."""
import argparse,pathlib,sys,tempfile
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
import widget
app=QApplication([]); widget.configure_app(app)
with tempfile.TemporaryDirectory() as directory,patch.object(widget,'STATE_DIR',pathlib.Path(directory)),patch('launcher.autorun_enabled',return_value=False):
    w=widget.QuotaWidget(argparse.Namespace(preview=str(ROOT/'docs/example-quota.json')))
    w.settings['motion']=False; w.animation_timer.stop(); w.apply_scale(1)
    w.show(); app.processEvents()
    examples=[('question','等你回答','示例：采用哪种界面布局？'),('permission','权限确认中','示例：需要访问指定文件夹'),
              ('completed','本轮已完成','示例：处理结束，回 Codex 查看结果'),('hourly','现在是 10:00','整点报时 · 使用电脑时记得适当休息')]
    for kind,title,summary in examples:
        w.notice={'kind':kind,'title':title,'summary':summary}
        w.update(); app.processEvents()
        image=QPixmap(w.size()); image.fill(Qt.GlobalColor.transparent); w.render(image)
        image.save(str(ROOT/'docs'/('notice-'+kind+'.png')))
    w.hide(); w.worker.close(); w.tray.hide()
print('Exported four explicit notification demo states')
