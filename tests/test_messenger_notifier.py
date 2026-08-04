from messenger.src.notifier import TelegramNotifier


def test_messenger_notifier_delegates_outbound_delivery_to_shared_transport():
    class Transport:
        enabled = True

        def __init__(self):
            self.messages = []

        def send_message(self, text, *, disable_web_page_preview=False):
            self.messages.append((text, disable_web_page_preview))
            return {"ok": True, "code": "sent", "message_id": 1}

    transport = Transport()
    notifier = TelegramNotifier("123456:fake_token_abcdefghijklmnop", "-1001234567890", transport=transport)

    assert notifier.send_message("draft") is True
    assert transport.messages == [("draft", True)]
