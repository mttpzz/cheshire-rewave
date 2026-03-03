from cat.mad_hatter.decorators import tool  # type: ignore
from duckduckgo_search import DDGS

@tool(return_direct=False)
def web_search(query, cat):
    """
        Cerca informazioni su internet quando non conosci la risposta o hai bisogno di dati aggiornati. 
        L'input deve essere una query di ricerca testuale.
    """

    cat.send_ws_message(content=f"Ricerca in corso...")

    try:
        # duckduckgo initializer
        with DDGS() as ddgs:
            # web search (only first 5 results)
            results = ddgs.text(query, max_results=5)
            
            if not results:
                return f"Non ho trovato risultati recenti per '{query}'."

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
