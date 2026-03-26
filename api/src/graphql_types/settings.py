"""GraphQL types for the in-app settings system."""

from typing import Any, List, Optional

import strawberry


@strawberry.type
class AppSettingType:
    key: str
    value: str
    type: str
    category: str
    label: str
    description: str
    is_default: bool
    sensitive: bool
    options: Optional[List[str]] = None


@strawberry.type
class SettingsCategoryType:
    category: str
    label: str
    settings: List[AppSettingType]


@strawberry.type
class UpdateSettingResult:
    success: bool
    message: str
    setting: Optional[AppSettingType] = None


@strawberry.type
class CookieUploadResult:
    success: bool
    message: str


@strawberry.type
class YamlMigrationResult:
    success: bool
    migrated: int
    skipped: int
    message: str


def dict_to_setting_type(data: dict[str, Any]) -> AppSettingType:
    """Convert a service dict to an AppSettingType."""
    return AppSettingType(
        key=data["key"],
        value=data["value"],
        type=data["type"],
        category=data["category"],
        label=data["label"],
        description=data["description"],
        is_default=data["isDefault"],
        sensitive=data["sensitive"],
        options=data.get("options"),
    )


def dict_to_category_type(data: dict[str, Any]) -> SettingsCategoryType:
    """Convert a service dict to a SettingsCategoryType."""
    return SettingsCategoryType(
        category=data["category"],
        label=data["label"],
        settings=[dict_to_setting_type(s) for s in data["settings"]],
    )
