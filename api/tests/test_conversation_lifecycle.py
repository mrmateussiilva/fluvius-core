import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.common.enums import ConversationStatus
from app.messages.router import reopen_for_agent
from app.providers.webhook_router import reopen_from_provider


class ConversationLifecycleTest(unittest.TestCase):
    def test_incoming_reopens_as_new_and_clears_assignee(self) -> None:
        conversation = SimpleNamespace(
            status=ConversationStatus.CLOSED,
            assigned_user_id=uuid4(),
        )

        reopened = reopen_from_provider(conversation)

        self.assertTrue(reopened)
        self.assertEqual(conversation.status, ConversationStatus.NEW)
        self.assertIsNone(conversation.assigned_user_id)

    def test_agent_send_reopens_and_assigns_current_user(self) -> None:
        user_id = uuid4()
        conversation = SimpleNamespace(
            status=ConversationStatus.CLOSED,
            assigned_user_id=None,
        )

        reopened = reopen_for_agent(conversation, user_id)

        self.assertTrue(reopened)
        self.assertEqual(conversation.status, ConversationStatus.OPEN)
        self.assertEqual(conversation.assigned_user_id, user_id)

    def test_active_conversation_is_unchanged(self) -> None:
        conversation = SimpleNamespace(
            status=ConversationStatus.OPEN,
            assigned_user_id=uuid4(),
        )

        self.assertFalse(reopen_from_provider(conversation))
        self.assertEqual(conversation.status, ConversationStatus.OPEN)


if __name__ == "__main__":
    unittest.main()
