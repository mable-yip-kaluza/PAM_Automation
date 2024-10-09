import os

JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
JIRA_EMAIL = os.getenv('JIRA_EMAIL')
JIRA_SERVER = os.getenv('JIRA_SERVER')
JIRA_PROJECT_KEY = os.getenv('JIRA_PROJECT_KEY')
MANAGER_EMAIL = os.getenv('MANAGER_EMAIL')
SLACK_TOKEN = os.getenv('SLACK_TOKEN')
SLACK_CHANNEL = os.getenv('SLACK_CHANNEL')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# Ensure these variables are uppercase to follow Python conventions for constants
jira_project_key = JIRA_PROJECT_KEY
manager_email = MANAGER_EMAIL
