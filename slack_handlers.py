import json
import os
from flask import jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from github_handlers import get_emails_from_github, update_github_and_create_pr
from jira_handlers import create_jira_tickets
from utils import logger
from views import get_team_selection_view, open_edit_modal, post_email_list_message, post_confirmed_email_list_message

def handle_slack_interactions(form_data, logger, slack_client, slack_channel, team_email_lists):
    payload = json.loads(form_data["payload"])
    
    if payload.get("type") == "view_submission":
        return handle_view_submission(payload, logger, slack_client, slack_channel, team_email_lists)
    elif payload.get("type") == "block_actions":
        return handle_block_actions(payload, logger, slack_client, slack_channel, team_email_lists)
    else:
        return jsonify({"status": "error", "message": "Unknown interaction type"})

def handle_view_submission(payload, logger, slack_client, slack_channel, team_email_lists):
    view = payload["view"]
    callback_id = view["callback_id"]

    if callback_id == "team_selection_modal":
        return handle_team_selection(view, slack_client, slack_channel)
    elif callback_id == "edit_people_modal":
        return handle_email_editing(view, team_email_lists, slack_client, slack_channel)
    else:
        logger.error(f"Unknown view submission callback_id: {callback_id}")
        return {"response_action": "errors", "errors": {"general": "An unknown error occurred."}}

def handle_block_actions(payload, logger, slack_client, slack_channel, team_email_lists):
    action = payload["actions"][0]
    action_id = action["action_id"]
    team_name = payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("team_name", "")

    if action_id == 'edit_people':
        return open_edit_modal(payload['trigger_id'], team_name, team_email_lists, slack_client)
    elif action_id == 'confirm_email_changes':
        return confirm_email_changes(team_name, team_email_lists, slack_client, slack_channel)
    elif action_id == 'confirm_prod_access':
        return confirm_prod_access(team_name, team_email_lists, slack_client, slack_channel)
    else:
        return jsonify({"status": "error", "message": "Unknown action"})

def handle_prod_access_command(form_data, slack_client):
    try:
        slack_client.views_open(
            trigger_id=form_data["trigger_id"],
            view=get_team_selection_view()
        )
        return jsonify({"status": "success"})
    except SlackApiError as e:
        return jsonify({"status": "error", "error": str(e)})
    
def handle_team_selection(view, slack_client, slack_channel):
    selected_option = view["state"]["values"]["team_name"]["team_name_select"]["selected_option"]
    team_name = selected_option["value"]
    
    breakglass_emails = get_emails_from_github(team_name)
    
    if not breakglass_emails:
        return {
            "response_action": "errors",
            "errors": {
                "team_name": "No BreakGlass emails found for this team. Please check the team name and try again."
            }
        }
    
    return post_email_list_message(team_name, breakglass_emails, slack_client, slack_channel)

def handle_email_editing(view, team_email_lists, slack_client, slack_channel):
    team_name = view["private_metadata"]
    new_emails = view["state"]["values"]["email_list"]["email_input"]["value"].split("\n")
    new_emails = [email.strip() for email in new_emails if email.strip()]

    # Update the local cache
    team_email_lists[team_name] = new_emails

    # Show a preview of the changes
    return post_email_preview_message(team_name, new_emails, slack_client, slack_channel)

def post_email_preview_message(team_name, emails, slack_client, slack_channel):
    try:
        email_list = "\n• ".join(emails)
        response = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Preview of updated email list for team {team_name}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Preview of updated email list for team *{team_name}*:\n\n• {email_list}"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Confirm Changes"
                            },
                            "style": "primary",
                            "action_id": "confirm_email_changes"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Edit Again"
                            },
                            "action_id": "edit_people"
                        }
                    ]
                }
            ],
            metadata={"event_type": "prod_access_request", "event_payload": {"team_name": team_name}}
        )
        logger.debug(f"Posted email preview message: {response}")
        return {"response_action": "clear"}
    except SlackApiError as e:
        logger.error(f"Error posting email preview message: {e}")
        return {"response_action": "errors", "errors": {"email_list": "Failed to preview email list"}}


def confirm_email_changes(team_name, team_email_lists, slack_client, slack_channel):
    emails = team_email_lists.get(team_name, [])
    if not emails:
        return jsonify({"response_action": "errors", "errors": {"general": "No email list found for this team."}})

    result = update_github_and_create_pr(team_name, emails, send_slack_message)
    if result["success"]:
        # Create Jira tickets
        jira_result = create_jira_tickets(emails, team_name)
        
        # Prepare the message
        pr_message = f"A pull request has been created to update the BreakGlass emails. <{result['pr_url']}|View PR>"
        jira_message = jira_result["message"] if jira_result["success"] else "Failed to create Jira tickets. Please try again or contact support."
        
        return post_confirmed_email_list_message(team_name, emails, pr_message, jira_message, slack_client, slack_channel)
    else:
        return jsonify({
            "response_action": "errors",
            "errors": {
                "email_list": f"Failed to update email list in GitHub: {result.get('error', 'Unknown error')}. Please try again."
            }
        })
    
def send_slack_message(message):
    try:
        slack_token = os.getenv('SLACK_TOKEN')
        slack_client = WebClient(token=slack_token)
        # Slack channel
        slack_channel = os.getenv('SLACK_CHANNEL')
        slack_client.chat_postMessage(
            channel=slack_channel,
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

def confirm_prod_access(team_name, team_email_lists, slack_client, slack_channel):
    # Get the current email list for the team
    breakglass_emails = team_email_lists.get(team_name, get_emails_from_github(team_name))
    
    # Initialize jira_result
    jira_result = {"success": False, "message": "Jira tickets were not created."}
    
    # Update GitHub and create PR
    github_result = update_github_and_create_pr(team_name, breakglass_emails, send_slack_message)
    
    if github_result["success"]:
        # Create Jira tickets
        jira_result = create_jira_tickets(breakglass_emails, team_name)
        
        if jira_result["success"]:
            response_message = f"Production access confirmed for next week. Jira tickets have been created. {github_result['pr_url']}"
        else:
            response_message = "GitHub update successful, but failed to create Jira tickets. Please try again or contact support."
    else:
        response_message = f"Failed to update GitHub. {github_result.get('error', 'Unknown error')}. Please try again or contact support."

    return post_confirmed_email_list_message(team_name, breakglass_emails, response_message, jira_result.get("message", ""), slack_client, slack_channel)
        