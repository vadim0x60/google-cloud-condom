import sys
from pathlib import Path

import google.auth
from google.auth.credentials import AnonymousCredentials

# The Google clients are created when condom is imported; give them credentials
# so the tests run without a Google Cloud login. Tests replace the clients anyway.
google.auth.default = lambda *args, **kwargs: (AnonymousCredentials(), "test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
