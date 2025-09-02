from enum import Enum


class Platform(str, Enum):
    SERVICENOW = "servicenow"
    SALESFORCE = "salesforce"
    PEGA = "pega"


def normalize_platform(value: str) -> Platform:
    lowered = value.strip().lower()
    return Platform(lowered)

