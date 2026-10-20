import argparse, json, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QPalette, QColor, QWheelEvent
from PySide6.QtWidgets import QApplication, QSlider, QLabel, QPushButton, QCheckBox, QComboBox
from PySide6.QtTest import QTest
import widget

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=pathlib.Path(self.temp.name)
        (root/'snapshot.json').write_text(json.dumps({'windows':[{'remaining_percent':70,'label':'5小时'}]}))
        self.state=patch.object(widget,'STATE_DIR',root); self.state.start()
        self.autorun=patch('launcher.autorun_enabled',return_value=False); self.autorun.start()
        dark=QPalette(); dark.setColor(QPalette.ColorRole.WindowText,QColor('white'))
        dark.setColor(QPalette.ColorRole.Text,QColor('white')); self.app.setPalette(dark)
        widget.configure_app(self.app)
        self.w=widget.QuotaWidget(argparse.Namespace(preview=str(root/'snapshot.json')))

    def tearDown(self):
        self.w.worker.close(); self.w.tray.hide(); self.w.deleteLater()
        self.app.processEvents(); self.autorun.stop(); self.state.stop(); self.temp.cleanup()

    def test_light_surfaces_have_dark_text_even_after_dark_palette(self):
        dialog=self.w.create_settings_dialog(); dialog.ensurePolished()
        controls=[control for kind in (QLabel,QPushButton,QCheckBox,QComboBox) for control in dialog.findChildren(kind)]
        for control in controls:
            control.ensurePolished()
            role=QPalette.ColorRole.ButtonText if isinstance(control,QPushButton) else QPalette.ColorRole.WindowText
            self.assertLess(control.palette().color(role).lightness(),160)
        menu=self.w.make_menu(); menu.ensurePolished()
        self.assertLess(menu.palette().color(QPalette.ColorRole.WindowText).lightness(),160)
        dialog.deleteLater(); menu.deleteLater()

    def test_scale_limits_slider_and_wheel_persist(self):
        dialog=self.w.create_settings_dialog(); slider=dialog.findChild(QSlider)
        self.assertEqual((slider.minimum(),slider.maximum()),(50,200))
        slider.setValue(150); self.assertEqual(self.w.size().width(),450)
        wheel=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        self.w.wheelEvent(wheel); self.assertEqual(self.w.scale,1.55)
        self.w.apply_scale(3); self.assertEqual(self.w.scale,2)
        self.w.apply_scale(0); self.assertEqual(self.w.scale,.5)
        saved=json.loads((widget.STATE_DIR/'settings.json').read_text())
        self.assertEqual(saved['scale'],.5); dialog.deleteLater()

    def test_visible_settings_button_opens_dialog(self):
        self.w.show(); self.app.processEvents()
        with patch.object(self.w,'show_settings') as open_settings:
            point=(widget.SETTINGS_RECT.center()*self.w.scale).toPoint()
            QTest.mouseClick(self.w,Qt.MouseButton.LeftButton,pos=point)
            open_settings.assert_called_once()
        self.w.hide()

if __name__=='__main__': unittest.main()
