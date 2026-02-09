from cat.mad_hatter.decorators import tool, plugin, hook # type: ignore
from pydantic import BaseModel
from vanna.openai import OpenAI_Chat
from vanna.qdrant import Qdrant_VectorStore
from qdrant_client import QdrantClient
from dotenv import load_dotenv
import os

# load environment variables from .env file
load_dotenv()

QDRANT_URL = os.getenv('QDRANT_URL')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL')

DBHOST = os.getenv('DBHOST')
DBNAME = os.getenv('DBNAME')
DBUSER = os.getenv('DBUSER')
DBPASSWORD = os.getenv('DBPASSWORD')
DBPORT = int(os.getenv('DBPORT'))


# settings class for the plugin
class DBSettings(BaseModel):
    mysql_host: str = DBHOST
    mysql_dbname: str = DBNAME
    mysql_user: str = DBUSER
    mysql_password: str = DBPASSWORD
    mysql_port: int = DBPORT

@plugin
def settings_model():
    return DBSettings()


# configuration for Vanna model
qdrant_client = QdrantClient(
    url=QDRANT_URL, 
    api_key=QDRANT_API_KEY,
    check_compatibility=False   # skip version check between client and server
)

config_vn = {'client': qdrant_client,
            'model': OPENAI_MODEL,
            'api_key': OPENAI_API_KEY}

# Vanna model class
class MyVanna(Qdrant_VectorStore, OpenAI_Chat):
    def __init__(self, config=None):
        Qdrant_VectorStore.__init__(self, config=config)
        OpenAI_Chat.__init__(self, config=config)


@tool(return_direct=True, examples=['Recupera dal DB le vendite totali del mese scorso.'])
def execute_sql_query(text_query, cat):
    """
    Recall an instance of MyVanna to execute a SQL query.
    Input is the SQL query string.
    """
    # plugin settings for connecting to the database
    plugin_settings = cat.mad_hatter.get_plugin().load_settings()

    # create an instance of MyVanna and connect to MySQL database
    vn = MyVanna(config=config_vn)
    vn.connect_to_mysql(host=plugin_settings['mysql_host'],
                        dbname=plugin_settings['mysql_dbname'],
                        user=plugin_settings['mysql_user'],
                        password=plugin_settings['mysql_password'],
                        port=plugin_settings['mysql_port'])

    # generate and execute the SQL query
    sql_query = vn.generate_sql(text_query, allow_llm_to_see_data=True)
    df_query = vn.run_sql(sql_query)

    # format the output
    direct_output = f"The result of the SQL query is:\n {df_query.to_string(index=False)}"

    return direct_output
