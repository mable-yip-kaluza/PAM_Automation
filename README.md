# PAM Slack Bot

This Slack bot automates the process of managing production access for team members. It integrates with GitHub for storing team information and Jira for ticket creation.

## Features

- Team selection via Slack modal
- Editing of team members with production access
- GitHub integration for storing and updating team information
- Jira ticket creation for production access requests
- Slack notifications for various stages of the process

## Prerequisites

- Python 3.9+
- A Slack workspace with bot permissions
- GitHub repository access
- Jira account with appropriate permissions

## Installation

1. Clone the repository:

   ```
   git clone https://github.com/mable-yip-kaluza/PAM_Automation.git
   ```

2. Install the required packages:

   ```
   pip install -r requirements.txt
   ```

3. Copy `.env.dev` to `.env` and fill in your actual credentials and configuration:
   ```
   cp .env.dev .env
   ```

## Configuration

Edit the `.env` file with your specific configuration:

- `SLACK_TOKEN`: Your Slack bot token
- `JIRA_API_TOKEN`: Your Jira API token
- `JIRA_EMAIL`: Email associated with your Jira account
- `JIRA_SERVER`: URL of your Jira server
- `JIRA_PROJECT_KEY`: Key of the Jira project for ticket creation
- `MANAGER_EMAIL`: Email of the manager to assign Jira tickets
- `SLACK_CHANNEL`: Slack channel ID for notifications
- `GITHUB_TOKEN`: Your GitHub personal access token
- `GITHUB_REPO`: GitHub repository in the format `username/repo`

## Running the Application

To start the Flask server:

```
python main.py
```

The server will start on `http://localhost:5000` by default.

## Development

For development, you can use the Flask development server which is started when running `main.py`.
