from cat.mad_hatter.decorators import tool, plugin, hook # type: ignore
from pydantic import BaseModel
import msal
import requests
import sys
import os
import atexit
from bs4 import BeautifulSoup
import json
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

# token file Docker path
CACHE_FILE = "/app/cat/plugins/email/token_cache.bin"


# settings class for the plugin
class DBSettings(BaseModel):
    email_address: str = EMAIL_ADDRESS

@plugin
def settings_model():
    return DBSettings()


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


def fetch_emails(access_token, target_email, num_emails):
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
        msg += f"\n📬 Last {len(emails)} emails:\n" + "-"*20
        
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
                f"\n📄 TESTO: {body[:2000]}\n"
            msg += "-"*20
    else:
        msg += f"\n❌ API error: {response.status_code}" \
            f"\n{response.text}"

    # return all the emails or the error message
    return msg


@tool(return_direct=True, examples=['Mostrami le ultime 5 mail', 'Quali sono le ultime 2 mail ricevute?'])
def email_reader(input_prompt, cat):
    """
    Return the last emails received in the inbox of the email address specified in the plugin settings.
    The input is a text prompt given by the user that should specifies how many emails to retrieve.
    """
    
    # build target email address from the username (if admin, use my email address)
    username = cat.user_data.name
    target_email = username if username!='admin' else 'matteo'
    target_email += "@rewave.it"

    # retrieve number of emails to fetch from the text query (default is 1)
    num_emails = cat.llm(f"Extract the main number refferring to the quantity of emails to fetch from the following sentence: {input_prompt}. Answer ONLY with the number as an integer, without any additional text or punctuation. If you can't find any number, answer '1'.")

    # app with cache handling
    msal_app = create_msal_app()
    
    # getting the token
    token = get_access_token(msal_app)
    
    # download emails
    if token:
        direct_output = fetch_emails(token, target_email, num_emails)

    return direct_output


@tool(return_direct=True, examples=["Verifica se l'ultima mail parla di corsi di sicurezza", "Controlla se l'argomento dell'ultima mail riguarda un pacchetto di Microsoft"])
def email_classifier(input_topic, cat):
    """
    Return if the email text speaks about a certain topic.
    Input must be a string specifying the topic to check in the last received email, for example: "input_topic"="corsi di sicurezza" or "input_topic"="pacchetto Microsoft".
    """
    
    cat.send_ws_message(f"Verifico se l'argomento dell'ultima email ricevuta riguarda {input_topic}...")

    # build target email address from the username (if admin, use my email address)
    username = cat.user_data.name
    target_email = username if username!='admin' else 'matteo'
    target_email += "@rewave.it"

    # app with cache handling
    msal_app = create_msal_app()
    
    # getting the token
    token = get_access_token(msal_app)
    
    # download emails
    if token:
        last_email = fetch_emails(token, target_email, 1)

    start = "TESTO: "
    end = "\n--------------------"
    email_text = last_email.split(start)[1].split(end)[0].strip()

    prompt = f"""
        Analizza la seguente email e dimmi se l'argomento principale riguarda: "{input_topic}".
        
        Testo dell'email:
        "{email_text}"

        Rispondi ESATTAMENTE solo con una parola: "SÌ" o "NO".
    """
    response = cat.llm(prompt)

    if response.strip().upper() == "SÌ":
        output = f"L'argomento principale dell'ultima email ricevuta riguarda {input_topic}."
    else:
        output = f"L'argomento principale dell'ultima email ricevuta NON riguarda {input_topic}."
    
    # send directly the output to the user via websocket if the tool is scheduled, otherwise return it as usual
    jobs = cat.white_rabbit.get_jobs()
    if jobs:
        cat.send_ws_message(output, msg_type="chat")
    
    return output


@tool(return_direct=True, examples=["Controlla se l'ultima mail parla di cartotecnica ogni 30 secondi", "Ogni 60 secondi, verifica se l'ultima mail riguarda i corsi di sicurezza"])
def schedule_email_classifier(tool_input, cat):
    """
    This tool schedules the email_classifier tool to run every given seconds, checking if the last email received is about a certain topic.
    Input must be an object with the topic to check and the interval in seconds, for example: {"topic": "corsi di sicurezza", "interval": 60}
    """
    input_obj = json.loads(tool_input)
    topic = input_obj["topic"]
    interval = input_obj["interval"]
    
    cat.white_rabbit.schedule_interval_job(job=email_classifier.run, seconds=int(interval), input_by_llm=topic, cat=cat)

    return f"Schedulazione avviata: ogni {interval} secondi controllerò se l'ultima mail riguarda {topic}."
