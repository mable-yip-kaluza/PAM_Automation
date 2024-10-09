import os
from config import JIRA_API_TOKEN, JIRA_EMAIL, JIRA_PROJECT_KEY, JIRA_SERVER, get_team_config
from utils import logger
from jira import JIRA, JIRAError



def create_jira_tickets(breakglass_emails, team_name, prs):
    jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    created_tickets = []

    # Get team-specific configuration
    team_config = get_team_config(team_name)
    manager_email = team_config.get('manager_email') if team_config else None

    
    for email in breakglass_emails:
        # Find the corresponding PR for this email
        pr = next((pr for pr in prs if pr['email'] == email), None)
        
        if pr is None:
            logger.warning(f"No PR found for email {email}")
            continue

        issue_dict = {
            'project': {'key': JIRA_PROJECT_KEY},
            'summary': f'Grant production access for {email} - {team_name}',
            'description': f'Please grant production access for {email} for the {team_name} team.\n\nCorresponding GitHub PR: {pr["link"]}',
            'issuetype': {'name': 'Task'},
        }
        
        try:
            new_issue = jira.create_issue(fields=issue_dict)
            logger.info(f"Created Jira ticket: {new_issue.key}")
            created_tickets.append({"key": new_issue.key, "pr_number": pr["number"]})
            
            try:
                jira.assign_issue(new_issue, manager_email)
            except JIRAError as e:
                logger.warning(f"Could not assign ticket {new_issue.key} to {manager_email}: {str(e)}")
        except JIRAError as e:
            logger.error(f"Error creating Jira ticket for {email}: {str(e)}")
    
    if created_tickets:
        return {"success": True, "tickets": created_tickets}
    else:
        message = "Failed to create any Jira tickets"
        logger.error(message)
        return {"success": False, "message": message}