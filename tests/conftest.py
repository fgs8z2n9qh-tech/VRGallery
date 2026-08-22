import os
import sys

# tests run against the source tree, not an installed copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# nothing here should ever touch the real library
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
