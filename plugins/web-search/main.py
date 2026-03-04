from cat.mad_hatter.decorators import tool  # type: ignore
from ddgs import DDGS


@tool(examples=["Cerca sul web", "Cerca su internet", "Cerca online"])
def web_search(input_query, cat):
    """
    You MUST use this tool if you don't know how to answer to the user or if you don't have any information.
    If you already have the information in your memory, you MUST integrate it with the result of this tool.
    Use this tool also every time the user asks to search something on the web or if the user asks about recent news.
    The input is the query string.
    """
    
    cat.send_ws_message(content=f"Ricerca sul web in corso...")

    try:
        # web search using only first 5 results
        results = DDGS().text(input_query, max_results=5)
        if not results:
            return f"Non ho trovato risultati recenti per '{input_query}'."

        # formatting data
        formatted_results = "Ecco cosa ho trovato sul web:\n\n"
        for r in results:
            formatted_results += f"- Titolo: {r['title']}\n"
            formatted_results += f"  Snippet: {r['body']}\n"
            formatted_results += f"  Link: {r['href']}\n\n"

        return formatted_results

    except Exception as e:
        print(f"Errore durante la ricerca: {e}")
        return "❌ Al momento non riesco a collegarmi a internet per effettuare la ricerca. Riprova più tardi."
