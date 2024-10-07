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


email_prod_access_weekly_rotation = [
    'mable.yip@kaluza.com'
]

email_prod_access_always = ['ben.clare@kaluza.com']

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
            
            if action_id == 'confirm_prod_access':
                response_message = "Production access confirmed for next week. Jira tickets will be created."
                create_jira_tickets()
                return jsonify({"status": "success", "message": response_message})
            elif action_id == 'edit_people':
                return open_edit_modal(payload['trigger_id'])
            else:
                response_message = "Unknown action"
                return jsonify({"status": "error", "message": response_message})
        else:
            return jsonify({"status": "error", "message": "Unknown payload type"})
    else:
        return post_email_list_message()

def post_email_list_message():
    try:
        emails = email_prod_access_weekly_rotation + email_prod_access_always
        email_list = "\n• ".join(emails)
        response = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Please confirm the following people for next week's production access:\n{email_list}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Who will have production access next week?\n\n*People for next week's production access:*\n• {email_list}"
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
            ]
        )
        return jsonify({"status": "message sent", "ts": response['ts'], "channel": response['channel']})
    except SlackApiError as e:
        return jsonify({"status": "error", "error": e.response['error']})

def handle_view_submission(payload):
    app.logger.debug(f"Received view submission payload: {payload}")
    view = payload["view"]
    if view["callback_id"] == "edit_people_modal":
        new_emails = view["state"]["values"]["email_list"]["email_input"]["value"].split("\n")
        new_emails = [email.strip() for email in new_emails if email.strip()]
        
        app.logger.debug(f"New emails: {new_emails}")
        
        global email_prod_access_weekly_rotation, email_prod_access_always
        email_prod_access_weekly_rotation = new_emails
        email_prod_access_always = []  # Reset this list as we're not differentiating in the UI
        
        app.logger.debug(f"Updated email_prod_access_weekly_rotation: {email_prod_access_weekly_rotation}")
        
        update_email_list_message(payload['user']['id'])
        
        return jsonify({
            "response_action": "clear"
        })
    
    return jsonify({"status": "error", "message": "Unknown view submission"})

def update_email_list_message(user_id):
    try:
        emails = email_prod_access_weekly_rotation + email_prod_access_always
        email_list = "\n• ".join(emails)
        
        app.logger.debug(f"Updating message with email list: {email_list}")
        
        try:
            history = slack_client.conversations_history(channel=slack_channel, limit=10)
            for message in history['messages']:
                if message.get('bot_id'):
                    updated_message = slack_client.chat_update(
                        channel=slack_channel,
                        ts=message['ts'],
                        text=f"Please confirm the following people for next week's production access:\n{email_list}",
                        blocks=[
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"Who will have production access next week?\n\n*People for next week's production access:*\n• {email_list}"
                                }
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": f"Last edited by <@{user_id}>"
                                    }
                                ]
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
                        ]
                    )
                    app.logger.debug(f"Updated message response: {updated_message}")
                    return
        except SlackApiError as e:
            app.logger.error(f"Error updating message: {e}")
        
        new_message = slack_client.chat_postMessage(
            channel=slack_channel,
            text=f"Please confirm the following people for next week's production access:\n{email_list}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Who will have production access next week?\n\n*People for next week's production access:*\n• {email_list}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Last edited by <@{user_id}>"
                        }
                    ]
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
            ]
        )
        app.logger.debug(f"Posted new message: {new_message}")
    except SlackApiError as e:
        app.logger.error(f"Error posting message: {e}")

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
    
def create_jira_tickets():
    if not all([jira_api_token, jira_email, jira_server, manager_email]):
        app.logger.error("Missing JIRA environment variables")
        return None

    try:
        jira = JIRA(server=jira_server, basic_auth=(jira_email, jira_api_token))
        
        # Get the account ID for the manager
        manager_account_id = get_jira_account_id(jira, manager_email)
        if not manager_account_id:
            send_slack_message(f"Error: Could not find Jira user with email: {manager_email}")
            return None

        emails = email_prod_access_weekly_rotation + email_prod_access_always
        created_tickets = []
        
        for email in emails:
            issue_dict = {
                'project': {'key': jira_project_key},
                'summary': f'Production access for {email}',
                'description': f'Granting production access for {email} for next week.',
                'issuetype': {'name': 'Task'},
                'assignee': {'id': manager_account_id}
            }
            
            new_issue = jira.create_issue(fields=issue_dict)
            app.logger.info(f"Created JIRA issue: {new_issue.key} for {email}")
            created_tickets.append((email, new_issue.key))
            
            # Send Slack message for each created ticket
            send_slack_message(f"Created JIRA issue: <{jira_server}browse/{new_issue.key}|{new_issue.key}> for {email}")

        update_github_and_create_pr(emails)
        
        return created_tickets
    except Exception as e:
        error_message = f"Failed to create Jira tickets: {str(e)}"
        app.logger.error(error_message)
        send_slack_message(error_message)
        return None
    

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

def open_edit_modal(trigger_id):
    emails = email_prod_access_weekly_rotation + email_prod_access_always
    email_list = "\n".join(emails)
    
    try:
        slack_client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "edit_people_modal",
                "title": {"type": "plain_text", "text": "Edit People"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
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
        return jsonify({"status": "error", "error": str(e)})

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