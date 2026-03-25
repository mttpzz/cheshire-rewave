from cat.logs.cat_logger import get_plugin_logger     # type: ignore
from cat.mad_hatter.decorators import hook, tool  # type: ignore
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import io
from fastapi import UploadFile
from starlette.datastructures import Headers


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
# start the logger with its plugin name
log = get_plugin_logger("file-manager")


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
BASE_FOLDER_CAT = os.getenv('BASE_FOLDER_CAT')
REGISTRY_PATH = os.path.join(BASE_FOLDER_CAT, "index_registry")

DOCS_EXT = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


# --- HELPERS -------------------------------------------------------------------------------------------------------------------
def _get_registry_file() -> str:
    os.makedirs(REGISTRY_PATH, exist_ok=True)
    return os.path.join(REGISTRY_PATH, "shared_registry.json")


def _load_registry() -> dict:
    path = _get_registry_file()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(registry: dict) -> None:
    path = _get_registry_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _ingest_file(cat, filepath: str, filename: str, content_type: str, metadata: dict) -> None:
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    
    upload_file = UploadFile(file=io.BytesIO(file_bytes), filename=filename, headers=Headers({"content-type": content_type}))
    cat.rabbit_hole.ingest_file(cat, file=upload_file, metadata=metadata)


def _remove_from_memory(cat, filename: str) -> int:
    # get all points and ignore next_page_offset
    all_points, _ = cat.memory.vectors.declarative.get_all_points()
    
    ids_to_delete = [
        point.id for point in all_points
        if point.payload.get("metadata", {}).get("filename") == filename
    ]

    if ids_to_delete:
        cat.memory.vectors.declarative.delete_points(ids_to_delete)

    return len(ids_to_delete)


# --- SYNC DOCS -----------------------------------------------------------------------------------------------------------------
def _sync_documents(cat) -> str:
    """
    Sync declarative memory with a shared document folder.
    Remove old files, index new files and skip files already in memory.
    Return a summary message.
    """
    if not os.path.exists(BASE_FOLDER_CAT):
        log.warning("⚠️ Folder not found.")
        return "⚠️ Cartella documenti non trovata."

    registry = _load_registry()

    # remove older files no more in the shared folder
    rem_files, rem_errors = [], []

    for filename in list(registry.keys()):
        filepath = os.path.join(BASE_FOLDER_CAT, filename)
        if not os.path.exists(filepath):
            try:
                num_chunks = _remove_from_memory(cat, filename)
                del registry[filename]
                rem_files.append(filename)
                log.info(f"⚠️ '{filename}' removed from memory ({num_chunks} chunks eliminated).")
            except Exception as e:
                log.error(f"❌ Error removing '{filename}': {e}")
                rem_errors.append(filename)

    if rem_files:
        _save_registry(registry)

    # indexing new files
    files = [
        f for f in os.listdir(BASE_FOLDER_CAT)
        if os.path.splitext(f)[1].lower() in DOCS_EXT
    ]

    if not files:
        log.info(f"⚠️ No supported docs found. Removed: {len(rem_files)}; Errors: {len(rem_errors)}")
        no_file_summary = (
            "⚠️ Nessun documento supportato trovato.\n"
            f"🗑️ Rimossi: {len(rem_files)}\n"
            f"❌ Errori: {len(rem_errors)}"
        )
        return no_file_summary

    new_files, skip_files, index_errors = [], [], []

    for filename in files:
        try:
            if filename in registry:
                skip_files.append(filename)
                continue

            filepath = os.path.join(BASE_FOLDER_CAT, filename)
            ext = os.path.splitext(filename)[1].lower()
            content_type = DOCS_EXT[ext]
            metadata = {
                "filename": filename,
                "indexed_at": datetime.now(tz=ZoneInfo("Europe/Rome")).isoformat(timespec="seconds"),
                "source": "documents_sync_plugin",
            }

            _ingest_file(cat, filepath, filename, content_type, metadata)

            registry[filename] = {
                "indexed_at": datetime.now(tz=ZoneInfo("Europe/Rome")).isoformat(timespec="seconds"),
                "size_kb": round(os.path.getsize(filepath) / 1024, 1),
                "type": ext,
            }

            new_files.append(filename)

        except Exception as e:
            log.error(f"❌ Error with '{filename}': {e}")
            index_errors.append(filename)

    _save_registry(registry)

    # log and return a summary
    error_files = rem_errors + index_errors
    log.info(
        f"✅ Sync done — "
        f"New: {len(new_files)}; Removed: {len(rem_files)}; "
        f"Skipped: {len(skip_files)}; Errors: {len(error_files)}"
    )

    summary = (
        f"Sincronizzazione completata:\n"
        f"✅ Nuovi: {len(new_files)}\n"
        f"🗑️ Rimossi: {len(rem_files)}\n"
        f"⏭️ Già presenti: {len(skip_files)}\n"
        f"❌ Errori: {len(error_files)}"
    )
    if new_files:
        summary += f"\n\nNuovi file indicizzati: {', '.join(new_files)}"
    if rem_files:
        summary += f"\nFile rimossi dalla memoria: {', '.join(rem_files)}"
    if error_files:
        summary += f"\nFile con errori: {', '.join(error_files)}"

    return summary


# --- HOOK: AUTO ----------------------------------------------------------------------------------------------------------------
@hook
def after_cat_bootstrap(cat):
    log.info("Starting sync declarative memory hook.")
    try:
        _sync_documents(cat)
    except Exception as e:
        log.error(f"❌ Hook error: {e}")


# --- TOOL: MANUAL --------------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=["aggiorna i documenti", "sincronizza la memoria"])
def sync_documents(tool_input: str, cat) -> str:
    """
    Sync declarative memory with the documents folder.
    Index new files and remove deleted ones.
    Use this tool when the user says: update documents, sync memory, I added new files, I removed some documents, refresh search, etc.
    """
    log.info("Starting sync declarative memory tool.")
    try:
        return _sync_documents(cat)
    except Exception as e:
        log.error(f"❌ Tool error: {e}")
        return f"❌ Errore durante la sincronizzazione: {str(e)}"
