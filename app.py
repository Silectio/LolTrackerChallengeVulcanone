import streamlit as st
import requests
from datetime import datetime
import psycopg2
import psycopg2.extras
import pandas as pd


# --- Configuration / Secrets ---
# On garde la compatibilité avec `st.secrets["api_key"]` mais on privilégie
# la dernière clé enregistrée en base (table `api_keys`).
DB_URL = st.secrets.get("database_url")
dictTier = {
    "IRON": 0,
    "BRONZE": 400,
    "SILVER": 800,
    "GOLD": 1200,
    "PLATINUM": 1600,
    "EMERALD": 2000,
    "DIAMOND": 2400,
    "MASTER": 2800,
}
dictRank = {"IV": 0, "III": 100, "II": 200, "I": 300}


def LP_from_League_entry(league_entry):
    tier = league_entry["tier"]
    rank = league_entry["rank"]
    lp = league_entry["leaguePoints"]
    totalLP = dictTier[tier] + dictRank[rank] + lp
    return totalLP


def db_execute(query, params=None, fetch=False):
    """Execute a query using a fresh connection each time.

    Returns fetched rows if fetch=True, otherwise returns None.
    This avoids keeping a long-lived connection that can be closed by the DB.
    """
    if not DB_URL:
        raise RuntimeError("DATABASE_URL not configured")
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            if fetch:
                rows = cur.fetchall()
                return rows
            conn.commit()
    finally:
        conn.close()


def db_select_all(table, columns=None):
    cols = "*" if not columns else ", ".join(columns)
    rows = db_execute(f"SELECT {cols} FROM {table}", fetch=True)
    return rows or []


def db_insert(table, obj: dict):
    keys = list(obj.keys())
    cols = ", ".join(keys)
    placeholders = ", ".join(["%s"] * len(keys))
    values = [obj[k] for k in keys]
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    print(sql)
    db_execute(sql, tuple(values), fetch=False)


def db_init_players_table():
    sql = """
    CREATE TABLE IF NOT EXISTS players (
        id bigserial primary key,
        game_name text not null,
        tag text not null,
        puuid text not null,
        added_date timestamptz not null default now(),
        UNIQUE(game_name, tag)
    )
    """
    db_execute(sql)


def db_init_api_keys_table():
    sql = """
    CREATE TABLE IF NOT EXISTS api_keys (
        id bigserial primary key,
        api_key text not null,
        added_date timestamptz not null default now()
    )
    """
    db_execute(sql)


def get_latest_api_key():
    """Retourne la dernière clé API Riot stockée en DB.

    Si aucune n'est présente, tente de lire `st.secrets["api_key"]`.
    """
    try:
        rows = db_execute(
            "SELECT api_key FROM api_keys ORDER BY added_date DESC LIMIT 1",
            fetch=True,
        )
        if rows:
            return rows[0]["api_key"]
    except Exception:
        # on ne bloque pas si la table n'existe pas encore ou autre
        pass
    return st.secrets.get("api_key")


def db_init_snapshot_table():
    sql = """
    CREATE TABLE IF NOT EXISTS snapshot (
        id bigserial primary key,
        game_name text not null,
        lp integer not null,
        snapshot_date timestamptz not null default now()
    )
    """
    db_execute(sql)


def get_account_by_riot_id(game_name, tag_line, show_errors=True):
    api_key = get_latest_api_key()
    if not api_key:
        if show_errors:
            st.error("Clé API Riot manquante. Ajoutez une clef")
        return None
    url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    headers = {"X-Riot-Token": api_key}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        if show_errors:
            st.error(f"Erreur réseau vers Riot API: {e}")
        return None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        if show_errors:
            st.error("Joueur introuvable (404). Vérifiez le nom et le tag.")
        return None
    if resp.status_code == 401:
        if show_errors:
            st.error("Clé API invalide (401).")
        return None
    if resp.status_code == 429:
        if show_errors:
            st.error("Trop de requêtes (429). Réessayez plus tard.")
        return None
    if show_errors:
        st.error(f"Erreur Riot API {resp.status_code}: {resp.text}")
    return None


def get_ranks_by_puuid(puuid, show_errors=True):
    api_key = get_latest_api_key()
    if not api_key:
        if show_errors:
            st.error("Clé API Riot manquante. Ajoutez une clef")
        return None
    url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    headers = {"X-Riot-Token": api_key}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        if show_errors:
            st.error(f"Erreur réseau vers Riot API: {e}")
        return None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        if show_errors:
            st.error("Joueur introuvable (404). Vérifier le puuid")
        return None
    if resp.status_code == 401:
        if show_errors:
            st.error("Clé API invalide (401).")
        return None
    if resp.status_code == 429:
        if show_errors:
            st.error("Trop de requêtes (429). Réessayez plus tard.")
        return None
    if show_errors:
        st.error(f"Erreur Riot API {resp.status_code}: {resp.text}")
    return None


def add_player_flow(game_name, tag_line):
    # validate via Riot API
    acct = get_account_by_riot_id(game_name, tag_line, show_errors=True)
    if acct is None:
        return False, "Impossible de valider le joueur via Riot API"

    # store minimal canonical names returned by API
    canonical_name = acct.get("gameName") or game_name
    canonical_tag = acct.get("tagLine") or tag_line
    canonical_puuid = acct.get("puuid")
    db_insert(
        "players",
        {"game_name": canonical_name, "tag": canonical_tag, "puuid": canonical_puuid},
    )
    return True, f"{canonical_name}#{canonical_tag} ajouté"


def get_all_players_rank():
    rows = db_select_all("players", ["game_name", "tag", "added_date", "puuid"])
    dictPlayer = {}

    for i in range(len(rows)):
        resp = get_ranks_by_puuid(rows[i]["puuid"])
        # print(i, resp, rows[i]["game_name"])
        if resp is None:
            return None

        for j in range(len(resp)):
            if resp[j]["queueType"] == "RANKED_SOLO_5x5":
                dictPlayer[rows[i]["game_name"]] = LP_from_League_entry(resp[j])
        # print("==========")
    return dictPlayer


def main():
    st.set_page_config(page_title="Vulcanone Challenge", layout="wide", page_icon="🔥")
    st.title("Vulcanone Challenge")
    st.divider()
    if not DB_URL:
        st.error(
            "DATABASE_URL absent. Configurez la variable d'environnement ou secrets."
        )
        st.stop()

    # ensure table exists
    try:
        db_init_players_table()
        db_init_snapshot_table()
        db_init_api_keys_table()
    except Exception as e:
        st.error(f"Erreur initialisation DB: {e}")
        st.stop()

    # get_rank = st.button("Get rank from all players")

    # if get_rank:
    #     rankDict = get_all_players_rank()
    #     print(rankDict)

    with st.sidebar:
        password = st.text_input("Mot de passe admin", type="password")
        if password == st.secrets.get("admin_password"):
            st.header("Administration")
            with st.sidebar.form("add_player"):
                st.header("➕ Ajouter un joueur")
                new_name = st.text_input("Nom du joueur (case-sensitive)")
                new_tag = st.text_input("Tag (sans #)")
                submit = st.form_submit_button("Ajouter")

            if submit:
                if not new_name or not new_tag:
                    st.sidebar.warning("Nom et tag requis.")
                else:
                    ok, msg = add_player_flow(new_name.strip(), new_tag.strip())
                    if ok:
                        st.sidebar.success(msg)
                    else:
                        st.sidebar.error(msg)

            snapshotButton = st.button("Créer un snapshot des LP")
            if snapshotButton:
                rankDict = get_all_players_rank()
                if rankDict:
                    for key in rankDict.keys():
                        db_insert(
                            "snapshot",
                            {
                                "game_name": key,
                                "lp": rankDict[key],
                            },
                        )
        st.divider()
        st.subheader("Clé API Riot temporaire")
        with st.form("add_api_key"):
            api_key_input = st.text_input(
                "Ajouter une clé Riot (lecture seule)",
                help="La dernière clé ajoutée sera utilisée pour les appels. Vous pouvez en crée une sur : https://developer.riotgames.com/",
            )
            add_key_btn = st.form_submit_button("Ajouter la clé")
        if add_key_btn:
            k = api_key_input.strip()
            if not k:
                st.warning("Veuillez saisir une clé valide.")
            else:
                try:
                    db_insert("api_keys", {"api_key": k})
                    st.success("Clé API ajoutée. Elle sera utilisée automatiquement.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur ajout clé API: {e}")
        st.button("Rafraîchir la page", on_click=lambda: None)

    st.header("Liste de joueurs")
    try:
        rows = db_select_all("players", ["game_name", "tag"])
        snapshots = db_select_all("snapshot", ["game_name", "lp"])
        for i in range(len(rows)):
            lp_snapshot = "-"
            for j in range(len(snapshots)):
                if snapshots[j]["game_name"] == rows[i]["game_name"]:
                    lp_snapshot = snapshots[j]["lp"]
            rows[i]["lp_snapshot"] = lp_snapshot
        current_ranks = get_all_players_rank()
        if rows:
            out = []
            for r in rows:
                d = dict(r)
                if current_ranks and r["game_name"] in current_ranks:
                    d["current_lp"] = current_ranks[r["game_name"]]
                    d["diff_lp"] = (
                        d["current_lp"] - d["lp_snapshot"]
                        if d["lp_snapshot"] != "-"
                        else "-"
                    )
                else:
                    d["current_lp"] = "-"
                    d["diff_lp"] = "-"

                out.append(d)
                d["game_name"] = f"{d['game_name']}#{d['tag']}"
                d.pop("tag", None)
            st.dataframe(
                pd.DataFrame(out),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "game_name": "Nom du joueur",
                    "lp_snapshot": "Dernier snapshot LP",
                    "current_lp": "LP actuel",
                    "diff_lp": "Diff LP",
                },
            )
        else:
            st.info("Aucun joueur enregistré.")
    except Exception as e:
        st.error(f"Erreur lecture DB: {e}")


if __name__ == "__main__":
    main()
