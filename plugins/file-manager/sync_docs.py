from cat.logs.cat_logger import get_plugin_logger     # type: ignore
from cat.mad_hatter.decorators import hook, tool      # type: ignore
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import io
from fastapi import UploadFile
from starlette.datastructures import Headers


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
log = get_plugin_logger("file-manager")


# --- ENV / CONST ---------------------------------------------------------------------------------------------------------------
BASE_FOLDER_CAT = os.getenv('BASE_FOLDER_CAT')
REGISTRY_PATH = os.path.join(BASE_FOLDER_CAT, "index_registry")
SYNC_SUBDIR = "sync"
EXCLUDED_USER_DIRS = {"index_registry"}

DOCS_EXT = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


# --- REGISTRY HELPERS ----------------------------------------------------------------------------------------------------------
def _registry_file(user_id: str) -> str:
    os.makedirs(REGISTRY_PATH, exist_ok=True)
    return os.path.join(REGISTRY_PATH, f"{user_id}.json")


def _load_registry(user_id: str) -> dict:
    path = _registry_file(user_id)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(user_id: str, registry: dict) -> None:
    path = _registry_file(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


# --- INGEST / DELETE -----------------------------------------------------------------------------------------------------------
def _ingest_file(cat, filepath: str, filename: str, content_type: str, metadata: dict) -> None:
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    upload_file = UploadFile(
        file=io.BytesIO(file_bytes),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    cat.rabbit_hole.ingest_file(cat, file=upload_file, metadata=metadata)


def _remove_from_memory(cat, user_id: str, filename: str) -> int:
    all_points, _ = cat.memory.vectors.declarative.get_all_points()
    ids_to_delete = [
        p.id for p in all_points
        if p.payload.get("metadata", {}).get("filename") == filename
        and p.payload.get("metadata", {}).get("user_id") == user_id
    ]
    if ids_to_delete:
        cat.memory.vectors.declarative.delete_points(ids_to_delete)
    return len(ids_to_delete)


# --- USER DISCOVERY ------------------------------------------------------------------------------------------------------------
def _list_user_ids() -> list[str]:
    if not os.path.exists(BASE_FOLDER_CAT):
        return []
    return [
        d for d in os.listdir(BASE_FOLDER_CAT)
        if os.path.isdir(os.path.join(BASE_FOLDER_CAT, d))
        and d not in EXCLUDED_USER_DIRS
    ]


def _user_sync_dir(user_id: str) -> str:
    return os.path.join(BASE_FOLDER_CAT, user_id, SYNC_SUBDIR)


def _list_sync_files(user_id: str) -> list[str]:
    sync_dir = _user_sync_dir(user_id)
    if not os.path.isdir(sync_dir):
        return []
    return [
        f for f in os.listdir(sync_dir)
        if os.path.isfile(os.path.join(sync_dir, f))
        and os.path.splitext(f)[1].lower() in DOCS_EXT
    ]


# --- SYNC CORE -----------------------------------------------------------------------------------------------------------------
def _sync_user(cat, user_id: str) -> dict:
    """Sync declarative memory for a single user. Return counters."""
    sync_dir = _user_sync_dir(user_id)
    os.makedirs(sync_dir, exist_ok=True)

    registry = _load_registry(user_id)
    now_iso = lambda: datetime.now(tz=ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")

    rem_files, rem_errors = [], []
    new_files, skip_files, index_errors = [], [], []

    # 1) remove entries whose file is gone
    for filename in list(registry.keys()):
        filepath = os.path.join(sync_dir, filename)
        if not os.path.exists(filepath):
            try:
                n = _remove_from_memory(cat, user_id, filename)
                del registry[filename]
                rem_files.append(filename)
                log.info(f"⚠️ [{user_id}] '{filename}' removed ({n} chunks).")
            except Exception as e:
                log.error(f"❌ [{user_id}] remove '{filename}': {e}")
                rem_errors.append(filename)

    if rem_files:
        _save_registry(user_id, registry)

    # 2) index new files
    for filename in _list_sync_files(user_id):
        if filename in registry:
            skip_files.append(filename)
            continue
        try:
            filepath = os.path.join(sync_dir, filename)
            ext = os.path.splitext(filename)[1].lower()
            metadata = {
                "filename": filename,
                "user_id": user_id,
                "indexed_at": now_iso(),
                "source": filename,
            }
            _ingest_file(cat, filepath, filename, DOCS_EXT[ext], metadata)
            registry[filename] = {
                "indexed_at": now_iso(),
                "size_kb": round(os.path.getsize(filepath) / 1024, 1),
                "type": ext,
            }
            new_files.append(filename)
        except Exception as e:
            log.error(f"❌ [{user_id}] index '{filename}': {e}")
            index_errors.append(filename)

    if new_files:
        _save_registry(user_id, registry)

    return {
        "user_id": user_id,
        "new": new_files,
        "removed": rem_files,
        "skipped": skip_files,
        "errors": rem_errors + index_errors,
    }


def _sync_documents(cat, only_user: str | None = None) -> str:
    """
    Sync declarative memory per-user.
    only_user=None → all users on disk; otherwise only that user.
    """
    if not os.path.exists(BASE_FOLDER_CAT):
        log.warning("⚠️ Folder not found.")
        return "⚠️ Cartella documenti non trovata."

    users = [only_user] if only_user else _list_user_ids()
    if not users:
        return "⚠️ Nessun utente trovato."

    totals = {"new": 0, "removed": 0, "skipped": 0, "errors": 0}
    per_user_lines = []

    for uid in users:
        try:
            r = _sync_user(cat, uid)
            totals["new"] += len(r["new"])
            totals["removed"] += len(r["removed"])
            totals["skipped"] += len(r["skipped"])
            totals["errors"] += len(r["errors"])
            per_user_lines.append(
                f"• {uid}: ✅{len(r['new'])} 🗑️{len(r['removed'])} "
                f"⏭️{len(r['skipped'])} ❌{len(r['errors'])}"
            )
        except Exception as e:
            log.error(f"❌ user '{uid}': {e}")
            totals["errors"] += 1
            per_user_lines.append(f"• {uid}: ❌ errore generale")

    log.info(
        f"✅ Sync done — New: {totals['new']}; Removed: {totals['removed']}; "
        f"Skipped: {totals['skipped']}; Errors: {totals['errors']}"
    )

    summary = (
        "Sincronizzazione completata:\n"
        f"✅ Nuovi: {totals['new']}\n"
        f"🗑️ Rimossi: {totals['removed']}\n"
        f"⏭️ Già presenti: {totals['skipped']}\n"
        f"❌ Errori: {totals['errors']}"
    )
    if per_user_lines:
        summary += "\n\nDettaglio:\n" + "\n".join(per_user_lines)
    return summary


# --- HOOK: AUTO ----------------------------------------------------------------------------------------------------------------
@hook
def after_cat_bootstrap(cat):
    log.info("Starting sync declarative memory hook (all users).")
    try:
        _sync_documents(cat)  # all users at boot
    except Exception as e:
        log.error(f"❌ Hook error: {e}")


# --- TOOL: MANUAL --------------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=["aggiorna i documenti", "sincronizza la memoria"])
def sync_documents(tool_input: str, cat) -> str:
    """
    Sync the user's declarative memory with their sync folder.
    Index new files and remove deleted ones.
    Use when the user says: update documents, sync memory, I added new files, I removed some documents, refresh search, etc.
    """
    log.info(f"Starting sync tool for user '{cat.user_id}'.")
    try:
        return _sync_documents(cat, only_user=cat.user_id)
    except Exception as e:
        log.error(f"❌ Tool error: {e}")
        return f"❌ Errore durante la sincronizzazione: {str(e)}"
