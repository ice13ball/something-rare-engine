# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import sys
from pathlib import Path

import pytest

# Add backend directory to sys.path so imports like `import db` work within backend modules
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture
async def export_client():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"X-API-Key": os.environ.get("ABYSSAL_API_KEY", "")},
    ) as client:
        yield client
