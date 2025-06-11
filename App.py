# Installation des dépendances
!pip install -q streamlit pandas
!wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared -q
!chmod +x cloudflared

# Création du fichier app.py
with open("app.py", "w") as f:
    f.write('''
import streamlit as st
import math
import pandas as pd
import json
from datetime import datetime
from io import BytesIO

# ==================== CLASSE ARE ====================
class AREIntermittent:
    """Calculateur ARE basé sur les règles officielles de France Travail,
    avec la distinction entre Annexe 8 (Techniciens) et Annexe 10 (Artistes)."""

    AJ_MINIMALE = 31.71 # Mise à jour de la valeur de l'AJ minimale au 1er juillet 2024 (source Unédic)
    SMIC_JOURNALIER = 60.0 # Valeur indicative pour le seuil de prélèvements sociaux

    PARAMS = {
        8: {  # Techniciens
            "seuil_salaire": 14400, "taux_salaire_inf": 0.42, "taux_salaire_sup": 0.05,
            "seuil_heures": 720, "taux_heures_inf": 0.26, "taux_heures_sup": 0.08,
            "partie_c": 0.40, "plancher": 38.34 # Mise à jour du plancher
        },
        10: {  # Artistes
            # Pour l'Annexe 10, nous allons implémenter la formule SJR + bonus cachets
            # Ces paramètres sont moins directement utilisés dans cette nouvelle logique
            "seuil_salaire": 13700, "taux_salaire_inf": 0.36, "taux_salaire_sup": 0.05,
            "seuil_heures": 690, "taux_heures_inf": 0.26, "taux_heures_sup": 0.08,
            "partie_c": 0.70, "plancher": 44.43 # Mise à jour du plancher
        }
    }

    @staticmethod
    def calculer_are(annexe, salaire_reference_brut_12mois, heures_travaillees_12mois, total_cachets_12mois, jours_reference=365):
        """
        Calcule l'ARE journalière brute et nette pour un intermittent du spectacle.

        Args:
            annexe (int): Annexe de rattachement (8 pour techniciens, 10 pour artistes).
            salaire_reference_brut_12mois (float): Salaire brut total sur les 12 derniers mois.
            heures_travaillees_12mois (int): Nombre total d'heures travaillées sur les 12 derniers mois.
            total_cachets_12mois (int): Nombre total de cachets sur les 12 derniers mois (important pour Annexe 10).
            jours_reference (int): Nombre de jours calendaires sur la période de référence (souvent 365 ou 366).
                                   Pour les intermittents, la période peut être ramenée à 319 jours ou autre selon les cas.
                                   Laisser 365 pour un calcul simple ou ajuster si SJR déjà connu.
        Returns:
            dict: Dictionnaire contenant l'ARE nette, brute et les détails.
        """
        params = AREIntermittent.PARAMS[annexe]
        are_brute = 0
        details = {}
        sjr = 0 # Salaire Journalier de Référence

        # Calcul du SJR si jours_reference est fourni
        if jours_reference > 0:
            sjr = salaire_reference_brut_12mois / jours_reference

        if annexe == 10: # Artistes : Utilisation de la formule SJR + bonus cachets
            # Refaire le calcul AJ pour annexe 10 selon Grok
            # Étape 1 : SJR est déjà calculé
            # Étape 2 : Partie A (fixe ici) - Max(AJ_MINIMALE, 70% * SJR)
            partie_a_grok = max(AREIntermittent.AJ_MINIMALE, 0.70 * sjr)
            # Étape 3 : Partie B (variable, cachets) - 12,27 * Nbre cachets / 12
            partie_b_grok = 12.27 * total_cachets_12mois / 12
            # Étape 4 : AJ brute (A + B)
            are_brute = partie_a_grok + partie_b_grok
            # Application du plancher pour l'annexe 10
            are_brute = max(are_brute, params["plancher"])

            details = {
                "sjr": round(sjr, 2),
                "partie_sjr_70pc": round(0.70 * sjr, 2),
                "partie_a_grok_final": round(partie_a_grok, 2),
                "partie_b_grok_cachets": round(partie_b_grok, 2)
            }


        elif annexe == 8: # Techniciens : Utilisation de la formule A+B+C

            # Partie A (Salaire)
            salaire_calcul_a = salaire_reference_brut_12mois
            if salaire_calcul_a <= params["seuil_salaire"]:
                a = (AREIntermittent.AJ_MINIMALE * params["taux_salaire_inf"] * salaire_calcul_a) / 5000
            else:
                a = (AREIntermittent.AJ_MINIMALE *
                    (params["taux_salaire_inf"] * params["seuil_salaire"] +
                     params["taux_salaire_sup"] * (salaire_calcul_a - params["seuil_salaire"]))) / 5000

            # Partie B (Heures)
            if heures_travaillees_12mois <= params["seuil_heures"]:
                b = (AREIntermittent.AJ_MINIMALE * params["taux_heures_inf"] * heures_travaillees_12mois) / 507
            else:
                b = (AREIntermittent.AJ_MINIMALE *
                    (params["taux_heures_inf"] * params["seuil_heures"] +
                     params["taux_heures_sup"] * (heures_travaillees_12mois - params["seuil_heures"]))) / 507

            # Partie C (Fixe)
            c = AREIntermittent.AJ_MINIMALE * params["partie_c"]

            are_brute = max(a + b + c, params["plancher"])

            details = {
                "partie_a": round(a, 2),
                "partie_b": round(b, 2),
                "partie_c": round(c, 2)
            }
        else:
            st.error("Annexe non supportée.")
            return {"net": 0, "brut": 0, "details": {}}

        # Calcul de l'ARE nette (CSG/CRDS)
        # Taux standard de 6.7% (6.2% CSG + 0.5% CRDS) si l'ARE brute est supérieure au SMIC journalier
        are_nette = are_brute * 0.933 if are_brute > AREIntermittent.SMIC_JOURNALIER else are_brute # 1 - (0.062+0.005) = 0.933

        # Ajout du diviseur d'annualisation pour l'ARE nette journalière,
        # comme suggéré par Grok pour coller aux résultats de France Travail pour Annexe 10
        # Attention : ce diviseur (1.76) est une "pratique courante" et non une règle officielle Unédic claire.
        # Il peut varier et est appliqué uniquement à l'Annexe 10 dans cette implémentation.
        diviseur_annualisation = 1.76

        if annexe == 10:
             are_nette_journaliere_final = are_nette / diviseur_annualisation
             details["diviseur_annualisation_applique"] = diviseur_annualisation
             details["are_nette_avant_diviseur"] = round(are_nette, 2)
        else: # Annexe 8 n'utilise généralement pas ce diviseur pour le calcul journalier
            are_nette_journaliere_final = are_nette
            details["diviseur_annualisation_applique"] = "Non applicable"


        return {
            "net": round(are_nette_journaliere_final, 2),
            "brut": round(are_brute, 2), # Le brut n'est pas divisé par 1.76
            "details": details
        }

# ==================== CONFIGURATION ====================
# Les VALEURS_PAR_DEFAUT peuvent être ajustées si besoin
VALEURS_PAR_DEFAUT = {
    "smic_horaire": 11.65, # SMIC horaire brut au 1er janvier 2025 (indicatif)
    "are_annexe8": 38.34, # Plancher Annexe 8
    "are_annexe10": 44.43, # Plancher Annexe 10
    "taux_majoration_6h": 0.0, # Mis à 0 car ce bonus spécifique est retiré de la formule officielle
    "bonus_seuil_cachets": 0, # Mis à 0 car ce bonus spécifique est retiré de la formule officielle
    "bonus_montant": 0 # Mis à 0 car ce bonus spécifique est retiré de la formule officielle
}

if "historique" not in st.session_state:
    st.session_state.historique = pd.DataFrame(columns=[
        "Date", "Type", "Annexe", "Cachets", "Cachets 6h", "Heures",
        "Salaire Ref", "ARE Journalière", "Bonus", "ARE Mensuelle", "Details CDD"
    ])

if "parametres" not in st.session_state:
    st.session_state.parametres = VALEURS_PAR_DEFAUT

# ==================== FONCTIONS ====================
def charger_parametres():
    try:
        with open("parametres.json", "r") as f:
            st.session_state.parametres = json.load(f)
    except:
        st.session_state.parametres = VALEURS_PAR_DEFAUT

def sauvegarder_parametres():
    with open("parametres.json", "w") as f:
        json.dump(st.session_state.parametres, f)

def calcul_jni(annexe, heures_totales, jours_mois):
    """Calcul des Jours Non Indemnisés (JNI)"""
    if annexe == 10:
        return min(math.ceil((heures_totales * 1.3) / 10), jours_mois)
    else:
        return min(math.ceil((heures_totales * 1.4) / 8), jours_mois)

def to_excel(df):
    """Export Excel"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# ==================== INTERFACE ====================
st.set_page_config(layout="wide", page_title="Intermittent Pro V1.6")

# Navigation
page = st.sidebar.radio("Menu", [
    "🏠 Dashboard",
    "🧮 Calculateur ARE",
    "📅 Simulateur Mensuel",
    "📊 Historique",
    "⚙️ Paramètres"
])

# Page : Dashboard
if page == "🏠 Dashboard":
    st.title("📊 Tableau de bord V1.6")
    st.markdown("""
    **Fonctionnalités incluses :**
    - ✅ Calculateur ARE (Annexe 8 et 10)
    - ✅ Simulation mensuelle (CDD, auto-entrepreneur, formations)
    - ✅ Historique modifiable et export Excel
    """)

# Page : Calculateur ARE
elif page == "🧮 Calculateur ARE":
    st.title("🧮 Calculateur ARE (Basé sur règles Unédic)")
    st.warning("Note : Le calcul de l'ARE est complexe. Ce simulateur fournit une estimation basée sur les règles connues. Le calcul exact de France Travail peut varier.")

    col1, col2 = st.columns(2)
    with col1:
        annexe = st.radio("Annexe de rattachement", [10, 8], format_func=lambda x: "Artiste (10)" if x == 10 else "Technicien (8)")
        # CORRECTION ICI : Conversion de min_value et max_value en float
        salaire_brut_12mois = st.number_input("Salaire brut total sur 12 mois (€)", min_value=1000.0, max_value=100000.0, value=8536.59 if annexe == 10 else 15000.0, help="Le salaire brut figurant sur vos fiches de paie sur les 12 derniers mois.")
        heures_travaillees_12mois = st.number_input("Heures travaillées sur 12 mois", min_value=10, max_value=2000, value=732 if annexe == 10 else 800, help="Nombre total d'heures (ou équivalent cachets) sur les 12 derniers mois.")
    with col2:
        total_cachets_12mois = st.number_input("Total cachets sur 12 mois", min_value=0, max_value=200, value=61, help="Nombre total de cachets sur la période de référence (important pour les artistes).")
        jours_reference_calendaires = st.number_input("Jours calendaires de la période de référence", min_value=1, max_value=366, value=319, help="Nombre de jours entre la fin de votre dernier contrat et le point de départ de la période de référence. Souvent 365, mais peut être 319 dans certains calculs.")

    if st.button("Calculer l'ARE", type="primary"):
        result = AREIntermittent.calculer_are(annexe, salaire_brut_12mois, heures_travaillees_12mois, total_cachets_12mois, jours_reference_calendaires)

        st.success(f"""
        ### Résultats Estimés de l'ARE Journalière
        **ARE journalière brute :** {result['brut']} €
        **ARE journalière nette estimée :** {result['net']} €
        """)
        with st.expander("Détails du calcul"):
            st.json(result['details']) # Afficher les détails du calcul spécifique à chaque annexe

# Page : Simulateur Mensuel
elif page == "📅 Simulateur Mensuel":
    st.title("📅 Simulateur Mensuel Complet")

    col1, col2 = st.columns(2)
    with col1:
        annexe = st.radio("Statut", [10, 8], key="annexe_mensuel", format_func=lambda x: "Artiste (10)" if x == 10 else "Technicien (8)")
        jours_mois = st.number_input("Jours dans le mois", 28, 31, 30)
        cachets = st.number_input("Nombre de cachets travaillés ce mois-ci", 0, 31, 5)
        heures_cachet = st.number_input("Heures par cachet (pour calcul JNI)", 1, 12, 12 if annexe == 10 else 8)

    with col2:
        montant_cachet = st.number_input("Montant net par cachet (€)", 50, 1000, 90)
        has_cdd = st.checkbox("Ajouter un CDD")
        has_auto = st.checkbox("Ajouter auto-entrepreneur")

    # Formulaire CDD détaillé
    cdd_heures = 0
    cdd_taux_horaire = 0.0
    if has_cdd:
        with st.expander("📝 Détails CDD", expanded=True):
            cdd_heures = st.number_input("Heures CDD", 0, 200, 143)
            cdd_taux_horaire = st.number_input("Taux horaire net (€)", 0.0, 100.0, 11.61)

    # Formulaire auto-entrepreneur
    auto_montant = 0
    if has_auto:
        with st.expander("📝 Détails Auto-entrepreneur"):
            auto_montant = st.number_input("Revenu net auto-entrepreneur (€)", 0, 10000, 800)

    # Section Heures assimilées
    with st.expander("⏱ Heures assimilées (formations, maladie...)"):
        heures_formation = st.number_input("Heures de formation", 0, 200, 0)
        cachets_repet = st.number_input("Cachets répétition (6h)", 0, 50, 0)
        jours_maladie = st.number_input("Jours de maladie non payés", 0, 30, 0)

    # Champ manuel pour l'ARE journalière
    with st.expander("⚙️ Paramètres avancés"):
        # La valeur par défaut est basée sur l'ARE réelle que vous avez mentionnée
        are_journaliere_override = st.number_input("ARE journalière à utiliser pour la simulation (€)", value=49.70, min_value=0.0, max_value=100.0, step=0.01, help="Ce montant est utilisé pour le calcul de l'ARE mensuelle et n'est pas calculé par ce simulateur.")

    # Calcul
    if st.button("Simuler le mois", type="primary"):
        # Heures totales (inclut répétitions, maladie, formations)
        heures_totales = (cachets * heures_cachet) + (cachets_repet * 6) + (jours_maladie * 8) + heures_formation + cdd_heures

        # Jours indemnisés
        # IMPORTANT : Pour le simulateur mensuel, nous utilisons calcul_jni car c'est pour la gestion des jours.
        # La valeur de are_journaliere_override est saisie manuellement.
        jni = calcul_jni(annexe, heures_totales, jours_mois)
        jours_indem = max(jours_mois - jni, 0)

        # Calcul ARE mensuelle
        are_mensuelle = are_journaliere_override * jours_indem

        # Préparer les détails du CDD pour l'historique
        details_cdd = f"{cdd_heures}h à {cdd_taux_horaire}€/h" if has_cdd else ""

        # Sauvegarde dans l'historique
        new_row = {
            "Date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "Type": "Mensuel",
            "Annexe": annexe,
            "Cachets": cachets,
            "Cachets 6h": cachets_repet, # Ici, cachets_repet sont les cachets de 6h pour le JNI
            "Heures": heures_totales,
            "Salaire Ref": "N/A (Mensuel)", # Indique que le salaire de ref n'est pas calculé ici
            "ARE Journalière": are_journaliere_override,
            "Bonus": "N/A", # Pas de calcul de bonus dans cette section
            "ARE Mensuelle": round(are_mensuelle, 2),
            "Details CDD": details_cdd
        }
        st.session_state.historique = pd.concat([st.session_state.historique, pd.DataFrame([new_row])], ignore_index=True)

        # Affichage résultats
        st.success(f"""
        **RÉSULTATS DE LA SIMULATION MENSUELLE :**
        - Heures totales travaillées/assimilées : **{heures_totales} heures**
        - Jours Non Indemnisés (JNI) : **{jni} jours**
        - Jours indemnisables ce mois-ci : **{jours_indem} jours**
        - ARE journalière utilisée pour le calcul : **{are_journaliere_override} €**
        - **ARE mensuelle estimée : {are_mensuelle:.2f} €**
        - Revenu CDD : **{cdd_heures * cdd_taux_horaire:.2f} €**
        - Revenu Auto-entrepreneur : **{auto_montant:.2f} €**
        - **Revenu total net estimé ce mois-ci : {are_mensuelle + (cachets * montant_cachet) + (cdd_heures * cdd_taux_horaire) + auto_montant:.2f} €**
        """)


# Page : Historique
elif page == "📊 Historique":
    st.title("📊 Historique Complet")

    if not st.session_state.historique.empty:
        # Permettre la suppression de lignes
        st.subheader("Modifier ou supprimer des entrées")
        edited_df = st.data_editor(
            st.session_state.historique,
            column_config={
                "ARE Journalière": st.column_config.NumberColumn(format="%.2f €"),
                "ARE Mensuelle": st.column_config.NumberColumn(format="%.2f €")
            },
            hide_index=False, # Afficher l'index pour faciliter la suppression
            use_container_width=True,
            num_rows="dynamic" # Permet d'ajouter/supprimer des lignes
        )
        st.session_state.historique = edited_df # Mettre à jour l'historique avec les modifications

        st.subheader("Exporter l'historique")
        # Export
        st.download_button(
            "📥 Exporter en Excel",
            data=to_excel(st.session_state.historique), # Utiliser le df de session_state mis à jour
            file_name="historique_intermittent.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Aucune donnée enregistrée dans l'historique.")

# Page : Paramètres
elif page == "⚙️ Paramètres":
    st.title("⚙️ Paramètres Avancés")
    st.warning("Attention : Modifier ces paramètres peut altérer la précision des calculs si les valeurs ne correspondent pas aux règles actuelles de France Travail.")

    st.subheader("Paramètres de base")
    col1, col2 = st.columns(2)
    with col1:
        # AJ_MINIMALE est maintenant une constante dans la classe
        st.info(f"AJ Minimale utilisée : **{AREIntermittent.AJ_MINIMALE} €** (Code)")
        # SMIC_JOURNALIER est maintenant une constante dans la classe
        st.info(f"SMIC Journalier utilisé pour prélèvement : **{AREIntermittent.SMIC_JOURNALIER} €** (Code)")
        st.number_input("SMIC Horaire brut (€)", value=VALEURS_PAR_DEFAUT["smic_horaire"], step=0.01, key="smic_horaire_param")
    with col2:
        st.number_input("Plancher ARE Annexe 8 (€)", value=AREIntermittent.PARAMS[8]["plancher"], step=0.01, key="plancher_a8_param", disabled=True)
        st.number_input("Plancher ARE Annexe 10 (€)", value=AREIntermittent.PARAMS[10]["plancher"], step=0.01, key="plancher_a10_param", disabled=True)
        st.number_input("Taux de prélèvement social (%)", value=6.7, step=0.1, help="CSG (6.2%) + CRDS (0.5%) = 6.7%. Appliqué si ARE brute > SMIC journalier.", disabled=True)
        st.number_input("Diviseur d'annualisation Annexe 10 (ex: 1.76)", value=1.76, step=0.01, help="Ce diviseur est une pratique courante pour lisser l'ARE journalière des artistes.", disabled=True)

    st.subheader("Coefficients Annexe 8 (Techniciens)")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.number_input("Seuil Salaire (€)", value=AREIntermittent.PARAMS[8]["seuil_salaire"], disabled=True)
        st.number_input("Taux Salaire Inf", value=AREIntermittent.PARAMS[8]["taux_salaire_inf"], format="%.2f", disabled=True)
    with col2:
        st.number_input("Seuil Heures", value=AREIntermittent.PARAMS[8]["seuil_heures"], disabled=True)
        st.number_input("Taux Heures Inf", value=AREIntermittent.PARAMS[8]["taux_heures_inf"], format="%.2f", disabled=True)
    with col3:
        st.number_input("Taux Salaire Sup", value=AREIntermittent.PARAMS[8]["taux_salaire_sup"], format="%.2f", disabled=True)
        st.number_input("Taux Heures Sup", value=AREIntermittent.PARAMS[8]["taux_heures_sup"], format="%.2f", disabled=True)
        st.number_input("Partie C (fixe)", value=AREIntermittent.PARAMS[8]["partie_c"], format="%.2f", disabled=True)

    # st.subheader("Coefficients Annexe 10 (Artistes) - Formule A+B+C")
    # st.info("Ces coefficients sont conservés pour information, mais la formule principale pour Annexe 10 est 'SJR + bonus cachets'.")
    # col1, col2, col3 = st.columns(3)
    # with col1:
    #     st.number_input("Seuil Salaire (€)", value=AREIntermittent.PARAMS[10]["seuil_salaire"], disabled=True)
    #     st.number_input("Taux Salaire Inf", value=AREIntermittent.PARAMS[10]["taux_salaire_inf"], format="%.2f", disabled=True)
    # with col2:
    #     st.number_input("Seuil Heures", value=AREIntermittent.PARAMS[10]["seuil_heures"], disabled=True)
    #     st.number_input("Taux Heures Inf", value=AREIntermittent.PARAMS[10]["taux_heures_inf"], format="%.2f", disabled=True)
    # with col3:
    #     st.number_input("Taux Salaire Sup", value=AREIntermittent.PARAMS[10]["taux_salaire_sup"], format="%.2f", disabled=True)
    #     st.number_input("Taux Heures Sup", value=AREIntermittent.PARAMS[10]["taux_heures_sup"], format="%.2f", disabled=True)
    #     st.number_input("Partie C (fixe)", value=AREIntermittent.PARAMS[10]["partie_c"], format="%.2f", disabled=True)

    # Note sur les bonus (pour retirer l'affichage des anciens bonus des paramètres)
    st.subheader("Anciens bonus spécifiques (désactivés)")
    st.info("Les bonus 'Majoration 30% cachets 6h' et '+5€ après 60 cachets' ne sont pas intégrés dans le calcul ARE des annexes 8 et 10 selon les règles officielles d'Unédic pour le moment. Ils sont désactivés pour plus de précision.")

    # Les boutons de sauvegarde pour les paramètres généraux ont été retirés
    # car la plupart des valeurs sont maintenant en dur dans la classe pour refléter les règles officielles.
    # Seul le SMIC horaire (pour info, pas directement dans AREIntermittent) peut être édité.
    if st.button("Sauvegarder les paramètres affichables", type="primary"):
        st.session_state.parametres.update({
            "smic_horaire": st.session_state.smic_horaire_param
        })
        sauvegarder_parametres()
        st.success("Paramètres affichables sauvegardés !")

# Initialisation
charger_parametres()
''')

# Lancement
!nohup streamlit run app.py --server.port 8501 > logs.txt 2>&1 &
!./cloudflared tunnel --url http://localhost:8501
