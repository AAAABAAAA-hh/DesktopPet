"""Small dialogs that don't try to look like the rest of Windows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, win32
from .theme import MUTED, PAPER, font
from .window import MAX_SCALE, MIN_SCALE

if TYPE_CHECKING:
    from .manager import PetManager


ABOUT_HTML = """
<div style="color:#3B3340">
  <div style="font-size:12pt; line-height:1.55">
    一个会趴在桌面右下角、可以拎起来、可以投喂、还会抢鼠标的纸片同学。
  </div>
  <div style="height:8px"></div>
  <div style="font-weight:600; font-size:10.5pt">怎么玩</div>
  <ul style="margin-top:4px; margin-bottom:6px; line-height:1.55">
    <li><b>左键</b>：点一下会 Q 弹一下；按住拖动时只用水平速度产生 ±12° 的阻尼惯性倾角，悬空时轻轻上下浮动，松手自由落体，落地还会蹲一下。</li>
    <li><b>连击</b>：0.9 秒内连点 3 下，会冒出跳动的 💢、气到脸红并甩出暴走台词。</li>
    <li><b>滚轮</b>：在脑袋上滚一滚，摸头降火气。</li>
    <li><b>右键</b>：投喂、换装（仅带 costumes/ 专属套件的角色）、更换/召唤人物模型、⚙️ 偏好设置、睡觉、学习，或者收起至托盘。</li>
    <li><b>拖文件</b>：把任意本地文件丢到它身上，可能会被吃掉，也可能会被吐出来。</li>
    <li><b>待机</b>：会轻轻呼吸、眨眼，偶尔自己晃两下。</li>
    <li><b>托盘</b>：召唤更多室友、全员开饭、显示/隐藏桌宠和恶作剧模式。</li>
  </ul>
  <div style="font-weight:600; font-size:10.5pt">整蛊开关</div>
  <div style="line-height:1.55">
    生气值满格时会触发桌面暴走：放大、贴纸条、短暂抢走鼠标。
    按 <b>Esc</b> 可以立刻中断抢鼠标；托盘里点「恶作剧模式」可以彻底关掉。
    状态监听只读取当前前台窗口的程序名和标题，用来吐槽你在卷还是在摸鱼，不会上传任何数据。
  </div>
  <div style="height:8px"></div>
  <div style="font-weight:600; font-size:10.5pt">换成你的同学</div>
  <div style="line-height:1.55">
    ⚙️ 偏好设置 →「人物模型」→「➕ 导入新角色」，选任意一张二次元立绘
    或人物全身/半身照片，再填写名称、头衔与姿态（站姿 / 坐姿趴桌）。
    通用打包器会自动 AI 去背景、归一化到 720×1080、切出头/身图层，
    并保持原始干净面容；复杂背景交给 rembg/GrabCut，不再生成纸边贴纸。<br>
    也可以手动把分层 PNG 放进 <b>characters/角色名/</b>；托盘菜单里能打开素材文件夹。
    设置里的「显示大小」支持 <b>20% ~ 200%</b>，默认 40%，能缩成桌角小挂件。
  </div>
</div>
"""


class AboutDialog(QDialog):
    def __init__(self, parent=None, open_folder_callback=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("桌角同学 Deskling · 使用说明")
        self.setMinimumWidth(590)
        self.setStyleSheet(
            f"QDialog {{ background: {PAPER}; }}"
            f"QLabel {{ background: transparent; }}"
        )
        self._open_folder = open_folder_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(13)

        top = QHBoxLayout()
        icon = QLabel()
        icon.setFixedSize(78, 78)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        title = QLabel("桌角同学")
        title.setFont(font(24, QFont.Weight.Black))
        title.setStyleSheet("color:#3B3340;")
        subtitle = QLabel("Deskling · 桌面纸片人分身")
        subtitle.setFont(font(10))
        subtitle.setStyleSheet(f"color:{MUTED};")
        text.addWidget(title)
        text.addWidget(subtitle)
        text.addStretch(1)
        top.addLayout(text, 1)
        version = QLabel(f"v{__version__}")
        version.setStyleSheet(f"color:{MUTED}; font-size:9pt;")
        version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        top.addWidget(version, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        body = QLabel(ABOUT_HTML)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(False)
        body.setFont(font(10))
        body.setStyleSheet("color:#4B4149;")
        layout.addWidget(body, 1)

        buttons = QHBoxLayout()
        folder_button = QPushButton("打开角色素材文件夹")
        folder_button.clicked.connect(self._on_open_folder)
        close_button = QPushButton("知道了")
        close_button.setObjectName("primary")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(folder_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._icon_label = icon

    def set_avatar(self, pixmap: QPixmap) -> None:
        if not pixmap.isNull():
            self._icon_label.setPixmap(
                pixmap.scaled(
                    78,
                    78,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _on_open_folder(self) -> None:
        if self._open_folder is not None:
            self._open_folder()
        self.accept()


@dataclass(frozen=True)
class CharacterImportInfo:
    """Metadata collected before an image is turned into a character."""

    name: str
    subtitle: str = "自定义导入角色"
    posture: str = "stand"


class CharacterImportDialog(QDialog):
    """Ask for a name, a subtitle and a posture before importing.

    The filename is deliberately **not** pre-filled: an imported classmate
    should get a human name ("小夏", "图书馆常驻NPC") instead of inheriting
    ``IMG_2048`` from the photo.
    """

    def __init__(
        self,
        parent=None,
        preview: QPixmap | str | Path | None = None,
        *,
        initial: CharacterImportInfo | None = None,
        title: str = "导入新角色",
        accept_text: str = "生成角色",
    ) -> None:
        super().__init__(parent)
        if isinstance(preview, (str, Path)):
            preview = QPixmap(str(preview))
        self.setWindowTitle(f"桌角同学 · {title}")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(430)
        self.setStyleSheet(f"QDialog {{ background: {PAPER}; }} QLabel {{ background: transparent; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self._preview = QLabel()
        self._preview.setFixedSize(66, 66)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if preview is not None and not preview.isNull():
            self._preview.setPixmap(
                preview.scaled(
                    66,
                    66,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        header.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignTop)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title_label = QLabel(title)
        title_label.setFont(font(17, QFont.Weight.Black))
        title_label.setStyleSheet("color:#3B3340;")
        subtitle = QLabel("图片只在本机处理，填好信息后立即生成角色卡。")
        subtitle.setObjectName("muted")
        subtitle.setFont(font(9))
        subtitle.setWordWrap(True)
        heading.addWidget(title_label)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        root.addLayout(header)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setColumnStretch(1, 1)

        name_label = QLabel("角色名称")
        name_label.setFont(font(10, QFont.Weight.DemiBold))
        self._name_edit = QLineEdit()
        self._name_edit.setMaxLength(24)
        self._name_edit.setPlaceholderText("例如：小夏 / 隔壁班的猫")
        self._name_edit.setFont(font(10))
        form.addWidget(name_label, 0, 0)
        form.addWidget(self._name_edit, 0, 1)

        subtitle_label = QLabel("头衔 / 人设简介")
        subtitle_label.setFont(font(10, QFont.Weight.DemiBold))
        self._subtitle_edit = QLineEdit()
        self._subtitle_edit.setMaxLength(60)
        self._subtitle_edit.setPlaceholderText("例如：图书馆常驻NPC / 后排摸鱼冠军")
        self._subtitle_edit.setFont(font(10))
        form.addWidget(subtitle_label, 1, 0)
        form.addWidget(self._subtitle_edit, 1, 1)

        posture_label = QLabel("姿态类型")
        posture_label.setFont(font(10, QFont.Weight.DemiBold))
        self._posture_combo = QComboBox()
        self._posture_combo.setFont(font(10))
        self._posture_combo.addItem("站姿", "stand")
        self._posture_combo.addItem("坐姿趴桌", "sit")
        self._posture_combo.setItemData(
            self._posture_combo.findData("stand"),
            "会走动、会爬墙，适合全身立绘。",
            Qt.ItemDataRole.ToolTipRole,
        )
        self._posture_combo.setItemData(
            self._posture_combo.findData("sit"),
            "固定在桌面一角，适合半身像、趴桌图。",
            Qt.ItemDataRole.ToolTipRole,
        )
        form.addWidget(posture_label, 2, 0)
        form.addWidget(self._posture_combo, 2, 1)
        root.addLayout(form)

        if initial is not None:
            self._name_edit.setText(initial.name)
            self._subtitle_edit.setText(initial.subtitle)
            index = self._posture_combo.findData(initial.posture)
            self._posture_combo.setCurrentIndex(max(0, index))
        self._name_edit.setFocus()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        cancel.clicked.connect(self.reject)
        self._accept_button = QPushButton(accept_text)
        self._accept_button.setObjectName("primary")
        # Enter/Return anywhere in the form submits the dialog.  The button is
        # both the visual primary action and Qt's default button.
        self._accept_button.setDefault(True)
        self._accept_button.setAutoDefault(True)
        self._accept_button.clicked.connect(self._submit)
        # Friendly alias for callers/tests that look for the save button.
        self.save_btn = self._accept_button
        buttons.addWidget(cancel)
        buttons.addWidget(self._accept_button)
        root.addLayout(buttons)

        # Escape is a real shortcut (not only a QDialog key handler), so it
        # also works while the focus is inside a QLineEdit.
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.activated.connect(self.reject)
        self._escape_shortcut = escape

        self._name_edit.textChanged.connect(self._update_accept_state)
        self._name_edit.returnPressed.connect(self._submit)
        self._subtitle_edit.returnPressed.connect(self._submit)
        self._posture_combo.activated.connect(lambda _index: self._update_accept_state())
        self._update_accept_state()

    def _update_accept_state(self) -> None:
        self._accept_button.setEnabled(bool(self._name_edit.text().strip()))

    def _submit(self) -> None:
        """Validate and accept; triggered by Enter or the save button."""

        if not self._name_edit.text().strip():
            self._name_edit.setFocus()
            return
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def info(self) -> CharacterImportInfo:
        return CharacterImportInfo(
            name=self._name_edit.text().strip(),
            subtitle=self._subtitle_edit.text().strip() or "自定义导入角色",
            posture=str(self._posture_combo.currentData() or "stand"),
        )

    @classmethod
    def ask(
        cls,
        parent,
        preview: QPixmap | None = None,
        *,
        initial: CharacterImportInfo | None = None,
        title: str = "导入新角色",
        accept_text: str = "生成角色",
    ) -> CharacterImportInfo | None:
        dialog = cls(
            parent,
            preview,
            initial=initial,
            title=title,
            accept_text=accept_text,
        )
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            info = dialog.info()
            if info.name:
                return info
        return None


class CharacterEditDialog(CharacterImportDialog):
    """Edit an existing custom character's metadata.

    Same form and Enter/Esc behavior as the import dialog, with edit-oriented
    default labels.  The skeleton/head art is already baked; this only changes
    the display name, subtitle and posture.
    """

    def __init__(
        self,
        parent=None,
        preview: QPixmap | str | Path | None = None,
        *,
        initial: CharacterImportInfo | None = None,
        title: str = "编辑角色信息",
        accept_text: str = "保存修改",
    ) -> None:
        super().__init__(
            parent,
            preview,
            initial=initial,
            title=title,
            accept_text=accept_text,
        )


#: Short aliases kept for callers/tests that prefer these spellings.
ImportCharacterDialog = CharacterImportDialog
EditCharacterDialog = CharacterEditDialog


class SettingsDialog(QDialog):
    """A two-column settings panel: sections on the left, details on the right."""

    def __init__(self, manager: "PetManager") -> None:
        super().__init__(None)
        self.manager = manager
        self._cards: dict[str, QToolButton] = {}
        self.setWindowTitle("桌角同学 · 设置")
        self.setWindowIcon(manager.common.icon)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        # Resizable dialog: a sensible minimum, no hard-coded width/height
        # lock.  Both the page content and the card grid follow the window.
        self.setMinimumSize(760, 560)
        self.setSizeGripEnabled(True)
        self.resize(1040, 720)
        self._build()
        self._refresh()
        QTimer.singleShot(0, self._relayout_cards)
        screen = None
        active = manager.active_window
        if active is not None:
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.screenAt(active.window_center())
        if screen is None:
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            # Keep the initial window inside the usable screen, but leave the
            # user free to resize it afterwards.
            self.resize(
                min(self.width(), max(self.minimumWidth(), available.width() - 40)),
                min(self.height(), max(self.minimumHeight(), available.height() - 40)),
            )
            self.move(
                available.center().x() - self.width() // 2,
                available.center().y() - self.height() // 2,
            )

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        if hasattr(self, "_cards_grid"):
            self._relayout_cards()

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        # Keep the panel above other applications, even when it is reopened
        # from the tray while a full-screen app is active.
        self.raise_()
        self.activateWindow()
        # The viewport width is only known after the first show; schedule a
        # relayout so a wide initial window immediately fills its first row.
        QTimer.singleShot(0, self._relayout_cards)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Resize
            and getattr(self, "_cards_viewport", None) is obj
            and obj.width() != self._last_card_viewport_width
        ):
            QTimer.singleShot(0, self._relayout_cards)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(16)
        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setMinimumWidth(150)
        self._nav.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for title in ("人物模型", "桌面行为", "关于 / 数据"):
            self._nav.addItem(title)
        self._nav.setCurrentRow(0)
        body.addWidget(self._nav, 0, Qt.AlignmentFlag.AlignTop)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._wrap_page(self._page_model()))
        self._pages.addWidget(self._wrap_page(self._page_behavior()))
        self._pages.addWidget(self._wrap_page(self._page_about()))
        body.addWidget(self._pages, 1)
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        root.addLayout(body, 1)

        root.addLayout(self._build_footer())
        self._connect_actions()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        self._avatar = QLabel()
        self._avatar.setFixedSize(66, 66)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel("桌宠设置")
        title.setObjectName("settingsTitle")
        title.setFont(font(23, QFont.Weight.Black))
        subtitle = QLabel("人物模型 · 桌面行为 · 数据")
        subtitle.setObjectName("muted")
        subtitle.setFont(font(9.5))
        self._current_label = QLabel("当前：")
        self._current_label.setFont(font(10.5, QFont.Weight.DemiBold))
        self._current_label.setWordWrap(True)
        self._status_label = QLabel("")
        self._status_label.setObjectName("muted")
        self._status_label.setFont(font(9))
        self._status_label.setWordWrap(True)
        info.addWidget(title)
        info.addWidget(subtitle)
        info.addSpacing(5)
        info.addWidget(self._current_label)
        info.addWidget(self._status_label)
        header.addLayout(info, 1)
        version = QLabel(f"v{__version__}")
        version.setObjectName("muted")
        version.setFont(font(9))
        version.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        header.addWidget(version, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _wrap_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("settingsPage")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _page_model(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPageBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(10)

        section = QFrame()
        section.setObjectName("settingsSection")
        inner = QVBoxLayout(section)
        inner.setContentsMargins(18, 15, 18, 16)
        inner.setSpacing(8)
        title = QLabel("人物模型")
        title.setFont(font(13, QFont.Weight.Bold))
        inner.addWidget(title)
        hint = QLabel(
            "点一下卡片立刻切换当前桌宠；点「➕ 导入新角色」上传立绘或照片，"
            "填写名称、头衔与姿态后生成新卡片。小满、老王、林林、伊蕾娜是系统初始角色，"
            "只可切换、不可删除；自定义角色卡片右上角可删除，右键还能编辑角色信息。"
        )
        hint.setObjectName("muted")
        hint.setFont(font(9))
        hint.setWordWrap(True)
        inner.addWidget(hint)

        self._card_group = QButtonGroup(self)
        self._card_group.setExclusive(True)
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setObjectName("cardScroll")
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # The grid wraps by itself; no horizontal scrolling and no nested
        # vertical scrollbar.  The whole settings page scrolls when needed.
        self._cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._cards_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._cards_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._cards_scroll.setMinimumHeight(126)
        self._cards_host = QWidget()
        self._cards_host.setObjectName("cardsHost")
        self._cards_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._cards_grid = QGridLayout(self._cards_host)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setHorizontalSpacing(6)
        self._cards_grid.setVerticalSpacing(6)
        # Backwards-compatible alias for callers that referenced the strip layout.
        self._cards_row = self._cards_grid
        self._cards_scroll.setWidget(self._cards_host)
        inner.addWidget(self._cards_scroll)
        self._card_widgets: list[QToolButton] = []
        self._card_columns = 1
        self._last_card_viewport_width = -1
        self._cards_viewport = self._cards_scroll.viewport()
        self._cards_viewport.installEventFilter(self)
        self._import_status = QLabel("")
        self._import_status.setObjectName("muted")
        self._import_status.setFont(font(9))
        self._import_status.setWordWrap(True)
        inner.addWidget(self._import_status)

        self._rebuild_cards()

        divider = QFrame()
        divider.setObjectName("settingsDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(divider)

        size_title = QLabel("显示大小")
        size_title.setFont(font(10.5, QFont.Weight.DemiBold))
        inner.addWidget(size_title)
        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(int(MIN_SCALE * 100), int(MAX_SCALE * 100))
        self._size_slider.setSingleStep(5)
        self._size_slider.setPageStep(10)
        self._size_slider.setMinimumWidth(200)
        self._size_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._size_slider.setToolTip("拖动即可实时调整当前桌宠的大小，每只同学分别记住自己的尺寸。")
        size_row.addWidget(self._size_slider, 1)
        self._size_value = QLabel("40%")
        self._size_value.setFont(font(10, QFont.Weight.DemiBold))
        self._size_value.setMinimumWidth(48)
        size_row.addWidget(self._size_value)
        size_hint = QLabel("默认 40% · 可缩到 20% 当桌角小挂件 · 不影响互动")
        size_hint.setObjectName("muted")
        size_hint.setFont(font(9))
        size_hint.setWordWrap(True)
        size_row.addWidget(size_hint, 0)
        size_row.addStretch(1)
        inner.addLayout(size_row)
        layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _page_behavior(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPageBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        section = QFrame()
        section.setObjectName("settingsSection")
        inner = QVBoxLayout(section)
        inner.setContentsMargins(18, 15, 18, 16)
        inner.setSpacing(7)
        title = QLabel("桌面行为")
        title.setFont(font(13, QFont.Weight.Bold))
        inner.addWidget(title)
        hint = QLabel("下面的开关会立即生效，并自动保存到 data/settings.json。")
        hint.setObjectName("muted")
        hint.setFont(font(9))
        inner.addWidget(hint)

        grid = QGridLayout()
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self._sound_check = QCheckBox("音效")
        self._sound_check.setChecked(self.manager.settings.sound_enabled)
        self._sound_check.setFont(font(10))
        grid.addWidget(self._sound_check, 0, 0)
        sound_hint = QLabel("摸头、投喂、开饭和说话时的提示音")
        sound_hint.setObjectName("muted")
        sound_hint.setFont(font(9))
        grid.addWidget(sound_hint, 0, 1)

        self._watch_check = QCheckBox("状态监听")
        self._watch_check.setChecked(self.manager.settings.auto_watch)
        self._watch_check.setFont(font(10))
        self._watch_check.setEnabled(win32.IS_WINDOWS)
        self._watch_check.setToolTip(
            "只读取前台窗口的程序名和标题，用来吐槽你在卷还是在摸鱼。不会读取内容或上传。"
        )
        grid.addWidget(self._watch_check, 1, 0)
        watch_hint = QLabel("识别前台 IDE / 学习软件 / 游戏 / 视频，吐槽你在卷还是在摸鱼")
        watch_hint.setObjectName("muted")
        watch_hint.setFont(font(9))
        grid.addWidget(watch_hint, 1, 1)

        self._mischief_check = QCheckBox("恶作剧模式")
        self._mischief_check.setChecked(self.manager.settings.mischief_enabled)
        self._mischief_check.setFont(font(10))
        self._mischief_check.setToolTip(
            "怒气满格时允许全屏遮挡、贴便利贴和短暂抢鼠标。抢鼠标最多约 2.35 秒，按 Esc 可中断。"
        )
        grid.addWidget(self._mischief_check, 2, 0)
        mischief_hint = QLabel("暴走时允许全屏遮挡、桌面便利贴和约 2 秒的鼠标牵引（Esc 中断）")
        mischief_hint.setObjectName("muted")
        mischief_hint.setFont(font(9))
        grid.addWidget(mischief_hint, 2, 1)

        max_label = QLabel("同时召唤上限")
        max_label.setFont(font(10))
        grid.addWidget(max_label, 3, 0)
        max_row = QHBoxLayout()
        self._max_spin = QSpinBox()
        self._max_spin.setRange(1, max(1, len(self.manager.characters)))
        self._max_spin.setValue(
            max(1, min(self.manager.settings.max_pets, max(1, len(self.manager.characters))))
        )
        self._max_spin.setSuffix(" 位")
        self._max_spin.setFont(font(10))
        self._max_spin.setToolTip("减少上限不会移除已经在桌面上的同学，只是不允许再召唤新人。")
        max_row.addWidget(self._max_spin)
        max_row.addSpacing(8)
        max_hint = QLabel("减少上限不会赶走已经在桌面上的同学")
        max_hint.setObjectName("muted")
        max_hint.setFont(font(9))
        max_row.addWidget(max_hint)
        max_row.addStretch(1)
        grid.addLayout(max_row, 3, 1)
        inner.addLayout(grid)
        layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _page_about(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPageBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        section = QFrame()
        section.setObjectName("settingsSection")
        inner = QVBoxLayout(section)
        inner.setContentsMargins(18, 15, 18, 16)
        inner.setSpacing(8)
        title = QLabel("关于 / 数据")
        title.setFont(font(13, QFont.Weight.Bold))
        inner.addWidget(title)
        about = QLabel(
            f"桌角同学 Deskling v{__version__}\n"
            "完全离线的小桌宠：透明置顶、可拖拽、可投喂、可召唤多位同学。\n"
            "导入的角色只在本机处理，不会上传。"
        )
        about.setObjectName("muted")
        about.setFont(font(9.5))
        about.setWordWrap(True)
        inner.addWidget(about)

        import_hint = QLabel(
            "导入的新角色会写到 characters/ 下（exe 版为 %APPDATA%\\Deskling\\characters\\）。\n"
            "复杂背景的照片会自动变成白边照片贴纸；想换背景或补表情，直接替换角色文件夹里的 PNG 即可。"
        )
        import_hint.setObjectName("muted")
        import_hint.setFont(font(9))
        import_hint.setWordWrap(True)
        inner.addWidget(import_hint)

        folder = QPushButton("打开人物素材文件夹")
        folder.clicked.connect(self.manager.open_characters_folder)
        inner.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        note = QLabel("所有改动即时生效，并自动保存到 data/settings.json")
        note.setObjectName("muted")
        note.setFont(font(9))
        note.setWordWrap(True)
        footer.addWidget(note)
        footer.addStretch(1)
        done = QPushButton("完成")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        return footer

    def _connect_actions(self) -> None:
        # Connect only after setting initial states so loading does not fire actions.
        self._sound_check.toggled.connect(self.manager.set_sound_enabled)
        self._watch_check.toggled.connect(self.manager.set_auto_watch_enabled)
        self._mischief_check.toggled.connect(self.manager.set_mischief_enabled)
        self._max_spin.valueChanged.connect(self.manager.set_max_pets)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(220)
        self._size_timer.timeout.connect(self._commit_size)
        self._pending_scale_slug = ""
        # Never lose the last slider position when the panel is closed quickly.
        self.finished.connect(lambda _result=0: self._commit_size())

    # ------------------------------------------------------------------
    # cards
    # ------------------------------------------------------------------
    def _rebuild_cards(self) -> None:
        """Rebuild the character grid after an import/delete."""

        while self._cards_grid.count():
            item = self._cards_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if isinstance(widget, QToolButton):
                    self._card_group.removeButton(widget)
                widget.setParent(None)
                widget.deleteLater()
        self._card_widgets.clear()
        self._cards.clear()

        for character in self.manager.characters:
            card = QToolButton()
            card.setObjectName("characterCard")
            card.setCheckable(True)
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setIcon(self.manager.character_icon(character))
            card.setIconSize(QSize(44, 44))
            card.setFont(font(8.6))
            card.setText(f"{character.name}\n{character.subtitle}")
            card.setFixedSize(120, 112)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            lock_note = "系统预置初始角色（不可删除）" if character.is_system else "右键可编辑或删除"
            card.setToolTip(
                f"更换为 {character.name} · {character.subtitle}\n"
                f"点一下就生效；{lock_note}。"
            )
            card.clicked.connect(
                lambda _=False, slug=character.slug: self._choose_character(slug)
            )
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda pos, slug=character.slug, button=card: self._show_card_menu(
                    slug, button.mapToGlobal(pos)
                )
            )
            self._add_card_delete_button(card, character)
            self._card_group.addButton(card)
            self._cards[character.slug] = card
            self._card_widgets.append(card)

        # The import affordance is always the final cell in reading order.
        self._import_button = QToolButton()
        self._import_button.setObjectName("importCard")
        self._import_button.setText("➕\n导入新角色")
        self._import_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._import_button.setFont(font(9, QFont.Weight.DemiBold))
        self._import_button.setFixedSize(120, 112)
        self._import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_button.setToolTip(
            "选一张二次元立绘或人物全身/半身照片，自动去背景并生成新角色卡。"
        )
        self._import_button.clicked.connect(self._on_import_character)
        self._card_widgets.append(self._import_button)

        self._relayout_cards()

        if hasattr(self, "_max_spin"):
            limit = max(1, len(self.manager.characters))
            self._max_spin.setRange(1, limit)
            if self._max_spin.value() > limit:
                self._max_spin.setValue(limit)

    def _relayout_cards(self) -> None:
        """Wrap the character cards into rows for the current window width.

        The grid is deliberately rebuilt on every resize instead of using a
        horizontal strip: widening the settings window must reveal more cards
        per row, while narrowing it wraps them and keeps the import card last.
        """

        widgets = getattr(self, "_card_widgets", None)
        if not hasattr(self, "_cards_grid") or not widgets:
            return
        for widget in widgets:
            self._cards_grid.removeWidget(widget)

        card_w, card_h, gap = 120, 112, 6
        viewport_w = self._cards_scroll.viewport().width()
        if viewport_w <= 0:
            # Before the first show the viewport has no width yet; estimate
            # from the dialog so the initial layout is already multi-column.
            viewport_w = max(card_w, self.width() - 260)
        columns = max(1, (viewport_w + gap) // (card_w + gap))
        for index, widget in enumerate(widgets):
            row, col = divmod(index, columns)
            self._cards_grid.addWidget(widget, row, col)

        rows = (len(widgets) + columns - 1) // columns
        for col in range(self._cards_grid.columnCount()):
            self._cards_grid.setColumnStretch(col, 0)
        self._cards_grid.setColumnStretch(columns, 1)
        height = rows * card_h + max(0, rows - 1) * gap
        self._cards_host.setMinimumHeight(height)
        self._cards_host.setMaximumHeight(height)
        self._cards_scroll.setMinimumHeight(height)
        self._cards_scroll.setMaximumHeight(height + 2)
        self._card_columns = columns
        self._last_card_viewport_width = viewport_w

    def _choose_character(self, slug: str) -> None:
        if slug == (self.manager.active_window.config.slug if self.manager.active_window else ""):
            self._refresh()
            return
        self.manager.switch_character(slug)
        self.raise_()
        self.activateWindow()
        self._refresh()

    # ------------------------------------------------------------------
    # per-card management (edit / delete)
    # ------------------------------------------------------------------
    def _add_card_delete_button(self, card: QToolButton, character) -> None:
        """A tiny delete affordance in the card's top-right corner.

        System classmates show a lock instead; custom characters get a real
        button that asks for confirmation and then removes the folder.
        """

        button = QToolButton(card)
        button.setObjectName("deleteCharacterCard")
        button.setFixedSize(19, 19)
        button.move(max(2, card.width() - 22), 4)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if character.is_system:
            button.setText("🔒")
            button.setEnabled(False)
            button.setToolTip("系统预置初始角色（不可删除）")
        else:
            button.setText("✕")
            button.setToolTip(f"删除「{character.name}」及其角色文件夹。")
            button.clicked.connect(
                lambda _=False, slug=character.slug: self._confirm_delete_character(slug)
            )
        button.raise_()

    def _show_card_menu(self, slug: str, global_pos) -> None:
        character = self.manager.by_slug.get(slug)
        if character is None:
            return
        menu = QMenu(self)
        try:
            if character.is_system:
                locked = menu.addAction("🔒 系统初始角色 · 不可删除")
                locked.setEnabled(False)
            else:
                edit = menu.addAction("编辑角色信息…")
                edit.triggered.connect(lambda _=False, s=slug: self._edit_character(s))
                remove = menu.addAction("删除该角色")
                remove.triggered.connect(
                    lambda _=False, s=slug: self._confirm_delete_character(s)
                )
            menu.exec(global_pos)
        finally:
            menu.deleteLater()

    def _edit_character(self, slug: str) -> None:
        character = self.manager.by_slug.get(slug)
        if character is None:
            return
        if character.is_system:
            self._import_status.setText(f"「{character.name}」是系统初始角色，信息已锁定。")
            return
        initial = CharacterImportInfo(
            name=character.name,
            subtitle=character.subtitle,
            posture=character.posture,
        )
        preview = self.manager.character_icon(character).pixmap(QSize(96, 96))
        info = CharacterEditDialog.ask(
            self,
            preview,
            initial=initial,
            title=f"编辑「{character.name}」",
            accept_text="保存修改",
        )
        if info is None:
            return
        ok, message = self.manager.update_character(
            slug,
            name=info.name,
            subtitle=info.subtitle,
            posture=info.posture,
        )
        if ok:
            self._rebuild_cards()
            self._refresh()
        self._import_status.setText(message)

    def _confirm_delete_character(self, slug: str) -> None:
        character = self.manager.by_slug.get(slug)
        if character is None:
            return
        if character.is_system:
            self._import_status.setText(f"「{character.name}」是系统初始角色，不能删除。")
            return
        answer = QMessageBox.question(
            self,
            "删除角色",
            f"确定要删除「{character.name}」吗？\n\n"
            f"角色文件夹 {character.folder.name}/ 和它的全部配置都会被清理，"
            "此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, message = self.manager.delete_character(slug)
        if ok:
            self._rebuild_cards()
            self._refresh()
        self._import_status.setText(message)

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        active = self.manager.active_window
        if active is not None:
            icon = self.manager.character_icon(active.config)
            self._avatar.setPixmap(icon.pixmap(QSize(60, 60)))
            self._current_label.setText(f"当前：{active.config.name} · {active.config.subtitle}")
            self._status_label.setText(
                f"{active.model.stat_line()} · 桌面上共 {len(self.manager.windows)} 位"
            )
            active_slug = active.config.slug
        else:
            self._avatar.setPixmap(self.manager.common.icon.pixmap(QSize(60, 60)))
            self._current_label.setText("桌面上暂无纸片人")
            self._status_label.setText("点一张人物卡，就能召唤一位同学。")
            active_slug = ""
        self._card_group.setExclusive(False)
        for slug, card in self._cards.items():
            card.setChecked(slug == active_slug)
        self._card_group.setExclusive(True)
        self._refresh_size(active)

    def _refresh_size(self, active) -> None:
        enabled = active is not None
        self._size_slider.setEnabled(enabled)
        self._size_value.setEnabled(enabled)
        self._size_slider.blockSignals(True)
        if active is not None:
            percent = int(round(self.manager.effective_scale(active.config) * 100))
            self._size_slider.setValue(
                max(self._size_slider.minimum(), min(self._size_slider.maximum(), percent))
            )
            self._size_value.setText(f"{percent}%")
        else:
            self._size_value.setText("—")
        self._size_slider.blockSignals(False)

    def _on_size_changed(self, value: int) -> None:
        self._size_value.setText(f"{value}%")
        active = self.manager.active_window
        self._pending_scale_slug = active.config.slug if active is not None else ""
        if active is not None:
            active.set_scale(value / 100.0)
        self._size_timer.start()

    def _commit_size(self) -> None:
        slug = self._pending_scale_slug
        if not slug:
            return
        self.manager.set_character_scale(slug, self._size_slider.value() / 100.0)

    def _ask_character_info(self, image_path: Path) -> CharacterImportInfo | None:
        """Popup metadata form for a freshly selected image.

        Kept as its own method so headless tests can stub the modal dialog
        without touching the image picker or the packager.
        """

        preview = QPixmap(str(image_path))
        return CharacterImportDialog.ask(self, preview, title="导入新角色")

    def _on_import_character(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入新角色",
            "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*)",
        )
        if not path:
            return
        info = self._ask_character_info(Path(path))
        if info is None:
            return
        ok, message, character = self.manager.import_character(
            Path(path),
            name=info.name,
            subtitle=info.subtitle,
            posture=info.posture,
        )
        if ok:
            self._rebuild_cards()
            self._refresh()
        self._import_status.setText(message)
        if ok and character is not None:
            self.raise_()
            self.activateWindow()
