"""Configuration shared by Basil Cloud clients."""

import os


DEFAULT_AUTH_SERVICE_URL = "https://basilauthservice-production.up.railway.app"
AUTH_SERVICE_URL = os.environ.get("BASIL_AUTH_SERVICE_URL", DEFAULT_AUTH_SERVICE_URL)
