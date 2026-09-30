import os

__all__ = ["CommonUtils"]

class CommonUtils:
    """CommonUtils"""

    def __init__(self):
        pass

    @classmethod
    def get_project_root_path(cls):
        """Return the exact project root path: H:\\Code\\EvGameSimulations"""
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
