from cat.logs.cat_logger import get_plugin_logger     # type: ignore
import msal
import os
import atexit


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
# start the logger with its plugin name
log = get_plugin_logger("email")


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TENANT_ID = os.getenv('TENANT_ID')  # 'common' if multitenant

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
        try:
            with open(CACHE_FILE, "r") as f:
                cache.deserialize(f.read())
        except Exception as e:
            log.error(f"❌ Cache file corrupt, ignoring: {e}")

    # function to save the cache on exit
    def save_cache():
        if cache.has_state_changed:
            try:
                os.makedirs(USER_CACHE_PATH, exist_ok=True)
                with open(CACHE_FILE, "w") as f:
                    f.write(cache.serialize())
                    log.info("✅ Token file saved.")
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
    # searching for token in the cache
    accounts = app.get_accounts()
    for account in accounts:
        result = app.acquire_token_silent(SCOPES, account=account)
        if result:
            save_cache()
            log.info("✅ Token found in the cache (No login required).")
            return result['access_token']

    # if no token found, start device flow
    log.warning("⚠️ No token found. Login required.")
    
    flow = app.initiate_device_flow(scopes=SCOPES)
    if 'user_code' not in flow:
        log.error("❌ Can't create Device Flow.")
        return None
    
    # send login instructions directly in chat (clickable link, opens in new tab)
    verification_uri = flow['verification_uri']
    user_code = flow['user_code']
    cat.send_ws_message(
        f"👉 Apri questo link: "
        f'<a href="{verification_uri}" target="_blank" rel="noopener noreferrer">{verification_uri}</a>'
        f"<br>👉 Inserisci il codice: <b>{user_code}</b>"
        f"<br>N.B. Potrebbe chiedere di eseguire il login con le tue credenziali Microsoft aziendali.",
        msg_type='chat'
    )
    
    result = app.acquire_token_by_device_flow(flow)

    if 'access_token' in result:
        save_cache()
        log.info("✅ Authentication done! Token saved.")
        return result['access_token']
    else:
        log.error(f"❌ Error during authentication: {result.get('error')}")
        return None
