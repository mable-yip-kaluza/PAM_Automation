import os
from github import Github
from config import GITHUB_TOKEN, GITHUB_REPO
from utils import logger
from datetime import datetime, timedelta
import base64
from github import Github, GithubException
import json


def get_team_folders():
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        contents = repo.get_contents("teams")
        folders = [item.name for item in contents if item.type == "dir"]
        logger.debug(f"Retrieved team folders: {folders}")
        return folders
    except Exception as e:
        logger.error(f"Error retrieving team folders: {str(e)}")
        return []
    
def update_github_and_create_pr(team_name, emails):
    try:
        logger.info(f"GITHUB_REPO environment variable: {GITHUB_REPO}")
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        logger.info(f"Successfully connected to GitHub repo: {repo.full_name}")

        file_path = f"teams/{team_name}/{team_name}.json"
        logger.info(f"Attempting to get contents of file: {file_path}")
        file_content = repo.get_contents(file_path)
        logger.info("Successfully retrieved file contents")

        content = file_content.decoded_content.decode()

        base_branch = repo.get_branch("main")
        prs_created = []

        for email in emails:
            # Create a new branch for each email
            branch_name = f"update-breakglass-{team_name}-{email.split('@')[0]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            logger.info(f"Attempting to create new branch: {branch_name}")
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_branch.commit.sha)
            logger.info(f"Successfully created new branch: {branch_name}")

            # Update content for this email
            updated_content = update_content_for_email(content, email)

            if updated_content == content:
                logger.info(f"No changes needed for email: {email}")
                continue

            # Update the file in the new branch
            repo.update_file(
                path=file_path,
                message=f"Update BreakGlass email for {team_name}: {email}",
                content=updated_content,
                sha=file_content.sha,
                branch=branch_name
            )

            # Create a pull request for this email
            pr = repo.create_pull(
                title=f"Update BreakGlass email for {team_name}: {email}",
                body=f"Automatically generated PR to update BreakGlass email: {email}",
                head=branch_name,
                base="main"
            )

            pr_link = f"<{pr.html_url}|PR-{pr.number}>"
            logger.info(f"Created GitHub PR: {pr.html_url}")
            prs_created.append(pr_link)

        if prs_created:
            message = f"PRs created: {', '.join(prs_created)}"
            return {"success": True, "message": message}
        else:
            message = "No changes were needed in the statements.json file."
            return {"success": True, "message": message}

    except Exception as e:
        logger.error(f"Failed to create GitHub PR: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error args: {e.args}")
        return {"success": False, "message": str(e)}

def update_content_for_email(content, email):
    try:
        content_dict = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Invalid JSON content")
        return content

    updated = False
    for aws_account in content_dict.get('Resources', {}).get('Aws', []):
        if aws_account.get('Production', False) and 'BreakGlass' in aws_account:
            breakglass = aws_account['BreakGlass']
            write_list = breakglass.get('Write', [])

            # Update existing email or add new one
            email_updated = False
            for entry in write_list:
                if entry.get('Email') == email:
                    entry['Expiry'] = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    email_updated = True
                    updated = True
                    break
            
            if not email_updated:
                write_list.append({
                    "Email": email,
                    "Expiry": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                })
                updated = True
            
            breakglass['Write'] = write_list

    if not updated:
        logger.warning(f"No BreakGlass section found or updated for email: {email}")

    updated_content = json.dumps(content_dict, indent=4)+ '\n' 
    return updated_content

def get_emails_from_github(team_name):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        file_path = f"teams/{team_name}/{team_name}.json"
        
        logger.debug(f"Attempting to fetch file: {file_path}")
        
        try:
            file_content = repo.get_contents(file_path)
            content = base64.b64decode(file_content.content).decode('utf-8')
            logger.debug(f"Raw file content: {content}")
            
            data = json.loads(content)
            logger.debug(f"Parsed JSON data: {json.dumps(data, indent=2)}")
            
            breakglass_emails = []
            if 'Resources' in data and 'Aws' in data['Resources']:
                for aws_account in data['Resources']['Aws']:
                    if 'Production' in aws_account and aws_account['Production']:
                        if 'BreakGlass' in aws_account and 'Write' in aws_account['BreakGlass']:
                            for entry in aws_account['BreakGlass']['Write']:
                                if 'Email' in entry:
                                    breakglass_emails.append(entry['Email'])
                                    logger.debug(f"Added email: {entry['Email']}")
            
            if not breakglass_emails:
                logger.warning("No BreakGlass emails found for production AWS accounts")
            
            logger.debug(f"Extracted emails: {breakglass_emails}")
            
            return breakglass_emails
        except GithubException as e:
            logger.error(f"Error fetching file from GitHub: {e}")
            return []
    except Exception as e:
        logger.error(f"Error connecting to GitHub: {str(e)}")
        return []