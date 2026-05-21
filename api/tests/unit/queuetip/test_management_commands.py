from django.core.management import call_command

import pytest

from queuetip.models import QueuetipSignupAllowlist


@pytest.mark.django_db
def test_queuetip_allow_email_adds_to_allowlist():
    call_command("queuetip_allow_email", "alice@example.com", "--note", "Cousin")
    obj = QueuetipSignupAllowlist.objects.get(email="alice@example.com")
    assert obj.note == "Cousin"


@pytest.mark.django_db
def test_queuetip_allow_email_idempotent_update():
    call_command("queuetip_allow_email", "alice@example.com", "--note", "v1")
    call_command("queuetip_allow_email", "alice@example.com", "--note", "v2")
    assert (
        QueuetipSignupAllowlist.objects.filter(email="alice@example.com").count() == 1
    )
    assert QueuetipSignupAllowlist.objects.get(email="alice@example.com").note == "v2"


@pytest.mark.django_db
def test_queuetip_allow_email_rejects_invalid_input():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("queuetip_allow_email", "not-an-email")
