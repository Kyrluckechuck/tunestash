"""CLI: add an email to the Queuetip sign-up allowlist.

Usage:
    docker compose exec web python manage.py queuetip_allow_email alice@example.com
    docker compose exec web python manage.py queuetip_allow_email alice@example.com --note "Cousin"
"""

from django.core.management.base import BaseCommand, CommandError

from queuetip.models import QueuetipSignupAllowlist


class Command(BaseCommand):
    help = "Add an email to the Queuetip sign-up allowlist."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        parser.add_argument(
            "--note", type=str, default="", help="Optional note (who/why)."
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        if not email or "@" not in email:
            raise CommandError(f"Not a valid email: {email!r}")
        obj, created = QueuetipSignupAllowlist.objects.update_or_create(
            email=email,
            defaults={"note": options["note"] or ""},
        )
        action = "Added" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} {email} to the allowlist."))
