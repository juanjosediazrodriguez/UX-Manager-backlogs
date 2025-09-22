from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter


class NoOpMessageAccountAdapter(DefaultAccountAdapter):
    """Account adapter that silences allauth user messages."""

    def add_message(self, request, level, message_template, message_context=None, extra_tags=""):
        # Override to skip adding messages to the Django messages framework
        return
