from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from openapi_spec_validator import validate


def validate_openapi_spec(path: str) -> Tuple[bool, str]:
    try:
        data = json.loads(Path(path).read_text())
        validate(data)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

