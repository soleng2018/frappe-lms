"""Backend healthcheck: GET /api/method/ping with the Host header set to the one site on disk."""

import glob
import os
import sys
import urllib.request

sites = glob.glob("/home/frappe/frappe-bench/sites/*/site_config.json")
if len(sites) != 1:
    sys.exit(f"expected one site, found {len(sites)}")
site = os.path.basename(os.path.dirname(sites[0]))
req = urllib.request.Request("http://127.0.0.1:8000/api/method/ping", headers={"Host": site})
with urllib.request.urlopen(req, timeout=4) as r:
    sys.exit(0 if r.status == 200 else 1)
