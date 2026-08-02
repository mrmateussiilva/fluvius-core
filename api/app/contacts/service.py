from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider, ContactKind
from app.contacts.models import Contact
from app.contacts.naming import usable_contact_name
from app.providers.base import ContactProfileResult, GroupDirectoryEntry
from app.providers.evolution_credentials import claim_evolution_credential
from app.providers.factory import get_provider


def apply_contact_profile(contact: Contact, profile: ContactProfileResult) -> None:
    for field in (
        "address_book_name",
        "push_name",
        "business_name",
        "verified_name",
    ):
        value = usable_contact_name(getattr(profile, field), contact.phone_number)
        if value is not None:
            setattr(contact, field, value)
    for field in (
        "about",
        "profile_picture_url",
        "is_on_whatsapp",
    ):
        value = getattr(profile, field)
        if value is not None:
            setattr(contact, field, value)
    if contact.kind == ContactKind.GROUP:
        group_name = usable_contact_name(profile.push_name, contact.phone_number)
        if group_name:
            contact.name = group_name
        if profile.group_member_count is not None:
            contact.group_member_count = profile.group_member_count
        if profile.group_members:
            contact.group_members = [
                member.model_dump(mode="json") for member in profile.group_members
            ]
            if contact.group_member_count is None:
                contact.group_member_count = len(profile.group_members)
    contact.profile_synced_at = datetime.now(UTC)
    contact.profile_sync_error = profile.error


async def synchronize_contact_profile(
    db: Session,
    *,
    channel: WhatsAppChannel,
    contact: Contact,
) -> ContactProfileResult:
    if channel.provider == ChannelProvider.EVOLUTION_GO:
        claim_evolution_credential(db, channel)
    provider = get_provider(channel.provider, channel, db)
    if contact.kind == ContactKind.GROUP:
        profile = await provider.get_group_profile(
            channel,
            contact.provider_address or contact.phone_number,
        )
    else:
        profile = await provider.get_contact_profile(
            channel,
            contact.phone_number,
        )
    apply_contact_profile(contact, profile)
    return profile


def upsert_group_directory_entry(
    db: Session,
    *,
    tenant_id,
    entry: GroupDirectoryEntry,
) -> Contact:
    contact = db.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.phone_number == entry.group_id,
        )
    )
    if contact is None:
        contact = Contact(
            tenant_id=tenant_id,
            kind=ContactKind.GROUP,
            phone_number=entry.group_id,
            provider_address=entry.provider_address,
            name=entry.name or f"Grupo {entry.group_id[-6:]}",
        )
        db.add(contact)
        db.flush()
    else:
        contact.kind = ContactKind.GROUP
        contact.provider_address = entry.provider_address or contact.provider_address

    profile = ContactProfileResult(
        push_name=entry.name,
        about=entry.about,
        profile_picture_url=entry.profile_picture_url,
        is_on_whatsapp=True,
        group_member_count=entry.member_count,
        group_members=list(entry.members),
    )
    apply_contact_profile(contact, profile)
    return contact


async def import_channel_groups(
    db: Session,
    *,
    channel: WhatsAppChannel,
) -> list[Contact]:
    if channel.provider == ChannelProvider.EVOLUTION_GO:
        claim_evolution_credential(db, channel)
    provider = get_provider(channel.provider, channel, db)
    entries = await provider.list_groups(channel)
    return [
        upsert_group_directory_entry(
            db,
            tenant_id=channel.tenant_id,
            entry=entry,
        )
        for entry in entries
    ]


def needs_group_profile_import(contact: Contact) -> bool:
    if contact.kind != ContactKind.GROUP:
        return False
    if contact.profile_synced_at is None:
        return True
    name = (contact.name or "").strip()
    return name.startswith("Grupo ") and name[6:].isdigit()
