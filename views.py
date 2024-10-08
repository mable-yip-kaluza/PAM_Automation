from flask import jsonify
from slack_sdk.models.views import View
from slack_sdk.models.blocks import InputBlock, SectionBlock, ActionsBlock
from slack_sdk.models.blocks.block_elements import SelectElement, ButtonElement
from slack_sdk.models.views import View
from slack_sdk.models.blocks.basic_components import PlainTextObject, Option, OptionGroup
from slack_sdk.errors import SlackApiError
from utils import logger

from github_handlers import get_emails_from_github, get_team_folders

def get_team_selection_view() -> View:
    team_folders = get_team_folders()
    
    # Group teams alphabetically
    team_groups = {}
    for team in team_folders:
        first_letter = team[0].upper()
        if first_letter not in team_groups:
            team_groups[first_letter] = []
        team_groups[first_letter].append(team)
    
    # Create option groups
    option_groups = []
    for letter, teams in sorted(team_groups.items()):
        options = [Option(text=PlainTextObject(text=team), value=team) for team in teams]
        option_groups.append(OptionGroup(label=PlainTextObject(text=letter), options=options[:100]))
    
    blocks = [
        InputBlock(
            block_id="team_name",
            label=PlainTextObject(text="Select Team"),
            element=SelectElement(
                placeholder=PlainTextObject(text="Choose a team"),
                option_groups=option_groups,
                action_id="team_name_select"
            )
        )
    ]

    return View(
        type="modal",
        callback_id="team_selection_modal",
        title=PlainTextObject(text="Select Team"),
        submit=PlainTextObject(text="Confirm"),
        close=PlainTextObject(text="Cancel"),
        blocks=blocks
    )

def open_edit_modal(trigger_id, team_name, team_email_lists, slack_client):
    try:
        # Try to get the most recent email list from the local cache
        emails = team_email_lists.get(team_name)
        
        # If not in cache, fetch from GitHub
        if emails is None:
            emails = get_emails_from_github(team_name)
            # Store in cache for future use
            team_email_lists[team_name] = emails

        slack_client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "edit_people_modal",
                "title": {"type": "plain_text", "text": "Edit People"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "private_metadata": team_name,
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "email_list",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "email_input",
                            "multiline": True,
                            "initial_value": "\n".join(emails)
                        },
                        "label": {"type": "plain_text", "text": "Edit email list (one per line)"}
                    }
                ]
            }
        )
        return jsonify({"status": "success"})
    except SlackApiError as e:
        logger.error(f"Error opening edit modal: {e}")
        return jsonify({"status": "error", "error": str(e)})
    

def post_email_list_message(team_name, emails,slack_client, slack_channel):
    try:
        email_list = "\n• ".join(emails)
        response = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Please confirm the following people for next week's production access for team {team_name}:\n{email_list}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Who will have production access next week for team *{team_name}*?\n\n*People for next week's production access:*\n• {email_list}"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Confirm"
                            },
                            "style": "primary",
                            "action_id": "confirm_prod_access"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Edit People"
                            },
                            "action_id": "edit_people"
                        }
                    ]
                }
            ],
            metadata={"event_type": "prod_access_request", "event_payload": {"team_name": team_name}}
        )
        logger.debug(f"Posted email list message: {response}")
        return {"response_action": "clear"}
    except SlackApiError as e:
        logger.error(f"Error posting email list message: {e}")
        return {"response_action": "errors", "errors": {"team_name": str(e)}}
    

def post_confirmed_email_list_message(team_name, emails, pr_message, jira_message, slack_client, slack_channel):
    try:
        email_list = "\n• ".join([f"<mailto:{email}|{email}>" for email in emails])
        response = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Confirmed updated email list for team {team_name}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Confirmed updated email list for team *{team_name}*:\n\n• {email_list}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": pr_message
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": jira_message
                    }
                }
            ],
            metadata={"event_type": "prod_access_request", "event_payload": {"team_name": team_name}}
        )
        logger.debug(f"Posted confirmed email list message: {response}")
        return jsonify({"response_action": "clear"})
    except SlackApiError as e:
        logger.error(f"Error posting confirmed email list message: {e}")
        return jsonify({"response_action": "errors", "errors": {"email_list": "Failed to confirm email list"}})