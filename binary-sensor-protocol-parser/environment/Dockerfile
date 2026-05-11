FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git=1:2.47.3-0+deb13u1 \
    tmux=3.5a-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir pytest==8.3.5

RUN python3 - <<'PYEOF'
import base64, os
os.makedirs('/app/data', exist_ok=True)
b64 = (
    'q80ADQABZVPxAABBvAAAM/2rzQANAAJlU/EBAUKCgAAzI96tvu+rzQANAANlU/ECAkR9QACC+qvN'
    'ABUABGVT8QMDP4zMzUEc9cO/AAAAUzmrzQAVAAVlU/EEBD3MzM2+TMzNP8j1w9pSq80ADQAGZVPx'
    'BQBCSAAAyLfK/rq+q80ADQAHZVPxBgcAAAAAOcGrzQANAAhlU/EHAUJcAABP8avNABEACWVT8QgC'
    'RHnAAER6AAAz6avNAA0ACmVT8QkAwSgAAPlaq80AFQALZVPxCgMAAAAAAAAAAAAAAADD9avNABEA'
    'DGVT8QsDP4AAAEAAAADmPqvNAA0ADWVT8QwBQpAAAB1Kq80ADQAOZVPxDQJEfyAAqoirzQANAA9l'
    'U/EO/wAAAABDs6vNAA0AEGVT8Q8AQhTMzdkUq80ADQARZVPxEAFCNgAAcPmrzQAVABJlU/ERAwAA'
    'AABBHPXDAAAAAEtQq80ADQABAgMEBavN'
)
with open('/app/data/sensor_dump.bin', 'wb') as f:
    f.write(base64.b64decode(b64))
PYEOF

RUN python3 - <<'PYEOF'
import os

os.makedirs('/app/data', exist_ok=True)

# SHA-256 of sensor_dump.bin — agent should verify this before parsing
checksum = "357ae41a920fcaffea09cca4df6ce919af8858ac65342d9b300a6163e7800e50  /app/data/sensor_dump.bin\n"
with open('/app/data/sensor_dump.bin.sha256', 'w') as f:
    f.write(checksum)
PYEOF
