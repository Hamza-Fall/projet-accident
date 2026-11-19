"""
Dashboard « Accidents corporels de la circulation en Île-de-France » (2022-2024).

Audience : responsable sécurité routière (préfecture, département) qui doit décider où, quand et vers quels usagers agir.
Source   : ONISR / Ministère de l'Intérieur, bases annuelles des accidents corporels (data.gouv.fr), licence ouverte.
Données  : base SQLite régénérée au démarrage à partir des CSV du dossier data/ (voir init_db.py).

En local :   python app.py    puis http://127.0.0.1:8050
Déploiement : gunicorn app:server --timeout 300
"""
import os
import textwrap
from functools import lru_cache

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

import db
import init_db

# La base n'est jamais versionnée : sur Render elle est reconstruite à CHAQUE démarrage (disque éphémère) ;
# en local, seulement si elle est absente (`python init_db.py` force la reconstruction).
if os.environ.get("RENDER") or not os.path.exists(db.DB_PATH):
    init_db.construire_base(afficher=False)

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
ANNEES = [2022, 2023, 2024]
DEPARTEMENTS = ["75", "77", "78", "91", "92", "93", "94", "95"]
NOMS_DEP = {"75": "75 – Paris", "77": "77 – Seine-et-Marne", "78": "78 – Yvelines", "91": "91 – Essonne",
            "92": "92 – Hauts-de-Seine", "93": "93 – Seine-Saint-Denis", "94": "94 – Val-de-Marne", "95": "95 – Val-d'Oise"}
MOIS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
ORDRE_GRAVITE = ["Tué", "Blessé hospitalisé", "Blessé léger", "Indemne"]
COULEUR_GRAVITE = {"Tué": "#7B1E1E", "Blessé hospitalisé": "#E4572E", "Blessé léger": "#F2B134", "Indemne": "#9DB4C0"}
COULEUR_ANNEE = {2022: "#9DB4C0", 2023: "#5B8DB8", 2024: "#1F4E79"}
BLEU = "#1F4E79"
SEUIL_POPULATION = 5000            # classement par habitant : communes de plus de 5 000 habitants (évite les petits nombres)


def fr(x, n=0):
    """Format français : 2 408 ou 2 407,9"""
    return f"{x:,.{n}f}".replace(",", " ").replace(".", ",")


# ----------------------------------------------------------------------------
# Données : requêtes SQL (via db.py), mises en cache par combinaison de filtres
# ----------------------------------------------------------------------------
@lru_cache(maxsize=48)
def donnees(annees, deps, graves, usager):
    return {
        "kpi": db.indicateurs(annees, deps, graves, usager),
        "mois": db.accidents_par_mois(annees, deps, graves, usager),
        "jh": db.accidents_jour_heure(annees, deps, graves, usager),
        "gravite": db.gravite_par_usager(annees, deps, graves, usager),
        "communes": db.communes_accidents(annees, deps, graves, usager),
        "points": db.points_noirs(annees, deps, graves, usager, limite=300),
    }


# ----------------------------------------------------------------------------
# Graphiques
# ----------------------------------------------------------------------------
def wrap(texte, largeur=46):
    return "<br>".join(textwrap.wrap(texte, largeur))


def style(fig, titre, legende=False):
    fig.update_layout(template="plotly_white", autosize=True, height=None, showlegend=legende, font=dict(size=11),
                      title=dict(text=wrap(titre), x=0.01, xanchor="left", y=0.97, yanchor="top", font=dict(size=12)),
                      margin=dict(t=58, l=48, r=14, b=70 if legende else 38),
                      legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=10)))
    return fig


def fig_vide(message):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14, color="#777"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, "")


def fig_courbe(mois_df, annees):                                 # courbe : évolution mensuelle
    fig = go.Figure()
    totaux = {}
    for a in annees:
        y = mois_df[mois_df["annee"] == a].set_index("mois")["accidents"].reindex(range(1, 13), fill_value=0)
        totaux[a] = int(y.sum())
        fig.add_trace(go.Scatter(x=MOIS, y=y.values, mode="lines+markers", name=str(a), line=dict(color=COULEUR_ANNEE[a], width=2.5),
                                 hovertemplate="%{x} " + str(a) + " : %{y} accidents<extra></extra>"))
    premiere, derniere = min(annees), max(annees)
    if len(annees) >= 2 and totaux[premiere] > 0:
        var = (totaux[derniere] / totaux[premiere] - 1) * 100
        titre = f"Les accidents {'baissent' if var < 0 else 'augmentent'} de {fr(abs(var), 1)} % entre {premiere} et {derniere}"
    else:
        y = mois_df.groupby("mois")["accidents"].sum()
        titre = f"Le mois le plus chargé est {MOIS[int(y.idxmax()) - 1]} ({fr(y.max())} accidents)" if len(y) else "Accidents par mois"
    style(fig, titre, legende=True)
    fig.update_layout(yaxis=dict(title="Accidents", rangemode="tozero"))
    return fig


def fig_heatmap(jh_df):                                          # heatmap : jour × heure
    m = jh_df.pivot_table(index="jour_semaine", columns="heure", values="accidents", aggfunc="sum").reindex(index=range(7), columns=range(24)).fillna(0)
    jour, heure = np.unravel_index(np.argmax(m.values), m.shape)
    fig = go.Figure(go.Heatmap(z=m.values, x=list(range(24)), y=JOURS, colorscale="YlOrRd", colorbar=dict(thickness=10, title=dict(text="Acc.", side="top")),
                               hovertemplate="%{y} %{x}h : %{z} accidents<extra></extra>"))
    style(fig, f"Le pic est le {JOURS[jour].lower()} à {heure} h ({fr(m.values[jour, heure])} accidents)")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(dtick=3, title_text="Heure")
    return fig


def fig_gravite(g_df):                                           # barres empilées : gravité selon le type d'usager
    p = g_df[g_df["gravite"].isin(ORDRE_GRAVITE)].pivot_table(index="type_usager", columns="gravite", values="usagers", aggfunc="sum").fillna(0)
    p = p.reindex(columns=ORDRE_GRAVITE, fill_value=0)
    totaux = p.sum(axis=1)
    p = p[totaux >= 50]
    if p.empty:
        return fig_vide("Pas assez d'usagers pour ce filtre")
    part = p.div(p.sum(axis=1), axis=0) * 100
    touches = part["Tué"] + part["Blessé hospitalisé"]
    ordre = list(touches.sort_values().index)                    # le plus touché en haut
    fig = go.Figure()
    for g in ORDRE_GRAVITE:
        fig.add_trace(go.Bar(y=ordre, x=part.loc[ordre, g], orientation="h", name=g, marker_color=COULEUR_GRAVITE[g],
                             hovertemplate="%{y} – " + g + " : %{x:.1f} %<extra></extra>"))
    pire = touches.idxmax()
    style(fig, f"{pire} : {fr(touches.max())} % des usagers sont tués ou hospitalisés", legende=True)
    fig.update_layout(barmode="stack", xaxis=dict(ticksuffix=" %", range=[0, 100]), margin=dict(l=120))
    return fig


def fig_communes(c_df):                                          # barres horizontales : classement des communes
    c = c_df.copy()
    par_habitant = c["population"].notna().any()
    if par_habitant:
        c = c[c["population"] >= SEUIL_POPULATION].copy()
        c["valeur"] = c["accidents_graves"] / c["population"] * 100000
        unite, base = "accidents graves pour 100 000 habitants", f"communes de plus de {fr(SEUIL_POPULATION)} habitants"
    else:
        c["valeur"] = c["accidents_graves"]
        unite, base = "accidents graves", "population non chargée"
    c = c.sort_values("valeur", ascending=False).head(15)
    if c.empty:
        return fig_vide("Aucune commune pour ce filtre")
    c = c.iloc[::-1]                                             # la plus touchée en haut
    fig = go.Figure(go.Bar(y=c["commune"], x=c["valeur"], orientation="h", marker_color=BLEU,
                           text=[fr(v, 1 if par_habitant else 0) for v in c["valeur"]], textposition="outside", cliponaxis=False,
                           customdata=c[["accidents", "accidents_graves"]].values,
                           hovertemplate="%{y} : %{customdata[0]} accidents dont %{customdata[1]} graves<extra></extra>"))
    top = c.iloc[-1]
    style(fig, f"{top['commune']} : {fr(top['valeur'], 1 if par_habitant else 0)} {unite} ({base})")
    fig.update_layout(margin=dict(l=110, r=40), xaxis=dict(visible=False))
    return fig


def fig_nuage(c_df):                                             # nuage de points : accidents contre part de graves
    c = c_df[c_df["accidents"] >= 10].copy()
    if len(c) < 3:
        return fig_vide("Pas assez de communes (au moins 10 accidents) pour ce filtre")
    c["pct"] = c["accidents_graves"] / c["accidents"] * 100
    moyenne = c_df["accidents_graves"].sum() / c_df["accidents"].sum() * 100
    gros = c[c["accidents"] >= 30]
    if len(gros):
        pire = gros.loc[gros["pct"].idxmax()]
        titre = f"À {pire['commune']}, {fr(pire['pct'])} % des accidents sont graves, contre {fr(moyenne)} % en moyenne"
    else:
        titre = f"{fr(moyenne)} % des accidents sont graves en moyenne"
    fig = go.Figure(go.Scatter(x=c["accidents"], y=c["pct"], mode="markers", text=c["commune"],
                               marker=dict(size=7, color=BLEU, opacity=0.6, line=dict(width=0.5, color="white")),
                               hovertemplate="<b>%{text}</b><br>%{x} accidents<br>%{y:.1f} % graves<extra></extra>"))
    fig.add_hline(y=moyenne, line_dash="dot", line_color="#999")
    style(fig, titre)
    fig.update_layout(xaxis=dict(title="Accidents (échelle log)", type="log"), yaxis=dict(title="Accidents graves (%)", ticksuffix=" %", rangemode="tozero"))
    return fig


def fig_table(p_df):                                             # tableau : lieux les plus graves
    t = p_df.head(10)
    if t.empty:
        return fig_vide("Aucun lieu géolocalisé pour ce filtre")
    fig = go.Figure(go.Table(
        columnwidth=[3, 2.2, 1.2, 1.2, 1.2],
        header=dict(values=["<b>Lieu</b>", "<b>Commune</b>", "<b>Accid.</b>", "<b>Graves</b>", "<b>Tués</b>"],
                    fill_color=BLEU, font=dict(color="white", size=11), align="left", height=24),
        cells=dict(values=[t["lieu"].fillna("—"), t["commune"], t["accidents"], t["graves"], t["tues"]],
                   fill_color="#F5F6F8", align="left", font=dict(size=11), height=22)))
    style(fig, f"Les 10 lieux les plus graves cumulent {fr(t['graves'].sum())} accidents graves")
    fig.update_layout(margin=dict(t=58, l=8, r=8, b=8))
    return fig


# ----------------------------------------------------------------------------
# Carte Folium : points noirs (lieux regroupés à ~100 m), colorés selon le nombre d'accidents graves
# ----------------------------------------------------------------------------
def couleur_points(graves):
    return "#7B1E1E" if graves >= 4 else "#E4572E" if graves >= 2 else "#F2B134" if graves == 1 else "#9DB4C0"


LEGENDE_CARTE = """
<div style="position:fixed; bottom:14px; left:10px; z-index:9999; background:white; padding:6px 10px; border:1px solid #999;
            border-radius:6px; font-family:Arial; font-size:11px; box-shadow:0 1px 4px rgba(0,0,0,.3)">
  <b>Points noirs</b> (lieux regroupés à ~100 m, 300 plus graves)<br>
  <span style="color:#7B1E1E">●</span> 4 accidents graves ou plus &nbsp;
  <span style="color:#E4572E">●</span> 2 à 3 &nbsp;
  <span style="color:#F2B134">●</span> 1 &nbsp;
  <span style="color:#9DB4C0">●</span> aucun<br>
  Taille du cercle = nombre d'accidents
</div>"""

CARTE_VIDE = ("<html><body style='font-family:Arial;color:#777;display:flex;align-items:center;justify-content:center;height:100%'>"
              "<p>Aucun lieu géolocalisé pour ce filtre.</p></body></html>")


def carte_html(p_df):
    if p_df.empty:
        return CARTE_VIDE
    m = folium.Map(location=[48.85, 2.35], zoom_start=10, tiles=None, control_scale=True)
    folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                     attr="Tiles © Esri", name="Fond clair (Esri)", max_zoom=16).add_to(m)
    m.fit_bounds([[p_df["lat"].min(), p_df["lon"].min()], [p_df["lat"].max(), p_df["lon"].max()]], padding=(30, 30))
    for r in p_df.itertuples():
        popup = (f"<div style='font-family:Arial;font-size:12px'><b>{r.lieu if isinstance(r.lieu, str) else 'Lieu non renseigné'}</b><br>{r.commune}"
                 f"<br>{r.accidents} accident(s) dont <b>{r.graves}</b> grave(s), {int(r.tues)} avec tué(s)</div>")
        folium.CircleMarker(location=[r.lat, r.lon], radius=min(4 + 2.5 * np.sqrt(r.accidents), 22), color="white", weight=1,
                            fill=True, fill_color=couleur_points(r.graves), fill_opacity=0.85,
                            tooltip=f"{r.commune} – {r.accidents} accidents, {r.graves} graves", popup=folium.Popup(popup, max_width=260)).add_to(m)
    m.get_root().html.add_child(folium.Element(LEGENDE_CARTE))
    return m.get_root().render()


# ----------------------------------------------------------------------------
# Mise en page : une seule page, sans défilement
# ----------------------------------------------------------------------------
def cartes_kpi(k):
    taux = k["tues"] / k["accidents"] * 100 if k["accidents"] else 0
    cartes = [("Accidents corporels", fr(k["accidents"]), "#1F4E79"), ("Tués", fr(k["tues"]), "#7B1E1E"),
              ("Blessés hospitalisés", fr(k["hospitalises"]), "#E4572E"), ("Tués pour 100 accidents", fr(taux, 1), "#555")]
    return [html.Div(style={"flex": "1 1 0", "background": "white", "border": "1px solid #E0E0E0", "borderRadius": "8px",
                            "padding": "4px 12px", "borderLeft": f"5px solid {couleur}"},
                     children=[html.Div(titre, style={"fontSize": "11px", "color": "#666"}),
                               html.Div(valeur, style={"fontSize": "22px", "fontWeight": "bold", "color": couleur})])
            for titre, valeur, couleur in cartes]


app = Dash(__name__)
app.title = "Accidents de la route en Île-de-France"
server = app.server                      # exposé pour gunicorn : gunicorn app:server
app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<style>html, body {margin: 0; height: 100%; overflow: hidden;}</style>
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>"""

PANNEAU = {"position": "relative", "backgroundColor": "white", "border": "1px solid #E0E0E0", "borderRadius": "8px",
           "minHeight": 0, "minWidth": 0, "overflow": "hidden"}
REMPLIR = {"position": "absolute", "top": 0, "left": 0, "right": 0, "bottom": 0}
CONFIG = {"displayModeBar": False, "responsive": True}
ETIQUETTE = {"fontWeight": "bold", "fontSize": "11px", "color": "#444", "display": "block", "marginBottom": "2px"}


def graphique(identifiant):
    return html.Div(style=PANNEAU, children=dcc.Graph(id=identifiant, style=REMPLIR, config=CONFIG))


app.layout = html.Div(
    style={"height": "100vh", "boxSizing": "border-box", "display": "flex", "flexDirection": "column", "gap": "6px",
           "padding": "6px 12px", "fontFamily": "Arial, sans-serif", "backgroundColor": "#F5F6F8", "overflow": "hidden"},
    children=[
        # Bandeau : titre + filtres (un seul jeu de filtres pour tous les visuels)
        html.Div(
            style={"display": "flex", "alignItems": "flex-end", "justifyContent": "space-between", "gap": "14px",
                   "flex": "0 0 auto", "position": "relative", "zIndex": 10},
            children=[
                html.Div([
                    html.H1("Accidents de la route en Île-de-France : où, quand et chez qui agir ?",
                            style={"margin": 0, "fontSize": "18px", "color": BLEU}),
                    html.Div("Accidents corporels 2022-2024 · Source : ONISR / Ministère de l'Intérieur (data.gouv.fr)",
                             style={"fontSize": "11px", "color": "#666"}),
                ]),
                html.Div(style={"display": "flex", "gap": "12px", "alignItems": "flex-end"}, children=[
                    html.Div(style={"width": "150px"}, children=[html.Label("Année(s)", style=ETIQUETTE), dcc.Dropdown(
                        id="filtre-annee", options=[{"label": str(a), "value": a} for a in ANNEES], value=ANNEES, multi=True, clearable=False)]),
                    html.Div(style={"width": "230px"}, children=[html.Label("Département(s)", style=ETIQUETTE), dcc.Dropdown(
                        id="filtre-dep", options=[{"label": NOMS_DEP[d], "value": d} for d in DEPARTEMENTS], value=DEPARTEMENTS, multi=True, clearable=False)]),
                    html.Div(style={"width": "190px"}, children=[html.Label("Accidents affichés", style=ETIQUETTE), dcc.Dropdown(
                        id="filtre-gravite", options=[{"label": "Tous les accidents", "value": "tous"},
                                                      {"label": "Accidents graves (tué ou hospitalisé)", "value": "graves"}],
                        value="tous", clearable=False)]),
                    html.Div(style={"width": "190px"}, children=[html.Label("Usager impliqué", style=ETIQUETTE), dcc.Dropdown(
                        id="filtre-usager", options=[{"label": "Tous les usagers", "value": "Tous"}] + [{"label": t, "value": t} for t in db.TYPES_USAGERS],
                        value="Tous", clearable=False)]),
                ]),
            ]),

        # Chiffres clés
        html.Div(id="kpi", style={"display": "flex", "gap": "8px", "flex": "0 0 auto"}),

        # Corps : 6 visuels à gauche (grille 2 x 3), carte à droite
        html.Div(
            style={"flex": "1 1 0", "minHeight": 0, "display": "grid", "gap": "8px",
                   "gridTemplateColumns": "minmax(0, 1.25fr) minmax(0, 1fr)", "gridTemplateRows": "minmax(0, 1fr)"},
            children=[
                html.Div(
                    style={"display": "grid", "gap": "8px", "minHeight": 0, "minWidth": 0,
                           "gridTemplateColumns": "minmax(0, 1fr) minmax(0, 1fr)", "gridTemplateRows": "repeat(3, minmax(0, 1fr))"},
                    children=[graphique("g-courbe"), graphique("g-heatmap"), graphique("g-gravite"),
                              graphique("g-communes"), graphique("g-nuage"), graphique("g-table")]),
                html.Div(style=PANNEAU, children=html.Iframe(id="carte", srcDoc="", style={**REMPLIR, "width": "100%", "height": "100%", "border": "none"})),
            ]),
    ])


# ----------------------------------------------------------------------------
# Callback : un seul jeu de filtres -> 6 graphiques + chiffres clés + carte
# ----------------------------------------------------------------------------
@app.callback(
    Output("kpi", "children"),
    Output("g-courbe", "figure"), Output("g-heatmap", "figure"), Output("g-gravite", "figure"),
    Output("g-communes", "figure"), Output("g-nuage", "figure"), Output("g-table", "figure"),
    Output("carte", "srcDoc"),
    Input("filtre-annee", "value"), Input("filtre-dep", "value"),
    Input("filtre-gravite", "value"), Input("filtre-usager", "value"),
)
def mettre_a_jour(annees, deps, gravite, usager):
    annees = tuple(sorted(a for a in (annees or []) if a in ANNEES))
    deps = tuple(sorted(d for d in (deps or []) if d in DEPARTEMENTS))
    if not annees or not deps:
        vide = fig_vide("Sélectionnez au moins une année et un département")
        return cartes_kpi({"accidents": 0, "tues": 0, "hospitalises": 0}), vide, vide, vide, vide, vide, vide, CARTE_VIDE
    d = donnees(annees, deps, gravite == "graves", usager or "Tous")
    if d["kpi"]["accidents"] == 0:
        vide = fig_vide("Aucun accident pour ces filtres")
        return cartes_kpi(d["kpi"]), vide, vide, vide, vide, vide, vide, CARTE_VIDE
    return (cartes_kpi(d["kpi"]), fig_courbe(d["mois"], list(annees)), fig_heatmap(d["jh"]), fig_gravite(d["gravite"]),
            fig_communes(d["communes"]), fig_nuage(d["communes"]), fig_table(d["points"]), carte_html(d["points"]))


if __name__ == "__main__":
    app.run(debug=True)
