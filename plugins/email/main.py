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
from dotenv import load_dotenv


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
# load environment variables from .env file
load_dotenv()

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TENANT_ID = os.getenv('TENANT_ID')  # 'common' if multitenant

# permissions (Scope)
SCOPES = ['Mail.Read', 'Mail.ReadWrite']
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# token file Docker path
CACHE_FILE = "/app/cat/plugins/email/token_cache.bin"


# --- CACHE FILE ----------------------------------------------------------------------------------------------------------------
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


# --- FETCHING AND FORMATTING EMAILS --------------------------------------------------------------------------------------------
def format_emails(response):
    """
    Format the email data retrieved from the Microsoft Graph API into a readable string format.
    """
    emails = response.json().get('value', [])
    format_output = f"\n📬 Last {len(emails)} emails:\n"
    format_output += "-" * 20
    
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
        
        format_output += f"\n📧 Email {i}:" \
            f"\n📅 DATA: {date}" \
            f"\n👤 DA: {sender_name}: {sender_address}" \
            f"\n📮 A: {recipients_str}" \
            f"\n📝 OGGETTO: {subject}" \
            f"\n👁️  LETTA: {'✅ Sì' if {is_read} else '❌ No'}" \
            f"\n📄 TESTO: {body[:2000]}\n"
        format_output += "-" * 20
    
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
    # all the emails
    # graph_endpoint = 'https://graph.microsoft.com/v1.0/users/{email_address}/messages'
    # only the inbox
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{email_address}/mailFolders/inbox/messages'

    response = requests.get(graph_endpoint, headers=headers, params=params)

    if response.status_code == 200:
        format_output = format_emails(response)
        return format_output
    else:
        error_msg = f"\n❌ API error: {response.status_code}" \
            f"\n{response.text}"
        return error_msg


# --- EMAIL: READ ---------------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Leggi le ultime 5 mail', 'Quali sono le ultime 2 mail ricevute?'])
def email_reader(input_prompt, cat):
    """
    Return the last emails received in the inbox of the email address specified in the plugin settings.
    The input is a text prompt given by the user that should specifies how many emails to retrieve.
    """
    cat.send_ws_message("Lettura email in corso...")

    try:
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

        # app with cache handling
        msal_app = create_msal_app()
        
        # getting the token
        token = get_access_token(msal_app)
        
        # download emails
        if token:
            direct_output = fetch_emails(token, email_address, num_emails)
    except Exception as e:
        return f"❌ Errore durante il recupero delle mail: {str(e)}"

    return direct_output


# --- EMAIL: WRITE --------------------------------------------------------------------------------------------------------------
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

    response = requests.post(graph_endpoint, headers=headers, json=email_data)

    if response.status_code == 202:
        return f"✅ Email inviata con successo a {to}"
    else:
        return f"❌ Errore durante l'invio dell'email: {response.status_code} - {response.text}"


@tool(return_direct=True, examples=['Invia una mail a matteo@rewave.it con oggetto "Saluti" chiedendogli come sta'])
def email_sender(input_prompt, cat):
    """
    This tool sends an email with a given subject and body to a specified recipient.
    Input MUST be an object with the recipient email address, the subject and the body of the email,
    for example: {"to": "matteo@rewave.it"; "subject": "Saluti"; "body": "Ciao Matteo, come stai?"}
    """
    cat.send_ws_message("Invio email in corso...")

    input_obj = json.loads(input_prompt)
    to = input_obj["to"]
    subject = input_obj["subject"]
    body = input_obj["body"]
    
    # get email address from settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    sender_email = settings['email_address']
    if not sender_email:
        return f"❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."

    # app with cache handling
    msal_app = create_msal_app()
    
    # getting the token
    token = get_access_token(msal_app)

    if token:
        direct_output = send_email(token, sender_email, to, subject, body)
    
    return direct_output


# --- EMAIL: CLASSIFY -----------------------------------------------------------------------------------------------------------
# @tool(return_direct=True, examples=["Verifica se l'ultima mail parla di corsi di sicurezza", "Controlla se l'argomento dell'ultima mail riguarda un pacchetto di Microsoft"])
# def email_classifier(input_topic, cat):
    """
    Return if the email text speaks about a certain topic.
    Input MUST be a string specifying the topic to check in the last received email, for example: "input_topic"="corsi di sicurezza" or "input_topic"="pacchetto Microsoft".
    """
    cat.send_ws_message(f"Verifico se l'argomento dell'ultima email ricevuta riguarda {input_topic}...")

    # get email address from settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    target_email = settings['email_address']
    if not target_email:
        return f"❌ Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."

    # app with cache handling
    msal_app = create_msal_app()
    
    # getting the token
    token = get_access_token(msal_app)
    
    # download last email
    if token:
        last_email = fetch_emails(token, target_email, 1)

    # take only the email text from the output of fetch_emails
    start = "TESTO: "
    end = "\n--------------------"
    email_text = last_email.split(start)[1].split(end)[0].strip()

    # create a prompt for the LLM to classify if the email text is about the input topic or not, and answer only with "SÌ" or "NO"
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

    # send directly the output to the user via websocket if the tool is scheduled, otherwise send it via email
    jobs = cat.white_rabbit.get_jobs()
    if jobs:
        cat.send_ws_message(output, msg_type="chat")
    else:
        send_email(token, target_email, target_email, "Argomento ultima mail", output)
    
    return output


# @tool(return_direct=True, examples=["Controlla se l'ultima mail parla di cartotecnica ogni 30 secondi", "Ogni 60 secondi, verifica se l'ultima mail riguarda i corsi di sicurezza"])
# def schedule_email_classifier(tool_input, cat):
    """
    This tool schedules the email_classifier tool to run every given seconds, checking if the last email received is about a certain topic.
    Input MUST be an object with the topic to check and the interval in seconds, for example: {"topic": "corsi di sicurezza", "interval": 60}
    """
    input_obj = json.loads(tool_input)
    topic = input_obj["topic"]
    interval = input_obj["interval"]
    
    cat.white_rabbit.schedule_interval_job(job=email_classifier.run, seconds=int(interval), input_by_llm=topic, cat=cat)

    return f"Schedulazione avviata: ogni {interval} secondi controllerò se l'ultima mail riguarda {topic}."


# --- EMAIL: REPLY FORM ---------------------------------------------------------------------------------------------------------
class EmailReply(BaseModel):
    topic: str
    email_received: str
    sender_email: str
    target_email: str
    email_subject: str
    email_text: str

@form
class EmailReplyForm(CatForm):
    description = """
        Questo form analizzerà l'ultima email ricevuta e se l'argomento principale riguarda il topic specificato,
        ti proporrà una possibile risposta da inviare al mittente.
        Potrai modificare testo e dati della mail prima di inviarla, e decidere se inviarla o meno.
    """

    model_class = EmailReply

    start_examples=[
        "Verifica se l'ultima e-mail parla di corsi di sicurezza",
        "Controlla se l'argomento dell'ultima e-mail riguarda un pacchetto di Microsoft"
    ]
    
    stop_example = [
        "Non voglio più mandare l'e-mail",
        "Annulla l'invio dell'e-mail",
        "Non inviare l'e-mail"
    ]
    
    ask_confirm = True

    def __init__(self, cat):
        super().__init__(cat)

        # get topic of the email to reply to from the first user prompt
        first_user_prompt = cat.working_memory.user_message_json.text
        email_topic = cat.llm(f"""Analizza la seguente frase e estrai l'argomento da verificare nelle e-mail (topic).
            Frase: {first_user_prompt}

            Esempi di output atteso:
            Se la frase è "Verifica se l'ultima mail parla di corsi di sicurezza", l'output deve essere solo "corsi di sicurezza".
            Se la frase è "Controlla se l'argomento dell'ultima mail riguarda un pacchetto di Microsoft", l'output deve essere solo "pacchetto Microsoft".
            
            Rispondi SOLO con il topic, senza ulteriori spiegazioni o parole aggiuntive.
            Se non riesci a identificare un topic, rispondi "Nessun topic identificato".
        """)

        # get email address from settings
        settings = cat.mad_hatter.get_plugin().load_settings()
        sender_email = settings['email_address']
        if not sender_email:
            sender_email = "Non trovato"

        # app with cache handling
        msal_app = create_msal_app()
        
        # getting the token
        token = get_access_token(msal_app)
        
        # download the last e-mail
        if token:
            last_email = fetch_emails(token, sender_email, 1)

        # take the sender email address from the last email which is the target of the reply
        start_target = "👤 DA: "
        end_target = "\n📮 A: "
        target_email = last_email.split(start_target)[1].split(end_target)[0].strip().split(": ")[-1]

        # take the subject of the last e-mail
        start_subject = "OGGETTO: "
        end_subject = "\n👁️"
        email_subject = last_email.split(start_subject)[1].split(end_subject)[0].strip()
        
        # take only the e-mail text
        start_text = "TESTO: "
        end_text = "\n--------------------"
        email_text = last_email.split(start_text)[1].split(end_text)[0].strip()

        # create a prompt for the LLM to classify if the e-mail text is about the input topic or not, and answer only with "SÌ" or "NO"
        response = self.cat.llm(f"""
            Analizza la seguente email e dimmi se l'argomento principale riguarda: {email_topic}.
            
            Testo dell'email:
            {email_text}

            Rispondi ESATTAMENTE solo con una parola e senza punteggiatura: "SÌ" o "NO".
        """)

        # if the response is "SÌ", create a proposed reply to the e-mail
        if response.strip().upper() == "SÌ":
            proposed_reply = self.cat.llm(f"""
                Rispondi alla seguente email proponendo una risposta cordiale ed estremamente sintetica (una frase o qualche parola).
                Se la mail ricevuta non contiene domande o richieste, rispondi con una frase di cortesia senza aggiungere ulteriori informazioni.
                Inizia la risposta con "Buongiorno" e termina con "Cordiali saluti".
                
                Mail ricevuta:
                {email_text}
            """)
        else:
            proposed_reply = ""

        # model data population
        self._model["topic"] = email_topic
        self._model["email_received"] = email_text
        self._model["sender_email"] = sender_email
        self._model["target_email"] = target_email
        self._model["email_subject"] = f"Re: {email_subject}"
        self._model["email_text"] = proposed_reply
    
    
    def message(self):    
        # check if the form is closed
        if self._state == CatFormState.CLOSED:
            return {
                "output": "Form chiuso e nessuna mail in coda da inviare."
            }
        
        # if the topic of the email is not relevant, don't propose a reply and close the form
        if self._model['email_text'] == "":
            return {
                "output": f"L'argomento principale dell'ultima mail ricevuta NON riguarda {self._model['topic']}."
            }
        
        # if no sender email found in settings
        if self._model['sender_email'] == "Non trovato":
            return {
                "output": "Problema con l'indirizzo mail. Prova a inserirlo nuovamente nelle impostazioni."
            }
        
        # initialize output with model data
        out: str = f"L'ultima mail ricevuta ha come argomento {self._model['topic']}." \
            f"\n📧 Il testo della mail è:\n{self._model['email_received'][:200]}" \
            f"\n ------------------------------------------------------------" \
            f"\n Proposta di email da inviare come risposta:" \
            f"\n👤 DA: {self._model['sender_email']}" \
            f"\n📮 A: {self._model['target_email']}" \
            f"\n📝 OGGETTO: {self._model['email_subject']}" \
            f"\n📄 TESTO: {self._model['email_text']}" \
            f"\n ------------------------------------------------------------"
        
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
            out += "\n --> Posso procedere a inviare l'e-mail?"

        return {
            "output": out
        }


    def submit(self, form_data):
        # app with cache handling
        msal_app = create_msal_app()
        
        # getting the token
        token = get_access_token(msal_app)
        
        # send email
        if token:
            send_email(token, form_data["sender_email"], "matteo@rewave.it", form_data["email_subject"], form_data["email_text"])   # TODO change target email with form_data["target_email"]
        
        return {
            "output": "✅ Email inviata!"
        }
