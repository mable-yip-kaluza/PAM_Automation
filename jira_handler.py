import os
from utils import logger
from jira import JIRA, JIRAError

# Jira configuration
jira_api_token = os.getenv('JIRA_API_TOKEN')
jira_email = os.getenv('JIRA_EMAIL')
jira_server = os.getenv('JIRA_SERVER')
jira_project_key = os.getenv('JIRA_PROJECT_KEY')
manager_email = os.getenv('MANAGER_EMAIL')   


# def get_jira_account_id(jira, email):
#     try:
#         users = jira.search_users(query=email, maxResults=1)
#         if users:
#             return users[0].accountId
#         else:
#             logger.error(f"No user found with email: {email}")
#             return None
#     except JIRAError as e:
#         logger.error(f"Error searching for user: {str(e)}")
#         return None


def create_jira_tickets(breakglass_emails, team_name):
    jira = JIRA(server=jira_server, basic_auth=(jira_email, jira_api_token))
    created_tickets = []
    
    for email in breakglass_emails:
        issue_dict = {
            'project': {'key': jira_project_key},
            'summary': f'Grant production access for {email} - {team_name}',
            'description': f'Please grant production access for {email} for the {team_name} team.',
            'issuetype': {'name': 'Task'},
        }
        
        try:
            new_issue = jira.create_issue(fields=issue_dict)
            logger.info(f"Created Jira ticket: {new_issue.key}")
            created_tickets.append(new_issue.key)
            
            try:
                jira.assign_issue(new_issue, manager_email)
            except JIRAError as e:
                logger.warning(f"Could not assign ticket {new_issue.key} to {manager_email}: {str(e)}")
        except JIRAError as e:
            logger.error(f"Error creating Jira ticket for {email}: {str(e)}")
    
    if created_tickets:
        ticket_links = [f"<{jira_server}/browse/{ticket}|{ticket}>" for ticket in created_tickets]
        ticket_list = ", ".join(ticket_links)
        message = f"Jira tickets created: {ticket_list}"
        logger.info(message)
        return {"success": True, "message": message}
    else:
        message = "Failed to create any Jira tickets"
        logger.error(message)
        return {"success": False, "message": message}
