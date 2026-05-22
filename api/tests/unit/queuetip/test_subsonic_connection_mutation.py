"""Tests for the add-Subsonic-connection guard."""

import pytest

from queuetip.models import Account, SubsonicConnection
from src.queuetip.errors import ValidationError
from src.queuetip.schema.mutation import _create_subsonic_connection


@pytest.mark.django_db
def test_add_subsonic_connection_rejects_second_and_preserves_first():
    """A second addSubsonicConnection must be rejected, not clobber the first.

    Replacing would CASCADE-delete the account's PlaylistExportTargets; the UI
    routes edits through updateSubsonicConnection instead.
    """
    account = Account.objects.create(display_name="t")
    first = _create_subsonic_connection(
        account, "Nav", "https://nav.example", "user", "pw"
    )

    with pytest.raises(ValidationError):
        _create_subsonic_connection(
            account, "Nav2", "https://nav2.example", "user", "pw2"
        )

    remaining = SubsonicConnection.objects.filter(account=account)
    assert remaining.count() == 1
    assert remaining.first().id == first.id
