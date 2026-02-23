import msal
import requests
import sys
import os
import atexit
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TENANT_ID = os.getenv('TENANT_ID')  # 'common' if multitenant

EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')

# permissions (Scope)
SCOPES = ['Mail.Read', 'Mail.ReadWrite']
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# token file name
CACHE_FILE = "token_cache.bin"


def create_msal_app():
    """
    msal app used to configure cache file.
    """

    # creation of a serializable cache object
    cache = msal.SerializableTokenCache()

    # search for existing cache file and load it
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache.deserialize(f.read())

    # function to save the cache on exit
    def save_cache():
        if cache.has_state_changed:
            with open(CACHE_FILE, "w") as f:
                f.write(cache.serialize())
    
    # register the function to save the cache on exit
    atexit.register(save_cache)

    # app creation with cache handling
    app = msal.PublicClientApplication(
        CLIENT_ID, 
        authority=AUTHORITY,
        token_cache=cache
    )
    return app


def get_access_token(app):
    """
    Authentication handler with cache
    """
    
    # searchaing for token in the cache
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            print("✅ Token found in the cache (No login required).")
            return result['access_token']

    # if no token found, start device flow
    print("⚠️ No token found. Login...")
    
    flow = app.initiate_device_flow(scopes=SCOPES)
    if 'user_code' not in flow:
        raise ValueError("Can't create Device Flow.")

    print(f"\n👉 Login page: {flow['verification_uri']}")
    print(f"👉 Insert the following code: {flow['user_code']}\n")
    
    result = app.acquire_token_by_device_flow(flow)

    if 'access_token' in result:
        print("✅ Authentication done! Token saved.")
        return result['access_token']
    else:
        print(f"❌ Error during authentication: {result.get('error')}")
        sys.exit(1)


def fetch_emails(access_token, target_email, num_emails=2):
    """
    Fetching the latest emails from the target email address.
    """

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    params = {
        '$top': num_emails,
        '$select': 'subject,from,toRecipients,receivedDateTime,body,isRead',
        '$orderby': 'receivedDateTime desc'
    }
    # Microsoft Graph Endpoint to read all the emails
    # graph_endpoint = 'https://graph.microsoft.com/v1.0/users/{target_email}/messages'
    # only inbox
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{target_email}/mailFolders/inbox/messages'

    response = requests.get(graph_endpoint, headers=headers, params=params)

    msg = ""
    if response.status_code == 200:
        emails = response.json().get('value', [])
        msg += f"\n📬 Last {len(emails)} emails:\n" + "-"*40
        
        for i, email in enumerate(emails, 1):
            date = email.get('receivedDateTime', '')
            subject = email.get('subject', 'Nessun oggetto')
            sender_name = email.get('from', {}).get('emailAddress', {}).get('name', 'Sconosciuto')
            sender_address = email.get('from', {}).get('emailAddress', {}).get('address', 'Sconosciuto')
            is_read = email.get('isRead', False)
            body_data = email.get('body', {})
            
            # body from html to text
            if body_data.get('contentType') == 'html':
                soup = BeautifulSoup(body_data.get('content', ''), 'html.parser')
                body = soup.get_text(separator='\n')
            else:
                body = body_data.get('content', '')

            # toRecipients is a list
            recipients_data = email.get('toRecipients', [])
            if recipients_data:
                recipients_list = [
                    r.get('emailAddress', {}).get('name') + ": " + r.get('emailAddress', {}).get('address') 
                    for r in recipients_data
                ]
            recipients_str = ", ".join(recipients_list) if recipients_list else "Nessuno"
            
            msg += f"\n📧 Email {i}:" \
                f"\n📅 DATA: {date}" \
                f"\n👤 DA: {sender_name}: {sender_address}" \
                f"\n📮 A: {recipients_str}" \
                f"\n📝 OGGETTO: {subject}" \
                f"\n👁️  LETTA: {'✅ Sì' if {is_read} else '❌ No'}" \
                f"\n📄 TESTO: {body}...\n"
            msg += "-"*40
    else:
        msg += f"\n❌ API error: {response.status_code}" \
            f"\n{response.text}"

    # return all the emails or the error message
    return msg


if __name__ == "__main__":
    # app with cache handling
    msal_app = create_msal_app()
    
    # getting the token
    token = get_access_token(msal_app)
    
    # download emails
    target_email = EMAIL_ADDRESS    # target email address
    num_emails = 1  # number of emails to fetch
    if token:
        msg = fetch_emails(token, target_email, num_emails)
        print(msg)
