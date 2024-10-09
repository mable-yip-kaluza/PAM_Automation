import logging
from slack_sdk.errors import SlackApiError

from config import SLACK_CHANNEL


logger = logging.getLogger(__name__)


def send_slack_message(message, slack_client):
    try:
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                }
            ]
        )
    except SlackApiError as e:
        logger.error(f"Error sending Slack message: {e}")