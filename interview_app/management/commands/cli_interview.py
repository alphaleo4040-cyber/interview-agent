import sys
from django.core.management.base import BaseCommand
import main


class Command(BaseCommand):
    help = "Run the interactive terminal AI Job Interview CLI."

    def handle(self, *args, **options):
        main.main()
