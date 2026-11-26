"""Windows desktop GUI — PySide6 + embedded PyVista/VTK renderer."""
from __future__ import annotations

import os
os.environ.setdefault('QT_API', 'pyside6')

from pathlib import Path

import numpy as np
import pyvista as pv
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from PySide6.QtCore import QSignalBlocker, Qt, QThread, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from pyvistaqt import QtInteractor

from .core import (
    BoxSelection, CloudDocument, CropCancelled, CropError, box_corners, box_kind, check_cancel,
    export_crop, load_cloud,
)
from .brush import BrushOperation, BrushSelection
from .brush_ui import BrushOverlay
from .history import VIEW_SELECTIONS, SelectionHistory, load_history_json, save_history_json
from .las import LasDocument
from .polygon import PolygonOperation, PolygonSelection
from .polygon_ui import PolygonOverlay, capture_projection

BG = '#F5F5F4'
DARK = '#191919'
TERRA = '#AA422F'
OPEN_FILTER = 'Point clouds (*.ply *.las *.laz);;PLY (*.ply);;LAS (*.las);;LAZ (*.laz)'
SAVE_FILTERS = {'.las': 'LAS (*.las)', '.laz': 'LAZ (*.laz)', '.ply': 'Binary PLY (*.ply)'}


class LoadTask(QThread):
    success = Signal(object)
    failure = Signal(str)
    progress_value = Signal(int)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            doc = load_cloud(self.path, self.progress_value.emit)
            if isinstance(doc, LasDocument):
                coords, attrs = doc.preview(progress=self.progress_value.emit)
            else:
                coords, attrs = doc.preview()
            self.success.emit((doc, coords, attrs))
        except Exception as e:
            self.failure.emit(str(e))


class ExportTask(QThread):
    success = Signal(object)
    failure = Signal(str)
    progress_value = Signal(int)
    cancelled = Signal()

    def __init__(self, doc, selection, output, allow_drop, overwrite, history):
        super().__init__()
        self.doc, self.selection, self.output = doc, selection, output
        self.allow_drop, self.overwrite = allow_drop, overwrite
        self.history = history

    def run(self):
        try:
            result = export_crop(
                self.doc, self.selection, self.output,
                allow_drop_elements=self.allow_drop, overwrite=self.overwrite,
                selection_history=self.history, progress=self.progress_value.emit,
                cancelled=self.isInterruptionRequested,
            )
            self.success.emit(result)
        except CropCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failure.emit(str(e))


class BrushPreviewTask(QThread):
    success = Signal(object)
    failure = Signal(str)
    progress_value = Signal(int)
    cancelled = Signal()

    def __init__(self, xyz, selection, operation=None, before_mask=None):
        super().__init__()
        self.xyz, self.selection = xyz, selection
        self.operation, self.before_mask = operation, before_mask

    def run(self):
        try:
            mask = np.empty(len(self.xyz), dtype=bool)
            changed = None
            if self.operation is not None:
                changed = np.empty_like(mask)
                base = self.selection
                if isinstance(base, VIEW_SELECTIONS):
                    plan = BrushSelection(base.initial_box, base.operations + (self.operation,))
                else:
                    plan = BrushSelection(base, (self.operation,))
            else:
                plan = self.selection
            for start in range(0, len(mask), 40_000):
                check_cancel(self.isInterruptionRequested)
                section = slice(start, start + 40_000)
                xyz = self.xyz[section]
                mask[section] = plan.mask(xyz)
                if changed is not None:
                    before = (self.before_mask[section] if self.before_mask is not None
                              else self.selection.mask(xyz))
                    changed[section] = before ^ mask[section]
                self.progress_value.emit(100 * min(start + len(xyz), len(mask)) // len(mask))
            check_cancel(self.isInterruptionRequested)
            self.success.emit((mask, changed, self.operation))
        except CropCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failure.emit(str(exc))


class SaveSelectionTask(QThread):
    success = Signal(object)
    failure = Signal(str)
    progress_value = Signal(int)

    def __init__(self, path, doc, roi, snapshot, full_count):
        super().__init__()
        self.args = (path, doc, roi, snapshot, full_count)

    def run(self):
        try:
            self.success.emit(save_history_json(*self.args))
        except Exception as exc:
            self.failure.emit(str(exc))


def button(label: str, primary=False):
    b = QPushButton(label)
    if primary:
        b.setProperty('primary', True)
    b.setMinimumHeight(36)
    return b


class CropperWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GS-PrepTools | LiDAR Point Cloud Object Cropper')
        self.resize(1460, 830)
        self.doc: CloudDocument | LasDocument | None = None
        self.coords: np.ndarray | None = None
        self.attrs: dict = {}
        self.roi: BoxSelection | PolygonSelection | BrushSelection | None = None
        self._brush_draft = None
        self._brush_mask = None
        self._brush_mask_roi = None
        self.history: SelectionHistory | None = None
        self._placing_box = False
        self._widget_reference: BoxSelection | None = None
        self.box_widget = None
        self.preview_active = False
        self.roi_locked = False
        self.task = None
        self.busy = False
        self._build_ui()
        self._style()
        self.plotter.set_background('#141A1E')
        self.plotter.add_axes()
        self.statusBar().showMessage('Buka PLY, LAS, atau LAZ untuk memulai.')

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName('header')
        h = QHBoxLayout(header)
        logo = QLabel('GS  /  POINT CLOUD OBJECT CROPPER')
        logo.setObjectName('brand')
        h.addWidget(logo)
        h.addStretch()
        h.addWidget(QLabel('LiDAR Geometry Workspace  •  Local / Offline'))
        outer.addWidget(header)
        content = QHBoxLayout()
        content.setContentsMargins(12, 12, 12, 8)
        content.setSpacing(12)
        outer.addLayout(content, 1)

        left = QWidget()
        left.setObjectName('panel')
        left.setFixedWidth(292)
        l = QVBoxLayout(left)
        l.setSpacing(12)
        l.addWidget(self._heading('01  /  SOURCE FILE'))
        self.open_btn = button('Open Point Cloud…', primary=True)
        self.open_btn.clicked.connect(self.open_file)
        l.addWidget(self.open_btn)
        self.file_label = QLabel('Belum ada file dipilih.')
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(self.file_label)
        l.addWidget(self._heading('02  /  DATASET INFO'))
        self.meta_label = QLabel('—')
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(self.meta_label)
        l.addWidget(self._heading('03  /  VISUAL SETTINGS'))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.color_combo = QComboBox()
        self.color_combo.addItems(['RGB', 'Elevation', 'Intensity', 'Monochrome'])
        self.color_combo.currentTextChanged.connect(self._redraw)
        form.addRow('Color', self.color_combo)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 15)
        self.size_spin.setValue(3)
        self.size_spin.valueChanged.connect(self._redraw)
        form.addRow('Point size', self.size_spin)
        self.projection_combo = QComboBox()
        self.projection_combo.addItems(['Perspective', 'Orthographic'])
        self.projection_combo.currentIndexChanged.connect(self._change_projection)
        form.addRow('Projection', self.projection_combo)
        l.addLayout(form)
        l.addWidget(self._heading('04  /  CROP MODE'))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['Oriented Bounding Box (edit & rotate)',
                                  'Axis-Aligned Bounding Box (no rotation)'])
        self.mode_combo.currentIndexChanged.connect(lambda _: self._new_box('box'))
        l.addWidget(self.mode_combo)
        self.reset_btn = button('Reset / New Box')
        self.reset_btn.clicked.connect(self.reset_selection)
        l.addWidget(self.reset_btn)
        self.load_roi_btn = button('Load Saved Selection…')
        self.load_roi_btn.clicked.connect(self.load_roi)
        l.addWidget(self.load_roi_btn)
        self.save_roi_btn = button('Save Selection…')
        self.save_roi_btn.clicked.connect(self.save_roi)
        l.addWidget(self.save_roi_btn)
        l.addStretch(1)
        notice = QLabel('Original file is never modified.\n'
                        'PLY faces/other elements: vertex-only export with confirmation.\n'
                        'Gaussian PLY ≠ LiDAR reference geometry.')
        notice.setObjectName('notice')
        notice.setWordWrap(True)
        l.addWidget(notice)
        content.addWidget(left)

        middle = QWidget()
        m = QVBoxLayout(middle)
        m.setContentsMargins(0, 0, 0, 0)
        m.setSpacing(8)
        topline = QHBoxLayout()
        topline.addWidget(self._heading('INTERACTIVE 3D VIEWPORT'))
        topline.addStretch()
        for text, direction in [('Front', 'front'), ('Back', 'back'),
                                ('Left', 'left'), ('Right', 'right'),
                                ('Top', 'top'), ('Bottom', 'bottom'), ('Iso', 'iso')]:
            b = button(text)
            b.setMinimumHeight(27)
            b.clicked.connect(lambda checked=False, d=direction: self.set_view(d))
            topline.addWidget(b)
        m.addLayout(topline)
        self.plotter = QtInteractor(middle)
        m.addWidget(self.plotter.interactor, 1)
        self.polygon_overlay = PolygonOverlay(self.plotter.interactor)
        self.polygon_overlay.vertices_changed.connect(self._polygon_vertices_changed)
        self.polygon_overlay.interrupted.connect(self._polygon_interrupted)
        self.brush_overlay = BrushOverlay(self.plotter.interactor)
        self.brush_overlay.stroke_started.connect(self._update_buttons)
        self.brush_overlay.stroke_ready.connect(self._preview_stroke)
        self.brush_overlay.stroke_too_long.connect(self._brush_too_long)
        self.brush_overlay.interrupted.connect(self._brush_interrupted)
        content.addWidget(middle, 1)

        right = QWidget()
        right.setObjectName('panel')
        right.setFixedWidth(292)
        r = QVBoxLayout(right)
        r.addWidget(self._heading('CROP STATUS'))
        history_row = QHBoxLayout()
        self.undo_btn, self.redo_btn = button('Undo'), button('Redo')
        self.undo_btn.clicked.connect(self.undo_selection)
        self.redo_btn.clicked.connect(self.redo_selection)
        self.undo_btn.setToolTip('Undo the last selection change (Ctrl+Z)')
        self.redo_btn.setToolTip('Redo the next selection change (Ctrl+Y)')
        history_row.addWidget(self.undo_btn)
        history_row.addWidget(self.redo_btn)
        r.addLayout(history_row)
        self.history_label = QLabel('No selection history')
        r.addWidget(self.history_label)
        self.undo_shortcut = QShortcut('Ctrl+Z', self)
        self.redo_shortcut = QShortcut('Ctrl+Y', self)
        self.undo_shortcut.activated.connect(self.undo_selection)
        self.redo_shortcut.activated.connect(self.redo_selection)
        self.stat_label = QLabel('Buka PLY, atur kotak, lalu klik Preview Crop.')
        self.stat_label.setWordWrap(True)
        self.stat_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        r.addWidget(self.stat_label)
        self.preview_btn = button('Preview Crop', primary=True)
        self.preview_btn.clicked.connect(self.preview_crop)
        r.addWidget(self.preview_btn)
        self.show_original = QCheckBox('Show original (faded)')
        self.show_original.setChecked(True)
        self.show_original.toggled.connect(self._redraw)
        r.addWidget(self.show_original)
        r.addWidget(self._heading('POLYGON SELECTION'))
        self.draw_polygon_btn = button('Draw Polygon')
        self.draw_polygon_btn.clicked.connect(self.begin_polygon)
        r.addWidget(self.draw_polygon_btn)
        self.polygon_controls = QWidget()
        polygon_form = QFormLayout(self.polygon_controls)
        polygon_form.setContentsMargins(0, 0, 0, 0)
        self.use_box = QCheckBox('Use current box as starting ROI')
        self.use_box.setChecked(True)
        policy = self.use_box.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.use_box.setSizePolicy(policy)
        polygon_form.addRow(self.use_box)
        self.polygon_operation = QComboBox()
        self.polygon_operation.addItem('Keep Selected', 'keep')
        self.polygon_operation.addItem('Remove Selected', 'remove')
        polygon_form.addRow('Operation', self.polygon_operation)
        self.depth_near, self.depth_far = QDoubleSpinBox(), QDoubleSpinBox()
        for label, spin in (('Depth near', self.depth_near), ('Depth far', self.depth_far)):
            spin.setDecimals(8)
            spin.setRange(0, 1e15)
            spin.setToolTip('Depth along the camera axis in source units, including occluded points.')
            polygon_form.addRow(label, spin)
        actions = QHBoxLayout()
        self.confirm_polygon_btn = button('Confirm Polygon')
        self.confirm_polygon_btn.clicked.connect(self.confirm_polygon)
        cancel = button('Cancel')
        cancel.clicked.connect(self.cancel_polygon)
        actions.addWidget(cancel)
        actions.addWidget(self.confirm_polygon_btn)
        polygon_form.addRow(actions)
        policy = self.polygon_controls.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.polygon_controls.setSizePolicy(policy)
        self.polygon_controls.hide()
        r.addWidget(self.polygon_controls)
        self.cancel_polygon_shortcut = QShortcut('Escape', self)
        self.cancel_polygon_shortcut.activated.connect(self.cancel_polygon)
        self.cancel_polygon_shortcut.setEnabled(False)
        self.brush_toggle = button('Enable Brush')
        self.brush_toggle.setCheckable(True)
        self.brush_toggle.toggled.connect(self._toggle_brush)
        r.addWidget(self.brush_toggle)
        self.brush_controls = QWidget()
        brush_form = QFormLayout(self.brush_controls)
        brush_form.setContentsMargins(0, 0, 0, 0)
        self.brush_mode = QComboBox()
        self.brush_mode.addItem('Remove Brush', 'brush_remove')
        self.brush_mode.addItem('Restore Brush', 'brush_restore')
        brush_form.addRow('Mode', self.brush_mode)
        self.brush_radius = QSpinBox()
        self.brush_radius.setRange(1, 400)
        self.brush_radius.setValue(24)
        self.brush_radius.setSuffix(' px')
        self.brush_radius.setToolTip('Radius dalam piksel logis layar.')
        brush_form.addRow('Radius', self.brush_radius)
        self.brush_near, self.brush_far = QDoubleSpinBox(), QDoubleSpinBox()
        for label, spin in (('Depth near', self.brush_near), ('Depth far', self.brush_far)):
            spin.setDecimals(8)
            spin.setRange(0, 1e15)
            brush_form.addRow(label, spin)
        hint = QLabel('Restore mengembalikan titik yang dihapus brush dan masih lolos ROI awal serta poligon.')
        hint.setWordWrap(True)
        brush_form.addRow(hint)
        brush_actions = QHBoxLayout()
        self.cancel_stroke_btn, self.confirm_stroke_btn = button('Cancel Stroke'), button('Confirm Stroke')
        self.cancel_stroke_btn.clicked.connect(self.cancel_brush)
        self.confirm_stroke_btn.clicked.connect(self.confirm_brush)
        brush_actions.addWidget(self.cancel_stroke_btn)
        brush_actions.addWidget(self.confirm_stroke_btn)
        brush_form.addRow(brush_actions)
        self.brush_radius.valueChanged.connect(self._brush_style)
        self.brush_mode.currentIndexChanged.connect(self._brush_style)
        self.cancel_brush_shortcut = QShortcut('Escape', self)
        self.cancel_brush_shortcut.activated.connect(self.cancel_brush)
        self.brush_controls.hide()
        r.addWidget(self.brush_controls)
        r.addWidget(self._heading('EXPORT FULL RESOLUTION'))
        warning = QLabel('Preview memakai subset titik. Export menerapkan ROI '
                         'ke seluruh vertex asli, tanpa normalisasi, smoothing, atau denoising.')
        warning.setWordWrap(True)
        r.addWidget(warning)
        self.export_btn = button('Export Crop + JSON', primary=True)
        self.export_btn.clicked.connect(self.export)
        r.addWidget(self.export_btn)
        r.addStretch()
        right_scroll = QScrollArea()
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setFixedWidth(309)
        right_scroll.setWidget(right)
        content.addWidget(right_scroll)

        footer = QFrame()
        footer.setObjectName('footer')
        f = QHBoxLayout(footer)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        f.addWidget(self.progress, 1)
        self.progress_label = QLabel('Ready')
        f.addWidget(self.progress_label)
        self.cancel_export_btn = button('Cancel Export')
        self.cancel_export_btn.clicked.connect(self.cancel_export)
        f.addWidget(self.cancel_export_btn)
        outer.addWidget(footer)
        self._update_buttons()

    @staticmethod
    def _heading(txt):
        l = QLabel(txt)
        l.setObjectName('sectionHead')
        return l

    def _style(self):
        self.setStyleSheet(f'''
            QMainWindow, QWidget {{ background: {BG}; color: {DARK}; font-family: 'Segoe UI'; font-size: 12px; }}
            QFrame#header {{ background: #191919; min-height: 48px; }}
            QFrame#header QLabel {{ color: #EDEDED; background: transparent; }}
            QLabel#brand {{ font-size: 14px; font-weight: 700; letter-spacing: 1px; }}
            QWidget#panel {{ background: white; border: 1px solid #E4E4E2; border-radius: 9px; }}
            QLabel#sectionHead {{ color: {TERRA}; font-weight: 700; font-size: 11px; margin-top: 7px; }}
            QPushButton {{ border: 1px solid #D5D5D2; background: white; padding: 4px 8px; border-radius: 5px; }}
            QPushButton:hover {{ background: #F7F1EF; border-color: #BB8275; }}
            QPushButton[primary='true'] {{ color: white; background: {TERRA}; border: 1px solid {TERRA}; font-weight: 600; }}
            QPushButton[primary='true']:hover {{ background: #8F3021; }}
            QPushButton:disabled {{ color: #989898; background: #EDEDED; border-color: #E0E0E0; }}
            QComboBox, QSpinBox {{ padding: 5px; border: 1px solid #D9D9D6; border-radius: 4px; background: white; }}
            QLabel#notice {{ font-size: 11px; color: #6F6B67; background: #F8F5F2; padding: 8px; border-radius: 5px; }}
            QFrame#footer {{ background: #FFFFFF; border-top: 1px solid #E2E2DF; }}
            QProgressBar {{ height: 13px; text-align: center; background: #EEE; border: 1px solid #DDD; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {TERRA}; border-radius: 3px; }}
        ''')

    def _set_busy(self, value, text=''):
        self.busy = value
        self.plotter.interactor.setEnabled(not value)
        self.progress_label.setText(text or ('Working…' if value else 'Ready'))
        self._update_buttons()

    def _start_task(self, task, on_success):
        self.task = task
        task.progress_value.connect(self.progress.setValue)
        task.success.connect(on_success)
        task.failure.connect(self._task_failed)
        if isinstance(task, (ExportTask, BrushPreviewTask)):
            task.cancelled.connect(self._task_cancelled)
        task.finished.connect(self._task_finished)
        task.finished.connect(task.deleteLater)
        task.start()
        self._update_buttons()

    def _task_finished(self):
        if self.task is self.sender():
            self.task = None
            self._update_buttons()

    def _drawing(self):
        return self.polygon_overlay.camera is not None or self.brush_overlay.camera is not None

    def _update_buttons(self):
        has = self.doc is not None
        brush = self.brush_overlay.camera is not None
        available = not self.busy and not self._drawing()
        self.open_btn.setEnabled(available)
        self.reset_btn.setEnabled(has and available)
        self.load_roi_btn.setEnabled(has and available)
        self.save_roi_btn.setEnabled(self.history is not None and available)
        self.mode_combo.setEnabled(has and available and not isinstance(self.roi, VIEW_SELECTIONS))
        self.projection_combo.setEnabled(has and available)
        self.draw_polygon_btn.setEnabled(has and available)
        self.brush_toggle.setEnabled(has and (available or brush))
        self.cancel_stroke_btn.setEnabled(brush)
        self.cancel_brush_shortcut.setEnabled(brush)
        self.confirm_stroke_btn.setEnabled(brush and not self.busy and self._brush_draft is not None)
        editable = brush and not self.brush_overlay.drawing and not self.brush_overlay.finished
        for control in (self.brush_mode, self.brush_radius, self.brush_near, self.brush_far):
            control.setEnabled(editable)
        self.cancel_export_btn.setVisible(self.busy and isinstance(self.task, ExportTask))
        self.cancel_export_btn.setEnabled(self.progress_label.text() != 'Cancelling export…')
        self.preview_btn.setEnabled(has and self.roi is not None and available)
        self.export_btn.setEnabled(has and self.roi is not None and self.preview_active and available)
        can_undo = available and self.history is not None and self.history.can_undo
        can_redo = available and self.history is not None and self.history.can_redo
        self.undo_btn.setEnabled(can_undo)
        self.undo_shortcut.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
        self.redo_shortcut.setEnabled(can_redo)
        if self.history is None:
            self.history_label.setText('No selection history')
        else:
            step = self.history.current
            mode = ('Brush' if isinstance(self.roi, BrushSelection) else
                    'Polygon' if isinstance(self.roi, PolygonSelection) else step.box_mode)
            self.history_label.setText(f'History {self.history.position + 1}/{self.history.length} · {mode}')

    def _change_projection(self, index):
        if not self._drawing():
            self.plotter.camera.parallel_projection = bool(index)
            self.plotter.render()

    def begin_polygon(self):
        if self.doc is None or self.busy or self._drawing():
            return
        self.polygon_controls.show()
        # Apply pending layout changes before measuring the rendered viewport.
        self.centralWidget().layout().activate()
        self.plotter.render()
        camera = capture_projection(self.plotter)
        near, far = camera.clipping_range
        self.depth_near.setValue(max(0, near))
        self.depth_far.setValue(far)
        self.use_box.setVisible(not isinstance(self.roi, VIEW_SELECTIONS))
        self.use_box.setEnabled(isinstance(self.roi, BoxSelection))
        self.polygon_overlay.begin(camera)
        self.cancel_polygon_shortcut.setEnabled(True)
        self._update_buttons()

    def _polygon_vertices_changed(self, count):
        self.confirm_polygon_btn.setEnabled(count >= 3)
        self.statusBar().showMessage(
            f'{count} titik poligon. Klik kiri menambah, Backspace menghapus, Esc membatalkan.'
        )

    def _polygon_interrupted(self):
        self.cancel_polygon('Ukuran atau DPI viewport berubah. Gambar kembali poligon pada tampilan baru.')

    def cancel_polygon(self, message=''):
        if self.polygon_overlay.camera is None:
            return
        self.polygon_overlay.finish()
        self.polygon_controls.hide()
        self.cancel_polygon_shortcut.setEnabled(False)
        self._update_buttons()
        self.statusBar().showMessage(message or 'Draft poligon dibatalkan.')

    def confirm_polygon(self):
        overlay = self.polygon_overlay
        if overlay.camera is None:
            return
        try:
            operation = PolygonOperation(
                self.polygon_operation.currentData(), tuple(overlay.vertices), overlay.camera,
                (self.depth_near.value(), self.depth_far.value()),
            )
        except CropError as exc:
            self.statusBar().showMessage(str(exc))
            return
        if self.history is None:
            return
        self.history.apply_polygon(operation, use_box=self.use_box.isChecked())
        self.roi = self.history.selection
        self._clear_box_display()
        self.roi_locked = True
        self.cancel_polygon('Poligon diterapkan. Ubah sudut kamera untuk membuat seleksi berikutnya.')
        self.preview_crop()

    def _brush_style(self):
        self.brush_overlay.radius = self.brush_radius.value()
        self.brush_overlay.restore = self.brush_mode.currentData() == 'brush_restore'
        self.brush_overlay.update()

    def _toggle_brush(self, enabled):
        if not enabled:
            self.cancel_brush()
            return
        if self.busy or self.roi is None or self._drawing():
            with QSignalBlocker(self.brush_toggle):
                self.brush_toggle.setChecked(False)
            return
        self.brush_controls.show()
        self.centralWidget().layout().activate()
        self.plotter.render()
        camera = capture_projection(self.plotter)
        near, far = camera.clipping_range
        self.brush_near.setValue(max(0., near))
        self.brush_far.setValue(far)
        self._brush_style()
        self.brush_overlay.begin(camera)
        self.brush_toggle.setText('Disable Brush')
        self.statusBar().showMessage('Atur radius dan depth, lalu klik dan geser untuk satu sapuan.')
        self._update_buttons()

    def _preview_stroke(self):
        overlay = self.brush_overlay
        try:
            operation = BrushOperation(self.brush_mode.currentData(), tuple(overlay.points),
                                       self.brush_radius.value(), overlay.camera,
                                       (self.brush_near.value(), self.brush_far.value()))
        except CropError as exc:
            self.cancel_brush()
            self.statusBar().showMessage(str(exc))
            return
        self.progress.setValue(0)
        self._set_busy(True, 'Calculating stroke preview…')
        before = self._brush_mask if self.roi is self._brush_mask_roi else None
        task = BrushPreviewTask(self.coords, self.roi, operation, before)
        self._start_task(task, self._stroke_preview_ok)

    def _stroke_preview_ok(self, result):
        self._set_busy(False, 'Preview ready')
        if self.brush_overlay.camera is None:
            return
        mask, changed, operation = result
        count = int(changed.sum())
        self._brush_draft = (operation, mask, count)
        self.plotter.remove_actor('brush_hit', render=False)
        if count:
            color = '#58d9a6' if operation.kind == 'brush_restore' else '#ff856e'
            self.plotter.add_mesh(pv.PolyData(self.coords[changed]), name='brush_hit', style='points',
                                  point_size=max(5, self.size_spin.value()), color=color,
                                  reset_camera=False, lighting=False)
        action = 'dipulihkan' if operation.kind == 'brush_restore' else 'dihapus'
        self.statusBar().showMessage(f'{count:,} titik sampel akan {action}. Confirm atau Cancel Stroke.')
        self._update_buttons()

    def _finish_brush(self):
        self.brush_overlay.finish()
        self._brush_draft = None
        self.brush_controls.hide()
        self.brush_toggle.setText('Enable Brush')
        with QSignalBlocker(self.brush_toggle):
            self.brush_toggle.setChecked(False)
        self.plotter.remove_actor('brush_hit', render=False)
        self._update_buttons()

    def cancel_brush(self):
        if self.brush_overlay.camera is None:
            return
        if self.busy and isinstance(self.task, BrushPreviewTask):
            self.task.requestInterruption()
        self._finish_brush()
        self.plotter.render()
        self.statusBar().showMessage('Sapuan dibatalkan.')

    def _brush_too_long(self):
        self.cancel_brush()
        self.statusBar().showMessage('Sapuan terlalu panjang. Gunakan beberapa sapuan yang lebih pendek.')

    def _brush_interrupted(self):
        self.cancel_brush()
        self.statusBar().showMessage('Viewport berubah. Aktifkan brush untuk menggambar ulang sapuan.')

    def confirm_brush(self):
        if self.busy or self._brush_draft is None:
            return
        operation, mask, count = self._brush_draft
        self.history.apply_brush(operation)
        self.roi = self.history.selection
        self.roi_locked = True
        self._clear_box_display()
        self._finish_brush()
        self._update_preview(allow_empty=True, chosen=mask)
        action = 'dipulihkan' if operation.kind == 'brush_restore' else 'dihapus'
        self.stat_label.setText(f'{count:,} titik sampel {action}.\n' + self.stat_label.text())
        self.statusBar().showMessage('Sapuan diterapkan. Kamera dapat digerakkan kembali.')

    def _task_cancelled(self):
        self._set_busy(False, 'Cancelled')
        self.progress.setValue(0)
        self.statusBar().showMessage('Operasi dibatalkan.')

    def cancel_export(self):
        if self.busy and isinstance(self.task, ExportTask):
            self.task.requestInterruption()
            self.progress_label.setText('Cancelling export…')
            self.cancel_export_btn.setEnabled(False)

    def _task_failed(self, message):
        if self.brush_overlay.camera is not None:
            self._finish_brush()
        self._set_busy(False, 'Error')
        self.progress.setValue(0)
        QMessageBox.critical(self, 'Operation failed', message)
        self.statusBar().showMessage('Error: ' + message)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open point cloud', '', OPEN_FILTER)
        if not path:
            return
        self._set_busy(True, 'Loading / validating point cloud…')
        self.progress.setValue(0)
        self._start_task(LoadTask(path), self._load_ok)

    def _load_ok(self, data):
        self.doc, self.coords, self.attrs = data
        self.history = None
        self.roi = None
        self._brush_mask = self._brush_mask_roi = None
        self.preview_active = False
        self.roi_locked = False
        self.file_label.setText(str(self.doc.path))
        summary = (
            f'Type: {self.doc.classification}\n'
            f'Vertices: {self.doc.count:,}\n'
            f'File size: {self.doc.file_size / (1024 ** 2):,.2f} MB\n'
            f'Preview vertices: {len(self.coords):,}\n'
            f'Attributes: {", ".join(self.doc.names)}\n'
            f'Additional elements: {", ".join(self.doc.other_elements) or "none"}'
        )
        if isinstance(self.doc, LasDocument):
            data = self.doc.metadata()
            rgb_label = {'available': 'Available', 'all_zero': 'All values zero',
                         'absent': 'Absent'}[data['rgb']]
            crs = data['spatial'].get('crs_name') or 'Unspecified'
            units = ', '.join(data['spatial']['axis_units']) or 'Unspecified'
            summary += (f'\nScale: {data["scales"]}\nOffset: {data["offsets"]}'
                        f'\nRGB: {rgb_label}\nCRS: {crs}\nAxis units: {units}')
            self.color_combo.setCurrentText(
                'RGB' if self._las_preview_has_rgb() else self._las_fallback_color()
            )
        else:
            self.color_combo.setCurrentText('RGB')
        self.meta_label.setText(summary)
        self.plotter.clear()
        self.plotter.add_axes()
        self._add_points(self.coords, self.attrs, 'original', 1.0)
        self.plotter.reset_camera()
        self._set_busy(False, 'Loaded')
        self._new_box('initial')
        self.progress.setValue(100)
        if self.doc.is_gaussian:
            QMessageBox.warning(self, 'Gaussian attributes detected',
                'PLY memiliki atribut Gaussian Splatting. Crop vertex/gaussian dapat dilakukan, '
                'tetapi hasilnya BUKAN ground truth LiDAR. Pastikan jenis file sumber benar.')
        if self.doc.other_elements:
            QMessageBox.information(self, 'Non-vertex elements detected',
                'File memiliki element tambahan (misalnya faces). MVP hanya mengekspor '
                'vertex yang terpilih; faces/elemen lain TIDAK dipertahankan. '
                'Konfirmasi akan diminta saat ekspor.')
        self.statusBar().showMessage('Point cloud loaded. Atur kotak, lalu klik Preview Crop.')

    def _vtk_box_planes(self, widget):
        planes = vtk.vtkPlanes()
        widget.GetPlanes(planes)
        points = vtk_to_numpy(planes.GetPoints().GetData()).copy()
        normals = vtk_to_numpy(planes.GetNormals()).copy()
        return BoxSelection.from_planes(points, normals)

    def _box_changed(self, vtk_planes):
        if self._placing_box or self.history is None or self.busy or self._drawing():
            return
        try:
            points = vtk_to_numpy(vtk_planes.GetPoints().GetData()).copy()
            normals = vtk_to_numpy(vtk_planes.GetNormals()).copy()
            roi = BoxSelection.from_planes(points, normals)
        except (CropError, ValueError) as exc:
            self._restore_selection()
            self.statusBar().showMessage(f'Invalid ROI: {exc}')
            return
        reference = self._widget_reference
        if (reference is not None and np.array_equal(roi.origins, reference.origins)
                and np.array_equal(roi.normals, reference.normals)):
            return
        self.history.set_box(roi, self._box_mode())
        self.roi = roi
        self._widget_reference = roi
        self.roi_locked = False
        had_preview = self.preview_active
        self.preview_active = False
        self.stat_label.setText('Box changed. Klik Preview Crop untuk memperbarui hasil.')
        if had_preview:
            self._redraw()
        self._update_buttons()

    def reset_selection(self):
        self._new_box('reset')

    def _box_mode(self):
        return 'OBB' if self.mode_combo.currentIndex() == 0 else 'AABB'

    def _clear_box_display(self):
        self.plotter.clear_box_widgets()
        self.box_widget = None
        self._widget_reference = None
        self.plotter.remove_actor('saved_roi', render=False)

    def _place_box(self, bounds):
        self._placing_box = True
        try:
            self.box_widget = self.plotter.add_box_widget(
                callback=self._box_changed, bounds=bounds, factor=1.0,
                use_planes=True, pass_widget=False, color='#E7A58C',
                rotation_enabled=(self._box_mode() == 'OBB'),
                outline_translation=True, interaction_event='end',
            )
        finally:
            self._placing_box = False

    def _new_box(self, action):
        if self.doc is None or self.busy or self._drawing():
            return
        self._clear_box_display()
        self.preview_active = False
        self.roi_locked = False
        bounds = list(self.doc.bounds)
        # Prevent zero-thickness box in planar laser scans.
        for i in (0, 2, 4):
            if bounds[i+1] - bounds[i] < 1e-6:
                bounds[i+1] = bounds[i] + 0.001
        self._place_box(bounds)
        self.roi = self._vtk_box_planes(self.box_widget)
        self._widget_reference = self.roi
        if action == 'initial':
            self.history = SelectionHistory(self.roi, self._box_mode())
        else:
            self.history.set_box(self.roi, self._box_mode(), reset=(action == 'reset'))
        self.stat_label.setText('Move / resize / rotate box, lalu klik Preview Crop.')
        self._redraw()
        self._update_buttons()

    def _restore_box_widget(self, roi, corners):
        if box_kind(roi) == 'AABB':
            self._place_box(np.column_stack((corners.min(axis=0), corners.max(axis=0))).ravel())
            return
        x = roi.normals[0]
        y = next(n for n in roi.normals[1:] if abs(n @ x) < .5)
        z = np.cross(x, y)
        axes = np.column_stack((x, y, z))
        dimensions = np.ptp((corners - corners.mean(axis=0)) @ axes, axis=0)
        matrix = np.eye(4)
        matrix[:3, :3] = axes * dimensions
        matrix[:3, 3] = corners.mean(axis=0)
        self._place_box([-.5, .5] * 3)
        transform = vtk.vtkTransform()
        transform.SetMatrix(matrix.ravel())
        self.box_widget.SetTransform(transform)

    def _restore_selection(self, *, lock_box=False):
        roi = self.history.selection
        self._clear_box_display()
        self.roi = roi
        self.roi_locked = lock_box or isinstance(roi, VIEW_SELECTIONS)
        with QSignalBlocker(self.mode_combo):
            self.mode_combo.setCurrentIndex(0 if self.history.current.box_mode == 'OBB' else 1)
        if isinstance(roi, BoxSelection):
            corners = box_corners(roi)
            if lock_box:
                surface_filter = vtk.vtkDataSetSurfaceFilter()
                surface_filter.SetInputData(pv.PolyData(corners).delaunay_3d())
                surface_filter.Update()
                self.plotter.add_mesh(pv.wrap(surface_filter.GetOutput()), name='saved_roi',
                                      color='#E7A58C', style='wireframe', line_width=2, opacity=0.9)
            else:
                self._restore_box_widget(roi, corners)
                self._widget_reference = self._vtk_box_planes(self.box_widget)
        self._update_preview(allow_empty=True)

    def undo_selection(self):
        self._navigate_history(redo=False)

    def redo_selection(self):
        self._navigate_history(redo=True)

    def _navigate_history(self, *, redo):
        if self.history is None or self.busy or self._drawing():
            return
        changed = self.history.redo() if redo else self.history.undo()
        if changed:
            self._restore_selection()

    def _las_preview_has_rgb(self):
        return any(np.any(self.attrs.get(name, ())) for name in ('red', 'green', 'blue'))

    def _las_fallback_color(self):
        intensity = self.attrs.get('intensity')
        return 'Intensity' if intensity is not None and np.ptp(intensity) != 0 else 'Elevation'

    def _add_points(self, points, attrs, name, opacity):
        if points is None or len(points) == 0:
            return
        pc = pv.PolyData(points)
        mode = self.color_combo.currentText()
        if isinstance(self.doc, LasDocument) and mode == 'RGB' and not self._las_preview_has_rgb():
            mode = self._las_fallback_color()
        scalar_opts = {}
        if mode == 'RGB' and all(c in attrs for c in ('red', 'green', 'blue')):
            rgb = np.column_stack([attrs['red'], attrs['green'], attrs['blue']])
            if rgb.dtype.kind == 'f' and np.nanmax(rgb) <= 1.:
                rgb = rgb * 255
            if isinstance(self.doc, LasDocument) and any(
                    self.attrs[channel].max() > 255 for channel in ('red', 'green', 'blue')):
                rgb = np.rint(rgb / 257.)
            pc['color'] = np.clip(rgb, 0, 255).astype(np.uint8)
            scalar_opts = {'scalars': 'color', 'rgb': True}
        elif mode == 'Elevation':
            pc['height'] = points[:, 2]
            scalar_opts = {'scalars': 'height', 'cmap': 'terrain', 'show_scalar_bar': False}
        elif mode == 'Intensity' and 'intensity' in attrs:
            pc['strength'] = attrs['intensity'].astype('f8')
            scalar_opts = {'scalars': 'strength', 'cmap': 'viridis', 'show_scalar_bar': False}
        else:
            scalar_opts = {'color': '#E0AD8E'}
        self.plotter.add_mesh(pc, name=name, style='points',
                              point_size=self.size_spin.value(), opacity=opacity,
                              render_points_as_spheres=False, **scalar_opts)

    def _redraw(self, *_, mask=None):
        if self.doc is None or self.coords is None or self.busy:
            return
        if self.preview_active and self.roi is not None:
            if isinstance(self.roi, BrushSelection) and mask is None:
                if self.roi is not self._brush_mask_roi:
                    return
                mask = self._brush_mask
            chosen = self.roi.mask(self.coords) if mask is None else mask
            if self.show_original.isChecked():
                self._add_points(self.coords, self.attrs, 'original', 0.14)
            else:
                self.plotter.remove_actor('original', render=False)
            chosen_attrs = {k: v[chosen] for k, v in self.attrs.items()}
            if chosen.any():
                self._add_points(self.coords[chosen], chosen_attrs, 'selected', 1.0)
            else:
                self.plotter.remove_actor('selected', render=False)
        else:
            self._add_points(self.coords, self.attrs, 'original', 1.0)
            self.plotter.remove_actor('selected', render=False)
        self.plotter.render()

    def preview_crop(self):
        self._update_preview()

    def _update_preview(self, *, allow_empty=False, chosen=None):
        if self.doc is None or self.roi is None or self.busy:
            return
        if isinstance(self.roi, BrushSelection) and chosen is None:
            if self.roi is self._brush_mask_roi:
                chosen = self._brush_mask
            else:
                self.preview_active = False
                self.stat_label.setText('Memperbarui preview seleksi…')
                self._set_busy(True, 'Calculating preview…')
                self._start_task(BrushPreviewTask(self.coords, self.roi), self._brush_undo_preview_ok)
                return
        if chosen is None:
            chosen = self.roi.mask(self.coords)
        if isinstance(self.roi, BrushSelection):
            self._brush_mask_roi, self._brush_mask = self.roi, chosen
        else:
            self._brush_mask = self._brush_mask_roi = None
        full_count = self.history.current.full_count if self.history else None
        count_note = (f'Full retained: {full_count:,}\n' if full_count is not None else
                      'Jumlah full-resolution dihitung dan diverifikasi saat ekspor.')
        if not chosen.any():
            if allow_empty or isinstance(self.doc, LasDocument) or isinstance(self.roi, VIEW_SELECTIONS):
                self.preview_active = True
                self.stat_label.setText(
                    f'Preview selected: 0 / {len(self.coords):,}\n{count_note}'
                )
                self._redraw(mask=chosen)
                self._update_buttons()
                return
            QMessageBox.warning(self, 'Crop empty', 'Preview crop kosong. Perbesar atau geser kotak.')
            return
        self.preview_active = True
        count = int(chosen.sum())
        ratio = 100 * count / len(self.coords)
        picked = self.coords[chosen]
        mins = picked.min(axis=0)
        maxs = picked.max(axis=0)
        operations = (f'Selection operations: {len(self.roi.operations)}\n'
                      if isinstance(self.roi, VIEW_SELECTIONS) else '')
        self.stat_label.setText(
            f'Source: {self.doc.count:,} vertices\n'
            f'{operations}'
            f'Preview selected: {count:,} / {len(self.coords):,}\n'
            f'Preview retained: {ratio:.2f}%\n'
            f'Preview XYZ min: {np.round(mins, 4)}\n'
            f'Preview XYZ max: {np.round(maxs, 4)}\n\n'
            f'{count_note}'
        )
        self._redraw(mask=chosen)
        self._update_buttons()

    def _brush_undo_preview_ok(self, result):
        self._set_busy(False, 'Preview ready')
        self._update_preview(allow_empty=True, chosen=result[0])

    def load_roi(self):
        if self.doc is None or self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Load selection JSON', '', 'JSON (*.json)')
        if not path:
            return
        try:
            history = load_history_json(path, self.doc)
            roi = history.selection
            if isinstance(roi, BoxSelection):
                box_corners(roi)
            self.history = history
            self._restore_selection(lock_box=True)
            self.statusBar().showMessage('Seleksi dan history aktif dimuat dari JSON.')
        except Exception as exc:
            QMessageBox.critical(self, 'Load selection failed', str(exc))

    def save_roi(self):
        if self.history is None or self.busy or self._drawing():
            return
        default = self.doc.path.with_name(self.doc.path.stem + '_selection.json')
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save selection JSON', str(default), 'JSON (*.json)',
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        path = Path(path).with_suffix('.json')
        if path.exists() and QMessageBox.question(
            self, 'Overwrite selection?', f'Timpa file seleksi ini?\n{path}',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._set_busy(True, 'Saving selection…')
        task = SaveSelectionTask(path, self.doc, self.roi, self.history.snapshot(), self.history.current.full_count)
        self._start_task(task, self._selection_saved)

    def _selection_saved(self, path):
        self._set_busy(False, 'Selection saved')
        self.statusBar().showMessage(f'Seleksi disimpan: {path}')

    def export(self):
        if self.doc is None or self.roi is None or not self.preview_active or self.busy:
            return
        is_las = isinstance(self.doc, LasDocument)
        default_ext = self.doc.path.suffix.lower() if is_las else '.ply'
        options = (default_ext, *(ext for ext in SAVE_FILTERS if ext != default_ext)) if is_las else ('.ply',)
        default = str(self.doc.path.with_name(self.doc.path.stem + '_crop' + default_ext))
        dest, selected_filter = QFileDialog.getSaveFileName(
            self, 'Save cropped point cloud', default, ';;'.join(SAVE_FILTERS[ext] for ext in options)
        )
        if not dest:
            return
        destpath = Path(dest)
        if destpath.suffix.lower() not in options:
            ext = next((ext for ext in options if SAVE_FILTERS[ext] == selected_filter), default_ext)
            destpath = destpath.with_suffix(ext)
        if is_las and destpath.suffix.lower() == '.ply':
            reply = QMessageBox.question(
                self, 'Derived PLY export',
                'PLY menyimpan XYZ float64 dan atribut scalar yang kompatibel. '
                'Header LAS seperti scale, offset, dan CRS dicatat di JSON. '
                'Gunakan LAS/LAZ untuk mempertahankan format native. Lanjutkan?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        allow_drop = False
        if self.doc.other_elements:
            elements = ', '.join(self.doc.other_elements)
            reply = QMessageBox.warning(
                self, 'Vertex-only export confirmation',
                f'File sumber mempunyai element non-vertex: {elements}.\n\n'
                'MVP ini hanya menyimpan vertex yang dipilih. Faces/elemen lain '
                'akan DIHILANGKAN pada output. Lanjutkan?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            allow_drop = True
        if self.doc.is_gaussian:
            reply = QMessageBox.warning(
                self, 'Gaussian PLY warning',
                'Ini merupakan Gaussian PLY, bukan LiDAR ground truth. '
                'Atribut Gaussian akan dipertahankan tetapi hasil ini tidak cocok '
                'secara otomatis sebagai acuan Chamfer Distance LiDAR. Lanjutkan?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        meta = destpath.with_name(destpath.stem + '_selection.json')
        overwrite = False
        if destpath.exists() or meta.exists():
            reply = QMessageBox.question(
                self, 'Overwrite output?', 'PLY atau JSON output sudah ada. Timpa file tersebut?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            overwrite = True
        self.progress.setValue(0)
        self._set_busy(True, 'Scanning full resolution / exporting / verifying…')
        task = ExportTask(self.doc, self.roi, destpath, allow_drop, overwrite, self.history.snapshot())
        self._start_task(task, self._export_ok)

    def _export_ok(self, result):
        out, meta, info = result
        self.history.current.full_count = info['retained_points']
        self._set_busy(False, 'Export verified')
        self._update_preview(allow_empty=True)
        self.statusBar().showMessage('Crop written and attribute values verified.')
        QMessageBox.information(self, 'Export successful',
            f'Export verified: {info["retained_points"]:,} / {info["source_points"]:,} points.\n\n'
            f'{out.suffix.upper()[1:]}: {out}\nMetadata: {meta}')

    def set_view(self, direction):
        if self.doc is None or self._drawing():
            return
        if direction == 'iso':
            self.plotter.view_isometric()
            return
        bounds = self.doc.bounds
        center = np.array([(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2,
                           (bounds[4]+bounds[5])/2])
        span = max(bounds[1]-bounds[0], bounds[3]-bounds[2],
                   bounds[5]-bounds[4], 1e-3) * 2.4
        orientations = {
            'front': ((0,-1,0), (0,0,1)), 'back': ((0,1,0), (0,0,1)),
            'left': ((-1,0,0), (0,0,1)), 'right': ((1,0,0), (0,0,1)),
            'top': ((0,0,1), (0,1,0)), 'bottom': ((0,0,-1), (0,1,0)),
        }
        v, up = orientations[direction]
        camera = center + span * np.array(v)
        self.plotter.camera_position = [camera.tolist(), center.tolist(), list(up)]
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def closeEvent(self, event):
        if self.task is not None:
            QMessageBox.warning(self, 'Still processing',
                'Selesaikan load/export sebelum menutup aplikasi.')
            event.ignore()
            return
        self.plotter.close()
        event.accept()


def run():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName('GS-PrepTools LiDAR Point Cloud Object Cropper')
    window = CropperWindow()
    window.show()
    return app.exec()
