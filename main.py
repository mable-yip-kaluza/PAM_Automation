import base64
import json
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import logging
import awsgi
import urllib.parse

from config import SLACK_CHANNEL, SLACK_TOKEN
from slack_handlers import handle_slack_interactions, handle_prod_access_command, send_pr_approved_message
from github_handlers import get_team_folders, verify_github_webhook

# Load environment variables
load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Slack Client
slack_client = WebClient(token=SLACK_TOKEN)


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
        return handle_slack_interactions(request.form, app.logger, slack_client, SLACK_CHANNEL, team_email_lists)
    elif "command" in request.form and request.form["command"] == "/prod-access":
        return handle_prod_access_command(request.form, slack_client)
    else:
        return jsonify({"status": "error", "message": "Invalid request"})


@app.route('/github/webhook', methods=['POST'])
def github_webhook():
    # Verify the webhook signature
    if not verify_github_webhook(request):
        return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get('X-GitHub-Event')
    payload = request.json

    if event == 'pull_request_review':
        action = payload['action']
        pr = payload['pull_request']
        review = payload['review']

        if action == 'submitted' and review['state'] == 'approved':
            # Check if the PR has the 'breakglass-update' label
            labels = [label['name'] for label in pr['labels']]
            if 'breakglass-update' in labels:
                # Extract relevant information
                pr_number = pr['number']
                pr_title = pr['title']
                pr_url = pr['html_url']
                approver = review['user']['login']

                # Send Slack message
                send_pr_approved_message(pr_number, pr_title, pr_url, approver, slack_client, SLACK_CHANNEL)

    return jsonify({"status": "success"}), 200


# def lambda_handler(event, context):
#     app.logger.debug(f"Received event: {json.dumps(event)}")

#     if event.get('isBase64Encoded', False):
#         body = base64.b64decode(event['body']).decode('utf-8')
#     else:
#         body = event['body']
    
#     app.logger.debug(f"Decoded body: {body}")

#     # Parse the body content
#     parsed_body = urllib.parse.parse_qs(body)
#     app.logger.debug(f"Parsed body: {json.dumps(parsed_body)}")

#     # If there's a 'payload' key, it's a Slack interaction
#     if 'payload' in parsed_body:
#         payload = json.loads(parsed_body['payload'][0])
#         app.logger.debug(f"Parsed payload: {json.dumps(payload)}")
#         return {
#             'statusCode': 200,
#             'body': json.dumps(payload)
#         }
#     else:
#         app.logger.debug("No 'payload' key found in parsed body")
#         return {
#             'statusCode': 200,
#             'body': json.dumps(parsed_body)
#         }

if __name__ == "__main__":
    print("Starting Flask server")
    app.run(debug=True)



