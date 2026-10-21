"""霜铃 — a transparent, draggable Codex plan-quota desktop companion."""
from __future__ import annotations
import argparse, json, math, os, sys, threading, time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QRectF, QPoint, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPixmap, QIcon, QPainterPath, QDesktopServices, QPalette
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSlider, QCheckBox, QFileDialog, QMessageBox, QComboBox
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QUrl
from quota_source import CodexClient, QuotaError
from notifications import NotificationStore, HourlyChime, PRIORITY, short_text

APP_TITLE='霜铃 · Codex 额度挂件'
BASE_W, BASE_H = 300, 400
RESOURCE_DIR=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
if not (RESOURCE_DIR/'assets').exists() and (RESOURCE_DIR.parent/'assets').exists():
    RESOURCE_DIR=RESOURCE_DIR.parent
APP_DIR=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
STATE_DIR=APP_DIR/'state'
SETTINGS_RECT=QRectF(224,20,24,24)

def configure_app(app):
    # Explicit colors prevent Windows dark-mode text leaking onto light surfaces.
    app.setStyle('Fusion')
    palette=QPalette()
    for role,color in ((QPalette.ColorRole.Window,'#fffdfd'),(QPalette.ColorRole.Base,'#ffffff'),
                       (QPalette.ColorRole.Button,'#f5f0fc'),(QPalette.ColorRole.WindowText,'#41374f'),
                       (QPalette.ColorRole.Text,'#41374f'),(QPalette.ColorRole.ButtonText,'#41374f'),
                       (QPalette.ColorRole.ToolTipBase,'#fffdfd'),(QPalette.ColorRole.ToolTipText,'#41374f'),
                       (QPalette.ColorRole.Highlight,'#dfd1f2'),(QPalette.ColorRole.HighlightedText,'#352847')):
        palette.setColor(role,QColor(color))
    for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled,role,QColor('#7a7085'))
    app.setPalette(palette)
    app.setStyleSheet('''
        QDialog, QMessageBox {background:#fffdfd;color:#41374f;}
        QLabel, QCheckBox {color:#41374f;font-family:"Microsoft YaHei UI";font-size:13px;}
        QPushButton, QComboBox {color:#41374f;padding:7px 14px;border:1px solid #d9d0e9;border-radius:8px;background:#f5f0fc;}
        QPushButton:hover, QComboBox:hover {background:#ebe1f8;}
        QComboBox QAbstractItemView {color:#41374f;background:#fffdfd;selection-background-color:#dfd1f2;selection-color:#352847;}
        QMenu {color:#41374f;background:#fffdfd;border:1px solid #ddd2ec;padding:5px;}
        QMenu::item {padding:7px 22px;color:#41374f;}
        QMenu::item:selected {background:#eee6f9;color:#493465;}
        QMenu::separator {height:1px;background:#ddd2ec;margin:4px;}
        QToolTip {color:#41374f;background:#fffdfd;border:1px solid #bbaaCC;padding:5px;}
        QSlider::groove:horizontal {height:6px;background:#ddd4e8;border-radius:3px;}
        QSlider::sub-page:horizontal {background:#8970b7;border-radius:3px;}
        QSlider::handle:horizontal {background:#705396;border:1px solid #5e427f;width:16px;margin:-6px 0;border-radius:8px;}
    ''')

def countdown(timestamp, now=None):
    if timestamp is None:
        return '重置时间未知'
    seconds=max(0,int(timestamp-(time.time() if now is None else now)))
    if seconds == 0:
        return '等待刷新额度'
    days,seconds=divmod(seconds,86400); hours,seconds=divmod(seconds,3600); minutes,seconds=divmod(seconds,60)
    if days:
        return f'{days}天{hours:02d}时后重置'
    return f'{hours:02d}:{minutes:02d}:{seconds:02d} 后重置'

def save_json(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

class QuotaWorker(QObject):
    received=Signal(object)
    failed=Signal(str)
    def __init__(self):
        super().__init__()
        self.client=CodexClient()
        self.busy=False
        self.closed=False
    def refresh(self):
        if self.busy or self.closed:
            return
        self.busy=True
        def work():
            try:
                result=self.client.read()
                if not self.closed:
                    self.received.emit(result)
            except Exception as exc:
                if not self.closed:
                    self.failed.emit(str(exc) if isinstance(exc,QuotaError) else '额度读取失败，请稍后重试。')
            finally:
                self.busy=False
        threading.Thread(target=work,daemon=True).start()
    def close(self):
        self.closed=True
        self.client.close()

class QuotaWidget(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args=args
        self.settings={'scale':0.85,'topmost':True,'snap':True,'motion':True,'refresh_seconds':60,'focus':0,'codex_alerts':True,'hourly_chime':True}
        try:
            self.settings.update(json.loads((STATE_DIR/'settings.json').read_text(encoding='utf-8')))
        except (OSError,ValueError,TypeError):
            pass
        self.scale=max(0.5,min(2.0,float(self.settings['scale'])))
        self.snapshot=None
        self.error=''
        self.loading=True
        self.focus=int(self.settings.get('focus',0))
        self.display_value=None
        self.target_value=None
        self.last_tick=time.monotonic()
        self.started=time.monotonic()
        self.pressed_at=-100
        self.press_global=None
        self.dragging=False
        self.left_docked=False
        self.details_dialog=None
        self.notifications=NotificationStore(STATE_DIR/'notifications')
        self.hourly_chime=HourlyChime()
        self.hourly_notice=None
        self.notice=None
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.pixmap=QPixmap(str(RESOURCE_DIR/'assets/dragon.png'))
        if self.pixmap.isNull():
            raise RuntimeError('缺少 assets/dragon.png')
        self.icon=QIcon(self.pixmap)
        self.setWindowIcon(self.icon)
        self.resize(round(BASE_W*self.scale),round(BASE_H*self.scale))
        self.position_initially()
        self.worker=QuotaWorker()
        self.worker.received.connect(self.on_data)
        self.worker.failed.connect(self.on_error)
        self.refresh_timer=QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(max(30,int(self.settings['refresh_seconds']))*1000)
        self.animation_timer=QTimer(self)
        self.animation_timer.timeout.connect(self.tick)
        self.animation_timer.start(33)
        self.clock_timer=QTimer(self)
        self.clock_timer.timeout.connect(self.update_tooltip)
        self.clock_timer.start(1000)
        self.notice_timer=QTimer(self)
        self.notice_timer.timeout.connect(self.poll_notices)
        self.notice_timer.start(500)
        self.tray=QSystemTrayIcon(self.icon,self)
        self.tray.setToolTip(APP_TITLE)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setContextMenu(self.make_menu())
        if QSystemTrayIcon.isSystemTrayAvailable() and not args.preview:
            self.tray.show()
        if not args.preview:
            try:
                cached=json.loads((STATE_DIR/'last-quota.json').read_text(encoding='utf-8'))
                if isinstance(cached,dict) and cached.get('windows'):
                    self.snapshot=cached
                    self.loading=False
                    self.error='正在更新上次记录'
                    self.update_target()
            except (OSError,ValueError,TypeError):
                pass
            QTimer.singleShot(100,self.refresh)
        else:
            self.snapshot=json.loads(Path(args.preview).read_text(encoding='utf-8'))
            self.loading=False
            self.update_target()
        self.update_tooltip()

    def position_initially(self):
        screens=QApplication.screens()
        if not screens:
            return
        saved_x,saved_y=self.settings.get('x'),self.settings.get('y')
        if isinstance(saved_x,int) and isinstance(saved_y,int):
            point=QPoint(saved_x+self.width()//2,saved_y+self.height()//2)
            if any(s.availableGeometry().contains(point) for s in screens):
                self.move(saved_x,saved_y)
                self.clamp_to_screen()
                return
        area=QApplication.primaryScreen().availableGeometry()
        self.move(area.right()-self.width()-24,area.bottom()-self.height()-16)

    def save_settings(self):
        self.settings.update({'scale':self.scale,'x':self.x(),'y':self.y(),'focus':self.focus})
        try:
            save_json(STATE_DIR/'settings.json',self.settings)
        except OSError:
            pass

    def refresh(self):
        if self.worker.busy:
            return
        self.loading=True
        self.worker.refresh()
        self.update()

    def on_data(self, snapshot):
        self.snapshot=snapshot
        self.loading=False
        self.error=''
        self.update_target()
        try:
            save_json(STATE_DIR/'last-quota.json',snapshot)
        except OSError:
            pass
        self.update_tooltip()
        self.update()

    def on_error(self, message):
        self.loading=False
        self.error=message
        self.update_tooltip()
        self.update()

    def current_window(self):
        if not self.snapshot or not self.snapshot.get('windows'):
            return None
        return self.snapshot['windows'][self.focus%len(self.snapshot['windows'])]

    def update_target(self):
        window=self.current_window()
        self.target_value=window['remaining_percent'] if window else None
        if self.display_value is None:
            self.display_value=self.target_value

    def tick(self):
        if self.display_value is not None and self.target_value is not None:
            delta=self.target_value-self.display_value
            self.display_value=self.target_value if abs(delta)<0.04 else self.display_value+delta*0.16
        self.update()

    def is_stale(self):
        return bool(self.error) or bool(self.snapshot and time.time()-self.snapshot.get('updated_at',0)>max(180,int(self.settings['refresh_seconds'])*3))

    def update_tooltip(self):
        lines=[APP_TITLE]
        if self.notice:
            lines += [self.notice['title'],self.notice.get('summary','')]
        if self.snapshot:
            lines.append('套餐：'+str(self.snapshot.get('plan') or '未知'))
            for w in self.snapshot['windows']:
                reset=datetime.fromtimestamp(w['resets_at']).strftime('%m-%d %H:%M:%S') if w.get('resets_at') else '未知'
                lines.append(f"{w['label']}：剩余 {w['remaining_percent']:g}% · {reset} 重置")
            updated=datetime.fromtimestamp(self.snapshot.get('updated_at',0)).strftime('%H:%M:%S')
            lines.append('上次成功更新：'+updated)
        if self.error:
            lines.append(self.error)
        lines += ['单击龙娘刷新 · 单击气泡切换窗口','滚轮调整大小 · 右上角···外观设置','拖动移动 · 右键查看额度详情','数据范围：Codex 套餐额度，不代表普通 ChatGPT 各模型聊天限额。']
        self.setToolTip('\n'.join(lines))

    def poll_notices(self):
        if self.args.preview: return
        now=time.time()
        hourly=self.hourly_chime.poll(now,self.settings.get('hourly_chime',True))
        if hourly: self.hourly_notice=hourly
        if self.hourly_notice and self.hourly_notice['expires_at']<=now: self.hourly_notice=None
        codex=self.notifications.current(now) if self.settings.get('codex_alerts',True) else None
        choices=[item for item in (codex,self.hourly_notice if self.settings.get('hourly_chime',True) else None) if item]
        notice=max(choices,key=lambda item:PRIORITY[item['kind']],default=None)
        if notice!=self.notice:
            self.notice=notice; self.update_tooltip(); self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(self.scale,self.scale)
        self.draw_bubble(p)
        elapsed=time.monotonic()-self.started
        bob=math.sin(elapsed*1.9)*1.6 if self.settings['motion'] and not self.dragging else 0
        pulse_age=time.monotonic()-self.pressed_at
        squash=1-0.09*math.exp(-pulse_age*8)*math.cos(pulse_age*20) if pulse_age<0.8 else 1
        target=QRectF(100,172+bob,193,224)
        aspect=self.pixmap.width()/self.pixmap.height()
        width=min(target.width(),target.height()*aspect)
        height=width/aspect
        target=QRectF(target.center().x()-width/2,target.bottom()-height,width,height)
        p.save()
        p.translate(target.center().x(),target.bottom())
        p.scale(1+(1-squash)*0.45,squash)
        if self.left_docked:
            p.scale(-1,1)
        p.drawPixmap(QRectF(-width/2,-height,width,height),self.pixmap,QRectF(self.pixmap.rect()))
        p.restore()

    def text(self,p,rect,text,size,color,bold=False,alignment=Qt.AlignmentFlag.AlignCenter):
        font=QFont('Microsoft YaHei UI')
        font.setPixelSize(size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(rect,alignment,text)

    def draw_bubble(self,p):
        outline=QColor('#6b5b9b')
        p.setPen(QPen(outline,3.1))
        p.setBrush(QColor('#fffefd'))
        p.drawRoundedRect(QRectF(8,8,253,153),54,54)
        p.drawEllipse(QRectF(83,173,16,11))
        p.drawEllipse(QRectF(109,190,9,7))
        plan=(str(self.snapshot.get('plan') or '').upper() if self.snapshot else '')
        heading='CODEX 提醒' if self.notice else 'CODEX'+(' · '+plan if plan else ' 额度')
        self.text(p,QRectF(28,16,191,25),heading,14,'#59477f',True)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#eee7f8'))
        p.drawRoundedRect(SETTINGS_RECT,8,8)
        self.text(p,SETTINGS_RECT,'···',18,'#59477f',True)
        if self.notice:
            self.draw_notice(p)
            return
        w=self.current_window()
        if w:
            value=self.display_value if self.display_value is not None else w['remaining_percent']
            color='#b76b86' if value<=15 else '#7563b4'
            self.text(p,QRectF(23,41,223,49),f'{value:.0f}%',40,color,True)
            self.text(p,QRectF(23,87,223,23),w['label']+'额度剩余',12,'#6a587e')
            others=[item for item in self.snapshot['windows'] if item is not w]
            other=others[0] if others else None
            sub=f"{other['label']}剩余 {other['remaining_percent']:g}%" if other else '单窗口额度'
            if self.is_stale():
                sub='上次记录 · 等待更新'
            self.text(p,QRectF(23,109,223,22),sub,12,'#805c3e' if self.is_stale() else '#6a587e')
            status=countdown(w.get('resets_at'))
        else:
            self.text(p,QRectF(23,43,223,47),'···' if self.loading else '—',40,'#7563b4',True)
            self.text(p,QRectF(23,92,223,25),'正在读取套餐额度' if self.loading else '暂未取得额度',13,'#9285b2')
            status='连接本机 Codex' if self.loading else '右键查看连接说明'
        stale=self.is_stale()
        fill='#eee7db' if stale else '#e9e1f8'
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(52,145,163,24),12,12)
        dot='#c59b69' if stale else ('#a595d1' if self.loading else '#73b394')
        p.setBrush(QColor(dot))
        p.drawEllipse(QRectF(62,153,7,7))
        self.text(p,QRectF(74,146,131,22),status,10,'#7b6a96',True)

    def draw_notice(self,p):
        notice=self.notice; pending=notice['kind'] in ('question','permission')
        color='#8c5939' if pending else '#59477f'
        self.text(p,QRectF(23,44,223,34),notice['title'],22,color,True)
        flags=int(Qt.AlignmentFlag.AlignCenter)|int(Qt.TextFlag.TextWordWrap)
        self.text(p,QRectF(28,80,213,43),short_text(notice.get('summary',''),38),12,'#51435f',alignment=flags)
        windows=self.snapshot.get('windows',[]) if self.snapshot else []
        quota=' · '.join(f"{window['label']} {window['remaining_percent']:g}%" for window in windows[:2])
        self.text(p,QRectF(23,123,223,20),quota or '额度仍会自动刷新',10,'#6a587e')
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#f4e4cb' if pending else '#e9e1f8'))
        p.drawRoundedRect(QRectF(52,145,163,24),12,12)
        self.text(p,QRectF(55,146,157,22),'回 Codex 查看并处理' if pending else '稍后自动恢复额度',10,color,True)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.press_global=event.globalPosition().toPoint()
            self.press_origin=self.pos()
            self.press_local=event.position()
            self.pressed_at=time.monotonic()
            self.dragging=False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self,event):
        if self.press_global is not None and event.buttons()&Qt.MouseButton.LeftButton:
            delta=event.globalPosition().toPoint()-self.press_global
            if delta.manhattanLength()>5:
                self.dragging=True
            if self.dragging:
                self.move(self.press_origin+delta)
            event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.press_global is not None:
            if self.dragging:
                self.clamp_to_screen(snap=bool(self.settings['snap']))
                self.save_settings()
            elif SETTINGS_RECT.contains(self.press_local/self.scale):
                self.show_settings()
            elif self.press_local.y()/self.scale<170 and self.snapshot and len(self.snapshot['windows'])>1:
                self.focus=(self.focus+1)%len(self.snapshot['windows'])
                self.display_value=None
                self.update_target()
                self.save_settings()
            else:
                self.refresh()
            self.press_global=None
            self.dragging=False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()

    def mouseDoubleClickEvent(self,event):
        # Qt delivers the second press as a double-click event. Keep its bounce
        # and normal release handling without opening a separate dialog.
        self.mousePressEvent(event)

    def apply_scale(self,scale):
        anchor=self.geometry().bottomRight()
        self.scale=round(max(0.5,min(2.0,scale)),2)
        self.resize(round(BASE_W*self.scale),round(BASE_H*self.scale))
        self.move(anchor.x()-self.width()+1,anchor.y()-self.height()+1)
        self.clamp_to_screen(); self.save_settings(); self.update()

    def wheelEvent(self,event):
        delta=event.angleDelta().y()
        if delta:
            self.apply_scale(self.scale+delta/120*0.05)
            event.accept()

    def clamp_to_screen(self,snap=False):
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        x=max(area.left(),min(self.x(),area.right()-self.width()+1))
        y=max(area.top(),min(self.y(),area.bottom()-self.height()+1))
        if snap:
            if x-area.left()<36: x=area.left()
            elif area.right()+1-(x+self.width())<36: x=area.right()-self.width()+1
            if y-area.top()<25: y=area.top()
            elif area.bottom()+1-(y+self.height())<25: y=area.bottom()-self.height()+1
        self.left_docked=x<=area.left()+2
        self.move(x,y)

    def contextMenuEvent(self,event):
        self.make_menu().exec(event.globalPos())

    def make_menu(self):
        menu=QMenu(self)
        menu.addAction('刷新额度',self.refresh)
        menu.addAction('额度详情 / 连接状态',self.show_details)
        menu.addAction('外观设置',self.show_settings)
        menu.addAction('接入 Codex 气泡提醒…',self.connect_codex_alerts)
        menu.addAction('解除 Codex 提醒接入',self.disconnect_codex_alerts)
        from launcher import autorun_enabled
        follow=menu.addAction('跟随 Codex / ChatGPT 启停')
        follow.setCheckable(True); follow.setChecked(autorun_enabled())
        follow.toggled.connect(self.set_follow_mode)
        menu.addSeparator()
        top=menu.addAction('置顶显示')
        top.setCheckable(True); top.setChecked(bool(self.settings['topmost']))
        top.toggled.connect(self.set_topmost)
        visible=menu.addAction('显示挂件')
        visible.setCheckable(True); visible.setChecked(self.isVisible())
        visible.toggled.connect(self.setVisible)
        menu.addAction('恢复右下角位置',self.reset_position)
        menu.addAction('打开 Codex 用量页',lambda:QDesktopServices.openUrl(QUrl('https://chatgpt.com/codex/settings/usage')))
        menu.addSeparator()
        menu.addAction('退出挂件',lambda:self.quit_app())
        return menu

    def set_topmost(self,enabled):
        self.settings['topmost']=enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,enabled)
        self.show()
        self.save_settings()

    def set_follow_mode(self,enabled):
        from launcher import install_autostart,remove_autostart
        if enabled: install_autostart()
        else: remove_autostart()

    def connect_codex_alerts(self):
        from codex_hooks import install_hooks
        try:
            target=install_hooks()
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'提醒接入失败',str(exc)); return
        QMessageBox.information(self,'Codex 提醒已配置',
            '已配置本地提醒 Hook：\n'+str(target)+'\n\n请在 Codex CLI 中输入 /hooks，审阅并信任“霜铃气泡提醒（仅通知）”。\nCodex 信任后才会发送询问、权限和结束事件；需要时重新打开会话。\n提醒不会批准权限或替你回答问题。')

    def disconnect_codex_alerts(self):
        from codex_hooks import remove_hooks
        try: remove_hooks()
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'解除提醒失败',str(exc)); return
        for path,_ in self.notifications.entries():
            try: path.unlink(missing_ok=True)
            except OSError: pass
        self.poll_notices()
        QMessageBox.information(self,'提醒已解除','已移除霜铃自己的 Codex Hook，保留其他规则。整点报时仍可在外观设置中开关。')

    def reset_position(self):
        self.settings.pop('x',None); self.settings.pop('y',None)
        self.position_initially()
        self.left_docked=False
        self.show(); self.save_settings()

    def tray_activated(self,reason):
        if reason==QSystemTrayIcon.ActivationReason.Trigger:
            self.setVisible(not self.isVisible())

    def show_details(self):
        if self.details_dialog and self.details_dialog.isVisible():
            self.details_dialog.raise_(); return
        dialog=QDialog(self)
        dialog.setWindowTitle('霜铃 · 额度详情')
        dialog.setMinimumWidth(410)
        layout=QVBoxLayout(dialog)
        title=QLabel('Codex 套餐剩余额度')
        title.setStyleSheet('font-size:19px;font-weight:700;color:#6b5b9b;margin-bottom:8px')
        layout.addWidget(title)
        data=QLabel()
        data.setWordWrap(True)
        data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(data)
        def update_detail():
            self.update_tooltip()
            data.setText(self.toolTip().replace('\n单击龙娘刷新 · 单击气泡切换窗口','').replace('\n拖动移动 · 右键查看额度详情',''))
        update_detail()
        timer=QTimer(dialog); timer.timeout.connect(update_detail); timer.start(1000)
        note=QLabel('连接官方 Codex App Server，沿用本机 Codex CLI 登录。\n若未登录，请在终端运行 codex login 并自行完成登录。\n不读取浏览器 Cookie，不需要 OpenAI API Key。')
        note.setWordWrap(True); note.setStyleSheet('color:#675a76;margin:12px 0')
        layout.addWidget(note)
        buttons=QHBoxLayout()
        refresh=QPushButton('立即刷新'); refresh.clicked.connect(self.refresh); buttons.addWidget(refresh)
        select=QPushButton('选择 codex.exe'); select.clicked.connect(self.select_codex); buttons.addWidget(select)
        close=QPushButton('关闭'); close.clicked.connect(dialog.close); buttons.addWidget(close)
        layout.addLayout(buttons)
        self.details_dialog=dialog
        dialog.show()

    def select_codex(self):
        path,_=QFileDialog.getOpenFileName(self,'选择官方 Codex CLI 可执行文件','','Codex (codex.exe)')
        if path:
            if self.worker.busy:
                QMessageBox.information(self,'正在读取','请等待当前读取完成后再选择。'); return
            self.worker.client.close()
            self.worker.client.command=[path]
            self.settings['codex_exe']=path
            self.save_settings()
            self.refresh()

    def create_settings_dialog(self):
        dialog=QDialog(self); dialog.setWindowTitle('霜铃 · 外观设置')
        dialog.setMinimumWidth(360)
        layout=QVBoxLayout(dialog)
        label=QLabel(f'挂件大小：{round(self.scale*100)}%'); layout.addWidget(label)
        slider=QSlider(Qt.Orientation.Horizontal); slider.setRange(50,200); slider.setValue(round(self.scale*100)); layout.addWidget(slider)
        layout.addWidget(QLabel('50% — 200% · 也可以直接在挂件上滚动鼠标滚轮'))
        def resize(value):
            self.apply_scale(value/100); label.setText(f'挂件大小：{value}%')
        slider.valueChanged.connect(resize)
        snap=QCheckBox('靠近屏幕边缘时吸附'); snap.setChecked(self.settings['snap']); layout.addWidget(snap)
        motion=QCheckBox('轻微浮动和按压回弹'); motion.setChecked(self.settings['motion']); layout.addWidget(motion)
        alerts=QCheckBox('在气泡显示 Codex 询问、权限与本轮结束提醒'); alerts.setChecked(self.settings.get('codex_alerts',True)); layout.addWidget(alerts)
        hourly=QCheckBox('整点在气泡报时（无声音）'); hourly.setChecked(self.settings.get('hourly_chime',True)); layout.addWidget(hourly)
        layout.addWidget(QLabel('自动刷新频率'))
        interval=QComboBox()
        for seconds in (30,60,120,300): interval.addItem(f'{seconds} 秒',seconds)
        index=interval.findData(self.settings['refresh_seconds']); interval.setCurrentIndex(max(0,index)); layout.addWidget(interval)
        save=QPushButton('保存'); layout.addWidget(save)
        def done():
            self.settings.update({'snap':snap.isChecked(),'motion':motion.isChecked(),'refresh_seconds':interval.currentData(),'codex_alerts':alerts.isChecked(),'hourly_chime':hourly.isChecked()})
            self.refresh_timer.start(int(interval.currentData())*1000)
            self.save_settings(); dialog.accept()
        save.clicked.connect(done)
        dialog.finished.connect(lambda _: self.save_settings())
        return dialog

    def show_settings(self):
        self.create_settings_dialog().exec()

    def quit_app(self,user_initiated=True):
        if user_initiated:
            from launcher import ipc,WATCHER_PIPE
            ipc(WATCHER_PIPE,b'pause')
        self.save_settings(); self.worker.close(); self.tray.hide(); QApplication.quit()

    def closeEvent(self,event):
        self.quit_app(); event.accept()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--probe',action='store_true',help='Read real quota and exit; no inference requests.')
    parser.add_argument('--preview',metavar='JSON',help='Render explicitly supplied data, not a live connection.')
    parser.add_argument('--render-preview',metavar='PNG',help='Export widget drawing to PNG and exit.')
    args=parser.parse_args()
    if args.probe:
        client=CodexClient()
        try: print(json.dumps(client.read(),ensure_ascii=False,indent=2))
        finally: client.close()
        return
    app=QApplication(sys.argv[:1]); app.setApplicationName('ShuanglingQuotaWidget'); app.setQuitOnLastWindowClosed(False)
    configure_app(app)
    socket=QLocalSocket(); socket.connectToServer('ShuanglingQuotaWidget_v1')
    if not args.render_preview and socket.waitForConnected(250):
        socket.write(b'show'); socket.waitForBytesWritten(250); return
    server=QLocalServer()
    if not args.render_preview:
        QLocalServer.removeServer('ShuanglingQuotaWidget_v1')
        server.listen('ShuanglingQuotaWidget_v1')
    widget=QuotaWidget(args)
    if widget.settings.get('codex_exe'):
        widget.worker.client.command=[widget.settings['codex_exe']]
    if not widget.settings['topmost']:
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,False)
    def show_existing():
        connection=server.nextPendingConnection()
        if not connection: return
        connection.waitForReadyRead(150)
        command=bytes(connection.readAll())
        connection.close()
        if command==b'quit':
            widget.quit_app(user_initiated=False); return
        if command==b'ping':
            return
        widget.show(); widget.raise_()
    server.newConnection.connect(show_existing)
    app.aboutToQuit.connect(widget.worker.close)
    if args.render_preview:
        pixmap=QPixmap(widget.size()); pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap); pixmap.save(args.render_preview); widget.worker.close(); return
    widget.show()
    app.exec()

if __name__=='__main__':
    main()
