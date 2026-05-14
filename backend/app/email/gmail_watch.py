"""Gmail watch setup and renewal."""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.config import settings
import structlog

logger = structlog.get_logger()


def get_gmail_service():
    """Build authenticated Gmail service."""
    creds = Credentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)


async def setup_gmail_watch():
    """Register Gmail push notifications via Pub/Sub. Must be renewed every 7 days."""
    service = get_gmail_service()
    request = service.users().watch(
        userId="me",
        body={
            "topicName": settings.GMAIL_PUBSUB_TOPIC,
            "labelIds": ["INBOX"],
        },
    )
    result = request.execute()
    logger.info("gmail_watch_registered", expiration=result.get("expiration"))
    return result


async def stop_gmail_watch():
    """Stop existing Gmail watch."""
    service = get_gmail_service()
    service.users().stop(userId="me").execute()
    logger.info("gmail_watch_stopped")
