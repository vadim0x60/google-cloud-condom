import sys
from pathlib import Path

import google.auth
from google.auth.credentials import AnonymousCredentials

# The Google clients are created when kill_switch is imported; give them credentials
# so the tests run without a Google Cloud login. Tests replace the clients anyway.
google.auth.default = lambda *args, **kwargs: (AnonymousCredentials(), "test")
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "function")]
