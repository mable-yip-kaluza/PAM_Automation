import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import json
from github import Github
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging

from slack_sdk.models.blocks import InputBlock, SectionBlock, ActionsBlock
from slack_sdk.models.blocks.block_elements import SelectElement, ButtonElement
from slack_sdk.models.views import View
from slack_sdk.models.blocks.basic_components import PlainTextObject, Option, OptionGroup
from slack_sdk.errors import SlackApiError


from github_handlers import get_team_folders, update_github_and_create_pr, get_emails_from_github
from jira_handlers import create_jira_tickets

# Load environment variables
load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Slack Client
slack_token = os.getenv('SLACK_TOKEN')
slack_client = WebClient(token=slack_token)
# Slack channel
slack_channel = os.getenv('SLACK_CHANNEL')



team_email_lists = {}

@app.route('/slack/team_search', methods=['POST'])
def team_search():
    payload = request.form
    query = payload.get('value', '').lower()
    
    all_teams = get_team_folders()
    matching_teams = [team for team in all_teams if query in team.lower()]
    
    options = [
        {
            "text": {"type": "plain_text", "text": team},
            "value": team
        }
        for team in matching_teams[:20]  # Limit to 20 results
    ]
    
    return jsonify({
        "options": options
    })

@app.route('/slack/actions', methods=['POST'])
def handle_interactions():
    app.logger.debug(f"Received payload: {request.form}")
    
    if "payload" in request.form:
        payload = json.loads(request.form["payload"])
        
        if payload.get("type") == "view_submission":
            return handle_view_submission(payload)
        elif payload.get("type") == "block_actions":
            action = payload["actions"][0]
            action_id = action["action_id"]
            # Extract team name from message metadata
            team_name = payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("team_name", "")
            # Fetch the breakglass emails for the current team
            breakglass_emails = get_emails_from_github(team_name)
            
            if action['action_id'] == 'edit_people':
                team_name = payload['message']['metadata']['event_payload']['team_name']
                return open_edit_modal(payload['trigger_id'], team_name)
            elif action['action_id'] == 'confirm_email_changes':
                team_name = payload['message']['metadata']['event_payload']['team_name']
                return confirm_email_changes(team_name)
            elif action['action_id'] == 'confirm_prod_access':
                team_name = payload['message']['metadata']['event_payload']['team_name']

                # Get the current email list for the team
                breakglass_emails = team_email_lists.get(team_name, get_emails_from_github(team_name))
                
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

                return post_confirmed_email_list_message(team_name, breakglass_emails, response_message, jira_result.get("message", ""))
        
            else:
                response_message = "Unknown action"
                return jsonify({"status": "error", "message": response_message})
    elif "command" in request.form and request.form["command"] == "/prod-access":
        try:
            slack_client.views_open(
                trigger_id=request.form["trigger_id"],
                view=get_team_selection_view()
            )
            return jsonify({"status": "success"})
        except SlackApiError as e:
            return jsonify({"status": "error", "error": str(e)})
    else:
        return jsonify({"status": "error", "message": "Invalid request"})



def confirm_email_changes(team_name):
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
        
        return post_confirmed_email_list_message(team_name, emails, pr_message, jira_message)
    else:
        return jsonify({
            "response_action": "errors",
            "errors": {
                "email_list": f"Failed to update email list in GitHub: {result.get('error', 'Unknown error')}. Please try again."
            }
        })


def post_confirmed_email_list_message(team_name, emails, pr_message, jira_message):
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
                },
                {
                    "type": "actions",
                    "elements": [
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
        app.logger.debug(f"Posted confirmed email list message: {response}")
        return jsonify({"response_action": "clear"})
    except SlackApiError as e:
        app.logger.error(f"Error posting confirmed email list message: {e}")
        return jsonify({"response_action": "errors", "errors": {"email_list": "Failed to confirm email list"}})

def open_team_selection_modal(trigger_id):
    try:
        slack_client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "team_selection_modal",
                "title": {"type": "plain_text", "text": "Select Team"},
                "submit": {"type": "plain_text", "text": "Confirm"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "team_name",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "team_name_input",
                            "placeholder": {"type": "plain_text", "text": "Enter the complete team name"}
                        },
                        "label": {"type": "plain_text", "text": "Team Name"}
                    }
                ]
            }
        )
        return jsonify({"status": "success"})
    except SlackApiError as e:
        return jsonify({"status": "error", "error": str(e)})
    

def post_email_list_message(team_name, emails):
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
        app.logger.debug(f"Posted email list message: {response}")
        return {"response_action": "clear"}
    except SlackApiError as e:
        app.logger.error(f"Error posting email list message: {e}")
        return {"response_action": "errors", "errors": {"team_name": str(e)}}

def handle_view_submission(payload):
    view = payload["view"]
    callback_id = view["callback_id"]

    if callback_id == "team_selection_modal":
        return handle_team_selection(view)
    elif callback_id == "edit_people_modal":
        return handle_email_editing(view)
    else:
        app.logger.error(f"Unknown view submission callback_id: {callback_id}")
        return {"response_action": "errors", "errors": {"general": "An unknown error occurred."}}
    
def handle_team_selection(view):
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
    
    return post_email_list_message(team_name, breakglass_emails)


def handle_email_editing(view):
    team_name = view["private_metadata"]
    new_emails = view["state"]["values"]["email_list"]["email_input"]["value"].split("\n")
    new_emails = [email.strip() for email in new_emails if email.strip()]

    # Update the local cache
    team_email_lists[team_name] = new_emails

    # Show a preview of the changes
    return post_email_preview_message(team_name, new_emails)

def post_email_preview_message(team_name, emails):
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
        app.logger.debug(f"Posted email preview message: {response}")
        return {"response_action": "clear"}
    except SlackApiError as e:
        app.logger.error(f"Error posting email preview message: {e}")
        return {"response_action": "errors", "errors": {"email_list": "Failed to preview email list"}}


def post_updated_email_list_message(team_name, emails):
    try:
        email_list = "\n• ".join(emails)
        response = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Updated list of people for next week's production access for team {team_name}:\n{email_list}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Updated list of people for next week's production access for team *{team_name}*:\n\n• {email_list}"
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
        app.logger.debug(f"Posted updated email list message: {response}")
        return {"response_action": "clear"}
    except SlackApiError as e:
        app.logger.error(f"Error posting updated email list message: {e}")
        return {"response_action": "errors", "errors": {"email_list": "Failed to update email list"}}
    


def send_slack_message(message):
    try:
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
        app.logger.error(f"Error sending Slack message: {e}")

def send_jira_confirmation(channel_id, created_tickets):
    jira_server = os.getenv('JIRA_SERVER')
    if not created_tickets:
        message = "Failed to create Jira tickets. Please check the logs for more information."
    else:
        ticket_list = "\n".join([f"• {email}: <{jira_server}browse/{ticket_key}|{ticket_key}>" for email, ticket_key in created_tickets])
        message = f"Jira tickets created successfully:\n{ticket_list}"
    
    try:
        slack_client.chat_postMessage(
            channel=channel_id,
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
        app.logger.error(f"Error sending Jira confirmation: {e}")


def open_edit_modal(trigger_id, team_name):
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
        app.logger.error(f"Error opening edit modal: {e}")
        return jsonify({"status": "error", "error": str(e)})





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



if __name__ == "__main__":
    print("Starting Flask server")
    app.run(debug=True)