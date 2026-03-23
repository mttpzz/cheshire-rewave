from cat.logs.cat_logger import get_plugin_logger     # type: ignore
from cat.mad_hatter.decorators import tool  # type: ignore
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .auth import create_msal_app, get_access_token


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
# start the logger with its plugin name
log = get_plugin_logger("email")


# --- GET AND POST CALENDAR EVENTS ----------------------------------------------------------------------------------------------
def cal_get(endpoint: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.get(f"https://graph.microsoft.com/v1.0/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.json()

def cal_post(endpoint: str, payload: dict, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"https://graph.microsoft.com/v1.0/{endpoint}", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


# --- TOOL: EVENTS OF NEXT N DAYS -----------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Dimmi i miei appuntamenti per i prossimi 3 giorni', 'Quali eventi ho nei prossimi 10 giorni?'])
def get_upcoming_events(tool_input, cat):
    """
    Show calendar events for the upcoming days.
    Input: number of days (e.g. "7")
    Use this tool when the user asks about: appointments, meetings, deadlines, what's on my agenda, events this week, etc.
    """
    log.info("Starting getting upcoming events.")
    cat.send_ws_message(f"Ricerca dei prossimi eventi in corso...")

    try:
        days = int(tool_input.strip()) if tool_input.strip().isdigit() else 7
        now = datetime.now(ZoneInfo("Europe/Rome"))
        end = now + timedelta(days=days)

        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint = (
            f"me/calendarView"
            f"?startDateTime={start_str}&endDateTime={end_str}"
            f"&$orderby=start/dateTime"
            f"&$select=subject,start,end,location,bodyPreview"
            f"&$top=20"
        )

        # getting calendar events
        app, save_cache = create_msal_app(cat.user_id)
        token = get_access_token(cat, app, save_cache)
        data = cal_get(endpoint, token)
        events = data.get("value", [])

        if not events:
            return f"⚠️ Nessun evento nei prossimi {days} giorni."

        # formatting
        result = f"📅 **Eventi nei prossimi {days} giorni:**\n\n"
        for ev in events:
            # converting from utc to italy time zone
            start_utc = datetime.fromisoformat(ev["start"]["dateTime"][:16].replace("T", " "))
            start = start_utc.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")
            subject = ev.get("subject", "Senza titolo")
            location = ev.get("location", {}).get("displayName", "")
            loc_str = f" — 📍 {location}" if location else ""
            result += f"• **{start}** — {subject}{loc_str}\n"

        return result

    except Exception as e:
        log.error(f"❌ Error while retriving events: {str(e)}")
        return f"❌ Errore nel recupero eventi: {str(e)}"


# --- TOOL: NEW EVENT -----------------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Crea un evento Controllo per il giorno 23 marzo dalle 11 alle 12'])
def create_calendar_event(tool_input, cat):
    """
    Create a new event in the Outlook calendar.
    Expected input (separated by |): title|date (YYYY-MM-DD)|start time (HH:MM)|end time (HH:MM)|optional notes
    Example: "Production meeting|2024-03-25|10:00|11:00|Discuss Rossi order"
    Use this tool when the user says: add to calendar, create appointment, mark meeting, put in agenda, etc.
    """
    log.info("Starting creating calendar event.")
    cat.send_ws_message(f"Creazione evento nel calendario in corso...")
    
    try:
        # getting calendar data
        parts = [p.strip() for p in tool_input.split("|")]
        if len(parts) < 4:
            return "❌ Problema nella creazione dell'evento. \nProva a usare questo formato: titolo|data|ora inizio|ora fine|note"

        title, date, start_time, end_time = parts[:4]
        notes = parts[4] if len(parts) > 4 else ""

        payload = {
            "subject": title,
            "body": {"contentType": "text", "content": notes},
            "start": {
                "dateTime": f"{date}T{start_time}:00",
                "timeZone": "Europe/Rome"
            },
            "end": {
                "dateTime": f"{date}T{end_time}:00",
                "timeZone": "Europe/Rome"
            },
        }

        # posting calendar events
        app, save_cache = create_msal_app(cat.user_id)
        token = get_access_token(cat, app, save_cache)
        cal_post(f"me/events", payload, token)

        return f"✅ Evento '{title}' creato il {date} dalle {start_time} alle {end_time}."

    except Exception as e:
        log.error(f"❌ Error while creating the event: {str(e)}")
        return f"❌ Errore nella creazione dell'evento: {str(e)}"


# --- TOOL: SEARCHING EVENTS ----------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Quando è il mio appuntamento con Cristiano?', 'Trova gli eventi riguardo i controlli'])
def search_calendar_events(tool_input, cat):
    """
    Search for events in the calendar that contain a keyword in the title.
    Input: keyword to search for (e.g. "Smith" or "budget review")
    Use this tool when the user asks: search in calendar, when is my appointment with X, find the meeting about Y, etc.
    """
    log.info("Starting searching calendar events.")
    cat.send_ws_message(f"Ricerca nei prossimi eventi in corso...")

    try:
        keyword = tool_input.strip().lower()
        now = datetime.now(ZoneInfo("Europe/Rome"))
        end = now + timedelta(days=90)  # search in next 90 days

        # getting calendar events
        endpoint = (
            f"me/calendarView"
            f"?startDateTime={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&endDateTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&$select=subject,start,end,location"
            f"&$top=50"
        )
        app, save_cache = create_msal_app(cat.user_id)
        token = get_access_token(cat, app, save_cache)
        data = cal_get(endpoint, token)
        events = [
            e for e in data.get("value", [])
            if keyword in e.get("subject", "").lower()
        ]

        if not events:
            return f"⚠️ Nessun evento trovato con '{keyword}' nei prossimi 90 giorni."

        # formatting
        result = f"🔍 **Risultati per '{keyword}':**\n\n"
        for ev in events:
            # converting from utc to italy time zone
            start_utc = datetime.fromisoformat(ev["start"]["dateTime"][:16].replace("T", " "))
            start = start_utc.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")
            result += f"• **{start}** — {ev.get('subject', 'Senza titolo')}\n"

        return result

    except Exception as e:
        log.error(f"❌ Error while searching events: {str(e)}")
        return f"❌ Errore nella ricerca degli eventi: {str(e)}"


# --- TOOL: DELETING EVENTS -----------------------------------------------------------------------------------------------------
@tool(return_direct=True, examples=['Elimina evento Revisione', 'Cancella appuntamento Controllo'])
def delete_calendar_event(tool_input, cat):
    """
    Delete an event from the Outlook calendar.
    Input: keyword from the title of the event to delete (e.g. "Bianchi Meeting")
    Use this tool when the user says: cancel appointment, delete meeting, remove from calendar, remove X's event, etc.
    """
    log.info("Starting deleting calendar event.")
    cat.send_ws_message(f"Eliminazione dell'evento in corso...")

    try:
        keyword = tool_input.strip().lower()
        now = datetime.now(ZoneInfo("Europe/Rome"))
        end = now + timedelta(days=90)  # search in next 90 days

        # getting calendar events
        endpoint = (
            f"me/calendarView"
            f"?startDateTime={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&endDateTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&$select=id,subject,start"
            f"&$top=50"
        )

        app, save_cache = create_msal_app(cat.user_id)
        token = get_access_token(cat, app, save_cache)
        data = cal_get(endpoint, token)

        events = [
            ev for ev in data.get("value", [])
            if keyword in ev.get("subject", "").lower()
        ]

        if not events:
            return f"⚠️ Nessun evento trovato con '{tool_input}' nei prossimi 90 giorni."

        # it deletes always the first event, even if it finds more than 1
        event = events[0]
        event_id = event["id"]
        # converting from utc to italy time zone
        start_utc = datetime.fromisoformat(event["start"]["dateTime"][:16].replace("T", " "))
        start = start_utc.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")
        subject = event.get("subject", "Senza titolo")

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.delete(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
            headers=headers
        )
        response.raise_for_status()

        return f"🗑️ Evento '{subject}' del {start} cancellato con successo."

    except Exception as e:
        log.error(f"❌ Error deleting event: {str(e)}")
        return f"❌ Errore durante la cancellazione dell'evento: {str(e)}"
