"""Response policy and path format shared by Hearth and its public page server."""

import re

MAX_PAGE = 5_000_000
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
POLICY = ("default-src 'self' 'unsafe-inline' data: blob:; script-src 'none'; style-src 'unsafe-inline'; "
          "img-src data:; connect-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; "
          "frame-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'")
CSP = POLICY + "; frame-ancestors 'self'; sandbox"
PUBLIC_CSP = POLICY + "; frame-ancestors 'none'; sandbox"
