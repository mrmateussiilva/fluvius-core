import unittest

from app.contacts.models import Contact
from app.contacts.naming import contact_display_name, usable_contact_name


class ContactNamingTest(unittest.TestCase):
    phone_number = "5527999999999"

    def test_rejects_phone_jid_and_placeholder_as_names(self) -> None:
        for value in (
            "+55 (27) 99999-9999",
            "5527999999999@s.whatsapp.net",
            "unknown",
            "...",
        ):
            with self.subTest(value=value):
                self.assertIsNone(usable_contact_name(value, self.phone_number))

    def test_prefers_manual_then_verified_and_address_book_names(self) -> None:
        contact = Contact(
            phone_number=self.phone_number,
            name=self.phone_number,
            verified_name="Empresa Verificada",
            business_name="Empresa Comercial",
            address_book_name="Maria Agenda",
            push_name="Maria WhatsApp",
        )
        self.assertEqual(contact_display_name(contact), "Empresa Verificada")

        contact.name = "Maria Operacao"
        self.assertEqual(contact_display_name(contact), "Maria Operacao")

        contact.name = None
        contact.verified_name = None
        contact.business_name = None
        self.assertEqual(contact_display_name(contact), "Maria Agenda")

    def test_falls_back_to_phone_when_no_reliable_name_exists(self) -> None:
        contact = Contact(
            phone_number=self.phone_number,
            name=self.phone_number,
            push_name=f"{self.phone_number}@s.whatsapp.net",
        )
        self.assertEqual(contact_display_name(contact), self.phone_number)


if __name__ == "__main__":
    unittest.main()
