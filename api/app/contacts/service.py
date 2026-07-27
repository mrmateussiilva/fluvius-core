from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.contacts.models import Contact
from app.providers.base import ContactProfileResult
from app.providers.evolution_credentials import claim_evolution_credential
from app.providers.factory import get_provider


async def synchronize_contact_profile(
    db: Session,
    *,
    channel: WhatsAppChannel,
    contact: Contact,
) -> ContactProfileResult:
    if channel.provider == ChannelProvider.EVOLUTION_GO:
        claim_evolution_credential(db, channel)
    profile = await get_provider(channel.provider, channel, db).get_contact_profile(
        channel,
        contact.phone_number,
    )
    for field in (
        "push_name",
        "business_name",
        "verified_name",
        "about",
        "profile_picture_url",
        "is_on_whatsapp",
    ):
        value = getattr(profile, field)
        if value is not None:
            setattr(contact, field, value)
    if not contact.name and profile.push_name:
        contact.name = profile.push_name
    contact.profile_synced_at = datetime.now(UTC)
    contact.profile_sync_error = profile.error
    return profile
