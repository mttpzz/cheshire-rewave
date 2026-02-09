from vanna.openai import OpenAI_Chat
from vanna.qdrant import Qdrant_VectorStore
from qdrant_client import QdrantClient
from dotenv import load_dotenv
import os

# load environment variables from .env file
load_dotenv('../.env')

QDRANT_URL = os.getenv('QDRANT_URL')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL')

DBHOST = os.getenv('DBHOST')
DBNAME = os.getenv('DBNAME')
DBUSER = os.getenv('DBUSER')
DBPASSWORD = os.getenv('DBPASSWORD')
DBPORT = int(os.getenv('DBPORT'))


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


# create an instance of MyVanna and connect to MySQL
vn = MyVanna(config=config_vn)
vn.connect_to_mysql(host=DBHOST, dbname=DBNAME, user=DBUSER, password=DBPASSWORD, port=DBPORT)

# the information schema query
df_information_schema = vn.run_sql("SELECT * FROM INFORMATION_SCHEMA.COLUMNS")

# this will break up the information schema into bite-sized chunks that can be referenced by the LLM
plan = vn.get_training_plan_generic(df_information_schema)

# if you like the plan, then uncomment this and run it to train
vn.train(plan=plan)

print("Training complete.")