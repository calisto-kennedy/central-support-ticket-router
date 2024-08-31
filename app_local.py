import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import openai
from bs4 import BeautifulSoup
import json

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables
email = os.getenv('ZENDESK_EMAIL')
password = os.getenv('ZENDESK_PASSWORD')
openai_api_key = os.getenv('OPENAI_API_KEY')

# Function to fetch ticket details from Zendesk
def get_ticket_details(ticket_id):
    url = f'https://central-supportdesk.zendesk.com/api/v2/tickets/{ticket_id}.json'
    auth = HTTPBasicAuth(email, password)
    headers = {'Content-Type': 'application/json'}
    response = requests.get(url, headers=headers, auth=auth)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching ticket details: {response.status_code} {response.text}")
    
    return response.json()

# Function to fetch requester details using requester_id
def get_requester_details(requester_id):
    url = f'https://central-supportdesk.zendesk.com/api/v2/users/{requester_id}.json'
    auth = HTTPBasicAuth(email, password)
    headers = {'Content-Type': 'application/json'}
    response = requests.get(url, headers=headers, auth=auth)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching requester details: {response.status_code} {response.text}")
    
    return response.json()['user']['name']

# Function to fetch group details using group_id
def get_group_details(group_id):
    url = f'https://central-supportdesk.zendesk.com/api/v2/groups/{group_id}.json'
    auth = HTTPBasicAuth(email, password)
    headers = {'Content-Type': 'application/json'}
    response = requests.get(url, headers=headers, auth=auth)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching group details: {response.status_code} {response.text}")
    
    return response.json()['group']['name']

# Function to extract relevant details from the ticket
def extract_ticket_info(ticket_details):
    issue_type = None
    tags = ticket_details['ticket'].get('tags', [])
    custom_fields = ticket_details['ticket'].get('custom_fields', [])
    subject = ticket_details['ticket'].get('subject', '')
    description = ticket_details['ticket'].get('description', '')
    requester_id = ticket_details['ticket'].get('requester_id', '')
    group_id = ticket_details['ticket'].get('group_id', '')

    # Iterate through custom fields to find 'issue_type' or similar fields
    for field in custom_fields:
        if isinstance(field['value'], str) and field['value'].lower() in ['issue_type', 'problem_type']:
            issue_type = field['value']
            break

    return {
        "subject": subject,
        "description": description,
        "tags": tags,
        "issue_type": issue_type,
        "requester_id": requester_id,
        "group_id": group_id
    }

# Function to formulate the prompt for OpenAI, now including routing, scope, and group information
def formulate_prompt(ticket_info, routing_info, requester_name, group_name):
    issue_type = ticket_info['issue_type'] if ticket_info['issue_type'] else "Unknown"
    tags = ', '.join(ticket_info['tags'])
    routing_info_str = "\n".join([f"{key}: {value}" for key, value in routing_info.items()])
    
    # Including scope responsibility, group, and requester's name in the prompt
    prompt = (
        f"Requester: {requester_name}\n"
        f"Ticket Subject: {ticket_info['subject']}\n"
        f"Ticket Description: {ticket_info['description']}\n"
        f"Issue Type: {issue_type}\n"
        f"Tags: {tags}\n"
        f"Current Group: {group_name}\n\n"
        f"The following is the routing information which includes scope responsibility (e.g., L1, L2, BU, PS, Finance, Engineering, Collections):\n{routing_info_str}\n\n"
        "Based on the information above, who should handle this ticket? "
        "If escalation is required, to whom should it be escalated?"
    )
    return prompt

# Function to query OpenAI with the ticket and routing information
def query_openai(prompt, openai_api_key):
    openai.api_key = openai_api_key
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert in customer support ticket management."},
            {"role": "user", "content": prompt},
        ]
    )
    return response['choices'][0]['message']['content'].strip()

# Function to determine the relevant article based on ticket_form_id
def determine_relevant_article(ticket_details):
    ticket_form_article_map = {
        '360001529340': {   # ACRM
            'subdomain': 'support.acrm.aurea.com',
            'article_id': '360020118499'
        },
        '15690572875666': { # Influitive
            'subdomain': 'support.influitive.com',
            'article_id': '15883286599058'
        },
        '10746755231378': {   # Alpha
            'subdomain': 'alpha-school-support.zendesk.com',
            'article_id': '11998839408786'
        },
        '8982987496978': {   # CFIN
            'subdomain': 'central-finance.zendesk.com',
            'article_id': '9081827578130'
        },
        '360000071353': {   # Crossover
            'subdomain': 'support.crossover.com',
            'article_id': '360008529373'
        },
        '360000337594': {   # FogBugz
            'subdomain': 'support.fogbugz.com',
            'article_id': '360013086800'
        },
        '10791313891474': {   # Kandy 
            'subdomain': 'supportportal.kandy.io',
            'article_id': '11713628235922'
        },
        '10855255360274': {   # Skyvera Monetization and CxM
            'subdomain': 'skyvera-monetization.zendesk.com',
            'article_id': '16268337936914'
        },
        '17348612826386': {   # PeerApp
            'subdomain': 'support.skyvera.com',
            'article_id': '360013199420'
        },
        # Additional mappings as needed
    }

    ticket_form_id = ticket_details['ticket']['ticket_form_id']
    
    if str(ticket_form_id) in ticket_form_article_map:
        return ticket_form_article_map[str(ticket_form_id)]
    
    return None

# Function to fetch a Zendesk Help Center article using the API
def get_help_center_article(article_id, subdomain):
    auth = HTTPBasicAuth(email, password)
    url = f"https://{subdomain}/api/v2/help_center/articles/{article_id}.json"
    headers = {'Content-Type': 'application/json'}
    response = requests.get(url, headers=headers, auth=auth)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching help center article: {response.status_code} {response.text}")
    
    return response.json()

# Function to parse routing information from the article content
def parse_routing_information(article_body):
    soup = BeautifulSoup(article_body, 'html.parser')
    
    # Try to find a table first
    table = soup.find('table')
    if table:
        routing_table = {}
        for row in table.find_all('tr'):
            columns = row.find_all('td')
            if len(columns) >= 2:
                key = columns[0].get_text(strip=True)
                value = columns[1].get_text(strip=True)
                routing_table[key] = value
        return routing_table

    # If no table is found, extract text-based routing information
    text = soup.get_text(separator="\n")
    
    # Look for patterns or keywords in the text
    routing_info = {}
    lines = text.splitlines()
    for line in lines:
        if any(keyword in line.lower() for keyword in ["route", "escalate", "team", "scope", "responsibility"]):
            # Simple heuristic: consider this line as relevant
            parts = line.split(":")
            if len(parts) == 2:
                routing_info[parts[0].strip()] = parts[1].strip()
            else:
                routing_info[line.strip()] = ""
    
    if not routing_info:
        raise Exception("No routing information found in the article")
    
    return routing_info

# Main function to process a ticket and determine routing
def process_ticket(ticket_id):
    try:
        # Fetch ticket details
        ticket_details = get_ticket_details(ticket_id)
        
        # Extract relevant information from the ticket
        ticket_info = extract_ticket_info(ticket_details)
        
        # Fetch requester's full name
        requester_name = get_requester_details(ticket_info['requester_id'])
        
        # Fetch group's full name
        group_name = get_group_details(ticket_info['group_id'])
        
        # Determine the relevant article based on the ticket_form_id
        relevant_article = determine_relevant_article(ticket_details)
        if not relevant_article:
            raise Exception("No relevant article found for the ticket's form ID.")
        
        # Fetch the article content
        article_json = get_help_center_article(relevant_article['article_id'], relevant_article['subdomain'])
        article_body = article_json['article']['body']

        # Parse the routing information from the article
        routing_info = parse_routing_information(article_body)
        
        # Formulate the prompt for OpenAI, including routing information and requester's name
        prompt = formulate_prompt(ticket_info, routing_info, requester_name, group_name)
        
        # Query OpenAI with the ticket and routing information
        response = query_openai(prompt, openai_api_key)
        
        # Output the decision
        print(f"OpenAI Decision for Ticket {ticket_id}:")
        print(response)
        print("\n")
    
    except Exception as e:
        print(f"Error processing ticket {ticket_id}: {str(e)}")

# Example execution
if __name__ == "__main__":
    ticket_id = '4458072'  # Example ticket ID
    process_ticket(ticket_id)
