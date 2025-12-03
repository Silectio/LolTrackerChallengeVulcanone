import streamlit as st
import requests
import os

import time
from datetime import datetime
import psycopg2

api_key = st.secrets.get("api_key")

base_url_lol = "https://euw1.api.riotgames.com"
base_url_riot = "https://europe.api.riotgames.com"

st.set_page_config(page_title="LoL Tracker", page_icon="🎮", layout="wide")
st.title("🎮 League of Legends Rank Tracker")
st.markdown("---")


@st.cache_resource
def get_db_conn():
    url = (
        st.secrets.get("database_url")
        or st.secrets.get("DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    if not url:
        return None
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists players (
              id bigserial primary key,
              game_name text not null,
              tag text not null,
              added_date timestamptz not null default now(),
              unique(game_name, tag)
            )
            """
        )
    conn.commit()
    return conn


def db_list_players(conn):
    with conn.cursor() as cur:
        cur.execute(
            "select game_name, tag, added_date from players order by added_date desc"
        )
        return cur.fetchall()


def db_add_player(conn, game_name, tag):
    with conn.cursor() as cur:
        cur.execute(
            "insert into players (game_name, tag) values (%s, %s) on conflict (game_name, tag) do nothing",
            (game_name, tag),
        )
    conn.commit()


def db_delete_player(conn, game_name, tag):
    with conn.cursor() as cur:
        cur.execute(
            "delete from players where game_name=%s and tag=%s", (game_name, tag)
        )
    conn.commit()


def get_account_by_riot_id(game_name, tag_line, show_errors=True):
    url = f"{base_url_riot}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    headers = {"X-Riot-Token": api_key}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            if show_errors:
                st.error("❌ Joueur non trouvé. Vérifiez le nom et le tag.")
            return None
        elif response.status_code == 401:
            if show_errors:
                st.error("❌ Clé API invalide ou expirée.")
            return None
        elif response.status_code == 429:
            if show_errors:
                st.error("⚠️ Limite de taux dépassée. Réessayez dans quelques instants.")
            return None
        else:
            if show_errors:
                st.error(f"❌ Erreur {response.status_code}: {response.text}")
            return None
    except Exception as e:
        if show_errors:
            st.error(f"❌ Erreur de connexion: {str(e)}")
        return None


def get_league_entries_by_puuid(puuid, show_errors=True):
    url = f"{base_url_lol}/lol/league/v4/entries/by-puuid/{puuid}"
    headers = {"X-Riot-Token": api_key}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            if show_errors:
                st.warning("⚠️ Aucune donnée de classement trouvée pour ce joueur.")
            return []
        else:
            if show_errors:
                st.error(f"❌ Erreur {response.status_code}: {response.text}")
            return None
    except Exception as e:
        if show_errors:
            st.error(f"❌ Erreur de connexion: {str(e)}")
        return None


def format_queue_type(queue_type):
    queue_names = {
        "RANKED_SOLO_5x5": "🏆 Ranked Solo/Duo",
        "RANKED_FLEX_SR": "👥 Ranked Flex",
        "RANKED_FLEX_TT": "👥 Ranked Flex 3v3",
        "CHERRY": "🍒 Arena",
    }
    return queue_names.get(queue_type, queue_type)


def get_rank_emoji(tier):
    emoji_map = {
        "IRON": "⚫",
        "BRONZE": "🟤",
        "SILVER": "⚪",
        "GOLD": "🟡",
        "PLATINUM": "🔷",
        "EMERALD": "🟢",
        "DIAMOND": "💎",
        "MASTER": "🔮",
        "GRANDMASTER": "🌟",
        "CHALLENGER": "👑",
    }
    return emoji_map.get(tier, "📊")


def display_rank_info(entry):
    tier = entry.get("tier", "N/A")
    rank = entry.get("rank", "")
    lp = entry.get("leaguePoints", 0)
    wins = entry.get("wins", 0)
    losses = entry.get("losses", 0)
    total_games = wins + losses
    winrate = (wins / total_games * 100) if total_games > 0 else 0
    hot_streak = entry.get("hotStreak", False)
    veteran = entry.get("veteran", False)
    st.markdown(f"### {get_rank_emoji(tier)} {tier.capitalize()} {rank}")
    st.markdown(f"**{lp} LP**")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Victoires", wins)
    with col2:
        st.metric("Défaites", losses)
    with col3:
        st.metric("Winrate", f"{winrate:.1f}%")
    badges = []
    if hot_streak:
        badges.append("🔥 Hot Streak")
    if veteran:
        badges.append("🎖️ Vétéran")
    if entry.get("freshBlood", False):
        badges.append("🆕 Nouveau")
    if badges:
        st.markdown(" • ".join(badges))
    if "miniSeries" in entry:
        mini = entry["miniSeries"]
        progress = mini.get("progress", "")
        progress_display = (
            progress.replace("W", "✅").replace("L", "❌").replace("N", "⬜")
        )
        st.markdown(f"**Série de promotion:** {progress_display}")


def get_main_rank(league_entries):
    if not league_entries:
        return "Unranked", 0, 0, 0
    for entry in league_entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            tier = entry.get("tier", "Unranked")
            rank = entry.get("rank", "")
            lp = entry.get("leaguePoints", 0)
            wins = entry.get("wins", 0)
            losses = entry.get("losses", 0)
            total = wins + losses
            winrate = (wins / total * 100) if total > 0 else 0
            return f"{tier} {rank}", lp, winrate, wins + losses
    return "Unranked", 0, 0, 0


def display_player_compact(player_data):
    name = player_data.get("display_name", "N/A")
    tag = player_data.get("tag", "N/A")
    rank, lp, winrate, games = player_data.get("rank_info", ("Unranked", 0, 0, 0))
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    with col1:
        st.markdown(f"**{name}#{tag}**")
    with col2:
        tier = rank.split()[0] if rank != "Unranked" else "Unranked"
        emoji = get_rank_emoji(tier.upper())
        st.markdown(f"{emoji} {rank}")
    with col3:
        st.markdown(f"**{lp}** LP")
    with col4:
        st.markdown(f"**{winrate:.0f}%** WR")
    with col5:
        st.markdown(f"{games} games")


st.sidebar.header("🎯 Mode")
mode = st.sidebar.radio(
    "Sélectionnez un mode:",
    ["🔍 Recherche individuelle", "👥 Liste de joueurs"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")

if mode == "🔍 Recherche individuelle":
    st.sidebar.header("🔍 Recherche de joueur")
    if not api_key:
        st.sidebar.error("⚠️ Clé API manquante dans les secrets.")
    else:
        st.sidebar.success("✅ Clé API chargée")

    with st.sidebar.form("search_form"):
        game_name = st.text_input(
            "Nom du joueur", value="Silectio", help="Entrez le nom du joueur (gameName)"
        )
        tag_line = st.text_input(
            "Tag", value="EUW", help="Entrez le tag du joueur (sans le #)"
        )
        submit_button = st.form_submit_button("🔍 Rechercher", use_container_width=True)

    if submit_button and game_name and tag_line:
        if not api_key:
            st.error("❌ Veuillez configurer votre clé API avant de continuer.")
        else:
            with st.spinner(f"🔄 Recherche de {game_name}#{tag_line}..."):
                account_data = get_account_by_riot_id(game_name, tag_line)

                if account_data:
                    puuid = account_data.get("puuid")
                    display_name = account_data.get("gameName", game_name)
                    display_tag = account_data.get("tagLine", tag_line)

                    st.success(f"✅ Joueur trouvé: **{display_name}#{display_tag}**")

                    st.markdown("---")
                    with st.spinner("🔄 Récupération des rangs..."):
                        league_entries = get_league_entries_by_puuid(puuid)

                        if league_entries is not None:
                            if len(league_entries) == 0:
                                st.info(
                                    "ℹ️ Ce joueur n'a pas encore de classement cette saison."
                                )
                            else:
                                st.subheader(f"📊 Classements de {display_name}")
                                titles = [
                                    str(
                                        format_queue_type(
                                            e.get("queueType") or "Unknown"
                                        )
                                    )
                                    for e in league_entries
                                ]
                                tabs = st.tabs(titles)
                                for t, entry in zip(tabs, league_entries):
                                    with t:
                                        display_rank_info(entry)
    elif not game_name or not tag_line:
        st.info(
            "👈 Entrez un nom de joueur et un tag dans la barre latérale pour commencer."
        )

else:  # Mode Liste de joueurs
    st.sidebar.header("👥 Gestion de la liste")
    conn = get_db_conn()
    if conn is None:
        st.sidebar.error("⚠️ DATABASE_URL manquant dans les secrets/environnement.")
        st.stop()
    if "players_list" not in st.session_state:
        rows = db_list_players(conn)
        st.session_state.players_list = [
            {
                "game_name": r[0],
                "tag": r[1],
                "added_date": r[2].isoformat() if r[2] else None,
            }
            for r in rows
        ]

    if not api_key:
        st.sidebar.error("⚠️ Clé API manquante dans les secrets.")
    else:
        st.sidebar.success("✅ Clé API chargée")

    with st.sidebar.form("add_player_form"):
        st.markdown("**➕ Ajouter un joueur**")
        new_game_name = st.text_input("Nom du joueur", help="Entrez le nom du joueur")
        new_tag_line = st.text_input("Tag", help="Entrez le tag (sans le #)")
        add_button = st.form_submit_button("➕ Ajouter", use_container_width=True)

    if add_button and new_game_name and new_tag_line:
        already_exists = any(
            p["game_name"].lower() == new_game_name.lower()
            and p["tag"].lower() == new_tag_line.lower()
            for p in st.session_state.players_list
        )

        if already_exists:
            st.sidebar.warning("⚠️ Ce joueur est déjà dans la liste!")
        else:
            db_add_player(conn, new_game_name, new_tag_line)
            rows = db_list_players(conn)
            st.session_state.players_list = [
                {
                    "game_name": r[0],
                    "tag": r[1],
                    "added_date": r[2].isoformat() if r[2] else None,
                }
                for r in rows
            ]
            st.sidebar.success(f"✅ {new_game_name}#{new_tag_line} ajouté!")
            st.rerun()

    st.sidebar.markdown("---")

    if st.sidebar.button(
        "🔄 Rafraîchir tous les rangs", use_container_width=True, type="primary"
    ):
        st.session_state.refresh_requested = True

    st.header(f"👥 Liste de joueurs ({len(st.session_state.players_list)})")

    if len(st.session_state.players_list) == 0:
        st.info("ℹ️ Aucun joueur dans la liste. Ajoutez-en un dans la barre latérale!")
    else:
        if st.session_state.get("refresh_requested", False):
            progress_bar = st.progress(0)
            status_text = st.empty()

            players_data = []
            total = len(st.session_state.players_list)

            for idx, player in enumerate(st.session_state.players_list):
                status_text.text(
                    f"🔄 Récupération de {player['game_name']}#{player['tag']}... ({idx+1}/{total})"
                )
                progress_bar.progress((idx + 1) / total)
                account_data = get_account_by_riot_id(
                    player["game_name"], player["tag"], show_errors=False
                )

                if account_data:
                    puuid = account_data.get("puuid")
                    display_name = account_data.get("gameName", player["game_name"])
                    display_tag = account_data.get("tagLine", player["tag"])
                    league_entries = get_league_entries_by_puuid(
                        puuid, show_errors=False
                    )

                    if league_entries is not None:
                        rank_info = get_main_rank(league_entries)

                        players_data.append(
                            {
                                "game_name": player["game_name"],
                                "tag": player["tag"],
                                "display_name": display_name,
                                "display_tag": display_tag,
                                "puuid": puuid,
                                "league_entries": league_entries,
                                "rank_info": rank_info,
                                "status": "success",
                            }
                        )
                    else:
                        players_data.append(
                            {
                                "game_name": player["game_name"],
                                "tag": player["tag"],
                                "status": "error_rank",
                            }
                        )
                else:
                    players_data.append(
                        {
                            "game_name": player["game_name"],
                            "tag": player["tag"],
                            "status": "error_account",
                        }
                    )
                if idx < total - 1:
                    time.sleep(1.2)

            progress_bar.empty()
            status_text.empty()

            st.session_state.players_data = players_data
            st.session_state.last_refresh = datetime.now().isoformat()
            st.session_state.refresh_requested = False
            st.success("✅ Tous les rangs ont été rafraîchis!")
            st.rerun()

        if st.session_state.get("last_refresh"):
            last_refresh_dt = datetime.fromisoformat(st.session_state.last_refresh)
            st.caption(
                f"🕐 Dernière mise à jour: {last_refresh_dt.strftime('%d/%m/%Y %H:%M:%S')}"
            )

        st.markdown("---")

        if st.session_state.get("players_data"):
            tier_order = {
                "CHALLENGER": 9,
                "GRANDMASTER": 8,
                "MASTER": 7,
                "DIAMOND": 6,
                "EMERALD": 5,
                "PLATINUM": 4,
                "GOLD": 3,
                "SILVER": 2,
                "BRONZE": 1,
                "IRON": 0,
                "UNRANKED": -1,
            }

            sorted_players = sorted(
                st.session_state.players_data,
                key=lambda p: (
                    tier_order.get(
                        p.get("rank_info", ("Unranked", 0, 0, 0))[0].split()[0].upper(),
                        -1,
                    ),
                    p.get("rank_info", ("Unranked", 0, 0, 0))[1],
                ),
                reverse=True,
            )
            col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1, 1, 1, 1])
            with col1:
                st.markdown("**👤 Joueur**")
            with col2:
                st.markdown("**🏆 Rang**")
            with col3:
                st.markdown("**💎 LP**")
            with col4:
                st.markdown("**📊 WR**")
            with col5:
                st.markdown("**🎮 Games**")
            with col6:
                st.markdown("**⚙️**")

            st.markdown("---")
            for idx, player in enumerate(sorted_players):
                if player.get("status") == "success":
                    name = player.get("display_name", "N/A")
                    tag = player.get("display_tag", "N/A")
                    rank, lp, winrate, games = player.get(
                        "rank_info", ("Unranked", 0, 0, 0)
                    )

                    col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1, 1, 1, 1])

                    with col1:
                        if st.button(
                            f"{name}#{tag}",
                            key=f"player_{idx}",
                            use_container_width=True,
                        ):
                            st.session_state.selected_player = player
                    with col2:
                        tier = rank.split()[0] if rank != "Unranked" else "Unranked"
                        emoji = get_rank_emoji(tier.upper())
                        st.markdown(f"{emoji} {rank}")
                    with col3:
                        st.markdown(f"**{lp}**")
                    with col4:
                        st.markdown(f"**{winrate:.0f}%**")
                    with col5:
                        st.markdown(f"{games}")
                    with col6:
                        if st.button("🗑️", key=f"delete_{idx}", help="Supprimer"):
                            db_delete_player(conn, player["game_name"], player["tag"])
                            rows = db_list_players(conn)
                            st.session_state.players_list = [
                                {
                                    "game_name": r[0],
                                    "tag": r[1],
                                    "added_date": r[2].isoformat() if r[2] else None,
                                }
                                for r in rows
                            ]
                            if "players_data" in st.session_state:
                                st.session_state.players_data = [
                                    p
                                    for p in st.session_state.players_data
                                    if not (
                                        p["game_name"] == player["game_name"]
                                        and p["tag"] == player["tag"]
                                    )
                                ]
                            st.rerun()
                else:
                    col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1, 1, 1, 1])
                    with col1:
                        st.markdown(f"**{player['game_name']}#{player['tag']}**")
                    with col2:
                        st.markdown("❌ Erreur")
                    with col6:
                        if st.button("🗑️", key=f"delete_err_{idx}", help="Supprimer"):
                            db_delete_player(conn, player["game_name"], player["tag"])
                            rows = db_list_players(conn)
                            st.session_state.players_list = [
                                {
                                    "game_name": r[0],
                                    "tag": r[1],
                                    "added_date": r[2].isoformat() if r[2] else None,
                                }
                                for r in rows
                            ]
                            st.rerun()

            if st.session_state.get("selected_player"):
                st.markdown("---")
                player = st.session_state.selected_player
                st.subheader(
                    f"📊 Détails de {player['display_name']}#{player['display_tag']}"
                )

                league_entries = player.get("league_entries", [])

                if len(league_entries) == 0:
                    st.info("ℹ️ Ce joueur n'a pas encore de classement cette saison.")
                else:
                    titles = [
                        str(format_queue_type(e.get("queueType") or "Unknown"))
                        for e in league_entries
                    ]
                    tabs = st.tabs(titles)
                    for t, entry in zip(tabs, league_entries):
                        with t:
                            display_rank_info(entry)
        else:
            st.info(
                "👆 Cliquez sur 'Rafraîchir tous les rangs' pour charger les données!"
            )
