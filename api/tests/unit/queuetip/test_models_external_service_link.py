import datetime as dt

from django.db import IntegrityError
from django.utils import timezone

import pytest

from queuetip.models import Account, ExternalServiceLink


@pytest.mark.django_db
def test_external_service_link_persists():
    a = Account.objects.create(display_name="Owner")
    link = ExternalServiceLink.objects.create(
        account=a,
        service="spotify",
        access_token="at",
        refresh_token="rt",
        expires_at=timezone.now() + dt.timedelta(hours=1),
        scope="playlist-modify-private",
        service_user_id="spotify_user_123",
    )
    assert link.id is not None
    assert link.account_id == a.id


@pytest.mark.django_db
def test_external_service_link_unique_per_account_service():
    a = Account.objects.create(display_name="Owner")
    ExternalServiceLink.objects.create(
        account=a,
        service="spotify",
        access_token="at1",
        refresh_token="rt1",
        expires_at=timezone.now() + dt.timedelta(hours=1),
        scope="x",
        service_user_id="u1",
    )
    with pytest.raises(IntegrityError):
        ExternalServiceLink.objects.create(
            account=a,
            service="spotify",
            access_token="at2",
            refresh_token="rt2",
            expires_at=timezone.now() + dt.timedelta(hours=1),
            scope="x",
            service_user_id="u2",
        )
