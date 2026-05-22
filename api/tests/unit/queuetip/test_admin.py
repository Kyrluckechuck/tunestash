"""Tests for the queuetip admin gate (is_queuetip_admin)."""

import pytest

from library_manager.models import AppSetting
from queuetip.models import Account, AuthIdentity
from queuetip.permissions import is_queuetip_admin


@pytest.mark.django_db
def test_is_queuetip_admin_gate():
    account = Account.objects.create(display_name="Op")
    AuthIdentity.objects.create(
        account=account, provider="magic_link", identifier="justin@kyryli.uk"
    )

    # Empty setting → nobody is admin.
    assert is_queuetip_admin(account) is False
    assert is_queuetip_admin(None) is False

    # Setting lists the email (case-insensitive) → admin.
    AppSetting.objects.create(
        key="queuetip_admin_emails",
        value="Justin@Kyryli.uk, other@x.com",
        category="authentication",
    )
    assert is_queuetip_admin(account) is True

    # An account whose email isn't listed is not admin.
    other = Account.objects.create(display_name="Other")
    AuthIdentity.objects.create(
        account=other, provider="magic_link", identifier="nope@example.com"
    )
    assert is_queuetip_admin(other) is False
