"""Run from the lidar_point_cropper folder with `python run.py`."""
import os
os.environ.setdefault('QT_API', 'pyside6')
from lidar_cropper.gui import run

if __name__ == '__main__':
    raise SystemExit(run())
