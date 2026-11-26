"""Selection commands and replay. Entries contain geometry, never point arrays."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    HISTORY_SCHEMA, BoxSelection, CropError, box_kind, file_sha256, read_selection_metadata, write_json_atomic,
)
from .brush import BRUSH_ACTIONS, BRUSH_TYPE, BrushOperation, BrushSelection, decode_operation
from .polygon import POLYGON_TYPE, PolygonOperation, PolygonSelection

VIEW_SELECTIONS = (PolygonSelection, BrushSelection)
VIEW_OPERATIONS = (PolygonOperation, BrushOperation)


def decode_selection(data):
    if data.get('type') == BRUSH_TYPE:
        return BrushSelection.from_dict(data)
    if data.get('type') == POLYGON_TYPE:
        return PolygonSelection.from_dict(data)
    return BoxSelection.from_dict(data)


@dataclass
class SelectionStep:
    action: str
    geometry: BoxSelection | PolygonSelection | PolygonOperation | BrushSelection | BrushOperation
    box_mode: str
    use_box: bool = True
    full_count: int | None = None

    def to_dict(self):
        data = {'action': self.action, 'geometry': self.geometry.to_dict(), 'box_mode': self.box_mode}
        if isinstance(self.geometry, VIEW_OPERATIONS):
            data['use_box'] = self.use_box
        return data


class SelectionHistory:
    def __init__(self, initial: BoxSelection | PolygonSelection | BrushSelection, box_mode: str):
        self._steps = [SelectionStep('initial', initial, box_mode)]
        self._position = 0

    @property
    def position(self):
        return self._position

    @property
    def length(self):
        return len(self._steps)

    @property
    def can_undo(self):
        return self.position > 0

    @property
    def can_redo(self):
        return self.position + 1 < self.length

    @property
    def current(self):
        return self._steps[self.position]

    @property
    def selection(self) -> BoxSelection | PolygonSelection | BrushSelection:
        index = self.position
        while isinstance(self._steps[index].geometry, VIEW_OPERATIONS):
            index -= 1
        base = self._steps[index].geometry
        suffix = self._steps[index + 1:self.position + 1]
        if not suffix:
            return base
        operations = tuple(step.geometry for step in suffix)
        if isinstance(base, VIEW_SELECTIONS):
            initial, operations = base.initial_box, base.operations + operations
        else:
            initial = base if suffix[0].use_box else None
        selection_type = BrushSelection if any(isinstance(op, BrushOperation) for op in operations) else PolygonSelection
        return selection_type(initial, operations)

    def _append(self, step):
        del self._steps[self.position + 1:]
        self._steps.append(step)
        self._position += 1

    def set_box(self, box: BoxSelection, box_mode: str, *, reset=False):
        self._append(SelectionStep('reset' if reset else 'box', box, box_mode))

    def apply_polygon(self, operation: PolygonOperation, *, use_box=True):
        self._append(SelectionStep(operation.kind, operation, self.current.box_mode, use_box))

    def apply_brush(self, operation: BrushOperation):
        self._append(SelectionStep(operation.kind, operation, self.current.box_mode))

    def undo(self):
        if self.can_undo:
            self._position -= 1
            return True
        return False

    def redo(self):
        if self.can_redo:
            self._position += 1
            return True
        return False

    def snapshot(self):
        """Serialise the applied prefix. An undone branch is session-local."""
        return {'position': self.position,
                'steps': [step.to_dict() for step in self._steps[:self.position + 1]]}

    @classmethod
    def from_snapshot(cls, snapshot):
        entries = snapshot['steps']
        if (not isinstance(entries, list) or not entries or
                snapshot['position'] != len(entries) - 1 or entries[0]['action'] != 'initial'):
            raise CropError('Posisi history seleksi tidak valid.')
        history = cls(decode_selection(entries[0]['geometry']), _box_mode(entries[0]))
        for entry in entries[1:]:
            action, geometry = entry['action'], entry['geometry']
            mode = _box_mode(entry)
            if action in ('box', 'reset'):
                history.set_box(BoxSelection.from_dict(geometry), mode, reset=(action == 'reset'))
            elif action in ('keep', 'remove', *BRUSH_ACTIONS):
                operation = decode_operation(geometry)
                use_box = entry.get('use_box', True)
                if operation.kind != action or mode != history.current.box_mode or not isinstance(use_box, bool):
                    raise CropError('Operasi history poligon tidak konsisten.')
                if isinstance(operation, BrushOperation):
                    if not use_box:
                        raise CropError('Stroke brush memerlukan domain seleksi aktif.')
                    history.apply_brush(operation)
                else:
                    history.apply_polygon(operation, use_box=use_box)
            else:
                raise CropError('Operasi history tidak dikenal.')
        return history


def _box_mode(entry):
    mode = entry['box_mode']
    if mode not in ('AABB', 'OBB'):
        raise CropError('Mode kotak pada history tidak valid.')
    return mode


def history_from_metadata(data, source_count):
    selection = decode_selection(data['selection'])
    if 'selection_history' in data:
        history = SelectionHistory.from_snapshot(data['selection_history'])
        if history.selection.to_dict() != selection.to_dict():
            raise CropError('Seleksi aktif tidak cocok dengan history.')
    else:
        box = selection.initial_box if isinstance(selection, VIEW_SELECTIONS) else selection
        history = SelectionHistory(selection, box_kind(box) if box else 'OBB')
    count = data.get('retained_points')
    if type(count) is int and 0 <= count <= source_count:
        history.current.full_count = count
    return history


def load_history_json(path, doc):
    return history_from_metadata(read_selection_metadata(path, doc), doc.count)


def save_history_json(path, doc, roi, snapshot, full_count):
    out = Path(path).expanduser().resolve()
    if out.suffix.lower() != '.json':
        raise CropError('File seleksi harus berekstensi .json.')
    if out == doc.path or (out.exists() and out.samefile(doc.path)):
        raise CropError('File sumber tidak boleh ditimpa.')
    before = doc.path.stat()
    stamp = (before.st_size, before.st_mtime_ns)
    if getattr(doc, 'source_stamp', stamp) != stamp:
        raise CropError('File sumber berubah sejak dibuka. Buka ulang sebelum menyimpan seleksi.')
    digest = file_sha256(doc.path)
    after = doc.path.stat()
    if stamp != (after.st_size, after.st_mtime_ns):
        raise CropError('File sumber berubah saat menyimpan seleksi.')
    payload = {
        'schema_version': HISTORY_SCHEMA, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_file': str(doc.path), 'input_sha256': digest, 'input_size_bytes': before.st_size,
        'input_modified_ns': before.st_mtime_ns, 'source_points': doc.count,
        'retained_points': full_count, 'selection': roi.to_dict(), 'selection_history': snapshot,
    }
    write_json_atomic(out, payload)
    return out
