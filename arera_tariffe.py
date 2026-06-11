#!/usr/bin/env python3
"""
arera_tariffe.py — Tappa 1: dati reali del Portale Offerte ARERA
================================================================

Scarica l'open data delle offerte di ENERGIA ELETTRICA del mercato libero
(ilportaleofferte.it) e ne ricava una TABELLA ESSENZIALE per il profilo
"privato luce", utilizzabile dall'app per il confronto col mercato.

Si usa in due modi:

  1) python arera_tariffe.py esplora
     Scarica il file più recente e ne stampa la STRUTTURA (i tag XML reali)
     + la prima offerta per intero. Serve a noi per confermare lo schema.

  2) python arera_tariffe.py estrai
     Produce 'tariffe_luce.csv' e 'tariffe_luce.json' con le colonne:
        venditore_piva, nome_offerta, cod_offerta, tipo_cliente,
        tipo_prezzo (fisso/variabile), indice, spread, prezzo_fisso,
        quota_fissa_annua, durata_mesi
     (filtrando ai soli clienti DOMESTICI)

Richiede solo Python 3 (nessuna libreria esterna). Va lanciato da un
computer con accesso a internet normale (non da reti che bloccano il sito).

NOTA: i nomi dei tag nello schema ARERA possono variare. Lo script lavora
sui nomi "locali" ignorando i namespace e cercando per parole chiave, così
ha buone probabilità di funzionare. Se qualche colonna esce vuota, lanciare
prima 'esplora' e incollarmi l'output: rifinisco la mappatura in un minuto.
"""

import sys, csv, json, datetime, urllib.request, urllib.error
import xml.etree.ElementTree as ET

BASE = "https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/offerteML"
HEADERS = {"User-Agent": "Mozilla/5.0 (TariffaChiara data fetch)"}


def url_for(date, market="E"):
    # cartella ANNO_MESE (mese NON con zero iniziale), file con DATA AAAAMMGG
    folder = f"{date.year}_{date.month}"
    fname = f"PO_Offerte_{market}_MLIBERO_{date:%Y%m%d}.xml"
    return f"{BASE}/{folder}/{fname}"


def find_latest(market="E", days_back=15):
    """Prova oggi e i giorni precedenti finché trova un file disponibile."""
    today = datetime.date.today()
    for i in range(days_back):
        d = today - datetime.timedelta(days=i)
        u = url_for(d, market)
        try:
            req = urllib.request.Request(u, headers=HEADERS, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    return u
        except urllib.error.HTTPError:
            continue
        except Exception:
            continue
    return None


def download(url):
    print(f"Scarico: {url}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    print(f"Scaricati {len(data)/1_000_000:.1f} MB")
    return data


def local(tag):
    """Nome del tag senza il namespace {...}."""
    return tag.split("}")[-1] if "}" in tag else tag


def leaves(elem):
    """Tutti i tag-foglia (localname -> testo) sotto un elemento."""
    out = {}
    for e in elem.iter():
        if len(list(e)) == 0 and e.text and e.text.strip():
            out.setdefault(local(e.tag), e.text.strip())
    return out


# ---------------------------------------------------------------- ESPLORA
def esplora():
    url = find_latest("E")
    if not url:
        print("Nessun file trovato negli ultimi giorni. Apri ilportaleofferte.it "
              "> Open Data > Offerte (xml) e copia l'URL corrente.")
        return
    data = download(url)
    root = ET.fromstring(data)
    print(f"\nRADICE: <{local(root.tag)}>")

    # figli diretti e loro frequenza
    from collections import Counter
    figli = Counter(local(c.tag) for c in root)
    print("Figli diretti della radice:")
    for k, v in figli.most_common():
        print(f"  {k}: {v}")

    # l'elemento ripetuto (l'offerta) è il figlio più frequente
    offer_tag = figli.most_common(1)[0][0]
    print(f"\nElemento 'offerta' presunto: <{offer_tag}>")

    first = next((c for c in root if local(c.tag) == offer_tag), None)
    if first is not None:
        print("\n--- PRIMA OFFERTA (XML completo) ---")
        ET.indent(first)
        print(ET.tostring(first, encoding="unicode"))
        print("\n--- TAG-FOGLIA DELLA PRIMA OFFERTA ---")
        for k, v in leaves(first).items():
            print(f"  {k} = {v[:80]}")


# ---------------------------------------------------------------- ESTRAI
DOMESTICO = {"1", "01", "domestico"}
TIPO_OFFERTA = {"01": "fisso", "02": "variabile", "03": "flat"}
UNITA = {"01": "€/anno", "02": "€/kW/anno", "03": "€/kWh", "04": "€/Smc", "06": "€/punto/anno"}


def kids(elem, name):
    """Figli diretti con un dato localname."""
    return [c for c in elem if local(c.tag) == name]


def text_of(elem, name):
    """Testo del primo discendente con quel localname."""
    for e in elem.iter():
        if local(e.tag) == name and e.text and e.text.strip():
            return e.text.strip()
    return None


def parse_componenti(off):
    """Estrae prezzo energia (spread o fisso) e quota fissa dai blocchi ComponenteImpresa."""
    energia_vals, energia_um, quota, quota_um = [], None, None, None
    for comp in kids(off, "ComponenteImpresa"):
        nome = (text_of(comp, "NOME") or "").upper()
        desc = (text_of(comp, "DESCRIZIONE") or "").lower()
        macro = text_of(comp, "MACROAREA")
        prezzi = [text_of(ip, "PREZZO") for ip in kids(comp, "IntervalloPrezzi")]
        prezzi = [p for p in prezzi if p]
        ums = [text_of(ip, "UNITA_MISURA") for ip in kids(comp, "IntervalloPrezzi")]
        um = next((u for u in ums if u), None)
        is_energia = macro == "04" or "SPREAD" in nome or "materia prima" in desc
        is_quota = macro == "01" or "commercializ" in desc or "quota" in nome.lower()
        if is_energia and prezzi:
            energia_vals, energia_um = prezzi, um
        elif is_quota and prezzi:
            quota, quota_um = prezzi[0], um
    # se le fasce hanno prezzi diversi le uniamo (es. F1/F2/F3), se uguali una sola
    uniq = []
    for p in energia_vals:
        if p not in uniq:
            uniq.append(p)
    prezzo_energia = "/".join(uniq) if uniq else None
    # quota fissa portata ad anno se espressa al mese
    quota_anno = quota
    if quota and quota_um and "mese" in (UNITA.get(quota_um, "")):
        try:
            quota_anno = str(round(float(quota.replace(",", ".")) * 12, 2))
        except ValueError:
            pass
    return prezzo_energia, UNITA.get(energia_um, energia_um), quota_anno, UNITA.get(quota_um, quota_um)


def estrai():
    url = find_latest("E")
    if not url:
        print("File non trovato. Vedi nota in 'esplora'.")
        return
    data = download(url)
    root = ET.fromstring(data)
    from collections import Counter
    figli = Counter(local(c.tag) for c in root)
    offer_tag = figli.most_common(1)[0][0]

    righe = []
    for off in (c for c in root if local(c.tag) == offer_tag):
        tipo_cliente = text_of(off, "TIPO_CLIENTE")
        if tipo_cliente not in DOMESTICO:
            continue  # solo clienti domestici (privati)
        tipo_off = text_of(off, "TIPO_OFFERTA")
        durata = text_of(off, "DURATA")
        prezzo_energia, energia_um, quota, quota_um = parse_componenti(off)
        righe.append({
            "venditore_piva": text_of(off, "PIVA_UTENTE"),
            "nome_offerta": text_of(off, "NOME_OFFERTA"),
            "cod_offerta": text_of(off, "COD_OFFERTA"),
            "tipo_prezzo": TIPO_OFFERTA.get(tipo_off, tipo_off),
            "indice_prezzo": text_of(off, "IDX_PREZZO_ENERGIA"),
            "prezzo_energia": prezzo_energia,  # spread (se variabile) o prezzo fisso
            "unita_energia": energia_um,
            "quota_fissa_annua": quota,
            "unita_quota": quota_um,
            "consumo_min": text_of(off, "CONSUMO_MIN"),
            "consumo_max": text_of(off, "CONSUMO_MAX"),
            "durata_mesi": "indeterminata" if durata == "-1" else durata,
        })

    if not righe:
        print("Nessuna offerta domestica estratta: forse i tag sono diversi. "
              "Lancia 'esplora' e incollami l'output.")
        return

    with open("tariffe_luce.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(righe[0].keys()))
        w.writeheader()
        w.writerows(righe)
    with open("tariffe_luce.json", "w", encoding="utf-8") as f:
        json.dump(righe, f, ensure_ascii=False, indent=2)

    print(f"\nFatto: {len(righe)} offerte domestiche -> tariffe_luce.csv / .json")
    print("Anteprima prime 3:")
    for r in righe[:3]:
        print(" ", r)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "esplora"
    if mode == "esplora":
        esplora()
    elif mode == "estrai":
        estrai()
    else:
        print("Uso: python arera_tariffe.py [esplora|estrai]")
