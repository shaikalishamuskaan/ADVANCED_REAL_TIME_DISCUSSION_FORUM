import os
from urllib.error import HTTPError
from urllib.request import urlopen


url = os.environ["FORUM_HEALTH_URL"]
expected = int(os.environ.get("FORUM_HEALTH_STATUS", "200"))
try:
    with urlopen(url, timeout=3) as response:
        status = response.status
except HTTPError as error:
    status = error.code
raise SystemExit(0 if status == expected else 1)
