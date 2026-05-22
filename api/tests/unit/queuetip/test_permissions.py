import pytest

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import (
    PermissionDeniedError,
    get_membership,
    require_member,
    require_owner,
)


def _setup():
    owner = Account.objects.create(display_name="Owner")
    member = Account.objects.create(display_name="Member")
    outsider = Account.objects.create(display_name="Out")
    playlist = Playlist.objects.create(name="P", created_by=owner)
    PlaylistMembership.objects.create(
        playlist=playlist, account=owner, role=PlaylistMembership.ROLE_OWNER
    )
    PlaylistMembership.objects.create(
        playlist=playlist, account=member, role=PlaylistMembership.ROLE_MEMBER
    )
    return owner, member, outsider, playlist


@pytest.mark.django_db
def test_get_membership_returns_owner_membership():
    owner, _member, _out, playlist = _setup()
    m = get_membership(owner, playlist)
    assert m is not None
    assert m.role == PlaylistMembership.ROLE_OWNER


@pytest.mark.django_db
def test_get_membership_returns_none_for_outsider():
    _owner, _member, out, playlist = _setup()
    assert get_membership(out, playlist) is None


@pytest.mark.django_db
def test_require_member_passes_for_member():
    _o, member, _out, playlist = _setup()
    m = require_member(member, playlist)
    assert m.role == PlaylistMembership.ROLE_MEMBER


@pytest.mark.django_db
def test_require_member_rejects_outsider():
    _o, _m, out, playlist = _setup()
    with pytest.raises(PermissionDeniedError):
        require_member(out, playlist)


@pytest.mark.django_db
def test_require_owner_passes_for_owner():
    owner, _m, _out, playlist = _setup()
    m = require_owner(owner, playlist)
    assert m.role == PlaylistMembership.ROLE_OWNER


@pytest.mark.django_db
def test_require_owner_rejects_member():
    _o, member, _out, playlist = _setup()
    with pytest.raises(PermissionDeniedError):
        require_owner(member, playlist)


def test_require_member_rejects_anonymous():
    with pytest.raises(PermissionDeniedError):
        require_member(None, None)  # type: ignore[arg-type]
