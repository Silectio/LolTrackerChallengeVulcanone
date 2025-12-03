import streamlit as st
import requests
import os
import time
from datetime import datetime, timezone
import psycopg2
import pandas as pd
import altair as alt

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
        cur.execute(
            """
            create table if not exists snapshots (
                id bigserial primary key,
                game_name text not null,
                tag text not null,
                tier text not null,
                rank text not null,
                lp int not null,
                created_at timestamptz not null default now()
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


def db_insert_snapshot(conn, game_name, tag, tier, rank, lp, created_at=None):
    ts = created_at or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "insert into snapshots (game_name, tag, tier, rank, lp, created_at) values (%s, %s, %s, %s, %s, %s)",
            (game_name, tag, tier, rank, int(lp), ts),
        )
    conn.commit()


def db_get_snapshots(conn, game_name=None, tag=None):
    with conn.cursor() as cur:
        if game_name and tag:
            cur.execute(
                "select game_name, tag, tier, rank, lp, created_at from snapshots where game_name=%s and tag=%s order by created_at asc",
                (game_name, tag),
            )
        else:
            cur.execute(
                "select game_name, tag, tier, rank, lp, created_at from snapshots order by created_at asc"
            )
        return cur.fetchall()


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
        "🔄 Rafraîchir et snapshot", use_container_width=True, type="primary"
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
                        tier_str = (
                            rank_info[0].split()[0]
                            if rank_info[0] != "Unranked"
                            else "UNRANKED"
                        )
                        rank_div = (
                            rank_info[0].split()[1]
                            if rank_info[0] != "Unranked"
                            and len(rank_info[0].split()) > 1
                            else ""
                        )
                        lp_val = rank_info[1]
                        try:
                            db_insert_snapshot(
                                conn,
                                player["game_name"],
                                player["tag"],
                                tier_str,
                                rank_div,
                                lp_val,
                            )
                        except Exception:
                            pass

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
        # Tableau récap évolutions
        try:
            snaps = db_get_snapshots(conn)
            df = pd.DataFrame(
                snaps, columns=["game_name", "tag", "tier", "rank", "lp", "created_at"]
            )
            if not df.empty:
                latest = (
                    df.sort_values("created_at").groupby(["game_name", "tag"]).tail(1)
                )
                daily = df.copy()
                daily["date"] = daily["created_at"].dt.date
                daily_agg = (
                    daily.groupby(["game_name", "tag", "date"])
                    .agg(lp=("lp", "max"))
                    .reset_index()
                )
                daily_delta = (
                    daily_agg.sort_values(["game_name", "tag", "date"])
                    .groupby(["game_name", "tag"])
                    .lp.diff()
                )
                daily_agg["lp_diff"] = daily_delta.fillna(0)
                daily_mean = (
                    daily_agg.groupby(["game_name", "tag"])
                    .lp_diff.mean()
                    .reset_index()
                    .rename(columns={"lp_diff": "lp_diff_day_avg"})
                )
                week = df.copy()
                week["week"] = week["created_at"].dt.isocalendar().week
                week_agg = (
                    week.groupby(["game_name", "tag", "week"])
                    .agg(lp=("lp", "max"))
                    .reset_index()
                )
                week_delta = (
                    week_agg.sort_values(["game_name", "tag", "week"])
                    .groupby(["game_name", "tag"])
                    .lp.diff()
                )
                week_agg["lp_diff"] = week_delta.fillna(0)
                week_mean = (
                    week_agg.groupby(["game_name", "tag"])
                    .lp_diff.mean()
                    .reset_index()
                    .rename(columns={"lp_diff": "lp_diff_week_avg"})
                )
                summary = latest.merge(
                    daily_mean, on=["game_name", "tag"], how="left"
                ).merge(week_mean, on=["game_name", "tag"], how="left")
                summary = summary[
                    [
                        "game_name",
                        "tag",
                        "tier",
                        "rank",
                        "lp",
                        "lp_diff_day_avg",
                        "lp_diff_week_avg",
                    ]
                ]
                st.subheader("📈 Évolution LP (récap)")
                st.dataframe(summary.fillna(0), use_container_width=True)
        except Exception:
            pass

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
            st.subheader("👥 Joueurs")
            cols = st.columns(5)
            for idx, player in enumerate(sorted_players):
                if player.get("status") == "success":
                    name = player.get("display_name", "N/A")
                    tag = player.get("display_tag", "N/A")
                    col = cols[idx % 5]
                    with col:
                        if st.button(
                            f"{name}#{tag}",
                            key=f"player_{idx}",
                            use_container_width=True,
                        ):
                            st.session_state.selected_player = player
                        if st.button("🗑️", key=f"delete_{idx}"):
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
                    col = cols[idx % 5]
                    with col:
                        st.markdown(f"**{player['game_name']}#{player['tag']}**")
                        if st.button("🗑️", key=f"delete_err_{idx}"):
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
                    f"📊 Évolution LP — {player['display_name']}#{player['display_tag']}"
                )
                try:
                    snaps = db_get_snapshots(conn, player["game_name"], player["tag"])
                    dfp = pd.DataFrame(
                        snaps,
                        columns=[
                            "game_name",
                            "tag",
                            "tier",
                            "rank",
                            "lp",
                            "created_at",
                        ],
                    ).sort_values("created_at")
                    if dfp.empty:
                        st.info("Aucune donnée de snapshot pour ce joueur.")
                    else:
                        chart = (
                            alt.Chart(dfp)
                            .mark_line(point=True)
                            .encode(
                                x="created_at:T",
                                y="lp:Q",
                                tooltip=["created_at:T", "lp:Q", "tier:N", "rank:N"],
                            )
                            .properties(height=300)
                        )
                        st.altair_chart(chart, use_container_width=True)
                        daily = dfp.copy()
                        daily["date"] = daily["created_at"].dt.date
                        daily_agg = (
                            daily.groupby("date").agg(lp=("lp", "max")).reset_index()
                        )
                        daily_agg["lp_diff"] = daily_agg["lp"].diff().fillna(0)
                        day_avg = daily_agg["lp_diff"].mean()
                        week = dfp.copy()
                        week["week"] = week["created_at"].dt.isocalendar().week
                        week_agg = (
                            week.groupby("week").agg(lp=("lp", "max")).reset_index()
                        )
                        week_agg["lp_diff"] = week_agg["lp"].diff().fillna(0)
                        week_avg = week_agg["lp_diff"].mean()
                        c1, c2 = st.columns(2)
                        with c1:
                            st.metric("Δ LP moyen par jour", f"{day_avg:.1f}")
                        with c2:
                            st.metric("Δ LP moyen par semaine", f"{week_avg:.1f}")
                except Exception:
                    st.warning("Impossible d’afficher le graphique pour ce joueur.")
        else:
            st.info(
                "👆 Cliquez sur 'Rafraîchir tous les rangs' pour charger les données!"
            )
