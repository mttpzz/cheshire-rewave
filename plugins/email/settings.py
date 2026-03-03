from cat.mad_hatter.decorators import plugin, hook  # type: ignore
from pydantic import BaseModel
import os
from dotenv import load_dotenv


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
# load environment variables from .env file
load_dotenv()
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')


# --- PLUGIN SETTINGS -----------------------------------------------------------------------------------------------------------
# settings class for the plugin
class MailSettings(BaseModel):
    email_address: str = EMAIL_ADDRESS

@plugin
def settings_model():
    return MailSettings


# --- HOOK TO SAVE SETTINGS -----------------------------------------------------------------------------------------------------
@hook
def after_cat_bootstrap(cat):
    # plugin ID or plugin folder name
    plugin_id = "email"
    
    plugin = cat.mad_hatter.plugins.get(plugin_id)
    
    if plugin:
        # reading default values from Pydantic model, if settings.json file not exists or is empty
        current_settings = plugin.load_settings()
        
        # writing data inside settings.json
        plugin.save_settings(current_settings)
        
        print(f"✅ Impostazioni del plugin ***{plugin_id}*** salvate in automatico!")
