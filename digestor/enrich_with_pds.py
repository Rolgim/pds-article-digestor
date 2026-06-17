import json
import requests
from bs4 import BeautifulSoup
import time
from concurrent.futures import ThreadPoolExecutor

FICHIER_ENTREE = "../docs/doi_by_collection.json"
FICHIER_SORTIE = "../docs/datasets_enriched.json"
MAX_THREADS = 5 

def scrape_all_pds_metadata(doi_suffix):
    """
    Va chercher la page du DOI et extrait ABSOLUMENT TOUTES les informations 
    du tableau (clés/valeurs), sans aucun filtre restrictif.
    """
    if not doi_suffix:
        return {}
        
    url = f"https://doi.org/{doi_suffix}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    extracted_metadata = {}
    
    try:
        # Configuration d'un timeout pour éviter le blocage d'un thread
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"[-] Erreur HTTP {response.status_code} pour le DOI {doi_suffix}")
            return {"error": f"HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        
        for row in rows:
            tds = row.find_all('td')
            # On cible les structures clés/valeurs du tableau (2 colonnes)
            if len(tds) == 2:
                key = tds[0].get_text(strip=True)
                val = tds[1].get_text(separator="\n", strip=True)
                
                # On ne prend que les lignes qui contiennent une vraie clé et une vraie valeur
                # (en ignorant les lignes vides ou les espaces insécables de mise en page)
                if key and val and not key.startswith("&nbsp"):
                    # Normalisation propre de la clé (ex: "START DATE TIME" -> "start_date_time")
                    clean_key = key.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
                    extracted_metadata[clean_key] = val
                    
        return extracted_metadata

    except Exception as e:
        print(f"[-] Erreur lors du traitement du DOI {doi_suffix}: {e}")
        return {"error": str(e)}

def worker(item_tuple):
    key, item = item_tuple
    print(f"[+] Scraping en cours : {key}")

    # item est maintenant un DOI string (ou None)
    doi = item if isinstance(item, str) else None

    if not doi:
        return key, {"doi": None, "info": "Aucun DOI"}

    scraped = scrape_all_pds_metadata(doi)

    # Le DOI est toujours conservé, même si le scraping a échoué
    result = {"doi": doi}
    result.update(scraped)
    return key, result
    
def main():
    # 1. Chargement du fichier JSON d'entrée
    try:
        with open(FICHIER_ENTREE, 'r', encoding='utf-8') as f:
            data_input = json.load(f)
        print(f"Fichier d'entrée '{FICHIER_ENTREE}' chargé. Début du nettoyage et scraping parallèle...\n")
    except FileNotFoundError:
        print(f"Erreur : Le fichier '{FICHIER_ENTREE}' est introuvable.")
        return
    except json.JSONDecodeError:
        print(f"Erreur : Le fichier '{FICHIER_ENTREE}' n'est pas un JSON valide.")
        return

    new_json_output = {}

    # 2. Pool de threads pour paralléliser l'analyse des pages de la NASA
    items_to_process = list(data_input.items())
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        results = executor.map(worker, items_to_process)
        
        # On construit le nouveau dictionnaire final
        for key, scraped_data in results:
            new_json_output[key] = scraped_data

    # 3. Sauvegarde dans le nouveau fichier de sortie
    with open(FICHIER_SORTIE, 'w', encoding='utf-8') as f:
        json.dump(new_json_output, f, indent=2, ensure_ascii=False)
        
    print(f"\n[OK] Terminé. Le nouveau JSON épuré a été sauvegardé sous : '{FICHIER_SORTIE}'")

if __name__ == "__main__":
    main()