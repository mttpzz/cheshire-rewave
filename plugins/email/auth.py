from cat.logs.cat_logger import get_plugin_logger     # type: ignore
import msal
import sys
import os
import atexit
import requests


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
# start the logger with its plugin name
log = get_plugin_logger("email")


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TENANT_ID = os.getenv('TENANT_ID')  # 'common' if multitenant

BASE_FOLDER_CAT = os.getenv('BASE_FOLDER_CAT')

# permissions (Scope)
SCOPES = ['Mail.Read', 'Mail.ReadWrite', 'Calendars.Read', 'Calendars.ReadWrite']
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# token file Docker path
BASE_CACHE_PATH = "/app/cat/plugins/email/token"


# --- CACHE AND TOKEN -----------------------------------------------------------------------------------------------------------
def create_msal_app(user_id):
    """
    msal app used to configure cache file.
    """
    USER_CACHE_PATH = os.path.join(BASE_CACHE_PATH, user_id)
    CACHE_FILE = os.path.join(USER_CACHE_PATH, "token_cache.bin")

    # creation of a serializable cache object
    cache = msal.SerializableTokenCache()

    # search for existing cache file and load it
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache.deserialize(f.read())

    # function to save the cache on exit
    def save_cache():
        if cache.has_state_changed:
            try:
                os.makedirs(USER_CACHE_PATH, exist_ok=True)
                with open(CACHE_FILE, "w") as f:
                    f.write(cache.serialize())
                    log.warning("✅ Token file saved.")
            except OSError as e:
                log.error(f"❌ Error while saving the token file: {str(e)}")
    
    # register the function to save the cache on exit
    atexit.register(save_cache)

    # app creation with cache handling
    app = msal.PublicClientApplication(
        CLIENT_ID, 
        authority=AUTHORITY,
        token_cache=cache
    )
    return app, save_cache


def get_access_token(cat, app, save_cache):
    """
    Authentication handler with cache
    """
    # searchaing for token in the cache
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            save_cache()
            log.info("✅ Token found in the cache (No login required).")
            return result['access_token']

    # if no token found, start device flow
    log.warning("⚠️ No token found. Login required.")
    
    flow = app.initiate_device_flow(scopes=SCOPES)
    if 'user_code' not in flow:
        log.error("❌ Can't create Device Flow.")
    
    # create a login.txt file with login instructions for creating the token file
    try:
        file_text = f"👉 Collegati a questo link: {flow['verification_uri']}\n" \
                    f"👉 e inserisci il seguente codice: {flow['user_code']}\n" \
                    "N.B. Potrebbe chiedere di eseguire il login con le tue credenziali Microsoft aziendali."
        
        user_id = cat.user_id
        base_path = os.path.join(BASE_FOLDER_CAT, user_id)
        filename = 'login.txt'

        if not os.path.exists(base_path):
            os.makedirs(base_path)
        
        # os.path.basename impedisce attacchi di tipo path traversal
        full_path = os.path.join(base_path, os.path.basename(filename))
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(file_text)

    except Exception as e:
        log.error(f"❌ Error during login file creation: {str(e)}.")

    cat.send_ws_message(f"Apri il file ***{filename}*** e segui le istruzioni.")
    
    result = app.acquire_token_by_device_flow(flow)

    if 'access_token' in result:
        save_cache()
        log.warning("✅ Authentication done! Token saved.")
        if os.path.exists(full_path):
            os.remove(full_path)    # delete login file
        return result['access_token']
    else:
        log.error(f"❌ Error during authentication: {result.get('error')}")
        sys.exit(1)
