from app.contacts.models import Contact

INVALID_NAMES = frozenset(
    {
        "desconhecido",
        "none",
        "null",
        "sem nome",
        "unknown",
    }
)


def normalize_contact_name(value: str | None) -> str | None:
    normalized = " ".join((value or "").strip().split())
    return normalized or None


def usable_contact_name(value: str | None, phone_number: str) -> str | None:
    normalized = normalize_contact_name(value)
    if normalized is None:
        return None

    lowered = normalized.casefold()
    if lowered in INVALID_NAMES or lowered.endswith(
        ("@g.us", "@lid", "@s.whatsapp.net")
    ):
        return None
    if not any(character.isalnum() for character in normalized):
        return None

    candidate_digits = "".join(
        character for character in normalized if character.isdigit()
    )
    phone_digits = "".join(
        character for character in phone_number if character.isdigit()
    )
    if (
        candidate_digits
        and candidate_digits == phone_digits
        and not any(character.isalpha() for character in normalized)
    ):
        return None
    return normalized


def contact_display_name(contact: Contact) -> str:
    for candidate in (
        contact.name,
        contact.verified_name,
        contact.business_name,
        contact.address_book_name,
        contact.push_name,
    ):
        usable = usable_contact_name(candidate, contact.phone_number)
        if usable:
            return usable
    return contact.phone_number
