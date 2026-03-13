from cat.mad_hatter.decorators import tool, hook    # type: ignore
import os


@hook
def agent_prompt_prefix(prefix, cat):
    settings = cat.mad_hatter.get_plugin().load_settings()
    prefix = settings["prompt_prefix"]

    return prefix


@hook
def before_cat_recalls_episodic_memories(default_episodic_recall_config, cat):
    settings = cat.mad_hatter.get_plugin().load_settings()
    default_episodic_recall_config["k"] = settings["episodic_memory_k"]
    default_episodic_recall_config["threshold"] = settings["episodic_memory_threshold"]

    return default_episodic_recall_config


@hook
def before_cat_recalls_declarative_memories(default_declarative_recall_config, cat):
    settings = cat.mad_hatter.get_plugin().load_settings()
    default_declarative_recall_config["k"] = settings["declarative_memory_k"]
    default_declarative_recall_config["threshold"] = settings["declarative_memory_threshold"]

    return default_declarative_recall_config


@hook
def before_cat_recalls_procedural_memories(default_procedural_recall_config, cat):
    settings = cat.mad_hatter.get_plugin().load_settings()
    default_procedural_recall_config["k"] = settings["procedural_memory_k"]
    default_procedural_recall_config["threshold"] = settings["procedural_memory_threshold"]

    return default_procedural_recall_config


@hook
def agent_prompt_suffix(suffix, cat):
    settings = cat.mad_hatter.get_plugin().load_settings()
    username = settings["user_name"] if settings["user_name"] != "" else "Human"
    suffix = f"""
        # Context

        {{episodic_memory}}

        {{declarative_memory}}

        {{tools_output}}
    """

    if settings["language"] == "Human":
        suffix += f"""
            ALWAYS answer in the {username}'s language
        """
    elif settings["language"] not in ["None", "Human"]:
        suffix += f"""
            ALWAYS answer in {settings["language"]}
        """

    suffix += f"""
        ## Conversation until now:"""

    return suffix


# --- USER FOLDER LINK ----------------------------------------------------------------------------------------------------------
BASE_FOLDER_CAT = os.getenv('BASE_FOLDER_CAT')
BASE_FOLDER_USER = os.getenv('BASE_FOLDER_USER')

@hook
def before_cat_reads_message(user_msg, cat):
    # folder for file access
    user_id = cat.user_id
    user_path = os.path.join(BASE_FOLDER_USER, user_id)
    
    if not os.path.exists(user_path):
        os.makedirs(user_path)
    
    user_path_link = f'<a href="{user_path}" target="_blank">{user_path}</a>'

    # Recuperiamo la cronologia della sessione attuale
    if len(cat.working_memory.history) == 0:
        # È la prima volta che apriamo la chat!
        cat.send_ws_message(f"A questo link troverai tutti i file creati in questa conversazione: {user_path_link}", msg_type="chat")
            
    return user_msg


@tool(return_direct=True, examples=['In quale cartella vengono salvati i file?', 'Dimmi qual è la cartella dei documenti.'])
def get_folder_link(_, cat):
    """
    This Tool to return the link of the folder in which all the files are saved.
    """
    # folder for file access
    user_id = cat.user_id
    user_path = os.path.join(BASE_FOLDER_USER, user_id)
    
    if not os.path.exists(user_path):
        os.makedirs(user_path)
    
    user_path_link = f'<a href="{user_path}" target="_blank">{user_path}</a>'

    return f"A questo link troverai tutti i file creati in questa conversazione: {user_path_link}"
