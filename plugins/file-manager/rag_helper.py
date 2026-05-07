from cat.logs.cat_logger import get_plugin_logger     # type: ignore
from cat.mad_hatter.decorators import hook, tool      # type: ignore
from langchain_core.document_loaders import BaseBlobParser, Blob  # type: ignore
from langchain_core.documents import Document   # type: ignore
from docling.document_converter import DocumentConverter
import tempfile
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import html


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
log = get_plugin_logger("file-manager")


# --- CONST ---------------------------------------------------------------------------------------------------------------------
DOCS_EXT = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".md": "text/markdown",
    ".csv": "text/csv",
}

DOCLING_MIMES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}


# --- TOOL: LIST RAG SOURCES ----------------------------------------------------------------------------------------------------
def _classify_source(src: str, md: dict) -> str:
    if src.startswith(("http://", "https://")):
        return "url"
    if src.startswith("text:"):
        return "text"
    ext = os.path.splitext(src)[1].lower()
    if ext in DOCS_EXT or md.get("filename"):
        return "file"
    return "other"

def _fmt_ts(ts):
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(ts)


@tool(
    return_direct=True,
    examples=[
        "che cosa hai indicizzato",
        "elenca tutto nel rag",
        "lista contenuti caricati",
        "cosa c'è nella memoria",
        "che documenti hai indicizzato",
    ],
)
def list_indexed_documents(tool_input: str, cat) -> str:
    """
    List everything indexed in the user's declarative memory (RAG): files, URLs, raw text.
    Use when the user asks: what's in the RAG, list indexed content, show my documents/links/notes.
    """
    user_id = cat.user_id
    log.info(f"Listing indexed content for user '{user_id}'.")
    try:
        all_points, _ = cat.memory.vectors.declarative.get_all_points()

        items: dict[str, dict] = {}
        for p in all_points:
            md = p.payload.get("metadata", {}) or {}
            if md.get("user_id") != user_id:
                continue

            src = md.get("source") or md.get("filename") or md.get("url")
            if not src:
                content = p.payload.get("page_content", "")
                src = f"text:{content[:40].strip()}…" if content else "unknown"

            kind = _classify_source(src, md)
            entry = items.setdefault(src, {
                "kind": kind,
                "chunks": 0,
                "indexed_at": md.get("indexed_at") or md.get("when"),
            })
            entry["chunks"] += 1
            ts = md.get("indexed_at") or md.get("when")
            if ts:
                try:
                    if not entry["indexed_at"] or float(ts) > float(entry["indexed_at"]):
                        entry["indexed_at"] = ts
                except (ValueError, TypeError):
                    pass  # keep existing value if unparseable
        
        if not items:
            return "📂 Nessun contenuto indicizzato."

        groups: dict[str, list[tuple[str, dict]]] = {}
        for src, info in items.items():
            groups.setdefault(info["kind"], []).append((src, info))

        icons = {"file": "📄", "url": "🔗", "text": "📝", "other": "❔"}
        order = ["file", "url", "text", "other"]

        lines = [f"📚 Contenuti indicizzati ({len(items)}):", ""]
        for kind in order:
            if kind not in groups:
                continue
            lines.append(f"**{icons[kind]} {kind.upper()}** ({len(groups[kind])})")
            for src, info in sorted(groups[kind]):
                indexed = _fmt_ts(info["indexed_at"])
                label = f'<a href="{html.escape(src, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(src)}</a>' if kind == "url" else html.escape(src)
                lines.append(f"• {label} — {info['chunks']} chunk · {indexed}")
            lines.append("")
        return "\n".join(lines).rstrip()
    except Exception as e:
        log.error(f"❌ List tool error: {e}")
        return "❌ Errore durante l'elenco. Riprova."


# --- DOCLING PARSER ------------------------------------------------------------------------------------------------------------
# Lazy singleton: DocumentConverter loads heavy ML models on init,
# reuse one instance across all uploads instead of reloading per file.
_converter: DocumentConverter | None = None

def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        log.info("Loading Docling models (first run)...")
        _converter = DocumentConverter()
    return _converter

class DoclingMarkdownParser(BaseBlobParser):
    def __init__(self, default_suffix: str = ".bin"):
        self.default_suffix = default_suffix

    def lazy_parse(self, blob: Blob):
        suffix = os.path.splitext(blob.source or "")[1].lower() or self.default_suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(blob.as_bytes())
            tmp_path = tmp.name
        try:
            log.info(f"Docling convert: {blob.source or tmp_path}")
            result = _get_converter().convert(tmp_path)
            md = result.document.export_to_markdown()
        except Exception as e:
            log.error(f"❌ Docling failed on {blob.source}: {e}")
            raise
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        yield Document(
            page_content=md,
            metadata={"source": blob.source or "", "parser": "docling"},
        )



# Pre-load Docling models at boot: first conversion downloads/loads
# heavy ML models (~minutes), which would timeout proxy on first chat upload.
@hook
def after_cat_bootstrap(cat):
    log.info("Warming up Docling models...")
    _get_converter()
    log.info("Docling ready.")


@hook
def rabbithole_instantiates_parsers(parsers: dict, cat) -> dict:
    for mime, suffix in DOCLING_MIMES.items():
        parsers[mime] = DoclingMarkdownParser(default_suffix=suffix)
    log.info(f"Docling parser registered: {list(DOCLING_MIMES.keys())}")
    return parsers