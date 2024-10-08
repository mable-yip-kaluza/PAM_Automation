import os
from config import JIRA_API_TOKEN, JIRA_EMAIL, JIRA_PROJECT_KEY, JIRA_SERVER, MANAGER_EMAIL
from utils import logger
from jira import JIRA, JIRAError



def create_jira_tickets(breakglass_emails, team_name):
    jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    created_tickets = []
    
    for email in breakglass_emails:
        issue_dict = {
            'project': {'key': JIRA_PROJECT_KEY},
            'summary': f'Grant production access for {email} - {team_name}',
            'description': f'Please grant production access for {email} for the {team_name} team.',
            'issuetype': {'name': 'Task'},
        }
        
        try:
            new_issue = jira.create_issue(fields=issue_dict)
            logger.info(f"Created Jira ticket: {new_issue.key}")
            created_tickets.append(new_issue.key)
            
            try:
                jira.assign_issue(new_issue, MANAGER_EMAIL)
            except JIRAError as e:
                logger.warning(f"Could not assign ticket {new_issue.key} to {MANAGER_EMAIL}: {str(e)}")
        except JIRAError as e:
            logger.error(f"Error creating Jira ticket for {email}: {str(e)}")
    
    if created_tickets:
        ticket_links = [f"<{JIRA_SERVER}/browse/{ticket}|{ticket}>" for ticket in created_tickets]
        ticket_list = ", ".join(ticket_links)
        message = f"Jira tickets created: {ticket_list}"
        logger.info(message)
        return {"success": True, "message": message}
    else:
        message = "Failed to create any Jira tickets"
        logger.error(message)
        return {"success": False, "message": message}
