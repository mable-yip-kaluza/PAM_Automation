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
        # Fetch account IDs for the email and manager
        requester_account_id = get_account_id(jira, email)
        manager_account_id = get_account_id(jira, manager_email) if manager_email else None

        if not requester_account_id or not manager_account_id:
            logger.error(f"Could not find account ID for email: {email} or manager: {manager_email}")
            continue

        issue_dict = {
            'project': {'key': JIRA_PROJECT_KEY},
            'summary': f'Grant production access for {email} - {team_name}',
            'description': f'Please grant production access for {email} for the {team_name} team.\n\nCorresponding GitHub PR: {pr["link"]}',
            'issuetype': {'name': 'Task'},
            # Add required custom fields with correct formats
            'customfield_17322': {'value': 'Temporary'},  # PAM: Access Need
            'customfield_15231': {'value': 'Billing'},  # Lead Squad
            'customfield_17332': {'accountId': requester_account_id},  # PAM: Who is this request for?
            'customfield_17342': {'accountId': manager_account_id},  # PAM: Who is your SEM?
            'customfield_17326': {'value': 'Write'},  # PAM: Access Type
            'customfield_14686': {'value': 'Statements'},  # Assigned Team
            'customfield_17327': [{'value': 'AWS'}, {'value': 'Direct Kafka'}, {'value': 'Retail-BigQuery'}],  # PAM: Access To (as an array)
        }
        
        try:
            new_issue = jira.create_issue(fields=issue_dict)
            logger.info(f"Created Jira ticket: {new_issue.key}")
            created_tickets.append({"key": new_issue.key, "pr_number": pr["number"]})
            
            if manager_email: 
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
    
def get_account_id(jira, email):
    try:
        users = jira.search_users(query=email, maxResults=1)
        if users:
            return users[0].accountId
    except JIRAError as e:
        logger.error(f"Error searching for user {email}: {str(e)}")
    return None