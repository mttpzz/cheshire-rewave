from cat.logs.cat_logger import get_plugin_logger     # type: ignore
from cat.mad_hatter.decorators import tool  # type: ignore
from cat.experimental.form import CatForm, CatFormState, form   # type: ignore
from pydantic import BaseModel
from typing import List
import msal
import requests
import sys
import os
import atexit
from bs4 import BeautifulSoup
import json


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
# start the logger with its plugin name
log = get_plugin_logger("email")


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TENANT_ID = os.getenv('TENANT_ID')  # 'common' if multitenant

# permissions (Scope)
SCOPES = ['Mail.Read', 'Mail.ReadWrite']
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# token file Docker path
CACHE_FILE = "/app/cat/plugins/email/token_cache.bin"


# --- CACHE AND TOKEN -----------------------------------------------------------------------------------------------------------
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
            log.info("✅ Token found in the cache (No login required).")
            return result['access_token']

    # if no token found, start device flow
    log.warning("⚠️ No token found. Login...")
    
    flow = app.initiate_device_flow(scopes=SCOPES)
    if 'user_code' not in flow:
        log.error("❌ Can't create Device Flow.")
        raise ValueError("Can't create Device Flow.")

    log.warning(f"👉 Login page: {flow['verification_uri']}")
    log.warning(f"👉 Insert the following code: {flow['user_code']}\n")
    
    result = app.acquire_token_by_device_flow(flow)

    if 'access_token' in result:
        log.warning("✅ Authentication done! Token saved.")
        return result['access_token']
    else:
        log.error(f"❌ Error during authentication: {result.get('error')}")
        sys.exit(1)


# --- FORMATTING, FETCHING AND SENDING EMAILS -----------------------------------------------------------------------------------
def format_emails(response):
    """
    Format the email data retrieved from the Microsoft Graph API into a readable string format.
    """
    emails = response.json().get('value', [])
    format_output = f"📬 Ecco le anteprime delle ultime {len(emails)} email:"
    format_output += "\n- \n- \n-"
    
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
        
        format_output += f"\n📧 EMAIL {i}" \
            f"\n📅 DATA: {date}" \
            f"\n👤 DA: {sender_name}: {sender_address}" \
            f"\n📮 A: {recipients_str}" \
            f"\n📝 OGGETTO: {subject}" \
            f"\n👁️  LETTA: {'✅ Sì' if {is_read} else '❌ No'}" \
            f"\n📄 TESTO: {body[:2000]}"
        format_output += "\n- \n- \n-"
    
    return format_output


def fetch_emails(access_token, email_address, num_emails):
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
    
    # Microsoft Graph Endpoint to read
    # graph_endpoint = 'https://graph.microsoft.com/v1.0/users/{email_address}/messages'    # all the emails
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{email_address}/mailFolders/inbox/messages'   # only the inbox

    try:
        response = requests.get(graph_endpoint, headers=headers, params=params)
        
        # Raise an exception if status code is one of the unsuccess codes (401, 403, 500, etc.)
        # NB: 202 (Accepted) is a success code
        response.raise_for_status()

        return format_emails(response)
    
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Error in fetching mails: {str(e)}")
        return f"❌ Errore durante l'accesso alla casella di posta. Riprova."


def send_email(access_token, sender, to, subject, body):
    """
    This function sends an email with a given subject and body to a specified recipient.
    """
    headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    email_data = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to
                    }
                }
            ]
        },
        "saveToSentItems": "true"
    }

    # Microsoft Graph Endpoint to send emails from the sender email address
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail'

    try:
        response = requests.post(graph_endpoint, headers=headers, json=email_data)

        # Raise an exception if status code is one of the unsuccess codes (401, 403, 500, etc.)
        # NB: 202 (Accepted) is a success code
        response.raise_for_status()

        return f"✅ Email inviata con successo a {to}"
    
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Error in sending mails: {str(e)}")
        return f"❌ Errore durante l'invio della mail. Riprova."


# --- TOOL: EMAIL READ ----------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Leggi le ultime 5 mail', 'Quali sono le ultime 2 mail?'])
def email_reader(input_prompt, cat):
    """
    Use this Tool to return the last emails received in the inbox of the email address specified in the plugin settings.
    The input is a text prompt given by the user that should specifies how many emails to retrieve.
    """
    log.info("Starting reading mail plugin.")
    cat.send_ws_message("Lettura email in corso...")

    # get email address from settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    email_address = settings['email_address']
    if not email_address:
        return f"❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."
    
    # retrieve number of emails to fetch from the text query (default is 1)
    prompt = f"""
        Extract the main number refferring to the quantity of emails to fetch from the following sentence: {input_prompt}.
        Answer ONLY with the number as an integer, without any additional text or punctuation. If you can't find any number, answer '1'.
    """
    num_emails = cat.llm(prompt)

    # download emails
    msal_app = create_msal_app()
    token = get_access_token(msal_app)
    direct_output = fetch_emails(token, email_address, num_emails)
    direct_output += "\n ---> Se vuoi che ti proponga una possibile risposta a un'email, indicami il numero della mail. " \
            "\n Esempio: se vuoi che risponda all'email 3, chiedimi di proporre una risposta alla mail 3."

    return direct_output


# --- TOOL: EMAIL WRITE ---------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Invia una mail a matteo@rewave.it con oggetto "Saluti" chiedendogli come sta'])
def email_sender(input_json, cat):
    """
    This Tool sends an email with given subject and body to a specified recipient.
    The input MUST be a Python dictionary which contains the recipient email address, the subject and the body of the email,
    for example: {"to": "matteo@rewave.it", "subject": "Saluti", "body": "Ciao Matteo, come stai?"}
    """
    log.info("Starting sending mail plugin.")
    cat.send_ws_message("Invio email in corso...")

    # parsing input
    try:
        input_data = json.loads(input_json) if isinstance(input_json, str) else input_json
        to = input_data.get("to", "").lower().strip()
        subject = input_data.get("subject", "Nessun oggetto")
        body = input_data.get("body", "")
    except Exception as e:
        log.error(f"❌ Error while parsing input: {str(e)}.")
        return f"❌ Errore nel formato dei dati. Riprova."
    
    # get email address from settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    sender_email = settings['email_address']
    if not sender_email:
        return f"❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."

    # sending email
    msal_app = create_msal_app()
    token = get_access_token(msal_app)
    direct_output = send_email(token, sender_email, to, subject, body)

    return direct_output


# --- TOOL: EMAIL CLASSIFY ------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=["Verifica se l'ultima mail parla di corsi di sicurezza", "Controlla se l'argomento dell'ultima mail riguarda un pacchetto di Microsoft"])
def email_classifier(input_topic, cat):
    """
    This Tool returns if the last email text is about a certain topic, given by the user.
    Input MUST be a string specifying the topic to check in the last received email,
    for example: input_topic="corsi di sicurezza" or input_topic="cartotecnica".
    """
    log.info("Starting classifing mail plugin.")
    cat.send_ws_message(f"Verifico se l'argomento dell'ultima email ricevuta riguarda {input_topic}...")

    # get email address from settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    target_email = settings['email_address']
    if not target_email:
        return f"❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."

    # download the last email
    msal_app = create_msal_app()
    token = get_access_token(msal_app)
    last_email = fetch_emails(token, target_email, 1)

    # take only the email text from the output of fetch_emails
    start = "TESTO: "
    end = "\n--------------------"
    email_text = last_email.split(start)[1].split(end)[0].strip()

    # create a prompt for the LLM to classify if the email text is about the input topic or not, and answer only with "SÌ" or "NO"
    prompt = f"""
        Analyze the following email text and determine if the main topic is: {input_topic}.

        Email text:
        {email_text}

        Respond EXACTLY with only one word and no punctuation: "YES" or "NO".
    """
    response = cat.llm(prompt)

    if response.strip().upper() == "YES":
        output = f"✅ L'argomento principale dell'ultima mail ricevuta riguarda {input_topic}."
    else:
        output = f"⚠️ L'argomento principale dell'ultima mail ricevuta NON riguarda {input_topic}."

    # send directly the output to the user if the tool is scheduled
    jobs = cat.white_rabbit.get_jobs()
    if jobs:
        cat.send_ws_message(output, msg_type="chat")
    
    # return will be ignore if the tool is scheduled
    return output


@tool(return_direct=True, examples=["Controlla se l'ultima mail parla di cartotecnica ogni 30 secondi", "Ogni 60 secondi, verifica se l'ultima mail riguarda i corsi di sicurezza"])
def schedule_email_classifier(tool_input, cat):
    """
    This tool schedules the email_classifier Tool to run every given seconds, checking if the last email received is about a certain topic.
    Input MUST be a Python dictionary with the topic to check and the interval in seconds,
    for example: {"topic": "corsi di sicurezza", "interval": 60}
    """
    input_obj = json.loads(tool_input)
    topic = input_obj["topic"]
    interval = input_obj["interval"]
    
    cat.white_rabbit.schedule_interval_job(job=email_classifier.run, seconds=int(interval), input_by_llm=topic, cat=cat)

    log.info(f"✅ Tool email_classifier scheduled. Every {interval} seconds it will check if the last email is about: {topic}.")
    return f"✅ Schedulazione avviata: ogni {interval} secondi controllerò se l'ultima mail riguarda {topic}."


# --- FORM: EMAIL REPLY ---------------------------------------------------------------------------------------------------------
class EmailReply(BaseModel):
    email_received: str
    sender_email: str
    recipient_email: str
    email_subject: str
    email_text: str


@form
class EmailReplyForm(CatForm):
    description = """
        This Form reads the last received emails and return a possible reply to the email indicated by the user.
        The user must confirm all the information (sender, recipient, subject and text) before sending the reply.

        Example: if the user asks 'Proponi una risposta alla mail 3', this Form will read the last 3 emails and return all the useful data to reply to the mail 3.
    """

    model_class = EmailReply

    start_examples=[
        "Proponi una risposta all'email 3",
        "Cosa posso rispondere alla mail 6?",
        "Dimmi cosa rispondere alla mail 1"
    ]
    
    stop_example = [
        "Non mandare la mail",
        "Annulla l'invio dell'email",
        "Non inviare l'e-mail",
        "No"
    ]
    
    ask_confirm = True

    def __init__(self, cat):
        super().__init__(cat)

        log.info("Starting reply form plugin.")
        cat.send_ws_message("Proposta di risposta all'email in corso...")

        # get topic of the email to reply to from the first user prompt
        first_user_prompt = cat.working_memory.user_message_json.text
        email_number = cat.llm(
            f"""
                Analyze the following sentence and extract the number specified by the user.
                Sentence: {first_user_prompt}

                Expected output examples:
                If the sentence is "Proponi una risposta alla mail 5", the output must be only "5".
                If the sentence is "Cosa posso rispondere alla mail tre?", the output must be only "3".
                
                Respond ONLY with the number, without further explanations or additional words.
                If you cannot identify a number, respond ONLY with "0".
            """
        )
        try:
            if email_number != 0:
                # get email address from settings
                settings = cat.mad_hatter.get_plugin().load_settings()
                sender_email = settings['email_address']
                if not sender_email:
                    sender_email = "Null"
                
                # download the last email
                msal_app = create_msal_app()
                token = get_access_token(msal_app)
                last_emails = fetch_emails(token, sender_email, email_number)

                # extract the email information
                start_email = f"📧 EMAIL {email_number}"
                email_data = last_emails.split(start_email)[1]

                # extract the sender email address
                start_recipient = "👤 DA: "
                end_recipient = "\n📮 A: "
                recipient_email = email_data.split(start_recipient)[1].split(end_recipient)[0].strip().split(": ")[-1]

                # extract the subject
                start_subject = "OGGETTO: "
                end_subject = "\n👁️"
                email_subject = email_data.split(start_subject)[1].split(end_subject)[0].strip()
                
                # extract the e-mail text
                start_text = "TESTO: "
                end_text = "\n--------------------"
                email_text = email_data.split(start_text)[1].split(end_text)[0].strip()

                # create a proposed reply to the e-mail
                proposed_reply = self.cat.llm(
                    f"""Reply to the following email with a polite and extremely concise response (a single sentence or just a few words).
                        If the received email does not contain any questions or requests, reply with a simple courtesy phrase without adding any additional information.
                        Start the response with "Buongiorno" and end with "Cordiali saluti".

                        Received email:
                        {email_text}
                    """
                )

                # model data population
                self._model["email_received"] = email_text
                self._model["sender_email"] = sender_email
                self._model["recipient_email"] = recipient_email
                self._model["email_subject"] = f"Re: {email_subject}"
                self._model["email_text"] = proposed_reply
            else:
                # if no mail number found, populate model data with Null strings
                self._model["email_received"] = "Null"
                self._model["sender_email"] = "Null"
                self._model["recipient_email"] = "Null"
                self._model["email_subject"] = "Null"
                self._model["email_text"] = "Null"
        
        except Exception as e:
            log.error(f"❌ Error while creating a reply: {str(e)}.")
            self._model["email_text"] = "Error"

    
    def message(self):    
        # check if the form is closed
        if self._state == CatFormState.CLOSED:
            return {"output": "Form chiuso e nessuna mail in coda da inviare."}
        
        # if the number of the email is not defined
        if self._model['email_text'] == "Null":
            return {"output": f"❌ Nessuna mail trovata. Riprova."}
        # if there is an error during the init function
        elif self._model["email_text"] == "Error":
            return {"output": f"❌ Problema durante la creazione della mail di risposta. Riprova."}
        
        # if no sender email found in settings
        if self._model['sender_email'] == "Null":
            return {"output": "❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."}
        
        # initialize output with model data
        out: str = f"\n📧 Il testo della mail ricevuta è:\n{self._model['email_received'][:100]}" \
            "\n- \n- \n-" \
            f"\n Proposta di email da inviare come risposta:" \
            f"\n👤 DA: {self._model['sender_email']}" \
            f"\n📮 A: {self._model['recipient_email']}" \
            f"\n📝 OGGETTO: {self._model['email_subject']}" \
            f"\n📄 TESTO: {self._model['email_text']}\n" \
            "\n- \n- \n-"
        
        # add missing fields
        missing_fields: List[str] = self._missing_fields
        if missing_fields:
            out += f"\n I dati mancanti sono: {missing_fields}."

        # add errors
        errors: List[str] = self._errors
        if errors:
            out += f"\n Questi dati non sono validi: {errors}.\n"

        # add confirmation message if needed
        if self._state == CatFormState.WAIT_CONFIRM:
            out += "\n ---> Posso procedere a inviare l'e-mail o devo chiudere il form?"

        return {"output": out}


    def submit(self, form_data):
        # sending the email
        msal_app = create_msal_app()
        token = get_access_token(msal_app)
        send_email(token, form_data["sender_email"], "matteo@rewave.it", form_data["email_subject"], form_data["email_text"])   # TODO change target email with form_data["recipient_email"]
        
        return {"output": "✅ Email inviata!"}
