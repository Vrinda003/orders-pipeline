"""Lets the tests import the modules in src/ (config, pipeline, validate...)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))