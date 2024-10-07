import base64
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import json
from github import Github
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
from jira import JIRA, JIRAError
from slack_sdk.models.blocks import InputBlock, SectionBlock, ContextBlock
from slack_sdk.models.blocks.block_elements import PlainTextInputElement
from slack_sdk.models.views import View
from slack_sdk.models.blocks.basic_components import PlainTextObject, MarkdownTextObject
from slack_sdk.errors import SlackApiError
from github import Github, GithubException

# Load environment variables
load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# Initialize Slack Client
slack_token = os.getenv('SLACK_TOKEN')
slack_client = WebClient(token=slack_token)

# Jira configuration
jira_api_token = os.getenv('JIRA_API_TOKEN')
jira_email = os.getenv('JIRA_EMAIL')
jira_server = os.getenv('JIRA_SERVER')
jira_project_key = os.getenv('JIRA_PROJECT_KEY')
manager_email = os.getenv('MANAGER_EMAIL')   

# Slack channel
slack_channel = os.getenv('SLACK_CHANNEL')


GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

team_email_lists = {}

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
            
            if action_id == 'edit_people':
                app.logger.debug(f"Extracted team name: {team_name}")
                return open_edit_modal(payload['trigger_id'], breakglass_emails, team_name)
            elif action_id == 'confirm_prod_access':
                # Extract team name from message metadata
                team_name = payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("team_name", "")
                # Get the current email list for the team
                breakglass_emails = team_email_lists.get(team_name, [])
                
                if create_jira_tickets(breakglass_emails, team_name):
                    response_message = "Production access confirmed for next week. Jira tickets have been created."
                else:
                    response_message = "Failed to create Jira tickets. Please try again or contact support."
                
                return jsonify({
                    "response_action": "update",
                    "view": {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Confirmation"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": response_message}
                            }
                        ]
                    }
                })
        
            else:
                response_message = "Unknown action"
                return jsonify({"status": "error", "message": response_message})
        else:
            return jsonify({"status": "error", "message": "Unknown payload type"})
    elif "trigger_id" in request.form:
        return open_team_selection_modal(request.form['trigger_id'])
    else:
        return jsonify({"status": "error", "message": "Invalid request"})

def get_team_selection_view(team_name: str = "") -> View:
    blocks = [
        InputBlock(
            block_id="team_name",
            label=PlainTextObject(text="Team Name"),
            element=PlainTextInputElement(
                action_id="team_name_input",
                placeholder=PlainTextObject(text="Enter the complete team name"),
                initial_value=team_name
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
        if not emails:
            error_message = f"No emails found for team {team_name}. Please check the team name and try again."
            slack_client.chat_postMessage(
                channel=slack_channel,
                text=error_message
            )
            return jsonify({"response_action": "errors", "errors": {"team_name": error_message}})

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
        return jsonify({"response_action": "clear"})
    except SlackApiError as e:
        app.logger.error(f"Error posting email list message: {e}")
        return jsonify({"response_action": "errors", "errors": {"team_name": str(e)}})
    
def handle_view_submission(payload):
    view = payload["view"]
    if view["callback_id"] == "team_selection_modal":
        # Handle team selection submission
        team_name = view["state"]["values"]["team_name"]["team_name_input"]["value"]
        app.logger.debug(f"Selected team: {team_name}")
        
        # Fetch the breakglass emails for the selected team
        breakglass_emails = get_emails_from_github(team_name)
        
        # Post the initial email list message
        return post_email_list_message(team_name, breakglass_emails)
    
    elif view["callback_id"] == "edit_people_modal":
        # Handle email edit submission
        updated_emails = view["state"]["values"]["email_list"]["email_input"]["value"].split("\n")
        team_name = view.get("private_metadata", "Unknown Team")
        
        app.logger.info(f"Updated email list for team {team_name}: {updated_emails}")
        
        # Post an updated message with the new email list
        return post_updated_email_list_message(team_name, updated_emails)
    
    return jsonify({"response_action": "errors", "errors": {"email_list": "Invalid submission"}})

def post_updated_email_list_message(team_name, emails):
    global team_email_lists
    team_email_lists[team_name] = emails  # Store the updated email list
    
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
        return jsonify({"response_action": "clear"})
    except SlackApiError as e:
        app.logger.error(f"Error posting updated email list message: {e}")
        return jsonify({"response_action": "errors", "errors": {"email_list": "Failed to update email list"}})
    
def get_jira_account_id(jira, email):
    try:
        users = jira.search_users(query=email, maxResults=1)
        if users:
            return users[0].accountId
        else:
            app.logger.error(f"No user found with email: {email}")
            return None
    except JIRAError as e:
        app.logger.error(f"Error searching for user: {str(e)}")
        return None
    
def create_jira_tickets(breakglass_emails, team_name):
    try:
        jira = JIRA(server=jira_server, basic_auth=(jira_email, jira_api_token))
        
        for email in breakglass_emails:
            summary = f"Grant production access to {email} for team {team_name}"
            description = f"Please grant production access to {email} for the {team_name} team for the upcoming week."
            
            issue_dict = {
                'project': {'key': jira_project_key},
                'summary': summary,
                'description': description,
                'issuetype': {'name': 'Task'},
            }
            
            new_issue = jira.create_issue(fields=issue_dict)
            app.logger.info(f"Created Jira ticket: {new_issue.key}")
            
            # Assign the ticket to the manager
            manager_account_id = get_jira_account_id(jira, manager_email)
            if manager_account_id:
                try:
                    jira.assign_issue(new_issue, manager_account_id)
                    app.logger.info(f"Assigned ticket {new_issue.key} to {manager_email}")
                except JIRAError as e:
                    app.logger.warning(f"Could not assign ticket {new_issue.key} to {manager_email}: {str(e)}")
            else:
                app.logger.warning(f"Could not assign ticket {new_issue.key} to {manager_email}: Account ID not found")
        
        return True
    except JIRAError as e:
        app.logger.error(f"JIRA Error: {str(e)}")
        return False
    except Exception as e:
        app.logger.error(f"Failed to create Jira tickets: {str(e)}")
        return False
    
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


def open_edit_modal(trigger_id, breakglass_emails, team_name):
    global team_email_lists
    
    # Use the stored email list if available, otherwise use the breakglass emails
    email_list = "\n".join(team_email_lists.get(team_name, breakglass_emails))
    
    try:
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
                            "initial_value": email_list
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

def get_emails_from_github(team_name):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        file_path = f"teams/{team_name}/{team_name}.json"
        
        app.logger.debug(f"Attempting to fetch file: {file_path}")
        
        try:
            file_content = repo.get_contents(file_path)
            content = base64.b64decode(file_content.content).decode('utf-8')
            app.logger.debug(f"Raw file content: {content}")
            
            data = json.loads(content)
            app.logger.debug(f"Parsed JSON data: {json.dumps(data, indent=2)}")
            
            breakglass_emails = []
            if 'Resources' in data and 'Aws' in data['Resources']:
                for aws_account in data['Resources']['Aws']:
                    if 'Production' in aws_account and aws_account['Production']:
                        if 'BreakGlass' in aws_account and 'Write' in aws_account['BreakGlass']:
                            for entry in aws_account['BreakGlass']['Write']:
                                if 'Email' in entry:
                                    breakglass_emails.append(entry['Email'])
                                    app.logger.debug(f"Added email: {entry['Email']}")
            
            if not breakglass_emails:
                app.logger.warning("No BreakGlass emails found for production AWS accounts")
            
            app.logger.debug(f"Extracted emails: {breakglass_emails}")
            
            return breakglass_emails
        except GithubException as e:
            app.logger.error(f"Error fetching file from GitHub: {e}")
            return []
    except Exception as e:
        app.logger.error(f"Error connecting to GitHub: {str(e)}")
        return []

def update_github_and_create_pr(emails):
    try:
        g = Github(os.getenv('GITHUB_TOKEN'))
        repo = g.get_repo(os.getenv('GITHUB_REPO'))

        # Get the content of the file
        file_path = "teams/statements/statements.json"
        file_content = repo.get_contents(file_path)
        content = file_content.decoded_content.decode()

        # Find the BreakGlass Write section
        breakglass_start = content.find('"BreakGlass": {')
        write_start = content.find('"Write": [', breakglass_start)
        write_end = content.find(']', write_start)
        
        # Extract the current Write entries
        write_content = content[write_start+10:write_end].strip()
        current_entries = [entry.strip() for entry in write_content.split('},') if entry.strip()]

        # Determine the indentation
        base_indent = ' ' * (write_start - content.rfind('\n', 0, write_start) - 1)
        entry_indent = base_indent + '    '

        # Update existing entries and add new ones
        updated_entries = []
        existing_emails = set()
        for entry in current_entries:
            email_start = entry.find('"Email": "') + 9
            email_end = entry.find('"', email_start)
            email = entry[email_start:email_end]
            existing_emails.add(email)
            
            if email in emails:
                # Update expiry for existing email
                new_expiry = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                updated_entry = (f'{entry_indent}{{\n'
                                 f'{entry_indent}    "Email": "{email}",\n'
                                 f'{entry_indent}    "Expiry": "{new_expiry}"\n'
                                 f'{entry_indent}}}')
                updated_entries.append(updated_entry)
            else:
                updated_entries.append(f'{entry_indent}{entry}')

        # Add new entries
        for email in emails:
            if email not in existing_emails:
                new_expiry = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                new_entry = (f'{entry_indent}{{\n'
                             f'{entry_indent}    "Email": "{email}",\n'
                             f'{entry_indent}    "Expiry": "{new_expiry}"\n'
                             f'{entry_indent}}}')
                updated_entries.append(new_entry)

        # Reconstruct the Write section
        new_write_content = f'{base_indent}"Write": [\n' + ',\n'.join(updated_entries) + f'\n{base_indent}]'
        updated_content = content[:write_start] + new_write_content + content[write_end+1:]

        if updated_content == content:
            send_slack_message("No changes were needed in the statements.json file.")
            return

        # Create a new branch
        base_branch = repo.get_branch("main")
        branch_name = f"update-breakglass-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_branch.commit.sha)

        # Update the file in the new branch
        repo.update_file(
            path=file_path,
            message="Update BreakGlass expiry dates and add new entries",
            content=updated_content,
            sha=file_content.sha,
            branch=branch_name
        )

        # Create a pull request
        pr = repo.create_pull(
            title="Update BreakGlass expiry dates and add new entries",
            body="Automatically generated PR to update BreakGlass expiry dates and add new entries",
            head=branch_name,
            base="main"
        )

        send_slack_message(f"Created GitHub PR: {pr.html_url}")

    except Exception as e:
        error_message = f"Failed to create GitHub PR: {str(e)}"
        app.logger.error(error_message)
        send_slack_message(error_message)

if __name__ == "__main__":
    print("Starting Flask server")
    app.run(debug=True)