from dotenv import load_dotenv
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import logging

from config import SLACK_CHANNEL, SLACK_TOKEN
from slack_handlers import handle_slack_interactions, handle_prod_access_command
from github_handlers import get_team_folders, update_github_and_create_pr, get_emails_from_github

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

if __name__ == "__main__":
    print("Starting Flask server")
    app.run(debug=True)