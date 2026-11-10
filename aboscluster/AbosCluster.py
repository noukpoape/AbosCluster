#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 14 18:23:06 2025

@author: knoukpoa
"""



import json
import math
import pickle
import os
import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from types import SimpleNamespace
from tkinter import (ttk, messagebox, filedialog, colorchooser, simpledialog, Canvas, Frame, Label, Entry,
                     Spinbox, Checkbutton, Scale, PhotoImage, StringVar,
                     BooleanVar, DoubleVar, BOTH, BOTTOM, END, FLAT,
                     GROOVE, LEFT, YES)
from tkmacosx import Button
import numpy as np
import pandas as pd      # lecture des fichiers Excel : requiert openpyxl (xlsx) ou xlrd (xls)
from matplotlib.figure import Figure                                         # graphiques (bouton « Plots »)
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection


def tracer_trajectoires_groupees (ax, segments_par_groupe, couleurs, alpha_ligne = 0.25, epaisseur = 0.8,
                                  alpha_points = 0.4, taille_points = 2.2, points_creux = False):
    """ Trajectoires individuelles tracees rapidement : pour chaque groupe, UNE
    collection de lignes (toutes ses trajectoires) et UNE serie de points, au
    lieu de deux objets par sujet (affichage, zoom et survol bien plus fluides).
    segments_par_groupe : groupe -> liste de tableaux (n_i x 2) ; renvoie
    groupe -> [objets traces] (legende interactive). """
    objets = {}
    for g, segments in segments_par_groupe.items():
        segments = [s for s in segments if len(s)]
        if not segments:
            objets[g] = []
            continue
        c = couleurs[g]
        lignes = LineCollection(segments, colors = c, alpha = alpha_ligne, linewidths = epaisseur)
        ax.add_collection(lignes)
        points = np.concatenate(segments)
        if points_creux:
            serie, = ax.plot(points[:, 0], points[:, 1], linestyle = "none", marker = "o", markersize = taille_points,
                             markerfacecolor = "white", markeredgecolor = c, markeredgewidth = epaisseur)
        else:
            serie, = ax.plot(points[:, 0], points[:, 1], linestyle = "none", marker = "o", markersize = taille_points,
                             color = c, alpha = alpha_points)
        objets[g] = [lignes, serie]
    return objets


def mise_en_page (figure, toile):
    """ Mise en page (constrained layout) calculee une seule fois, puis figee :
    les redessins suivants (zoom, deplacement, survol, legende interactive) ne
    la recalculent plus. A rappeler quand la taille ou les polices changent. """
    try:
        figure.set_layout_engine("constrained")
    except Exception:
        try:
            figure.set_constrained_layout(True)
        except Exception:
            pass
    toile.draw()
    try:
        figure.set_layout_engine("none")
    except Exception:
        try:
            figure.set_constrained_layout(False)
        except Exception:
            pass


##=============================================================================
##  InfoMergeCluster : classification de donnees longitudinales eparses
##  avec selection automatique du nombre de classes.
##  Traduction Python du code R « Code_InfoMerge.R » (infomergecluster,
##  predict.infomerge, fitted_curves, plot.infomerge, infomerge_stability et
##  toutes leurs dependances internes .im_*), integree au fichier de
##  l'application.
##  Modele : y_i | z_i = k ~ N(B_i beta_k + X_i gamma_k, Z_i G Z_i' + s2 I).
##  - standardize = True (defaut) : standardisation Min-Max du temps, de la
##    reponse et des covariables avant l'analyse ; resultats renvoyes a
##    l'echelle de depart (.im_unscale) ;
##  - covariables non centrees : facteurs (texte, booleens, categories) codes
##    en indicatrices, modalite de reference = la plus frequente (en nombre de
##    sujets distincts, puis de mesures, puis ordre des niveaux) ; beta_k est
##    la trajectoire du cluster pour des covariables nulles ;
##  - predict / plot : courbe du cluster k evaluee par defaut aux moyennes des
##    covariables dans ce cluster (covariates = "cluster"), ou sur la
##    population ("population"), a covariables nulles ("zero") ou a des
##    valeurs imposees ; enveloppe de confiance (l'enveloppe de prediction du
##    code R n'est pas reprise).
##  Differences avec R : k-means de Lloyd (initialisation k-means++) au lieu
##  de Hartigan-Wong ; messages transmis a la fonction log ; noms des
##  covariables passes par cov_labels (au lieu de z1, ..., z<n_cov>).
##=============================================================================

# =========================================================================== #
#  Fonction principale                                                        #
# =========================================================================== #

def infomergecluster (data, K_max = 8, K = None, df = 15, degree = 3, penalty = True, pen_order = 2,
                      re = "linear", n_cov = 0, weights = "constant", min_size = 2, K0 = None,
                      criterion = "BIC", a_dir = 0.5, n_outer = 3, quick_cycles = 4, full_cycles = 15,
                      inner_cap = 3, tol = 1e-5, nstart = 5, seed = None, keep_data = True,
                      verbose = True, log = print, cov_labels = None, standardize = True):
    """ infomergecluster() : voir l'en-tete du module et la documentation R.
    data : DataFrame long (colonnes par position : 1re = identifiant,
           avant-derniere = temps, derniere = reponse ; avec n_cov > 0 :
           1re = identifiant, 2e = temps, 3e = reponse, 4e a 3 + n_cov =
           covariables) ou liste de tableaux (un par sujet : avant-derniere
           colonne = temps, derniere = reponse ; avec n_cov > 0 : 1re = temps,
           2e = reponse, puis les covariables).
    cov_labels : noms des covariables (ajout de la version Python ; par
           defaut z1, ..., z<n_cov> comme en R).
    standardize : True (defaut) : standardisation Min-Max du temps, de la
           reponse et des covariables avant l'analyse ; les resultats sont
           renvoyes a l'echelle de depart.
    Renvoie un objet (SimpleNamespace) aux memes champs que la liste R. """
    if re not in ("linear", "intercept", "spline"):
        raise ValueError("'re' must be \"linear\", \"intercept\" or \"spline\".")
    if weights not in ("constant", "covariates"):
        raise ValueError("'weights' must be \"constant\" or \"covariates\".")
    if criterion not in ("BIC", "ICL"):
        raise ValueError("'criterion' must be \"BIC\" or \"ICL\".")
    t_start = time.time()
    if not isinstance(n_cov, (int, np.integer)) or n_cov < 0:
        raise ValueError("'n_cov' must be an integer >= 0.")
    n_cov = int(n_cov)
    message = log if verbose else (lambda *args: None)

    d = _as_long(data, n_cov, cov_labels)
    zn = list(cov_labels) if cov_labels is not None else ["z%d" % (j + 1) for j in range(n_cov)]
    cov_raw = d[zn] if n_cov > 0 else None
    d = d[["id", "t", "y"]].copy()
    n_raw = len(d)
    ok = d.notna().all(axis = 1).to_numpy().copy()
    if cov_raw is not None:
        ok = ok & cov_raw.notna().all(axis = 1).to_numpy()
    d = d[ok]
    if len(d) < n_raw:
        message("%d incomplete or non-numeric measurement(s) ignored." % (n_raw - len(d)))
    d = d.reset_index(drop = True)
    cov = _im_covariate_design(cov_raw, ok, standardize, ids = d["id"].to_numpy(), message = message)
    if weights == "covariates" and len(cov["names"]) == 0:
        raise ValueError("weights = \"covariates\" requires n_cov > 0.")
    if cov["names"]:
        d = pd.concat([d, cov["X"].reset_index(drop = True)], axis = 1)
    d = d.sort_values(["id", "t"], kind = "mergesort").reset_index(drop = True)
    N_subj = d["id"].nunique()
    if N_subj < 10:
        raise ValueError("Too few subjects (N < 10).")
    if K is not None:
        if int(K) != K or K < 1:
            raise ValueError("'K' must be None or an integer >= 1.")
        K = int(K)
        if K > N_subj // 2:
            raise ValueError("'K' = %d is too large for N = %d subjects (K <= %d)." % (K, N_subj, N_subj // 2))

    ## standardisation Min-Max du temps et de la reponse (covariables : voir
    ## _im_covariate_design) ; facteurs conserves pour le retour a l'echelle
    sc = {"standardize": bool(standardize), "t_min": 0.0, "t_range": 1.0, "y_min": 0.0, "y_range": 1.0,
          "cov_min": cov["cmin"], "cov_range": cov["crange"]}
    if standardize:
        sc["t_min"] = float(d["t"].min())
        sc["t_range"] = float(d["t"].max()) - sc["t_min"]
        sc["y_min"] = float(d["y"].min())
        sc["y_range"] = float(d["y"].max()) - sc["y_min"]
        if sc["t_range"] <= 0:
            raise ValueError("Min-Max standardization impossible: the time is constant.")
        if sc["y_range"] <= 0:
            raise ValueError("Min-Max standardization impossible: the response is constant.")
        d["t"] = (d["t"].astype(float) - sc["t_min"]) / sc["t_range"]
        d["y"] = (d["y"].astype(float) - sc["y_min"]) / sc["y_range"]
        message("Data standardized (Min-Max); results returned on the original scale.")

    rng = np.random.default_rng(seed)
    message("--- random effect: %s" % re)
    out = _fit_one(d, re, K_max = K_max, K_fixed = K, df = df, degree = degree, penalty = penalty,
                   pen_order = pen_order, cov_names = cov["names"],
                   weights = weights, min_size = min_size, K0 = K0, criterion = criterion, a_dir = a_dir,
                   n_outer = n_outer, quick_cycles = quick_cycles, full_cycles = full_cycles,
                   inner_cap = inner_cap, tol = tol, nstart = nstart, rng = rng, message = message)
    ## retour a l'echelle de depart (parametres et donnees)
    out = _im_unscale(out, sc)
    out.time_sec = time.time() - t_start
    du = _im_unscale_data(d, sc, cov["names"])
    ## moyennes des covariables (echelle d'origine) pour les courbes moyennes
    ## « melange » de predict() et plot()
    if out.covariates is not None:
        out.covariates["reference"] = dict(cov["reference"])
    out.cov_means = _im_cov_means(du, cov["names"], out.ids, out.posterior) if cov["names"] else None
    out.data = du if keep_data else None
    return out


def _im_unscale_data (d, sc, cov_names):
    """ .im_unscale_data : donnees a l'echelle de depart (temps et reponse
    d'origine, covariables non centrees sur leur echelle d'origine). """
    d = d.copy()
    d["t"] = sc["t_min"] + sc["t_range"] * d["t"].astype(float)
    d["y"] = sc["y_min"] + sc["y_range"] * d["y"].astype(float)
    for j, c in enumerate(cov_names):
        d[c] = sc["cov_min"][j] + sc["cov_range"][j] * d[c].astype(float)
    return d


def _im_unscale (out, sc):
    """ .im_unscale : parametres estimes ramenes a l'echelle de depart. Sur
    l'echelle standardisee x' = (x - cmin) / rx :
      B beta' by + ay + by x' gamma' = B [ay + by beta' - cmin' gamma] + x gamma,
      gamma = by gamma' / rx  (partition de l'unite des B-splines). """
    at, bt, ay, by = sc["t_min"], sc["t_range"], sc["y_min"], sc["y_range"]
    ## base B-spline : transformation affine des noeuds et des bornes
    b = dict(out.basis)
    b["knots"] = at + bt * np.asarray(b["knots"], dtype = float)
    b["lo"], b["hi"] = at + bt * b["lo"], at + bt * b["hi"]
    out.basis = b
    ## trajectoires moyennes
    beta = ay + by * out.beta.to_numpy(dtype = float)
    p0 = beta.shape[0]
    J = np.eye(p0) * by                                     # (beta', gamma') -> (beta, gamma), pour Vbeta
    if out.gamma is not None:
        rx = np.asarray(sc["cov_range"], dtype = float)
        cm = np.asarray(sc["cov_min"], dtype = float)
        r = out.gamma.shape[0]
        gamma = out.gamma.to_numpy(dtype = float) * (by / rx)[:, None]
        beta = beta - (gamma * cm[:, None]).sum(axis = 0)[None, :]
        out.gamma = pd.DataFrame(gamma, index = out.gamma.index, columns = out.gamma.columns)
        J = np.block([[J, -np.tile(cm * by / rx, (p0, 1))], [np.zeros((r, p0)), np.diag(by / rx)]])
    out.beta = pd.DataFrame(beta, index = out.beta.index, columns = out.beta.columns)
    if out.alpha is not None and out.alpha.shape[0] > 1:
        a = out.alpha.to_numpy(dtype = float).copy()
        a[1:] = a[1:] / np.asarray(sc["cov_range"], dtype = float)[:, None]
        a[0] = a[0] - (a[1:] * np.asarray(sc["cov_min"], dtype = float)[:, None]).sum(axis = 0)
        out.alpha = pd.DataFrame(a, index = out.alpha.index, columns = out.alpha.columns)
    out.Vbeta = {k: J @ V @ J.T for k, V in out.Vbeta.items()}
    ## structure de variance et lissage
    out.G = by ** 2 * out.G
    out.sigma2 = by ** 2 * out.sigma2
    out.lam = out.lam / by ** 2
    setattr(out, "lambda", out.lam)
    out.var_y = by ** 2 * out.var_y
    ## lois a priori et variogramme
    pr = dict(out.prior)
    for cle in ("Psi0", "b_sigma", "nugget", "g_mode"):
        pr[cle] = by ** 2 * pr[cle]
    out.prior = pr
    vario = dict(out.variogram)
    vario["nugget"], vario["sill"], vario["lag_max"] = by ** 2 * vario["nugget"], by ** 2 * vario["sill"], bt * vario["lag_max"]
    out.variogram = vario
    out.log_prior = _log_prior(out.G, out.sigma2, pr)
    ## log-vraisemblance et criteres : jacobien de y -> (y - min) / etendue
    jac = out.n_obs * math.log(by)
    out.loglik = out.loglik - jac
    tab = out.table.copy()
    tab["loglik"] = tab["loglik"] - jac
    tab["BIC"] = tab["BIC"] + 2 * jac
    tab["ICL"] = tab["ICL"] + 2 * jac
    out.table = tab
    out.scaling = sc
    return out


def _num (v):
    """ .im_num : conversion numerique (valeurs non numeriques -> NaN). """
    return pd.to_numeric(pd.Series(v).astype("object").map(lambda x: x.strip().replace(",", ".") if isinstance(x, str) else x),
                         errors = "coerce").to_numpy(dtype = float)


def _as_long (data, n_cov = 0, cov_labels = None):
    """ .im_as_long : conversion au format long interne (id, t, y, z1..). """
    zn = list(cov_labels) if cov_labels is not None else ["z%d" % (j + 1) for j in range(n_cov)]
    if len(zn) != n_cov or len(set(zn)) != n_cov or set(zn) & {"id", "t", "y"}:
        raise ValueError("'cov_labels' must contain n_cov distinct names, other than id, t and y.")
    if isinstance(data, (pd.DataFrame, np.ndarray)):
        data = pd.DataFrame(data)
        nc = data.shape[1]
        if nc < 3:
            raise ValueError("A long data frame must have at least 3 columns: identifier (1st), "
                             "time (second-to-last) and response (last).")
        ident = data.iloc[:, 0].to_numpy()
        if n_cov > 0:
            if nc < 3 + n_cov:
                raise ValueError("With n_cov = %d, a long data frame must have at least %d columns: "
                                 "identifier, time, response and the covariates." % (n_cov, 3 + n_cov))
            out = pd.DataFrame({"id": ident, "t": _num(data.iloc[:, 1]), "y": _num(data.iloc[:, 2])})
            for j, z in enumerate(zn):
                out[z] = data.iloc[:, 3 + j].to_numpy()
            return out
        return pd.DataFrame({"id": ident, "t": _num(data.iloc[:, nc - 2]), "y": _num(data.iloc[:, nc - 1])})
    if isinstance(data, (list, tuple, dict)):
        elements = list(data.values()) if isinstance(data, dict) else list(data)
        noms = list(data.keys()) if isinstance(data, dict) else None
        if len(elements) == 0:
            raise ValueError("The list 'data' is empty.")
        ids = noms if noms and len(set(noms)) == len(noms) else list(range(1, len(elements) + 1))
        parts = []
        for i, e in enumerate(elements):
            e = pd.DataFrame(e)
            nc = e.shape[1]
            if nc < 2:
                raise ValueError("Element %d must have at least 2 columns: time (second-to-last) and response (last)." % (i + 1))
            if len(e) == 0:
                continue
            if n_cov > 0:
                if nc < 2 + n_cov:
                    raise ValueError("With n_cov = %d, element %d must have at least %d columns." % (n_cov, i + 1, 2 + n_cov))
                o = pd.DataFrame({"id": ids[i], "t": _num(e.iloc[:, 0]), "y": _num(e.iloc[:, 1])})
                for j, z in enumerate(zn):
                    o[z] = e.iloc[:, 2 + j].to_numpy()
            else:
                o = pd.DataFrame({"id": ids[i], "t": _num(e.iloc[:, nc - 2]), "y": _num(e.iloc[:, nc - 1])})
            parts.append(o)
        if not parts:
            raise ValueError("No measurements in 'data'.")
        return pd.concat(parts, ignore_index = True)
    raise ValueError("'data' must be a data frame or a list of data frames / matrices.")


def _niveau_facteur (v):
    """ Libelle d'une modalite d'un facteur (comme as.character / factor de R :
    TRUE / FALSE pour les booleens, entiers sans decimale). """
    if isinstance(v, (bool, np.bool_)):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def _est_facteur (serie):
    """ Colonne traitee comme facteur (R : character, logical ou factor) :
    texte, booleens, categories ; une colonne « object » ne contenant que des
    nombres reste numerique. """
    if pd.api.types.is_bool_dtype(serie) or isinstance(serie.dtype, pd.CategoricalDtype):
        return True
    if pd.api.types.is_numeric_dtype(serie):
        return False
    valeurs = serie.dropna()
    return not all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))
                   for v in valeurs)


def _im_covariate_design (cov_raw, ok, standardize = False, ids = None, message = None):
    """ .im_covariate_design : design numerique des covariables sur les lignes
    gardees, sans centrage.
    - facteurs (texte, booleens, categories) : indicatrices (model.matrix), la
      modalite de reference (sans indicatrice) etant la plus frequente, en
      nombre de sujets distincts ayant la modalite (egalite : nombre de
      mesures, puis ordre des niveaux) ; facteurs a une seule modalite retires ;
    - colonnes sans variation retirees ;
    - standardize = True : chaque colonne ramenee a [0, 1] (Min-Max) ; cmin et
      crange servent au retour a l'echelle de depart.
    ids : identifiants des sujets sur les lignes gardees. """
    message = message or (lambda *args: None)
    vide = {"X": None, "names": [], "cmin": np.zeros(0), "crange": np.zeros(0), "reference": {}}
    if cov_raw is None:
        return vide
    cv = cov_raw[ok].reset_index(drop = True).copy()
    ids = None if ids is None else pd.Series(np.asarray(ids)).astype(str).reset_index(drop = True)
    facteurs = {}
    for c in cv.columns:
        if _est_facteur(cv[c]):
            texte = cv[c].map(_niveau_facteur)
            facteurs[c] = sorted(texte.unique())             # niveaux presents (droplevels)
            cv[c] = texte
        else:
            cv[c] = pd.to_numeric(cv[c], errors = "coerce").astype(float)
    ## facteurs a une seule modalite : retires
    une = [c for c in facteurs if len(facteurs[c]) < 2]
    if une:
        message("Warning: qualitative covariate(s) with a single modality removed: " + ", ".join(map(str, une)))
        cv = cv.drop(columns = une)
        for c in une:
            del facteurs[c]
    if cv.shape[1] == 0:
        return vide
    ## modalite de reference = la plus frequente ; indicatrices des autres modalites
    reference, colonnes, noms = {}, [], []
    for c in cv.columns:
        if c in facteurs:
            niveaux = facteurs[c]
            n_mes = cv[c].value_counts()
            if ids is not None:
                n_sub = pd.DataFrame({"id": ids, "v": cv[c]}).drop_duplicates()["v"].value_counts()
            else:
                n_sub = n_mes
            ordre = sorted(range(len(niveaux)), key = lambda j: (-int(n_sub.get(niveaux[j], 0)),
                                                                  -int(n_mes.get(niveaux[j], 0)), j))
            ref = niveaux[ordre[0]]
            reference[str(c)] = ref
            for n in niveaux:
                if n != ref:
                    colonnes.append((cv[c] == n).astype(float).to_numpy())
                    noms.append(str(c) + n)
        else:
            colonnes.append(cv[c].to_numpy(dtype = float))
            noms.append(str(c))
    ## noms uniques (make.unique de R)
    vus, uniques = {}, []
    for n in noms:
        if n in vus:
            vus[n] += 1
            uniques.append("%s.%d" % (n, vus[n]))
        else:
            vus[n] = 0
            uniques.append(n)
    X = pd.DataFrame(np.column_stack(colonnes), columns = uniques)
    garder = [c for c in X.columns if X[c].var(ddof = 1) > 0]
    retirees = [c for c in X.columns if c not in garder]
    if retirees:
        message("Warning: covariate column(s) without variation removed: " + ", ".join(retirees))
    X = X[garder]
    if X.shape[1] == 0:
        return dict(vide, reference = reference)
    cmin = np.zeros(X.shape[1])
    crange = np.ones(X.shape[1])
    if standardize:
        cmin = X.min(axis = 0).to_numpy(dtype = float)
        crange = X.max(axis = 0).to_numpy(dtype = float) - cmin
        X = (X - cmin) / crange
    noms = ["cov_" + c for c in X.columns]
    X.columns = noms
    return {"X": X, "names": noms, "cmin": cmin, "crange": crange, "reference": reference}


# =========================================================================== #
#  Ajustement complet pour une structure d'effet aleatoire                    #
# =========================================================================== #

def _fit_one (d, re, K_max, K_fixed, df, degree, penalty, pen_order, cov_names, weights,
              min_size, K0, criterion, a_dir, n_outer, quick_cycles, full_cycles, inner_cap, tol,
              nstart, rng, message):
    ids = pd.unique(d["id"])
    idx = pd.Index(ids).get_indexer(d["id"])              # 0..N-1, sujets tries
    N = len(ids)
    t = d["t"].to_numpy(dtype = float)
    y = d["y"].to_numpy(dtype = float)

    basis = _make_basis(t, df, degree)
    B = _basis_eval(basis, t)
    Zm = _Z(basis, re, t, B)
    p0 = B.shape[1]                                        # partie spline
    r = len(cov_names)                                     # covariables
    if r > 0:
        B = np.hstack([B, d[cov_names].to_numpy(dtype = float)])   # design augmente [B | X]
    p = B.shape[1]
    q = Zm.shape[1]
    n_i = np.bincount(idx, minlength = N)
    Wc = None
    if weights == "covariates":
        Xs = np.zeros((N, r))
        np.add.at(Xs, idx, d[cov_names].to_numpy(dtype = float))
        Wc = np.hstack([np.ones((N, 1)), Xs / n_i[:, None]])

    S = _design_stats(B, Zm, y, idx, N)
    S.groups = _groups(B, Zm, y, idx, N)
    S.p, S.q, S.N = p, q, N

    if K_fixed is not None:
        K_max = int(K_fixed)
    if K0 is None:
        K0 = min(100, max(3 * K_max, math.ceil(2 * math.sqrt(N))))
    K0 = int(min(K0, N // 3))
    if K_fixed is not None:
        K0 = max(K0, K_max)
    K_max = int(min(K_max, K0))

    vy = float(np.var(y, ddof = 1))
    P = np.zeros((p, p))                                   # penalite diag(P_spline, 0)
    if penalty:
        P[:p0, :p0] = _penalty_matrix(basis, pen_order)
        rk = p0 - pen_order
    else:
        rk = 0
    Qtot = S.Q.sum(axis = 0)
    beta0 = np.linalg.solve(Qtot + np.eye(p) * 1e-8 * np.mean(np.diag(Qtot)), S.cc.sum(axis = 0))
    r0 = y - B @ beta0
    vario = _variogram(idx, t, r0)
    pr = _prior(q, vy, vario, Zm)
    ## aucun plancher sur s2 : les lois a priori garantissent s2 > 0 ;
    ## seul le garde-fou numerique sur les valeurs propres de G est conserve
    floors = {"G": 1e-8 * vy}
    message("  variogram: nugget = %.4g, sill = %.4g (%d pairs%s)"
            % (pr["nugget"], vario["sill"], vario["n_pairs"],
               "" if pr["nugget_source"] == "variogram" else "; nugget: " + pr["nugget_source"]))
    ctrl = SimpleNamespace(inner_cap = inner_cap, tol = tol, floors = floors, P = P, rk = rk,
                           penalty = penalty, prior = pr, Wc = Wc)

    def score (f):
        tb = _criteria_table([f], q, N, penalty)
        return tb["BIC"].iloc[0] if criterion == "BIC" else tb["ICL"].iloc[0]

    message("InfoMergeCluster: N = %d subjects, %d measurements, p = %d, q = %d, K0 = %d" % (N, len(d), p, q, K0))

    v_res = max(np.mean(r0 ** 2), 1e-8 * vy)
    fits = [None] * (K_max + 1)                            # indices 1..K_max
    lam0 = (1e-3 * np.mean(np.diag(Qtot)[:p0]) / (v_res * np.mean(np.diag(P)[:p0]))) if penalty else 0.0
    fits[1] = _em(S, 1, np.ones((N, 1)), np.eye(q) * v_res / 2, v_res / 2, lam0, full_cycles, ctrl)
    G, s2, lam = fits[1].G, fits[1].s2, fits[1].lam

    def pick (tab):
        ## which.min de R : valeurs manquantes ou non finies ignorees (np.argmin
        ## renverrait la position d'un NaN, d'ou un K sans rapport avec le critere)
        crit = (tab["BIC"] if criterion == "BIC" else tab["ICL"]).to_numpy(dtype = float)
        crit = np.where(np.isfinite(crit), crit, np.inf)
        return int(tab["K"].iloc[int(np.argmin(crit))])

    def valid (f):
        return bool(np.all(f.pi * N >= min_size)) and np.isfinite(f.ll)

    def try_fit (Kk, tau0, G0, s20, lam_, cycles):
        f = _em(S, Kk, tau0, G0, s20, lam_, cycles, ctrl)
        if valid(f):
            return f
        keep = f.pi * N >= min_size
        if keep.sum() < 1:
            return None
        tau = f.tau[:, keep]
        tau = tau / tau.sum(axis = 1, keepdims = True)
        f2 = _em(S, int(keep.sum()), tau, f.G, f.s2, f.lam, cycles, ctrl)
        return f2 if valid(f2) else None

    def store (f):
        if f is None:
            return
        k = f.K
        if fits[k] is None or not np.isfinite(score(fits[k])) or score(f) < score(fits[k]):
            fits[k] = f

    K_prev = None
    tree = None
    outer_log = []

    if K_fixed is not None:
        ## K impose : partition initiale par l'arbre, puis un EM (pas de selection de K)
        K_hat = K_max
        if K_hat >= 2:
            tree = _tree(S, G, s2, lam, K0, K_hat, a_dir, nstart, floors, ctrl, rng)
            lab = tree.parts[K_hat]
            if lab is None:
                lab = rng.permutation(np.resize(np.arange(1, K_hat + 1), N))
            fits[K_hat] = _em(S, K_hat, _onehot(lab, K_hat, 0.01), tree.G_within, tree.s2_within, lam, full_cycles, ctrl)
            petites = fits[K_hat].pi * N < min_size
            if petites.any():
                message("Warning: imposed K = %d: %d cluster(s) with posterior size < min_size = %g."
                        % (K_hat, int(petites.sum()), min_size))
        message("  clustering with K = %d (imposed)" % K_hat)
        tab = _criteria_table(fits, q, N, penalty)
    else:
        for o in range(1, n_outer + 1):
            tree = _tree(S, G, s2, lam, K0, K_max, a_dir, nstart, floors, ctrl, rng)
            G_start = tree.G_within if o == 1 else G
            s2_start = tree.s2_within if o == 1 else s2
            for Kk in range(2, K_max + 1):
                lab = tree.parts[Kk]
                if lab is None:
                    continue
                store(try_fit(Kk, _onehot(lab, Kk, 0.01), G_start, s2_start, lam, quick_cycles))
            K_hat = pick(_criteria_table(fits, q, N, penalty))
            for Kk in sorted(set(min(max(K_hat + j, 1), K_max) for j in (-1, 0, 1))):
                if fits[Kk] is None:
                    continue
                store(try_fit(Kk, fits[Kk].tau, fits[Kk].G, fits[Kk].s2, fits[Kk].lam, full_cycles))
            tab = _criteria_table(fits, q, N, penalty)
            K_hat = pick(tab)
            outer_log.append({"iteration": o, "K_hat": K_hat, "K_tree": tree.K_tree})
            message("  outer iteration %d: K (%s) = %d   [tree K = %d]" % (o, criterion, K_hat, tree.K_tree))
            if K_prev is not None and K_hat == K_prev:
                break
            K_prev = K_hat
            G, s2, lam = fits[K_hat].G, fits[K_hat].s2, fits[K_hat].lam

    best = fits[K_hat]
    ordre = np.argsort(-best.pi, kind = "stable")
    labs = ["C%d" % (k + 1) for k in range(K_hat)]
    beta = best.beta[:p0, ordre]
    gamma = None
    if r > 0:
        gamma = pd.DataFrame(best.beta[p0:p0 + r, ordre], index = [c[4:] for c in cov_names], columns = labs)
    alpha = None
    if best.alpha is not None:
        a = best.alpha[:, ordre]
        a = a - a[:, [0]]                                   # reference : classe C1
        alpha = pd.DataFrame(a, index = ["(Intercept)"] + [c[4:] for c in cov_names], columns = labs)
    tau = best.tau[:, ordre]
    posterior = pd.DataFrame(tau, index = [str(i) for i in ids], columns = labs)
    cluster = pd.Series(np.argmax(tau, axis = 1) + 1, index = [str(i) for i in ids])

    return SimpleNamespace(
        K = K_hat, K_fixed = K_fixed is not None, re = re, criterion = criterion,
        cluster = cluster, posterior = posterior, pi = pd.Series(best.pi[ordre], index = labs),
        beta = pd.DataFrame(beta, columns = labs), gamma = gamma, alpha = alpha, weights = weights,
        covariates = {"names": cov_names} if r > 0 else None,
        Vbeta = {labs[j]: best.Vbeta[k] for j, k in enumerate(ordre)},
        G = best.G, sigma2 = best.s2, **{"lambda": best.lam}, lam = best.lam, edf = best.edf,
        loglik = best.ll, log_prior = best.log_prior, prior = pr, variogram = vario, table = tab,
        K_tree = tree.K_tree if tree is not None else None,
        icl_path = tree.icl_path if tree is not None else None,
        outer = pd.DataFrame(outer_log) if outer_log else None,
        basis = basis, fits = fits, N = N, n_obs = len(d), var_y = vy, ids = [str(i) for i in ids])


# =========================================================================== #
#  Lois a priori sur la structure de variance                                 #
# =========================================================================== #

def _variogram (idx, t, r, lag_prob = 0.25, min_pairs = 10):
    """ .im_variogram : variogramme empirique intra-sujet des residus. """
    sill = float(np.var(r, ddof = 1))
    ordre = np.argsort(idx, kind = "stable")
    frontieres = np.flatnonzero(np.diff(idx[ordre])) + 1
    us, vs = [], []
    for ix in np.split(ordre, frontieres):
        if len(ix) < 2:
            continue
        a, b = np.triu_indices(len(ix), 1)                 # paires j < k (ordre de combn)
        a, b = ix[a], ix[b]
        us.append(np.abs(t[a] - t[b]))
        vs.append(0.5 * (r[a] - r[b]) ** 2)
    if not us:
        return {"nugget": np.nan, "sill": sill, "n_pairs": 0, "lag_max": np.nan}
    u, v = np.concatenate(us), np.concatenate(vs)
    n_pairs = len(u)
    if n_pairs < min_pairs:
        return {"nugget": np.nan, "sill": sill, "n_pairs": n_pairs, "lag_max": np.nan}
    u_max = np.quantile(u, lag_prob)
    sel = np.flatnonzero(u <= u_max)
    if len(sel) < min_pairs:
        sel = np.argsort(u, kind = "stable")[:min_pairs]
    nug = np.nan
    if len(np.unique(u[sel])) >= 2:
        X = np.column_stack([np.ones(len(sel)), u[sel]])
        nug = np.linalg.lstsq(X, v[sel], rcond = None)[0][0]
    if not np.isfinite(nug) or nug <= 0:
        nug = float(np.mean(v[sel]))
    return {"nugget": float(min(nug, sill)), "sill": sill, "n_pairs": n_pairs, "lag_max": float(np.max(u[sel]))}


def _prior (q, vy, vario, Zm):
    """ .im_prior : hyperparametres calibres sur le variogramme. """
    g_share, nu0, a = 0.5, q, 1
    if np.isfinite(vario["nugget"]):
        nugget, src = vario["nugget"], "variogram"
    else:
        nugget, src = 0.05 * vario["sill"], "fallback 5% of the sill (too few within-subject pairs)"
    nugget = max(nugget, 1e-8 * vy)
    proc = max(vario["sill"] - nugget, 1e-8 * vy)
    g_mode = g_share * proc / np.mean(np.sum(Zm ** 2, axis = 1))
    Psi0 = np.eye(q) * (nu0 + q + 1) * g_mode
    b = (a + 1) * nugget
    return {"nu0": nu0, "Psi0": Psi0, "a_sigma": a, "b_sigma": b, "q": q, "nugget": nugget,
            "nugget_source": src, "g_mode": g_mode, "g_share": g_share}


def _log_prior (G, s2, pr):
    """ .im_log_prior : log p0(G, s2) a une constante pres. """
    q = G.shape[0]
    return (-0.5 * (pr["nu0"] + q + 1) * _logdet(G) - 0.5 * np.sum(pr["Psi0"] * _inv(G))
            - (pr["a_sigma"] + 1) * math.log(s2) - pr["b_sigma"] / s2)


# =========================================================================== #
#  Bases et statistiques du design                                            #
# =========================================================================== #

def _make_basis (t, df, degree):
    """ .im_make_basis : noeuds interieurs aux quantiles des temps. """
    ord_ = degree + 1
    n_int = df - ord_
    if n_int < 0:
        raise ValueError("'df' must be >= degree + 1.")
    lo, hi = float(np.min(t)), float(np.max(t))
    interieur = np.array([])
    if n_int > 0:
        pr = np.linspace(0, 1, n_int + 2)[1:-1]
        interieur = np.unique(np.quantile(t, pr))
        interieur = interieur[(interieur > lo) & (interieur < hi)]
    knots = np.concatenate([np.repeat(lo, ord_), interieur, np.repeat(hi, ord_)])
    return {"knots": knots, "ord": ord_, "lo": lo, "hi": hi, "p": len(knots) - ord_}


def _spline_design (knots, x, ord_, deriv = 0):
    """ splines::splineDesign : fonctions B-splines d'ordre ord_ (et leurs
    derivees d'ordre deriv) aux points x ; un point egal au dernier noeud est
    rattache au dernier intervalle non vide (continuite a droite). """
    x = np.asarray(x, dtype = float)
    if deriv > 0:
        Bl = _spline_design(knots, x, ord_ - 1, deriv - 1)
        n_f = len(knots) - ord_
        D = np.zeros((len(x), n_f))
        for i in range(n_f):
            d1 = knots[i + ord_ - 1] - knots[i]
            d2 = knots[i + ord_] - knots[i + 1]
            if d1 > 0:
                D[:, i] += (ord_ - 1) * Bl[:, i] / d1
            if d2 > 0:
                D[:, i] -= (ord_ - 1) * Bl[:, i + 1] / d2
        return D
    n0 = len(knots) - 1
    Bk = np.zeros((len(x), n0))
    for i in range(n0):
        if knots[i + 1] > knots[i]:
            Bk[:, i] = (x >= knots[i]) & (x < knots[i + 1])
    dernier = max(i for i in range(n0) if knots[i + 1] > knots[i])
    Bk[x == knots[-1], dernier] = 1.0
    for k in range(2, ord_ + 1):
        n_k = len(knots) - k
        nouveau = np.zeros((len(x), n_k))
        for i in range(n_k):
            d1 = knots[i + k - 1] - knots[i]
            d2 = knots[i + k] - knots[i + 1]
            if d1 > 0:
                nouveau[:, i] += (x - knots[i]) / d1 * Bk[:, i]
            if d2 > 0:
                nouveau[:, i] += (knots[i + k] - x) / d2 * Bk[:, i + 1]
        Bk = nouveau
    return Bk


def _basis_eval (basis, t):
    """ .im_basis_eval """
    t = np.clip(np.asarray(t, dtype = float), basis["lo"], basis["hi"])
    return _spline_design(basis["knots"], t, basis["ord"])


def _penalty_matrix (basis, m):
    """ .im_penalty_matrix : P_jl = int_0^1 B_j^(m) B_l^(m) du (quadrature de
    Gauss-Legendre exacte par intervalle), u = (t - lo) / (hi - lo). """
    m = int(m)
    if m < 1 or m > basis["ord"] - 1:
        raise ValueError("'pen_order' must satisfy 1 <= pen_order <= degree.")
    br = np.unique(basis["knots"])
    a, h = br[:-1], np.diff(br)
    gx, gw = np.polynomial.legendre.leggauss(basis["ord"] - m)
    x = (np.repeat(a + h / 2, len(gx)) + np.repeat(h / 2, len(gx)) * np.tile(gx, len(a)))
    w = np.repeat(h / 2, len(gx)) * np.tile(gw, len(a))
    Dm = _spline_design(basis["knots"], x, basis["ord"], m)
    Dw = Dm * np.sqrt(w)[:, None]
    P = (Dw.T @ Dw) * (basis["hi"] - basis["lo"]) ** (2 * m - 1)
    return (P + P.T) / 2


def _Z (basis, re, t, B = None):
    """ .im_Z : design de l'effet aleatoire. """
    if re == "spline":
        return _basis_eval(basis, t) if B is None else B
    if re == "intercept":
        return np.ones((len(t), 1))
    tt = (np.clip(t, basis["lo"], basis["hi"]) - basis["lo"]) / (basis["hi"] - basis["lo"]) - 0.5
    return np.column_stack([np.ones(len(t)), tt])


def _design_stats (B, Zm, y, idx, N):
    """ .im_design_stats : sommes par sujet ne dependant que du design. """
    def agg (M):
        out = np.zeros((N,) + M.shape[1:])
        np.add.at(out, idx, M)
        return out
    return SimpleNamespace(Q = agg(np.einsum("ij,ik->ijk", B, B)), BZ = agg(np.einsum("ij,ik->ijk", B, Zm)),
                           ZZ = agg(np.einsum("ij,ik->ijk", Zm, Zm)), cc = agg(B * y[:, None]),
                           Zy = agg(Zm * y[:, None]), yy = agg(y ** 2), n = np.bincount(idx, minlength = N))


def _groups (B, Zm, y, idx, N):
    """ .im_groups : sujets regroupes par nombre de mesures (calcul vectorise). """
    n = np.bincount(idx, minlength = N)
    debut = np.concatenate([[0], np.cumsum(n)[:-1]])
    groupes = []
    for nv in np.unique(n):
        I = np.flatnonzero(n == nv)
        lignes = debut[I][:, None] + np.arange(nv)[None, :]
        groupes.append(SimpleNamespace(n = int(nv), I = I, B = B[lignes], Z = Zm[lignes], y = y[lignes]))
    return groupes


# =========================================================================== #
#  Statistiques d'information suffisantes (Proposition 1)                     #
# =========================================================================== #

def _subject_stats (S, G, s2):
    """ .im_subject_stats : V_i = Z_i G Z_i' + s2 I ; A_i = B'V^-1 B,
    b_i = B'V^-1 y, Z'V^-1 B, Z'V^-1 Z, Z'V^-1 y et constante c0_i. """
    N, p, q = S.N, S.p, S.q
    A = np.zeros((N, p, p))
    b = np.zeros((N, p))
    ZVB = np.zeros((N, q, p))
    ZVZ = np.zeros((N, q, q))
    ZVy = np.zeros((N, q))
    c0 = np.zeros(N)
    for g in S.groups:
        V = np.einsum("mjq,qr,mlr->mjl", g.Z, G, g.Z) + s2 * np.eye(g.n)
        L = np.linalg.cholesky(V)
        X = np.concatenate([g.B, g.Z, g.y[:, :, None]], axis = 2)
        W = np.linalg.solve(L, X)                         # L^{-1} [B | Z | y]
        wb, wz, wy = W[:, :, :p], W[:, :, p:p + q], W[:, :, p + q]
        A[g.I] = np.einsum("mjp,mjr->mpr", wb, wb)
        ZVB[g.I] = np.einsum("mjq,mjp->mqp", wz, wb)
        ZVZ[g.I] = np.einsum("mjq,mjr->mqr", wz, wz)
        b[g.I] = np.einsum("mjp,mj->mp", wb, wy)
        ZVy[g.I] = np.einsum("mjq,mj->mq", wz, wy)
        ld = 2 * np.sum(np.log(np.diagonal(L, axis1 = 1, axis2 = 2)), axis = 1)
        c0[g.I] = -0.5 * (g.n * math.log(2 * math.pi) + ld + np.sum(wy ** 2, axis = 1))
    return SimpleNamespace(A = A, b = b, c0 = c0, ZVB = ZVB, ZVZ = ZVZ, ZVy = ZVy)


# =========================================================================== #
#  EM sur les statistiques suffisantes (Proposition 2)                        #
# =========================================================================== #

def _estep (st, beta, pik):
    """ .im_estep """
    lp = np.log(np.maximum(pik, 1e-300))
    L = (lp + st.c0[:, None] + st.b @ beta - 0.5 * np.einsum("ipr,pk,rk->ik", st.A, beta, beta))
    mx = L.max(axis = 1, keepdims = True)
    E = np.exp(L - mx)
    s = E.sum(axis = 1, keepdims = True)
    return E / s, float(np.sum(mx[:, 0] + np.log(s[:, 0])))


def _mstep_beta (st, tau, lam = 0.0, P = None):
    """ .im_mstep_beta : beta_k = H_k^{-1} sum_i tau_ik b_i,
    H_k = sum_i tau_ik A_i + ridge I + lambda P. """
    p = st.b.shape[1]
    K = tau.shape[1]
    AT = np.einsum("ipr,ik->kpr", st.A, tau)
    bT = st.b.T @ tau
    ridge = 1e-8 * max(np.mean(np.diag(st.A.mean(axis = 0))), 1e-12)
    beta = np.zeros((p, K))
    H = []
    for k in range(K):
        Hk = AT[k] + np.eye(p) * ridge
        if P is not None and lam > 0:
            Hk = Hk + lam * P
        H.append(Hk)
        beta[:, k] = np.linalg.solve(Hk, bT[:, k])
    return SimpleNamespace(beta = beta, pi = tau.mean(axis = 0), H = H, AT = AT)


def _mstep_pi (tau, W, ridge = 1e-4, iters = 25, tol = 1e-9):
    """ .im_mstep_pi : regression logistique multinomiale ponderee (classe 1 en
    reference), pas de Newton avec reduction de pas. """
    N, K = tau.shape
    dw = W.shape[1]
    A = np.zeros((dw, K))
    if K == 1:
        return np.zeros((dw, 1)), np.ones((N, 1))
    nk = tau.sum(axis = 0)
    A[0] = np.log(np.maximum(nk, 1e-10) / max(nk[0], 1e-10))
    A[0, 0] = 0.0

    def sm (A):
        E = W @ A
        E = E - E.max(axis = 1, keepdims = True)
        Pm = np.exp(E)
        return Pm / Pm.sum(axis = 1, keepdims = True)

    def obj (A):
        E = W @ A
        mx = E.max(axis = 1, keepdims = True)
        return (np.sum(tau * E) - np.sum(tau.sum(axis = 1) * (mx[:, 0] + np.log(np.exp(E - mx).sum(axis = 1))))
                - 0.5 * ridge * np.sum(A[1:, 1:] ** 2))

    Km = K - 1
    pen = np.tile(np.concatenate([[0.0], np.repeat(ridge, dw - 1)]), Km)
    f_old = obj(A)
    for _ in range(iters):
        Pm = sm(A)
        R = tau - Pm
        gA = W.T @ R[:, 1:]
        gA[1:] -= ridge * A[1:, 1:]
        H = np.zeros((dw * Km, dw * Km))
        for j in range(Km):
            for l in range(j, Km):
                wgt = Pm[:, j + 1] * ((j == l) - Pm[:, l + 1])
                blk = (W * wgt[:, None]).T @ W
                H[j * dw:(j + 1) * dw, l * dw:(l + 1) * dw] = blk
                H[l * dw:(l + 1) * dw, j * dw:(j + 1) * dw] = blk.T
        H += np.diag(pen + 1e-8)
        pas = np.linalg.solve(H, gA.T.reshape(-1)).reshape(Km, dw).T
        stp = 1.0
        while True:
            An = A.copy()
            An[:, 1:] = A[:, 1:] + stp * pas
            f_new = obj(An)
            if np.isfinite(f_new) and f_new >= f_old - 1e-12:
                break
            stp /= 2
            if stp < 1e-4:
                An, f_new = A, f_old
                break
        A = An
        fini = abs(f_new - f_old) < tol * (1 + abs(f_old))
        f_old = f_new
        if fini:
            break
    return A, sm(A)


def _weights (tau, ms, ctrl):
    """ .im_weights : vecteur pi_k ou matrice N x K pi_k(x_i). """
    return ms.pi[None, :] if ctrl.Wc is None else _mstep_pi(tau, ctrl.Wc)[1]


def _lam_update (beta, H, lam, P, rk):
    """ .im_lam_update (Fellner-Schall). """
    num = den = 0.0
    for k in range(beta.shape[1]):
        num += rk - lam * np.trace(np.linalg.solve(H[k], P))
        den += beta[:, k] @ P @ beta[:, k]
    return min(max(max(num, 1e-8) / max(den, 1e-300), 1e-8), 1e10)


def _mstep_cov (S, st, tau, beta, G, floors, prior):
    """ .im_mstep_cov : mode a posteriori de (G, s2). """
    q, N = S.q, S.N
    Mg = np.zeros((q, q))
    sse = 0.0
    for k in range(beta.shape[1]):
        sel = np.flatnonzero(tau[:, k] > 1e-12)
        if len(sel) == 0:
            continue
        tk = tau[sel, k]
        bk = beta[:, k]
        g = st.ZVy[sel] - st.ZVB[sel] @ bk                    # Z'V^-1 (y - B beta_k)
        Mg += (g * tk[:, None]).T @ g
        m = g @ G                                             # E[u_i] = G g_i
        res = (S.yy[sel] - 2 * S.cc[sel] @ bk - 2 * np.sum(S.Zy[sel] * m, axis = 1)
               + np.einsum("ipr,p,r->i", S.Q[sel], bk, bk)
               + 2 * np.sum(np.einsum("ipq,p->iq", S.BZ[sel], bk) * m, axis = 1)
               + np.einsum("iqr,iq,ir->i", S.ZZ[sel], m, m))
        sse += np.sum(tk * res)
    Euu = G @ Mg @ G + N * G - G @ st.ZVZ.sum(axis = 0) @ G
    trGZZ = np.einsum("iqr,qr->i", S.ZZ, G)
    trGZVZGZZ = np.einsum("iqr,iqr->i", G @ st.ZVZ @ G, S.ZZ)
    sse += np.sum(trGZZ - trGZVZGZZ)
    G_new = (Euu + prior["Psi0"]) / (N + prior["nu0"] + q + 1)
    s2_new = (sse + 2 * prior["b_sigma"]) / (np.sum(S.n) + 2 * prior["a_sigma"] + 2)
    return _psd_floor(G_new, floors["G"]), s2_new           # s2_new > 0 (loi a priori IG)


def _pack (G, s2, lam):
    """ .im_pack : parametrage (G, s2, lambda) pour l'extrapolation SQUAREM. """
    L = np.linalg.cholesky(G)
    return np.concatenate([L[np.tril_indices(G.shape[0])], [math.log(s2), math.log(max(lam, 1e-300))]])


def _unpack (th, q, floors, penalty):
    """ .im_unpack """
    L = np.zeros((q, q))
    L[np.tril_indices(q)] = th[:-2]
    lam = min(max(math.exp(min(th[-1], 700)), 1e-8), 1e10) if penalty else 0.0
    return L @ L.T + np.eye(q) * floors["G"], math.exp(min(th[-2], 700)), lam


def _Fmap (S, th, tau, ctrl):
    """ .im_Fmap : une application de la carte EM (G, s2, lambda) -> (G', s2', lambda'). """
    G, s2, lam = _unpack(th, S.q, ctrl.floors, ctrl.penalty)
    st = _subject_stats(S, G, s2)
    ms = _mstep_beta(st, tau, lam, ctrl.P)
    pw = _weights(tau, ms, ctrl)
    for it in range(ctrl.inner_cap):
        tau, ll = _estep(st, ms.beta, pw)
        if it < ctrl.inner_cap - 1:
            ms = _mstep_beta(st, tau, lam, ctrl.P)
            pw = _weights(tau, ms, ctrl)
    pen = lam_new = 0.0
    if ctrl.penalty:
        pen = 0.5 * lam * np.sum(ms.beta * (ctrl.P @ ms.beta))
        lam_new = _lam_update(ms.beta, ms.H, lam, ctrl.P, ctrl.rk)
    G_n, s2_n = _mstep_cov(S, st, tau, ms.beta, G, ctrl.floors, ctrl.prior)
    obj = ll - pen + _log_prior(G, s2, ctrl.prior)          # objectif penalise
    return _pack(G_n, s2_n, lam_new), obj, tau


def _em (S, K, tau, G, s2, lam, max_cycles, ctrl, max_iter = 500):
    """ .im_em : EM accelere par SQUAREM, puis polissage de (beta, pi). """
    th0 = _pack(G, s2, lam)
    ll_old = -np.inf
    n_eval = 0
    for _ in range(max_cycles):
        th1, ll1, tau1 = _Fmap(S, th0, tau, ctrl)
        th2, ll2, tau2 = _Fmap(S, th1, tau1, ctrl)
        r = th1 - th0
        v = th2 - th1 - r
        nv = math.sqrt(np.sum(v ** 2))
        alpha = -math.sqrt(np.sum(r ** 2)) / nv if nv > 0 else -1.0
        alpha = max(min(alpha, -1.0), -50.0)
        try:
            F3 = _Fmap(S, th0 - 2 * alpha * r + alpha ** 2 * v, tau2, ctrl)
        except (np.linalg.LinAlgError, ValueError, OverflowError, FloatingPointError):
            F3 = None
        n_eval += 3
        if F3 is not None and np.isfinite(F3[1]) and F3[1] >= ll2:
            th0, ll, tau = F3[0], F3[1], F3[2]
        else:
            th0, ll, tau = th2, ll2, tau2
        if abs(ll - ll_old) < ctrl.tol * abs(ll):
            break
        ll_old = ll
    G, s2, lam = _unpack(th0, S.q, ctrl.floors, ctrl.penalty)
    st = _subject_stats(S, G, s2)
    ms = _mstep_beta(st, tau, lam, ctrl.P)
    pw = _weights(tau, ms, ctrl)
    ll = -np.inf
    for _ in range(max_iter):
        tau, ll_n = _estep(st, ms.beta, pw)
        conv = abs(ll_n - ll) < 1e-9 * abs(ll_n)
        ll = ll_n
        if conv:
            break
        ms = _mstep_beta(st, tau, lam, ctrl.P)
        pw = _weights(tau, ms, ctrl)
    alpha = None if ctrl.Wc is None else _mstep_pi(tau, ctrl.Wc)[0]
    edf = float(sum(np.trace(np.linalg.solve(ms.H[k], ms.AT[k])) for k in range(K)))
    Vbeta = [_inv((H + H.T) / 2) for H in ms.H]
    return SimpleNamespace(K = K, beta = ms.beta, pi = tau.mean(axis = 0), G = G, s2 = s2, lam = lam, edf = edf,
                           tau = tau, ll = ll, log_prior = _log_prior(G, s2, ctrl.prior), alpha = alpha,
                           n_alpha = 0 if ctrl.Wc is None else (K - 1) * (ctrl.Wc.shape[1] - 1),
                           n_eval = n_eval, Vbeta = Vbeta)


# =========================================================================== #
#  InfoMergeCluster : arbre de fusions fonde sur l'ICL exacte                 #
# =========================================================================== #

def _kmeans (X, K, nstart, rng, iter_max = 100):
    """ k-means (Lloyd, initialisation k-means++), meilleur de nstart departs. """
    meilleur, inertie_min = None, np.inf
    for _ in range(max(1, nstart)):
        centres = [X[rng.integers(len(X))]]
        for _k in range(1, K):
            d2 = np.min(((X[:, None, :] - np.array(centres)[None, :, :]) ** 2).sum(axis = 2), axis = 1)
            centres.append(X[rng.choice(len(X), p = d2 / d2.sum())] if d2.sum() > 0 else X[rng.integers(len(X))])
        C = np.array(centres)
        lab = None
        for _it in range(iter_max):
            nouv = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(axis = 2), axis = 1)
            if lab is not None and np.array_equal(nouv, lab):
                break
            lab = nouv
            for k in range(K):
                if np.any(lab == k):
                    C[k] = X[lab == k].mean(axis = 0)
        inertie = np.sum((X - C[lab]) ** 2)
        if inertie < inertie_min:
            meilleur, inertie_min = lab, inertie
    return meilleur


def _tree (S, G, s2, lam, K0, K_max, a_dir, nstart, floors, ctrl, rng, G_iter = 5):
    """ .im_tree : estimations individuelles, sur-segmentation (k-means),
    covariance intra micro-classes, puis fusions gloutonnes selon l'ICL exacte. """
    N, p = S.N, S.p
    st = _subject_stats(S, G, s2)
    ## (a) estimations individuelles retrecies
    Pl = lam * ctrl.P
    Atot = st.A.sum(axis = 0)
    m0 = np.linalg.solve(Atot + Pl + np.eye(p) * 1e-10 * np.mean(np.diag(Atot)), st.b.sum(axis = 0))
    R0 = np.eye(p) * 0.1 * np.mean(np.diag(Atot)) / N + Pl
    r0 = R0 @ m0
    theta = np.linalg.solve(st.A + R0[None], (st.b + r0)[:, :, None])[:, :, 0]
    ## (b) sur-segmentation
    n_distinct = len(np.unique(np.round(theta, 10), axis = 0))
    K0 = max(2, min(K0, n_distinct - 1))
    cl = _kmeans(theta, K0, nstart, rng)
    _, cl = np.unique(cl, return_inverse = True)              # 0..K0-1
    K0 = int(cl.max()) + 1
    ## (c) covariance intra micro-classes
    tau_h = _onehot(cl + 1, K0, 0.0)
    Gw, s2w = G, s2
    fl_w = {"G": 1e-10 * np.mean(np.diag(G))}
    for _ in range(G_iter):
        stw = _subject_stats(S, Gw, s2w)
        bw = _mstep_beta(stw, tau_h, lam, ctrl.P).beta
        Gw, s2w = _mstep_cov(S, stw, tau_h, bw, Gw, fl_w, ctrl.prior)
    st = _subject_stats(S, Gw, s2w)
    ## (d) statistiques des micro-classes et a priori bayesien empirique
    AC = np.zeros((K0, p, p)); np.add.at(AC, cl, st.A)
    bC = np.zeros((K0, p)); np.add.at(bC, cl, st.b)
    nC = np.bincount(cl, minlength = K0).astype(float)
    Atot = st.A.sum(axis = 0)
    m0 = np.linalg.solve(Atot + Pl + np.eye(p) * 1e-10 * np.mean(np.diag(Atot)), st.b.sum(axis = 0))
    R0 = np.eye(p) * 0.1 * np.mean(np.diag(Atot)) / N + Pl
    r0 = R0 @ m0
    mu = np.array([np.linalg.solve(R0 + AC[k], bC[k] + r0) for k in range(K0)])
    wts = nC / nC.sum()
    m0 = (mu * wts[:, None]).sum(axis = 0)
    Dm = (mu - m0) * np.sqrt(wts)[:, None]
    Sm = Dm.T @ Dm
    T0 = Sm + np.eye(p) * (0.05 * np.mean(np.diag(Sm)) + 1e-12)
    T0inv = _inv(T0)
    T0m = T0inv @ m0
    ldT0 = _logdet(T0)
    mTm = m0 @ T0m

    def Lfun (Ak, bv):
        R = np.linalg.cholesky(T0inv + Ak)
        z = np.linalg.solve(R, bv + T0m)
        return -0.5 * (ldT0 + 2 * np.sum(np.log(np.diag(R)))) + 0.5 * np.sum(z ** 2) - 0.5 * mTm

    def icl_part (Kk, nv):
        return (math.lgamma(Kk * a_dir) - Kk * math.lgamma(a_dir) + sum(math.lgamma(x + a_dir) for x in nv)
                - math.lgamma(N + Kk * a_dir))

    Lc = np.array([Lfun(AC[k], bC[k]) for k in range(K0)])

    def dfun (k, l):
        return (Lfun(AC[k] + AC[l], bC[k] + bC[l]) - Lc[k] - Lc[l] + math.lgamma(nC[k] + nC[l] + a_dir)
                - math.lgamma(nC[k] + a_dir) - math.lgamma(nC[l] + a_dir))

    ## (e) fusions gloutonnes
    D = np.full((K0, K0), -np.inf)
    for k in range(K0 - 1):
        for l in range(k + 1, K0):
            D[k, l] = dfun(k, l)
    act = np.ones(K0, dtype = bool)
    grp = np.arange(K0)
    icl_path = np.full(K0 + 1, np.nan)                         # indices 1..K0
    parts = [None] * (K_max + 1)
    Kc = K0
    icl_path[Kc] = Lc.sum() + icl_part(Kc, nC)
    if Kc <= K_max:
        parts[Kc] = grp.copy()
    while Kc > 1:
        k, l = np.unravel_index(int(np.argmax(D)), D.shape)  # premier maximum (ordre par colonnes en R)
        AC[k] += AC[l]; bC[k] += bC[l]
        nC[k] += nC[l]; nC[l] = 0
        act[l] = False
        Lc[k] = Lfun(AC[k], bC[k])
        grp[grp == l] = k
        D[l, :] = -np.inf; D[:, l] = -np.inf
        for j in np.flatnonzero(act):
            if j == k:
                continue
            if j < k:
                D[j, k] = dfun(j, k)
            else:
                D[k, j] = dfun(k, j)
        Kc -= 1
        icl_path[Kc] = Lc[act].sum() + icl_part(Kc, nC[act])
        if Kc <= K_max:
            parts[Kc] = grp.copy()
    parts = [None if g is None else np.unique(g, return_inverse = True)[1][cl] + 1 for g in parts]
    K_tree = int(np.nanargmax(icl_path))
    return SimpleNamespace(parts = parts, icl_path = icl_path[1:], K_tree = K_tree, K0 = K0, micro = cl + 1,
                           G_within = Gw, s2_within = s2w, T0 = T0, m0 = m0)


# =========================================================================== #
#  Criteres et utilitaires                                                    #
# =========================================================================== #

def _criteria_table (fits, q, N, penalty):
    """ .im_criteria_table : BIC, ICL, entropie, nombre de parametres. """
    lignes = []
    for f in fits:
        if f is None:
            continue
        dK = (f.K - 1) + (f.n_alpha or 0) + f.edf + q * (q + 1) / 2 + 1 + float(penalty)
        tt = f.tau[f.tau > 0]
        ent = float(-np.sum(tt * np.log(tt)))
        bic = -2 * f.ll + dK * math.log(N)
        lignes.append({"K": f.K, "loglik": f.ll, "edf": f.edf, "n_par": dK, "BIC": bic,
                       "ICL": bic + 2 * ent, "entropy": ent, "min_pi": float(np.min(f.pi))})
    return pd.DataFrame(lignes)


def _onehot (lab, K, eps = 0.01):
    """ .im_onehot : labels 1..K -> responsabilites lissees. """
    lab = np.asarray(lab, dtype = int)
    tau = np.full((len(lab), K), eps / K)
    tau[np.arange(len(lab)), lab - 1] = 1 - eps + eps / K
    return tau


def _inv (M):
    L = np.linalg.cholesky(M)
    Li = np.linalg.inv(L)
    return Li.T @ Li


def _logdet (M):
    return 2 * float(np.sum(np.log(np.diag(np.linalg.cholesky(M)))))


def _psd_floor (M, floor_abs):
    M = (M + M.T) / 2
    valeurs, vecteurs = np.linalg.eigh(M)
    return (vecteurs * np.maximum(valeurs, floor_abs)) @ vecteurs.T


# =========================================================================== #
#  Methodes : resume, prediction, courbes individuelles, graphique            #
# =========================================================================== #

def _qnorm (p):
    """ Quantile de la loi normale (approximation d'Acklam, erreur < 1.2e-9 apres une iteration de Newton). """
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    dd = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        u = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) / ((((dd[0]*u+dd[1])*u+dd[2])*u+dd[3])*u+1)
    elif p <= 1 - pl:
        u = p - 0.5; r = u * u
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*u / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        u = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) / ((((dd[0]*u+dd[1])*u+dd[2])*u+dd[3])*u+1)
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    return x - e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)


def predict_infomergecluster (x, times = None, interval = "none", level = 0.95, covariates = "cluster", type = None):
    """ predict.infomerge : trajectoires moyennes des clusters, avec enveloppe
    optionnelle.
    interval = "none" : courbes moyennes seules ; "confidence" : bande de
      confiance ponctuelle de la courbe moyenne, f_k(t) +/- z sqrt(a(t)' H_k^-1 a(t)),
      a(t) = (B(t), x_k). Colonnes <Ck>_lwr et <Ck>_upr : bornes.
      (L'enveloppe de prediction du code R n'est pas reprise.)
    covariates : valeurs x_k des covariables auxquelles la courbe du cluster k
      est evaluee, f_k(t) = B(t)' beta_k + x_k' gamma_k :
      "cluster" (defaut) : moyennes des covariables parmi les sujets du
        cluster k, ponderees par les probabilites a posteriori (pour une
        indicatrice : proportion du niveau dans le cluster, soit le melange
        des courbes par niveau) ;
      "population" : moyennes sur l'ensemble des sujets, memes valeurs pour
        tous les clusters (comparaison a composition egale) ;
      "zero" : covariables nulles (niveau de reference des facteurs,
        variables continues a 0), soit B beta_k ;
      liste de valeurs : valeurs imposees, dans l'ordre de x.gamma.index
        (indicatrices ou proportions pour les facteurs), echelle d'origine.
    type (ajout de l'application) : "raw" = covariates "cluster",
      "regressed" = covariates "population" (donnees de donnees_regressees). """
    if type is not None:
        if type not in ("raw", "regressed"):
            raise ValueError("'type' must be \"raw\" or \"regressed\".")
        covariates = "cluster" if type == "raw" else "population"
    if interval not in ("none", "confidence"):
        raise ValueError("'interval' must be \"none\" or \"confidence\".")
    if times is None:
        times = np.linspace(x.basis["lo"], x.basis["hi"], 200)
    times = np.asarray(times, dtype = float)
    Bt = _basis_eval(x.basis, times)
    labs = list(x.beta.columns)
    K = len(labs)
    Xk = _im_cov_values(x, covariates)                       # K x r (r = 0 sans covariables)
    r = Xk.shape[1]
    nT = len(Bt)
    A_classes, fit = [], np.zeros((nT, K))
    for k in range(K):
        if r > 0:
            Ak = np.hstack([Bt, np.tile(Xk[k], (nT, 1))])
            fit[:, k] = Ak @ np.concatenate([x.beta.iloc[:, k].to_numpy(dtype = float), x.gamma.iloc[:, k].to_numpy(dtype = float)])
        else:
            Ak = Bt
            fit[:, k] = Bt @ x.beta.iloc[:, k].to_numpy(dtype = float)
        A_classes.append(Ak)
    out = pd.DataFrame(fit, columns = labs)
    out.insert(0, "time", times)
    out.attrs["covariates"] = Xk
    if interval == "none":
        return out
    if not 0 < level < 1:
        raise ValueError("'level' must be in ]0, 1[.")
    z = _qnorm(1 - (1 - level) / 2)
    for k, lab in enumerate(labs):
        At = A_classes[k]
        se = np.sqrt(np.maximum(np.sum((At @ x.Vbeta[lab]) * At, axis = 1), 0))
        out[lab + "_lwr"] = fit[:, k] - z * se
        out[lab + "_upr"] = fit[:, k] + z * se
    return out


def _im_cov_values (x, covariates):
    """ .im_cov_values : valeurs des covariables (matrice K x r) utilisees par
    predict ; voir l'argument covariates de predict_infomergecluster. """
    K = x.beta.shape[1]
    r = 0 if x.gamma is None else x.gamma.shape[0]
    if r == 0:
        return np.zeros((K, 0))
    if covariates is None:
        covariates = "zero"
    if not isinstance(covariates, str):
        valeurs = np.asarray(covariates, dtype = float).ravel()
        if len(valeurs) != r:
            raise ValueError("'covariates' must have %d value(s), in the order: %s" % (r, ", ".join(x.gamma.index)))
        return np.tile(valeurs, (K, 1))
    if covariates not in ("cluster", "population", "zero"):
        raise ValueError("'covariates' must be \"cluster\", \"population\", \"zero\" or numeric values.")
    if covariates == "zero":
        return np.zeros((K, r))
    cm = getattr(x, "cov_means", None)
    if cm is None and getattr(x, "data", None) is not None:
        cm = _im_cov_means(x.data, x.covariates["names"], x.ids, x.posterior)
    if cm is None:
        return np.zeros((K, r))                       # moyennes indisponibles : covariables nulles
    if covariates == "cluster":
        return cm["cluster"].to_numpy(dtype = float)
    return np.tile(cm["population"].to_numpy(dtype = float), (K, 1))


def _im_cov_means (dd, cov_names, ids, tau):
    """ .im_cov_means : moyennes des covariables, par sujet (moyenne de ses
    mesures), puis sur la population et par cluster (ponderation par tau).
    ids : identifiants dans l'ordre des lignes de tau. """
    ids = [str(i) for i in ids]
    idx = pd.Index(ids).get_indexer(dd["id"].astype(str))
    X = dd[cov_names].to_numpy(dtype = float)
    xs = np.zeros((len(ids), len(cov_names)))
    np.add.at(xs, idx, X)
    xs = xs / np.bincount(idx, minlength = len(ids))[:, None]
    cn = [c[4:] if c.startswith("cov_") else c for c in cov_names]
    T = tau.to_numpy(dtype = float) if hasattr(tau, "to_numpy") else np.asarray(tau, dtype = float)
    labs = list(tau.columns) if hasattr(tau, "columns") else ["C%d" % (k + 1) for k in range(T.shape[1])]
    population = pd.Series(xs.mean(axis = 0), index = cn)
    cluster = pd.DataFrame((T.T @ xs) / T.sum(axis = 0)[:, None], index = labs, columns = cn)
    return {"population": population, "cluster": cluster}


def moyennes_covariables_classes (x):
    """ Moyennes des covariables de chaque cluster (ponderees par les
    probabilites a posteriori), liste de K vecteurs. """
    return list(_im_cov_values(x, "cluster"))


def donnees_regressees (x):
    """ Donnees regressees sur les covariables (ajout de l'application) :
    y_reg = y - (x_ij - xbar)' gamma_k, effet des covariables du cluster (MAP)
    du sujet retire, les covariables etant ramenees a leur moyenne sur la
    population (xbar, comme predict(covariates = "population")). Renvoie une
    copie de x.data avec la colonne « y_reg » (egale a y sans covariable). """
    if x.data is None:
        raise ValueError("Rerun infomergecluster() with keep_data = True.")
    d = x.data.copy()
    d["y_reg"] = d["y"].to_numpy(dtype = float)
    if x.gamma is not None:
        k = d["id"].astype(str).map(x.cluster).to_numpy(dtype = int) - 1
        xbar = _im_cov_values(x, "population")[0]
        X = d[x.covariates["names"]].to_numpy(dtype = float) - xbar[None, :]
        effet = np.einsum("ij,ji->i", X, x.gamma.to_numpy()[:, k])
        d["y_reg"] = d["y_reg"] - effet
    return d


def fitted_curves (x, times = None):
    """ fitted_curves : trajectoires individuelles predites (BLUP sachant la
    classe MAP). Renvoie un DataFrame sujets x temps. """
    if x.data is None:
        raise ValueError("Rerun infomergecluster() with keep_data = True.")
    if times is None:
        times = np.linspace(x.basis["lo"], x.basis["hi"], 100)
    d = x.data
    Bt = _basis_eval(x.basis, times)
    Zt = _Z(x.basis, x.re, np.asarray(times, dtype = float), Bt)
    res = np.full((len(x.ids), len(times)), np.nan)
    for i, (ident, di) in enumerate(d.groupby(d["id"].astype(str), sort = False)):
        Bi = _basis_eval(x.basis, di["t"].to_numpy())
        Zi = _Z(x.basis, x.re, di["t"].to_numpy(), Bi)
        Vi = Zi @ x.G @ Zi.T + x.sigma2 * np.eye(len(Zi))
        k = int(x.cluster[ident]) - 1
        bk = x.beta.iloc[:, k].to_numpy()
        decal_obs = decal_grille = 0.0
        if x.gamma is not None:
            Xi = di[x.covariates["names"]].to_numpy(dtype = float)
            gk = x.gamma.iloc[:, k].to_numpy()
            decal_obs = Xi @ gk
            decal_grille = float(Xi.mean(axis = 0) @ gk)
        u = x.G @ Zi.T @ np.linalg.solve(Vi, di["y"].to_numpy() - Bi @ bk - decal_obs)
        res[x.ids.index(ident)] = Bt @ bk + decal_grille + Zt @ u
    return pd.DataFrame(res, index = x.ids)


def _hcl_dark3 (k):
    """ hcl.colors(k, "Dark 3") (qualitative : chroma 80, luminance 60). """
    couleurs = []
    for i in range(k):
        h = math.radians(360.0 * i / k)
        L, C = 60.0, 80.0
        u, v = C * math.cos(h), C * math.sin(h)
        Y = ((L + 16) / 116) ** 3 * 100
        un, vn = 0.1978398, 0.4683363
        up, vp = u / (13 * L) + un, v / (13 * L) + vn
        X = 9 * Y * up / (4 * vp)
        Zc = -X / 3 - 5 * Y + 3 * Y / vp
        rgb = np.array([[3.240479, -1.537150, -0.498535], [-0.969256, 1.875992, 0.041556],
                        [0.055648, -0.204043, 1.057311]]) @ (np.array([X, Y, Zc]) / 100)
        rgb = np.where(rgb > 0.00304, 1.055 * np.clip(rgb, 0, None) ** (1 / 2.4) - 0.055, 12.92 * rgb)
        couleurs.append("#%02x%02x%02x" % tuple(int(round(255 * min(max(c, 0), 1))) for c in rgb))
    return couleurs


def plot_infomergecluster (ax, x, max_subjects = 300, envelope = False,
                           xlab = "Time (days)", ylab = "Weight", main = "InfoMergeCluster: K = %d (%s)",
                           level = 0.95, show_data = True, legend = True, legend_pos = "upper left", seed = 1,
                           data_type = "raw", covariates = None):
    """ plot.infomerge : trajectoires individuelles (couleur de leur cluster,
    transparentes), enveloppe de confiance facultative (niveau level) et
    trajectoires moyennes des clusters ;
    legende « Ck : N_k (p %) », N_k = nombre de sujets affectes au cluster k
    (affectation MAP), p = 100 N_k / N.
    covariates : valeurs des covariables des courbes moyennes, transmises a
    predict ("cluster" par defaut, "population", "zero" ou valeurs).
    data_type (application, modele avec covariables) : "raw" (donnees brutes,
    courbes aux moyennes des covariables de chaque cluster) ou "regressed"
    (donnees regressees sur les covariables, courbes aux moyennes de la
    population). """
    cols = _hcl_dark3(max(x.K, 2))[:x.K]
    labs = list(x.beta.columns)
    regressees = data_type == "regressed" and x.gamma is not None
    if covariates is None:
        covariates = "population" if regressees else "cluster"
    mc = predict_infomergecluster(x, interval = "confidence" if envelope else "none", level = level,
                                  covariates = covariates)
    ax.lignes_groupes = {k: [] for k in range(x.K)}       # elements de chaque classe (legende interactive)
    if show_data and x.data is not None:
        ids = x.ids
        rng = np.random.default_rng(seed)
        montres = set(rng.choice(ids, max_subjects, replace = False)) if len(ids) > max_subjects else set(ids)
        d = donnees_regressees(x) if regressees else x.data
        colonne_y = "y_reg" if regressees else "y"
        d = d[d["id"].astype(str).isin(montres)]
        segments = {k: [] for k in range(x.K)}
        for ident, s in d.groupby(d["id"].astype(str), sort = False):
            k = int(x.cluster[ident]) - 1
            segments[k].append(s[["t", colonne_y]].to_numpy(dtype = float))
        for k, objets in tracer_trajectoires_groupees(ax, segments, cols).items():
            ax.lignes_groupes[k] += objets
    if envelope:
        for k, lab in enumerate(labs):
            ax.lignes_groupes[k].append(ax.fill_between(mc["time"], mc[lab + "_lwr"], mc[lab + "_upr"], color = cols[k], alpha = 0.25, linewidth = 0))
            ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab + "_lwr"], color = cols[k], linestyle = "--", linewidth = 1)
            ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab + "_upr"], color = cols[k], linestyle = "--", linewidth = 1)
    n_k = np.bincount(x.cluster.to_numpy(dtype = int) - 1, minlength = x.K)   # sujets affectes (MAP)
    for k, lab in enumerate(labs):
        ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab], color = cols[k], linewidth = 3,
                                        label = "%s : %d (%.0f%%)" % (lab, n_k[k], 100 * n_k[k] / max(n_k.sum(), 1)))
    ax.set_xlim(x.basis["lo"], x.basis["hi"])
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)
    ax.set_title((main % (x.K, "imposed" if x.K_fixed else x.criterion) if "%" in main else main)
                 + ("  —  regressed on covariates" if regressees else ""))
    if legend:
        titre = "CE : %g%%" % (100 * level)                 # niveau de confiance, toujours indique
        ax.legend(loc = legend_pos, frameon = False, title = titre)
    return ax


def infomerge_stability (data, seeds = range(1, 11), verbose = False, log = print, **arguments):
    """ infomerge_stability : relance infomergecluster() avec plusieurs graines ;
    renvoie l'ajustement de meilleur critere, complete par un diagnostic de
    stabilite (frequence des K, ARI entre runs) dans x.stability. Les
    arguments de infomergecluster() passent par **arguments (sans seed). """
    seeds = list(seeds)
    fits = []
    for graine in seeds:
        if verbose:
            log("seed %s" % graine)
        fits.append(infomergecluster(data, seed = graine, verbose = False, **arguments))
    Ks = [int(f.K) for f in fits]
    crit = []
    for f in fits:
        ligne = f.table[f.table["K"] == f.K]
        crit.append(float(ligne["BIC" if f.criterion == "BIC" else "ICL"].iloc[0]))
    n = len(fits)
    ari = np.eye(n)
    for i in range(n - 1):
        for j in range(i + 1, n):
            a = fits[i].cluster
            ari[i, j] = ari[j, i] = indice_ari(a.to_numpy(), fits[j].cluster[a.index].to_numpy())
    best = fits[int(np.argmin(crit))]
    best.stability = {"seeds": seeds, "K": Ks, "K_freq": pd.Series(Ks).value_counts().sort_index(),
                      "criterion": crit, "ari": ari,
                      "mean_ari": float(ari[np.triu_indices(n, 1)].mean()) if n > 1 else 1.0}
    return best


def resume_infomergecluster (x):
    """ print.infomerge : resume texte de l'ajustement. """
    lignes = ["InfoMergeCluster: clustering of sparse longitudinal data",
              "  %d subjects, %d measurements, B-spline basis p = %d, random effect: %s"
              % (x.N, x.n_obs, x.basis["p"], x.re)]
    if x.K_fixed:
        lignes.append("  K imposed by the user: %d (not estimated)" % x.K)
    else:
        lignes.append("  K selected (%s): %d" % (x.criterion, x.K))
    lignes.append("  Proportions: " + ", ".join("%.3f" % p for p in x.pi))
    lignes.append("  sigma2 = %.4g ; trace(G) = %.4g ; lambda = %.3g ; effective df (total) = %.1f"
                  % (x.sigma2, float(np.trace(x.G)), x.lam, x.edf))
    sc = getattr(x, "scaling", None)
    if sc is not None and sc.get("standardize"):
        lignes.append("  Data standardized (Min-Max) for the fit; results on the original scale")
    pr = getattr(x, "prior", None)
    if pr is not None:
        q = pr["q"]
        lignes.append("  Priors: G ~ IW(nu0 = %.3g, Psi0 [trace %.3g]) ; sigma2 ~ IG(%.3g, %.3g)"
                      % (pr["nu0"], float(np.trace(pr["Psi0"])), pr["a_sigma"], pr["b_sigma"]))
        lignes.append("    nugget = %.4g (%s), sill = %.4g ; prior modes: sigma2 = %.4g, G = %.4g I"
                      % (pr["nugget"], pr["nugget_source"], x.variogram["sill"], pr["b_sigma"] / (pr["a_sigma"] + 1),
                         float(np.mean(np.diag(pr["Psi0"]))) / (pr["nu0"] + q + 1)))
    if x.gamma is not None:
        lignes.append("  Covariates (not centered, cluster-specific effects gamma_k): " + ", ".join(x.gamma.index))
        ref = (x.covariates or {}).get("reference") or {}
        if ref:
            lignes.append("  Reference modalities (most frequent): " + ", ".join("%s = %s" % kv for kv in ref.items()))
        lignes += ["    " + l for l in x.gamma.round(4).to_string().splitlines()]
    if x.weights == "covariates" and x.alpha is not None:
        lignes.append("  Covariate-dependent weights (multinomial logistic, reference C1):")
        lignes += ["    " + l for l in x.alpha.round(4).to_string().splitlines()]
    lignes.append("  computing time = %.2f s" % getattr(x, "time_sec", float("nan")))
    if getattr(x, "var_y", None) is not None and x.sigma2 < 1e-3 * x.var_y:
        lignes.append("  WARNING: residual variance almost zero (sigma2 < 0.1 % of var(y)). In this regime "
                      "(data without measurement error), several partitions have almost equal criteria: "
                      "the selected K may vary with the seed or a_dir. See infomerge_stability() or increase df.")
    st = getattr(x, "stability", None)
    if st is not None:
        lignes.append("  Stability over %d seeds: mean ARI between partitions = %.2f" % (len(st["seeds"]), st["mean_ari"]))
        lignes.append("  Frequency of the K obtained: " + ", ".join("K=%s : %d" % (k, v) for k, v in st["K_freq"].items()))
    tab = x.table.copy()
    for c in ("loglik", "edf", "n_par", "BIC", "ICL", "entropy"):
        tab[c] = tab[c].round(2)
    tab["min_pi"] = tab["min_pi"].round(3)
    lignes += ["  " + l for l in tab.to_string(index = False).splitlines()]
    return "\n".join(lignes)


# =========================================================================== #
#  FKMS : k-means fonctionnel avec covariables, lambda choisi par GCV         #
#  (traduction de fkms.covariables.lambda.gcv et de ses dependances, code R   #
#  fkms_cov.R ; bs(), bsplinepen(), fourier(), ginv(), AssignClust_C,         #
#  classError remplaces par leurs equivalents numpy)                          #
# =========================================================================== #

def _fk_bspline_bs (eval_x, N_bs):
    """ splines::bs(eval.x, df = N.bs, intercept = TRUE) : B-splines cubiques,
    noeuds interieurs aux quantiles des temps distincts. """
    if N_bs < 4:
        raise ValueError("'N.bs' must be >= 4 for the B-spline basis.")
    lo, hi = float(np.min(eval_x)), float(np.max(eval_x))
    n_int = N_bs - 4
    interieur = np.quantile(eval_x, np.linspace(0, 1, n_int + 2)[1:-1]) if n_int > 0 else np.array([])
    knots = np.concatenate([np.repeat(lo, 4), interieur, np.repeat(hi, 4)])
    return {"type": "B", "knots": knots, "ord": 4, "lo": lo, "hi": hi, "N_bs": N_bs}


def _fk_bsplinepen (lo, hi, N_bs, m = 2):
    """ fda::bsplinepen(create.bspline.basis(c(lo, hi), nbasis = N.bs), int2Lfd(2)) :
    P_jl = int B_j'' B_l'' dt, base B-spline cubique a noeuds equidistants
    (quadrature de Gauss-Legendre exacte par intervalle). """
    br = np.linspace(lo, hi, N_bs - 4 + 2)
    knots = np.concatenate([np.repeat(lo, 3), br, np.repeat(hi, 3)])
    a, h = br[:-1], np.diff(br)
    gx, gw = np.polynomial.legendre.leggauss(4)
    x = np.repeat(a + h / 2, len(gx)) + np.repeat(h / 2, len(gx)) * np.tile(gx, len(a))
    w = np.repeat(h / 2, len(gx)) * np.tile(gw, len(a))
    Dm = _spline_design(knots, x, 4, m) * np.sqrt(w)[:, None]
    P = Dm.T @ Dm
    return (P + P.T) / 2


def _fk_fourier (x, N_bs, period):
    """ fda::fourier(x, nbasis = N.bs, period) : constante puis sin / cos. """
    x = np.asarray(x, dtype = float)
    omega = 2 * math.pi / period
    cols = [np.full(len(x), 1 / math.sqrt(2))]
    for j in range(1, (N_bs - 1) // 2 + 1):
        cols += [np.sin(j * omega * x), np.cos(j * omega * x)]
    return np.column_stack(cols) / math.sqrt(period / 2)


def fkms_basis_eval (basis, t):
    """ Fonctions de base (B-splines ou Fourier) aux temps t. """
    t = np.asarray(t, dtype = float)
    if basis["type"] == "B":
        return _spline_design(basis["knots"], np.clip(t, basis["lo"], basis["hi"]), basis["ord"])
    return _fk_fourier(t, basis["N_bs"], basis["period"])


def _fk_ginv (A):
    """ MASS::ginv """
    return np.linalg.pinv(A)


def SelectLambdaGCV (D, w, y, P, lambda_grid):
    """ Lambda d'un cluster par GCV : n * RSS / (n - edf)^2. """
    n = D.shape[0]
    M = D.T @ (D * w[:, None])
    b = D.T @ (w * y)
    gcv = np.full(len(lambda_grid), np.inf)
    for i, lam in enumerate(lambda_grid):
        A_inv = _fk_ginv(M + lam * P)
        beta = A_inv @ b
        denom = n - np.trace(A_inv @ M)
        if denom <= 0:
            continue
        gcv[i] = n * np.sum(w * (y - D @ beta) ** 2) / denom ** 2
    return lambda_grid[0] if not np.isfinite(gcv).any() else lambda_grid[int(np.argmin(gcv))]


def _fk_donnees_cluster (S, Z, y, w, cls, k, P_ext):
    """ Design (base + covariables) d'un cluster, sans les colonnes nulles. """
    lignes = cls == k
    D = S[lignes] if Z is None else np.hstack([S[lignes], Z[lignes]])
    garder = np.where(~np.all(D == 0, axis = 0))[0] if D.shape[0] else np.array([], dtype = int)
    return D[:, garder], P_ext[np.ix_(garder, garder)], y[lignes], w[lignes], garder


def SelectLambdaGCV_Global (S, Z, y, w, cls, N_clust, P_ext, lambda_grid):
    """ Lambda unique, commun a tous les clusters, par GCV globale. """
    blocs = []
    for k in range(1, N_clust + 1):
        D, P, yk, wk, _ = _fk_donnees_cluster(S, Z, y, w, cls, k, P_ext)
        blocs.append((D, D.T @ (D * wk[:, None]), D.T @ (wk * yk), P, wk, yk))
    gcv = np.full(len(lambda_grid), np.inf)
    for i, lam in enumerate(lambda_grid):
        rss = edf = n = 0.0
        for D, M, b, P, wk, yk in blocs:
            A_inv = _fk_ginv(M + lam * P)
            beta = A_inv @ b
            edf += np.trace(A_inv @ M)
            rss += np.sum(wk * (yk - D @ beta) ** 2)
            n += D.shape[0]
        if n - edf > 0:
            gcv[i] = n * rss / (n - edf) ** 2
    return lambda_grid[0] if not np.isfinite(gcv).any() else lambda_grid[int(np.argmin(gcv))]


def FitClustersIndependent (S, Z, y, w, cls, N_clust, P_ext, basis_type, lam, lambda_gcv, lambda_grid, lambda_common):
    """ Ajustement independant de chaque cluster : moindres carres ponderes
    penalises (base B) ou regression ponderee lm (base de Fourier). Renvoie les
    coefficients (base puis covariables) et les lambdas retenus. """
    p = S.shape[1] + (0 if Z is None else Z.shape[1])
    coefs, lambdas = [], np.zeros(N_clust)
    partage = None
    if basis_type == "B" and lambda_gcv and lambda_common:
        partage = SelectLambdaGCV_Global(S, Z, y, w, cls, N_clust, P_ext, lambda_grid)
    for k in range(1, N_clust + 1):
        D, P, yk, wk, garder = _fk_donnees_cluster(S, Z, y, w, cls, k, P_ext)
        beta = np.zeros(p)
        if basis_type == "B":
            lam_k = (partage if lambda_common else SelectLambdaGCV(D, wk, yk, P, lambda_grid)) if lambda_gcv else lam
            lambdas[k - 1] = lam_k
            if D.shape[0]:
                beta[garder] = _fk_ginv(D.T @ (D * wk[:, None]) + lam_k * P) @ (D.T @ (wk * yk))
        elif D.shape[0]:                                    # lm(y ~ 0 + ..., weights = wt)
            rw = np.sqrt(wk)
            beta[garder] = np.linalg.lstsq(D * rw[:, None], yk * rw, rcond = None)[0]
        coefs.append(beta)
    return coefs, lambdas


def _fk_affecter (ids_codes, N_sub, loss):
    """ AssignClust_C : chaque individu va au cluster de perte totale minimale. """
    totaux = np.vstack([np.bincount(ids_codes, weights = loss[:, k], minlength = N_sub) for k in range(loss.shape[1])]).T
    return np.argmin(totaux, axis = 1) + 1


def _fk_meme_partition (a, b):
    """ classError(a, b)$errorRate == 0 : partitions identiques a l'etiquetage pres. """
    tab = pd.crosstab(a, b).to_numpy()
    return bool(np.all((tab > 0).sum(axis = 1) == 1) and np.all((tab > 0).sum(axis = 0) == 1))


def ComputeCoefVcov (D, y, w, ident, beta, lam, P, se_type = "sandwich"):
    """ Covariance des coefficients d'un cluster : « sandwich » (scores
    regroupes par individu, correction G / (G - 1)) ou « model » (erreurs iid). """
    DtWD = D.T @ (D * w[:, None])
    A_inv = _fk_ginv(DtWD + lam * P)
    r = y - D @ beta
    edf = float(np.trace(A_inv @ DtWD))
    if se_type == "sandwich":
        codes, _ = pd.factorize(ident)
        U = np.zeros((codes.max() + 1 if len(codes) else 0, D.shape[1]))
        np.add.at(U, codes, D * (w * r)[:, None])
        G = U.shape[0]
        meat = U.T @ U * G / max(G - 1, 1)
    else:
        sigma2 = np.sum(r ** 2) / max(len(y) - edf, 1)
        meat = sigma2 * (D.T @ (D * (w ** 2)[:, None]))
    V = A_inv @ meat @ A_inv
    return (V + V.T) / 2, edf


def BandFromVcov (Gm, est, V, level = 0.95):
    """ Bande de confiance ponctuelle autour de est = Gm beta, comme pour
    InfoMergeCluster : est +/- z se, se = sqrt(diag(Gm V Gm')),
    z = quantile normal d'ordre 1 - (1 - level) / 2. """
    se = np.sqrt(np.maximum(np.sum((Gm @ V) * Gm, axis = 1), 0))
    z = _qnorm(1 - (1 - level) / 2)
    return {"se": se, "lower": est - z * se, "upper": est + z * se, "crit": z}


def _fk_preparer (data, N_cov, cov_labels, message = None):
    """ Tableau long : identifiant, temps, reponse puis les N_cov covariables ;
    lignes incompletes retirees ; mesures regroupees par individu.
    Covariables (meme codage qu'InfoMergeCluster, _im_covariate_design, sans
    standardisation ni centrage) : facteurs (texte, booleens, categories)
    codes en indicatrices, modalite de reference = la plus frequente (en
    nombre de sujets distincts, puis de mesures, puis ordre des niveaux) ;
    facteurs a une seule modalite et colonnes constantes retires.
    Renvoie (tableau, noms des colonnes de covariables, references). """
    d = pd.DataFrame(data).copy()
    if d.shape[1] < 3 + N_cov:
        raise ValueError("With N.cov = %d, the data must have at least %d columns: identifier, time, response "
                         "and the covariates." % (N_cov, 3 + N_cov))
    noms = list(cov_labels) if cov_labels is not None else ["z%d" % (j + 1) for j in range(N_cov)]
    base = pd.DataFrame({"id": d.iloc[:, 0].astype(str), "x": pd.to_numeric(d.iloc[:, 1], errors = "coerce"),
                         "y": pd.to_numeric(d.iloc[:, 2], errors = "coerce")})
    brut = d.iloc[:, 3:3 + N_cov].copy() if N_cov > 0 else None
    if brut is not None:
        brut.columns = noms
    ok = base["x"].notna() & base["y"].notna()
    if brut is not None:
        ok &= brut.notna().all(axis = 1)
    base = base[ok.to_numpy()].reset_index(drop = True)
    Z, z_names, references = None, [], {}
    if brut is not None:
        design = _im_covariate_design(brut.reset_index(drop = True), ok.to_numpy(), standardize = False,
                                      ids = base["id"].to_numpy(), message = message)
        references = design["reference"]
        if design["X"] is not None:
            z_names = [c[4:] for c in design["names"]]
            Z = design["X"].to_numpy(dtype = float)
            for j, c in enumerate(z_names):
                base[c] = Z[:, j]
    ## individus dans l'ordre d'apparition, mesures triees par temps
    ordre_id = {v: i for i, v in enumerate(pd.unique(base["id"]))}
    base["_o"] = base["id"].map(ordre_id)
    base = base.sort_values(["_o", "x"], kind = "stable").drop(columns = "_o").reset_index(drop = True)
    return base, z_names, references


def fkms_covariables_lambda_gcv (data, N_clust = 2, N_bs = None, N_random = 1, N_rep = 100, ini_cls = None,
                                 basis = "B", lam = 0.0, N_cov = 0, lambda_gcv = False,
                                 lambda_grid = None, lambda_common = False, cov_effect = "cluster",
                                 conf_band = True, conf_level = 0.95, se_type = "sandwich",
                                 seed = None, cov_labels = None,
                                 verbose = False, log = print, arret = None):
    """ fkms.covariables.lambda.gcv : k-means fonctionnel (base B-spline ou de
    Fourier) avec covariables, effet des covariables propre a chaque cluster
    (« cluster ») ou commun (« common »), lambda fixe ou choisi par GCV
    (propre a chaque cluster ou commun), poids 1 / n_i par mesure, N_random
    initialisations aleatoires (meilleur MSE), enveloppes des courbes moyennes.
    data : tableau long, colonnes identifiant, temps, reponse puis les N_cov
    covariables. Les clusters sont renumerotes par effectif decroissant.
    arret : fonction appelee a chaque iteration (interruption possible). """
    if N_bs is None:
        raise ValueError("Check the argument 'N.bs'.")
    if basis not in ("B", "F"):
        raise ValueError("Check the argument 'basis' (\"B\" or \"F\").")
    if lambda_grid is None:
        lambda_grid = 10 ** np.linspace(-6, 3, 30)
    lambda_grid = np.asarray(lambda_grid, dtype = float)
    rng = np.random.default_rng(seed)
    message = (lambda m: log(m)) if verbose else (lambda m: None)
    d, z_names, references = _fk_preparer(data, int(N_cov), cov_labels, message = message)
    N_cov = len(z_names)
    if basis == "F" and N_bs % 2 == 0:
        N_bs += 1
    ids_codes, ids = pd.factorize(d["id"])
    N_sub = len(ids)
    x, y = d["x"].to_numpy(float), d["y"].to_numpy(float)
    nt = np.bincount(ids_codes, minlength = N_sub)
    w = 1.0 / nt[ids_codes]                                 # wt = 1 / n_i
    eval_x = np.unique(x)
    if basis == "B":
        base = _fk_bspline_bs(eval_x, N_bs)
    else:
        base = {"type": "F", "N_bs": N_bs, "period": float(eval_x.max() - eval_x.min()),
                "lo": float(eval_x.min()), "hi": float(eval_x.max())}
    S = fkms_basis_eval(base, x)
    Z = d[z_names].to_numpy(float) if N_cov > 0 else None
    P = _fk_bsplinepen(base["lo"], base["hi"], N_bs) if basis == "B" and (lambda_gcv or lam > 0) else np.zeros((N_bs, N_bs))
    P_ext = np.zeros((N_bs + N_cov, N_bs + N_cov))
    P_ext[:N_bs, :N_bs] = P
    Dfull = S if Z is None else np.hstack([S, Z])
    message("FKMS: N = %d subjects, %d measurements, K = %d, basis %s, N.bs = %d, N.cov = %d"
            % (N_sub, len(d), N_clust, basis, N_bs, N_cov))

    meilleur = {"mse": np.inf}
    for n_random in range(1, N_random + 1):
        if n_random == 1 and ini_cls is not None:
            cls_sub = np.asarray(ini_cls, dtype = int)
        else:
            cls_sub = rng.integers(1, N_clust + 1, N_sub)          # rmultinom (probabilites egales)
        cls_prev = cls_sub
        cls = cls_sub[ids_codes]
        for n_rep in range(N_rep):
            if arret is not None:
                arret()
            if N_cov > 0 and cov_effect == "common":
                ## effet commun des covariables : un seul systeme, base par cluster + covariables
                p_big = N_clust * N_bs + N_cov
                D_big = np.zeros((len(d), p_big))
                P_big = np.zeros((p_big, p_big))
                for k in range(N_clust):
                    lignes = cls == k + 1
                    D_big[lignes, k * N_bs:(k + 1) * N_bs] = S[lignes]
                    if basis == "B":
                        P_big[k * N_bs:(k + 1) * N_bs, k * N_bs:(k + 1) * N_bs] = P
                D_big[:, N_clust * N_bs:] = Z
                garder = np.where(~np.all(D_big == 0, axis = 0))[0]
                D_use, P_use = D_big[:, garder], P_big[np.ix_(garder, garder)]
                if basis == "B":
                    lam_c = SelectLambdaGCV(D_use, w, y, P_use, lambda_grid) if lambda_gcv else lam
                else:
                    lam_c = 0.0
                lambdas = np.full(N_clust, lam_c)
                beta_big = np.zeros(p_big)
                beta_big[garder] = _fk_ginv(D_use.T @ (D_use * w[:, None]) + lam_c * P_use) @ (D_use.T @ (w * y))
                gamma_c = beta_big[N_clust * N_bs:]
                coefs = [np.concatenate([beta_big[k * N_bs:(k + 1) * N_bs], gamma_c]) for k in range(N_clust)]
            else:
                coefs, lambdas = FitClustersIndependent(S, Z, y, w, cls, N_clust, P_ext, basis, lam,
                                                        lambda_gcv, lambda_grid, lambda_common)
            perte = np.column_stack([(y - Dfull @ coefs[k]) ** 2 for k in range(N_clust)])
            nouveau = _fk_affecter(ids_codes, N_sub, perte)
            cls_nouveau = nouveau[ids_codes]
            effectifs = np.bincount(cls_nouveau, minlength = N_clust + 1)[1:]
            if np.any(effectifs == 0) or np.any(effectifs < N_bs):
                cls_sub = cls_prev                         # cluster vide ou trop petit : on garde la partition
                break
            cls_sub = nouveau
            cls = cls_nouveau
            if _fk_meme_partition(cls_sub, cls_prev):
                break
            cls_prev = cls_sub
        mse = 0.0
        for k in range(N_clust):
            lignes = cls == k + 1
            if lignes.any():
                mse += np.mean((y[lignes] - Dfull[lignes] @ coefs[k]) ** 2)
        message("  random start %d: MSE = %.5g" % (n_random, mse))
        if np.isfinite(mse) and mse < meilleur["mse"]:
            meilleur = {"mse": mse, "cls": cls_sub.copy(), "coefs": coefs, "lambdas": lambdas, "n_opt": n_random}

    if "cls" not in meilleur:
        raise ValueError("FKMS did not converge (MSE not finite).")
    ## clusters renumerotes par effectif decroissant (comme InfoMergeCluster)
    eff = np.bincount(meilleur["cls"], minlength = N_clust + 1)[1:]
    ordre = np.argsort(-eff, kind = "stable")
    nouvel_indice = np.empty(N_clust, dtype = int)
    nouvel_indice[ordre] = np.arange(N_clust)
    cls_sub = nouvel_indice[meilleur["cls"] - 1] + 1
    cls = cls_sub[ids_codes]
    coefs = [meilleur["coefs"][k] for k in ordre]
    lambdas = meilleur["lambdas"][ordre]
    if N_cov > 0 and cov_effect == "common":               # ajustement final par cluster (comme en R)
        coefs, lambdas = FitClustersIndependent(S, Z, y, w, cls, N_clust, P_ext, basis, lam,
                                                lambda_gcv, lambda_grid, lambda_common)
    labs = ["C%d" % (k + 1) for k in range(N_clust)]
    beta = pd.DataFrame(np.column_stack([c[:N_bs] for c in coefs]), columns = labs)
    gamma = pd.DataFrame(np.column_stack([c[N_bs:] for c in coefs]), index = z_names, columns = labs) if N_cov > 0 else None
    vcov, edf = {}, {}
    if conf_band:
        for k, lab in enumerate(labs):
            lignes = cls == k + 1
            vcov[lab], edf[lab] = ComputeCoefVcov(Dfull[lignes], y[lignes], w[lignes], d["id"].to_numpy()[lignes],
                                                  coefs[k], lambdas[k] if basis == "B" else 0.0, P_ext, se_type)
    data_out = d.copy()
    data_out["wt"] = w
    data_out["cluster"] = cls
    data_out = data_out.rename(columns = {"x": "t"})
    n_k = np.bincount(cls_sub, minlength = N_clust + 1)[1:]
    message("FKMS: MSE = %.5g, sizes = %s" % (meilleur["mse"], ", ".join(str(int(v)) for v in n_k)))
    return SimpleNamespace(
        method = "FKMS", K = N_clust, K_fixed = True, criterion = "MSE",
        cluster = pd.Series(cls_sub, index = [str(i) for i in ids]), ids = [str(i) for i in ids],
        data = data_out, beta = beta, gamma = gamma, z_names = z_names,
        cov_reference = references,                    # modalite de reference de chaque facteur (la plus frequente)
        z_mean_all = d[z_names].mean().to_numpy(float) if N_cov > 0 else np.zeros(0),
        basis = base, vcov = vcov, edf = edf, conf_level = conf_level, se_type = se_type,
        lambda_clust = pd.Series(lambdas, index = labs) if basis == "B" else None,
        n_k = pd.Series(n_k, index = labs), pi = pd.Series(n_k / n_k.sum(), index = labs),
        mse = float(meilleur["mse"]), n_opt = meilleur["n_opt"], N = N_sub, n_obs = len(d),
        cov_effect = cov_effect, table = None)


def fkms_selection_k (data, K_max = 8, k_seq = None, log = print, verbose = False, **arguments):
    """ f.mse.cov : FKMS pour k = 1, ..., K_max (ou k_seq), K retenu = MSE
    minimal, puis ajustement final avec ce K ; table des MSE dans x.table. """
    k_seq = list(range(1, int(K_max) + 1)) if k_seq is None else [int(k) for k in k_seq]
    mse = []
    for k in k_seq:
        try:
            mse.append(fkms_covariables_lambda_gcv(data, N_clust = k, verbose = False, log = log, **arguments).mse)
        except ArretDemandeAlgorithme:
            raise
        except Exception as erreur:
            log("  k = %d failed: %s" % (k, erreur))
            mse.append(np.nan)
        if verbose:
            log("  k = %d  mse = %.4g" % (k, mse[-1]))
    table = pd.DataFrame({"K": k_seq, "MSE": mse})
    if table["MSE"].notna().sum() == 0:
        raise ValueError("FKMS failed for every value of K.")
    k_opt = int(table.loc[table["MSE"].idxmin(), "K"])
    res = fkms_covariables_lambda_gcv(data, N_clust = k_opt, verbose = verbose, log = log, **arguments)
    res.K_fixed, res.table = False, table
    return res


class ArretDemandeAlgorithme (Exception):
    """ Interruption demandee pendant un calcul (bouton d'arret). """


def donnees_regressees_fkms (x):
    """ Donnees regressees sur les covariables : y_reg = y - (z - zbar) gamma_k,
    covariables ramenees a leur moyenne generale (comme pour InfoMergeCluster). """
    d = x.data.copy()
    d["y_reg"] = d["y"].to_numpy(float)
    if x.gamma is not None:
        k = d["cluster"].to_numpy(int) - 1
        Zc = d[x.z_names].to_numpy(float) - x.z_mean_all
        d["y_reg"] -= np.einsum("ij,ji->i", Zc, x.gamma.to_numpy()[:, k])
    return d


def predict_fkms (x, times = None, interval = "none", level = 0.95, type = "raw", seed = 1):
    """ Courbes moyennes des clusters et enveloppes de confiance ponctuelles
    (comme pour InfoMergeCluster) :
    - type = "raw" : covariables a la moyenne du cluster (courbes des donnees
      brutes, x$centers en R) ;
    - type = "regressed" : covariables a leur moyenne generale (courbes des
      donnees regressees). """
    if times is None:
        times = np.linspace(x.basis["lo"], x.basis["hi"], 200)
    times = np.asarray(times, dtype = float)
    St = fkms_basis_eval(x.basis, times)
    labs = list(x.beta.columns)
    out = pd.DataFrame({"time": times})
    for k, lab in enumerate(labs):
        if x.gamma is not None:
            if type == "raw":
                zk = x.data.loc[x.data["cluster"] == k + 1, x.z_names].to_numpy(float).mean(axis = 0)
            else:
                zk = x.z_mean_all
            Gm = np.hstack([St, np.tile(zk, (len(times), 1))])
            coef = np.concatenate([x.beta[lab].to_numpy(), x.gamma[lab].to_numpy()])
        else:
            Gm, coef = St, x.beta[lab].to_numpy()
        est = Gm @ coef
        out[lab] = est
        if interval == "none" or lab not in x.vcov:
            continue
        bande = BandFromVcov(Gm, est, x.vcov[lab], level)
        out[lab + "_lwr"] = bande["lower"]
        out[lab + "_upr"] = bande["upper"]
    return out


def plot_data_cluster (ax, x, max_subjects = 300, envelope = False, envelope_type = "confidence",
                       xlab = "Time (days)", ylab = "Weight", main = "FKMS : K = %d",
                       level = 0.95, show_data = True, legend = True, legend_pos = "upper left", seed = 1,
                       data_type = "raw"):
    """ plot.data.cluster adapte aux principes de plot_infomergecluster :
    trajectoires individuelles (couleur de leur cluster, transparentes,
    sous-echantillonnees au-dela de max_subjects), enveloppes facultatives,
    courbes moyennes ; legende « C_k : N_k (p %) » ; elements de chaque cluster
    memorises (legende interactive) ; donnees brutes ou regressees sur les
    covariables (data_type). """
    cols = _hcl_dark3(max(x.K, 2))[:x.K]
    labs = list(x.beta.columns)
    regressees = data_type == "regressed" and x.gamma is not None
    mc = predict_fkms(x, interval = "confidence" if envelope else "none", level = level,
                      type = "regressed" if regressees else "raw")
    ax.lignes_groupes = {k: [] for k in range(x.K)}
    if show_data:
        rng = np.random.default_rng(seed)
        montres = set(rng.choice(x.ids, max_subjects, replace = False)) if len(x.ids) > max_subjects else set(x.ids)
        d = donnees_regressees_fkms(x) if regressees else x.data
        colonne_y = "y_reg" if regressees else "y"
        d = d[d["id"].astype(str).isin(montres)]
        segments = {k: [] for k in range(x.K)}
        for ident, s in d.groupby(d["id"].astype(str), sort = False):
            k = int(s["cluster"].iloc[0]) - 1
            segments[k].append(s[["t", colonne_y]].to_numpy(dtype = float))
        for k, objets in tracer_trajectoires_groupees(ax, segments, cols).items():
            ax.lignes_groupes[k] += objets
    if envelope:
        for k, lab in enumerate(labs):
            if lab + "_lwr" not in mc:
                continue
            ax.lignes_groupes[k].append(ax.fill_between(mc["time"], mc[lab + "_lwr"], mc[lab + "_upr"], color = cols[k], alpha = 0.25, linewidth = 0))
            ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab + "_lwr"], color = cols[k], linestyle = "--", linewidth = 1)
            ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab + "_upr"], color = cols[k], linestyle = "--", linewidth = 1)
    for k, lab in enumerate(labs):
        ax.lignes_groupes[k] += ax.plot(mc["time"], mc[lab], color = cols[k], linewidth = 3,
                                        label = "%s : %d (%.0f%%)" % (lab, int(x.n_k[lab]), 100 * x.pi[lab]))   # comme InfoMergeCluster
    ax.set_xlim(x.basis["lo"], x.basis["hi"])
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)
    titre = main
    if "%" in main:                                # « K = %d », ou ancien format avec le MSE
        for valeurs in ((x.K,), (x.K, x.mse)):
            try:
                titre = main % valeurs
                break
            except (TypeError, ValueError):
                pass
    ax.set_title(titre + ("  —  regressed on covariates" if regressees else ""))
    if legend:
        titre_leg = "CE : %g%%" % (100 * level)             # niveau de confiance, toujours indique
        ax.legend(loc = legend_pos, frameon = False, title = titre_leg)
    return ax


def my_path(true_path):
    """ Chemin absolu d'une ressource (dossier ABOS). Application installee
    (PyInstaller) : ressources dans sys._MEIPASS (dossier _internal) ;
    sinon a cote de l'executable ou du script. """
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, true_path)



##------ Configuration de l'interface principale
SmartDigicat = tk.Tk()
SmartDigicat.geometry("1200x800")
SmartDigicat.title("AbosCluster v1.0")

##------ Chargement des icones
Run = PhotoImage(file = my_path('ABOS/run_p.png'))
Open = PhotoImage(file=my_path('ABOS/open_p.png'))
New = PhotoImage(file=my_path('ABOS/new_p.png'))
Save = PhotoImage(file=my_path('ABOS/save_p.png'))
Undo = PhotoImage(file=my_path('ABOS/undo_p.png'))
Redo = PhotoImage(file=my_path('ABOS/redo_p.png'))
Model = PhotoImage(file=my_path('ABOS/model_p.png'))
Log = PhotoImage(file=my_path('ABOS/log_p.png'))
Results = PhotoImage(file=my_path('ABOS/results_p.png'))
Help = PhotoImage(file=my_path('ABOS/help_p.png'))
Website = PhotoImage(file=my_path('ABOS/web_p.png'))
Analysis = PhotoImage(file=my_path('ABOS/new_analysis.png'))
Delete = PhotoImage(file=my_path('ABOS/delete.png'))
Restore = PhotoImage(file=my_path('ABOS/restore.png'))
Picture_save = PhotoImage(file=my_path('ABOS/picture_save.png'))
Csv_import = PhotoImage(file=my_path('ABOS/csv_import.png'))
Settings = PhotoImage(file=my_path('ABOS/settings.png'))
##data_p = PhotoImage(file='ABOS/data_p.png'))
data_import = PhotoImage(file=my_path('ABOS/import_p.png'))
my_data_edit_p = PhotoImage(file=my_path('ABOS/settings_p-32.png'))
img_smatdigicat = PhotoImage(file=my_path('ABOS/icon.png'))

Edit_data_p = PhotoImage(file=my_path('ABOS/Edit_data_p.png'))
Export_data_p = PhotoImage(file=my_path('ABOS/Export_data_p.png'))
Export_data_clin = PhotoImage(file=my_path('ABOS/Export_data_clin.png'))
view_stat = PhotoImage(file=my_path('ABOS/view_stat.png'))
rafraichir_graph = PhotoImage(file=my_path('ABOS/rafraichir_graph.png'))
save_graph_p = PhotoImage(file=my_path('ABOS/save_graph_p.png'))

arret = PhotoImage(file=my_path('ABOS/arret.png'))
langue = PhotoImage(file=my_path('ABOS/langue.png'))
Rename_model = PhotoImage(file=my_path('ABOS/Rename_model.png'))
try:                                   # icone de la fenetre et de la barre des taches
    SmartDigicat.iconphoto(True, img_smatdigicat)
except tk.TclError:
    pass



##=============================================================================
##  Import et edition des donnees (boutons "Import data" et "Edit data")
##=============================================================================

## Codes textuels traites comme valeurs manquantes (comparaison sans tenir compte de la casse)
CODES_MANQUANTS = ["", "NA", "N/A", "NaN", "NULL", ".", "--", "na", "n/a", "nan", "null"]
LARGEUR_COLONNE = 130              # largeur minimale d'une colonne du tableau (pixels)
EXTENSIONS_EXCEL = (".xlsx", ".xlsm", ".xls")

data = None                        # donnees brutes importees
data_analy = None                  # donnees editees (servent aux analyses)
panneau_courant = None             # panneau affiche dans Center_frame


def normaliser_manquants (df):
    """ Remplace par NaN les codes textuels de valeurs manquantes et retire les
    espaces en debut et fin de chaine ; convertit en nombre les colonnes
    textuelles entierement numeriques. """
    codes = {c.upper() for c in CODES_MANQUANTS}
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            serie = df[col].astype("object")
            masque_texte = serie.map(lambda v: isinstance(v, str))
            serie[masque_texte] = serie[masque_texte].str.strip()
            masque_na = serie.map(lambda v: isinstance(v, str) and v.upper() in codes)
            serie[masque_na] = np.nan
            n_valeurs = serie.notna().sum()
            numerique = pd.to_numeric(serie, errors = "coerce")
            if numerique.notna().sum() != n_valeurs:
                ## virgule decimale (ex. « 120,5 »)
                numerique = pd.to_numeric(serie.map(lambda v: v.replace(",", ".") if isinstance(v, str) else v), errors = "coerce")
            ## colonne numerique stockee en texte : conversion si aucune valeur n'est perdue
            if n_valeurs > 0 and numerique.notna().sum() == n_valeurs:
                df[col] = numerique
            else:
                df[col] = serie
    return df


def lire_un_fichier (chemin, feuilles = None):
    """ Lit un fichier CSV/texte (separateur detecte automatiquement) ou Excel.
    Pour un classeur Excel, 'feuilles' est la liste des feuilles a lire (None :
    toutes) ; les feuilles retenues sont empilees. Renvoie un DataFrame. """
    extension = os.path.splitext(chemin)[1].lower()
    if extension in EXTENSIONS_EXCEL:
        classeur = pd.read_excel(chemin, sheet_name = None, na_values = CODES_MANQUANTS, keep_default_na = True)
        noms = list(classeur) if feuilles is None else list(feuilles)
        if len(noms) == 0:
            raise ValueError("The Excel file does not contain any sheet.")
        tables = [classeur[n] for n in noms]
    else:
        tables = [pd.read_csv(chemin, sep = None, engine = "python", na_values = CODES_MANQUANTS, keep_default_na = True)]
    colonnes = list(tables[0].columns)
    for tab in tables[1:]:
        if list(tab.columns) != colonnes:
            raise ValueError("The selected sheets do not have the same columns.")
    return normaliser_manquants(pd.concat(tables, ignore_index = True))


def choisir_feuilles_excel (chemin):
    """ Fenetre de choix des feuilles d'un classeur Excel qui en contient
    plusieurs. Renvoie la liste des feuilles choisies, ou None si annule. """
    noms = pd.ExcelFile(chemin).sheet_names
    if len(noms) <= 1:
        return noms
    choix = {"feuilles": None}
    fenetre = tk.Toplevel(SmartDigicat)
    fenetre.title(traduire("Excel sheets"))
    fenetre.transient(SmartDigicat)
    fenetre.grab_set()
    Label(fenetre, text = "Select the sheets to import\n" + os.path.basename(chemin), font = ('arial', 14)).pack(padx = 15, pady = 10)
    liste = tk.Listbox(fenetre, selectmode = tk.MULTIPLE, exportselection = False, height = min(len(noms), 12), font = ('arial', 13))
    for n in noms:
        liste.insert(END, n)
    liste.selection_set(0, END)
    liste.pack(fill = BOTH, expand = True, padx = 15)

    def valider ():
        sel = [noms[i] for i in liste.curselection()]
        if len(sel) == 0:
            messagebox.showwarning("Excel sheets", "Select at least one sheet.", parent = fenetre)
            return
        choix["feuilles"] = sel
        fenetre.destroy()

    cadre = Frame(fenetre)
    cadre.pack(pady = 10)
    tk.Button(cadre, text = "Import", command = valider, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre, text = "Cancel", command = fenetre.destroy, width = 10).pack(side = LEFT, padx = 5)
    fenetre.wait_window()
    return choix["feuilles"]


def rendre_deplacable (boite):
    """ Boite de dialogue integree au panneau central, deplacable a la souris :
    on la saisit par son fond ou par ses textes (titres, consignes), puis on la
    fait glisser ; elle reste dans les limites du panneau. """
    if not boite.winfo_exists():
        return
    depart = {}

    def saisir (event):
        depart.update(x = event.x_root, y = event.y_root, bx = boite.winfo_x(), by = boite.winfo_y())

    def glisser (event):
        if not depart:
            return
        parent = boite.master
        nx = depart["bx"] + event.x_root - depart["x"]
        ny = depart["by"] + event.y_root - depart["y"]
        nx = max(0, min(nx, parent.winfo_width() - boite.winfo_width()))
        ny = max(0, min(ny, parent.winfo_height() - boite.winfo_height()))
        boite.place_configure(relx = 0, rely = 0, x = nx, y = ny, anchor = "nw")

    def lier (widget):
        if isinstance(widget, (tk.Frame, tk.Label)) and not isinstance(widget, Canvas):
            widget.bind("<ButtonPress-1>", saisir, add = "+")
            widget.bind("<B1-Motion>", glisser, add = "+")
            if isinstance(widget, tk.Label):
                widget.configure(cursor = "fleur")
            for enfant in widget.winfo_children():
                if not isinstance(enfant, Canvas):     # listes defilantes : pas de deplacement
                    lier(enfant)

    lier(boite)


def nouveau_panneau (parent):
    """ Detruit le panneau precedent et en cree un nouveau couvrant Center_frame. """
    global panneau_courant
    rappel_selection["fonction"] = None        # options du panneau precedent
    rappel_selection["axes"] = None
    if panneau_courant is not None and panneau_courant.winfo_exists():
        panneau_courant.destroy()
    panneau_courant = Frame(parent, background = "white")
    panneau_courant.place(relx = 0, rely = 0, relwidth = 1, relheight = 1)
    return panneau_courant


def afficher_tableau (parent, df, nb_lignes = None):
    """ Affiche un DataFrame dans un ttk.Treeview avec barres de defilement.
    Les valeurs manquantes sont affichees « NA ». """
    for w in parent.winfo_children():
        w.destroy()
    colonnes = [str(c) for c in df.columns]
    vue = df if nb_lignes is None else df.head(nb_lignes)
    tableau = ttk.Treeview(parent, columns = colonnes, show = "headings", selectmode = "extended")
    defil_y = ttk.Scrollbar(parent, orient = "vertical", command = tableau.yview)
    defil_x = ttk.Scrollbar(parent, orient = "horizontal", command = tableau.xview)
    tableau.configure(yscrollcommand = defil_y.set, xscrollcommand = defil_x.set)
    for c in colonnes:
        tableau.heading(c, text = c)
        tableau.column(c, width = LARGEUR_COLONNE, minwidth = LARGEUR_COLONNE, anchor = "center", stretch = False)

    def ajuster_colonnes (event = None):
        ## Largeur des colonnes adaptee au nombre de variables affichees :
        ## peu de colonnes -> elles se partagent toute la largeur du tableau ;
        ## beaucoup de colonnes -> largeur minimale et defilement horizontal.
        if len(colonnes) == 0:
            return
        largeur = max(LARGEUR_COLONNE, (tableau.winfo_width() - 4) // len(colonnes))
        for c in colonnes:
            tableau.column(c, width = largeur)

    tableau.bind("<Configure>", ajuster_colonnes)
    for ligne in vue.itertuples(index = False):
        tableau.insert("", "end", values = ["NA" if pd.isna(v) else v for v in ligne])
    tableau.grid(row = 0, column = 0, sticky = "nsew")
    defil_y.grid(row = 0, column = 1, sticky = "ns")
    defil_x.grid(row = 1, column = 0, sticky = "ew")
    parent.grid_rowconfigure(0, weight = 1)
    parent.grid_columnconfigure(0, weight = 1)
    return tableau


def import_data (parent):
    """ Bouton « Import data » : selection d'un ou plusieurs fichiers (CSV,
    texte, Excel), lecture, empilement s'ils ont les memes colonnes. Affiche
    ensuite, au centre de la fenetre, un message de reussite ou d'echec. """
    global data, data_analy, filtres, colonnes_categorielles, colonnes_double
    types = [("Data files", "*.csv *.txt *.xlsx *.xlsm *.xls"), ("CSV files", "*.csv"),
             ("Excel files", "*.xlsx *.xlsm *.xls"), ("Text files", "*.txt"), ("All", "*.*")]
    chemins = filedialog.askopenfilenames(title = "Import data", filetypes = types)
    succes = False
    if chemins:
        tables = []
        try:
            for chemin in chemins:
                sel = None
                if os.path.splitext(chemin)[1].lower() in EXTENSIONS_EXCEL:
                    sel = choisir_feuilles_excel(chemin)
                    if sel is None:       # choix des feuilles annule
                        tables = None
                        break
                tables.append(lire_un_fichier(chemin, sel))
            if tables:
                colonnes = list(tables[0].columns)
                if any(list(tab.columns) != colonnes for tab in tables[1:]):
                    raise ValueError("The selected files do not have the same columns.")
                data = pd.concat(tables, ignore_index = True)
                data_analy = data.copy()
                filtres = {}              # nouvelles donnees : filtres, conversions et graphiques reinitialises
                traces_graphiques.clear()
                type_courant["titre"] = None
                colonnes_categorielles = []
                colonnes_double = []
                succes = True
                historique_valider("Import data")
        except Exception as erreur:
            messagebox.showerror("Import data", "The file could not be read:\n" + str(erreur))

    ## Message au centre de la fenetre (meme presentation que SmartDigiCat)
    panneau = nouveau_panneau(parent)
    if succes:
        message = Label(panneau, text = "Data successfully loaded! \n You can carry out the desired analysis. \n (descriptive analyses or modeling)", font = ('Helvetica 18 bold italic'), fg = "gray20", background = "white")
    else:
        message = Label(panneau, text = "Please try again import failed", font = ('Helvetica 18 bold italic'), fg = "red", background = "white")
    message.place(relx = 0.3, rely = 0.3, relwidth = 0.4)


colonnes_categorielles = []        # colonnes traitees comme qualitatives (« Categorizing variables »)
colonnes_double = []               # colonnes converties en reels (« Convert to double »)
data_stat_all_exp = None           # dernier tableau « Overview stat » (pour « Export stat »)
panneau_stat = None                # panneau « Overview stat » affiche


def convertir_en_double (serie):
    """ Conversion numerique d'une colonne (virgule decimale acceptee) ;
    les valeurs non numeriques deviennent manquantes. """
    if pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie):
        return serie.astype(float)
    texte = serie.map(lambda v: v.strip().replace(",", ".") if isinstance(v, str) else v)
    return pd.to_numeric(texte, errors = "coerce").astype(float)


def choisir_conversions (mode, case_option):
    """ Options de « Convert variable », choisies dans le panneau avant
    l'affichage de la boite :
    - mode = "categorical" (« Categorizing variables ») : variables traitees
      comme qualitatives (codes) ;
    - mode = "double" (« Convert to double ») : variables converties en reels
      (quantitatives).
    La boite presente les variables en cases a cocher. Une meme variable ne
    peut etre a la fois categorisee et convertie en reel. """
    global colonnes_categorielles, colonnes_double
    categoriel = (mode == "categorical")
    if not case_option.get():
        ## option decochee : liste videe (les conversions deja faites restent
        ## dans les donnees : les colonnes converties restent reelles)
        if categoriel:
            colonnes_categorielles = []
        else:
            colonnes_double = []
        return
    noms = [str(c) for c in data_analy.columns]
    actuelles = colonnes_categorielles if categoriel else colonnes_double
    autres = colonnes_double if categoriel else colonnes_categorielles

    ## Boite integree au panneau central : centree, detruite avec le panneau, modale
    hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
    fenetre = Frame(hote, bd = 2, relief = "ridge")
    fenetre.place(relx = 0.5, rely = 0.5, anchor = "center")
    fenetre.after_idle(lambda: rendre_deplacable(fenetre))    # boite deplacable a la souris
    fenetre.lift()
    fenetre.grab_set()
    Label(fenetre, text = "Categorizing variables" if categoriel else "Convert to double",
          font = ('arial', 15, 'bold'), fg = "saddlebrown").pack(anchor = "w", padx = 15, pady = (10, 0))
    Label(fenetre, text = "Select the variables to treat as categorical" if categoriel else "Select the variables to convert to quantitative (double)",
          font = ('arial', 14)).pack(anchor = "w", padx = 15, pady = (0, 8))

    ## variables en cases a cocher, dans une zone defilante
    zone = Frame(fenetre, bd = 1, relief = "sunken")
    zone.pack(fill = BOTH, expand = True, padx = 15)
    toile = Canvas(zone, highlightthickness = 0, width = 300, height = min(max(len(noms), 5), 15) * 26)
    defil = ttk.Scrollbar(zone, orient = "vertical", command = toile.yview)
    toile.configure(yscrollcommand = defil.set)
    toile.pack(side = LEFT, fill = BOTH, expand = True)
    defil.pack(side = LEFT, fill = "y")
    interieur = Frame(toile)
    toile.create_window((0, 0), window = interieur, anchor = "nw")
    interieur.bind("<Configure>", lambda event: toile.configure(scrollregion = toile.bbox("all")))
    cases = {}
    for n in noms:
        cases[n] = BooleanVar(value = n in actuelles)
        Checkbutton(interieur, text = n, variable = cases[n], font = ('arial', 13), anchor = "w").pack(fill = "x", anchor = "w")
    molette = lambda event: toile.yview_scroll(-1 * (event.delta if abs(event.delta) < 10 else event.delta // 120), "units")
    zone.bind("<Enter>", lambda event: toile.bind_all("<MouseWheel>", molette))
    zone.bind("<Leave>", lambda event: toile.unbind_all("<MouseWheel>"))

    def fermer ():
        toile.unbind_all("<MouseWheel>")
        fenetre.destroy()

    def valider ():
        global colonnes_categorielles, colonnes_double, data_analy
        sel = [n for n in noms if cases[n].get()]
        communes = [n for n in sel if n in autres]
        if communes:
            messagebox.showwarning("Convert variable", "A variable cannot be both categorical and double:\n" + ", ".join(communes), parent = fenetre)
            return
        if categoriel:
            colonnes_categorielles = sel
        else:
            ## conversion en reels : valeurs non numeriques -> manquantes (confirmation)
            nouvelles = [n for n in sel if n not in colonnes_double]
            converties = {n: convertir_en_double(data_analy[n]) for n in nouvelles}
            pertes = {n: int(converties[n].isna().sum() - data_analy[n].isna().sum()) for n in nouvelles}
            pertes = {n: k for n, k in pertes.items() if k > 0}
            if pertes:
                detail = "\n".join(n + " : " + str(k) + " value(s)" for n, k in pertes.items())
                if not messagebox.askyesno("Convert variable", "Non-numeric values will be set to missing:\n" + detail + "\n\nContinue?", parent = fenetre):
                    return
            if converties:
                data_analy = data_analy.copy()
                for n, serie in converties.items():
                    data_analy[n] = serie
                    filtres.pop(n, None)      # le filtre d'une variable convertie n'est plus valide
                    if memoire_filtres.pop(n, None) is not None:
                        sauver_memoire_filtres()
            colonnes_double = sel
        if len(sel) == 0:
            case_option.set(False)
        fermer()
        historique_valider("Convert variable")

    def annuler ():
        if len(actuelles) == 0:
            case_option.set(False)
        fermer()

    cadre = Frame(fenetre)
    cadre.pack(pady = 10)
    tk.Button(cadre, text = "Save", command = valider, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre, text = "Cancel", command = annuler, width = 10).pack(side = LEFT, padx = 5)


##-----------------------------------------------------------------------------
##  « Filtering data » : filtrage des lignes selon une ou plusieurs variables
##-----------------------------------------------------------------------------
## filtres[colonne] = ("modalites", [modalites conservees])   variable qualitative ou entiere
##                  = ("intervalle", (min, max))              variable quantitative continue
filtres = {}                       # filtres actifs (case « Filtering data » cochee)
## derniers filtres enregistres : pre-remplissage de la boite « Filtering data »,
## meme apres avoir decoche la case ; conserves d'une session a l'autre
FICHIER_FILTRES = os.path.join(os.path.expanduser("~"), ".abos_filtres.json")
memoire_filtres = {}


def sauver_memoire_filtres ():
    try:
        with open(FICHIER_FILTRES, "w", encoding = "utf-8") as fichier:
            json.dump({c: [genre, list(valeur)] for c, (genre, valeur) in memoire_filtres.items()},
                      fichier, ensure_ascii = False, indent = 1)
    except (OSError, TypeError, ValueError):
        pass                                   # memorisation sur disque facultative


def charger_memoire_filtres ():
    try:
        with open(FICHIER_FILTRES, encoding = "utf-8") as fichier:
            contenu = json.load(fichier)
        for c, (genre, valeur) in contenu.items():
            memoire_filtres[c] = (genre, tuple(valeur) if genre == "intervalle" else list(valeur))
    except (OSError, ValueError, TypeError):
        pass


charger_memoire_filtres()


def cle_modalite (v):
    """ Libelle d'une modalite : les reels entiers (ex. 2.0) sont ecrits sans decimale. """
    if isinstance(v, (bool, np.bool_)):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def type_filtre (serie, nom):
    """ « modalites » pour une variable qualitative ou a valeurs entieres,
    « intervalle » pour une variable quantitative continue. """
    if nom in colonnes_double and pd.api.types.is_numeric_dtype(serie):
        return "intervalle"
    if nom in colonnes_categorielles or not pd.api.types.is_numeric_dtype(serie) or pd.api.types.is_bool_dtype(serie):
        return "modalites"
    x = serie.dropna().to_numpy(dtype = float)
    if pd.api.types.is_integer_dtype(serie) or (len(x) > 0 and np.all(np.mod(x, 1) == 0)):
        return "modalites"
    return "intervalle"


def appliquer_filtres (df, regles = None):
    """ Lignes de df satisfaisant toutes les regles de filtrage. Une ligne dont
    la variable filtree est manquante est exclue. """
    regles = filtres if regles is None else regles
    masque = pd.Series(True, index = df.index)
    for col, (genre, valeur) in regles.items():
        if col not in df.columns:
            continue
        if genre == "modalites":
            gardees = set(valeur)
            masque &= df[col].map(lambda v: (not pd.isna(v)) and cle_modalite(v) in gardees).astype(bool)
        else:
            mini, maxi = valeur
            masque &= pd.to_numeric(df[col], errors = "coerce").between(mini, maxi)
    return df[masque].reset_index(drop = True)


def choisir_filtres (case_cochee):
    """ « Filtering data » : choix des variables de filtrage, presentees comme
    dans « Categorizing variables ».
    - variable qualitative ou entiere : un second niveau affiche ses modalites,
      a selectionner (modalites conservees) ;
    - variable quantitative : un clic sur la variable ouvre une boite de
      dialogue ou l'on specifie le minimum et le maximum. """
    global filtres
    if not case_cochee.get():
        filtres = {}
        return
    noms = [str(c) for c in data_analy.columns]
    ## pre-remplissage : derniers filtres enregistres (colonnes presentes)
    provisoire = {k: v for k, v in (filtres or memoire_filtres).items() if k in noms}
    etat = {"variable": None, "cles": []}

    ## Boite integree au panneau central (et non fenetre separee) : centree sur
    ## le panneau courant, detruite avec lui, modale par capture locale (grab)
    hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
    fenetre = Frame(hote, bd = 2, relief = "ridge")
    fenetre.place(relx = 0.5, rely = 0.5, anchor = "center")
    fenetre.after_idle(lambda: rendre_deplacable(fenetre))    # boite deplacable a la souris
    fenetre.lift()
    fenetre.grab_set()
    entete = Frame(fenetre)
    entete.grid(row = 0, column = 0, columnspan = 2, padx = 15, pady = (10, 4), sticky = "w")
    Label(entete, text = "Filtering data", font = ('arial', 15, 'bold'), fg = "saddlebrown").pack(anchor = "w")
    Label(entete, text = "Select the variables used to filter the data", font = ('arial', 14)).pack(anchor = "w")
    Label(fenetre, text = "Quantitative variable: click on the variable to specify its min and max.\n"
                          "Qualitative or integer variable: click on the variable, then select the modalities to keep.",
          font = ('arial', 12), fg = "gray30", justify = "left").grid(row = 1, column = 0, columnspan = 2, padx = 15, pady = (0, 8), sticky = "w")

    ## --- Premier niveau : les variables
    cadre_var = Frame(fenetre)
    cadre_var.grid(row = 2, column = 0, sticky = "nsew", padx = (15, 8))
    Label(cadre_var, text = "Variables", font = ('arial', 13, 'bold')).pack(anchor = "w")
    liste_var = tk.Listbox(cadre_var, selectmode = tk.BROWSE, exportselection = False, height = min(max(len(noms), 5), 15), width = 28, font = ('arial', 13))
    defil_var = ttk.Scrollbar(cadre_var, orient = "vertical", command = liste_var.yview)
    liste_var.configure(yscrollcommand = defil_var.set)
    liste_var.pack(side = LEFT, fill = BOTH, expand = True)
    defil_var.pack(side = LEFT, fill = "y")
    for n in noms:
        liste_var.insert(END, n)

    ## --- Second niveau : les modalites de la variable choisie
    cadre_mod = Frame(fenetre)
    titre_mod = Label(cadre_mod, text = "", font = ('arial', 13, 'bold'))
    titre_mod.pack(anchor = "w")
    zone_mod = Frame(cadre_mod)
    zone_mod.pack(fill = BOTH, expand = True)
    liste_mod = tk.Listbox(zone_mod, selectmode = tk.MULTIPLE, exportselection = False, height = 12, width = 28, font = ('arial', 13))
    defil_mod = ttk.Scrollbar(zone_mod, orient = "vertical", command = liste_mod.yview)
    liste_mod.configure(yscrollcommand = defil_mod.set)
    liste_mod.pack(side = LEFT, fill = BOTH, expand = True)
    defil_mod.pack(side = LEFT, fill = "y")
    boutons_mod = Frame(cadre_mod)
    boutons_mod.pack(pady = (4, 0))

    ## --- Resume des filtres
    resume = Label(fenetre, text = "", font = ('arial', 12), fg = "saddlebrown", justify = "left", anchor = "w")
    resume.grid(row = 3, column = 0, columnspan = 2, padx = 15, pady = (8, 0), sticky = "ew")
    fenetre.grid_columnconfigure(0, weight = 1)
    fenetre.grid_columnconfigure(1, weight = 1)
    fenetre.grid_rowconfigure(2, weight = 1)

    def rafraichir ():
        for i, n in enumerate(noms):
            liste_var.itemconfig(i, foreground = "saddlebrown" if n in provisoire else "gray20")
        lignes = []
        for n, (genre, valeur) in provisoire.items():
            if genre == "modalites":
                lignes.append(n + " :  " + str(len(valeur)) + " modality(ies) kept")
            else:
                lignes.append(n + " :  " + formater_valeur_stat(valeur[0]) + "  ≤  x  ≤  " + formater_valeur_stat(valeur[1]))
        n_gardees = len(appliquer_filtres(data_analy, provisoire))
        resume.configure(text = ("Filters:\n  " + "\n  ".join(lignes) + "\n" if lignes else "No filter.\n")
                                + "Rows kept: " + str(n_gardees) + " / " + str(len(data_analy)))

    def modalites_de (nom):
        """ Modalites observees (libelle, effectif), triees. """
        effectifs = {}
        for v in data_analy[nom].dropna():
            c = cle_modalite(v)
            effectifs[c] = effectifs.get(c, 0) + 1
        def ordre (c):
            try:
                return (0, float(c), "")
            except ValueError:
                return (1, 0.0, c)
        return [(c, effectifs[c]) for c in sorted(effectifs, key = ordre)]

    def afficher_modalites (nom):
        etat["variable"] = nom
        mods = modalites_de(nom)
        etat["cles"] = [c for c, _ in mods]
        titre_mod.configure(text = "Modalities of " + nom)
        liste_mod.delete(0, END)
        gardees = provisoire[nom][1] if nom in provisoire else []      # par defaut : aucune modalite cochee
        for c, k in mods:
            liste_mod.insert(END, c + "   (n = " + str(k) + ")")
            if c in gardees:
                liste_mod.selection_set(END)
        cadre_mod.grid(row = 2, column = 1, sticky = "nsew", padx = (8, 15))

    def maj_modalites (event = None):
        nom = etat["variable"]
        if nom is None:
            return
        sel = [etat["cles"][i] for i in liste_mod.curselection()]
        if len(sel) == 0:
            provisoire.pop(nom, None)          # aucune modalite cochee : pas de filtre sur cette variable
        else:
            provisoire[nom] = ("modalites", sel)
        rafraichir()

    def tout_selectionner (valeur):
        if valeur:
            liste_mod.selection_set(0, END)
        else:
            liste_mod.selection_clear(0, END)
        maj_modalites()

    tk.Button(boutons_mod, text = "Select all", command = lambda: tout_selectionner(True), width = 10).pack(side = LEFT, padx = 3)
    tk.Button(boutons_mod, text = "Clear", command = lambda: tout_selectionner(False), width = 10).pack(side = LEFT, padx = 3)
    liste_mod.bind("<<ListboxSelect>>", maj_modalites)

    def demander_intervalle (nom):
        """ Boite de dialogue : minimum et maximum d'une variable quantitative. """
        x = pd.to_numeric(data_analy[nom], errors = "coerce").dropna()
        if len(x) == 0:
            messagebox.showwarning("Filtering data", "The variable " + nom + " has no observed value.", parent = fenetre)
            return
        obs_min, obs_max = float(x.min()), float(x.max())
        mini_actuel, maxi_actuel = provisoire[nom][1] if nom in provisoire else (obs_min, obs_max)
        ## boite min / max, elle aussi dans le panneau central, au-dessus de la boite de filtrage
        boite = Frame(hote, bd = 2, relief = "ridge")
        boite.place(relx = 0.5, rely = 0.5, anchor = "center")
        boite.after_idle(lambda: rendre_deplacable(boite))    # boite deplacable a la souris
        boite.lift()
        boite.grab_set()
        Label(boite, text = nom, font = ('arial', 14, 'bold')).grid(row = 0, column = 0, columnspan = 2, padx = 15, pady = (12, 2))
        Label(boite, text = "Observed range: [" + formater_valeur_stat(obs_min) + " ; " + formater_valeur_stat(obs_max) + "]",
              font = ('arial', 12), fg = "gray30").grid(row = 1, column = 0, columnspan = 2, padx = 15, pady = (0, 10))
        var_min = StringVar(value = formater_valeur_stat(mini_actuel))
        var_max = StringVar(value = formater_valeur_stat(maxi_actuel))
        Label(boite, text = "Min", font = ('arial', 13)).grid(row = 2, column = 0, sticky = "e", padx = (15, 6), pady = 3)
        entree_min = Entry(boite, textvariable = var_min, width = 14)
        entree_min.bind("<Return>", lambda event: enregistrer())
        entree_min.grid(row = 2, column = 1, sticky = "w", padx = (0, 15), pady = 3)
        Label(boite, text = "Max", font = ('arial', 13)).grid(row = 3, column = 0, sticky = "e", padx = (15, 6), pady = 3)
        entree_max = Entry(boite, textvariable = var_max, width = 14)
        entree_max.grid(row = 3, column = 1, sticky = "w", padx = (0, 15), pady = 3)
        entree_max.bind("<Return>", lambda event: enregistrer())
        entree_min.focus_set()

        def fermer ():
            boite.destroy()
            if fenetre.winfo_exists():
                fenetre.grab_set()

        def enregistrer ():
            try:
                mini = float(var_min.get().strip().replace(",", "."))
                maxi = float(var_max.get().strip().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Filtering data", "Please enter numeric values for min and max.", parent = boite)
                return
            if mini > maxi:
                messagebox.showwarning("Filtering data", "The min must be lower than or equal to the max.", parent = boite)
                return
            if mini <= obs_min and maxi >= obs_max:
                provisoire.pop(nom, None)      # intervalle couvrant toutes les valeurs : pas de restriction
            else:
                provisoire[nom] = ("intervalle", (mini, maxi))
            rafraichir()
            fermer()

        def retirer ():
            provisoire.pop(nom, None)
            rafraichir()
            fermer()

        cadre = Frame(boite)
        cadre.grid(row = 4, column = 0, columnspan = 2, pady = 12)
        tk.Button(cadre, text = "Save", command = enregistrer, width = 10).pack(side = LEFT, padx = 4)
        tk.Button(cadre, text = "Remove filter", command = retirer, width = 12).pack(side = LEFT, padx = 4)
        tk.Button(cadre, text = "Cancel", command = fermer, width = 10).pack(side = LEFT, padx = 4)

    def clic_variable (event):
        i = liste_var.nearest(event.y)
        boite_i = liste_var.bbox(i)
        if i < 0 or not boite_i or not (boite_i[1] <= event.y <= boite_i[1] + boite_i[3]):
            return
        nom = noms[i]
        if type_filtre(data_analy[nom], nom) == "modalites":
            afficher_modalites(nom)
        else:
            etat["variable"] = None
            cadre_mod.grid_remove()
            demander_intervalle(nom)

    liste_var.bind("<ButtonRelease-1>", clic_variable)

    def valider ():
        global filtres
        vides = [n for n, (genre, valeur) in provisoire.items() if genre == "modalites" and len(valeur) == 0]
        if vides:
            messagebox.showwarning("Filtering data", "Select at least one modality for: " + ", ".join(vides), parent = fenetre)
            return
        filtres = dict(provisoire)
        memoire_filtres.clear()                       # memorises pour le prochain remplissage
        memoire_filtres.update(provisoire)
        sauver_memoire_filtres()
        if len(filtres) == 0:
            case_cochee.set(False)
        fenetre.destroy()
        historique_valider("Filtering data")

    def annuler ():
        if len(filtres) == 0:
            case_cochee.set(False)
        fenetre.destroy()

    cadre = Frame(fenetre)
    cadre.grid(row = 4, column = 0, columnspan = 2, pady = 10)
    tk.Button(cadre, text = "Save", command = valider, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre, text = "Cancel", command = annuler, width = 10).pack(side = LEFT, padx = 5)
    rafraichir()


def table_stat (df):
    """ Tableau « Overview stat » : pour chaque colonne, type, nombre de
    modalites, valeurs manquantes, N et moyenne (ecart-type) pour une variable
    quantitative, ou effectif et pourcentage de chaque modalite pour une
    variable qualitative. """
    lignes = []
    n_total = len(df)
    for col in df.columns:
        x = df[col]
        manquants = int(x.isna().sum())
        quantitative = pd.api.types.is_numeric_dtype(x) and not pd.api.types.is_bool_dtype(x) and str(col) not in colonnes_categorielles
        if quantitative:
            entier = pd.api.types.is_integer_dtype(x)
            d = 1 if entier else 2
            moyenne = "" if x.notna().sum() == 0 else str(round(float(x.mean()), d)) + " (" + str(round(float(x.std()), d)) + ")"
            lignes.append({"Characteristics": str(col), "Type": "integer" if entier else "double", "Unique": "", "Modality": "",
                           "Missing": manquants, "N": n_total, "mean (SD) / (%)": moyenne})
        else:
            effectifs = x.dropna().astype(str).value_counts().sort_index()
            lignes.append({"Characteristics": str(col), "Type": "categorical" if str(col) in colonnes_categorielles else "character",
                           "Unique": len(effectifs), "Modality": "", "Missing": manquants, "N": n_total, "mean (SD) / (%)": ""})
            for modalite, n in effectifs.items():
                lignes.append({"Characteristics": "", "Type": "", "Unique": "", "Modality": modalite, "Missing": "",
                               "N": int(n), "mean (SD) / (%)": str(round(100 * n / n_total, 2)) + "%"})
    return pd.DataFrame(lignes)


def lignes_groupe_overview (tableau):
    """ Indices des lignes de titre des variables qualitatives (mises en evidence). """
    return [i for i, (nom, typ) in enumerate(zip(tableau["Characteristics"].astype(str), tableau["Type"].astype(str)))
            if nom.strip() != "" and typ not in ("double", "integer")]


def formater_valeur_stat (valeur):
    """ Texte d'une cellule : entiers sans decimales, reels a 3 decimales au plus. """
    if valeur is None or (isinstance(valeur, float) and not np.isfinite(valeur)):
        return ""
    if isinstance(valeur, (int, np.integer)):
        return str(int(valeur))
    if isinstance(valeur, (float, np.floating)):
        return str(int(valeur)) if float(valeur).is_integer() else ("%.3f" % valeur).rstrip("0").rstrip(".")
    return str(valeur)


def afficher_tableau_stat (parent, tableau, titre, lignes_groupe):
    """ Tableau de statistiques : titre, en-tete, lignes alternees, lignes de
    variable qualitative mises en evidence, barres de defilement. """
    style = ttk.Style()
    style.configure("Stat.Treeview", font = ('arial', 12), rowheight = 26, background = "white", fieldbackground = "white", foreground = "gray15")
    style.configure("Stat.Treeview.Heading", font = ('arial', 12, 'bold'), foreground = "gray15")
    cadre = Frame(parent, background = "white")
    cadre.grid_columnconfigure(0, weight = 1)
    cadre.grid_rowconfigure(1, weight = 1)
    if titre:
        Label(cadre, text = titre, font = ('arial', 16, 'bold'), fg = "gray20", bg = "white", anchor = "w").grid(row = 0, column = 0, columnspan = 2, sticky = "ew", padx = 10, pady = (8, 4))
    ids = ["c%d" % i for i in range(len(tableau.columns))]
    arbre = ttk.Treeview(cadre, columns = ids, show = "headings", style = "Stat.Treeview", selectmode = "browse")
    dy = ttk.Scrollbar(cadre, orient = "vertical", command = arbre.yview)
    dx = ttk.Scrollbar(cadre, orient = "horizontal", command = arbre.xview)
    arbre.configure(yscrollcommand = dy.set, xscrollcommand = dx.set)
    arbre.grid(row = 1, column = 0, sticky = "nsew", padx = (10, 0))
    dy.grid(row = 1, column = 1, sticky = "ns")
    dx.grid(row = 2, column = 0, sticky = "ew", padx = (10, 0), pady = (0, 6))
    valeurs = [[formater_valeur_stat(v) for v in ligne] for ligne in tableau.itertuples(index = False, name = None)]
    for k, (i, nom) in enumerate(zip(ids, tableau.columns)):
        largeur = max([len(str(nom))] + [len(l[k]) for l in valeurs[:300]]) * 9 + 30
        arbre.heading(i, text = str(nom), anchor = "w" if k == 0 else "center")
        arbre.column(i, width = min(max(largeur, 80), 420), stretch = False, anchor = "w" if k == 0 else "center")
    arbre.tag_configure("pair", background = "white")
    arbre.tag_configure("impair", background = "#f3f5f7")
    arbre.tag_configure("groupe", background = "#e2ebf4", font = ('arial', 12, 'bold'))
    groupes = set(lignes_groupe)
    for k, ligne in enumerate(valeurs):
        arbre.insert("", "end", values = ligne, tags = ("groupe" if k in groupes else ("impair" if k % 2 else "pair"),))
    return cadre


def stat_data_all (parent, df):
    """ « Overview stat » : tableau recapitulatif de toutes les colonnes. """
    global data_stat_all_exp, panneau_stat
    if panneau_stat is not None and panneau_stat.winfo_exists():
        panneau_stat.destroy()
    panneau_stat = Frame(parent, background = 'gray90')
    panneau_stat.place(relx = 0, rely = 0, relwidth = 0.8, relheight = 1)
    donnees = df.reset_index(drop = True)
    if donnees.shape[0] == 0 or donnees.shape[1] == 0:
        data_stat_all_exp = None
        Label(panneau_stat, text = "The table is empty.", font = ('arial', 18), fg = "red", background = "gray80").place(relx = 0.1, rely = 0.35, relwidth = 0.8)
        return
    data_stat_all_exp = table_stat(donnees)
    cadre = afficher_tableau_stat(panneau_stat, data_stat_all_exp, "", lignes_groupe_overview(data_stat_all_exp))
    cadre.place(relx = 0.005, rely = 0.02, relwidth = 0.99, relheight = 0.96)


def exporter_stat_overview ():
    """ « Export stat » : exporte le tableau de « Overview stat » (Excel, Word ou CSV). """
    if data_stat_all_exp is None:
        messagebox.showwarning("Export stat", "Please display the statistics first (button 'Overview stat').")
        return
    chemin = filedialog.asksaveasfilename(title = "Export stat", filetypes = [("Excel file", "*.xlsx"), ("Word file", "*.docx"), ("csv file", "*.csv")], defaultextension = ".xlsx")
    if not chemin:
        return
    titre = "Overview of the data"
    tableau = data_stat_all_exp
    groupes = lignes_groupe_overview(tableau)
    extension = os.path.splitext(chemin)[1].lower()
    try:
        if extension == ".csv":
            with open(chemin, "w", encoding = "utf-8-sig", newline = "") as fichier:
                fichier.write(titre + "\n")
                tableau.to_csv(fichier, sep = ";", index = False)
        elif extension == ".docx":
            from docx import Document                    # python-docx, requis pour l'export Word
            from docx.shared import Pt
            document = Document()
            document.add_heading(titre, level = 2)
            table = document.add_table(rows = 1, cols = tableau.shape[1])
            table.style = "Table Grid"
            for cellule, nom in zip(table.rows[0].cells, tableau.columns):
                cellule.text = str(nom)
                cellule.paragraphs[0].runs[0].font.bold = True
            for k, ligne in enumerate(tableau.itertuples(index = False, name = None)):
                for cellule, valeur in zip(table.add_row().cells, ligne):
                    cellule.text = formater_valeur_stat(valeur)
                    if k in groupes and cellule.paragraphs[0].runs:
                        cellule.paragraphs[0].runs[0].font.bold = True
            for ligne_table in table.rows:
                for cellule in ligne_table.cells:
                    for paragraphe in cellule.paragraphs:
                        for morceau in paragraphe.runs:
                            morceau.font.size = Pt(9)
            document.save(chemin)
        else:
            from openpyxl.styles import Font, PatternFill, Alignment
            if extension != ".xlsx":
                chemin += ".xlsx"
            with pd.ExcelWriter(chemin, engine = "openpyxl") as fichier:
                tableau.to_excel(fichier, sheet_name = "Overview", index = False, startrow = 2)
                feuille = fichier.sheets["Overview"]
                feuille.cell(row = 1, column = 1, value = titre).font = Font(bold = True, size = 13)
                for cellule in feuille[3]:
                    cellule.font = Font(bold = True)
                    cellule.fill = PatternFill("solid", fgColor = "DDDDDD")
                    cellule.alignment = Alignment(horizontal = "center")
                for k in groupes:
                    for cellule in feuille[4 + k]:
                        cellule.font = Font(bold = True)
                        cellule.fill = PatternFill("solid", fgColor = "E2EBF4")
    except Exception as erreur:
        messagebox.showerror("Export stat", "The table could not be exported:\n" + str(erreur))
        return
    messagebox.showinfo("Export stat", "Table exported to:\n" + chemin)


def my_exporting_data (df):
    """ « Export clean » : exporte les donnees editees en CSV (separateur ;). """
    chemin = filedialog.asksaveasfilename(title = "Export clean", filetypes = [("csv file", "*.csv")], defaultextension = ".csv")
    if not chemin:
        return
    try:
        df.to_csv(chemin, sep = ";", index = False, decimal = ".")
    except Exception as erreur:
        messagebox.showerror("Export clean", "The data could not be exported:\n" + str(erreur))


def edit_data (parent):
    """ Bouton « Edit data » : meme disposition et memes fonctions que le
    panneau « Edit data » de SmartDigiCat. Partie haute : imputation des
    valeurs manquantes, recherche et changement de modalite, renommage d'une
    colonne, colonnes et lignes a afficher.
    Partie basse : tableau des donnees et boutons « Overview stat »,
    « Export stat » et « Export clean ». """
    global data_analy
    if data is None:
        panneau = nouveau_panneau(parent)
        Label(panneau, text = "Please load data to be analyzed", font = ('Helvetica 16 bold italic'), fg = "red", background = "white").place(relx = 0, rely = 0, relwidth = 1, relheight = 1)
        return

    panneau = nouveau_panneau(parent)
    height_window = Canvas(panneau, relief = GROOVE, background = 'white', highlightthickness = 0)
    low_window = Canvas(panneau, relief = GROOVE, background = 'gray90', highlightthickness = 0)
    height_window.place(relx = 0, rely = 0, relwidth = 1, relheight = 0.6)
    low_window.place(relx = 0, rely = 0.6, relwidth = 1, relheight = 0.4)
    cadre_tableau = Frame(low_window, background = "white")
    cadre_tableau.place(relx = 0, rely = 0, relwidth = 0.8, relheight = 1)

    titre = dict(font = ('arial', 15), fg = "saddlebrown", bg = "white")
    noms = [str(c) for c in data_analy.columns]
    entete_tout = ["Select column name"] + noms

    ## --- Trois panneaux de meme largeur, separes par des traits verticaux
    panneaux = []
    for relx in (0.015, 0.348, 0.681):
        cadre = Frame(height_window, background = "white")
        cadre.place(relx = relx, rely = 0.04, relwidth = 0.304, relheight = 0.82)
        cadre.grid_columnconfigure(0, weight = 1)
        panneaux.append(cadre)
    p1, p2, p3 = panneaux
    for relx in (0.3325, 0.6655):
        tk.Frame(height_window, bd = 10, relief = 'sunken', width = 4).place(relx = relx, rely = 0.04, relheight = 0.82)
    etiquette = dict(font = ('arial', 14), fg = "gray30", background = "white", anchor = "w")
    marge = dict(sticky = "ew", padx = 12)

    ## --- Panneau 1 : imputation des valeurs manquantes
    ## « Missing value imputation » : case a cocher qui ouvre une boite de dialogue
    ## (colonne, methode quantitative, methode qualitative) ; les choix enregistres
    ## sont appliques au clic sur « View & Edit »
    list_quanti = ["select method", "mean", "median", "delete"]
    list_quali = ["select method", "modality reference", "delete"]
    imputation = {"colonne": None, "quanti": "select method", "quali": "select method"}   # None : toutes les colonnes
    imputation_def = BooleanVar(value = False)

    def type_colonne (c):
        ## meme typologie que « Overview stat »
        if str(c) in colonnes_categorielles:
            return "categorical"
        if pd.api.types.is_numeric_dtype(data_analy[c]) and not pd.api.types.is_bool_dtype(data_analy[c]):
            return "integer" if pd.api.types.is_integer_dtype(data_analy[c]) else "double"
        return "character"

    def choisir_imputation ():
        if not imputation_def.get():
            ## case decochee : aucune imputation
            imputation.update(colonne = None, quanti = "select method", quali = "select method")
            return
        hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
        boite = nouvelle_boite(hote)
        Label(boite, text = "Missing value imputation", font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(
            row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 0))
        Label(boite, text = "Select the column and the methods used to treat its missing values", font = ('arial', 13)).grid(
            row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 8))
        ## colonnes : type et nombre de valeurs manquantes entre parentheses
        manquants = data_analy.isna().sum()
        choix_colonnes = [None] + [str(c) for c in data_analy.columns]
        libelles = ["All columns (" + str(int(manquants.sum())) + " NA)"] + \
                   [str(c) + "  (" + type_colonne(c) + ", " + str(int(manquants[c])) + " NA)" for c in data_analy.columns]
        Label(boite, text = "Column", **ETIQUETTE_BOITE).grid(row = 2, column = 0, sticky = "w", padx = (15, 6), pady = 3)
        choix_colonne = ttk.Combobox(boite, values = libelles, state = "readonly", width = 34)
        choix_colonne.grid(row = 2, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
        choix_colonne.current(choix_colonnes.index(imputation["colonne"]) if imputation["colonne"] in choix_colonnes else 0)
        Label(boite, text = "Quantitative", **ETIQUETTE_BOITE).grid(row = 3, column = 0, sticky = "w", padx = (15, 6), pady = 3)
        choix_quanti = ttk.Combobox(boite, values = list_quanti, state = "readonly", width = 34)
        choix_quanti.grid(row = 3, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
        choix_quanti.set(imputation["quanti"])
        Label(boite, text = "Qualitative", **ETIQUETTE_BOITE).grid(row = 4, column = 0, sticky = "w", padx = (15, 6), pady = 3)
        choix_quali = ttk.Combobox(boite, values = list_quali, state = "readonly", width = 34)
        choix_quali.grid(row = 4, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
        choix_quali.set(imputation["quali"])
        Label(boite, text = "Applied when you click on « View & Edit »", **AIDE_BOITE).grid(
            row = 5, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (4, 0))
        boite.grid_columnconfigure(1, weight = 1)

        def enregistrer ():
            imputation.update(colonne = choix_colonnes[choix_colonne.current()], quanti = choix_quanti.get(), quali = choix_quali.get())
            if imputation["quanti"] == "select method" and imputation["quali"] == "select method":
                imputation_def.set(False)          # aucune methode choisie : case decochee
            boite.destroy()

        def annuler ():
            if imputation["quanti"] == "select method" and imputation["quali"] == "select method":
                imputation_def.set(False)
            boite.destroy()

        cadre_b = Frame(boite)
        cadre_b.grid(row = 6, column = 0, columnspan = 2, pady = 10)
        tk.Button(cadre_b, text = "Save", command = enregistrer, width = 10).pack(side = LEFT, padx = 5)
        tk.Button(cadre_b, text = "Cancel", command = annuler, width = 10).pack(side = LEFT, padx = 5)

    Checkbutton(p1, text = "Missing value imputation", variable = imputation_def, command = choisir_imputation, fg = "saddlebrown", font = ('arial', 14), background = 'white', anchor = "w").grid(row = 0, column = 0, pady = (30, 10), **marge)
    ## « Convert variable » : on choisit l'option dans le panneau (cases en retrait),
    ## puis la boite des variables s'affiche
    conversion_def = BooleanVar(value = len(colonnes_categorielles) > 0 or len(colonnes_double) > 0)
    categorial_var_def = BooleanVar(value = len(colonnes_categorielles) > 0)
    double_var_def = BooleanVar(value = len(colonnes_double) > 0)
    case_cat = Checkbutton(p1, text = "Categorizing variables", variable = categorial_var_def, command = lambda: choisir_conversions("categorical", categorial_var_def), fg = "gray30", font = ('arial', 13), background = 'white', anchor = "w")
    case_dbl = Checkbutton(p1, text = "Convert to double", variable = double_var_def, command = lambda: choisir_conversions("double", double_var_def), fg = "gray30", font = ('arial', 13), background = 'white', anchor = "w")

    def afficher_options_conversion ():
        global colonnes_categorielles, colonnes_double
        if conversion_def.get():
            case_cat.grid(row = 2, column = 0, sticky = "ew", padx = (34, 12))
            case_dbl.grid(row = 3, column = 0, sticky = "ew", padx = (34, 12))
        else:
            ## « Convert variable » decoche : options masquees et listes videes
            case_cat.grid_remove()
            case_dbl.grid_remove()
            categorial_var_def.set(False)
            double_var_def.set(False)
            colonnes_categorielles = []
            colonnes_double = []
            historique_valider("Convert variable")

    Checkbutton(p1, text = "Convert variable", variable = conversion_def, command = afficher_options_conversion, fg = "saddlebrown", font = ('arial', 14), background = 'white', anchor = "w").grid(row = 1, column = 0, pady = (10, 10), **marge)
    if conversion_def.get():
        afficher_options_conversion()
    filtrage_def = BooleanVar(value = len(filtres) > 0)
    Checkbutton(p1, text = "Filtering data", variable = filtrage_def, command = lambda: choisir_filtres(filtrage_def), fg = "saddlebrown", font = ('arial', 14), background = 'white', anchor = "w").grid(row = 4, column = 0, pady = (10, 10), **marge)

    ## --- Panneau 2 : changement de modalite et renommage d'une colonne
    Label(p2, text = "Search & change modality", anchor = "w", **titre).grid(row = 0, column = 0, pady = (0, 10), **marge)
    Label(p2, text = "Characteristic", **etiquette).grid(row = 1, column = 0, **marge)
    modality_edit = ttk.Combobox(p2, values = entete_tout, state = "readonly")
    modality_edit.grid(row = 2, column = 0, pady = (2, 6), **marge)
    modality_edit.current(0)
    Label(p2, text = "Search", **etiquette).grid(row = 3, column = 0, **marge)
    ancienne_mod = StringVar(value = "old modality")
    Entry(p2, textvariable = ancienne_mod).grid(row = 4, column = 0, pady = (2, 6), **marge)
    Label(p2, text = "Replace", **etiquette).grid(row = 5, column = 0, **marge)
    nouvelle_mod = StringVar(value = "new modality")
    Entry(p2, textvariable = nouvelle_mod).grid(row = 6, column = 0, pady = (2, 14), **marge)
    Label(p2, text = "Rename column", anchor = "w", **titre).grid(row = 7, column = 0, pady = (0, 6), **marge)
    rename_columns = ttk.Combobox(p2, values = entete_tout, state = "readonly")
    rename_columns.grid(row = 8, column = 0, pady = (0, 6), **marge)
    rename_columns.current(0)
    nouveau_nom = StringVar(value = "Enter new name column")
    Entry(p2, textvariable = nouveau_nom).grid(row = 9, column = 0, **marge)

    ## --- Panneau 3 : colonnes et lignes a afficher
    Label(p3, text = "Parameters for overview", anchor = "w", **titre).grid(row = 0, column = 0, columnspan = 3, pady = (0, 10), **marge)
    Label(p3, text = "Select the columns to display", **etiquette).grid(row = 1, column = 0, columnspan = 3, **marge)
    ## variables en cases a cocher, dans une zone defilante
    zone_col = Frame(p3, bd = 1, relief = GROOVE, background = "white")
    zone_col.grid(row = 2, column = 0, columnspan = 3, pady = (2, 10), sticky = "nsew", padx = 12)
    p3.grid_rowconfigure(2, weight = 1)
    toile_col = Canvas(zone_col, highlightthickness = 0, background = "white", height = 120)
    defil_col = ttk.Scrollbar(zone_col, orient = "vertical", command = toile_col.yview)
    toile_col.configure(yscrollcommand = defil_col.set)
    toile_col.pack(side = LEFT, fill = BOTH, expand = True)
    defil_col.pack(side = LEFT, fill = "y")
    interieur_col = Frame(toile_col, background = "white")
    fenetre_col = toile_col.create_window((0, 0), window = interieur_col, anchor = "nw")
    interieur_col.bind("<Configure>", lambda event: toile_col.configure(scrollregion = toile_col.bbox("all")))
    toile_col.bind("<Configure>", lambda event: toile_col.itemconfigure(fenetre_col, width = event.width))
    molette_col = lambda event: toile_col.yview_scroll(-1 * (event.delta if abs(event.delta) < 10 else event.delta // 120), "units")
    zone_col.bind("<Enter>", lambda event: toile_col.bind_all("<MouseWheel>", molette_col))
    zone_col.bind("<Leave>", lambda event: toile_col.unbind_all("<MouseWheel>"))
    cases_colonnes = []                    # [(nom, BooleanVar)] dans l'ordre des colonnes

    def remplir_colonnes (liste_noms, cochees = ()):
        for w in interieur_col.winfo_children():
            w.destroy()
        cases_colonnes.clear()
        for n in liste_noms:
            v = BooleanVar(value = n in cochees)
            Checkbutton(interieur_col, text = n, variable = v, fg = "gray30", font = ('arial', 12), background = "white", anchor = "w").pack(fill = "x", anchor = "w")
            cases_colonnes.append((n, v))

    def colonnes_cochees ():
        return [n for n, v in cases_colonnes if v.get()]

    remplir_colonnes(noms)
    Label(p3, text = "Lines to display", **etiquette).grid(row = 3, column = 0, sticky = "w", padx = (12, 6))
    row_edit_value_default = DoubleVar(value = len(data_analy))
    Spinbox(p3, from_ = 1, to = 1000000, increment = 1, textvariable = row_edit_value_default, width = 9).grid(row = 3, column = 1, sticky = "w")
    all_columns_def = BooleanVar(value = False)
    Checkbutton(p3, text = "All rows", variable = all_columns_def, fg = "gray30", font = ('arial', 14), background = 'white').grid(row = 3, column = 2, sticky = "e", padx = (6, 12))

    ## --- Messages, sous chaque panneau
    rapport_missing_value_all = Label(height_window, text = "", font = ('arial', 14), fg = "gray20", bg = "white")
    rapport_missing_value_all.place(relx = 0, rely = 0.93, relwidth = 0.304)
    change_modality = Label(height_window, text = "", font = ('arial', 14), fg = "gray20", bg = "white")
    change_modality.place(relx = 0.348, rely = 0.93, relwidth = 0.304)
    view_info_data_all = Label(height_window, text = "", font = ('arial', 14), fg = "gray20", bg = "white")
    view_info_data_all.place(relx = 0.3, rely = 0.93, relwidth = 0.304)

    def Edit_data_all ():
        """ « View & Edit » : applique les modifications et affiche le tableau. """
        global data_analy, panneau_stat
        avant = data_analy
        df = data_analy.copy()
        ## renommage d'une colonne
        if rename_columns.current() != 0 and nouveau_nom.get() not in ("Enter new name column", ""):
            ancien = entete_tout[rename_columns.current()]
            df = df.rename(columns = {ancien: nouveau_nom.get()})
            if imputation["colonne"] == ancien:   # la colonne a imputer suit le renommage
                imputation["colonne"] = nouveau_nom.get()
            if ancien in filtres:             # le filtre suit la colonne renommee
                filtres[nouveau_nom.get()] = filtres.pop(ancien)
            if ancien in memoire_filtres:
                memoire_filtres[nouveau_nom.get()] = memoire_filtres.pop(ancien)
                sauver_memoire_filtres()
            for liste_noms in (colonnes_categorielles, colonnes_double):
                liste_noms[:] = [nouveau_nom.get() if c == ancien else c for c in liste_noms]
        ## changement de modalite
        nb_modalite = None
        if modality_edit.current() != 0 and ancienne_mod.get() != "old modality" and nouvelle_mod.get() != "new modality":
            col = entete_tout[modality_edit.current()]
            if col in df.columns:
                masque = df[col].map(lambda v: not pd.isna(v) and str(v) == ancienne_mod.get())
                df[col] = df[col].astype("object").where(~masque, nouvelle_mod.get())
                nb_modalite = int((df[col].astype(str) == nouvelle_mod.get()).sum())
                if col in filtres and filtres[col][0] == "modalites" and ancienne_mod.get() in filtres[col][1]:
                    gardees = [nouvelle_mod.get() if m == ancienne_mod.get() else m for m in filtres[col][1]]
                    filtres[col] = ("modalites", list(dict.fromkeys(gardees)))
        ## valeurs manquantes
        ## (colonne choisie dans la boite « Missing value imputation », ou toutes les colonnes)
        quanti, quali = imputation["quanti"], imputation["quali"]
        if imputation["colonne"] is not None and imputation["colonne"] in [str(c) for c in df.columns]:
            cibles = [c for c in df.columns if str(c) == imputation["colonne"]]
        else:
            cibles = list(df.columns)
        cibles_quanti = [c for c in cibles if pd.api.types.is_numeric_dtype(df[c]) and str(c) not in colonnes_categorielles]
        cibles_quali = [c for c in cibles if c not in cibles_quanti]
        ## « delete » : lignes ayant une valeur manquante dans les colonnes ciblees
        a_supprimer = (cibles_quanti if quanti == "delete" else []) + (cibles_quali if quali == "delete" else [])
        if quanti == "delete" and quali == "delete":
            a_supprimer = cibles
        if a_supprimer:
            df = df.dropna(axis = 0, how = 'any', subset = a_supprimer)
        if quanti in ("mean", "median"):
            for col in cibles_quanti:
                df[col] = df[col].fillna(df[col].mean() if quanti == "mean" else df[col].median())
        if quali == "modality reference":
            for col in cibles_quali:
                mode = df[col].mode(dropna = True)
                if not mode.empty:
                    df[col] = df[col].fillna(mode.iloc[0])
        data_analy = df.reset_index(drop = True)
        ## filtrage des lignes, puis colonnes et lignes a afficher
        donnees = appliquer_filtres(data_analy)
        selection = colonnes_cochees()
        selection = [c for c in selection if c in donnees.columns]
        vue = donnees[selection] if selection else donnees
        if all_columns_def.get():
            n = len(vue)
        else:
            try:
                n = max(1, int(float(row_edit_value_default.get())))
            except (tk.TclError, ValueError):
                n = len(vue)
        vue = vue.head(n)
        row_edit_value_default.set(len(vue))
        ## le tableau « Overview stat » recouvre la zone du tableau : on le retire
        ## pour que le tableau de donnees s'affiche a chaque clic sur « View & Edit »
        if panneau_stat is not None and panneau_stat.winfo_exists():
            panneau_stat.destroy()
        panneau_stat = None
        cadre_tableau.lift()
        afficher_tableau(cadre_tableau, vue)
        ## nombre de patients : valeurs distinctes de la variable « Patient » sur les lignes affichees
        ## (calcule meme si la colonne Patient n'est pas selectionnee pour l'affichage)
        col_patient = next((c for c in donnees.columns if str(c).strip().lower() == "patient"), None)
        texte = "Rows: " + str(vue.shape[0]) + " , Columns: " + str(vue.shape[1])
        if col_patient is not None:
            texte = "Patients: " + str(int(donnees[col_patient].head(len(vue)).nunique(dropna = True))) + " , " + texte
        view_info_data_all.configure(text = texte)
        if list(avant.columns) != list(data_analy.columns) or not avant.equals(data_analy):
            historique_valider("Edit data")
        if nb_modalite is not None:
            change_modality.configure(text = " Number of " + nouvelle_mod.get() + ": " + str(nb_modalite))
        ## listes de colonnes mises a jour (renommage eventuel)
        nouveaux = [str(c) for c in data_analy.columns]
        if nouveaux != noms:
            noms[:] = nouveaux
            entete_tout[:] = ["Select column name"] + nouveaux
            modality_edit.configure(values = entete_tout)
            rename_columns.configure(values = entete_tout)
            modality_edit.current(0)
            rename_columns.current(0)
            ## cases conservees par position (une colonne renommee reste cochee)
            etats = [v.get() for _, v in cases_colonnes]
            remplir_colonnes(nouveaux, [c for c, e in zip(nouveaux, etats) if e])

    def donnees_stat ():
        """ Donnees de « Overview stat » : lignes filtrees, restreintes aux colonnes
        choisies dans « Select the columns to display » (toutes si aucune). """
        donnees = appliquer_filtres(data_analy)
        selection = colonnes_cochees()
        selection = [c for c in selection if c in donnees.columns]
        return donnees[selection] if selection else donnees

    ## --- Boutons (memes icones et positions que SmartDigiCat)
    style_b = dict(font = ('arial', 14), compound = tk.TOP, borderwidth = 0, relief = FLAT, borderless = True, bordercolor = "gray90", background = 'gray90', disabledforeground = 'gray90', focuscolor = 'gray90', highlightcolor = 'gray90', highlightbackground = 'gray90')
    ## « View & Edit » : ancre en bas du panneau 1, toujours visible
    bouton_edit = Button(p1, image = Edit_data_p, text = "View & Edit", command = Edit_data_all, **style_b)
    bouton_edit.place(relx = 0.5, rely = 1.0, anchor = "s", width = 110, height = 60)
    bouton_edit.lift()
    Button(low_window, image = view_stat, text = "Overview stat", command = lambda: stat_data_all(low_window, donnees_stat()), **style_b).place(relx = 0.85, rely = 0.05, width = 110, height = 60)
    Button(low_window, image = Export_data_p, text = "Export stat", command = exporter_stat_overview, **style_b).place(relx = 0.85, rely = 0.38, width = 110, height = 60)
    Button(low_window, image = Export_data_clin, text = "Export clean", command = lambda: my_exporting_data(appliquer_filtres(data_analy)), **style_b).place(relx = 0.85, rely = 0.7, width = 110, height = 60)


##=============================================================================
##  Trajectoires (bouton « Plots » > « Graphiques » > « Trajectory »)
##  Traduction Python de format_long_data, coder_groupe, plot.data et
##  trace_trajectoires (script R du projet ABOS).
##=============================================================================

## Palette par defaut de R (palette()) : couleurs 1 a 8
PALETTE_R = ["black", "#DF536B", "#61D04F", "#2297E6", "#28E2E5", "#CD0BBC", "#F5C710", "#9E9E9E"]

## Variables reponses par defaut : nom de colonne -> (titre de l'axe y, titre du graphique)
VARIABLES_DEFAUT = {
    "Poids": ("Weight (kg)", "Poids trajectories"),
    "BMI":   ("BMI (kg/m$^2$)", "BMI trajectories"),
    "TWL":   ("TWL (%)", "TWL trajectories"),
}


def vers_numerique (serie):
    """ Conversion numerique robuste (virgule decimale acceptee) ; equivalent de to_num(). """
    if pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie):
        return serie.astype(float)
    texte = serie.map(lambda v: v.strip().replace(",", ".") if isinstance(v, str) else v)
    return pd.to_numeric(texte, errors = "coerce")


def format_long_data (df):
    """ format_long_data() : col. 1 = patient, col. 2 = temps, col. 3.. = variables.
    Convertit le temps et les autres colonnes en numerique (l'identifiant aussi,
    s'il est numerique), trie par patient (ordre d'apparition) puis par temps.
    Renvoie (liste de DataFrames par patient, DataFrame empile). """
    if df.shape[1] < 2:
        raise ValueError("The data must contain at least two columns (patient, time).")
    df = df.copy()
    ident = df.columns[0]
    num_id = vers_numerique(df[ident])
    if num_id.notna().sum() == df[ident].notna().sum():
        df[ident] = num_id                     # identifiant numerique (as.integer en R)
    for c in df.columns[1:]:
        df[c] = vers_numerique(df[c])
    ordre_patients = pd.unique(df[ident])
    rang = pd.Series(range(len(ordre_patients)), index = ordre_patients)
    df["_rang"] = df[ident].map(rang)
    df = df.sort_values(["_rang", df.columns[1]], kind = "mergesort", na_position = "last").drop(columns = "_rang")
    df = df.reset_index(drop = True)
    liste = [d.reset_index(drop = True) for _, d in df.groupby(ident, sort = False)]
    return liste, df


def formater_borne (b):
    if np.isinf(b):
        return "Inf" if b > 0 else "-Inf"
    return cle_modalite(float(b))


def coder_groupe (data, groupe, labels = None, breaks = None, id = "Patient"):
    """ coder_groupe() : une valeur par patient (premiere valeur non manquante),
    decoupage en classes [a, b) si breaks est donne (derniere classe fermee),
    libelles par dictionnaire (valeur -> libelle) ou liste dans l'ordre des
    niveaux. Renvoie (codes 1..K ou NaN par ligne, niveaux, messages). """
    messages = []
    if groupe not in data.columns:
        raise ValueError("Variable '" + groupe + "' is not in the data.")
    x = data[groupe]
    n_val = x.groupby(data[id], sort = False).nunique(dropna = True)
    if (n_val > 1).any():
        messages.append(str(int((n_val > 1).sum())) + " patient(s) with several values of '" + groupe + "': the first non-missing value is kept.")
    val_pat = x.groupby(data[id], sort = False).agg(lambda v: v.dropna().iloc[0] if v.notna().any() else np.nan)
    x_pat = data[id].map(val_pat)

    if breaks is not None:
        ## cut(..., right = FALSE, include.lowest = TRUE)
        b = np.asarray(sorted(breaks), dtype = float)
        xv = vers_numerique(x_pat).to_numpy(dtype = float)
        idx = np.searchsorted(b, xv, side = "right") - 1
        idx = np.where(xv == b[-1], len(b) - 2, idx)
        valide = (~np.isnan(xv)) & (idx >= 0) & (idx <= len(b) - 2)
        niveaux = ["[" + formater_borne(b[k]) + "," + formater_borne(b[k + 1]) + (")" if k < len(b) - 2 else "]") for k in range(len(b) - 1)]
        valeurs = pd.Series([niveaux[k] if v else np.nan for k, v in zip(idx, valide)], index = data.index, dtype = "object")
    else:
        valeurs = x_pat.map(lambda v: np.nan if pd.isna(v) else cle_modalite(v))
        uniques = valeurs.dropna().unique().tolist()
        try:
            niveaux = sorted(uniques, key = float)
        except (TypeError, ValueError):
            niveaux = sorted(uniques, key = lambda v: (str(v).lower(), str(v)))   # ordre de R (sans tenir compte de la casse)

    if isinstance(labels, dict):
        ## factor(as.character(x), levels = names(labels), labels = labels)
        cles = [str(k) for k in labels]
        rang = {k: i for i, k in enumerate(cles)}
        code = valeurs.map(lambda v: rang.get(v, np.nan) if not pd.isna(v) else np.nan) + 1
        niveaux = [str(labels[k]) for k in labels]
    else:
        rang = {k: i for i, k in enumerate(niveaux)}
        code = valeurs.map(lambda v: rang.get(v, np.nan) if not pd.isna(v) else np.nan) + 1
        if labels is not None:
            if len(labels) != len(niveaux):
                raise ValueError("'labels' must have " + str(len(niveaux)) + " elements (levels: " + ", ".join(niveaux) + ").")
            niveaux = [str(l) for l in labels]
    return code.astype(float), niveaux, messages


def hcl_vers_hex (h, c, l):
    """ Couleur HCL (polarLUV, blanc D65) -> code hexadecimal sRGB, comme hcl() de R. """
    xn, yn, zn = 95.047, 100.000, 108.883
    un = 4 * xn / (xn + 15 * yn + 3 * zn)
    vn = 9 * yn / (xn + 15 * yn + 3 * zn)
    u, v = c * np.cos(np.radians(h)), c * np.sin(np.radians(h))
    y = yn * (((l + 16) / 116) ** 3 if l > 8 else l / 903.3)
    if l == 0:
        return "#000000"
    up, vp = u / (13 * l) + un, v / (13 * l) + vn
    x = 9 * y * up / (4 * vp)
    z = -x / 3 - 5 * y + 3 * y / vp
    rgb = np.array([[3.240479, -1.537150, -0.498535], [-0.969256, 1.875992, 0.041556], [0.055648, -0.204043, 1.057311]]) @ (np.array([x, y, z]) / 100)
    rgb = np.where(rgb > 0.00304, 1.055 * np.clip(rgb, 0, None) ** (1 / 2.4) - 0.055, 12.92 * rgb)
    return "#%02x%02x%02x" % tuple(int(round(255 * min(max(k, 0), 1))) for k in rgb)


def couleurs_groupes (k):
    """ Couleurs de plot.data : palette de R (1..k) si k <= 8, sinon hcl.colors(k, "Dark 3"). """
    if k <= 8:
        return PALETTE_R[:k]
    return [hcl_vers_hex(360 * i / k, 80, 60) for i in range(k)]


def style_graphique_r (ax):
    """ Aspect des graphiques de base de R : cadre complet, graduations vers
    l'exterieur, titres d'axes rapproches (mgp = c(2, 0.6, 0)), marges de 4 %. """
    for cote in ax.spines.values():
        cote.set_visible(True)
        cote.set_linewidth(0.8)
        cote.set_color("black")
    ax.tick_params(direction = "out", length = 4, width = 0.8, pad = 2, labelsize = 9, colors = "black")
    ax.margins(0.04)
    ax.grid(False)
    ax.set_facecolor("white")


def plot_data (ax, data, n_k = None, xlab = "Time (days)", ylab = "Weight",
               main = "Trajectories (true labels)", col = None, legend = True, groupe = None, lwd = 1.0):
    """ Traduction de plot.data() (Code_InfoMerge.R).
    data : DataFrame lu par position, 3 colonnes (id, x, y) ou 4 colonnes
           (id, groupe, x, y) ; ou liste de matrices (x, y), une par courbe,
           avec groupe (attribut « groupe » en R) ou n_k (effectifs par groupe).
    col  : couleurs des groupes (recyclees) ; par defaut 1..K de la palette R
           si K <= 8, sinon hcl.colors(K, "Dark 3").
    lwd  : epaisseur des lignes (points typographiques).
    Chaque courbe est tracee en points et segments (type = "b"). """
    ## ---- 0. Detection automatique du format
    if isinstance(data, pd.DataFrame):
        format_df = True
        p = data.shape[1]
        if p == 3:
            col_id, col_grp, col_x, col_y = data.iloc[:, 0], None, data.iloc[:, 1], data.iloc[:, 2]
        elif p == 4:
            col_id, col_grp, col_x, col_y = data.iloc[:, 0], data.iloc[:, 1], data.iloc[:, 2], data.iloc[:, 3]
        else:
            raise ValueError("The data frame must have 3 columns (id, x, y) or 4 columns (id, group, x, y).")
    elif isinstance(data, (list, tuple)):
        format_df = False
    else:
        raise ValueError("'data' must be a data frame (id, x, y) or a list of matrices (x, y).")

    ## ---- 1. Coordonnees et groupes
    if not format_df:
        n_courbes = len(data)
        if groupe is None:
            if n_k is not None:
                if sum(n_k) != n_courbes:
                    raise ValueError("sum(n_k) must be equal to the number of curves in 'data'.")
                groupe = np.repeat(np.arange(1, len(n_k) + 1), n_k)
            else:
                groupe = np.ones(n_courbes)
        courbes = [(np.asarray(d, dtype = float)[:, 0], np.asarray(d, dtype = float)[:, 1]) for d in data]
    else:
        ids = pd.unique(col_id)
        if col_grp is not None:
            premiere = ~col_id.duplicated()
            groupe = pd.Series(col_grp[premiere].to_numpy(), index = col_id[premiere].to_numpy()).loc[ids].to_numpy()
        else:
            groupe = np.ones(len(ids))
        x_tout, y_tout = col_x.to_numpy(dtype = float), col_y.to_numpy(dtype = float)
        position = {i: k for k, i in enumerate(ids)}
        lignes = [[] for _ in ids]
        for r, i in enumerate(col_id.to_numpy()):
            lignes[position[i]].append(r)
        courbes = [(x_tout[r], y_tout[r]) for r in lignes]
    groupe = list(groupe)

    ## ---- 2. Couleurs : une par groupe
    niveaux = sorted(set(groupe))
    K = len(niveaux)
    if col is None:
        col = couleurs_groupes(K)
    col = [col[k % len(col)] for k in range(K)]          # recyclage
    col_courbe = [col[niveaux.index(g)] for g in groupe]

    ## ---- 3. Graphique : xlim et ylim = etendues des donnees, une courbe par individu
    t_all = np.concatenate([c[0] for c in courbes]) if courbes else np.array([0.0])
    y_all = np.concatenate([c[1] for c in courbes]) if courbes else np.array([0.0])
    style_graphique_r(ax)
    if np.isfinite(t_all).any() and np.isfinite(y_all).any():
        e = 0.04                                        # extension de 4 % (xaxs = yaxs = "r")
        x0, x1 = np.nanmin(t_all), np.nanmax(t_all)
        y0, y1 = np.nanmin(y_all), np.nanmax(y_all)
        ax.set_xlim(x0 - e * (x1 - x0), x1 + e * (x1 - x0))
        ax.set_ylim(y0 - e * (y1 - y0), y1 + e * (y1 - y0))
    ax.lignes_groupes = {g: [] for g in niveaux}            # courbes de chaque groupe (legende interactive)
    ## type = "b" : segments et points (pch = 1, cercles vides) ; une collection de
    ## lignes et une serie de points par groupe (affichage fluide)
    segments = {g: [] for g in niveaux}
    for (x, y), g in zip(courbes, groupe):
        xy = np.column_stack([np.asarray(x, dtype = float), np.asarray(y, dtype = float)])
        segments[g].append(xy[np.isfinite(xy).all(axis = 1)])
    couleur_groupe = {g: col[niveaux.index(g)] for g in niveaux}
    for g, objets in tracer_trajectoires_groupees(ax, segments, couleur_groupe, alpha_ligne = 1.0, epaisseur = lwd,
                                                  taille_points = 4 + lwd, points_creux = True).items():
        ax.lignes_groupes[g] += objets
    ax.set_xlabel(xlab, fontsize = 10, labelpad = 2)
    ax.set_ylabel(ylab, fontsize = 10, labelpad = 2)
    ax.set_title(main, fontsize = 12, fontweight = "bold")
    return niveaux, col


def trace_trajectoires (figure, data, variables):
    """ trace_trajectoires() generalisee : un graphique par variable reponse,
    chacun avec sa propre variable de groupe (eventuelle) et sa legende.
    variables : dictionnaire variable -> parametres
        ylab, main, xlab                      titres de l'axe y, du graphique, de l'axe x
        groupe, labels, breaks, titre_legende arguments de coder_groupe() et titre de la legende
    Mise en page : deux colonnes, les graphiques a gauche (un par ligne) et,
    a droite, la legende du graphique de la meme ligne.
    Renvoie la liste des messages (patients exclus, valeurs multiples). """
    from matplotlib.lines import Line2D
    messages = []
    absentes = [c for c in ["Patient", "Time"] + list(variables) if c not in data.columns]
    if absentes:
        raise ValueError("Columns not found in the data: " + ", ".join(absentes))
    grille = figure.add_gridspec(len(variables), 2, width_ratios = [4, 1.3])
    for k, (v, p) in enumerate(variables.items()):
        ax = figure.add_subplot(grille[k, 0])               # colonne de gauche : graphique
        ax_leg = figure.add_subplot(grille[k, 1])           # colonne de droite : legende
        ax_leg.axis("off")
        groupe = p.get("groupe")
        cols = ["Patient", "Time", v]
        d = data.copy()
        if groupe is not None:
            code, niveaux, msg = coder_groupe(d, groupe, labels = p.get("labels"), breaks = p.get("breaks"))
            messages += ["[" + v + "] " + m for m in msg]
            d["Groupe"] = code
            cols.append("Groupe")
        _, df = format_long_data(d[cols])
        if groupe is not None:
            na_pat = df.loc[df["Groupe"].isna(), "Patient"].unique()
            if len(na_pat):
                messages.append("[" + v + "] " + str(len(na_pat)) + " patient(s) excluded: '" + groupe + "' missing.")
            df = df[df["Groupe"].notna()].reset_index(drop = True)
            presents, couleurs = plot_data(ax, df[["Patient", "Groupe", "Time", v]], xlab = p.get("xlab", "Time (month)"),
                                           ylab = p.get("ylab", v), main = p.get("main", ""), lwd = p.get("lwd", 1.0))
            ## legende (lwd = 3, pch = 1, texte gras, sans cadre) : memes couleurs que les courbes
            poignees = [Line2D([0], [0], color = c, linewidth = 3, marker = "o", markersize = 6, markerfacecolor = "white", markeredgecolor = c) for c in couleurs]
            libelles = [niveaux[int(g) - 1] for g in presents]
            if p.get("labels") is None and p.get("breaks") is None:
                libelles = mots_cles(libelles, LONGUEUR_MAX_LEGENDE)   # modalites brutes trop longues : mots cles
            legende = ax_leg.legend(poignees, libelles, title = p.get("titre_legende") or groupe,
                                    loc = "center left", borderaxespad = 0, frameon = False,
                                    prop = {"weight": "bold", "size": 10}, title_fontsize = 11)
            legende.get_title().set_fontweight("bold")
            legende._legend_box.align = "left"            # titre aligne a gauche (toutes versions de matplotlib)
            ## legende interactive : un clic sur une modalite n'affiche que ses trajectoires
            poignees_leg = getattr(legende, "legend_handles", None) or getattr(legende, "legendHandles", [])
            legende.modalites = {}
            for g, poignee, texte in zip(presents, poignees_leg, legende.get_texts()):
                for artiste in (poignee, texte):
                    artiste.set_picker(True)
                    legende.modalites[artiste] = g
            legende.ax_cible = ax
            legende.modalite_seule = None
        else:
            plot_data(ax, df[["Patient", "Time", v]], xlab = p.get("xlab", "Time (month)"),
                      ylab = p.get("ylab", v), main = p.get("main", ""), lwd = p.get("lwd", 1.0),
                      col = [p.get("couleur") or "black"])     # sans groupe : couleur choisie
    return messages


figure_graphique = None            # figure matplotlib affichee dans le panneau des graphiques
statut_graphique = None            # message sous les options (patients exclus, etc.)
## derniers parametres des variables reponses (pre-remplissage de la boite de dialogue)
parametres_trajectoire = {"variables": None, "parametres": {}}


HAUTEUR_MIN_GRAPHIQUE = 320        # hauteur minimale d'une ligne de graphique (pixels)
## « Y-depth » (bloc « Axes option ») : hauteur de chaque ligne de graphique,
## commune a tous les graphiques ; None : valeur par defaut (moitie du panneau)
hauteur_graphiques = {"valeur": None, "defaut": None, "dimensionner": None, "affichage": None}
zone_defilement = {"zone": None}   # zone defilante des graphiques affiches (position conservee au retrace)


def afficher_figure (n_lignes):
    """ Cree la figure matplotlib du panneau des graphiques, dans une zone
    defilante verticalement. Chaque ligne (graphique + legende) a la meme
    hauteur quel que soit le nombre de graphiques : la moitie de la hauteur du
    panneau (au moins HAUTEUR_MIN_GRAPHIQUE pixels). Au-dela, on fait defiler
    avec la barre de defilement ou la molette. """
    global figure_graphique
    for w in panneau_graphique.winfo_children():
        w.destroy()
    zone = Canvas(panneau_graphique, highlightthickness = 0, background = "white")
    defil = ttk.Scrollbar(panneau_graphique, orient = "vertical", command = zone.yview)
    zone.configure(yscrollcommand = defil.set)
    defil.pack(side = "right", fill = "y")
    zone.pack(side = "left", fill = BOTH, expand = True)
    interieur = Frame(zone, background = "white")
    fen = zone.create_window((0, 0), window = interieur, anchor = "nw")
    zone_defilement["zone"] = zone
    figure_graphique = Figure(constrained_layout = True)
    toile = FigureCanvasTkAgg(figure_graphique, master = interieur)
    widget = toile.get_tk_widget()
    widget.pack(side = "top", fill = "x")
    dpi = figure_graphique.get_dpi()

    def dimensionner (event = None):
        largeur = max(zone.winfo_width(), 200)
        hauteur_graphiques["defaut"] = max(HAUTEUR_MIN_GRAPHIQUE, zone.winfo_height() // 2)
        hauteur_ligne = hauteur_graphiques["valeur"] or hauteur_graphiques["defaut"]    # « Y-depth »
        hauteur = int(hauteur_ligne * max(n_lignes, 1))
        if hauteur_graphiques["affichage"] is not None:
            hauteur_graphiques["affichage"]()          # boite « Y-depth » remplie par la valeur utilisee
        figure_graphique.set_size_inches(largeur / dpi, hauteur / dpi, forward = False)
        widget.configure(width = largeur, height = hauteur)
        zone.itemconfigure(fen, width = largeur, height = hauteur)
        ## zone de defilement au moins aussi haute que le panneau : un graphique
        ## seul reste en haut (Tk centre une zone plus petite que la fenetre)
        zone.configure(scrollregion = (0, 0, largeur, max(hauteur, zone.winfo_height())))
        if hauteur <= zone.winfo_height():
            zone.yview_moveto(0)
        mise_en_page(figure_graphique, toile)    # mise en page recalculee (nouvelle taille)

    attente = {"id": None}

    def dimensionner_differe (event = None):
        ## redimensionnement de la fenetre : un seul recalcul quand il s'arrete
        if attente["id"] is not None:
            try:
                zone.after_cancel(attente["id"])
            except tk.TclError:
                pass
        attente["id"] = zone.after(120, dimensionner)

    zone.bind("<Configure>", dimensionner_differe)
    hauteur_graphiques["dimensionner"] = lambda: dimensionner() if zone.winfo_exists() else None
    molette = lambda event: zone.yview_scroll(-1 * (event.delta if abs(event.delta) < 10 else event.delta // 120), "units")
    widget.bind("<Enter>", lambda event: zone.bind_all("<MouseWheel>", molette))   # molette active sur les graphiques
    widget.bind("<Leave>", lambda event: zone.unbind_all("<MouseWheel>"))
    panneau_graphique.update_idletasks()
    dimensionner()
    return figure_graphique, toile


##------ Zoom des graphiques (barre de defilement de la barre verticale gauche)
## Le zoom est propre a chaque graphique : un clic sur un graphique le
## selectionne (fond legerement bleute) et la barre agit sur lui seul.
## Position 50 : taille d'origine ; 100 : zoom x4 ; 0 : zoom x1/4.
## Glisser avec la souris (bouton gauche enfonce) deplace le graphique ;
## un double clic le remet dans son etat d'origine.
ZOOM_NEUTRE = 50
etat_zoom = {"toile": None, "axes": [], "origine": {}, "niveau": {}, "centre": {}, "actif": None, "glisse": None}


def facteur_zoom (niveau):
    return 2 ** ((float(niveau) - ZOOM_NEUTRE) / 25)


def activer_zoom (figure, toile):
    """ Prepare le zoom des graphiques de la figure : graphiques principaux
    (axes visibles ; les colonnes de legende et de statistiques sont exclues),
    limites d'origine, niveau neutre ; aucun graphique n'est selectionne
    (les bornes des axes s'appliquent alors a tous les graphiques). """
    axes = [ax for ax in figure.axes if ax.axison]
    etat_zoom.update(toile = toile, axes = axes, actif = None, glisse = None,
                     origine = {ax: (ax.get_xlim(), ax.get_ylim()) for ax in axes},
                     niveau = {ax: ZOOM_NEUTRE for ax in axes},
                     centre = {ax: (sum(ax.get_xlim()) / 2, sum(ax.get_ylim()) / 2) for ax in axes})
    toile.mpl_connect("button_press_event", saisir_graphique)
    toile.mpl_connect("motion_notify_event", deplacer_graphique)
    toile.mpl_connect("button_release_event", lacher_graphique)
    toile.mpl_connect("pick_event", choisir_modalite_legende)
    toile.mpl_connect("motion_notify_event", survol_graphique)   # coordonnees au survol des courbes
    deselectionner_graphique()


def choisir_modalite_legende (event):
    """ Clic sur une modalite de la legende d'un graphique de trajectoires :
    seules les trajectoires de cette modalite restent affichees ; un second
    clic sur la meme modalite reaffiche toutes les trajectoires. """
    legende = next((ax.get_legend() for ax in event.artist.figure.axes
                    if ax.get_legend() is not None and event.artist in getattr(ax.get_legend(), "modalites", {})), None)
    if legende is None:
        return
    g = legende.modalites[event.artist]
    legende.modalite_seule = None if legende.modalite_seule == g else g
    for groupe, lignes in legende.ax_cible.lignes_groupes.items():
        visible = legende.modalite_seule is None or groupe == legende.modalite_seule
        for ligne in lignes:
            ligne.set_visible(visible)
    for artiste, groupe in legende.modalites.items():         # modalites masquees grisees dans la legende
        artiste.set_alpha(1.0 if legende.modalite_seule is None or groupe == legende.modalite_seule else 0.3)
    event.artist.figure.canvas.draw_idle()


def saisir_graphique (event):
    """ Clic : selection du graphique et debut du deplacement a la souris. """
    ax = event.inaxes
    if ax is None and event.button == 1:
        deselectionner_graphique()                # clic hors des graphiques : aucune selection
        return
    if ax is None or ax not in etat_zoom["axes"] or event.button != 1:
        return
    if event.dblclick:
        retablir_graphique(ax)
        return
    selectionner_graphique(ax)
    etat_zoom["glisse"] = (ax, event.x, event.y, ax.get_xlim(), ax.get_ylim())
    etat_zoom["toile"].get_tk_widget().configure(cursor = "fleur")


def deplacer_graphique (event):
    """ Glisser : decalage des limites du graphique, proportionnel au
    deplacement de la souris (en pixels). """
    if etat_zoom["glisse"] is None:
        return
    ax, x0, y0, (xa, xb), (ya, yb) = etat_zoom["glisse"]
    boite = ax.get_window_extent()
    dx = (event.x - x0) * (xb - xa) / boite.width
    dy = (event.y - y0) * (yb - ya) / boite.height
    ax.set_xlim(xa - dx, xb - dx)
    ax.set_ylim(ya - dy, yb - dy)
    etat_zoom["centre"][ax] = ((xa + xb) / 2 - dx, (ya + yb) / 2 - dy)
    etat_zoom["toile"].draw_idle()


def retablir_graphique (ax):
    """ Double clic : limites, centre et niveau de zoom d'origine du graphique ;
    toutes les trajectoires reaffichees (legende interactive remise a zero). """
    for autre in ax.figure.axes:
        legende = autre.get_legend()
        if legende is not None and getattr(legende, "ax_cible", None) is ax:
            legende.modalite_seule = None
            for artiste in legende.modalites:
                artiste.set_alpha(1.0)
    for lignes in getattr(ax, "lignes_groupes", {}).values():
        for ligne in lignes:
            ligne.set_visible(True)
    (x0, x1), (y0, y1) = etat_zoom["origine"][ax]
    etat_zoom["glisse"] = None
    etat_zoom["centre"][ax] = ((x0 + x1) / 2, (y0 + y1) / 2)
    etat_zoom["niveau"][ax] = ZOOM_NEUTRE
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    selectionner_graphique(ax)                 # la barre revient au niveau neutre


def lacher_graphique (event):
    if etat_zoom["glisse"] is not None:
        etat_zoom["glisse"] = None
        etat_zoom["toile"].get_tk_widget().configure(cursor = "")


def selectionner_graphique (ax):
    """ Graphique cible du zoom ; la barre reprend son niveau de zoom. """
    if ax is None or ax not in etat_zoom["axes"]:
        return
    for a in etat_zoom["axes"]:
        a.set_facecolor("#F2F6FC" if a is ax and len(etat_zoom["axes"]) > 1 else "white")
    etat_zoom["actif"] = ax
    scale.set(etat_zoom["niveau"][ax])
    etat_zoom["toile"].draw_idle()
    for rappel in list(rappel_selection.values()):
        if rappel is not None:                 # options propres au graphique selectionne
            rappel(ax)


RAYON_SURVOL = 8                   # distance maximale (pixels) entre la souris et un point de courbe


def _masquer_bulle (ax):
    bulle = getattr(ax, "bulle_survol", None)
    if bulle is not None and bulle.get_visible():
        bulle.set_visible(False)
        ax.point_survol = None
        return True
    return False


def survol_graphique (event):
    """ Souris sur une courbe : ses coordonnees (point le plus proche de la
    courbe, a moins de RAYON_SURVOL pixels) s'affichent dans une bulle. """
    if etat_zoom["toile"] is None or etat_zoom["glisse"] is not None:
        return
    maintenant = time.time()
    if maintenant - etat_zoom.get("dernier_survol", 0.0) < 0.04:       # au plus 25 fois par seconde
        return
    etat_zoom["dernier_survol"] = maintenant
    redessiner = False
    for ax in etat_zoom["axes"]:
        if ax is not event.inaxes:
            redessiner |= _masquer_bulle(ax)
    ax = event.inaxes
    if ax is None or ax not in etat_zoom["axes"]:
        if redessiner:
            etat_zoom["toile"].draw_idle()
        return
    ## points des courbes visibles (coordonnees des donnees -> pixels)
    blocs = []
    for ligne in ax.get_lines():
        if not ligne.get_visible():
            continue
        try:
            xy = np.asarray(ligne.get_xydata(), dtype = float)
        except (TypeError, ValueError):
            continue
        if xy.ndim == 2 and len(xy):
            blocs.append(xy[np.isfinite(xy).all(axis = 1)])
    point = None
    if blocs:
        xy = np.concatenate(blocs)
        if len(xy):
            pixels = ax.transData.transform(xy)
            d2 = (pixels[:, 0] - event.x) ** 2 + (pixels[:, 1] - event.y) ** 2
            k = int(np.argmin(d2))
            if d2[k] <= RAYON_SURVOL ** 2:
                point = (float(xy[k, 0]), float(xy[k, 1]))
    if point is None:
        if _masquer_bulle(ax) or redessiner:
            etat_zoom["toile"].draw_idle()
        return
    if getattr(ax, "point_survol", None) == point:
        return
    bulle = getattr(ax, "bulle_survol", None)
    if bulle is None:
        bulle = ax.annotate("", xy = point, xytext = (12, 12), textcoords = "offset points", fontsize = 9, zorder = 100,
                            bbox = dict(boxstyle = "round,pad=0.3", fc = "#FFFFF0", ec = "#7F7F7F", alpha = 0.95),
                            annotation_clip = False)
        ax.bulle_survol = bulle
    bulle.xy = point
    ## titres des axes (x / y si un axe n'a pas de titre)
    titre_x = ax.get_xlabel().strip() or "x"
    titre_y = ax.get_ylabel().strip() or "y"
    bulle.set_text("%s = %.4g\n%s = %.4g" % (titre_x, point[0], titre_y, point[1]))
    ## bulle a gauche / en dessous pres des bords droit et haut du graphique
    boite = ax.get_window_extent()
    bulle.set_position((12, 12))
    bulle.set_visible(True)
    try:                                           # largeur de la bulle (pixels), qui depend des titres
        largeur_px = bulle.get_window_extent(etat_zoom["toile"].get_renderer()).width
    except Exception:
        largeur_px = 120
    points = 72.0 / ax.figure.dpi                  # pixels -> points (decalage de la bulle)
    gauche = event.x > boite.x1 - largeur_px - 20
    bulle.set_position((-largeur_px * points - 8 if gauche else 12, -38 if event.y > boite.y1 - 45 else 12))
    ax.point_survol = point
    etat_zoom["toile"].draw_idle()


def deselectionner_graphique ():
    """ Aucun graphique selectionne : les options (bornes des axes) agissent
    sur tous les graphiques. """
    etat_zoom["actif"] = None
    for a in etat_zoom["axes"]:
        a.set_facecolor("white")
    if etat_zoom["toile"] is not None:
        etat_zoom["toile"].draw_idle()
    for rappel in list(rappel_selection.values()):
        if rappel is not None:
            rappel(None)


rappel_selection = {"fonction": None, "axes": None}   # appeles a chaque selection d'un graphique


##------ Bornes des axes (« Axes option » : lignes X et Y, min et max) --------
## Bornes globales (aucun graphique selectionne) et bornes propres a un
## graphique (graphique selectionne), prioritaires sur les globales. Une
## borne vide : limite automatique du graphique.
CLES_BORNES = ("xmin", "xmax", "ymin", "ymax")
## actif : case « Zoom axes » (affichage des options seulement) ;
## un graphique marque « normal » ignore les bornes globales
bornes_axes = {"actif": False, "global": dict.fromkeys(CLES_BORNES), "graphiques": {}}


def cle_graphique (ax, titre = None, indice = None):
    """ Identifiant d'un graphique, stable d'un trace a l'autre : analyse
    (resultats) ou type de graphique et rang de la variable (« Plots »). """
    if getattr(ax, "analyse", None) is not None:
        return ("analyse", ax.analyse)
    if indice is None:
        indice = etat_zoom["axes"].index(ax) if ax in etat_zoom["axes"] else 0
    return (titre or type_affiche["titre"], indice)


def bornes_effectives (ax, cle):
    propres = bornes_axes["graphiques"].get(cle, {})
    if propres.get("normal"):
        return dict.fromkeys(CLES_BORNES)          # axes normaux pour ce graphique
    b = dict(bornes_axes["global"])
    b.update({k: v for k, v in propres.items() if k in CLES_BORNES and v is not None})
    return b


def reappliquer_bornes (cibles = None):
    """ Limites recalculees (graphiques donnes ou tous) ; elles deviennent le
    nouvel etat d'origine du zoom. """
    cibles = list(etat_zoom["axes"]) if cibles is None else cibles
    for ax in cibles:
        appliquer_bornes_axe(ax, cle_graphique(ax))
        etat_zoom["origine"][ax] = (ax.get_xlim(), ax.get_ylim())
        etat_zoom["centre"][ax] = (sum(ax.get_xlim()) / 2, sum(ax.get_ylim()) / 2)
        etat_zoom["niveau"][ax] = ZOOM_NEUTRE
    if etat_zoom["actif"] is not None:
        scale.set(ZOOM_NEUTRE)
    if etat_zoom["toile"] is not None:
        etat_zoom["toile"].draw_idle()


def appliquer_bornes_axe (ax, cle):
    """ Limites du graphique : bornes saisies, sinon limites automatiques. """
    if not hasattr(ax, "limites_auto"):
        ax.limites_auto = (ax.get_xlim(), ax.get_ylim())
    (ax0, ax1), (ay0, ay1) = ax.limites_auto
    b = bornes_effectives(ax, cle)
    x0 = ax0 if b["xmin"] is None else b["xmin"]
    x1 = ax1 if b["xmax"] is None else b["xmax"]
    y0 = ay0 if b["ymin"] is None else b["ymin"]
    y1 = ay1 if b["ymax"] is None else b["ymax"]
    if x0 < x1:
        ax.set_xlim(x0, x1)
    if y0 < y1:
        ax.set_ylim(y0, y1)


def appliquer_bornes (figure, titre = None, indices = None):
    """ Bornes appliquees aux graphiques principaux d'une figure (apres le trace). """
    axes = [ax for ax in figure.axes if ax.axison]
    for k, ax in enumerate(axes):
        appliquer_bornes_axe(ax, cle_graphique(ax, titre, indices[k] if indices and k < len(indices) else k))


def modifier_borne (cle_borne, texte):
    """ Saisie d'une borne : graphique selectionne, sinon tous les graphiques. """
    texte = texte.strip().replace(",", ".")
    try:
        valeur = None if texte == "" else float(texte)
    except ValueError:
        messagebox.showwarning("Axes option", "Please enter a number (or leave the box empty for an automatic limit).")
        return False
    actif = etat_zoom["actif"]
    actuelle = (bornes_effectives(actif, cle_graphique(actif)) if actif is not None else bornes_axes["global"])[cle_borne]
    if valeur == actuelle:
        return True                                # valeur inchangee : le zoom en cours est conserve
    if actif is not None:
        propres = bornes_axes["graphiques"].setdefault(cle_graphique(actif), dict.fromkeys(CLES_BORNES))
        if propres.pop("normal", None):            # saisie d'une borne : le graphique n'est plus « normal »
            propres.update({c: v for c, v in bornes_axes["global"].items() if propres.get(c) is None})
        propres[cle_borne] = valeur
        cibles = [actif]
    else:
        bornes_axes["global"][cle_borne] = valeur
        cibles = list(etat_zoom["axes"])
    reappliquer_bornes(cibles)                     # nouvelles limites = nouvel etat d'origine du zoom
    return True


def lignes_bornes (cadre, ligne):
    """ Case « Zoom axes » du bloc « Axes option » ; cochee, elle affiche en
    retrait (comme les types sous « Graphiques » dans « Plots ») :
    - « Normal » (cochee par defaut) : axes normaux (limites automatiques) ;
    - X : borne inferieure et borne superieure de l'abscisse ;
    - Y : borne inferieure et borne superieure de l'ordonnee.
    Avec un graphique selectionne (clic), les bornes saisies et « Normal » ne
    valent que pour lui ; sans selection, pour tous les graphiques. Les boites
    sont toujours modifiables. « Zoom axes » ne fait qu'afficher ces options. """
    var_zoom = BooleanVar(value = bornes_axes["actif"])
    var_normal = BooleanVar(value = True)
    variables, entrees = {}, []
    sous = Frame(cadre, background = "gray90")
    style = dict(font = ('arial', 13), fg = "gray30", background = "gray90", activebackground = "gray90",
                 highlightthickness = 0, anchor = "w")
    case_normal = Checkbutton(sous, text = "Normal", variable = var_normal, **style)
    case_normal.grid(row = 0, column = 0, columnspan = 2, sticky = "w")
    for k, (nom_axe, cles) in enumerate((("X", ("xmin", "xmax")), ("Y", ("ymin", "ymax")))):
        Label(sous, text = nom_axe, font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = k + 1, column = 0, sticky = "w", padx = (4, 0), pady = (4, 0))
        boites = Frame(sous, background = "gray90")
        boites.grid(row = k + 1, column = 1, sticky = "w", padx = (8, 0), pady = (4, 0))
        for j, cle in enumerate(cles):
            variables[cle] = StringVar(value = "")
            entree = Entry(boites, textvariable = variables[cle], width = 7)
            entree.grid(row = 0, column = j, padx = (0, 4))
            valider = lambda event = None, cle = cle: modifier_borne(cle, variables[cle].get()) and afficher_bornes(etat_zoom["actif"])
            entree.bind("<Return>", valider)
            entree.bind("<FocusOut>", valider)
            entrees.append(entree)

    def portee ():
        ## bornes du graphique selectionne, ou bornes globales
        actif = etat_zoom["actif"]
        return actif, (cle_graphique(actif) if actif is not None else None)

    def afficher_bornes (ax = None):
        if not cadre.winfo_exists():
            rappel_selection["axes"] = None
            return
        actif, cle = portee()
        b = bornes_effectives(actif, cle) if actif is not None else bornes_axes["global"]
        var_normal.set(all(v is None for v in b.values()))
        for c, var in variables.items():                # boites toujours modifiables
            var.set("" if b[c] is None else formater_valeur_stat(b[c]))

    def basculer_normal ():
        actif, cle = portee()
        if var_normal.get():                       # axes normaux pour la portee courante
            if actif is not None:
                bornes_axes["graphiques"][cle] = {"normal": True}
            else:
                bornes_axes["global"] = dict.fromkeys(CLES_BORNES)
            reappliquer_bornes([actif] if actif is not None else None)
        afficher_bornes(actif)                     # decocher « Normal » : saisir les bornes dans les boites

    def basculer_zoom ():
        ## affichage des options ; les bornes de chaque graphique restent appliquees
        bornes_axes["actif"] = var_zoom.get()
        if var_zoom.get():
            sous.grid(row = ligne + 1, column = 0, columnspan = 2, sticky = "w", padx = (40, 0), pady = (2, 0))
        else:
            sous.grid_remove()
        afficher_bornes(etat_zoom["actif"])

    case_normal.configure(command = basculer_normal)
    Checkbutton(cadre, text = "Zoom axes", variable = var_zoom, command = basculer_zoom, **style).grid(
        row = ligne, column = 0, columnspan = 2, sticky = "w", padx = (18, 0), pady = (6, 0))
    ## « Y-depth » (ligne du bas, sous les options de « Zoom axes ») : hauteur de
    ## chaque graphique (pixels), commune a tous les graphiques
    Label(cadre, text = "Y-depth", font = ('arial', 13), fg = "gray30", background = "gray90").grid(
        row = ligne + 2, column = 0, sticky = "w", padx = (22, 0), pady = (6, 0))
    var_hauteur = StringVar(value = "")
    boite_hauteur = Spinbox(cadre, from_ = 150, to = 3000, increment = 20, textvariable = var_hauteur, width = 6)
    boite_hauteur.grid(row = ligne + 2, column = 1, sticky = "w", padx = (6, 0), pady = (6, 0))

    def afficher_hauteur ():
        if not boite_hauteur.winfo_exists():
            hauteur_graphiques["affichage"] = None
            return
        if boite_hauteur.focus_get() is not boite_hauteur:       # pas pendant la saisie
            valeur = hauteur_graphiques["valeur"] or hauteur_graphiques["defaut"]
            var_hauteur.set("" if valeur is None else str(int(valeur)))

    def appliquer_hauteur (event = None):
        texte = var_hauteur.get().strip().replace(",", ".")
        try:
            valeur = None if texte == "" else int(float(texte))
            if valeur is not None and valeur < 100:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Y-depth", "Y-depth must be a height in pixels (at least 100), or empty for the default value.")
            afficher_hauteur()
            return
        if valeur == (hauteur_graphiques["valeur"] or hauteur_graphiques["defaut"]):
            return
        hauteur_graphiques["valeur"] = valeur
        if hauteur_graphiques["dimensionner"] is not None:
            hauteur_graphiques["dimensionner"]()

    boite_hauteur.configure(command = appliquer_hauteur)
    boite_hauteur.bind("<Return>", appliquer_hauteur)
    boite_hauteur.bind("<FocusOut>", appliquer_hauteur)
    hauteur_graphiques["affichage"] = afficher_hauteur
    afficher_hauteur()
    if var_zoom.get():
        sous.grid(row = ligne + 1, column = 0, columnspan = 2, sticky = "w", padx = (40, 0), pady = (2, 0))
    rappel_selection["axes"] = afficher_bornes
    afficher_bornes(None)


def zoomer_graphique (valeur):
    """ Commande de la barre : zoom du graphique selectionne autour du centre
    de la vue courante (eventuellement deplacee a la souris). """
    ax = etat_zoom["actif"]
    if ax is None or etat_zoom["toile"] is None or ax not in etat_zoom["origine"]:
        return
    etat_zoom["niveau"][ax] = float(valeur)
    f = facteur_zoom(valeur)
    (x0, x1), (y0, y1) = etat_zoom["origine"][ax]
    cx, cy = etat_zoom["centre"][ax]
    dx, dy = (x1 - x0) / (2 * f), (y1 - y0) / (2 * f)
    ax.set_xlim(cx - dx, cx + dx)
    ax.set_ylim(cy - dy, cy + dy)
    etat_zoom["toile"].draw_idle()


def reinitialiser_zoom ():
    etat_zoom.update(toile = None, axes = [], origine = {}, niveau = {}, centre = {}, actif = None, glisse = None)


def effacer_figure ():
    """ Vide le panneau des graphiques (les graphiques construits restent
    proposes par « Save plot »). """
    global figure_graphique
    reinitialiser_zoom()
    type_affiche["titre"] = None
    if panneau_graphique is not None and panneau_graphique.winfo_exists():
        for w in panneau_graphique.winfo_children():
            w.destroy()
    figure_graphique = None


def lire_labels (texte):
    """ « 0=Non; 1=Oui » -> dictionnaire (valeur -> libelle) ;
    « < 40; 40-50; >= 50 » -> liste dans l'ordre des niveaux ; vide -> None. """
    morceaux = [m.strip() for m in texte.split(";") if m.strip() != ""]
    if len(morceaux) == 0:
        return None
    ## forme « valeur=libelle » (« <= 40 » ou « >= 50 » restent des libelles)
    paires = [re.match(r"^([^<>=!]+?)\s*=\s*(.+)$", m) for m in morceaux]
    if all(paires):
        return {pm.group(1).strip(): pm.group(2).strip() for pm in paires}
    return morceaux


def lire_breaks (texte):
    """ « -Inf, 40, 50, Inf » -> liste croissante de bornes ; vide -> None. """
    morceaux = [m.strip() for m in texte.replace(";", ",").split(",") if m.strip() != ""]
    if len(morceaux) == 0:
        return None
    bornes = [float(m) for m in morceaux]               # « Inf » et « -Inf » acceptes
    if len(bornes) < 2 or any(b2 <= b1 for b1, b2 in zip(bornes, bornes[1:])):
        raise ValueError("The breaks must contain at least two strictly increasing values.")
    return bornes


def est_quantitative (serie, nom):
    """ Variable quantitative : numerique, non booleenne, non declaree categorielle. """
    return (pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie)
            and nom not in colonnes_categorielles)


ETIQUETTE_BOITE = dict(font = ('arial', 13), anchor = "w")
AIDE_BOITE = dict(font = ('arial', 11), fg = "gray40", anchor = "w")


def nouvelle_boite (hote):
    """ Boite de dialogue integree au panneau central : centree, deplacable,
    modale (capture locale). """
    boite = Frame(hote, bd = 2, relief = "ridge")
    boite.place(relx = 0.5, rely = 0.5, anchor = "center")
    boite.after_idle(lambda: rendre_deplacable(boite))    # boite deplacable a la souris
    boite.lift()
    boite.grab_set()
    return boite


def champ_boite (boite, ligne, texte, valeur, largeur = 34):
    """ Ligne « libelle : zone de saisie » d'une boite ; renvoie la StringVar. """
    Label(boite, text = texte, **ETIQUETTE_BOITE).grid(row = ligne, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    var = StringVar(value = valeur)
    Entry(boite, textvariable = var, width = largeur).grid(row = ligne, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
    return var


def ligne_masquable (boite, ligne, texte, widget, aide = None):
    """ Libelle + widget (+ aide sur la ligne suivante) affiches ou masques
    ensemble ; renvoie une fonction afficher(booleen). """
    lab = Label(boite, text = texte, **ETIQUETTE_BOITE)
    lab_aide = Label(boite, text = aide, **AIDE_BOITE) if aide else None

    def afficher (visible):
        if visible:
            lab.grid(row = ligne, column = 0, sticky = "w", padx = (15, 6), pady = 3)
            widget.grid(row = ligne, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
            if lab_aide is not None:
                lab_aide.grid(row = ligne + 1, column = 1, sticky = "w", padx = (0, 15))
        else:
            lab.grid_remove(); widget.grid_remove()
            if lab_aide is not None:
                lab_aide.grid_remove()
    return afficher


## Graphiques construits (types coches et traces), dans l'ordre de construction :
## type -> {"tracer": fonction de trace, "variables": parametres}. Le panneau
## affiche le dernier type trace ; « Save plot » propose tous les graphiques construits.
traces_graphiques = {}
type_affiche = {"titre": None}
type_courant = {"titre": None}     # type coche quand « Graphiques » est decoche (reaffiche au retour)


def afficher_type (titre):
    """ Trace dans le panneau les graphiques du type titre (une ligne par
    variable) et affiche les messages correspondants. """
    t = traces_graphiques[titre]
    ## meme type retrace (action sur une courbe, Refresh...) : la position de la
    ## barre de defilement est conservee, on reste sur la courbe
    position = None
    ancienne_zone = zone_defilement["zone"]
    if type_affiche["titre"] == titre and ancienne_zone is not None:
        try:
            if ancienne_zone.winfo_exists():
                position = ancienne_zone.yview()[0]
        except tk.TclError:
            position = None
    figure, toile = afficher_figure(len(t["variables"]))
    messages = t["tracer"](figure, appliquer_filtres(data_analy), t["variables"])
    appliquer_polices(figure)
    appliquer_bornes(figure, titre)                   # bornes des axes (« Axes option »)
    mise_en_page(figure, toile)                       # mise en page calculee une fois, puis figee
    if position:
        zone = zone_defilement["zone"]
        zone.update_idletasks()
        zone.yview_moveto(position)                   # retour a la courbe sur laquelle on travaillait
    activer_zoom(figure, toile)                       # zoom propre a chaque graphique
    type_affiche["titre"] = titre
    type_courant["titre"] = titre                     # retrace au retour dans « Graphiques »
    if statut_graphique is not None and statut_graphique.winfo_exists():
        statut_graphique.configure(text = "\n".join(messages))


def rafraichir_graphique ():
    """ Bouton « Refresh » : retrace le graphique affiche avec les donnees
    editees et filtrees actuelles et les polices choisies (zoom et
    deplacements remis a l'etat d'origine). """
    titre = type_affiche["titre"]
    if titre not in traces_graphiques or panneau_graphique is None or not panneau_graphique.winfo_exists():
        messagebox.showinfo("Refresh", "No plot to refresh: draw a plot first (button 'Plot').")
        return
    try:
        afficher_type(titre)
    except Exception as erreur:
        effacer_figure()
        messagebox.showerror("Refresh", "The plot could not be drawn:\n" + str(erreur))


def retirer_graphique (titre):
    """ Type de graphique decoche : retire des graphiques construits ; s'il
    etait affiche, le panneau est vide. """
    traces_graphiques.pop(titre, None)
    if type_courant["titre"] == titre:
        type_courant["titre"] = None
    if type_affiche["titre"] == titre:
        effacer_figure()
        if statut_graphique is not None and statut_graphique.winfo_exists():
            statut_graphique.configure(text = "")


FORMATS_GRAPHIQUE = ["png", "pdf", "svg", "jpg", "tiff", "Word (docx)"]


def nom_fichier_sur (texte):
    """ Nom de fichier sans caracteres interdits. """
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(texte)).strip("_") or "plot"


def figure_individuelle (titre, v, largeur = 9.0, hauteur = 4.0):
    """ Graphique de type titre de la variable v seul (avec sa legende ou ses
    statistiques), retrace dans une figure independante, polices du panneau
    appliquees. """
    figure = Figure(figsize = (largeur, hauteur), constrained_layout = True)
    t = traces_graphiques[titre]
    t["tracer"](figure, appliquer_filtres(data_analy), {v: t["variables"][v]})
    appliquer_polices(figure)
    appliquer_bornes(figure, titre, [list(t["variables"]).index(v)])   # memes bornes que dans le panneau
    return figure


def sauver_graphiques ():
    """ Bouton « Save plot » : boite listant les graphiques affiches (cases a
    cocher), choix du format, de la resolution et du dossier ; chaque
    graphique coche est enregistre dans un fichier, ou tous dans un meme
    document Word (format « Word (docx) »). """
    if not traces_graphiques:
        messagebox.showinfo("Save plot", "No plot to save: draw a plot first (button 'Plot').")
        return
    ## tous les graphiques construits : (type, variable) -> parametres
    graphiques = {(titre, v): p for titre, t in traces_graphiques.items() for v, p in t["variables"].items()}
    hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
    boite = nouvelle_boite(hote)
    Label(boite, text = "Save plot", font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 3, sticky = "w", padx = 15, pady = (10, 0))
    Label(boite, text = "Select the plots to save", font = ('arial', 14)).grid(row = 1, column = 0, columnspan = 3, sticky = "w", padx = 15, pady = (0, 6))
    ## graphiques en cases a cocher (tous coches par defaut)
    cadre_cases = Frame(boite, bd = 1, relief = "sunken")
    cadre_cases.grid(row = 2, column = 0, columnspan = 3, sticky = "ew", padx = 15)
    cases = {}
    for (titre, v), p in graphiques.items():
        cases[(titre, v)] = BooleanVar(value = True)
        libelle = titre + "  —  " + v + ("  —  " + p["main"] if p.get("main") else "")
        Checkbutton(cadre_cases, text = libelle, variable = cases[(titre, v)], font = ('arial', 13), anchor = "w").pack(fill = "x", anchor = "w", padx = 4)
    cadre_tout = Frame(boite)
    cadre_tout.grid(row = 3, column = 0, columnspan = 3, sticky = "w", padx = 15, pady = (2, 8))
    tk.Button(cadre_tout, text = "Select all", width = 10, command = lambda: [c.set(True) for c in cases.values()]).pack(side = LEFT, padx = (0, 4))
    tk.Button(cadre_tout, text = "Clear", width = 10, command = lambda: [c.set(False) for c in cases.values()]).pack(side = LEFT)
    ## format, resolution, dossier, nom du document Word
    Label(boite, text = "Format", **ETIQUETTE_BOITE).grid(row = 4, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    choix_format = ttk.Combobox(boite, values = FORMATS_GRAPHIQUE, state = "readonly", width = 14)
    choix_format.set("png")
    choix_format.grid(row = 4, column = 1, sticky = "w", pady = 3)
    Label(boite, text = "Resolution (dpi)", **ETIQUETTE_BOITE).grid(row = 5, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    var_dpi = StringVar(value = "300")
    Spinbox(boite, from_ = 72, to = 1200, increment = 50, textvariable = var_dpi, width = 8).grid(row = 5, column = 1, sticky = "w", pady = 3)
    var_dpi.set("300")
    Label(boite, text = "Folder", **ETIQUETTE_BOITE).grid(row = 6, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    var_dossier = StringVar(value = os.path.expanduser("~"))
    Entry(boite, textvariable = var_dossier, width = 40).grid(row = 6, column = 1, sticky = "ew", pady = 3)

    def parcourir ():
        dossier = filedialog.askdirectory(title = "Folder for the plots", initialdir = var_dossier.get(), parent = boite)
        if dossier:
            var_dossier.set(dossier)

    tk.Button(boite, text = "Browse…", command = parcourir, width = 9).grid(row = 6, column = 2, sticky = "w", padx = (6, 15), pady = 3)
    var_nom_word = StringVar(value = "abos_plots")
    afficher_nom_word = ligne_masquable(boite, 7, "Word file name", Entry(boite, textvariable = var_nom_word, width = 40), "Saved as <name>.docx in the folder")
    choix_format.bind("<<ComboboxSelected>>", lambda event: afficher_nom_word(choix_format.get().startswith("Word")))
    afficher_nom_word(False)
    boite.grid_columnconfigure(1, weight = 1)

    def enregistrer ():
        choisis = [cle for cle in graphiques if cases[cle].get()]
        if not choisis:
            messagebox.showwarning("Save plot", "Check at least one plot.", parent = boite)
            return False
        dossier = var_dossier.get().strip()
        if not os.path.isdir(dossier):
            messagebox.showwarning("Save plot", "The folder does not exist:\n" + dossier, parent = boite)
            return False
        try:
            dpi = int(float(var_dpi.get()))
            if dpi < 50:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Save plot", "The resolution must be an integer (at least 50 dpi).", parent = boite)
            return False
        format_choisi = choix_format.get()
        word = format_choisi.startswith("Word")
        if word:
            chemins = [os.path.join(dossier, nom_fichier_sur(var_nom_word.get()) + ".docx")]
        else:
            ## un nom de fichier distinct par graphique, sans tenir compte de la
            ## casse (systemes de fichiers de macOS et Windows) : suffixe _2, _3...
            chemins, pris = [], set()
            for titre, v in choisis:
                base = nom_fichier_sur(titre + "_" + v)
                nom, k = base, 2
                while nom.lower() in pris:
                    nom, k = base + "_" + str(k), k + 1
                pris.add(nom.lower())
                chemins.append(os.path.join(dossier, nom + "." + format_choisi))
        existants = [c for c in chemins if os.path.exists(c)]
        if existants and not messagebox.askyesno("Save plot", "These files already exist and will be replaced:\n" + "\n".join(os.path.basename(c) for c in existants) + "\n\nContinue?", parent = boite):
            return False
        ## chaque graphique est exporte independamment : un echec n'interrompt
        ## pas les autres et il est signale avec sa cause
        echecs, reussis = [], 0
        document = None
        if word:
            try:
                import io
                from docx import Document                # python-docx, requis pour l'export Word
                from docx.shared import Inches
                document = Document()
                document.add_heading("Plots", level = 1)
            except Exception as erreur:
                messagebox.showerror("Save plot", "The Word document could not be created:\n" + str(erreur), parent = boite)
                return False
        for k, (titre, v) in enumerate(choisis):
            try:
                figure = figure_individuelle(titre, v)
                if word:
                    tampon = io.BytesIO()
                    figure.savefig(tampon, format = "png", dpi = dpi)
                    tampon.seek(0)
                    document.add_picture(tampon, width = Inches(6.3))
                    document.add_paragraph(titre + " — " + (graphiques[(titre, v)].get("main") or v)).runs[0].italic = True
                else:
                    figure.savefig(chemins[k], format = "jpeg" if format_choisi == "jpg" else format_choisi, dpi = dpi)
                    if not os.path.isfile(chemins[k]):
                        raise OSError("file not written")
                reussis += 1
            except Exception as erreur:
                echecs.append(titre + " — " + v + " : " + str(erreur))
        if word and reussis:
            try:
                document.save(chemins[0])
            except Exception as erreur:
                messagebox.showerror("Save plot", "The Word document could not be saved:\n" + str(erreur), parent = boite)
                return False
        texte = str(reussis) + " / " + str(len(choisis)) + " plot(s) saved in:\n" + dossier
        if echecs:
            messagebox.showwarning("Save plot", texte + "\n\nNot saved:\n" + "\n".join(echecs), parent = boite)
            return reussis > 0
        messagebox.showinfo("Save plot", texte, parent = boite)
        return True

    def fermer ():
        boite.destroy()

    def sauver ():
        if enregistrer():
            fermer()

    cadre_b = Frame(boite)
    cadre_b.grid(row = 9, column = 0, columnspan = 3, pady = 10)
    tk.Button(cadre_b, text = "Save", command = sauver, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre_b, text = "Cancel", command = fermer, width = 10).pack(side = LEFT, padx = 5)


def dialogue_variables_reponses (case, titre, memoire, requises, exclues, boite_parametres, resume, tracer_figure,
                                 selection = None):
    """ Premier niveau commun aux graphiques (« Bar plot », « Box plot », « Histogram », « Trajectory ») :
    variables reponses en cases a cocher ; cocher une variable ouvre la boite
    de second niveau boite_parametres(hote, fenetre, donnees, candidates, v,
    parametres, enregistrer, annuler). « Plot » appelle tracer_figure(figure,
    donnees, variables) qui renvoie la liste des messages (une ligne de
    graphique par variable). selection(serie, nom) : variables proposees
    (toutes si None).
    memoire : {"variables": variables cochees au dernier trace et leurs
    parametres, "parametres": derniers parametres enregistres pour chaque
    variable}. Les parametres enregistres pre-remplissent la boite de second
    niveau, meme apres avoir decoche la variable ou ferme la boite ; ils sont
    sauvegardes sur le disque (FICHIER_PARAMETRES_GRAPHIQUES). """
    donnees = appliquer_filtres(data_analy)
    noms = [str(c) for c in donnees.columns]
    absentes = [c for c in requises if c not in noms]
    if absentes:
        messagebox.showerror(titre, "The data must contain the columns " + ", ".join("'" + c + "'" for c in requises) + ".\nMissing: " + ", ".join(absentes))
        case.set(False)
        return
    candidates = [n for n in noms if n not in exclues and (selection is None or selection(donnees[n], n))]
    if len(candidates) == 0:
        messagebox.showwarning(titre, "No variable available for this plot.")
        case.set(False)
        return
    hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
    fenetre = nouvelle_boite(hote)
    Label(fenetre, text = titre, font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, sticky = "w", padx = 15, pady = (10, 0))
    Label(fenetre, text = "Response variables", font = ('arial', 14)).grid(row = 1, column = 0, sticky = "w", padx = 15)
    Label(fenetre, text = "Check a variable to define the parameters of its plot", **AIDE_BOITE).grid(row = 2, column = 0, sticky = "w", padx = 15, pady = (0, 4))

    ## variables reponses en cases a cocher (zone defilante)
    zone = Frame(fenetre, bd = 1, relief = "sunken")
    zone.grid(row = 3, column = 0, sticky = "nsew", padx = 15)
    toile = Canvas(zone, highlightthickness = 0, width = 520, height = min(max(len(candidates), 4), 12) * 26)
    defil = ttk.Scrollbar(zone, orient = "vertical", command = toile.yview)
    toile.configure(yscrollcommand = defil.set)
    toile.pack(side = LEFT, fill = BOTH, expand = True)
    defil.pack(side = LEFT, fill = "y")
    interieur = Frame(toile)
    fen_int = toile.create_window((0, 0), window = interieur, anchor = "nw")
    interieur.bind("<Configure>", lambda event: toile.configure(scrollregion = toile.bbox("all")))
    toile.bind("<Configure>", lambda event: toile.itemconfigure(fen_int, width = event.width))
    molette = lambda event: toile.yview_scroll(-1 * (event.delta if abs(event.delta) < 10 else event.delta // 120), "units")
    zone.bind("<Enter>", lambda event: toile.bind_all("<MouseWheel>", molette))
    zone.bind("<Leave>", lambda event: toile.unbind_all("<MouseWheel>"))

    ## parametres des variables cochees (dans l'ordre ou elles ont ete cochees)
    choisies = {v: dict(p) for v, p in (memoire["variables"] or {}).items() if v in candidates}
    cases, resumes = {}, {}

    def resumer (v):
        resumes[v].configure(text = "" if v not in choisies else "  →  " + resume(choisies[v]))

    def clic_case (v):
        if not cases[v].get():
            choisies.pop(v, None)
            resumer(v)
            return

        def enregistrer (parametres):
            choisies[v] = parametres
            memoire["parametres"][v] = parametres     # memorise pour le prochain parametrage
            sauver_parametres_graphiques()
            resumer(v)

        def annuler ():
            if v not in choisies:
                cases[v].set(False)          # variable non parametree : decochee

        boite_parametres(hote, fenetre, donnees, candidates, v, choisies.get(v) or memoire["parametres"].get(v), enregistrer, annuler)

    for v in candidates:
        ligne = Frame(interieur)
        ligne.pack(fill = "x", anchor = "w")
        cases[v] = BooleanVar(value = v in choisies)
        Checkbutton(ligne, text = v, variable = cases[v], command = lambda v = v: clic_case(v), font = ('arial', 13), anchor = "w").pack(side = LEFT)
        resumes[v] = Label(ligne, text = "", font = ('arial', 11), fg = "gray40", anchor = "w")
        resumes[v].pack(side = LEFT)
        resumer(v)
    fenetre.grid_columnconfigure(0, weight = 1)

    def fermer_dialogue ():
        toile.unbind_all("<MouseWheel>")
        fenetre.destroy()

    def tracer ():
        variables = {v: choisies[v] for v in choisies if cases[v].get()}
        if len(variables) == 0:
            messagebox.showwarning(titre, "Check at least one response variable.", parent = fenetre)
            return
        ## ce type est ajoute (ou mis a jour) parmi les graphiques construits
        ## (proposes par « Save plot »), puis affiche dans le panneau
        precedent = traces_graphiques.get(titre)
        traces_graphiques[titre] = {"tracer": tracer_figure, "variables": variables}
        try:
            afficher_type(titre)
        except Exception as erreur:
            if precedent is None:
                traces_graphiques.pop(titre, None)
            else:
                traces_graphiques[titre] = precedent
            effacer_figure()
            messagebox.showerror(titre, "The plot could not be drawn:\n" + str(erreur), parent = fenetre)
            return
        memoire["variables"] = variables
        sauver_parametres_graphiques()
        fermer_dialogue()

    def annuler_dialogue ():
        if titre not in traces_graphiques:       # type encore jamais trace : decoche
            case.set(False)
        fermer_dialogue()

    cadre = Frame(fenetre)
    cadre.grid(row = 4, column = 0, pady = 12)
    tk.Button(cadre, text = "Plot", command = tracer, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre, text = "Cancel", command = annuler_dialogue, width = 10).pack(side = LEFT, padx = 5)


def boutons_boite (boite, fenetre, ligne, enregistrer, annuler):
    """ Boutons « Save » / « Cancel » d'une boite de second niveau.
    enregistrer() renvoie True si la boite peut etre fermee. """
    def fermer ():
        boite.destroy()
        if fenetre.winfo_exists():
            fenetre.grab_set()

    def sauver ():
        if enregistrer():
            fermer()

    def abandonner ():
        annuler()
        fermer()

    cadre_b = Frame(boite)
    cadre_b.grid(row = ligne, column = 0, columnspan = 2, pady = 10)
    tk.Button(cadre_b, text = "Save", command = sauver, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre_b, text = "Cancel", command = abandonner, width = 10).pack(side = LEFT, padx = 5)


##-----------------------------------------------------------------------------
##  Second niveau de « Trajectory »
##-----------------------------------------------------------------------------
def boite_parametres_trajectoire (hote, fenetre, donnees, candidates, v, p0, enregistrer, annuler):
    """ Parametres du graphique de trajectoires de la variable v : titres,
    epaisseur des lignes, variable de groupe, labels, breaks (groupe
    quantitatif), titre de la legende (avec groupe) ou couleur (sans groupe). """
    if p0 is None:
        p0 = dict(ylab = VARIABLES_DEFAUT[v][0] if v in VARIABLES_DEFAUT else v,
                  main = v + " trajectories",           # titre : nom de la variable + « trajectories »
                  xlab = "Time (month)", lwd = 1.0, couleur = "black", groupe = None,
                  labels_texte = "", breaks_texte = "", titre_legende = "")
    boite = nouvelle_boite(hote)
    Label(boite, text = v, font = ('arial', 14, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 2))
    Label(boite, text = "Parameters of the trajectory plot", font = ('arial', 13)).grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 8))
    var_main = champ_boite(boite, 2, "Title", p0["main"])
    var_ylab = champ_boite(boite, 3, "Y-axis label", p0["ylab"])
    Label(boite, text = "$...$ for mathematical notation, e.g.  BMI (kg/m$^2$)", **AIDE_BOITE).grid(row = 4, column = 1, sticky = "w", padx = (0, 15))
    var_xlab = champ_boite(boite, 5, "X-axis label", p0["xlab"])

    ## groupe et legende, propres a cette variable
    Label(boite, text = "Group variable", **ETIQUETTE_BOITE).grid(row = 6, column = 0, sticky = "w", padx = (15, 6), pady = (10, 3))
    choix_groupe = ttk.Combobox(boite, values = ["None"] + [n for n in candidates if n != v], state = "readonly", width = 32)
    choix_groupe.grid(row = 6, column = 1, sticky = "ew", padx = (0, 15), pady = (10, 3))
    choix_groupe.set(p0["groupe"] if p0["groupe"] in candidates and p0["groupe"] != v else "None")
    var_labels = champ_boite(boite, 7, "Labels", p0["labels_texte"])
    Label(boite, text = "e.g.  0=Non diabetic; 1=Type 1; 2=Type 2   or   < 40; 40-50; >= 50  (order of the levels)", **AIDE_BOITE).grid(row = 8, column = 1, sticky = "w", padx = (0, 15))
    var_breaks = StringVar(value = p0["breaks_texte"])
    afficher_breaks = ligne_masquable(boite, 9, "Breaks", Entry(boite, textvariable = var_breaks, width = 34), "e.g.  -Inf, 40, 50, Inf   (classes [a, b))")
    var_titre = StringVar(value = p0.get("titre_legende", ""))
    afficher_titre = ligne_masquable(boite, 11, "Legend title", Entry(boite, textvariable = var_titre, width = 34), "Empty: name of the group variable")
    ## couleur (sans groupe) : meme emplacement que Breaks
    var_couleur = StringVar(value = p0.get("couleur", "black"))
    cadre_couleur = Frame(boite)
    echantillon = Label(cadre_couleur, text = "      ", background = var_couleur.get(), relief = "solid", bd = 1)
    echantillon.pack(side = LEFT, padx = (0, 8))

    def choisir_couleur ():
        choix = colorchooser.askcolor(color = var_couleur.get(), title = "Color of the trajectories", parent = boite)
        if choix and choix[1]:
            var_couleur.set(choix[1])
            echantillon.configure(background = choix[1])

    tk.Button(cadre_couleur, text = "Choose…", command = choisir_couleur, width = 9).pack(side = LEFT)
    afficher_couleur = ligne_masquable(boite, 9, "Color", cadre_couleur)
    ## epaisseur des lignes
    Label(boite, text = "Line width", **ETIQUETTE_BOITE).grid(row = 13, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    var_lwd = StringVar(value = formater_valeur_stat(p0.get("lwd", 1.0)))
    Spinbox(boite, from_ = 0.1, to = 10, increment = 0.1, textvariable = var_lwd, width = 8).grid(row = 13, column = 1, sticky = "w", padx = (0, 15), pady = 3)

    def maj_groupe (event = None):
        g = choix_groupe.get()
        afficher_couleur(g == "None")
        afficher_titre(g != "None")
        quantitative = g != "None" and est_quantitative(donnees[g], g)
        afficher_breaks(quantitative)
        if not quantitative:
            var_breaks.set("")

    choix_groupe.bind("<<ComboboxSelected>>", maj_groupe)
    maj_groupe()
    boite.grid_columnconfigure(1, weight = 1)

    def valider ():
        groupe = None if choix_groupe.get() == "None" else choix_groupe.get()
        try:
            labels = lire_labels(var_labels.get())
            breaks = lire_breaks(var_breaks.get())
        except ValueError as erreur:
            messagebox.showwarning("Trajectory", "Breaks: " + str(erreur), parent = boite)
            return False
        if groupe is None and labels is not None:
            messagebox.showwarning("Trajectory", "Labels require a group variable.", parent = boite)
            return False
        if groupe is not None:
            try:                              # controle immediat des labels (nombre de niveaux)
                coder_groupe(donnees, groupe, labels = labels, breaks = breaks)
            except ValueError as erreur:
                messagebox.showwarning("Trajectory", str(erreur), parent = boite)
                return False
        try:
            lwd = float(var_lwd.get().strip().replace(",", "."))
            if lwd <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Trajectory", "The line width must be a positive number.", parent = boite)
            return False
        enregistrer(dict(ylab = var_ylab.get().strip() or v, main = var_main.get().strip(),
                         xlab = var_xlab.get().strip() or "Time (month)", lwd = lwd, couleur = var_couleur.get(),
                         groupe = groupe, labels = labels, breaks = breaks, titre_legende = var_titre.get().strip(),
                         labels_texte = var_labels.get(), breaks_texte = var_breaks.get()))
        return True

    boutons_boite(boite, fenetre, 14, valider, annuler)


def resume_trajectoire (p):
    return p["main"] + ("  |  group: " + p["groupe"] if p["groupe"] else "")


def dialogue_trajectoire (case_trajectory):
    """ « Trajectory » : premier niveau commun + second niveau des trajectoires. """
    dialogue_variables_reponses(case_trajectory, "Trajectory", parametres_trajectoire, ("Patient", "Time"),
                                ("Patient", "Time"), boite_parametres_trajectoire, resume_trajectoire, trace_trajectoires)


##-----------------------------------------------------------------------------
##  « Box plot » : traduction de plot_poids() (ggboxplot de ggpubr)
##-----------------------------------------------------------------------------
## Palette « jco » de ggsci (utilisee par ggboxplot(palette = "jco"))
PALETTE_JCO = ["#0073C2", "#EFC000", "#868686", "#CD534C", "#7AA6DC", "#003C67", "#8F7700", "#3B3B3B", "#A73030", "#4A6990"]
parametres_boxplot = {"variables": None, "parametres": {}}
## Bloc « Mean point » (panneau de droite, « Box plot ») : moyenne de chaque
## distribution affichee par un point, de couleur choisie
point_moyenne = {"afficher": False, "couleur": "red", "taille": 6}   # taille : diametre du point (points typographiques)
COULEURS_POINT_MOYENNE = ["red", "black", "blue", "darkgreen", "orange", "purple", "saddlebrown", "gray40"]


MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "un", "une",
              "depuis", "plus", "sans", "avec", "pour", "par", "sur",
              "of", "the", "and", "with", "without", "for", "in", "on", "to"}
LONGUEUR_MAX_MODALITE = 12        # axe des x : au-dela, mots cles
LONGUEUR_MAX_LEGENDE = 20         # legende (colonne de droite, plus large)


def mots_cles (modalites, longueur_max = None):
    """ Libelles courts des modalites trop longues : on garde les mots qui
    distinguent chaque modalite. Mots vides et mots (ou radicaux de 5 lettres)
    communs a toutes les modalites retires ; un libelle encore trop long garde
    son premier mot entier, les suivants abreges (4 lettres + « . »). Des
    qu'une modalite est trop longue, toutes sont raccourcies de la meme facon. Les
    libelles d'origine sont conserves s'ils sont tous courts ou si les mots
    cles ne distinguent plus les modalites. """
    longueur_max = LONGUEUR_MAX_MODALITE if longueur_max is None else longueur_max
    textes = [str(m) for m in modalites]
    if len(textes) == 0 or all(len(t) <= longueur_max for t in textes):
        return textes
    mots = [[w for w in re.split(r"[\s_\-/.,;:()]+", t) if w] for t in textes]
    radical = lambda w: w.lower()[:5]
    communs = set.intersection(*[{radical(w) for w in ws} for ws in mots]) if len(mots) > 1 else set()
    courts = []
    for ws in mots:                    # meme traitement pour toutes les modalites (coherence)
        cles = [w for w in ws if w.lower() not in MOTS_VIDES and radical(w) not in communs] or ws
        libelle = " ".join(cles)
        if len(libelle) > longueur_max:
            libelle = " ".join([cles[0]] + [w[:4] + "." if len(w) > 4 else w for w in cles[1:]])
        courts.append(libelle[:1].upper() + libelle[1:])
    return courts if len(set(courts)) == len(set(textes)) else textes


def couper_r (x, breaks, labels = None):
    """ cut(x, breaks, labels) de R (intervalles (a, b], borne inferieure exclue).
    Renvoie (serie de libelles, niveaux dans l'ordre). """
    b = np.asarray(sorted(breaks), dtype = float)
    if labels is None:
        labels = ["(" + formater_borne(b[k]) + "," + formater_borne(b[k + 1]) + "]" for k in range(len(b) - 1)]
    elif len(labels) != len(b) - 1:
        raise ValueError("'labels' must have " + str(len(b) - 1) + " elements (one per class).")
    xv = vers_numerique(x).to_numpy(dtype = float)
    idx = np.searchsorted(b, xv, side = "left") - 1           # a < x <= b
    valide = (~np.isnan(xv)) & (idx >= 0) & (idx <= len(b) - 2)
    serie = pd.Series([labels[k] if ok else np.nan for k, ok in zip(idx, valide)], index = x.index, dtype = "object")
    return serie, list(labels)


def niveaux_facteur (serie):
    """ Niveaux de as.factor() : valeurs distinctes triees (numeriquement si possible). """
    valeurs = serie.dropna().unique().tolist()
    try:
        return sorted(valeurs, key = float)
    except (TypeError, ValueError):
        return sorted(valeurs, key = lambda v: (str(v).lower(), str(v)))   # ordre de R (sans tenir compte de la casse)


def style_ggpubr (ax):
    """ Aspect de theme_pubr() : axes gauche et bas seulement, sans grille. """
    for cote in ("top", "right"):
        ax.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        ax.spines[cote].set_linewidth(0.9)
        ax.spines[cote].set_color("black")
    ax.tick_params(direction = "out", length = 4, width = 0.9, labelsize = 10, colors = "black")
    ax.grid(False)
    ax.set_facecolor("white")


def plot_poids (ax, data, var_groupe = None, titre_legende = None, var_x = "AgeJourIntervention_cl",
                var_y = "Poids", lab_x = "Temps (mois)", lab_y = "Poids (Kg)",
                niveaux_x = None, ax_legende = None, libelles_x_imposes = False, libelles_groupe = None):
    """ Traduction de plot_poids() : boites a moustaches de var_y selon var_x,
    colorees par var_groupe (palette « jco », remplissage gray90), boites des
    groupes cote a cote pour chaque modalite de var_x.
    ax_legende : axe dedie a la legende (colonne de droite).
    libelles_x_imposes : libelles de classes donnes par l'utilisateur (pas
    de raccourcissement) ; sinon les modalites trop longues sont remplacees
    par leurs mots cles (axe des x et legende).
    libelles_groupe : libelles des modalites du groupe, comme pour
    « Trajectory » : dictionnaire (valeur -> libelle, dans l'ordre voulu ;
    les valeurs non citees sont exclues) ou liste dans l'ordre des niveaux.
    Renvoie (lignes retirees pour valeur manquante, lignes exclues par les
    libelles). """
    from matplotlib.patches import Patch
    d = data[[c for c in (var_x, var_y, var_groupe) if c is not None]].copy()
    d[var_y] = vers_numerique(d[var_y])
    n_avant = len(d)
    d = d.dropna()
    n_retirees = n_avant - len(d)
    cle = lambda v: cle_modalite(v) if not isinstance(v, str) else v
    d[var_x] = d[var_x].map(cle)
    niveaux_x = [n for n in (niveaux_x or niveaux_facteur(d[var_x]))]
    n_exclues = 0
    if var_groupe is not None:
        d[var_groupe] = d[var_groupe].map(cle)
        niveaux_g = niveaux_facteur(d[var_groupe])
        noms_g = mots_cles(niveaux_g, LONGUEUR_MAX_LEGENDE)
        if isinstance(libelles_groupe, dict):          # « valeur=libelle » : ordre et libelles imposes
            d[var_groupe] = d[var_groupe].astype(str)
            presents = set(d[var_groupe])
            niveaux_g = [str(k) for k in libelles_groupe if str(k) in presents]
            n_avant_lib = len(d)
            d = d[d[var_groupe].isin(niveaux_g)]
            n_exclues = n_avant_lib - len(d)
            noms_g = [str(libelles_groupe[k]) for k in libelles_groupe if str(k) in presents]
        elif libelles_groupe is not None:              # liste dans l'ordre des niveaux
            if len(libelles_groupe) != len(niveaux_g):
                raise ValueError("'labels' must have " + str(len(niveaux_g)) + " elements (levels: "
                                 + ", ".join(str(n) for n in niveaux_g) + ").")
            noms_g = [str(l) for l in libelles_groupe]
    else:
        niveaux_g = [None]
    couleurs = [PALETTE_JCO[k % len(PALETTE_JCO)] for k in range(len(niveaux_g))] if var_groupe is not None else ["black"]
    n_g = len(niveaux_g)
    largeur = 0.8 / n_g                                          # position_dodge(0.8)
    for j, (g, c) in enumerate(zip(niveaux_g, couleurs)):
        series, positions = [], []
        for i, nx in enumerate(niveaux_x):
            masque = d[var_x] == nx
            if g is not None:
                masque &= d[var_groupe] == g
            y = d.loc[masque, var_y].to_numpy(dtype = float)
            if len(y):
                series.append(y)
                positions.append(i - 0.4 + (j + 0.5) * largeur)
        if series:
            ax.boxplot(series, positions = positions, widths = largeur * 0.9, patch_artist = True, manage_ticks = False,
                       boxprops = dict(facecolor = "#E5E5E5", edgecolor = c, linewidth = 1),   # fill = "gray90"
                       medianprops = dict(color = c, linewidth = 1.6), whiskerprops = dict(color = c, linewidth = 1),
                       capprops = dict(visible = False),
                       flierprops = dict(marker = "o", markersize = 3, markerfacecolor = c, markeredgecolor = c))
            if point_moyenne["afficher"]:                    # bloc « Mean point » : moyenne de chaque boite
                ax.scatter(positions, [float(np.mean(y)) for y in series], marker = "o", s = float(point_moyenne.get("taille", 6)) ** 2,
                           color = point_moyenne["couleur"], edgecolors = "white", linewidths = 0.6, zorder = 4)
    ax.set_xticks(range(len(niveaux_x)))
    ax.set_xticklabels(niveaux_x if libelles_x_imposes else mots_cles(niveaux_x))   # modalites longues : mots cles
    ax.set_xlim(-0.6, len(niveaux_x) - 0.4)
    style_ggpubr(ax)
    ax.set_xlabel(lab_x, fontsize = 11)
    ax.set_ylabel(lab_y, fontsize = 11)
    if var_groupe is not None and ax_legende is not None:
        poignees = [Patch(facecolor = "#E5E5E5", edgecolor = c, linewidth = 1.2) for c in couleurs]
        legende = ax_legende.legend(poignees, noms_g, title = titre_legende or var_groupe,
                                    loc = "center left", borderaxespad = 0, frameon = False,
                                    prop = {"weight": "bold", "size": 10}, title_fontsize = 11)
        legende.get_title().set_fontweight("bold")
        legende._legend_box.align = "left"
    return n_retirees, n_exclues


def trace_boxplots (figure, data, variables):
    """ Un graphique plot_poids() par variable reponse. Mise en page comme
    « Trajectory » : deux colonnes, le graphique a gauche et sa legende a
    droite, une ligne par variable.
    variables : variable -> var_x, breaks, labels, lab_x, lab_y, groupe,
    titre_legende. Renvoie la liste des messages. """
    messages = []
    grille = figure.add_gridspec(len(variables), 2, width_ratios = [4, 1.3])
    for k, (v, p) in enumerate(variables.items()):
        ax = figure.add_subplot(grille[k, 0])               # colonne de gauche : graphique
        ax_leg = figure.add_subplot(grille[k, 1])           # colonne de droite : legende
        ax_leg.axis("off")
        d = data.copy()
        var_x, niveaux_x = p["var_x"], None
        if p.get("breaks") is not None:                     # var_x quantitative decoupee en classes
            d["_classes_x"], niveaux_x = couper_r(d[var_x], p["breaks"], p.get("labels"))
            var_x = "_classes_x"
        n, n_exclues = plot_poids(ax, d, var_groupe = p.get("groupe"), titre_legende = p.get("titre_legende"), var_x = var_x,
                                  var_y = v, lab_x = p.get("lab_x", p["var_x"]), lab_y = p.get("lab_y", v),
                                  niveaux_x = niveaux_x, ax_legende = ax_leg, libelles_x_imposes = p.get("labels") is not None,
                                  libelles_groupe = p.get("labels_groupe"))
        if n:
            messages.append("[" + v + "] " + str(n) + " row(s) with missing values removed.")
        if n_exclues:
            messages.append("[" + v + "] " + str(n_exclues) + " row(s) excluded: group value not listed in the group labels.")
    return messages


def boite_parametres_boxplot (hote, fenetre, donnees, candidates, v, p0, enregistrer, annuler):
    """ Parametres de plot_poids() pour la variable reponse v (var_y) :
    variable en abscisse (var_x) et, si elle est quantitative, ses classes
    (breaks, labels) ; titres des axes ; variable de groupe (couleur),
    titre de la legende. """
    autres = [n for n in candidates if n != v]
    if p0 is None:
        x0 = "Time" if "Time" in autres else (autres[0] if autres else "")
        p0 = dict(var_x = x0, breaks_texte = "", labels_texte = "", lab_x = "",
                  lab_y = VARIABLES_DEFAUT[v][0] if v in VARIABLES_DEFAUT else v,
                  groupe = None, titre_legende = "")
    p0.setdefault("labels_groupe_texte", "")
    boite = nouvelle_boite(hote)
    Label(boite, text = v, font = ('arial', 14, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 2))
    Label(boite, text = "Parameters of the box plot", font = ('arial', 13)).grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 8))
    ## abscisse
    Label(boite, text = "X variable", **ETIQUETTE_BOITE).grid(row = 2, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    choix_x = ttk.Combobox(boite, values = autres, state = "readonly", width = 32)
    choix_x.grid(row = 2, column = 1, sticky = "ew", padx = (0, 15), pady = 3)
    if p0["var_x"] in autres:
        choix_x.set(p0["var_x"])
    var_breaks = StringVar(value = p0["breaks_texte"])
    afficher_breaks = ligne_masquable(boite, 3, "Breaks", Entry(boite, textvariable = var_breaks, width = 34),
                                      "Quantitative X variable, e.g.  -Inf, 40, 50, Inf   (classes (a, b])")
    var_labels = StringVar(value = p0["labels_texte"])
    afficher_labels = ligne_masquable(boite, 5, "Labels", Entry(boite, textvariable = var_labels, width = 34),
                                      "One per class, e.g.  ≤ 40; ]40 ; 50]; > 50   (empty: (a,b])")
    var_lab_x = champ_boite(boite, 7, "X-axis label", p0["lab_x"])
    Label(boite, text = "Empty: name of the X variable", **AIDE_BOITE).grid(row = 8, column = 1, sticky = "w", padx = (0, 15))
    var_lab_y = champ_boite(boite, 9, "Y-axis label", p0["lab_y"])
    ## groupe (couleur) et legende
    Label(boite, text = "Group variable", **ETIQUETTE_BOITE).grid(row = 10, column = 0, sticky = "w", padx = (15, 6), pady = (10, 3))
    choix_groupe = ttk.Combobox(boite, values = ["None"] + autres, state = "readonly", width = 32)
    choix_groupe.grid(row = 10, column = 1, sticky = "ew", padx = (0, 15), pady = (10, 3))
    choix_groupe.set(p0["groupe"] if p0["groupe"] in autres else "None")
    ## libelles des modalites du groupe, comme dans « Trajectory »
    var_labels_groupe = StringVar(value = p0["labels_groupe_texte"])
    afficher_labels_groupe = ligne_masquable(boite, 11, "Group labels", Entry(boite, textvariable = var_labels_groupe, width = 34),
                                             "e.g.  0=Non diabetic; 1=Type 1; 2=Type 2   or   No; Yes  (order of the levels)")
    var_titre = StringVar(value = p0["titre_legende"])
    afficher_titre = ligne_masquable(boite, 13, "Legend title", Entry(boite, textvariable = var_titre, width = 34), "Empty: name of the group variable")

    def maj_x (event = None):
        x = choix_x.get()
        quantitative = x != "" and est_quantitative(donnees[x], x)
        afficher_breaks(quantitative)
        afficher_labels(quantitative)
        if not quantitative:
            var_breaks.set(""); var_labels.set("")

    def maj_groupe (event = None):
        avec = choix_groupe.get() != "None"
        afficher_titre(avec)
        afficher_labels_groupe(avec)
        if not avec:
            var_labels_groupe.set("")

    choix_x.bind("<<ComboboxSelected>>", maj_x)
    choix_groupe.bind("<<ComboboxSelected>>", maj_groupe)
    maj_x(); maj_groupe()
    boite.grid_columnconfigure(1, weight = 1)

    def valider ():
        var_x = choix_x.get()
        if var_x == "":
            messagebox.showwarning("Box plot", "Select the X variable.", parent = boite)
            return False
        groupe = None if choix_groupe.get() == "None" else choix_groupe.get()
        if groupe == var_x:
            messagebox.showwarning("Box plot", "The group variable must differ from the X variable.", parent = boite)
            return False
        try:
            breaks = lire_breaks(var_breaks.get())
        except ValueError as erreur:
            messagebox.showwarning("Box plot", "Breaks: " + str(erreur), parent = boite)
            return False
        labels = [m.strip() for m in var_labels.get().split(";") if m.strip() != ""] or None
        if labels is not None and breaks is None:
            messagebox.showwarning("Box plot", "Labels require breaks.", parent = boite)
            return False
        if breaks is not None:
            try:
                couper_r(donnees[var_x], breaks, labels)
            except ValueError as erreur:
                messagebox.showwarning("Box plot", str(erreur), parent = boite)
                return False
        labels_groupe = lire_labels(var_labels_groupe.get()) if groupe is not None else None
        if labels_groupe is not None:                  # controle immediat, comme pour « Trajectory »
            cle = lambda val: cle_modalite(val) if not isinstance(val, str) else val
            niveaux_g = niveaux_facteur(donnees[groupe].dropna().map(cle))
            if isinstance(labels_groupe, dict):
                if not set(str(k) for k in labels_groupe) & set(str(n) for n in niveaux_g):
                    messagebox.showwarning("Box plot", "None of the values in the group labels exists in '" + groupe
                                           + "' (levels: " + ", ".join(str(n) for n in niveaux_g) + ").", parent = boite)
                    return False
            elif len(labels_groupe) != len(niveaux_g):
                messagebox.showwarning("Box plot", "'labels' must have " + str(len(niveaux_g)) + " elements (levels: "
                                       + ", ".join(str(n) for n in niveaux_g) + ").", parent = boite)
                return False
        enregistrer(dict(var_x = var_x, breaks = breaks, labels = labels, lab_x = var_lab_x.get().strip() or var_x,
                         lab_y = var_lab_y.get().strip() or v, groupe = groupe, titre_legende = var_titre.get().strip(),
                         breaks_texte = var_breaks.get(),
                         labels_texte = var_labels.get(),
                         labels_groupe = labels_groupe, labels_groupe_texte = var_labels_groupe.get()))
        return True

    boutons_boite(boite, fenetre, 15, valider, annuler)


def resume_boxplot (p):
    return "x: " + p["var_x"] + ("  |  group: " + p["groupe"] if p["groupe"] else "")


def dialogue_boxplot (case_boxplot):
    """ « Box plot » : premier niveau commun + second niveau de plot_poids(). """
    dialogue_variables_reponses(case_boxplot, "Box plot", parametres_boxplot, (), ("Patient",),
                                boite_parametres_boxplot, resume_boxplot, trace_boxplots)


##-----------------------------------------------------------------------------
##  « Bar plot » : traduction de barplot_function(), plot_frequences() et
##  libelles_classes()
##-----------------------------------------------------------------------------
parametres_barplot = {"variables": None, "parametres": {}}
COULEUR_BARRES = "#B3B3B3"         # « gray70 », couleur passee par barplot_function()


def libelles_classes (bornes):
    """ libelles_classes() : « ≤ 40 », « ]40 ; 50] », « > 50 » (intervalles fermes a droite). """
    libelles = []
    for inf, sup in zip(bornes[:-1], bornes[1:]):
        if np.isinf(inf) and inf < 0:
            libelles.append("≤ " + formater_borne(sup))
        elif np.isinf(sup) and sup > 0:
            libelles.append("> " + formater_borne(inf))
        else:
            libelles.append("]" + formater_borne(inf) + " ; " + formater_borne(sup) + "]")
    return libelles


def plot_frequences (ax, x, lab_x, lab_y = "Frequency (%)", couleur = None,
                     niveaux = None, raccourcir = True):
    """ plot_frequences() : diagramme en barres verticales des frequences (%)
    de x, valeurs manquantes comprises (« NA »), pourcentages arrondis a 0,1
    inscrits dans le haut des barres. Pas de barres horizontales : au-dela de
    5 modalites, les libelles de l'axe sont inclines.
    niveaux : ordre des modalites (classes) ; raccourcir : mots cles des
    modalites trop longues. Renvoie (libelles, effectifs, pourcentages). """
    if couleur is None:
        couleur = "#009ACD" if pd.api.types.is_numeric_dtype(x) else COULEUR_BARRES   # deepskyblue3 / gray70
    valeurs = x.map(lambda v: "NA" if pd.isna(v) else (v if isinstance(v, str) else cle_modalite(v)))
    ordre = list(niveaux) if niveaux is not None else niveaux_facteur(valeurs[valeurs != "NA"])
    if (valeurs == "NA").any():
        ordre.append("NA")
    effectifs = valeurs.value_counts()
    ordre = [m for m in ordre if m in effectifs.index]          # table() : modalites observees
    pourcentages = np.array([100 * effectifs[m] / len(valeurs) for m in ordre])
    libelles = mots_cles(ordre) if raccourcir else ordre
    texte = lambda p: ("%.1f" % p).rstrip("0").rstrip(".")
    positions = np.arange(len(ordre))
    style_ggpubr(ax)                                             # theme_classic()
    ax.bar(positions, pourcentages, color = couleur, width = 0.9)
    for xp, p in zip(positions, pourcentages):                  # vjust = 1.6 : dans le haut de la barre
        ax.text(xp, p - 0.03 * pourcentages.max(), texte(p), ha = "center", va = "top", color = "#8B2323",
                fontsize = 10 if len(ordre) <= 8 else 8)
    ax.set_xticks(positions)
    if len(ordre) > 5:
        ax.set_xticklabels(libelles, rotation = 45, ha = "right", rotation_mode = "anchor")
    else:
        ax.set_xticklabels(libelles)
    ax.set_xlim(-0.6, len(ordre) - 0.4)
    ax.set_xlabel(lab_x, fontsize = 11)
    ax.set_ylabel(lab_y, fontsize = 11)
    return libelles, [int(effectifs[m]) for m in ordre], list(pourcentages)


def dessiner_tableau (ax, entetes, lignes, largeurs, total = False):
    """ Tableau de la colonne de droite (axe sans cadre) : en-tete en gras et
    filet dessous ; si total, filet avant la derniere ligne mise en gras.
    Premiere colonne alignee a gauche, nombres a droite. """
    ax.axis("off")
    tableau = ax.table(cellText = lignes, colLabels = entetes, loc = "center", colWidths = largeurs)
    tableau.auto_set_font_size(False)
    tableau.set_fontsize(9)
    tableau.scale(1, 1.3)
    derniere = len(lignes)
    for (i, j), cellule in tableau.get_celld().items():
        cellule.set_edgecolor("black")
        cellule.set_linewidth(0.8)
        cellule.visible_edges = "B" if i == 0 or (total and i == derniere - 1) else ""
        cellule.get_text().set_horizontalalignment("left" if j == 0 else "right")
        cellule.PAD = 0.04
        if i == 0 or (total and i == derniere):
            cellule.set_text_props(fontweight = "bold")
    tableau.cellules_grasses = {c for c in tableau.get_celld() if c[0] == 0 or (total and c[0] == derniere)}


def tableau_statistiques (ax, libelles, effectifs, pourcentages):
    """ Colonne de droite de « Bar plot » : effectif et pourcentage de chaque
    modalite (ou classe), puis le total. """
    lignes = [[l, str(n), ("%.1f" % p)] for l, n, p in zip(libelles, effectifs, pourcentages)]
    lignes.append(["Total", str(sum(effectifs)), "100"])
    dessiner_tableau(ax, ["Modality", "n", "%"], lignes, [0.56, 0.22, 0.22], total = True)


def trace_barplots (figure, data, variables):
    """ barplot_function() : un diagramme des frequences par variable. Mise en
    page en deux colonnes, comme les autres graphiques : le diagramme a gauche
    et, a droite, l'effectif et le pourcentage de chaque modalite ou classe.
    Les variables a moins de deux modalites sont ignorees.
    variables : variable -> lab_x, lab_y, breaks, labels,
    couleur, unite (« rows » : une ligne = une observation ; « patients » :
    premiere valeur non manquante de chaque patient). Renvoie les messages. """
    messages = []
    series = {}
    for v, p in variables.items():
        if p.get("unite") == "patients" and "Patient" in data.columns:
            x = data.groupby("Patient", sort = False)[v].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
        else:
            x = data[v]
        niveaux = None
        if p.get("breaks") is not None:                     # classes d'une variable quantitative
            x, niveaux = couper_r(x, p["breaks"], p.get("labels") or libelles_classes(sorted(p["breaks"])))
        if x.nunique(dropna = False) < 2:
            messages.append("[" + v + "] ignored (fewer than two modalities).")
            continue
        series[v] = (x, niveaux, p)
    if not series:
        raise ValueError("No variable to plot (fewer than two modalities).")
    grille = figure.add_gridspec(len(series), 2, width_ratios = [4, 1.3])
    for k, (v, (x, niveaux, p)) in enumerate(series.items()):
        ax = figure.add_subplot(grille[k, 0])               # colonne de gauche : diagramme
        ax_stat = figure.add_subplot(grille[k, 1])          # colonne de droite : statistiques
        resultats = plot_frequences(ax, x, lab_x = p.get("lab_x", v), lab_y = p.get("lab_y", "Frequency (%)"),
                        couleur = p.get("couleur") or COULEUR_BARRES,
                        niveaux = niveaux, raccourcir = p.get("labels") is None)
        tableau_statistiques(ax_stat, *resultats)
    return messages


def boite_parametres_barplot (hote, fenetre, donnees, candidates, v, p0, enregistrer, annuler):
    """ Parametres de barplot_function() pour la variable v : titres des axes
    (lab_x, lab_y), classes (breaks, labels) si v est quantitative, couleur
    et unite de comptage. """
    quantitative = est_quantitative(donnees[v], v)
    if p0 is None:
        p0 = dict(lab_x = v, lab_y = "Frequency (%)", breaks_texte = "", labels_texte = "",
                  couleur = COULEUR_BARRES, unite = "rows")
    boite = nouvelle_boite(hote)
    Label(boite, text = v, font = ('arial', 14, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 2))
    Label(boite, text = "Parameters of the bar plot", font = ('arial', 13)).grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 8))
    var_lab_x = champ_boite(boite, 2, "Modality axis label", p0["lab_x"])
    var_lab_y = champ_boite(boite, 3, "Frequency axis label", p0["lab_y"])
    ## classes : seulement pour une variable quantitative
    var_breaks = StringVar(value = p0["breaks_texte"])
    afficher_breaks = ligne_masquable(boite, 4, "Breaks", Entry(boite, textvariable = var_breaks, width = 34),
                                      "Quantitative variable, e.g.  -Inf, 40, 50, Inf   (classes (a, b])")
    var_labels = StringVar(value = p0["labels_texte"])
    afficher_labels = ligne_masquable(boite, 6, "Labels", Entry(boite, textvariable = var_labels, width = 34),
                                      "One per class (empty:  ≤ 40; ]40 ; 50]; > 50)")
    afficher_breaks(quantitative)
    afficher_labels(quantitative)
    ## couleur des barres
    var_couleur = StringVar(value = p0["couleur"])
    cadre_couleur = Frame(boite)
    cadre_couleur.grid(row = 9, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    Label(boite, text = "Color", **ETIQUETTE_BOITE).grid(row = 9, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    echantillon = Label(cadre_couleur, text = "      ", background = var_couleur.get(), relief = "solid", bd = 1)
    echantillon.pack(side = LEFT, padx = (0, 8))

    def choisir_couleur ():
        choix = colorchooser.askcolor(color = var_couleur.get(), title = "Color of the bars", parent = boite)
        if choix and choix[1]:
            var_couleur.set(choix[1])
            echantillon.configure(background = choix[1])

    tk.Button(cadre_couleur, text = "Choose…", command = choisir_couleur, width = 9).pack(side = LEFT)
    ## unite de comptage
    Label(boite, text = "Count", **ETIQUETTE_BOITE).grid(row = 10, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    unites = ["rows", "patients"] if "Patient" in donnees.columns else ["rows"]
    choix_unite = ttk.Combobox(boite, values = unites, state = "readonly", width = 12)
    choix_unite.set(p0["unite"] if p0["unite"] in unites else "rows")
    choix_unite.grid(row = 10, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    Label(boite, text = "rows: one observation per row;  patients: first non-missing value of each patient", **AIDE_BOITE).grid(row = 11, column = 1, sticky = "w", padx = (0, 15))
    boite.grid_columnconfigure(1, weight = 1)

    def valider ():
        try:
            breaks = lire_breaks(var_breaks.get()) if quantitative else None
        except ValueError as erreur:
            messagebox.showwarning("Bar plot", "Breaks: " + str(erreur), parent = boite)
            return False
        labels = [m.strip() for m in var_labels.get().split(";") if m.strip() != ""] or None
        if labels is not None and breaks is None:
            messagebox.showwarning("Bar plot", "Labels require breaks.", parent = boite)
            return False
        if breaks is not None:
            try:
                couper_r(donnees[v], breaks, labels)
            except ValueError as erreur:
                messagebox.showwarning("Bar plot", str(erreur), parent = boite)
                return False
        enregistrer(dict(lab_x = var_lab_x.get().strip() or v, lab_y = var_lab_y.get().strip() or "Frequency (%)",
                         breaks = breaks, labels = labels, couleur = var_couleur.get(),
                         unite = choix_unite.get(), breaks_texte = var_breaks.get() if quantitative else "",
                         labels_texte = var_labels.get() if quantitative else ""))
        return True

    boutons_boite(boite, fenetre, 12, valider, annuler)


def resume_barplot (p):
    return p["lab_x"] + ("  |  classes" if p.get("breaks") else "") + "  |  " + p["unite"]


def dialogue_barplot (case_barplot):
    """ « Bar plot » : premier niveau commun + second niveau de barplot_function(). """
    dialogue_variables_reponses(case_barplot, "Bar plot", parametres_barplot, (), ("Patient",),
                                boite_parametres_barplot, resume_barplot, trace_barplots)


##-----------------------------------------------------------------------------
##  « Histogram » : histogramme d'une variable quantitative et statistiques usuelles
##-----------------------------------------------------------------------------
parametres_histogramme = {"variables": None, "parametres": {}}
COULEUR_HISTOGRAMME = "#009ACD"    # « deepskyblue3 », couleur des variables numeriques (plot_frequences)
ECHELLES_HISTOGRAMME = {"count": "Count", "percent": "Frequency (%)", "density": "Density"}


def statistiques_usuelles (x):
    """ Statistiques usuelles d'une variable quantitative : effectif, valeurs
    manquantes, moyenne, ecart-type, minimum, quartiles, maximum. """
    v = x.dropna().to_numpy(dtype = float)
    f = lambda a: formater_valeur_stat(round(float(a), 2))
    if len(v) == 0:
        return [["N", "0"], ["Missing", str(int(x.isna().sum()))]]
    q1, med, q3 = np.percentile(v, [25, 50, 75])              # quantile(type = 7) de R
    return [["N", str(len(v))], ["Missing", str(int(x.isna().sum()))],
            ["Mean", f(v.mean())], ["SD", f(v.std(ddof = 1)) if len(v) > 1 else "NA"],
            ["Min", f(v.min())], ["Q1", f(q1)], ["Median", f(med)], ["Q3", f(q3)], ["Max", f(v.max())]]


def densite_lissee (v, n_points = 512):
    """ Estimation a noyau gaussien, comme density() de R : fenetre bw.nrd0
    (0,9 min(ecart-type, IQR / 1,34) n^(-1/5)), grille etendue de 3 fenetres
    de part et d'autre des donnees. Renvoie (abscisses, densites). """
    n = len(v)
    q1, q3 = np.percentile(v, [25, 75])
    echelle = min(np.std(v, ddof = 1), (q3 - q1) / 1.34)
    if echelle <= 0:
        echelle = np.std(v, ddof = 1) or abs(v[0]) or 1.0
    h = 0.9 * echelle * n ** (-0.2)
    grille = np.linspace(v.min() - 3 * h, v.max() + 3 * h, n_points)
    densites = np.exp(-0.5 * ((grille[:, None] - v[None, :]) / h) ** 2).sum(axis = 1) / (n * h * np.sqrt(2 * np.pi))
    return grille, densites


def histogramme (ax, x, lab_x, lab_y = None, nb_classes = None, echelle = "count", couleur = COULEUR_HISTOGRAMME):
    """ Histogramme de x (valeurs manquantes ignorees) ; nb_classes : nombre
    de classes (None : regle de Sturges, comme hist() de R) ; echelle :
    « count » (effectifs), « percent » (frequences en %) ou « density » (avec
    la densite lissee superposee). """
    v = x.dropna().to_numpy(dtype = float)
    style_ggpubr(ax)
    if len(v):
        bornes = np.histogram_bin_edges(v, bins = nb_classes if nb_classes else "sturges")
        poids = np.full(len(v), 100.0 / len(v)) if echelle == "percent" else None
        ax.hist(v, bins = bornes, weights = poids, density = (echelle == "density"), color = couleur,
                edgecolor = "white", linewidth = 0.8)
        if echelle == "density" and len(v) > 1:
            gx, gy = densite_lissee(v)                       # densite lissee superposee
            ax.plot(gx, gy, color = "#8B2323", linewidth = 1.8)
    ax.set_xlabel(lab_x, fontsize = 11)
    ax.set_ylabel(lab_y or ECHELLES_HISTOGRAMME[echelle], fontsize = 11)


def trace_histogrammes (figure, data, variables):
    """ Un histogramme par variable. Mise en page en deux colonnes : le
    graphique a gauche et, a droite, les statistiques usuelles.
    variables : variable -> lab_x, lab_y, nb_classes, echelle, couleur, unite
    (« rows » ou « patients » : premiere valeur non manquante par patient). """
    grille = figure.add_gridspec(len(variables), 2, width_ratios = [4, 1.3])
    for k, (v, p) in enumerate(variables.items()):
        ax = figure.add_subplot(grille[k, 0])               # colonne de gauche : histogramme
        ax_stat = figure.add_subplot(grille[k, 1])          # colonne de droite : statistiques
        if p.get("unite") == "patients" and "Patient" in data.columns:
            x = data.groupby("Patient", sort = False)[v].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
        else:
            x = data[v]
        x = vers_numerique(x)
        histogramme(ax, x, lab_x = p.get("lab_x", v), lab_y = p.get("lab_y"), nb_classes = p.get("nb_classes"),
                    echelle = p.get("echelle", "count"), couleur = p.get("couleur") or COULEUR_HISTOGRAMME)
        dessiner_tableau(ax_stat, ["Statistic", "Value"], statistiques_usuelles(x), [0.55, 0.45])
    return []


def boite_parametres_histogramme (hote, fenetre, donnees, candidates, v, p0, enregistrer, annuler):
    """ Parametres de l'histogramme de la variable v : titres des axes, nombre
    de classes, echelle de l'axe des y, couleur et unite de comptage. """
    if p0 is None:
        p0 = dict(lab_x = VARIABLES_DEFAUT[v][0] if v in VARIABLES_DEFAUT else v, lab_y = "",
                  nb_classes = None, echelle = "count", couleur = COULEUR_HISTOGRAMME, unite = "rows")
    boite = nouvelle_boite(hote)
    Label(boite, text = v, font = ('arial', 14, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 2))
    Label(boite, text = "Parameters of the histogram", font = ('arial', 13)).grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 8))
    var_lab_x = champ_boite(boite, 2, "X-axis label", p0["lab_x"])
    var_lab_y = champ_boite(boite, 3, "Y-axis label", p0["lab_y"])
    Label(boite, text = "Empty: Count, Frequency (%) or Density, according to the scale", **AIDE_BOITE).grid(row = 4, column = 1, sticky = "w", padx = (0, 15))
    ## nombre de classes
    Label(boite, text = "Number of bins", **ETIQUETTE_BOITE).grid(row = 5, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    var_classes = StringVar(value = "" if p0["nb_classes"] is None else str(p0["nb_classes"]))
    cadre_classes = Frame(boite)
    cadre_classes.grid(row = 5, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    Spinbox(cadre_classes, from_ = 2, to = 200, increment = 1, textvariable = var_classes, width = 6).pack(side = LEFT)
    Label(cadre_classes, text = "  empty: Sturges rule", **AIDE_BOITE).pack(side = LEFT)
    var_classes.set("" if p0["nb_classes"] is None else str(p0["nb_classes"]))
    ## echelle de l'axe des y
    Label(boite, text = "Scale", **ETIQUETTE_BOITE).grid(row = 6, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    choix_echelle = ttk.Combobox(boite, values = list(ECHELLES_HISTOGRAMME), state = "readonly", width = 12)
    choix_echelle.set(p0["echelle"])
    choix_echelle.grid(row = 6, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    ## couleur
    var_couleur = StringVar(value = p0["couleur"])
    Label(boite, text = "Color", **ETIQUETTE_BOITE).grid(row = 7, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    cadre_couleur = Frame(boite)
    cadre_couleur.grid(row = 7, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    echantillon = Label(cadre_couleur, text = "      ", background = var_couleur.get(), relief = "solid", bd = 1)
    echantillon.pack(side = LEFT, padx = (0, 8))

    def choisir_couleur ():
        choix = colorchooser.askcolor(color = var_couleur.get(), title = "Color of the bars", parent = boite)
        if choix and choix[1]:
            var_couleur.set(choix[1])
            echantillon.configure(background = choix[1])

    tk.Button(cadre_couleur, text = "Choose…", command = choisir_couleur, width = 9).pack(side = LEFT)
    ## unite de comptage
    Label(boite, text = "Count", **ETIQUETTE_BOITE).grid(row = 8, column = 0, sticky = "w", padx = (15, 6), pady = 3)
    unites = ["rows", "patients"] if "Patient" in donnees.columns else ["rows"]
    choix_unite = ttk.Combobox(boite, values = unites, state = "readonly", width = 12)
    choix_unite.set(p0["unite"] if p0["unite"] in unites else "rows")
    choix_unite.grid(row = 8, column = 1, sticky = "w", padx = (0, 15), pady = 3)
    Label(boite, text = "rows: one observation per row;  patients: first non-missing value of each patient", **AIDE_BOITE).grid(row = 9, column = 1, sticky = "w", padx = (0, 15))
    boite.grid_columnconfigure(1, weight = 1)

    def valider ():
        texte = var_classes.get().strip()
        try:
            nb_classes = None if texte == "" else int(texte)
            if nb_classes is not None and nb_classes < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Histogram", "The number of bins must be a positive integer (or empty).", parent = boite)
            return False
        enregistrer(dict(lab_x = var_lab_x.get().strip() or v, lab_y = var_lab_y.get().strip(), nb_classes = nb_classes,
                         echelle = choix_echelle.get(), couleur = var_couleur.get(), unite = choix_unite.get()))
        return True

    boutons_boite(boite, fenetre, 10, valider, annuler)


def resume_histogramme (p):
    return p["lab_x"] + "  |  " + ("Sturges" if p["nb_classes"] is None else str(p["nb_classes"]) + " bins") + "  |  " + p["echelle"]


def dialogue_histogramme (case_histogram):
    """ « Histogram » : premier niveau commun (variables quantitatives
    seulement) + second niveau de l'histogramme. """
    dialogue_variables_reponses(case_histogram, "Histogram", parametres_histogramme, (), ("Patient",),
                                boite_parametres_histogramme, resume_histogramme, trace_histogrammes,
                                selection = est_quantitative)


## Parametres des graphiques conserves d'une session a l'autre
FICHIER_PARAMETRES_GRAPHIQUES = os.path.join(os.path.expanduser("~"), ".abos_parametres_graphiques.json")


def sauver_parametres_graphiques ():
    """ Ecrit les parametres memorises des graphiques (fichier JSON). """
    contenu = {"Trajectory": parametres_trajectoire, "Box plot": parametres_boxplot, "Bar plot": parametres_barplot,
               "Histogram": parametres_histogramme}
    try:
        with open(FICHIER_PARAMETRES_GRAPHIQUES, "w", encoding = "utf-8") as fichier:
            json.dump(contenu, fichier, ensure_ascii = False, indent = 1)
    except (OSError, TypeError, ValueError):
        pass                                   # memorisation sur disque facultative


def charger_parametres_graphiques ():
    """ Relit les parametres memorises lors des sessions precedentes. """
    try:
        with open(FICHIER_PARAMETRES_GRAPHIQUES, encoding = "utf-8") as fichier:
            contenu = json.load(fichier)
    except (OSError, ValueError):
        return
    for nom, memoire in (("Trajectory", parametres_trajectoire), ("Box plot", parametres_boxplot), ("Bar plot", parametres_barplot),
                         ("Histogram", parametres_histogramme)):
        lu = contenu.get(nom) or {}
        memoire["variables"] = lu.get("variables") or None
        memoire["parametres"] = lu.get("parametres") or {}


charger_parametres_graphiques()


def choix_graphique (nom, case):
    """ Cases « Bar plot », « Box plot », « Histogram » et « Trajectory » : cochee -> boite de dialogue ;
    un seul type coche a la fois ; decochee par l'utilisateur -> graphiques
    de ce type retires. """
    if case.get():
        ## un seul type coche a la fois : les autres sont decoches (leurs
        ## graphiques restent proposes par « Save plot »)
        for autre, var in types_graphique.items():
            if autre != nom:
                var.set(False)
        {"Trajectory": dialogue_trajectoire, "Box plot": dialogue_boxplot, "Bar plot": dialogue_barplot,
         "Histogram": dialogue_histogramme}[nom](case)
    else:
        retirer_graphique(nom)


panneau_graphique = None           # zone des graphiques (bouton « Plots »)
panneau_options_graphique = None   # zone des options des graphiques (bouton « Plots »)
TYPES_GRAPHIQUE = sorted(["Bar plot", "Box plot", "Histogram", "Trajectory"])   # ordre alphabetique
types_graphique = {}               # type de graphique -> BooleanVar (case cochee)


## Polices des graphiques (panneau de droite de « Plots ») : titres, axes, legendes, statistiques
STYLES_POLICE = {"normal": ("normal", "normal"), "bold": ("bold", "normal"),
                 "italic": ("normal", "italic"), "bold italic": ("bold", "italic")}
police_graphiques = {"titre": {"taille": 12, "style": "bold"},
                     "axes": {"taille": 11, "style": "normal"},
                     "legende": {"taille": 10, "style": "bold"},
                     "statistiques": {"taille": 9, "style": "normal"}}
BLOCS_POLICE = [("titre", "Title option"), ("axes", "Axes option"), ("legende", "Legend option"), ("statistiques", "Statistics option")]
## types de graphique comportant l'element (None : tous)
TYPES_AVEC_ELEMENT = {"titre": None, "axes": None, "legende": {"Box plot", "Trajectory"}, "statistiques": {"Bar plot", "Histogram"}}


def appliquer_polices (figure):
    """ Polices des graphiques.
    - titres (T, style choisi) : titres des graphiques ;
    - axes (A, style choisi) : titres des deux axes en A, libelles des
      graduations et valeurs inscrites dans les barres en A - 1 ;
    - legendes (L, style choisi) : textes en L, titre en L + 1 ;
    - statistiques (S, style choisi) : cellules des tableaux en S (en-tete et
      ligne Total restent en gras). """
    t = police_graphiques["titre"]["taille"]
    p_t, f_t = STYLES_POLICE[police_graphiques["titre"]["style"]]
    a = police_graphiques["axes"]["taille"]
    p_a, f_a = STYLES_POLICE[police_graphiques["axes"]["style"]]
    l = police_graphiques["legende"]["taille"]
    p_l, f_l = STYLES_POLICE[police_graphiques["legende"]["style"]]
    st = police_graphiques["statistiques"]["taille"]
    p_s, f_s = STYLES_POLICE[police_graphiques["statistiques"]["style"]]
    for ax in figure.axes:
        ax.title.set_fontsize(t)
        ax.title.set_fontweight(p_t)
        ax.title.set_fontstyle(f_t)
        ## deux axes : titres et libelles des graduations
        ax.xaxis.label.set_fontsize(a)
        ax.yaxis.label.set_fontsize(a)
        ax.tick_params(labelsize = a - 1)
        for texte in [ax.xaxis.label, ax.yaxis.label] + list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            texte.set_fontweight(p_a)
            texte.set_fontstyle(f_a)
        for texte in ax.texts:                    # valeurs inscrites dans les barres
            texte.set_fontsize(a - 1)
        legende = ax.get_legend()
        if legende is not None:
            for texte in legende.get_texts():
                texte.set_fontsize(l)
                texte.set_fontweight(p_l)
                texte.set_fontstyle(f_l)
            legende.get_title().set_fontsize(l + 1)
            legende.get_title().set_fontstyle(f_l)
        for tableau in ax.tables:
            tableau.set_fontsize(st)
            gras = getattr(tableau, "cellules_grasses", set())
            for cle, cellule in tableau.get_celld().items():
                if cle not in gras:
                    cellule.get_text().set_fontweight(p_s)
                cellule.get_text().set_fontstyle(f_s)


def changer_polices (cle, taille, style):
    """ Nouvelle taille / nouveau style d'un bloc (titres, axes, legendes ou
    statistiques) : memorises et appliques au graphique affiche. """
    try:
        police_graphiques[cle]["taille"] = max(6, min(30, int(float(taille))))
    except (ValueError, tk.TclError):
        return
    if style in STYLES_POLICE:
        police_graphiques[cle]["style"] = style
    if figure_graphique is not None and etat_zoom["toile"] is not None:
        appliquer_polices(figure_graphique)
        mise_en_page(figure_graphique, etat_zoom["toile"])   # nouvelles polices : mise en page recalculee


COULEUR_TITRE_BLOC = "gray10"           # titres des blocs du panneau de droite (Title option, Axes option...)


def bloc_police (parent, ligne, cle, titre, couleur_titre = COULEUR_TITRE_BLOC):
    """ Bloc « <titre> » du panneau de droite : titre, trait horizontal,
    taille (Font size) puis style (Font style) des polices. """
    cadre = Frame(parent, background = "gray90")
    cadre.grid(row = ligne, column = 0, sticky = "ew", padx = 8, pady = (12, 0))
    cadre.grid_columnconfigure(1, weight = 1)
    Label(cadre, text = titre, font = ('arial', 14), fg = couleur_titre, background = "gray90").grid(row = 0, column = 0, columnspan = 2, sticky = "w")
    tk.Frame(cadre, height = 1, background = "gray50").grid(row = 1, column = 0, columnspan = 2, sticky = "ew", pady = (2, 6))   # trait sous le titre
    Label(cadre, text = "Font size", font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = 2, column = 0, sticky = "w", padx = (22, 0))
    var_taille = StringVar(value = str(police_graphiques[cle]["taille"]))
    choix_style = ttk.Combobox(cadre, values = list(STYLES_POLICE), state = "readonly", width = 11)
    appliquer = lambda event = None: changer_polices(cle, var_taille.get(), choix_style.get())
    boite_taille = Spinbox(cadre, from_ = 6, to = 30, increment = 1, textvariable = var_taille, width = 5, command = appliquer)
    boite_taille.grid(row = 2, column = 1, sticky = "w", padx = (6, 0))
    var_taille.set(str(police_graphiques[cle]["taille"]))
    Label(cadre, text = "Font style", font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = 3, column = 0, sticky = "w", padx = (22, 0), pady = (6, 0))
    choix_style.set(police_graphiques[cle]["style"])
    choix_style.grid(row = 3, column = 1, sticky = "w", padx = (6, 0), pady = (6, 0))
    choix_style.bind("<<ComboboxSelected>>", appliquer)
    boite_taille.bind("<Return>", appliquer)
    boite_taille.bind("<FocusOut>", appliquer)
    if cle == "axes":
        lignes_bornes(cadre, 4)                   # X : min, max ;  Y : min, max
    return cadre


def bloc_point_moyenne (parent, ligne, couleur_titre = COULEUR_TITRE_BLOC):
    """ Bloc « Mean point » du panneau de droite (« Box plot ») : case « View
    point » (moyenne de chaque distribution) et couleur des points. Tout
    changement retrace le box plot affiche. """
    cadre = Frame(parent, background = "gray90")
    cadre.grid(row = ligne, column = 0, sticky = "ew", padx = 8, pady = (12, 0))
    cadre.grid_columnconfigure(1, weight = 1)
    Label(cadre, text = "Mean point", font = ('arial', 14), fg = couleur_titre, background = "gray90").grid(row = 0, column = 0, columnspan = 2, sticky = "w")
    tk.Frame(cadre, height = 1, background = "gray50").grid(row = 1, column = 0, columnspan = 2, sticky = "ew", pady = (2, 6))   # trait sous le titre
    var_voir = BooleanVar(value = point_moyenne["afficher"])
    choix_couleur = ttk.Combobox(cadre, values = COULEURS_POINT_MOYENNE, state = "readonly", width = 11)
    choix_couleur.set(point_moyenne["couleur"])
    var_taille = StringVar(value = str(point_moyenne.get("taille", 6)))

    def appliquer (event = None):
        point_moyenne["afficher"] = bool(var_voir.get())
        point_moyenne["couleur"] = choix_couleur.get() or "red"
        try:
            point_moyenne["taille"] = max(2, min(20, int(float(var_taille.get()))))
        except (ValueError, tk.TclError):
            pass
        var_taille.set(str(point_moyenne["taille"]))
        if type_affiche["titre"] == "Box plot" and "Box plot" in traces_graphiques:
            try:
                afficher_type("Box plot")             # box plot affiche : retrace avec ou sans les moyennes
            except Exception:
                effacer_figure()

    Checkbutton(cadre, text = "View point", variable = var_voir, command = appliquer, font = ('arial', 13), fg = "gray30",
                background = "gray90", activebackground = "gray90", highlightthickness = 0, anchor = "w").grid(
        row = 2, column = 0, columnspan = 2, sticky = "w", padx = (18, 0))
    Label(cadre, text = "Color", font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = 3, column = 0, sticky = "w", padx = (22, 0), pady = (6, 0))
    choix_couleur.grid(row = 3, column = 1, sticky = "w", padx = (6, 0), pady = (6, 0))
    choix_couleur.bind("<<ComboboxSelected>>", appliquer)
    Label(cadre, text = "Point size", font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = 4, column = 0, sticky = "w", padx = (22, 0), pady = (6, 0))
    boite_taille = Spinbox(cadre, from_ = 2, to = 20, increment = 1, textvariable = var_taille, width = 5, command = appliquer)
    boite_taille.grid(row = 4, column = 1, sticky = "w", padx = (6, 0), pady = (6, 0))
    var_taille.set(str(point_moyenne.get("taille", 6)))
    boite_taille.bind("<Return>", appliquer)
    boite_taille.bind("<FocusOut>", appliquer)
    return cadre


def plots (parent):
    """ Bouton « Plots » : deux panneaux, 80 % a gauche pour les graphiques et
    20 % a droite pour les options. """
    global panneau_graphique, panneau_options_graphique, statut_graphique, figure_graphique
    figure_graphique = None
    type_affiche["titre"] = None
    if data is None:
        panneau = nouveau_panneau(parent)
        Label(panneau, text = "Please load data to be analyzed", font = ('Helvetica 16 bold italic'), fg = "red", background = "white").place(relx = 0, rely = 0, relwidth = 1, relheight = 1)
        return
    panneau = nouveau_panneau(parent)
    panneau_graphique = Frame(panneau, background = "white")
    panneau_graphique.place(relx = 0, rely = 0, relwidth = 0.8, relheight = 1)
    panneau_options_graphique = Frame(panneau, background = "gray90")
    panneau_options_graphique.place(relx = 0.8, rely = 0, relwidth = 0.2, relheight = 1)
    panneau_options_graphique.grid_columnconfigure(0, weight = 1)

    ## --- En haut du panneau de droite : « Graphiques », puis les types de graphique
    style_case = dict(fg = "gray30", background = "gray90", activebackground = "gray90", highlightthickness = 0, anchor = "w")
    graphiques_def = BooleanVar(value = False)
    cases_types = []
    for i, nom in enumerate(TYPES_GRAPHIQUE):
        types_graphique[nom] = BooleanVar(value = False)
        commande = lambda nom = nom: choix_graphique(nom, types_graphique[nom])
        cases_types.append(Checkbutton(panneau_options_graphique, text = nom, variable = types_graphique[nom], command = commande, font = ('arial', 13), **style_case))
    ## --- Polices : « Title option », « Axes option », « Legend option », « Statistics option »
    n = len(TYPES_GRAPHIQUE)
    ## ordre des blocs : Title, Axes, Legend, Mean point (« Box plot »), Statistics
    ordre_blocs = [cle for cle, _ in BLOCS_POLICE]
    ordre_blocs.insert(ordre_blocs.index("legende") + 1, "moyenne")
    titres_blocs = dict(BLOCS_POLICE)
    blocs = {}
    for k, cle in enumerate(ordre_blocs):
        if cle == "moyenne":
            blocs[cle] = bloc_point_moyenne(panneau_options_graphique, n + 1 + k)
        else:
            blocs[cle] = bloc_police(panneau_options_graphique, n + 1 + k, cle, titres_blocs[cle])
    types_blocs = dict(TYPES_AVEC_ELEMENT, moyenne = {"Box plot"})

    def maj_blocs_police ():
        ## « Legend option » / « Statistics option » / « Mean point » : affiches
        ## seulement si un type de graphique coche comporte cet element
        coches = {nom for nom, var in types_graphique.items() if var.get()}
        for cle, cadre in blocs.items():
            types = types_blocs[cle]
            if types is None or coches & types:
                cadre.grid()
            else:
                cadre.grid_remove()

    for var in types_graphique.values():       # toute coche / decoche (y compris par « Cancel »)
        var.trace_add("write", lambda *args: maj_blocs_police())
    maj_blocs_police()
    ## boutons « Refresh » et « Save plot » en bas du panneau de droite
    style_bouton = dict(font = ('arial', 13), compound = tk.TOP, borderwidth = 0, relief = FLAT, borderless = True,
                        bordercolor = "gray90", background = "gray90", focuscolor = "gray90", highlightcolor = "gray90",
                        highlightbackground = "gray90")
    Button(panneau_options_graphique, image = rafraichir_graph, text = "Refresh", command = rafraichir_graphique,
           **style_bouton).place(relx = 0.27, rely = 0.985, anchor = "s", width = 95, height = 60)
    Button(panneau_options_graphique, image = save_graph_p, text = "Save plot", command = sauver_graphiques,
           **style_bouton).place(relx = 0.73, rely = 0.985, anchor = "s", width = 95, height = 60)
    ## messages du dernier graphique (patients exclus, etc.)
    statut_graphique = Label(panneau_options_graphique, text = "", font = ('arial', 11), fg = "saddlebrown", background = "gray90", justify = "left", anchor = "w", wraplength = 200)
    statut_graphique.grid(row = n + 1 + len(ordre_blocs), column = 0, sticky = "ew", padx = 8, pady = (12, 0))

    def afficher_types ():
        ## « Graphiques » coche : types affiches en retrait et type courant
        ## recoche et retrace ; decoche : types masques et decoches
        if not graphiques_def.get():
            coches = [nom for nom, var in types_graphique.items() if var.get()]
            type_courant["titre"] = coches[0] if coches else type_affiche["titre"]
        for i, case in enumerate(cases_types):
            if graphiques_def.get():
                case.grid(row = i + 1, column = 0, sticky = "ew", padx = (30, 8), pady = 1)
            else:
                case.grid_remove()
                types_graphique[TYPES_GRAPHIQUE[i]].set(False)
        if not graphiques_def.get():
            effacer_figure()
            statut_graphique.configure(text = "")
        elif type_courant["titre"] in traces_graphiques and type_courant["titre"] in types_graphique:
            types_graphique[type_courant["titre"]].set(True)   # sans rouvrir la boite de dialogue
            try:
                afficher_type(type_courant["titre"])
            except Exception:
                effacer_figure()                  # donnees modifiees : graphique a reparametrer

    Checkbutton(panneau_options_graphique, text = "Graphiques", variable = graphiques_def, command = afficher_types,
                font = ('arial', 14), **style_case).grid(row = 0, column = 0, sticky = "ew", padx = 8, pady = (10, 2))


##=============================================================================
##  Boites d'analyse (bouton « Analysis » de la barre verticale gauche)
##  Chaque nouvelle analyse est representee par une boite (rectangle arrondi,
##  couleur au choix) dans le panneau central : selection par un clic,
##  deplacement a la souris, taille reglee par la barre verticale gauche.
##=============================================================================
analyses = []                      # noms des analyses, dans l'ordre de creation
couleurs_boites = {}               # analyse -> couleur de la boite
positions_boites = {}              # analyse -> (x, y) dans le panneau
taille_boites = 90                 # cote des boites (pixels)
TAILLE_BOITE_MIN, TAILLE_BOITE_MAX = 50, 160
ZOOM_CREATION_BOITE = 80             # zoom (%) applique a la creation d'une boite
ESPACEMENT_BOITES = 12
COULEUR_SELECTION_BOITE = "#4a7a8c"
boite_selectionnee = {"nom": None, "comparaison": None, "multi": []}   # multi : boites de modeles selectionnees  # boite selectionnee (boutons « Delete », « Rename »)
## Boites de comparaison (bouton de la barre verticale droite) : on y glisse et
## depose les boites d'analyse (modeles) a comparer
comparaisons = []                  # noms des boites de comparaison, dans l'ordre de creation
modeles_comparaison = {}           # comparaison -> analyses deposees (ordre de depot)
positions_comparaisons = {}        # comparaison -> (x, y) dans le panneau
corbeille_comparaisons = {}        # comparaisons supprimees : nom -> {"modeles", "position", "indices"}
indices_comparaison = {}           # comparaison -> indices choisis (« ARI », « Jaccard »)
couleurs_comparaisons = {}         # comparaison -> couleur choisie (sinon couleur par defaut)
INDICES_COMPARAISON = ["ARI", "Jaccard"]
INDICES_DEFAUT = ["ARI"]
## cote des boites de comparaison (barre de zoom de la barre droite) : 80 % de zoom par defaut
TAILLE_COMPARAISON_DEFAUT = int(round(TAILLE_BOITE_MIN + ZOOM_CREATION_BOITE / 100 * (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN)))
taille_comparaisons = TAILLE_COMPARAISON_DEFAUT
## agrandissement des boites de comparaison par rapport au cote regle par la
## barre de zoom (polices inchangees : plus de place pour les noms des modeles)
ECHELLE_COMPARAISON = 1.2
COULEUR_MODELE_CHOISI = "#FF8C00"  # modele selectionne dans une boite de comparaison
COULEUR_COMPARAISON = "#EEF3F8"
PART_MODELES = 0.55                # part du panneau (a gauche) reservee aux boites de modeles
COULEUR_COMPARAISON_CIBLE = "#2E7DD1"      # contour quand une analyse survole la boite
corbeille_boites = {}              # boites supprimees : nom -> {"couleur", "position", "methode", "parametres", "resultat"}
methodes_boites = {}               # boite -> methode de clustering choisie (« Settings »)
fenetre_parametres_boite = {"widget": None, "nom": None, "zone": None}
panneau_boites = {"widget": None, "rafraichir": None}  # panneau Clustering affiche
METHODES_CLUSTERING = ["Choose method", "InfoMergeCluster", "FKMS"]
METHODES_EXECUTABLES = ("InfoMergeCluster", "FKMS")       # methodes programmees (parametres, « Run »)
PREFIXE_RESULTATS = "Clustering — "                       # graphiques de resultats (« Save plot »)


def defauts_boite (nom = None, methode = None):
    """ Parametres par defaut de la methode d'une boite. """
    methode = methode or methodes_boites.get(nom)
    return PARAMETRES_FKMS_DEFAUT if methode == "FKMS" else PARAMETRES_INFOMERGE_DEFAUT


def boite_configuree (nom):
    return methodes_boites.get(nom) in METHODES_EXECUTABLES and nom in parametres_infomerge


def nouvelle_analyse (parent):
    """ Bouton « Analysis » : creation d'une analyse (nom unique, couleur de
    sa boite facultative), puis affichage des boites. """
    if not messagebox.askyesno("New analysis", "Do you want to define a new analysis?"):
        if analyses:
            afficher_boites(parent)
        return
    nom = simpledialog.askstring("New analysis", "Name of the new analysis", initialvalue = "New analysis")
    if nom is None or nom.strip() == "":
        return
    nom = nom.strip()
    if nom in analyses:
        messagebox.showwarning("Name already used", "This name is already used. Choose a different name.")
        afficher_boites(parent)
        return
    analyses.append(nom)
    couleur = colorchooser.askcolor(color = "white", title = "Choose a color for the box « " + nom + " »")
    if couleur is not None and couleur[1] is not None:
        couleurs_boites[nom] = couleur[1]
    ## nouvelle boite : barre de taille (zoom) placee a 80 %
    global taille_boites
    taille_boites = int(round(TAILLE_BOITE_MIN + ZOOM_CREATION_BOITE / 100 * (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN)))
    afficher_boites(parent)
    historique_valider("New analysis « " + nom + " »")


def etat_boite (nom):
    """ Etat d'une boite d'analyse : creee, configuree, en cours, executee. """
    if nom in calculs_en_cours:
        return "Running"
    if nom in file_execution:
        return "Waiting"
    if nom in resultats_boites:
        return "Executed"
    if boite_configuree(nom):
        return "Configured"
    return "Created"


def texte_infos_boite (nom):
    """ Texte affiche sous le titre d'une boite : methode, variable reponse,
    K (valeur imposee ou critere de selection BIC / ICL), type d'effet
    aleatoire, nombre de fonctions de base (df), nombre de covariables et
    niveau de confiance de l'enveloppe (CE). """
    methode = methodes_boites.get(nom)
    lignes = [methode or traduire("No method")]
    if boite_configuree(nom):
        v = dict(defauts_boite(nom))
        v.update(parametres_infomerge[nom])
        if v.get("response"):                      # variable reponse, juste apres la methode
            lignes.append("Target: " + str(v["response"]))
        if str(v.get("K", "")).strip() != "":
            lignes.append("K = " + str(v["K"]))
        else:                                      # K choisi automatiquement : K_max sur la ligne juste avant
            lignes.append("K_max = " + str(v["K_max"]))
            lignes.append("K: " + (str(v.get("criterion", "BIC")) if methode == "InfoMergeCluster" else "MSE"))
        if methode == "FKMS":                      # base, nombre de fonctions, lambda
            lignes.append("Basis: " + str(v["basis"]))
            lignes.append("N.bs = " + str(v["N_bs"]))
            if v["basis"] == "B":
                lignes.append("λ: GCV" if v["lambda_gcv"] else "λ = " + formater_valeur_stat(v["lambda"]))
                if v["lambda_gcv"]:                # grille testee : bornes et nombre de valeurs
                    lignes.append("grid: [" + format(v["lambda_min"], "g") + ", " + format(v["lambda_max"], "g")
                                  + "] × " + str(v["lambda_n"]))
        else:
            lignes.append("RE: " + str(v.get("re", "linear")))
            lignes.append("df = " + str(v.get("df", 15)))
        if v.get("covariates"):                    # modele avec covariables : leur nombre
            lignes.append("N-cov = " + str(len(v["covariates"])))
        try:                                       # niveau de confiance de l'enveloppe (comme la legende)
            lignes.append("CE: %g%%" % (100 * float(v.get("level", 0.95))))
        except (TypeError, ValueError):
            pass
    return "\n".join(lignes)


def titre_boite (nom):
    """ Titre d'une boite : « nom : no-cov » (modele sans covariable) ou
    « nom : with-cov » (avec covariables), une fois la configuration
    enregistree ; sinon le nom seul. L'etat est affiche en bas, dans un bandeau. """
    v = parametres_infomerge.get(nom) if boite_configuree(nom) else None
    if v is None:
        return nom
    return nom + " : " + ("with-cov" if v.get("covariates") else "no-cov")


## badge d'etat en bas de chaque boite : couleur de fond selon l'etat
COULEURS_ETAT = {"Created": "#9E9E9E", "Configured": "#E39B2D", "Waiting": "#8C7BC4",
                 "Running": "#3D7FD9", "Executed": "#3A9A5B"}


def rafraichir_boites ():
    """ Met a jour le texte des boites du panneau Clustering s'il est affiche. """
    widget, fonction = panneau_boites.get("widget"), panneau_boites.get("rafraichir")
    if fonction is not None and widget is not None and widget.winfo_exists():
        fonction()


def nouvelle_comparaison (parent):
    """ Bouton de la barre verticale droite : creation d'une boite de
    comparaison, dans laquelle on glisse et depose les modeles a comparer. """
    k = len(comparaisons) + 1
    while "Comparison " + str(k) in comparaisons:
        k += 1
    nom = simpledialog.askstring("New comparison", "Name of the new comparison box", initialvalue = "Comparison " + str(k))
    if nom is None or nom.strip() == "":
        return
    nom = nom.strip()
    if nom in comparaisons or nom in analyses:
        messagebox.showwarning("Name already used", "This name is already used. Choose a different name.")
        return
    comparaisons.append(nom)
    modeles_comparaison[nom] = []
    indices_comparaison[nom] = list(INDICES_DEFAUT)
    couleur = colorchooser.askcolor(color = COULEUR_COMPARAISON, title = "Choose a color for the comparison box « " + nom + " »")
    if couleur is not None and couleur[1] is not None:
        couleurs_comparaisons[nom] = couleur[1]      # sinon couleur par defaut
    _regler_taille_comparaisons(TAILLE_COMPARAISON_DEFAUT)   # nouvelle boite de comparaison : zoom a 80 %
    boite_selectionnee.update(nom = None, comparaison = nom)
    afficher_boites(parent)
    historique_valider("New comparison « " + nom + " »")


def zoomer_comparaisons (valeur):
    """ Barre de zoom de la barre verticale droite : taille des boites de
    comparaison (independante de celle des boites de modeles). """
    global taille_comparaisons
    taille_comparaisons = int(TAILLE_BOITE_MIN + float(valeur) / 100 * (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN))
    widget, fonction = panneau_boites.get("widget"), panneau_boites.get("comparaisons")
    if fonction is not None and widget is not None and widget.winfo_exists():
        fonction()


def ajouter_modele_comparaison (comparaison, analyse):
    """ Depot d'une analyse dans une boite de comparaison (sans doublon). """
    if comparaison not in comparaisons or analyse not in analyses:
        return False
    liste = modeles_comparaison.setdefault(comparaison, [])
    if analyse in liste:
        _message_barre("« " + analyse + " » is already in « " + comparaison + " »")
        return False
    liste.append(analyse)
    historique_valider("Add « " + analyse + " » to « " + comparaison + " »")
    return True


def afficher_boites (parent):
    """ Panneau des boites d'analyse. La barre verticale gauche regle la taille
    des boites tant que le panneau est ouvert ; son reglage precedent (zoom des
    graphiques) est restaure a la fermeture du panneau. """
    panneau = nouveau_panneau(parent)
    panneau_boites["widget"] = panneau
    Label(panneau, text = "Clustering sparse longitudinal trajectories", font = ('arial', 16), fg = "saddlebrown", background = "white").place(relx = 0.01, rely = 0.01)
    boites = {}                                    # nom -> (canevas, forme, texte)
    infos = {}                                     # nom -> texte (methode, K, RE, df)
    badges = {}                                    # nom -> (fond, texte) du badge d'etat
    bandeaux_titre = {}                            # nom -> fond du nom (bandeau du haut)
    haut_badges = {}                               # nom -> ordonnee du haut du bandeau du statut
    defilement = {}                                # nom -> premiere ligne de configuration affichee
    fleches_defilement = {}                        # nom -> (fleche haut, fleche bas)
    selection = boite_selectionnee
    if selection["nom"] not in analyses:
        selection["nom"] = None
    selection["multi"] = [n for n in selection.get("multi", []) if n in analyses] or ([selection["nom"]] if selection["nom"] else [])
    if selection.get("comparaison") not in comparaisons:
        selection["comparaison"] = None
    glisse = {"nom": None, "ref": None, "origine": None}
    comps = {}                                     # comparaison -> {"canevas", "forme", "titre", "bandeau", "contenu"}
    glisse_c = {"nom": None, "ref": None, "origine": None}
    cible = {"nom": None}                          # boite de comparaison survolee pendant un glisser

    def points_arrondis (x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    def police (taille):
        return max(7, int(taille * 10 / 88))

    def couleur_texte (fond):
        ## texte blanc sur fond fonce, fonce sur fond clair
        try:
            r, g, b = panneau.winfo_rgb(fond)
            if (0.299 * r + 0.587 * g + 0.114 * b) / 65535 < 0.55:
                return "white"
        except tk.TclError:
            pass
        return "gray10"

    def limite_gauche ():
        ## abscisse du separateur : avec des boites de comparaison, le panneau est
        ## partage en deux (modeles a gauche, comparaisons a droite)
        largeur = max(panneau.winfo_width(), parent.winfo_width())
        return int(PART_MODELES * largeur) if comparaisons else largeur

    def zone (tout = False):
        ## bornes de deplacement d'une boite d'analyse : partie gauche du panneau
        ## (tout = True : panneau entier, pendant un glisser vers une comparaison)
        largeur = max(panneau.winfo_width(), parent.winfo_width())
        hauteur = max(panneau.winfo_height(), parent.winfo_height())
        xmin, ymin = int(0.01 * largeur), int(0.01 * hauteur)
        droite = largeur if tout else limite_gauche()
        return xmin, ymin, max(xmin, droite - taille_boites - 10), max(ymin, hauteur - taille_boites - 10)

    def position_defaut (indice):
        xmin, ymin, xmax, ymax = zone()
        ymin += 60                                 # sous le titre
        colonnes = max(1, ((xmax - xmin) + taille_boites) // (taille_boites + ESPACEMENT_BOITES))
        ligne, colonne = divmod(indice, colonnes)
        return xmin + colonne * (taille_boites + ESPACEMENT_BOITES), ymin + ligne * (taille_boites + ESPACEMENT_BOITES)

    def apparence ():
        for nom, (canevas, forme, texte) in boites.items():
            fond = couleurs_boites.get(nom, "white")
            canevas.itemconfig(texte, fill = couleur_texte(couleur_bandeau_titre(fond)))   # nom sur son bandeau
            canevas.itemconfig(infos[nom], fill = couleur_texte(fond))
            if nom in selection["multi"]:
                canevas.itemconfig(forme, fill = fond, outline = COULEUR_SELECTION_BOITE, width = 3)
            else:
                canevas.itemconfig(forme, fill = fond, outline = "gray70", width = 1)

    def selectionner (nom, ajouter = False):
        ## clic simple : cette boite seule ; Shift / Ctrl / Cmd + clic : ajoutee a
        ## la selection (ou retiree si elle y etait deja)
        if nom is None:
            selection["multi"] = []
        elif ajouter:
            if nom in selection["multi"]:
                selection["multi"].remove(nom)
                nom = selection["multi"][-1] if selection["multi"] else None
            else:
                selection["multi"].append(nom)
        else:
            selection["multi"] = [nom]
        selection["nom"] = nom                     # boite de reference (Settings, Delete, Rename)
        if nom is not None:
            selection["comparaison"] = None
        apparence()
        apparence_comparaisons()
        for c in comps:                            # modeles selectionnes mis en evidence dans les comparaisons
            if comps[c]["canevas"].winfo_exists():
                dessiner_comparaison(c)

    dernier_clic = {"nom": None, "temps": 0}

    def saisir (event, nom):
        ## double clic (deux clics rapides sur la meme boite) : boite de dialogue
        ## « Settings » ; detection par le temps entre les clics (fiable sur macOS)
        ajouter = bool(event.state & (0x0001 | 0x0004 | 0x0008))     # Shift, Ctrl ou Cmd enfonce
        double = not ajouter and dernier_clic["nom"] == nom and 0 <= event.time - dernier_clic["temps"] <= 400
        dernier_clic.update(nom = None if double else nom, temps = event.time)
        if ajouter:
            selectionner(nom, ajouter = True)
            glisse.update(nom = None, ref = None, origine = None)   # pas de deplacement en multi-selection
            return
        if not (double and nom in selection["multi"]):
            selectionner(nom)
        if double:
            glisse.update(nom = None, ref = None, origine = None)
            if not (calculs_en_cours or file_execution):      # pas de parametrage pendant « Run »
                ouvrir_parametres_boite(parent)
            return
        canevas = boites[nom][0]
        tk.Misc.tkraise(canevas)                   # boite au premier plan
        glisse.update(nom = nom, ref = (event.x_root, event.y_root), origine = (canevas.winfo_x(), canevas.winfo_y()))

    def glisser (event, nom):
        if glisse["nom"] != nom:
            return
        xmin, ymin, xmax, ymax = zone()            # la boite reste dans la partie des modeles
        x = min(max(glisse["origine"][0] + event.x_root - glisse["ref"][0], xmin), xmax)
        y = min(max(glisse["origine"][1] + event.y_root - glisse["ref"][1], ymin), ymax)
        boites[nom][0].place(x = x, y = y)

    def comparaison_sous (x_root, y_root):
        ## boite de comparaison sous le pointeur (coordonnees ecran), ou None
        for c, elements in comps.items():
            cv = elements["canevas"]
            if not cv.winfo_exists():
                continue
            x0, y0 = cv.winfo_rootx(), cv.winfo_rooty()
            if x0 <= x_root <= x0 + cv.winfo_width() and y0 <= y_root <= y0 + cv.winfo_height():
                return c
        return None

    def lacher (event, nom):
        if glisse["nom"] != nom:
            return
        canevas = boites[nom][0]
        ancienne = positions_boites.get(nom)
        positions_boites[nom] = (canevas.winfo_x(), canevas.winfo_y())     # position memorisee
        glisse.update(nom = None, ref = None, origine = None)
        if ancienne != positions_boites[nom]:
            historique_valider("Move « " + nom + " »")

    def dessiner_badge (nom):
        ## etat de la boite : bandeau colore sur toute la largeur, tout en bas,
        ## coins inferieurs arrondis comme la boite ; texte centre
        canevas = boites[nom][0]
        fond_id, texte_id = badges[nom]
        etat = etat_boite(nom)
        taille = max(6, police(taille_boites) - 2)
        canevas.itemconfig(texte_id, text = traduire(etat), font = ('arial', taille, 'bold'), fill = "white", anchor = "center")
        hauteur_texte = tkfont.Font(font = ('arial', taille, 'bold')).metrics("linespace")
        bas = taille_boites - 3                        # juste a l'interieur du contour de la boite
        haut = bas - hauteur_texte - 6
        g, d = 3, taille_boites - 3
        r = min(int(taille_boites * 0.2), bas - haut)  # meme arrondi que la boite
        canevas.coords(fond_id, g, haut, g, haut, d, haut, d, haut, d, bas - r, d, bas, d - r, bas,
                       g + r, bas, g, bas, g, bas - r)
        canevas.itemconfig(fond_id, fill = COULEURS_ETAT.get(etat, "#9E9E9E"))
        canevas.coords(texte_id, taille_boites / 2, (haut + bas) / 2)
        haut_badges[nom] = haut
        canevas.tag_raise(texte_id)

    def couleur_bandeau_titre (fond):
        ## fond du nom : couleur de la boite assombrie
        try:
            r, g, b = (c / 257 for c in panneau.winfo_rgb(fond))
        except tk.TclError:
            r = g = b = 255
        return "#%02x%02x%02x" % tuple(int(c * 0.72) for c in (r, g, b))

    def dessiner_bandeau_titre (nom):
        ## nom tout en haut, sur un bandeau de toute la largeur (coins superieurs
        ## arrondis comme la boite) ; hauteur adaptee au nom (une ou plusieurs lignes)
        canevas, _, texte = boites[nom]
        fond_id = bandeaux_titre[nom]
        canevas.coords(texte, taille_boites / 2, 6)
        x0, y0, x1, y1 = canevas.bbox(texte)
        haut, bas = 3, y1 + 3
        g, d = 3, taille_boites - 3
        r = min(int(taille_boites * 0.2), bas - haut)  # meme arrondi que la boite
        canevas.coords(fond_id, g, haut + r, g, haut, g + r, haut, d - r, haut, d, haut, d, haut + r,
                       d, bas, d, bas, g, bas, g, bas)
        couleur = couleur_bandeau_titre(couleurs_boites.get(nom, "white"))
        canevas.itemconfig(fond_id, fill = couleur)
        canevas.itemconfig(texte, fill = couleur_texte(couleur))
        canevas.tag_raise(texte)

    taille_infos_commune = {"valeur": None}       # police commune du texte de configuration des boites

    def zone_infos (nom):
        ## zone du texte de configuration : entre le bandeau du nom et le badge d'etat
        canevas, _, texte = boites[nom]
        cadre_titre = canevas.bbox(bandeaux_titre[nom]) or canevas.bbox(texte)
        y = (cadre_titre[3] if cadre_titre else 0.3 * taille_boites) + 0.04 * taille_boites
        bas = haut_badges.get(nom, taille_boites) - 2
        return y, bas

    def taille_infos_ajustee (nom):
        ## plus grande police (de police(taille) - 2 jusqu'a 6) pour laquelle toute
        ## la configuration de la boite tient en hauteur et en largeur
        y, bas = zone_infos(nom)
        lignes = texte_infos_boite(nom).split("\n")
        for taille_infos in range(max(6, police(taille_boites) - 2), 5, -1):
            police_mesure = tkfont.Font(font = ('arial', taille_infos))
            interligne = police_mesure.metrics("linespace")
            if len(lignes) * interligne <= bas - y and max(police_mesure.measure(l) for l in lignes) <= taille_boites - 22:
                return taille_infos
        return 6

    def taille_infos_minimale ():
        ## taille minimale du texte de configuration, proportionnelle a la taille
        ## des boites (8 au zoom par defaut, jamais moins de 7) ; si la
        ## configuration ne tient pas a cette taille, la molette la fait defiler
        return max(7, police(taille_boites) - 7)

    def placer_toutes_infos ():
        ## meme taille de police dans toutes les boites : la plus grande qui
        ## convient a chacune, sans descendre sous taille_infos_minimale()
        noms = [n for n, (cv, _, _) in boites.items() if cv.winfo_exists()]
        commune = min((taille_infos_ajustee(n) for n in noms), default = None)
        taille_infos_commune["valeur"] = None if commune is None else max(commune, taille_infos_minimale())
        for n in noms:
            placer_infos(n)

    def placer_infos (nom):
        ## configuration entre le bandeau du nom et celui du statut ; si elle ne
        ## tient pas, seules les lignes visibles sont affichees et la molette de la
        ## souris fait defiler les autres (fleches ▲ ▼ quand il y en a d'autres)
        canevas, _, texte = boites[nom]
        info = infos[nom]
        y, bas = zone_infos(nom)
        lignes = texte_infos_boite(nom).split("\n")
        ## police commune a toutes les boites (placer_toutes_infos) ; a defaut,
        ## police ajustee a cette boite
        taille_infos = taille_infos_commune["valeur"] or max(taille_infos_ajustee(nom), taille_infos_minimale())
        police_infos = ('arial', taille_infos)
        police_mesure = tkfont.Font(font = police_infos)
        interligne = police_mesure.metrics("linespace")
        canevas.itemconfig(info, font = police_infos)
        ## ligne trop longue pour la largeur de la boite : raccourcie avec « … »
        ## (sinon elle passerait sur deux lignes)
        largeur_max = taille_boites - 22
        courtes = []
        for l in lignes:
            if police_mesure.measure(l) > largeur_max:
                while len(l) > 1 and police_mesure.measure(l + "…") > largeur_max:
                    l = l[:-1]
                l = l.rstrip() + "…"
            courtes.append(l)
        lignes = courtes
        n_visibles = max(1, int((bas - y) // interligne))
        debut = min(max(defilement.get(nom, 0), 0), max(0, len(lignes) - n_visibles))
        defilement[nom] = debut
        canevas.itemconfig(info, text = "\n".join(lignes[debut:debut + n_visibles]))
        canevas.coords(info, 8, y)                    # aligne a gauche
        fleches = fleches_defilement[nom]
        couleur = couleur_texte(couleurs_boites.get(nom, "white"))
        canevas.itemconfig(fleches[0], text = "▲" if debut > 0 else "", fill = couleur, font = police_infos)
        canevas.itemconfig(fleches[1], text = "▼" if debut + n_visibles < len(lignes) else "", fill = couleur, font = police_infos)
        canevas.coords(fleches[0], taille_boites - 6, y)
        canevas.coords(fleches[1], taille_boites - 6, bas)

    def defiler_infos (event, nom):
        ## molette sur une boite : defilement de sa configuration d'une ligne
        if getattr(event, "num", None) in (4, 5):
            pas = -1 if event.num == 4 else 1
        else:
            pas = -1 if event.delta > 0 else 1
        defilement[nom] = defilement.get(nom, 0) + pas
        placer_infos(nom)
        return "break"

    ## ------ boites de comparaison ------
    def taille_comparaison ():
        cote = int(round(taille_comparaisons * ECHELLE_COMPARAISON))
        return cote, cote                                 # barre de zoom de la barre verticale droite, agrandie

    def zone_comparaison ():
        ## bornes de deplacement d'une boite de comparaison : partie droite du panneau
        largeur_c, hauteur_c = taille_comparaison()
        largeur = max(panneau.winfo_width(), parent.winfo_width())
        hauteur = max(panneau.winfo_height(), parent.winfo_height())
        xmin, ymin = limite_gauche() + 12, int(0.01 * hauteur)
        return xmin, ymin, max(xmin, largeur - largeur_c - 10), max(ymin, hauteur - hauteur_c - 10)

    def position_defaut_comparaison (indice):
        ## grille dans la partie droite, sous son titre
        largeur_c, hauteur_c = taille_comparaison()
        xmin, ymin, xmax, ymax = zone_comparaison()
        ymin += 60
        colonnes = max(1, ((xmax - xmin) + largeur_c) // (largeur_c + ESPACEMENT_BOITES))
        ligne, colonne = divmod(indice, colonnes)
        return xmin + colonne * (largeur_c + ESPACEMENT_BOITES), ymin + ligne * (hauteur_c + ESPACEMENT_BOITES)

    decor_partage = []                             # separateur et titre de la partie droite

    def dessiner_partage ():
        for w in decor_partage:
            if w.winfo_exists():
                w.destroy()
        decor_partage.clear()
        if not comparaisons:
            return
        largeur = max(panneau.winfo_width(), parent.winfo_width())
        x = limite_gauche()
        trait = tk.Frame(panneau, width = 2, background = "gray70")
        trait.place(x = x, y = 10, width = 2, relheight = 1, height = -20)
        titre_c = Label(panneau, text = "Comparisons", font = ('arial', 16), fg = "saddlebrown", background = "white")
        titre_c.place(x = x + 12, rely = 0.01)
        decor_partage.extend([trait, titre_c])

    def apparence_comparaisons ():
        for c, e in comps.items():
            if not e["canevas"].winfo_exists():
                continue
            if c == cible["nom"]:
                e["canevas"].itemconfig(e["forme"], outline = COULEUR_COMPARAISON_CIBLE, width = 3, dash = "")
            elif c == selection.get("comparaison"):
                e["canevas"].itemconfig(e["forme"], outline = COULEUR_SELECTION_BOITE, width = 3, dash = (6, 3))
            else:
                e["canevas"].itemconfig(e["forme"], outline = "gray55", width = 2, dash = (6, 3))

    lignes_choisies = {}                           # comparaison -> modeles selectionnes dans la boite (a retirer)
    defilement_c = {}                              # comparaison -> indice du premier modele affiche (molette)

    def ajuster_textes (textes, largeur_dispo, taille_max, taille_min = 6, gras = False):
        """ Noms adaptes a la largeur disponible : police reduite (jusqu'a
        taille_min) pour que tous tiennent sur une ligne ; s'ils sont encore trop
        longs, ils sont raccourcis avec « … ». Renvoie (taille, textes). """
        style = ('bold',) if gras else ()
        taille = max(taille_min, taille_max)
        while taille > taille_min and any(tkfont.Font(font = ('arial', taille) + style).measure(t) > largeur_dispo for t in textes):
            taille -= 1
        mesure = tkfont.Font(font = ('arial', taille) + style).measure
        sortie = []
        for t in textes:
            if mesure(t) > largeur_dispo:
                while len(t) > 1 and mesure(t + "…") > largeur_dispo:
                    t = t[:-1]
                t = t.rstrip() + "…"
            sortie.append(t)
        return taille, sortie

    def dessiner_comparaison (c):
        ## cadre en pointilles, nom sur un bandeau, indices choisis, puis les modeles
        ## deposes (une ligne par modele, sur la couleur de sa boite) ; en bas, les
        ## fleches ➜ (faire entrer les modeles selectionnes) et ⬅ (retirer)
        e = comps[c]
        cv = e["canevas"]
        largeur_c, hauteur_c = taille_comparaison()
        cv.configure(width = largeur_c, height = hauteur_c)
        r = int(taille_comparaisons * 0.2)
        cv.coords(e["forme"], *points_arrondis(3, 3, largeur_c - 3, hauteur_c - 3, r))
        ## couleur de la boite : choisie, sinon couleur par defaut (bandeau bleu-gris)
        fond_c = couleurs_comparaisons.get(c)
        cv.itemconfig(e["forme"], fill = fond_c or COULEUR_COMPARAISON)
        couleur_bandeau = couleur_bandeau_titre(fond_c) if fond_c else "#5B7A99"
        cv.itemconfig(e["bandeau"], fill = couleur_bandeau)
        cv.itemconfig(e["titre"], fill = couleur_texte(couleur_bandeau))
        texte_fond = couleur_texte(fond_c or COULEUR_COMPARAISON)
        taille_police = police(taille_comparaisons)
        taille_titre, (titre_court,) = ajuster_textes([c], largeur_c - 16, taille_police, 6, gras = True)
        cv.itemconfig(e["titre"], text = titre_court, font = ('arial', taille_titre, 'bold'), width = 0)
        cv.coords(e["titre"], largeur_c / 2, 7)
        x0, y0, x1, y1 = cv.bbox(e["titre"])
        bas = y1 + 4
        cv.coords(e["bandeau"], 4, 4 + r, 4, 4, 4 + r, 4, largeur_c - 4 - r, 4, largeur_c - 4, 4, largeur_c - 4, 4 + r,
                  largeur_c - 4, bas, largeur_c - 4, bas, 4, bas, 4, bas)
        police_liste = ('arial', max(6, taille_police - 1))
        interligne = tkfont.Font(font = police_liste).metrics("linespace")
        ## indices de comparaison choisis (Settings)
        indices = indices_comparaison.get(c) or []
        cv.itemconfig(e["indices"], text = " · ".join(indices), font = ('arial', max(6, taille_police - 2), 'italic'),
                      fill = "#2F4A66" if texte_fond != "white" else "white")
        cv.coords(e["indices"], largeur_c / 2, bas + 2)
        haut_liste = bas + 4 + (interligne if indices else 0)
        ## fleches : ⬅ en bas a gauche (retirer), ➜ en bas a droite (faire entrer)
        diametre = max(16, int(0.24 * taille_comparaisons))
        police_fleche = ('arial', max(8, int(diametre * 0.6)), 'bold')
        y1f = hauteur_c - 7
        for cle_rond, cle_fleche, x0f in (("rond", "fleche", largeur_c - 7 - diametre), ("rond_retour", "fleche_retour", 7)):
            cv.coords(e[cle_rond], x0f, y1f - diametre, x0f + diametre, y1f)
            cv.coords(e[cle_fleche], x0f + diametre / 2, y1f - diametre / 2)
            cv.itemconfig(e[cle_fleche], font = police_fleche)
        e["zone_fleche"] = (largeur_c - 7 - diametre, y1f - diametre, largeur_c - 7, y1f)
        e["zone_retour"] = (7, y1f - diametre, 7 + diametre, y1f)
        ## lignes des modeles
        cv.delete("ligne_modele")
        e["lignes"] = []
        modeles = [m for m in modeles_comparaison.get(c, []) if m in analyses]
        choisies = lignes_choisies.setdefault(c, set())
        choisies &= set(modeles)
        ## titres des boites des modeles (« nom : no-cov » ou « nom : with-cov »,
        ## et non plus « methode : reponse »), adaptes a la largeur de la boite
        ## (une ligne chacun) ; meme taille de police pour tous, gras pour les
        ## modeles mis en evidence
        ## tous les modeles sont affiches : police des noms reduite (jusqu'a 7)
        ## et lignes resserrees tant qu'ils ne tiennent pas tous ; au-dela, la
        ## molette de la souris fait defiler la liste (fleches ▲ ▼).
        ## La rangee du bas n'est reservee que si une fleche ➜ / ⬅ est affichee.
        voir_entree = any(n in analyses for n in selection["multi"])
        voir_retour = bool(a_retirer(c))
        bas_liste = (y1f - diametre - 4) if (voir_entree or voir_retour) else (y1f - 2)
        titres = [titre_boite(m) for m in modeles]
        taille_depart = max(7, taille_police - 1)
        for taille_essai in range(taille_depart, 6, -1):
            taille_noms, noms_courts = ajuster_textes(titres, largeur_c - 26, taille_essai, min(6, taille_essai), gras = True)
            espace = 4 if taille_noms >= 10 else 2              # marge interieure d'une ligne
            hauteur_ligne = tkfont.Font(font = ('arial', taille_noms)).metrics("linespace") + espace
            place = max(1, int((bas_liste - haut_liste) // (hauteur_ligne + 1)))
            if len(modeles) <= place:
                break
        defile = len(modeles) > place
        if defile:                                 # place pour les fleches de defilement a droite
            taille_noms, noms_courts = ajuster_textes(titres, largeur_c - 36, taille_noms, min(6, taille_noms), gras = True)
        noms_courts = dict(zip(modeles, noms_courts))
        police_noms = ('arial', taille_noms)
        debut = min(max(defilement_c.get(c, 0), 0), max(0, len(modeles) - place)) if defile else 0
        defilement_c[c] = debut
        visibles = modeles[debut:debut + place]
        droite = largeur_c - (20 if defile else 8)      # marge a droite pour les fleches de defilement
        y = haut_liste
        for m in visibles:
            fond = couleurs_boites.get(m, "white")
            choisie = m in choisies
            ## modele selectionne (a retirer) : mis en evidence par un cadre orange
            ## epais et un texte en gras ; les autres modeles sont estompes
            ## boite du modele selectionnee dans la partie des modeles : cadre bleu
            ## (meme couleur que le contour de la boite selectionnee) et texte en gras
            liee = (not choisie) and m in selection["multi"]
            if choisie or liee:
                cv.create_rectangle(6, y - 2, droite + 2, y + hauteur_ligne + 2, fill = "",
                                    outline = COULEUR_MODELE_CHOISI if choisie else COULEUR_SELECTION_BOITE,
                                    width = 3, tags = ("ligne_modele",))
            cv.create_rectangle(8, y, droite, y + hauteur_ligne, fill = fond,
                                outline = COULEUR_MODELE_CHOISI if choisie else "gray60", width = 1,
                                stipple = "gray50" if (choisies and not choisie) else "", tags = ("ligne_modele",))
            cv.create_text(12, y + hauteur_ligne / 2, text = noms_courts[m], anchor = "w",
                           font = police_noms + (("bold",) if (choisie or liee) else ()),
                           fill = couleur_texte(fond) if (choisie or not choisies) else "gray40",
                           tags = ("ligne_modele",))
            e["lignes"].append((y, y + hauteur_ligne, m))
            y += hauteur_ligne + 1
        if defile:                                 # fleches : modeles caches au-dessus / en dessous
            couleur_fleches = "#2F4A66" if texte_fond != "white" else "white"
            police_fl = ('arial', max(7, taille_noms), 'bold')
            if debut > 0:
                cv.create_text(largeur_c - 11, haut_liste, text = "▲", anchor = "n", font = police_fl,
                               fill = couleur_fleches, tags = ("ligne_modele",))
            if debut + place < len(modeles):
                cv.create_text(largeur_c - 11, y - 2, text = "▼", anchor = "s", font = police_fl,
                               fill = couleur_fleches, tags = ("ligne_modele",))
        if not modeles:
            texte, position, ancre = traduire("Select models, then click on the arrow"), (largeur_c / 2, (haut_liste + bas_liste) / 2), "center"
        else:
            texte, position, ancre = "", (0, 0), "nw"
        cv.itemconfig(e["contenu"], text = texte, font = police_liste, fill = "gray45" if texte_fond != "white" else "gray90", width = largeur_c - 18,
                      anchor = ancre, justify = "center" if not modeles else "left")
        cv.coords(e["contenu"], *position)
        ## fleches affichees seulement quand elles servent (voir_entree / voir_retour, plus haut) :
        ##   ➜ si une ou plusieurs boites de modeles sont selectionnees ;
        ##   ⬅ si un modele de cette comparaison est selectionne (dans la boite
        ##     de comparaison, ou par sa boite de modele)
        for cle_rond, cle_fleche, cle_zone, visible in (("rond", "fleche", "zone_fleche", voir_entree),
                                                        ("rond_retour", "fleche_retour", "zone_retour", voir_retour)):
            for cle in (cle_rond, cle_fleche):
                cv.itemconfig(e[cle], state = "normal" if visible else "hidden")
                cv.tag_raise(e[cle])
            if not visible:
                e[cle_zone] = None                 # fleche masquee : pas cliquable

    dernier_clic_c = {"nom": None, "temps": 0}

    def dans_zone (zone_, x, y):
        x0, y0, x1, y1 = zone_ or (0, 0, -1, -1)
        return x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2

    def sur_fleche (c, x, y):
        return dans_zone(comps[c].get("zone_fleche"), x, y)

    def sur_retour (c, x, y):
        return dans_zone(comps[c].get("zone_retour"), x, y)

    def defiler_comparaison (event, c):
        ## molette sur une boite de comparaison : defilement de sa liste de modeles
        if getattr(event, "num", None) in (4, 5):
            pas = -1 if event.num == 4 else 1
        else:
            pas = -1 if event.delta > 0 else 1
        defilement_c[c] = defilement_c.get(c, 0) + pas
        dessiner_comparaison(c)
        return "break"

    def ligne_sous (c, x, y):
        largeur_c = taille_comparaison()[0]
        if not 8 <= x <= largeur_c - 8:
            return None
        return next((m for y0, y1, m in comps[c].get("lignes", []) if y0 <= y <= y1), None)

    def entrer_selection (c):
        ## fleche ➜ : les boites de modeles selectionnees entrent dans la comparaison
        choisis = [n for n in selection["multi"] if n in analyses]
        if not choisis:
            messagebox.showinfo("Comparison", "Select one or more model boxes first (Shift, Ctrl or Cmd + click to select several), then click on the arrow.")
            return
        deja = modeles_comparaison.setdefault(c, [])
        nouveaux = [n for n in choisis if n not in deja]
        if not nouveaux:
            _message_barre("The selected models are already in « " + c + " »")
            return
        deja.extend(nouveaux)
        dessiner_comparaison(c)
        historique_valider("Add " + str(len(nouveaux)) + " model(s) to « " + c + " »")
        _message_barre(str(len(nouveaux)) + " model(s) added to « " + c + " »")

    def a_retirer (c):
        ## modeles de la comparaison selectionnes : dans la boite de comparaison
        ## (clic sur leur ligne) ou par leur boite de modele
        presents = set(modeles_comparaison.get(c, []))
        return (set(lignes_choisies.get(c) or set()) | set(selection["multi"])) & presents

    def retirer_selection (c):
        ## fleche ⬅ : les modeles selectionnes sortent de la comparaison
        choisies = a_retirer(c)
        if not choisies:
            messagebox.showinfo("Comparison", "Click on one or more models in the comparison box to select them, then click on the arrow ⬅.")
            return
        modeles_comparaison[c] = [m for m in modeles_comparaison.get(c, []) if m not in choisies]
        n = len(choisies)
        lignes_choisies[c] = set()
        dessiner_comparaison(c)
        historique_valider("Remove " + str(n) + " model(s) from « " + c + " »")
        _message_barre(str(n) + " model(s) removed from « " + c + " »")

    def saisir_comparaison (event, c):
        selection["comparaison"] = c                # la selection des boites de modeles est conservee
        if sur_fleche(c, event.x, event.y):
            entrer_selection(c)
            apparence_comparaisons()
            return
        if sur_retour(c, event.x, event.y):
            retirer_selection(c)
            apparence_comparaisons()
            return
        m = ligne_sous(c, event.x, event.y)
        if m is not None:
            ## clic sur un modele de la boite : selectionne / deselectionne (a retirer)
            choisies = lignes_choisies.setdefault(c, set())
            choisies.symmetric_difference_update({m})
            dessiner_comparaison(c)
            apparence_comparaisons()
            return
        double = dernier_clic_c["nom"] == c and 0 <= event.time - dernier_clic_c["temps"] <= 400
        dernier_clic_c.update(nom = None if double else c, temps = event.time)
        fermer_parametres_boite()
        apparence()
        apparence_comparaisons()
        if double:
            glisse_c.update(nom = None, ref = None, origine = None)
            gerer_comparaison(parent, c)
            return
        cv = comps[c]["canevas"]
        tk.Misc.tkraise(cv)
        glisse_c.update(nom = c, ref = (event.x_root, event.y_root), origine = (cv.winfo_x(), cv.winfo_y()))

    def glisser_comparaison (event, c):
        if glisse_c["nom"] != c:
            return
        xmin, ymin, xmax, ymax = zone_comparaison()
        x = min(max(glisse_c["origine"][0] + event.x_root - glisse_c["ref"][0], xmin), xmax)
        y = min(max(glisse_c["origine"][1] + event.y_root - glisse_c["ref"][1], ymin), ymax)
        comps[c]["canevas"].place(x = x, y = y)

    def lacher_comparaison (event, c):
        if glisse_c["nom"] != c:
            return
        cv = comps[c]["canevas"]
        ancienne = positions_comparaisons.get(c)
        positions_comparaisons[c] = (cv.winfo_x(), cv.winfo_y())
        glisse_c.update(nom = None, ref = None, origine = None)
        if ancienne != positions_comparaisons[c]:
            historique_valider("Move « " + c + " »")

    def construire_comparaisons ():
        for e in comps.values():
            e["canevas"].destroy()
        comps.clear()
        dessiner_partage()
        xmin_c, ymin_c, xmax_c, ymax_c = zone_comparaison()
        for indice, c in enumerate(comparaisons):
            largeur_c, hauteur_c = taille_comparaison()
            cv = Canvas(panneau, width = largeur_c, height = hauteur_c, background = "white", highlightthickness = 0, cursor = "hand2")
            x, y = positions_comparaisons.get(c) or position_defaut_comparaison(indice)
            x, y = min(max(x, xmin_c), xmax_c), min(max(y, ymin_c), ymax_c)     # dans la partie droite
            positions_comparaisons[c] = (x, y)
            cv.place(x = x, y = y)
            comps[c] = {"canevas": cv,
                        "forme": cv.create_polygon(0, 0, 1, 1, smooth = True, fill = COULEUR_COMPARAISON, outline = "gray55", width = 2, dash = (6, 3)),
                        "bandeau": cv.create_polygon(0, 0, 1, 1, smooth = True, fill = "#5B7A99", outline = ""),
                        "titre": cv.create_text(0, 0, anchor = "n", fill = "white", justify = "center"),
                        "contenu": cv.create_text(0, 0, anchor = "nw"),
                        "indices": cv.create_text(0, 0, anchor = "n", fill = "#2F4A66"),
                        "rond": cv.create_oval(0, 0, 1, 1, fill = "#5B7A99", outline = "white", width = 1),
                        "fleche": cv.create_text(0, 0, text = "➜", fill = "white", anchor = "center"),
                        "rond_retour": cv.create_oval(0, 0, 1, 1, fill = "#A0522D", outline = "white", width = 1),
                        "fleche_retour": cv.create_text(0, 0, text = "⬅", fill = "white", anchor = "center")}
            dessiner_comparaison(c)
            cv.bind("<Button-1>", lambda event, n = c: saisir_comparaison(event, n))
            cv.bind("<B1-Motion>", lambda event, n = c: glisser_comparaison(event, n))
            cv.bind("<ButtonRelease-1>", lambda event, n = c: lacher_comparaison(event, n))
            for evenement in ("<MouseWheel>", "<Button-4>", "<Button-5>"):   # molette (macOS / Windows, Linux)
                cv.bind(evenement, lambda event, n = c: defiler_comparaison(event, n))
            cv.bind("<Motion>", lambda event, n = c: comps[n]["canevas"].configure(
                cursor = "hand2" if (sur_fleche(n, event.x, event.y) or sur_retour(n, event.x, event.y)
                                     or ligne_sous(n, event.x, event.y)) else "fleur"))
        apparence_comparaisons()

    def construire ():
        for canevas, _, _ in boites.values():
            canevas.destroy()
        boites.clear()
        infos.clear()
        badges.clear()
        bandeaux_titre.clear()
        fleches_defilement.clear()
        r = int(taille_boites * 0.2)
        for indice, nom in enumerate(analyses):
            canevas = Canvas(panneau, width = taille_boites, height = taille_boites, background = "white", highlightthickness = 0, cursor = "hand2")
            x, y = positions_boites.get(nom) or position_defaut(indice)
            xmin_a, ymin_a, xmax_a, ymax_a = zone()
            x, y = min(max(x, xmin_a), xmax_a), min(max(y, ymin_a), ymax_a)     # dans la partie des modeles
            positions_boites[nom] = (x, y)
            canevas.place(x = x, y = y)
            fond = couleurs_boites.get(nom, "white")
            forme = canevas.create_polygon(points_arrondis(2, 2, taille_boites - 2, taille_boites - 2, r), smooth = True,
                                           fill = fond, outline = "gray70", width = 1)
            ## nom en haut, puis methode, K, RE et df ; etat en bas, centre, sur fond colore
            bandeaux_titre[nom] = canevas.create_polygon(0, 0, 1, 1, smooth = True, outline = "")   # fond du nom
            texte = canevas.create_text(taille_boites / 2, 6, text = titre_boite(nom), anchor = "n",
                                        font = ('arial', police(taille_boites), 'bold'),
                                        fill = couleur_texte(fond), width = taille_boites - 14, justify = "center")
            infos[nom] = canevas.create_text(taille_boites / 2, 0.5 * taille_boites, text = texte_infos_boite(nom), anchor = "nw",
                                             font = ('arial', max(6, police(taille_boites) - 2)),
                                             fill = couleur_texte(fond), width = taille_boites - 14, justify = "left")
            boites[nom] = (canevas, forme, texte)
            badges[nom] = (canevas.create_polygon(0, 0, 1, 1, smooth = True, outline = ""),
                           canevas.create_text(0, 0, text = "", anchor = "center", justify = "center"))
            fleches_defilement[nom] = (canevas.create_text(0, 0, anchor = "ne", text = ""),
                                       canevas.create_text(0, 0, anchor = "se", text = ""))
            dessiner_bandeau_titre(nom)
            dessiner_badge(nom)
            placer_infos(nom)
            canevas.bind("<Button-1>", lambda event, n = nom: saisir(event, n))
            canevas.bind("<B1-Motion>", lambda event, n = nom: glisser(event, n))
            canevas.bind("<ButtonRelease-1>", lambda event, n = nom: lacher(event, n))
            for evenement in ("<MouseWheel>", "<Button-4>", "<Button-5>"):   # molette (macOS / Windows, Linux)
                canevas.bind(evenement, lambda event, n = nom: defiler_infos(event, n))
        placer_toutes_infos()                     # meme police dans toutes les boites
        apparence()
        construire_comparaisons()

    def redimensionner (valeur):
        ## barre verticale gauche : taille des boites (position et selection conservees)
        global taille_boites
        taille_boites = int(TAILLE_BOITE_MIN + float(valeur) / 100 * (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN))
        r = int(taille_boites * 0.2)
        for nom, (canevas, forme, texte) in boites.items():
            canevas.configure(width = taille_boites, height = taille_boites)
            canevas.coords(forme, *points_arrondis(2, 2, taille_boites - 2, taille_boites - 2, r))
            canevas.itemconfig(texte, width = taille_boites - 14, font = ('arial', police(taille_boites), 'bold'))
            dessiner_bandeau_titre(nom)
            canevas.itemconfig(infos[nom], width = taille_boites - 14, font = ('arial', max(6, police(taille_boites) - 2)))
            dessiner_badge(nom)
        placer_toutes_infos()                     # meme police dans toutes les boites

    def maj_infos ():
        ## etat, methode et K de chaque boite (appele apres un changement)
        for nom, (canevas, _, texte) in boites.items():
            if canevas.winfo_exists():
                canevas.itemconfig(texte, text = titre_boite(nom))
                canevas.itemconfig(infos[nom], text = texte_infos_boite(nom))
                dessiner_bandeau_titre(nom)
                dessiner_badge(nom)
        placer_toutes_infos()                     # meme police dans toutes les boites
        for c, e in comps.items():
            if e["canevas"].winfo_exists():
                dessiner_comparaison(c)

    panneau_boites["rafraichir"] = maj_infos

    def redimensionner_comparaisons ():
        ## barre de zoom de la barre droite : taille des boites de comparaison
        ## (reconstruites, et ramenees dans la partie droite si besoin)
        if panneau.winfo_exists():
            construire_comparaisons()

    panneau_boites["comparaisons"] = redimensionner_comparaisons

    ## la barre verticale gauche pilote la taille des boites tant que le panneau est ouvert
    precedent = {"commande": scale.cget("command"), "valeur": scale.get()}

    def restaurer_barre (event = None):
        if event is not None and event.widget is not panneau:
            return
        try:
            scale.configure(command = "")
            scale.set(precedent["valeur"])
            scale.configure(command = precedent["commande"])
        except tk.TclError:
            pass

    scale.configure(command = "")
    scale.set(int((taille_boites - TAILLE_BOITE_MIN) / (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN) * 100))
    scale.configure(command = redimensionner)
    panneau.bind("<Destroy>", restaurer_barre, add = "+")
    def clic_fond (event):
        ## clic sur le fond : deselection et fermeture de la boite « Settings »
        selection["comparaison"] = None
        selection["multi"] = []
        selectionner(None)
        fermer_parametres_boite()

    panneau.bind("<Button-1>", clic_fond)
    panneau.update_idletasks()
    construire()


def gerer_comparaison (parent, c):
    """ Settings (barre droite) ou double clic sur une boite de comparaison :
    choix des indices de comparaison (ARI, Jaccard ; l'un, l'autre ou les deux). """
    hote = panneau_courant if panneau_courant is not None and panneau_courant.winfo_exists() else Center_frame
    boite = nouvelle_boite(hote)
    Label(boite, text = c, font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, sticky = "w", padx = 15, pady = (10, 0))
    modeles = [m for m in modeles_comparaison.get(c, []) if m in analyses]
    Label(boite, text = str(len(modeles)) + " model(s) in the comparison", font = ('arial', 13)).grid(
        row = 1, column = 0, sticky = "w", padx = 15, pady = (0, 8))
    ## liste des modeles de la comparaison (fond : couleur de la boite du modele)
    Label(boite, text = "Models", font = ('arial', 13, 'bold'), fg = "gray30").grid(row = 2, column = 0, sticky = "w", padx = 15)
    liste = tk.Listbox(boite, font = ('arial', 13), selectmode = tk.BROWSE, exportselection = False, width = 40,
                       height = min(max(len(modeles), 3), 10), relief = GROOVE, activestyle = "none")
    liste.grid(row = 3, column = 0, sticky = "ew", padx = 15, pady = (2, 8))
    for m in modeles:
        liste.insert(END, "  " + libelle_analyse(m, analyses) + "   [" + m + "]")
        fond = couleurs_boites.get(m, "white")
        try:
            r_, g_, b_ = boite.winfo_rgb(fond)
            texte_couleur = "white" if (0.299 * r_ + 0.587 * g_ + 0.114 * b_) / 65535 < 0.55 else "gray10"
        except tk.TclError:
            texte_couleur = "gray10"
        liste.itemconfig(END, background = fond, foreground = texte_couleur,
                         selectbackground = fond, selectforeground = texte_couleur)
    if not modeles:
        liste.insert(END, "  " + traduire("No model yet: select model boxes, then click on the arrow ➜."))
        liste.itemconfig(END, foreground = "gray50")
    liste.bind("<<ListboxSelect>>", lambda event: liste.selection_clear(0, END))   # liste en lecture seule (defilement possible)
    Label(boite, text = "Comparison index", font = ('arial', 13, 'bold'), fg = "gray30").grid(row = 4, column = 0, sticky = "w", padx = 15)
    tk.Frame(boite, height = 1, background = "gray60").grid(row = 5, column = 0, sticky = "ew", padx = 15, pady = (2, 4))
    actuels = indices_comparaison.get(c) or list(INDICES_DEFAUT)
    cases = {}
    ## indices sur une meme ligne, en colonnes de meme largeur (disposition symetrique)
    cadre_indices = Frame(boite)
    cadre_indices.grid(row = 6, column = 0, sticky = "ew", padx = 15, pady = (2, 2))
    for k, indice in enumerate(INDICES_COMPARAISON):
        cadre_indices.columnconfigure(k, weight = 1, uniform = "indices")
        cases[indice] = BooleanVar(value = indice in actuels)
        Checkbutton(cadre_indices, text = indice, variable = cases[indice], font = ('arial', 16, 'bold')).grid(
            row = 0, column = k, padx = 10, pady = 2)
    ligne = 7
    Label(boite, text = "ARI: adjusted Rand index;  Jaccard: Jaccard index (pairs of subjects grouped together)", **AIDE_BOITE).grid(
        row = ligne, column = 0, sticky = "w", padx = 15, pady = (4, 0))
    Label(boite, text = "To remove a model: click on it in the comparison box, then on the arrow ⬅.", **AIDE_BOITE).grid(
        row = ligne + 1, column = 0, sticky = "w", padx = 15)
    ## couleur de la boite : par defaut, ou choisie
    Label(boite, text = "Color", font = ('arial', 13, 'bold'), fg = "gray30").grid(row = ligne + 2, column = 0, sticky = "w", padx = 15, pady = (10, 0))
    tk.Frame(boite, height = 1, background = "gray60").grid(row = ligne + 3, column = 0, sticky = "ew", padx = 15, pady = (2, 4))
    couleur_choisie = {"valeur": couleurs_comparaisons.get(c)}
    cadre_couleur = Frame(boite)
    cadre_couleur.grid(row = ligne + 4, column = 0, sticky = "w", padx = (30, 15))
    echantillon = Label(cadre_couleur, text = "      ", background = couleur_choisie["valeur"] or COULEUR_COMPARAISON, relief = "solid", bd = 1)
    echantillon.pack(side = LEFT, padx = (0, 8))
    etat_couleur = Label(cadre_couleur, text = "", **AIDE_BOITE)

    def montrer_couleur ():
        echantillon.configure(background = couleur_choisie["valeur"] or COULEUR_COMPARAISON)
        etat_couleur.configure(text = "default" if couleur_choisie["valeur"] is None else couleur_choisie["valeur"])

    def choisir_couleur ():
        choix = colorchooser.askcolor(color = couleur_choisie["valeur"] or COULEUR_COMPARAISON,
                                      title = "Color of the comparison box", parent = boite)
        if choix and choix[1]:
            couleur_choisie["valeur"] = choix[1]
            montrer_couleur()

    def couleur_defaut ():
        couleur_choisie["valeur"] = None
        montrer_couleur()

    tk.Button(cadre_couleur, text = "Choose…", command = choisir_couleur, width = 9).pack(side = LEFT)
    tk.Button(cadre_couleur, text = "Default", command = couleur_defaut, width = 8).pack(side = LEFT, padx = (4, 8))
    etat_couleur.pack(side = LEFT)
    montrer_couleur()

    def enregistrer ():
        choisis = [i for i in INDICES_COMPARAISON if cases[i].get()]
        if not choisis:
            messagebox.showwarning("Comparison", "Check at least one comparison index.", parent = boite)
            return
        ancien = (indices_comparaison.get(c), couleurs_comparaisons.get(c))
        indices_comparaison[c] = choisis
        if couleur_choisie["valeur"] is None:
            couleurs_comparaisons.pop(c, None)
        else:
            couleurs_comparaisons[c] = couleur_choisie["valeur"]
        boite.destroy()
        rafraichir_boites()
        if ancien != (choisis, couleur_choisie["valeur"]):
            historique_valider("Settings « " + c + " »")

    cadre = Frame(boite)
    cadre.grid(row = ligne + 5, column = 0, pady = 10)
    tk.Button(cadre, text = "Save", command = enregistrer, width = 10).pack(side = LEFT, padx = 4)
    tk.Button(cadre, text = "Cancel", command = boite.destroy, width = 10).pack(side = LEFT, padx = 4)


##------ Boutons de la barre verticale droite (boites de comparaison) --------
## Memes boutons que ceux qui suivent « Analysis » a gauche (Delete, Rename,
## Settings, Restore), mais pour la boite de comparaison selectionnee.
def comparaison_choisie (titre, parent):
    c = boite_selectionnee.get("comparaison")
    if c not in comparaisons:
        messagebox.showinfo(titre, "Please select a comparison box first (click on it in the Clustering panel).")
        if panneau_boites["widget"] is not panneau_courant or panneau_courant is None or not panneau_courant.winfo_exists():
            afficher_boites(parent)
        return None
    return c


def supprimer_comparaison (parent):
    """ « Delete » (barre droite) : la boite de comparaison selectionnee passe dans
    la corbeille des comparaisons ; les analyses qu'elle contient ne sont pas touchees. """
    c = comparaison_choisie("Delete", parent)
    if c is None:
        return
    if not messagebox.askyesno("Delete", "Do you really want to delete the comparison box « " + c + " »?\n\n"
                               "The analyses it contains are not deleted. You can restore it later with the « Restore » button (right bar)."):
        return
    nom_corbeille, k = c, 2
    while nom_corbeille in corbeille_comparaisons:
        nom_corbeille, k = c + " (" + str(k) + ")", k + 1
    corbeille_comparaisons[nom_corbeille] = {"modeles": list(modeles_comparaison.pop(c, [])),
                                             "position": positions_comparaisons.pop(c, None),
                                             "indices": indices_comparaison.pop(c, None),
                                             "couleur": couleurs_comparaisons.pop(c, None)}
    comparaisons.remove(c)
    boite_selectionnee["comparaison"] = None
    afficher_boites(parent)
    historique_valider("Delete « " + c + " »")


def renommer_comparaison (parent):
    """ « Rename » (barre droite) : renomme la boite de comparaison selectionnee. """
    c = comparaison_choisie("Rename", parent)
    if c is None:
        return
    nouveau = simpledialog.askstring("Rename", "New name of the comparison box « " + c + " »", initialvalue = c)
    if nouveau is None or nouveau.strip() == "" or nouveau.strip() == c:
        return
    nouveau = nouveau.strip()
    if nouveau in comparaisons or nouveau in analyses:
        messagebox.showwarning("Name already used", "This name is already used. Choose a different name.")
        return
    comparaisons[comparaisons.index(c)] = nouveau
    for dico in (modeles_comparaison, positions_comparaisons, indices_comparaison, couleurs_comparaisons):
        if c in dico:
            dico[nouveau] = dico.pop(c)
    boite_selectionnee["comparaison"] = nouveau
    afficher_boites(parent)
    historique_valider("Rename « " + c + " » → « " + nouveau + " »")


def parametres_comparaison (parent):
    """ « Settings » (barre droite) : modeles de la boite de comparaison selectionnee. """
    c = comparaison_choisie("Settings", parent)
    if c is None:
        return
    if panneau_boites["widget"] is not panneau_courant or not panneau_courant.winfo_exists():
        afficher_boites(parent)
    fermer_parametres_boite()
    gerer_comparaison(parent, c)


def corbeille_comparaison (parent):
    """ « Restore » (barre droite) : corbeille des boites de comparaison supprimees. """
    if not corbeille_comparaisons:
        messagebox.showinfo("Restore", "The recycle bin is empty: no comparison box deleted for the moment.")
        return
    afficher_boites(parent)
    boite = nouvelle_boite(panneau_courant)
    Label(boite, text = "Recycle bin (comparisons)", font = ('arial', 15, 'bold'), fg = "saddlebrown").pack(anchor = "w", padx = 15, pady = (10, 0))
    Label(boite, text = "Select a comparison box to restore", font = ('arial', 13)).pack(anchor = "w", padx = 15, pady = (0, 6))
    liste = tk.Listbox(boite, font = ('arial', 13), selectmode = tk.SINGLE, exportselection = False, width = 32,
                       height = min(max(len(corbeille_comparaisons), 4), 12), relief = GROOVE)
    liste.pack(fill = BOTH, expand = True, padx = 15)
    noms = list(corbeille_comparaisons)
    for n in noms:
        liste.insert(END, n + "   (" + str(len(corbeille_comparaisons[n]["modeles"])) + " model(s))")
    liste.selection_set(0)

    def selection_liste ():
        choix = liste.curselection()
        if not choix:
            messagebox.showinfo("Restore", "Please select a box in the list.", parent = boite)
            return None
        return noms[choix[0]]

    def restaurer ():
        nom = selection_liste()
        if nom is None:
            return
        nom_final = nom
        if nom_final in comparaisons or nom_final in analyses:
            nom_final = simpledialog.askstring("Name already used", "A box is already named « " + nom + " ». New name for the restored box:",
                                               initialvalue = nom + " (restored)", parent = boite)
            if nom_final is None or nom_final.strip() == "":
                return
            nom_final = nom_final.strip()
            if nom_final in comparaisons or nom_final in analyses:
                messagebox.showwarning("Name already used", "This name is already used. Restoration cancelled.", parent = boite)
                return
        infos = corbeille_comparaisons.pop(nom)
        comparaisons.append(nom_final)
        modeles_comparaison[nom_final] = [m for m in infos["modeles"] if m in analyses]   # analyses encore presentes
        if infos.get("position") is not None:
            positions_comparaisons[nom_final] = infos["position"]
        indices_comparaison[nom_final] = infos.get("indices") or list(INDICES_DEFAUT)
        if infos.get("couleur"):
            couleurs_comparaisons[nom_final] = infos["couleur"]
        boite_selectionnee["comparaison"] = nom_final
        afficher_boites(parent)                       # ferme aussi la corbeille
        historique_valider("Restore « " + nom_final + " »")

    def supprimer_definitivement ():
        nom = selection_liste()
        if nom is None:
            return
        if not messagebox.askyesno("Delete permanently", "Permanently delete « " + nom + " »?\n\nThis action cannot be undone.", parent = boite):
            return
        del corbeille_comparaisons[nom]
        boite.destroy()
        historique_valider("Delete permanently « " + nom + " »")
        if corbeille_comparaisons:
            corbeille_comparaison(parent)

    cadre = Frame(boite)
    cadre.pack(pady = 10)
    tk.Button(cadre, text = "Restore", command = restaurer, width = 10).pack(side = LEFT, padx = 4)
    tk.Button(cadre, text = "Delete permanently", command = supprimer_definitivement, width = 16).pack(side = LEFT, padx = 4)
    tk.Button(cadre, text = "Close", command = boite.destroy, width = 8).pack(side = LEFT, padx = 4)
    liste.bind("<Double-Button-1>", lambda event: restaurer())


def fermer_parametres_boite ():
    widget = fenetre_parametres_boite["widget"]
    if widget is not None and widget.winfo_exists():
        widget.destroy()
    fenetre_parametres_boite["widget"] = None


def ouvrir_parametres_boite (parent):
    """ Bouton « Settings » (ou double clic sur une boite) : boite de dialogue
    principale de la boite selectionnee, a droite du panneau Clustering, avec
    le choix de la methode de clustering. """
    nom = boite_selectionnee["nom"]
    if nom not in analyses:
        messagebox.showinfo("Settings", "Please select a box first (click on it in the Clustering panel).")
        return
    if panneau_boites["widget"] is None or panneau_boites["widget"] is not panneau_courant or not panneau_courant.winfo_exists():
        afficher_boites(parent)                   # la boite s'ouvre sur le panneau Clustering
    fermer_parametres_boite()
    largeur = int(round(0.40 * parent.winfo_width()))
    hauteur = int(round(0.93 * parent.winfo_height()))
    boite = Canvas(panneau_courant, background = "white", highlightthickness = 2, relief = GROOVE)
    boite.place(relx = 0.5, rely = 0.06, width = largeur, height = hauteur)
    fenetre_parametres_boite["widget"] = boite
    fenetre_parametres_boite["nom"] = nom
    Label(boite, text = nom, font = ('arial', 15, 'bold'), fg = "saddlebrown", background = "white").pack(pady = (10, 0))
    Label(boite, text = "Please select a clustering method", font = ('arial', 18), background = "white").pack(pady = 10)
    choix = ttk.Combobox(boite, values = METHODES_CLUSTERING, state = "readonly", width = 35)
    choix.set(methodes_boites.get(nom) if methodes_boites.get(nom) in METHODES_CLUSTERING else METHODES_CLUSTERING[0])
    choix.pack()
    ## zone des parametres et des resultats de la methode choisie
    barre = Frame(boite, background = "white")
    barre.pack(padx = 10, pady = (30, 0))          # boutons centres, plus bas sous la liste
    sans_fond = dict(background = "white", highlightbackground = "white", activebackground = "white")
    bouton_param = tk.Button(barre, text = "Display settings", width = 14, **sans_fond)
    zone_resultats = Frame(boite, background = "white")
    zone_resultats.pack(fill = BOTH, expand = True, padx = 4, pady = 4)
    fenetre_parametres_boite["zone"] = zone_resultats

    bouton_resultats = tk.Button(barre, text = "Results", width = 10, **sans_fond)

    def maj_zone ():
        ## InfoMergeCluster : bouton des parametres et, si un resultat existe,
        ## bouton « Results » (affichage dans le panneau central)
        for w in zone_resultats.winfo_children():
            w.destroy()
        if choix.get() in METHODES_EXECUTABLES:
            bouton_param.configure(command = lambda: dialogue_infomerge(parent, nom, zone_resultats, choix.get()))
            bouton_param.pack(side = LEFT)
            if nom in resultats_boites and methodes_boites.get(nom) == choix.get():
                bouton_resultats.configure(command = lambda: panneau_resultats_infomerge(parent, nom))
                bouton_resultats.pack(side = LEFT, padx = (6, 0))
            else:
                bouton_resultats.pack_forget()
            if nom in calculs_en_cours:
                afficher_progression(zone_resultats, [choix.get() + " is running."])
        else:
            bouton_param.pack_forget()
            bouton_resultats.pack_forget()

    def memoriser (event = None):
        if choix.current() > 0:
            if methodes_boites.get(nom) != choix.get():
                resultats_boites.pop(nom, None)    # autre methode : ancien resultat abandonne
                if nom in methodes_boites:
                    parametres_infomerge.pop(nom, None)    # parametres de l'ancienne methode abandonnes
            methodes_boites[nom] = choix.get()     # methode memorisee pour cette boite
            historique_valider("Method « " + nom + " »")
        else:
            methodes_boites.pop(nom, None)
        maj_zone()
        rafraichir_boites()                        # methode et etat affiches dans la boite
        if choix.get() in METHODES_EXECUTABLES and nom not in parametres_infomerge and nom not in calculs_en_cours:
            dialogue_infomerge(parent, nom, zone_resultats, choix.get())   # parametres de la methode

    choix.bind("<<ComboboxSelected>>", memoriser)
    maj_zone()


##-----------------------------------------------------------------------------
##  InfoMergeCluster : parametres (boite de dialogue), execution, resultats
##-----------------------------------------------------------------------------
parametres_infomerge = {}          # boite -> derniers parametres de infomergecluster
resultats_boites = {}              # boite -> resultat (objet renvoye par infomergecluster)
calculs_en_cours = {}              # boite -> {"messages": [...], "resultat": ..., "erreur": ...}

PARAMETRES_INFOMERGE_DEFAUT = {
    ## donnees (colonnes) et modele
    "id": "Patient", "time": "Time", "response": "", "covariates": [],
    "K": 3, "K_max": 8, "df": 15, "degree": 3, "penalty": True, "pen_order": 2, "re": "linear",
    "weights": "constant", "criterion": "BIC", "min_size": 2, "K0": "",
    "standardize": True,               # standardisation Min-Max (temps, reponse, covariables), resultats a l'echelle de depart
    ## algorithme
    "a_dir": 0.5, "n_outer": 3, "quick_cycles": 4, "full_cycles": 15, "inner_cap": 3, "tol": 1e-5,
    "nstart": 5, "seed": "",
    ## graphique (plot_infomergecluster)
    "envelope": False, "level": 0.95, "show_data": True, "max_subjects": 300,
    "all_subjects": False,             # case « All » : toutes les trajectoires individuelles (sinon TN = max_subjects)
    "regressed": False,                # case « Regressed data » (modele avec covariables) : donnees regressees
    "xlab": "Time (month)", "ylab": "", "main": "InfoMergeCluster: K = %d (%s)", "legend": True,
}
PARAMETRES_FKMS_DEFAUT = {
    ## donnees et modele (fkms.covariables.lambda.gcv)
    "id": "Patient", "time": "Time", "response": "", "covariates": [],
    "K": 3, "K_max": 8, "N_bs": 8, "basis": "B", "lambda": 0.0, "lambda_gcv": True, "lambda_common": False,
    "lambda_min": 1e-6, "lambda_max": 1e3, "lambda_n": 30,       # grille des lambda testes par GCV (echelle logarithmique)
    "cov_effect": "cluster", "conf_band": True, "se_type": "sandwich",
    ## algorithme
    "N_random": 10, "N_rep": 100, "seed": "",
    ## graphique (plot_data_cluster)
    "envelope": False, "level": 0.95, "show_data": True, "max_subjects": 300,
    "all_subjects": False, "regressed": False,
    "xlab": "Time (month)", "ylab": "", "main": "FKMS : K = %d", "legend": True,
}
## options du graphique (plot_infomergecluster) : les modifier ne demande pas de relancer le calcul
CLES_GRAPHIQUE_INFOMERGE = {"envelope", "level", "show_data", "max_subjects", "all_subjects", "regressed",
                            "xlab", "ylab", "main", "legend"}


def dialogue_infomerge (parent, nom, zone_resultats, methode = None):
    """ Boite de dialogue des parametres de infomergecluster() pour la boite
    nom : colonnes des donnees (identifiant, temps, reponse, covariables),
    parametres du modele et de l'algorithme, options du graphique
    (plot_infomergecluster). « Save » enregistre la configuration ; le bouton
    « Run » de la barre du haut lance ensuite l'ajustement. """
    methode = methode or methodes_boites.get(nom) or "InfoMergeCluster"
    fkms = methode == "FKMS"                       # FKMS : fkms.covariables.lambda.gcv
    donnees = appliquer_filtres(data_analy) if data_analy is not None else None
    if donnees is None or donnees.shape[1] < 3:
        messagebox.showwarning(methode, "Please import data first (button 'Import data').")
        return
    colonnes = [str(c) for c in donnees.columns]
    p0 = dict(defauts_boite(methode = methode))
    p0.update(parametres_infomerge.get(nom, {}) if methodes_boites.get(nom) == methode else {})
    if p0["response"] not in colonnes:
        p0["response"] = next((c for c in ("Poids", "BMI", "TWL") if c in colonnes),
                              next((c for c in colonnes if c not in (p0["id"], p0["time"])), colonnes[0]))
    boite = nouvelle_boite(panneau_courant)
    Label(boite, text = methode + " — " + nom, font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 0))
    Label(boite, text = "Parameters of fkms.covariables.lambda.gcv()" if fkms else "Parameters of infomergecluster()", font = ('arial', 13)).grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 6))
    ## parametres dans une zone defilante : hauteur reduite, barre de defilement
    ## pour acceder a la suite, poignee en bas a droite pour agrandir la boite
    cadre_defil = Frame(boite)
    cadre_defil.grid(row = 2, column = 0, columnspan = 2, sticky = "nsew")
    toile_param = Canvas(cadre_defil, highlightthickness = 0)
    defil_param = ttk.Scrollbar(cadre_defil, orient = "vertical", command = toile_param.yview)
    toile_param.configure(yscrollcommand = defil_param.set)
    toile_param.pack(side = LEFT, fill = BOTH, expand = True)
    defil_param.pack(side = LEFT, fill = "y")
    contenu = Frame(toile_param)
    toile_param.create_window((0, 0), window = contenu, anchor = "nw")
    gauche, droite = Frame(contenu), Frame(contenu)
    gauche.grid(row = 0, column = 0, sticky = "nw", padx = (15, 10))
    droite.grid(row = 0, column = 1, sticky = "nw", padx = (10, 15))
    champs = {}

    def section (cadre, texte):
        ligne = cadre.grid_size()[1]
        titre_section = Label(cadre, text = texte, font = ('arial', 13, 'bold'), fg = "gray30")
        titre_section.grid(row = ligne, column = 0, columnspan = 2, sticky = "w", pady = (8, 2))
        tk.Frame(cadre, height = 1, background = "gray60").grid(row = ligne + 1, column = 0, columnspan = 2, sticky = "ew", pady = (0, 3))
        return titre_section

    def ligne (cadre, cle, texte, widget_fn):
        r = cadre.grid_size()[1]
        Label(cadre, text = texte, font = ('arial', 12)).grid(row = r, column = 0, sticky = "w", padx = (10, 6), pady = 1)
        w = widget_fn(cadre)
        w.grid(row = r, column = 1, sticky = "w", pady = 1)
        return w

    def entree (cadre, cle, texte, largeur = 10):
        var = StringVar(value = "" if p0[cle] is None else str(p0[cle]))
        ligne(cadre, cle, texte, lambda c: Entry(c, textvariable = var, width = largeur))
        champs[cle] = var

    def liste (cadre, cle, texte, valeurs, largeur = 12):
        cb = ligne(cadre, cle, texte, lambda c: ttk.Combobox(c, values = valeurs, state = "readonly", width = largeur))
        cb.set(p0[cle] if p0[cle] in valeurs else valeurs[0])
        champs[cle] = cb

    def case (cadre, cle, texte, commande = None):
        var = BooleanVar(value = bool(p0[cle]))
        ligne(cadre, cle, texte, lambda c: Checkbutton(c, variable = var, command = commande))
        champs[cle] = var

    ## grille des lambda testes par GCV (FKMS) : borne inferieure, borne superieure et
    ## nombre de valeurs, sur une echelle logarithmique ; boite ouverte en cochant « lambda.gcv »
    grille_lambda = {"lambda_min": float(p0.get("lambda_min", 1e-6)), "lambda_max": float(p0.get("lambda_max", 1e3)),
                     "lambda_n": int(p0.get("lambda_n", 30))}

    def dialogue_grille_lambda ():
        """ Boite « Grid of lambda values (GCV) » ; renvoie True si elle est validee. """
        sous = nouvelle_boite(panneau_courant)
        resultat = {"ok": False}
        Label(sous, text = "Grid of lambda values (GCV)", font = ('arial', 15, 'bold'), fg = "saddlebrown").grid(
            row = 0, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (10, 0))
        Label(sous, text = "Values of lambda tested by generalized cross-validation", font = ('arial', 13)).grid(
            row = 1, column = 0, columnspan = 2, sticky = "w", padx = 15, pady = (0, 6))
        var_min = champ_boite(sous, 2, "Lower bound", format(grille_lambda["lambda_min"], "g"), 14)
        var_max = champ_boite(sous, 3, "Upper bound", format(grille_lambda["lambda_max"], "g"), 14)
        var_n = champ_boite(sous, 4, "Number of values", str(grille_lambda["lambda_n"]), 14)
        Label(sous, text = "The values are equally spaced on a logarithmic scale between the two bounds.", **AIDE_BOITE).grid(
            row = 5, column = 0, columnspan = 2, sticky = "w", padx = 15)

        def valider ():
            try:
                borne_min = float(var_min.get().strip().replace(",", "."))
                borne_max = float(var_max.get().strip().replace(",", "."))
                nombre = int(float(var_n.get().strip().replace(",", ".")))
            except ValueError:
                messagebox.showwarning("lambda.gcv", "Please enter numeric values.", parent = sous)
                return
            if not 0 < borne_min < borne_max or nombre < 2:
                messagebox.showwarning("lambda.gcv", "Check 0 < lower bound < upper bound and a number of values >= 2.", parent = sous)
                return
            grille_lambda.update(lambda_min = borne_min, lambda_max = borne_max, lambda_n = nombre)
            resultat["ok"] = True
            sous.destroy()

        cadre_s = Frame(sous)
        cadre_s.grid(row = 6, column = 0, columnspan = 2, pady = 10)
        tk.Button(cadre_s, text = "OK", command = valider, width = 10).pack(side = LEFT, padx = 5)
        tk.Button(cadre_s, text = "Cancel", command = sous.destroy, width = 10).pack(side = LEFT, padx = 5)
        boite.wait_window(sous)
        if boite.winfo_exists():
            boite.grab_set()                          # capture rendue a la boite des parametres
        return resultat["ok"]

    def choisir_grille_lambda ():
        """ « lambda.gcv » cochee : saisie de la grille ; annulation = case decochee. """
        if champs["lambda_gcv"].get() and not dialogue_grille_lambda():
            champs["lambda_gcv"].set(False)

    ## --- donnees
    section(gauche, "Data")
    liste(gauche, "id", "Identifier", colonnes, 18)
    liste(gauche, "time", "Time", colonnes, 18)
    liste(gauche, "response", "Response", colonnes, 18)
    r = gauche.grid_size()[1]
    Label(gauche, text = "Covariates", font = ('arial', 12)).grid(row = r, column = 0, sticky = "nw", padx = (10, 6), pady = 1)
    zone_cov = Frame(gauche, bd = 1, relief = "sunken")
    zone_cov.grid(row = r, column = 1, sticky = "w", pady = 1)
    toile = Canvas(zone_cov, highlightthickness = 0, width = 190, height = 70)
    defil = ttk.Scrollbar(zone_cov, orient = "vertical", command = toile.yview)
    toile.configure(yscrollcommand = defil.set)
    toile.pack(side = LEFT, fill = BOTH, expand = True)
    defil.pack(side = LEFT, fill = "y")
    interieur = Frame(toile)
    toile.create_window((0, 0), window = interieur, anchor = "nw")
    interieur.bind("<Configure>", lambda event: toile.configure(scrollregion = toile.bbox("all")))
    cases_cov = {}
    for c in colonnes:
        cases_cov[c] = BooleanVar(value = c in p0["covariates"])
        Checkbutton(interieur, text = c, variable = cases_cov[c], font = ('arial', 11), anchor = "w").pack(fill = "x", anchor = "w")
    ## --- modele
    titre_model = section(gauche, "Model")
    entree(gauche, "K", "K (empty: automatic, min MSE)" if fkms else "K (empty: automatic)")
    entree(gauche, "K_max", "K_max")
    if fkms:
        entree(gauche, "N_bs", "N.bs (basis functions)")
        liste(gauche, "basis", "basis (B-spline / Fourier)", ["B", "F"])
        entree(gauche, "lambda", "lambda")
        case(gauche, "lambda_gcv", "lambda.gcv", commande = choisir_grille_lambda)
        case(gauche, "lambda_common", "lambda.common")
        liste(gauche, "cov_effect", "cov.effect", ["cluster", "common"])
        case(gauche, "conf_band", "conf.band")
        liste(gauche, "se_type", "se.type", ["sandwich", "model"])
    if not fkms:
        entree(gauche, "df", "df (B-spline functions)")
        entree(gauche, "degree", "degree")
        case(gauche, "penalty", "penalty")
        entree(gauche, "pen_order", "pen_order")
        liste(gauche, "re", "re (random effect)", ["linear", "intercept", "spline"])
        liste(gauche, "weights", "weights", ["constant", "covariates"])
        liste(gauche, "criterion", "criterion", ["BIC", "ICL"])
        entree(gauche, "min_size", "min_size")
        entree(gauche, "K0", "K0 (empty: automatic)")
        case(gauche, "standardize", "standardize (Min-Max)")
        ## --- algorithme
        section(droite, "Algorithm")
        entree(droite, "a_dir", "a_dir")
        entree(droite, "n_outer", "n_outer")
        entree(droite, "quick_cycles", "quick_cycles")
        entree(droite, "full_cycles", "full_cycles")
        entree(droite, "inner_cap", "inner_cap")
        entree(droite, "tol", "tol")
        entree(droite, "nstart", "nstart")
        entree(droite, "seed", "seed (empty: random)")
    else:
        section(droite, "Algorithm")
        entree(droite, "N_random", "N.random")
        entree(droite, "N_rep", "N.rep")
        entree(droite, "seed", "seed (empty: random)")
    ## --- graphique
    titre_plot = section(droite, "Plot")
    case(droite, "envelope", "envelope")
    entree(droite, "level", "level")
    case(droite, "show_data", "show_data")
    entree(droite, "max_subjects", "max_subjects")
    entree(droite, "xlab", "xlab", 20)
    entree(droite, "ylab", "ylab (empty: response)", 20)
    entree(droite, "main", "main", 20)
    case(droite, "legend", "legend (right column)")

    def lire ():
        """ Valeurs saisies, converties et controlees ; None si une valeur est invalide. """
        v = {cle: (w.get() if not isinstance(w, BooleanVar) else w.get()) for cle, w in champs.items()}
        v["covariates"] = [c for c in colonnes if cases_cov[c].get()]
        if fkms:
            v.update(grille_lambda)
        try:
            if fkms:
                entiers, reels, optionnels = ("K_max", "N_bs", "N_random", "N_rep", "max_subjects"), ("lambda", "level"), ("K", "seed")
            else:
                entiers = ("K_max", "df", "degree", "pen_order", "n_outer", "quick_cycles", "full_cycles",
                           "inner_cap", "nstart", "max_subjects")
                reels, optionnels = ("a_dir", "tol", "level", "min_size"), ("K", "K0", "seed")
            for cle in entiers:
                v[cle] = int(float(str(v[cle]).replace(",", ".")))
            for cle in reels:
                v[cle] = float(str(v[cle]).replace(",", "."))
            for cle in optionnels:
                v[cle] = "" if str(v[cle]).strip() == "" else int(float(str(v[cle]).replace(",", ".")))
        except ValueError:
            messagebox.showwarning(methode, "Please enter numeric values for the numeric parameters.", parent = boite)
            return None
        roles = [v["id"], v["time"], v["response"]]
        if len(set(roles)) < 3:
            messagebox.showwarning(methode, "Identifier, time and response must be three different columns.", parent = boite)
            return None
        if set(v["covariates"]) & set(roles):
            messagebox.showwarning(methode, "A covariate cannot be the identifier, the time or the response.", parent = boite)
            return None
        if fkms:
            if v["N_bs"] < (4 if v["basis"] == "B" else 3) or v["lambda"] < 0 or not 0 < v["level"] < 1 \
                    or v["N_random"] < 1 or v["N_rep"] < 1 or (v["K"] != "" and v["K"] < 1) or v["K_max"] < 1:
                messagebox.showwarning(methode, "Check N.bs >= 4 (B-spline) or >= 3 (Fourier), lambda >= 0, "
                                                "0 < level < 1, K >= 1, K_max >= 1, N.random >= 1 and N.rep >= 1.", parent = boite)
                return None
            return v
        if v["weights"] == "covariates" and not v["covariates"]:
            messagebox.showwarning("InfoMergeCluster", "weights = \"covariates\" requires at least one covariate.", parent = boite)
            return None
        if v["df"] < v["degree"] + 1 or not 1 <= v["pen_order"] <= v["degree"] or not 0 < v["level"] < 1:
            messagebox.showwarning("InfoMergeCluster", "Check df >= degree + 1, 1 <= pen_order <= degree and 0 < level < 1.", parent = boite)
            return None
        return v

    def sauver ():
        v = lire()
        if v is None:
            return
        ancien = parametres_infomerge.get(nom)
        for c, valeur in (ancien or {}).items():      # options du panneau des resultats (« All »...) conservees
            v.setdefault(c, valeur)
        parametres_infomerge[nom] = v                 # configuration enregistree (executee par « Run »)
        boite.destroy()
        rafraichir_boites()                           # K et etat « Configured » affiches dans la boite
        historique_valider("Configuration « " + nom + " »")
        ## parametres du modele modifies (K, K_max, criterion, colonnes...) : l'ancien
        ## resultat ne correspond plus a la configuration, il est abandonne ;
        ## seules les options du graphique modifiees : le resultat est retrace
        modele_change = ancien is None or any(ancien.get(c) != v.get(c) for c in v if c not in CLES_GRAPHIQUE_INFOMERGE)
        if modele_change:
            resultats_boites.pop(nom, None)
            traces_graphiques.pop(PREFIXE_RESULTATS + nom, None)
        elif nom in resultats_boites and nom in noms_affiches and panneau_graphique is not None \
                and panneau_graphique.winfo_exists() \
                and type_affiche["titre"] in (PREFIXE_RESULTATS + nom, PREFIXE_RESULTATS + TOUTES_ANALYSES):
            afficher_resultats_infomerge(list(noms_affiches), panneau_graphique)

    cadre_b = Frame(boite)
    cadre_b.grid(row = 3, column = 0, columnspan = 2, pady = 10)
    tk.Button(cadre_b, text = "Save", command = sauver, width = 10).pack(side = LEFT, padx = 5)
    tk.Button(cadre_b, text = "Cancel", command = boite.destroy, width = 10).pack(side = LEFT, padx = 5)

    ## --- hauteur initiale reduite, defilement et agrandissement a la souris
    boite.update_idletasks()
    ## zone des covariables agrandie : section « Model » au niveau de « Plot »
    if not fkms:
        ecart = titre_plot.winfo_y() - titre_model.winfo_y()
        if ecart > 0:
            toile.configure(height = int(toile.cget("height")) + ecart)
            boite.update_idletasks()
    else:
        ## FKMS : zone des covariables de meme hauteur que pour InfoMergeCluster
        ## (hauteur de la section « Algorithm » d'InfoMergeCluster, 8 parametres,
        ## mesuree sur un cadre non affiche), puis « Plot » descendu au niveau de « Model »
        mesure = Frame(contenu)
        Label(mesure, text = "Algorithm", font = ('arial', 13, 'bold')).grid(row = 0, column = 0, columnspan = 2, sticky = "w", pady = (8, 2))
        tk.Frame(mesure, height = 1).grid(row = 1, column = 0, columnspan = 2, sticky = "ew", pady = (0, 3))
        for k, texte in enumerate(("a_dir", "n_outer", "quick_cycles", "full_cycles", "inner_cap", "tol", "nstart", "seed (empty: random)")):
            Label(mesure, text = texte, font = ('arial', 12)).grid(row = 2 + k, column = 0, sticky = "w", padx = (10, 6), pady = 1)
            Entry(mesure, width = 10).grid(row = 2 + k, column = 1, sticky = "w", pady = 1)
        mesure.update_idletasks()
        y_plot_infomerge = mesure.winfo_reqheight() + 8      # position de « Plot » chez InfoMergeCluster
        mesure.destroy()
        ecart = y_plot_infomerge - titre_model.winfo_y()
        if ecart > 0:
            toile.configure(height = int(toile.cget("height")) + ecart)
            boite.update_idletasks()
        decalage = titre_model.winfo_y() - titre_plot.winfo_y()
        if decalage > 0:
            titre_plot.grid_configure(pady = (8 + decalage, 2))
            boite.update_idletasks()
    larg_contenu, haut_contenu = contenu.winfo_reqwidth(), contenu.winfo_reqheight()
    haut_hote = max(panneau_courant.winfo_height(), 400)
    haut_max = lambda: max(150, min(haut_contenu, panneau_courant.winfo_height() - 140))
    toile_param.configure(width = larg_contenu, height = min(haut_contenu, max(250, int(0.5 * haut_hote))),
                          scrollregion = (0, 0, larg_contenu, haut_contenu))
    molette = lambda event: toile_param.yview_scroll(-1 * (event.delta if abs(event.delta) < 10 else event.delta // 120), "units")
    cadre_defil.bind("<Enter>", lambda event: toile_param.bind_all("<MouseWheel>", molette))
    cadre_defil.bind("<Leave>", lambda event: toile_param.unbind_all("<MouseWheel>"))
    boite.bind("<Destroy>", lambda event: toile_param.unbind_all("<MouseWheel>") if event.widget is boite else None, add = "+")
    ## poignee (canevas : non concernee par le deplacement de la boite)
    poignee = Canvas(boite, width = 14, height = 14, highlightthickness = 0, cursor = "sb_v_double_arrow")
    for k in (4, 8, 12):
        poignee.create_line(14, 14 - k, 14 - k, 14, fill = "gray50")
    poignee.place(relx = 1.0, rely = 1.0, anchor = "se", x = -2, y = -2)
    depart = {}

    def saisir_poignee (event):
        depart.update(y = event.y_root, h = toile_param.winfo_height())

    def tirer_poignee (event):
        if depart:
            h = min(max(120, depart["h"] + event.y_root - depart["y"]), haut_max())
            toile_param.configure(height = h)

    poignee.bind("<ButtonPress-1>", saisir_poignee)
    poignee.bind("<B1-Motion>", tirer_poignee)


class ArretDemande (ArretDemandeAlgorithme):
    """ Interruption d'une analyse par le bouton d'arret. """


TEXTE_ARRET = "stopped by the user"


def executer_infomerge (nom, zone_resultats, apres = None):
    """ Lance infomergecluster() dans un fil d'execution separe (l'interface
    reste utilisable) ; la progression et le resultat s'affichent dans la
    zone de resultats de la boite de dialogue « Settings ». """
    import threading
    methode = methodes_boites.get(nom, "InfoMergeCluster")
    v = dict(defauts_boite(nom))
    v.update(parametres_infomerge[nom])
    donnees = appliquer_filtres(data_analy)
    tableau = donnees[[v["id"], v["time"], v["response"]] + v["covariates"]]
    ## InfoMergeCluster et FKMS : une covariable est un facteur si elle est de
    ## type texte, booleen ou categorie ; les variables declarees qualitatives
    ## (« Categorizing variables ») sont donc passees en texte, meme codees par
    ## des nombres (indicatrices, reference = modalite la plus frequente)
    categorisees = [c for c in v["covariates"] if c in colonnes_categorielles]
    if categorisees:
        tableau = tableau.copy()
        for c in categorisees:
            tableau[c] = tableau[c].map(lambda val: val if pd.isna(val) else cle_modalite(val)).astype("object")
    etat = {"messages": ["Running " + methode + "..."], "resultat": None, "erreur": None, "fini": False, "arret": False}
    calculs_en_cours[nom] = etat

    def journal (message):
        ## messages de progression ; bouton d'arret : interruption a l'etape suivante
        if etat["arret"]:
            raise ArretDemande(TEXTE_ARRET)
        etat["messages"].append(message)

    def arret_fkms ():
        if etat["arret"]:
            raise ArretDemande(TEXTE_ARRET)

    def calcul_fkms ():
        ## FKMS : K fixe, ou K choisi par le MSE minimal (k = 1, ..., K_max)
        arguments = dict(N_bs = v["N_bs"], N_random = v["N_random"], N_rep = v["N_rep"], basis = v["basis"],
                         lam = v["lambda"], N_cov = len(v["covariates"]), lambda_gcv = v["lambda_gcv"],
                         lambda_common = v["lambda_common"], cov_effect = v["cov_effect"], conf_band = v["conf_band"],
                         lambda_grid = np.logspace(math.log10(v["lambda_min"]), math.log10(v["lambda_max"]), int(v["lambda_n"])),
                         conf_level = v["level"], se_type = v["se_type"],
                         seed = None if v["seed"] == "" else v["seed"], cov_labels = v["covariates"] or None,
                         log = journal, arret = arret_fkms)
        if v["K"] == "":
            return fkms_selection_k(tableau, K_max = v["K_max"], verbose = True, **arguments)
        return fkms_covariables_lambda_gcv(tableau, N_clust = v["K"], verbose = True, **arguments)

    def calcul ():
        try:
            if methode == "FKMS":
                etat["resultat"] = calcul_fkms()
            else:
                etat["resultat"] = infomergecluster(
                    tableau, K_max = v["K_max"], K = None if v["K"] == "" else v["K"], df = v["df"], degree = v["degree"],
                    penalty = v["penalty"], pen_order = v["pen_order"], re = v["re"], n_cov = len(v["covariates"]),
                    weights = v["weights"], min_size = v["min_size"], K0 = None if v["K0"] == "" else v["K0"],
                    criterion = v["criterion"], a_dir = v["a_dir"], n_outer = v["n_outer"],
                    quick_cycles = v["quick_cycles"], full_cycles = v["full_cycles"], inner_cap = v["inner_cap"],
                    tol = v["tol"], nstart = v["nstart"], seed = None if v["seed"] == "" else v["seed"],
                    verbose = True, log = journal, cov_labels = v["covariates"] or None,
                    standardize = bool(v.get("standardize", True)))
        except Exception as erreur:
            etat["erreur"] = TEXTE_ARRET if etat["arret"] else str(erreur)
        if etat["arret"]:
            etat["resultat"], etat["erreur"] = None, TEXTE_ARRET   # resultat d'une analyse arretee abandonne
        etat["fini"] = True

    etat["apres"] = apres                         # fonction appelee a la fin (file d'execution de « Run »)
    threading.Thread(target = calcul, daemon = True).start()
    suivre_infomerge(nom, zone_resultats)


def suivre_infomerge (nom, zone_resultats):
    """ Suivi du calcul (toutes les 200 ms) : derniers messages, puis resultat. """
    etat = calculs_en_cours.get(nom)
    if etat is None:
        return
    visible = zone_resultats is not None and zone_resultats.winfo_exists()
    if not etat["fini"]:
        if visible:
            afficher_progression(zone_resultats, etat["messages"])
        SmartDigicat.after(200, lambda: suivre_infomerge(nom, zone_resultats if visible else None))
        return
    del calculs_en_cours[nom]
    if etat["erreur"] is not None:
        rafraichir_boites()
        if etat.get("apres") is None:
            methode = methodes_boites.get(nom, "InfoMergeCluster")
            messagebox.showerror(methode, methode + " failed:\n" + etat["erreur"])
        if visible:
            afficher_progression(zone_resultats, etat["messages"] + ["Error: " + etat["erreur"]])
    else:
        resultats_boites[nom] = etat["resultat"]
        rafraichir_boites()                           # etat « Executed »
        if visible:
            afficher_resultats_infomerge(nom, zone_resultats)
    if etat.get("apres") is not None:
        etat["apres"](etat["erreur"])                 # analyse suivante de la file


##------ Zone defilante du panneau des options (a droite) --------------------
_zones_defilantes = []             # toiles des zones defilantes (molette)


def _molette_zones (event):
    """ Molette : fait defiler la zone defilante situee sous la souris (les
    autres widgets, dont le graphique et son zoom, ne sont pas concernes). """
    _zones_defilantes[:] = [t for t in _zones_defilantes if t.winfo_exists()]
    try:
        sous = SmartDigicat.winfo_containing(event.x_root, event.y_root)   # widget sous la souris
    except (KeyError, tk.TclError, AttributeError):
        return
    if sous is None:
        return
    nom = str(sous)
    for toile in _zones_defilantes:
        zone = getattr(toile, "zone_nom", str(toile))          # toile et sa barre de defilement
        if (nom == zone or nom.startswith(zone + ".")) and getattr(toile, "defilement_actif", False):
            if getattr(event, "num", None) in (4, 5):
                pas = -1 if event.num == 4 else 1
            elif sys.platform == "darwin":
                pas = -event.delta
            else:
                pas = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            toile.yview_scroll(pas, "units")
            return


def _activer_molette_zones (event = None):
    """ (Re)branche la molette sur les zones defilantes : d'autres zones du
    logiciel (graphique, listes) la rebranchent sur elles a l'entree de la
    souris et la debranchent a sa sortie. """
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        SmartDigicat.bind_all(sequence, _molette_zones)


def _armer_molette (widget):
    """ Entree de la souris sur la zone ou l'un de ses elements : molette
    rebranchee sur la zone defilante (une seule fois par widget). """
    try:
        if not getattr(widget, "_molette_armee", False):
            widget.bind("<Enter>", _activer_molette_zones, add = "+")
            widget._molette_armee = True
        for enfant in widget.winfo_children():
            _armer_molette(enfant)
    except tk.TclError:
        pass


def zone_defilante_options (panneau, hauteur_bas = 72):
    """ Panneau des options (20 % a droite du panneau central) : contenu dans
    une zone defilante verticale ; la barre de defilement n'apparait que si le
    contenu depasse la hauteur disponible. En bas, une bande fixe (boutons
    « Refresh » et « Save plot ») reste toujours visible.
    Renvoie (interieur, bas) : cadre ou placer les options et bande du bas. """
    exterieur = Frame(panneau, background = "gray90")
    exterieur.place(relx = 0.8, rely = 0, relwidth = 0.2, relheight = 1)
    bas = Frame(exterieur, background = "gray90", height = hauteur_bas)
    bas.pack(side = "bottom", fill = "x")
    bas.pack_propagate(False)
    zone = Frame(exterieur, background = "gray90")
    zone.pack(side = "top", fill = BOTH, expand = True)
    toile = Canvas(zone, background = "gray90", highlightthickness = 0, bd = 0, yscrollincrement = 20)
    defil = ttk.Scrollbar(zone, orient = "vertical", command = toile.yview)
    toile.configure(yscrollcommand = defil.set)
    toile.pack(side = LEFT, fill = BOTH, expand = True)
    interieur = Frame(toile, background = "gray90")
    fenetre = toile.create_window(0, 0, window = interieur, anchor = "nw")
    toile.defilement_actif = False
    toile.zone_nom = str(zone)

    def maj (event = None):
        _armer_molette(zone)                       # elements ajoutes ou affiches depuis
        hauteur = interieur.winfo_reqheight()
        toile.configure(scrollregion = (0, 0, max(1, toile.winfo_width()), hauteur))
        trop = hauteur > toile.winfo_height() + 1
        if trop and not toile.defilement_actif:
            defil.pack(side = "right", fill = "y", before = toile)
            toile.defilement_actif = True
        elif not trop and toile.defilement_actif:
            defil.pack_forget()
            toile.defilement_actif = False
            toile.yview_moveto(0)

    def largeur (event):
        toile.itemconfigure(fenetre, width = event.width)    # options a la largeur du panneau
        maj()

    interieur.bind("<Configure>", maj)
    toile.bind("<Configure>", largeur)
    _zones_defilantes.append(toile)
    _armer_molette(zone)
    _activer_molette_zones()
    return interieur, bas


def panneau_resultats_infomerge (parent, nom):
    """ Panneau central des resultats de InfoMergeCluster pour la boite nom,
    sur le principe du bouton « Plots » : 80 % a gauche pour le graphique
    (zone defilante, deux colonnes : graphique et legende des classes, zoom,
    deplacement, double clic), 20 % a droite pour les options (polices des
    titres, des axes et des legendes) et les boutons « Refresh » et
    « Save plot ». Renvoie la zone du graphique. """
    global panneau_graphique, panneau_options_graphique, statut_graphique, figure_graphique
    rappel_selection["fonction"] = None
    panneau = nouveau_panneau(parent)
    figure_graphique = None
    type_affiche["titre"] = None
    panneau_graphique = Frame(panneau, background = "white")
    panneau_graphique.place(relx = 0, rely = 0, relwidth = 0.8, relheight = 1)
    ## options dans une zone defilante (barre affichee si elles depassent la
    ## hauteur du panneau) ; « Refresh » et « Save plot » fixes en bas
    panneau_options_graphique, bande_boutons = zone_defilante_options(panneau)
    panneau_options_graphique.grid_columnconfigure(0, weight = 1)
    Label(panneau_options_graphique, text = "Summary", font = ('arial', 14, 'bold'), fg = "saddlebrown",
          background = "gray90", anchor = "w").grid(row = 0, column = 0, sticky = "ew", padx = 8, pady = (10, 0))
    executees = analyses_executees()
    initiales = executees if nom == TOUTES_ANALYSES else ([nom] if nom in executees else [])
    cadre_choix_analyses(panneau_options_graphique, 1, executees, initiales)
    blocs = [(cle, titre) for cle, titre in BLOCS_POLICE if cle in ("titre", "axes", "legende")]
    for k, (cle, titre) in enumerate(blocs):
        bloc_police(panneau_options_graphique, 2 + k, cle, titre, couleur_titre = "saddlebrown")   # couleur de « Summary »
    ## « Export data » sous « Comparisons » (ligne 4 + len(blocs))
    cadre_stat_options(panneau_options_graphique, 2 + len(blocs), nom, ligne_export = 4 + len(blocs))
    ## « Comparisons » : affiche seulement s'il existe des boites de comparaison ;
    ## cochee, les resultats des comparaisons (ARI, Jaccard) s'affichent dans une boite
    fenetre_comparaisons.update(widget = None, case = None)
    if comparaisons:
        var_comparaisons = BooleanVar(value = False)
        fenetre_comparaisons["case"] = var_comparaisons

        def basculer_comparaisons ():
            if var_comparaisons.get():
                afficher_resultats_comparaisons(panneau)
            else:
                fermer_resultats_comparaisons()

        Checkbutton(panneau_options_graphique, text = "Comparisons", variable = var_comparaisons, command = basculer_comparaisons,
                    font = ('arial', 14), fg = "gray30", background = "gray90", activebackground = "gray90",
                    highlightthickness = 0, anchor = "w").grid(row = 3 + len(blocs), column = 0, sticky = "ew", padx = 8, pady = (8, 0))
    statut_graphique = Label(panneau_options_graphique, text = "", font = ('arial', 11), fg = "saddlebrown",
                             background = "gray90", justify = "left", anchor = "w", wraplength = 200)
    statut_graphique.grid(row = 5 + len(blocs), column = 0, sticky = "ew", padx = 8, pady = (12, 12))
    style_bouton = dict(font = ('arial', 13), compound = tk.TOP, borderwidth = 0, relief = FLAT, borderless = True,
                        bordercolor = "gray90", background = "gray90", focuscolor = "gray90", highlightcolor = "gray90",
                        highlightbackground = "gray90")
    Button(bande_boutons, image = rafraichir_graph, text = "Refresh", command = rafraichir_graphique,
           **style_bouton).place(relx = 0.27, rely = 1.0, y = -6, anchor = "s", width = 95, height = 60)
    Button(bande_boutons, image = save_graph_p, text = "Save plot", command = sauver_graphiques,
           **style_bouton).place(relx = 0.73, rely = 1.0, y = -6, anchor = "s", width = 95, height = 60)
    if initiales:
        afficher_resultats_infomerge(initiales, panneau_graphique)
    elif nom not in calculs_en_cours:
        afficher_progression(panneau_graphique, ["No result for the current configuration.",
                                                 "Click on « Run » (top bar) to run InfoMergeCluster."])
    return panneau_graphique


##------ Resultats des boites de comparaison (ARI, Jaccard) -------------------
def _paires_contingence (a, b):
    """ Comptes de paires a partir de deux partitions (memes sujets) :
    n11 = paires ensemble dans les deux, n10 = ensemble dans a seulement,
    n01 = ensemble dans b seulement, total = nombre de paires. """
    tab = pd.crosstab(np.asarray(a), np.asarray(b)).to_numpy(dtype = float)
    c2 = lambda x: x * (x - 1) / 2
    n = tab.sum()
    somme_ij = c2(tab).sum()
    somme_a = c2(tab.sum(axis = 1)).sum()
    somme_b = c2(tab.sum(axis = 0)).sum()
    return somme_ij, somme_a, somme_b, c2(n)


def indice_ari (a, b):
    """ Indice de Rand ajuste (Hubert et Arabie) entre deux partitions. """
    somme_ij, somme_a, somme_b, total = _paires_contingence(a, b)
    if total == 0:
        return float("nan")
    attendu = somme_a * somme_b / total
    maximum = (somme_a + somme_b) / 2
    return 1.0 if maximum == attendu else float((somme_ij - attendu) / (maximum - attendu))


def indice_jaccard (a, b):
    """ Indice de Jaccard sur les paires : paires regroupees dans les deux
    partitions / paires regroupees dans au moins une des deux. """
    somme_ij, somme_a, somme_b, total = _paires_contingence(a, b)
    union = somme_a + somme_b - somme_ij
    return 1.0 if union == 0 else float(somme_ij / union)


def resultats_comparaisons ():
    """ Pour chaque boite de comparaison : indices entre chaque paire de modeles
    executes, calcules sur les sujets classes par les deux modeles. Renvoie une
    liste (comparaison, lignes) ; une ligne = dict (Model 1, Model 2, N, ARI,
    Jaccard) ou un message. """
    from itertools import combinations
    sortie = []
    for c in comparaisons:
        indices = indices_comparaison.get(c) or list(INDICES_DEFAUT)
        modeles = [m for m in modeles_comparaison.get(c, []) if m in analyses]
        executes = [m for m in modeles if m in resultats_boites and m not in calculs_en_cours]
        lignes = []
        non_executes = [m for m in modeles if m not in executes]
        if len(executes) < 2:
            lignes.append({"message": "Fewer than two executed models: add models and click on « Run »."})
        for m1, m2 in combinations(executes, 2):
            p1, p2 = resultats_boites[m1].cluster, resultats_boites[m2].cluster
            communs = p1.index.intersection(p2.index)
            ligne = {"Model 1": m1, "Model 2": m2, "N": len(communs), "ARI": None, "Jaccard": None}
            if len(communs) >= 2:
                a, b = p1.loc[communs].to_numpy(), p2.loc[communs].to_numpy()
                if "ARI" in indices:
                    ligne["ARI"] = indice_ari(a, b)
                if "Jaccard" in indices:
                    ligne["Jaccard"] = indice_jaccard(a, b)
            lignes.append(ligne)
        if non_executes:
            lignes.append({"message": "Not executed (ignored): " + ", ".join(non_executes)})
        sortie.append((c, indices, lignes))
    return sortie


fenetre_comparaisons = {"widget": None, "case": None}


def fermer_resultats_comparaisons ():
    widget = fenetre_comparaisons["widget"]
    if widget is not None and widget.winfo_exists():
        widget.destroy()
    fenetre_comparaisons["widget"] = None
    if fenetre_comparaisons["case"] is not None:
        try:
            fenetre_comparaisons["case"].set(False)
        except tk.TclError:
            pass


def afficher_resultats_comparaisons (hote):
    """ Boite (non modale, deplacable) des resultats des boites de comparaison :
    une section par comparaison, une ligne par paire de modeles. """
    fermer_widget = fenetre_comparaisons["widget"]
    if fermer_widget is not None and fermer_widget.winfo_exists():
        fermer_widget.destroy()
    boite = Frame(hote, bd = 2, relief = "ridge")
    boite.place(relx = 0.4, rely = 0.5, anchor = "center")
    boite.after_idle(lambda: rendre_deplacable(boite))
    boite.lift()
    fenetre_comparaisons["widget"] = boite
    Label(boite, text = "Comparison results", font = ('arial', 15, 'bold'), fg = "saddlebrown").pack(anchor = "w", padx = 15, pady = (10, 0))
    Label(boite, text = "Indices computed on the subjects classified by both models (1 = identical partitions)",
          **AIDE_BOITE).pack(anchor = "w", padx = 15, pady = (0, 6))
    cadre = Frame(boite)
    cadre.pack(fill = BOTH, expand = True, padx = 15)
    colonnes = ("Model 2", "N", "ARI", "Jaccard")
    style = ttk.Style()
    style.configure("Stat.Treeview", font = ('arial', 12), rowheight = 26, background = "white", fieldbackground = "white", foreground = "gray15")
    style.configure("Stat.Treeview.Heading", font = ('arial', 12, 'bold'), foreground = "gray15")
    arbre = ttk.Treeview(cadre, columns = colonnes, show = "tree headings", height = 12, style = "Stat.Treeview")
    defil = ttk.Scrollbar(cadre, orient = "vertical", command = arbre.yview)
    arbre.configure(yscrollcommand = defil.set)
    arbre.heading("#0", text = traduire("Comparison / Model 1"), anchor = "w")
    arbre.column("#0", width = 260, anchor = "w")
    for col, largeur in zip(colonnes, (220, 60, 80, 80)):
        arbre.heading(col, text = traduire(col), anchor = "center")
        arbre.column(col, width = largeur, anchor = "w" if col == "Model 2" else "center")
    arbre.tag_configure("groupe", background = "#e2ebf4", font = ('arial', 12, 'bold'))
    arbre.tag_configure("message", foreground = "gray45")
    arbre.pack(side = LEFT, fill = BOTH, expand = True)
    defil.pack(side = LEFT, fill = "y")
    tableau = []
    valeur = lambda v: "—" if v is None else ("NA" if not np.isfinite(v) else "%.3f" % v)
    for c, indices, lignes in resultats_comparaisons():
        parent = arbre.insert("", "end", text = c + "   (" + " · ".join(indices) + ")", open = True, tags = ("groupe",))
        for ligne in lignes:
            if "message" in ligne:
                arbre.insert(parent, "end", text = traduire(ligne["message"]), tags = ("message",))
                continue
            libelle = lambda m: libelle_analyse(m, analyses) + " (K = " + str(int(resultats_boites[m].K)) + ")"
            arbre.insert(parent, "end", text = libelle(ligne["Model 1"]),
                         values = (libelle(ligne["Model 2"]), ligne["N"], valeur(ligne["ARI"]), valeur(ligne["Jaccard"])))
            tableau.append({"Comparison": c, "Model 1": ligne["Model 1"], "Model 2": ligne["Model 2"], "N": ligne["N"],
                            "ARI": ligne["ARI"], "Jaccard": ligne["Jaccard"]})

    def exporter ():
        if not tableau:
            messagebox.showinfo("Comparison results", "No index to export: each comparison needs at least two executed models.", parent = boite)
            return
        chemin = filedialog.asksaveasfilename(defaultextension = ".csv", filetypes = [("CSV file", "*.csv")],
                                              initialfile = "comparisons.csv", title = "Export the comparison results")
        if not chemin:
            return
        try:
            pd.DataFrame(tableau).to_csv(chemin, sep = ";", index = False, encoding = "utf-8-sig")
        except Exception as erreur:
            messagebox.showerror("Comparison results", "The export failed:\n" + str(erreur), parent = boite)
            return
        messagebox.showinfo("Comparison results", "Results exported to:\n" + chemin, parent = boite)

    boutons = Frame(boite)
    boutons.pack(pady = 10)
    tk.Button(boutons, text = "Export CSV", command = exporter, width = 11).pack(side = LEFT, padx = 4)
    tk.Button(boutons, text = "Close", command = fermer_resultats_comparaisons, width = 8).pack(side = LEFT, padx = 4)


def afficher_progression (zone, messages):
    for w in zone.winfo_children():
        w.destroy()
    Label(zone, text = "\n".join(messages[-8:]), font = ('Courier', 11), fg = "gray20", background = "white",
          justify = "left", anchor = "nw").pack(fill = BOTH, expand = True, padx = 10, pady = 10)


def trace_infomerge (figure, donnees, variables):
    """ Trace des resultats de InfoMergeCluster, meme interface que les autres
    fonctions de trace (variables : boite -> parametres) : une ligne par
    boite, plot_infomergecluster a gauche et legende des classes a droite.
    plot_infomergecluster recoit directement la sortie de infomergecluster
    (v["resultat"]) ; les donnees ne servent pas. """
    grille = figure.add_gridspec(len(variables), 2, width_ratios = [4, 1.3])
    for k, (nom, v) in enumerate(variables.items()):
        x = v["resultat"]                                     # sortie de infomergecluster()
        ax = figure.add_subplot(grille[k, 0])
        ax.analyse = nom                                      # analyse tracee (options propres a chaque courbe)
        ax_leg = figure.add_subplot(grille[k, 1])
        ax_leg.axis("off")
        tn = len(x.ids) if v.get("all_subjects") else v["max_subjects"]      # « All » ou nombre TN de trajectoires
        tracer = plot_data_cluster if getattr(x, "method", None) == "FKMS" else plot_infomergecluster
        if v.get("main") in ("fkms : K = %d (MSE = %.3g)", "FKMS : K = %d (MSE = %.3g)"):   # anciennes valeurs par defaut
            v["main"] = PARAMETRES_FKMS_DEFAUT["main"]
        tracer(ax, x, max_subjects = tn, envelope = v["envelope"],
                              xlab = v["xlab"], ylab = v["ylab"] or v["response"],
                              main = v["main"], level = v["level"], show_data = v["show_data"], legend = False,
                              data_type = "regressed" if v.get("regressed") else "raw")
        ## titre du graphique : nom associe a la boite (ex. « Poids-MI : no-cov »)
        regresse = v.get("regressed") and getattr(x, "gamma", None) is not None
        ax.set_title(titre_boite(nom) + ("  —  regressed on covariates" if regresse else ""))
        style_graphique_r(ax)
        if v["legend"]:
            poignees, libelles = ax.get_legend_handles_labels()      # trajectoires moyennes « Ck (proportion) »
            ## niveau de confiance de l'enveloppe, toujours indique : « CE : 95% »
            titre = "Classes\nCE : %g%%" % (100 * v["level"])
            legende = ax_leg.legend(poignees, libelles, title = titre, loc = "center left", borderaxespad = 0,
                                    frameon = False, prop = {"weight": "bold", "size": 10}, title_fontsize = 11)
            legende.get_title().set_fontweight("bold")
            legende._legend_box.align = "left"
            ## legende interactive : un clic sur une classe n'affiche que ses
            ## trajectoires (individuelles, moyenne, enveloppe) ; un second clic
            ## sur la meme classe ou un double clic sur le graphique les reaffiche toutes
            poignees_leg = getattr(legende, "legend_handles", None) or getattr(legende, "legendHandles", [])
            legende.modalites = {}
            for k, (poignee, texte) in enumerate(zip(poignees_leg, legende.get_texts())):
                for artiste in (poignee, texte):
                    artiste.set_picker(True)
                    legende.modalites[artiste] = k
            legende.ax_cible = ax
            legende.modalite_seule = None
    return []


def afficher_resultats_infomerge (nom, zone):
    """ Resultat de infomergecluster() affiche comme les graphiques de
    « Plots » : enregistre parmi les graphiques construits (« Save plot »)
    puis trace dans le panneau des graphiques. """
    if zone is not panneau_graphique or not zone.winfo_exists():
        return
    executees = analyses_executees()
    if isinstance(nom, (list, tuple)):
        noms = [n for n in executees if n in nom]            # ordre des boites
    else:
        noms = executees if nom == TOUTES_ANALYSES else [n for n in [nom] if n in executees]
    noms_affiches[:] = noms
    if not noms:
        traces_graphiques.pop(PREFIXE_RESULTATS + TOUTES_ANALYSES, None)
        effacer_figure()
        afficher_progression(zone, ["No analysis selected.", "Check the analyses to display (Summary)."])
        return
    nom = noms[0] if len(noms) == 1 else TOUTES_ANALYSES
    variables = {}
    for n in noms:                                            # une ligne de graphique par analyse
        v = dict(defauts_boite(n))
        v.update(parametres_infomerge.get(n, {}))
        v["resultat"] = resultats_boites[n]                   # sortie de infomergecluster() transmise au trace
        variables[n] = v
    ## un meme graphique n'apparait qu'une fois dans « Save plot »
    if nom == TOUTES_ANALYSES:
        for n in noms:
            traces_graphiques.pop(PREFIXE_RESULTATS + n, None)
    else:
        traces_graphiques.pop(PREFIXE_RESULTATS + TOUTES_ANALYSES, None)
    titre = PREFIXE_RESULTATS + nom
    traces_graphiques[titre] = {"tracer": trace_infomerge, "variables": variables}
    afficher_type(titre)


TOUTES_ANALYSES = "All analyses"
noms_affiches = []                 # analyses affichees dans le panneau des resultats


def libelle_analyse (nom, noms):
    """ Libelle d'une analyse : « methode : variable analysee », complete du
    nom de la boite si plusieurs analyses ont le meme libelle. """
    base = lambda n: (methodes_boites.get(n) or "InfoMergeCluster") + " : " + \
        str(parametres_infomerge.get(n, {}).get("response", "") or n)
    libelle = base(nom)
    if sum(base(n) == libelle for n in noms) > 1:
        libelle += " (" + nom + ")"
    return libelle


def cadre_choix_analyses (parent, ligne, executees, initiales):
    """ Sous « Summary » : liste deroulante de cases a cocher (Checkbutton).
    - « All analyses » (cochee par defaut) : toutes les analyses affichees ;
    - cocher une analyse : seule sa courbe est affichee (« All analyses » est
      decochee) ; cocher d'autres analyses les ajoute a l'affichage ;
    - decocher la derniere analyse, ou cocher « All analyses » : retour a
      l'affichage de toutes les analyses.
    La liste reste ouverte pendant la selection et se ferme quand la souris
    la quitte ou par un nouveau clic sur le bouton. """
    cadre = Frame(parent, background = "gray90")
    cadre.grid(row = ligne, column = 0, sticky = "ew", padx = 8, pady = (4, 0))
    tout = not executees or len(initiales) == len(executees)
    var_toutes = BooleanVar(value = tout)
    cases = {n: BooleanVar(value = (not tout) and n in initiales) for n in executees}
    libelles = {n: libelle_analyse(n, executees) for n in executees}
    bouton = ttk.Button(cadre, width = 26)
    bouton.pack(side = LEFT, fill = "x", expand = True)
    ouverte = {"liste": None}

    def resumer ():
        choisies = [n for n in executees if cases[n].get()]
        if not executees:
            texte = "No analysis executed"
        elif var_toutes.get():
            texte = TOUTES_ANALYSES
        elif len(choisies) == 1:
            texte = libelles[choisies[0]]
        else:
            texte = str(len(choisies)) + " analyses selected"
        bouton.configure(text = traduire(texte) + "  ▾")

    def afficher ():
        resumer()
        noms = executees if var_toutes.get() else [n for n in executees if cases[n].get()]
        afficher_resultats_infomerge(noms, panneau_graphique)

    def basculer_toutes ():
        var_toutes.set(True)                       # « All analyses » : tout afficher
        for n in executees:
            cases[n].set(False)
        afficher()

    def basculer_une ():
        choisies = [n for n in executees if cases[n].get()]
        var_toutes.set(len(choisies) == 0)         # plus aucune analyse cochee : retour a « All »
        afficher()

    def fermer ():
        if ouverte["liste"] is not None and ouverte["liste"].winfo_exists():
            ouverte["liste"].destroy()
        ouverte["liste"] = None

    def verifier_sortie ():
        liste = ouverte["liste"]
        if liste is None or not liste.winfo_exists():
            return
        sous = liste.winfo_containing(*liste.winfo_pointerxy())
        while sous is not None and sous is not liste and sous is not bouton:
            sous = sous.master
        if sous is None:
            fermer()

    def ouvrir ():
        if ouverte["liste"] is not None:
            fermer()
            return
        hote = panneau_courant
        liste = Frame(hote, bd = 1, relief = "solid", background = "white")
        style = dict(background = "white", activebackground = "#E8EEF6", highlightthickness = 0, anchor = "w", fg = "gray20")
        Checkbutton(liste, text = TOUTES_ANALYSES, variable = var_toutes, command = basculer_toutes,
                    font = ('arial', 13, 'bold'), **style).pack(fill = "x", padx = 6, pady = (4, 2))
        if executees:
            tk.Frame(liste, height = 1, background = "gray75").pack(fill = "x", padx = 4, pady = 2)
        for n in executees:
            Checkbutton(liste, text = libelles[n], variable = cases[n], command = basculer_une,
                        font = ('arial', 13), **style).pack(fill = "x", padx = (6, 10), pady = 1)
        liste.update_idletasks()
        ## sous le bouton, alignee sur son bord droit si elle est plus large
        x_droite = bouton.winfo_rootx() + bouton.winfo_width() - hote.winfo_rootx()
        largeur = max(liste.winfo_reqwidth(), bouton.winfo_width())
        x = max(0, x_droite - largeur)
        y = bouton.winfo_rooty() + bouton.winfo_height() - hote.winfo_rooty()
        liste.place(x = x, y = y, width = largeur)
        liste.lift()
        liste.bind("<Leave>", lambda event: liste.after(150, verifier_sortie))
        ouverte["liste"] = liste

    bouton.configure(command = ouvrir)
    cadre.bind("<Destroy>", lambda event: fermer() if event.widget is cadre else None)
    resumer()
    return cadre


def analyses_executees ():
    """ Analyses ayant un resultat, dans l'ordre de creation des boites. """
    return [n for n in analyses if n in resultats_boites and n not in calculs_en_cours]


def afficher_log (parent):
    """ Bouton « Log » : resultats des analyses executees (toutes si
    plusieurs, avec le choix d'une seule dans le panneau de droite). """
    executees = analyses_executees()
    if not executees:
        panneau = nouveau_panneau(parent)
        Label(panneau, text = "No result yet.\nConfigure the analyses, then click on « Run ».",
              font = ('Helvetica 16 bold italic'), fg = "gray40", background = "white").place(relx = 0, rely = 0, relwidth = 1, relheight = 1)
        return
    panneau_resultats_infomerge(parent, TOUTES_ANALYSES if len(executees) > 1 else executees[0])


##-----------------------------------------------------------------------------
##  « Export data » : donnees du graphique d'un modele en CSV
##-----------------------------------------------------------------------------
def tableaux_export_modele (nom):
    """ Donnees du graphique du modele nom, telles qu'elles sont tracees
    (donnees brutes ou regressees selon « Regressed data ») :
    - courbes : courbes moyennes des classes et leurs enveloppes (niveau de la
      configuration), une ligne par classe et par temps ; colonnes Class,
      Time, Mean, Lower, Upper ;
    - trajectoires : mesures individuelles de tous les sujets ; colonnes ID,
      Time, Value, Class (None si le modele n'a pas garde les donnees).
    Class : numero de la classe (1 pour C1, 2 pour C2...). """
    x = resultats_boites[nom]
    v = dict(defauts_boite(nom))
    v.update(parametres_infomerge.get(nom, {}))
    fkms = getattr(x, "method", None) == "FKMS"
    regressees = bool(v.get("regressed")) and getattr(x, "gamma", None) is not None
    niveau = float(v.get("level", 0.95))
    classes = list(x.beta.columns)
    ## courbes moyennes et enveloppes
    predire = predict_fkms if fkms else predict_infomergecluster
    mc = predire(x, interval = "confidence", level = niveau, type = "regressed" if regressees else "raw")
    blocs = []
    for k, lab in enumerate(classes):
        blocs.append(pd.DataFrame({"Class": k + 1, "Time": mc["time"].to_numpy(float), "Mean": mc[lab].to_numpy(float),
                                   "Lower": mc[lab + "_lwr"].to_numpy(float) if lab + "_lwr" in mc else np.nan,
                                   "Upper": mc[lab + "_upr"].to_numpy(float) if lab + "_upr" in mc else np.nan}))
    courbes = pd.concat(blocs, ignore_index = True)          # colonnes : Class, Time, Mean, Lower, Upper
    ## trajectoires individuelles
    trajectoires = None
    if getattr(x, "data", None) is not None:
        if fkms:
            d = donnees_regressees_fkms(x) if regressees else x.data
            k = d["cluster"].to_numpy(int) - 1
        else:
            d = donnees_regressees(x) if regressees else x.data
            k = d["id"].astype(str).map(x.cluster).to_numpy(int) - 1
        trajectoires = pd.DataFrame({"ID": d["id"].to_numpy(), "Time": d["t"].to_numpy(float),
                                     "Value": d["y_reg" if regressees else "y"].to_numpy(float),
                                     "Class": (k + 1).astype(int)})          # classe en entier : 1 pour C1
        trajectoires = trajectoires.sort_values(["Class", "ID", "Time"], kind = "stable", ignore_index = True)
    return courbes, trajectoires


def _nom_fichier_export (nom):
    """ Nom de fichier propose : nom de la boite sans caracteres interdits. """
    base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in str(nom)).strip() or "model"
    return base.replace(" ", "_")


def exporter_donnees_modele (nom, quoi):
    """ Export CSV des donnees du graphique du modele nom : quoi = « curve »
    (courbes moyennes et enveloppes), « trajectory » (trajectoires
    individuelles) ou « all » (les deux : un fichier _curves et un fichier
    _trajectories). Separateur « ; », comme les autres exports. """
    if nom not in resultats_boites:
        messagebox.showinfo("Export data", "Select the plot of an executed model first.")
        return
    try:
        courbes, trajectoires = tableaux_export_modele(nom)
    except Exception as erreur:
        messagebox.showerror("Export data", "The export failed:\n" + str(erreur))
        return
    if quoi in ("trajectory", "all") and trajectoires is None:
        messagebox.showwarning("Export data", "The individual data of this model were not kept: the trajectories cannot be exported.")
        if quoi == "trajectory":
            return
        quoi = "curve"
    base = _nom_fichier_export(nom)
    titres = {"curve": "Export the mean curves and their envelopes", "trajectory": "Export the individual trajectories",
              "all": "Export the mean curves and the individual trajectories"}
    suffixe = {"curve": "_curves", "trajectory": "_trajectories", "all": ""}[quoi]
    chemin = filedialog.asksaveasfilename(defaultextension = ".csv", filetypes = [("CSV file", "*.csv")],
                                          initialfile = base + suffixe + ".csv", title = titres[quoi])
    if not chemin:
        return
    if quoi == "all":
        racine = os.path.splitext(chemin)[0]
        fichiers = [(racine + "_curves.csv", courbes), (racine + "_trajectories.csv", trajectoires)]
    else:
        fichiers = [(chemin, courbes if quoi == "curve" else trajectoires)]
    try:
        for fichier, tableau in fichiers:
            tableau.to_csv(fichier, sep = ";", index = False, encoding = "utf-8-sig")
    except Exception as erreur:
        messagebox.showerror("Export data", "The export failed:\n" + str(erreur))
        return
    messagebox.showinfo("Export data", "Results exported to:\n" + "\n".join(f for f, _ in fichiers))


##-----------------------------------------------------------------------------
##  Cases « Envelope » et « Trajectory » du panneau des resultats
##-----------------------------------------------------------------------------
def cadre_stat_options (parent, ligne, nom, ligne_export = None):
    """ Cases du panneau des resultats, propres a chaque graphique :
    - « Trajectory » : trajectoires individuelles des sujets (option show_data) ;
    - « Envelope » : enveloppe d'erreur autour des courbes moyennes (option
      envelope ; type et niveau choisis dans la configuration).
    Avec « All analyses », les cases agissent sur le graphique selectionne
    (clic sur le graphique) et affichent son etat. Options du graphique : le
    calcul n'est pas relance. """
    cadre = Frame(parent, background = "gray90")
    cadre.grid(row = ligne, column = 0, sticky = "ew", padx = 8, pady = (12, 0))
    cases = {}
    selection = {"analyse": None}

    def cible ():
        ## analyse du graphique selectionne parmi les graphiques affiches
        return selection["analyse"] if selection["analyse"] in noms_affiches else (noms_affiches[0] if noms_affiches else None)

    def maj_cases ():
        c = cible()
        config = parametres_infomerge.get(c, {})
        for cle, var in cases.items():
            var.set(bool(config.get(cle, defauts_boite(c)[cle])))
        entree_tn.configure(state = "normal")
        var_tn.set(str(config.get("max_subjects", defauts_boite(c)["max_subjects"])))
        etat_widgets()

    def sur_selection (ax):
        ## clic sur un graphique : les cases prennent l'etat de son analyse ;
        ## « Export data » n'apparait que lorsqu'un graphique est selectionne
        if not cadre.winfo_exists():
            rappel_selection["fonction"] = None
            return
        if getattr(ax, "analyse", None) is not None:
            selection["analyse"] = ax.analyse
            maj_cases()
            afficher_export(True)
        elif ax is None:
            afficher_export(False)

    def retracer (c):
        if noms_affiches and panneau_graphique is not None and panneau_graphique.winfo_exists():
            try:
                afficher_resultats_infomerge(list(noms_affiches), panneau_graphique)
            except Exception as erreur:
                messagebox.showerror("Clustering", "The plot could not be drawn:\n" + str(erreur))
                return
            ## le graphique modifie reste selectionne
            ax = next((a for a in etat_zoom["axes"] if getattr(a, "analyse", None) == c), None)
            if ax is not None:
                selectionner_graphique(ax)

    for k, (texte, cle) in enumerate((("Trajectory", "show_data"), ("Envelope", "envelope"))):
        cases[cle] = BooleanVar(value = False)

        def basculer (cle = cle):
            c = cible()
            if c in parametres_infomerge:
                parametres_infomerge[c][cle] = cases[cle].get()     # propre a cette analyse
            etat_widgets()
            retracer(c)

        Checkbutton(cadre, text = texte, variable = cases[cle], command = basculer, font = ('arial', 14), fg = "gray30",
                    background = "gray90", activebackground = "gray90", highlightthickness = 0,
                    anchor = "w").grid(row = 0, column = k, sticky = "w", padx = (0, 12))   # meme ligne
    ## sous « Trajectory », comme les types sous « Graphiques » dans « Plots » :
    ## options en retrait, affichees seulement si « Trajectory » est coche
    ##   All : toutes les trajectoires individuelles ;  TN : nombre de trajectoires
    sous_cadre = Frame(cadre, background = "gray90")
    cases["all_subjects"] = BooleanVar(value = False)
    var_tn = StringVar(value = "")
    case_all = Checkbutton(sous_cadre, text = "All", variable = cases["all_subjects"], font = ('arial', 13), fg = "gray30",
                           background = "gray90", activebackground = "gray90", highlightthickness = 0, anchor = "w")
    case_all.grid(row = 0, column = 0, columnspan = 2, sticky = "w", pady = 1)
    Label(sous_cadre, text = "TN", font = ('arial', 13), fg = "gray30", background = "gray90").grid(row = 1, column = 0, sticky = "w", padx = (4, 0), pady = 1)
    entree_tn = Spinbox(sous_cadre, from_ = 1, to = 100000, increment = 10, textvariable = var_tn, width = 6)
    entree_tn.grid(row = 1, column = 1, sticky = "w", padx = (8, 0), pady = 1)

    def etat_widgets ():
        ## options visibles seulement avec « Trajectory » ; TN inactif si « All » est coche
        if cases["show_data"].get():
            sous_cadre.grid(row = 1, column = 0, columnspan = 2, sticky = "w", padx = (30, 0), pady = (2, 0))
        else:
            sous_cadre.grid_remove()
        entree_tn.configure(state = "disabled" if cases["all_subjects"].get() else "normal")

    def basculer_all ():
        c = cible()
        if c in parametres_infomerge:
            parametres_infomerge[c]["all_subjects"] = cases["all_subjects"].get()
        etat_widgets()
        retracer(c)

    def appliquer_tn (event = None):
        c = cible()
        try:
            tn = int(float(var_tn.get().strip().replace(",", ".")))
            if tn < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("TN", "TN must be a positive integer (number of trajectories to display).")
            var_tn.set(str(parametres_infomerge.get(c, {}).get("max_subjects", defauts_boite(c)["max_subjects"])))
            return
        if c in parametres_infomerge and parametres_infomerge[c].get("max_subjects") != tn:
            parametres_infomerge[c]["max_subjects"] = tn
            retracer(c)

    case_all.configure(command = basculer_all)
    entree_tn.configure(command = appliquer_tn)
    entree_tn.bind("<Return>", appliquer_tn)
    entree_tn.bind("<FocusOut>", appliquer_tn)
    ## « Regressed data » : seulement pour un modele avec covariables (graphique
    ## selectionne) ; cochee, donnees regressees sur les covariables et courbes
    ## moyennes recalculees ; decochee, donnees brutes et leurs courbes moyennes
    cases["regressed"] = BooleanVar(value = False)

    def basculer_regression ():
        c = cible()
        if c in parametres_infomerge:
            parametres_infomerge[c]["regressed"] = cases["regressed"].get()   # propre a ce graphique
        retracer(c)

    case_regression = Checkbutton(cadre, text = "Regressed data", variable = cases["regressed"], command = basculer_regression,
                                  font = ('arial', 14), fg = "gray30", background = "gray90", activebackground = "gray90",
                                  highlightthickness = 0, anchor = "w")
    etat_widgets_trajectoire = etat_widgets

    def etat_widgets ():
        etat_widgets_trajectoire()
        c = cible()
        x = resultats_boites.get(c)
        if x is not None and getattr(x, "gamma", None) is not None:
            case_regression.grid(row = 2, column = 0, columnspan = 2, sticky = "w", pady = (6, 0))
        else:
            case_regression.grid_remove()

    ## « Export data » (dans le panneau, apres « Comparisons ») : affichee
    ## apres un clic sur le graphique d'un modele ; cochee, trois cases en
    ## retrait. Cocher une case exporte aussitot ses donnees (fenetre
    ## d'enregistrement), puis la case se decoche :
    ##   Curve : courbes moyennes et enveloppes (Class, Time, Mean, Lower, Upper)
    ##   Trajectory : trajectoires individuelles (ID, Time, Value, Class)
    ##   All : les deux ensembles de donnees (deux fichiers CSV)
    var_export = BooleanVar(value = False)
    choix_export = {q: BooleanVar(value = False) for q in ("curve", "trajectory", "all")}
    style_export = dict(font = ('arial', 13), fg = "gray30", background = "gray90", activebackground = "gray90",
                        highlightthickness = 0, anchor = "w")
    cadre_export = Frame(parent, background = "gray90")
    sous_export = Frame(cadre_export, background = "gray90")

    def decocher_choix ():
        for var in choix_export.values():
            var.set(False)

    def basculer_export ():
        if var_export.get():
            sous_export.pack(side = "top", anchor = "w", padx = (30, 0), pady = (2, 0))
        else:
            sous_export.pack_forget()
        decocher_choix()

    def cocher_choix (quoi):
        if not choix_export[quoi].get():
            return
        if quoi == "all":                          # « All » : courbes et trajectoires
            for var in choix_export.values():
                var.set(True)
        cadre_export.update_idletasks()
        try:
            exporter_donnees_modele(cible(), quoi)
        finally:
            decocher_choix()                       # une case peut etre cochee de nouveau

    Checkbutton(cadre_export, text = "Export data", variable = var_export, command = basculer_export,
                **dict(style_export, font = ('arial', 14))).pack(side = "top", anchor = "w")
    for texte, quoi in (("Curve", "curve"), ("Trajectory", "trajectory"), ("All", "all")):
        Checkbutton(sous_export, text = texte, variable = choix_export[quoi], command = lambda q = quoi: cocher_choix(q),
                    **style_export).pack(side = "top", anchor = "w", pady = 1)

    def afficher_export (visible):
        if visible and ligne_export is not None:
            cadre_export.grid(row = ligne_export, column = 0, sticky = "ew", padx = 8, pady = (8, 0))
        else:
            cadre_export.grid_remove()
            var_export.set(False)
            basculer_export()

    rappel_selection["fonction"] = sur_selection
    maj_cases()
    afficher_export(etat_zoom.get("actif") is not None and getattr(etat_zoom.get("actif"), "analyse", None) in noms_affiches)
    return cadre


file_execution = []                # analyses en attente d'execution (bouton « Run »)
arret_run = {"demande": False}     # bouton d'arret clique pendant « Run »


##------ Encadre d'execution (comme dans SmartDigiCat) ------------------------
## Pendant « Run », un encadre au centre du panneau central indique l'execution
## en cours, l'analyse calculee, le temps ecoule et le temps restant estime ; le
## bouton d'arret passe sur fond bleu. L'encadre se deplace a la souris et
## disparait des la fin (ou des un clic sur le bouton d'arret).
## Temps restant : le travail est decoupe en unites (une analyse). Duree prevue
## d'une analyse : sa duree lors de son precedent calcul si elle est connue,
## sinon la moyenne des analyses deja terminees pendant cette execution.
COULEUR_EXECUTION = "cornflowerblue"               # meme bleu que la barre de taille
durees_analyses = {}               # analyse -> duree de son dernier calcul (secondes)
_progression = {"actif": False, "total": 0, "fait": 0, "debut": 0.0, "debut_unite": 0.0,
                "durees_faites": [], "durees_prevues": [], "nom": None}
_indicateur = {"cadre": None, "titre": None, "temps": None, "position": (0.5, 0.5), "tache": None}


def progression_demarrer (noms):
    maintenant = time.time()
    _progression.update(actif = True, total = len(noms), fait = 0, debut = maintenant, debut_unite = maintenant,
                        durees_faites = [], durees_prevues = [durees_analyses.get(n) for n in noms], nom = None)


def progression_unite (nom):
    """ Debut du calcul de l'analyse nom (l'unite precedente est terminee). """
    _progression["nom"] = nom
    _progression["debut_unite"] = time.time()


def progression_unite_terminee (nom, reussie):
    duree = time.time() - _progression["debut_unite"]
    _progression["durees_faites"].append(duree)
    _progression["fait"] += 1
    if reussie:
        durees_analyses[nom] = duree               # duree prevue au prochain calcul
    return duree


def _temps_restant ():
    p = _progression
    if not p["actif"] or p["fait"] >= p["total"]:
        return 0.0
    faites = p["durees_faites"]
    moyenne = max(sum(faites) / len(faites), faites[-1]) if faites else None
    restantes = [d if d is not None and d > 0 else moyenne for d in p["durees_prevues"][p["fait"]:]]
    if any(d is None for d in restantes):
        return None                                # estimation impossible pour le moment
    return max(restantes[0] - (time.time() - p["debut_unite"]), 0.0) + sum(restantes[1:])


def _duree_texte (secondes):
    secondes = int(secondes + 0.999)
    if secondes >= 3600:
        return "%d h %02d min" % (secondes // 3600, (secondes % 3600) // 60)
    if secondes >= 60:
        return "%d min %02d s" % (secondes // 60, secondes % 60)
    return "%d s" % secondes


def _textes_indicateur ():
    p = _progression
    titre = "Running: " + str(p["nom"] or "") + ("   (%d / %d)" % (min(p["fait"] + 1, p["total"]), p["total"]) if p["total"] > 1 else "")
    restant = _temps_restant()
    if restant is None:
        valeur = "estimating..."
    elif restant < 1:
        valeur = "almost finished..."
    else:
        valeur = _duree_texte(restant)
    temps = "Elapsed time: " + _duree_texte(time.time() - p["debut"]) + "\nEstimated remaining time: " + valeur
    return titre, temps


def _rendre_indicateur_deplacable (cadre):
    depart = {"dx": 0, "dy": 0}

    def debut (event):
        depart["dx"] = event.x_root - (cadre.winfo_rootx() + cadre.winfo_width() / 2)
        depart["dy"] = event.y_root - (cadre.winfo_rooty() + cadre.winfo_height() / 2)
        return "break"

    def glisser (event):
        zone = cadre.master
        largeur, hauteur = zone.winfo_width(), zone.winfo_height()
        if largeur <= 1 or hauteur <= 1:
            return "break"
        demi_l, demi_h = cadre.winfo_width() / 2, cadre.winfo_height() / 2
        cx = min(max(event.x_root - depart["dx"] - zone.winfo_rootx(), demi_l), max(demi_l, largeur - demi_l))
        cy = min(max(event.y_root - depart["dy"] - zone.winfo_rooty(), demi_h), max(demi_h, hauteur - demi_h))
        _indicateur["position"] = (cx / largeur, cy / hauteur)        # position conservee
        cadre.place(relx = cx / largeur, rely = cy / hauteur, anchor = "center")
        return "break"

    for widget in [cadre] + list(cadre.winfo_children()):
        widget.configure(cursor = "fleur")
        widget.bind("<ButtonPress-1>", debut)
        widget.bind("<B1-Motion>", glisser)


def _creer_indicateur ():
    cadre = tk.Frame(Center_frame, background = "white", highlightthickness = 2, highlightbackground = COULEUR_EXECUTION,
                     highlightcolor = COULEUR_EXECUTION, padx = 30, pady = 20)    # contour bleu, comme le bouton d'arret actif
    Label(cadre, text = "Execution in progress...", font = ('arial', 20, 'bold'), fg = "gray20", bg = "white").pack(pady = (0, 6))
    Label(cadre, text = "Click the stop button (left bar) to interrupt it.", font = ('arial', 14), fg = "gray40", bg = "white").pack()
    titre, temps = _textes_indicateur()
    _indicateur["titre"] = Label(cadre, text = titre, font = ('arial', 14), fg = "gray20", bg = "white")
    _indicateur["titre"].pack(pady = (10, 0))
    _indicateur["temps"] = Label(cadre, text = temps, font = ('arial', 15, 'bold'), fg = COULEUR_EXECUTION, bg = "white", justify = "center")
    _indicateur["temps"].pack(pady = (6, 0))
    _rendre_indicateur_deplacable(cadre)
    relx, rely = _indicateur["position"]
    cadre.place(relx = relx, rely = rely, anchor = "center")
    _indicateur["cadre"] = cadre


def _couleur_bouton_arret (en_cours):
    couleur = COULEUR_EXECUTION if en_cours else "gray20"
    try:
        button_arret_model.configure(background = couleur, activebackground = couleur, bordercolor = couleur,
                                     focuscolor = couleur, highlightbackground = couleur)
    except tk.TclError:
        pass


def supprimer_indicateur ():
    """ Fin de l'execution ou arret : l'encadre disparait immediatement. """
    if _indicateur["tache"] is not None:
        try:
            SmartDigicat.after_cancel(_indicateur["tache"])
        except tk.TclError:
            pass
        _indicateur["tache"] = None
    cadre = _indicateur["cadre"]
    if cadre is not None and cadre.winfo_exists():
        cadre.destroy()
    _indicateur.update(cadre = None, titre = None, temps = None)
    _progression["actif"] = False
    _couleur_bouton_arret(False)


## ------ Blocage de l'interface pendant « Run » (comme dans SmartDigiCat) ------
## Chaque widget de l'application recoit en tete de ses « bindtags » une etiquette
## qui intercepte (return "break") clics, glisser et clavier : ses reactions ne sont
## plus declenchees, mais il garde son aspect (rien n'est grise). Seuls le bouton
## d'arret et l'encadre d'execution (deplacable) restent accessibles. La molette
## reste possible pour faire defiler, sauf sur les listes, champs numeriques et la
## barre de reglage, ou elle changerait la valeur. Curseur « montre ».
_TAG_BLOCAGE_RUN = "AbosBlocageRun"
_TAG_BLOCAGE_MOLETTE_RUN = "AbosBlocageMoletteRun"
_CLASSES_MOLETTE_BLOQUEE = ("TCombobox", "Spinbox", "TSpinbox", "Scale", "TScale", "Listbox")
_EVENEMENTS_BLOQUES_RUN = ("<ButtonPress>", "<ButtonRelease>", "<Double-ButtonPress>", "<Triple-ButtonPress>",
                           "<B1-Motion>", "<B2-Motion>", "<B3-Motion>", "<KeyPress>", "<KeyRelease>")
_EVENEMENTS_MOLETTE_RUN = ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>")
_blocage_run = {"classes_liees": False, "dernier_passage": 0.0, "actif": False}


def _descendants_widget (widget):
    try:
        enfants = widget.winfo_children()
    except Exception:
        return []
    resultat = []
    for enfant in enfants:
        resultat.append(enfant)
        resultat.extend(_descendants_widget(enfant))
    return resultat


def bloquer_interface (bloquer):
    """ True : plus aucun widget accessible sauf le bouton d'arret et l'encadre
    d'execution ; False : retour a la normale. Rappelee pendant l'execution pour
    bloquer aussi les widgets crees entre-temps. """
    if not _blocage_run["classes_liees"]:
        for evenement in _EVENEMENTS_BLOQUES_RUN:
            SmartDigicat.bind_class(_TAG_BLOCAGE_RUN, evenement, lambda event: "break")
        for evenement in _EVENEMENTS_MOLETTE_RUN:
            SmartDigicat.bind_class(_TAG_BLOCAGE_MOLETTE_RUN, evenement, lambda event: "break")
        _blocage_run["classes_liees"] = True
    _blocage_run["actif"] = bloquer
    exclus = set(str(w) for w in [button_arret_model] + _descendants_widget(button_arret_model))
    cadre = _indicateur.get("cadre")
    try:
        if cadre is not None and cadre.winfo_exists():
            exclus.update(str(w) for w in [cadre] + _descendants_widget(cadre))   # encadre deplacable
    except Exception:
        pass
    for widget in [SmartDigicat] + _descendants_widget(SmartDigicat):
        if str(widget) in exclus:
            continue
        try:
            etiquettes = [t for t in widget.bindtags() if t not in (_TAG_BLOCAGE_RUN, _TAG_BLOCAGE_MOLETTE_RUN)]
            if bloquer:
                ajout = [_TAG_BLOCAGE_RUN]
                if widget.winfo_class() in _CLASSES_MOLETTE_BLOQUEE:
                    ajout.append(_TAG_BLOCAGE_MOLETTE_RUN)
                etiquettes = ajout + etiquettes
            widget.bindtags(tuple(etiquettes))
        except Exception:
            pass
    try:
        SmartDigicat.configure(cursor = "watch" if bloquer else "")
        button_arret_model.configure(cursor = "hand2" if bloquer else "")     # seul bouton cliquable
    except Exception:
        pass
    if bloquer:
        try:
            SmartDigicat.focus_set()           # retire le focus clavier d'un champ de saisie
        except Exception:
            pass


def maintenir_indicateur ():
    """ Pendant l'execution (4 fois par seconde) : textes mis a jour ; encadre
    recree s'il a ete detruit et garde au premier plan (le panneau central
    peut changer pendant le calcul). """
    _indicateur["tache"] = None
    if not _progression["actif"] or arret_run["demande"]:
        supprimer_indicateur()
        return
    cadre = _indicateur["cadre"]
    if cadre is None or not cadre.winfo_exists():
        _creer_indicateur()
    else:
        titre, temps = _textes_indicateur()
        if _indicateur["titre"].cget("text") != titre:
            _indicateur["titre"].configure(text = titre)
        if _indicateur["temps"].cget("text") != temps:
            _indicateur["temps"].configure(text = temps)
    _indicateur["cadre"].lift()
    _couleur_bouton_arret(True)
    ## widgets apparus pendant l'execution : bloques eux aussi (au plus 3 fois / s)
    if _blocage_run["actif"] and time.time() - _blocage_run["dernier_passage"] > 0.3:
        _blocage_run["dernier_passage"] = time.time()
        bloquer_interface(True)
    _indicateur["tache"] = SmartDigicat.after(250, maintenir_indicateur)


def demander_arret_execution ():
    """ Bouton d'arret (barre verticale gauche, actif seulement pendant
    « Run ») : les analyses en attente ne sont pas lancees et l'analyse en
    cours est interrompue a sa prochaine etape (son resultat est abandonne). """
    if not calculs_en_cours and not file_execution:
        return
    arret_run["demande"] = True
    file_execution.clear()
    for etat in calculs_en_cours.values():
        etat["arret"] = True
    rafraichir_boites()
    supprimer_indicateur()                         # l'encadre d'execution disparait immediatement
    _message_barre("Stopping the execution...")


def executer_boite (parent):
    """ Bouton « Run » (barre du haut) : execute toutes les analyses
    configurees, sans selection prealable, l'une apres l'autre. Le panneau
    Clustering affiche l'etat de chaque boite (Waiting, Running, Executed) ;
    a la fin, les resultats s'affichent automatiquement (ils restent
    accessibles par le bouton « Log ») ; un bilan signale les analyses
    ignorees ou en echec. """
    if data_analy is None:
        messagebox.showinfo("Run", "Please import data first (button 'Import data').")
        return
    if calculs_en_cours or file_execution:
        messagebox.showinfo("Run", "The analyses are already running.")
        return
    a_lancer = [n for n in analyses if boite_configuree(n)]
    ignorees = [n for n in analyses if n not in a_lancer]
    if not a_lancer:
        messagebox.showinfo("Run", "No analysis to run: create a box (button 'Analysis'), then choose and "
                                   "configure its clustering method (button 'Settings').")
        return
    for n in a_lancer:
        resultats_boites.pop(n, None)
        traces_graphiques.pop(PREFIXE_RESULTATS + n, None)   # anciens graphiques retires de « Save plot »
    traces_graphiques.pop(PREFIXE_RESULTATS + TOUTES_ANALYSES, None)
    file_execution[:] = a_lancer
    bilan = {"reussies": [], "echecs": [], "arretees": []}
    arret_run["demande"] = False
    progression_demarrer(a_lancer)                 # temps restant estime (encadre d'execution)
    afficher_boites(parent)                        # etats affiches dans les boites
    bloquer_interface(True)                        # plus aucun bouton accessible, sauf le bouton d'arret

    def suivante (erreur = None, nom = None):
        if nom is not None:
            progression_unite_terminee(nom, erreur is None)
            if erreur == TEXTE_ARRET:
                bilan["arretees"].append(nom)
            else:
                (bilan["echecs"] if erreur is not None else bilan["reussies"]).append(nom if erreur is None else nom + " : " + erreur)
        ## analyses supprimees ou deconfigurees entre-temps : ignorees
        while file_execution and (file_execution[0] not in analyses or file_execution[0] not in parametres_infomerge):
            file_execution.pop(0)
        if not file_execution:
            supprimer_indicateur()                 # calculs termines : encadre retire tout de suite
            bloquer_interface(False)               # interface de nouveau accessible
            SmartDigicat.update_idletasks()
            rafraichir_boites()
            historique_valider("Run")
            afficher_log(parent)                   # resultats affiches automatiquement (aussi sous « Log »)
            texte = str(len(bilan["reussies"])) + " analysis(es) executed."
            if arret_run["demande"]:
                texte = "Execution stopped by the user.\n\n" + texte
                if bilan["arretees"]:
                    texte += "\n\nInterrupted:\n" + "\n".join(bilan["arretees"])
            if ignorees:
                texte += "\n\nNot configured (skipped):\n" + "\n".join(ignorees)
            if bilan["echecs"]:
                messagebox.showwarning("Run", texte + "\n\nFailed:\n" + "\n".join(bilan["echecs"]))
            elif ignorees or arret_run["demande"]:
                messagebox.showinfo("Run", texte)
            arret_run["demande"] = False
            return
        n = file_execution.pop(0)
        progression_unite(n)
        if _indicateur["tache"] is None:
            maintenir_indicateur()                 # encadre d'execution au centre du panneau central
        try:
            executer_infomerge(n, None, apres = lambda err, n = n: suivante(err, n))
        except Exception as exc:                   # donnees incompatibles avec la configuration
            calculs_en_cours.pop(n, None)
            suivante(str(exc), n)
        rafraichir_boites()

    suivante()


def supprimer_boite (parent):
    """ Bouton « Delete » : la boite selectionnee passe dans la corbeille
    (recuperable avec le bouton « Restore »). """
    nom = boite_selectionnee["nom"]
    if nom not in analyses:
        messagebox.showinfo("Delete", "Please select a box first (click on it in the Clustering panel).")
        return
    if not messagebox.askyesno("Delete", "Do you really want to delete the box « " + nom + " »?\n\nYou can restore it later with the « Restore » button."):
        return
    nom_corbeille, k = nom, 2
    while nom_corbeille in corbeille_boites:
        nom_corbeille, k = nom + " (" + str(k) + ")", k + 1
    corbeille_boites[nom_corbeille] = {"couleur": couleurs_boites.pop(nom, None), "position": positions_boites.pop(nom, None),
                                       "methode": methodes_boites.pop(nom, None),
                                       "parametres": parametres_infomerge.pop(nom, None),
                                       "resultat": resultats_boites.pop(nom, None)}
    analyses.remove(nom)
    for liste in modeles_comparaison.values():      # retiree des boites de comparaison
        if nom in liste:
            liste.remove(nom)
    traces_graphiques.pop(PREFIXE_RESULTATS + nom, None)
    traces_graphiques.pop(PREFIXE_RESULTATS + TOUTES_ANALYSES, None)
    boite_selectionnee["nom"] = None
    afficher_boites(parent)
    historique_valider("Delete « " + nom + " »")


def corbeille (parent):
    """ Bouton « Restore » : corbeille des boites supprimees, dans le panneau
    central ; restauration (avec un nouveau nom si le nom est repris) ou
    suppression definitive. """
    if not corbeille_boites:
        messagebox.showinfo("Restore", "The recycle bin is empty: no box deleted for the moment.")
        return
    afficher_boites(parent)                           # la corbeille s'ouvre sur le panneau Clustering
    boite = nouvelle_boite(panneau_courant)
    Label(boite, text = "Recycle bin", font = ('arial', 15, 'bold'), fg = "saddlebrown").pack(anchor = "w", padx = 15, pady = (10, 0))
    Label(boite, text = "Select a box to restore", font = ('arial', 13)).pack(anchor = "w", padx = 15, pady = (0, 6))
    liste = tk.Listbox(boite, font = ('arial', 13), selectmode = tk.SINGLE, exportselection = False, width = 32,
                       height = min(max(len(corbeille_boites), 4), 12), relief = GROOVE)
    liste.pack(fill = BOTH, expand = True, padx = 15)
    noms = list(corbeille_boites)
    for n in noms:
        liste.insert(END, n)
    liste.selection_set(0)

    def selection_liste ():
        choix = liste.curselection()
        if not choix:
            messagebox.showinfo("Restore", "Please select a box in the list.", parent = boite)
            return None
        return noms[choix[0]]

    def restaurer ():
        nom = selection_liste()
        if nom is None:
            return
        nom_final = nom
        if nom_final in analyses:
            nom_final = simpledialog.askstring("Name already used", "A box is already named « " + nom + " ». New name for the restored box:",
                                               initialvalue = nom + " (restored)", parent = boite)
            if nom_final is None or nom_final.strip() == "":
                return
            nom_final = nom_final.strip()
            if nom_final in analyses:
                messagebox.showwarning("Name already used", "This name is already used. Restoration cancelled.", parent = boite)
                return
        infos = corbeille_boites.pop(nom)
        analyses.append(nom_final)
        if infos["couleur"] is not None:
            couleurs_boites[nom_final] = infos["couleur"]
        if infos["position"] is not None:
            positions_boites[nom_final] = infos["position"]
        for cle, dico in (("methode", methodes_boites), ("parametres", parametres_infomerge), ("resultat", resultats_boites)):
            if infos.get(cle) is not None:
                dico[nom_final] = infos[cle]
        boite_selectionnee["nom"] = nom_final
        afficher_boites(parent)                       # ferme aussi la corbeille
        historique_valider("Restore « " + nom_final + " »")

    def supprimer_definitivement ():
        nom = selection_liste()
        if nom is None:
            return
        if not messagebox.askyesno("Delete permanently", "Permanently delete « " + nom + " »?\n\nThis action cannot be undone.", parent = boite):
            return
        del corbeille_boites[nom]
        boite.destroy()
        historique_valider("Delete permanently « " + nom + " »")
        if corbeille_boites:
            corbeille(parent)

    cadre = Frame(boite)
    cadre.pack(pady = 10)
    tk.Button(cadre, text = "Restore", command = restaurer, width = 10).pack(side = LEFT, padx = 4)
    tk.Button(cadre, text = "Delete permanently", command = supprimer_definitivement, width = 16).pack(side = LEFT, padx = 4)
    tk.Button(cadre, text = "Close", command = boite.destroy, width = 8).pack(side = LEFT, padx = 4)
    liste.bind("<Double-Button-1>", lambda event: restaurer())



##=============================================================================
##  Projets (boutons « New », « Open », « Save »), historique (« Undo »,
##  « Redo ») et enregistrement a la fermeture, sur le modele de SmartDigiCat.
##  Toutes les analyses se font dans un projet : sans projet ouvert, les
##  boutons d'analyse sont desactives.
##  Un projet = un fichier JSON (reglages lisibles : boites, methodes,
##  configurations, filtres, conversions, polices) + un dossier
##  « <nom>_fichiers » contenant donnees.pkl (donnees importees et editees,
##  resultats des analyses, au format pickle de Python).
##=============================================================================
nom_projet = None                  # projet ouvert (None : aucun)
chemin_projet = None               # fichier JSON du projet
VERSION_PROJET = 1
HISTORIQUE_TAILLE_MAX = 20
_historique = {"etats": [], "index": -1, "restauration": False, "compteur": 0}
## Fermeture : la boite « Save before quitting » n'apparait que si le projet a
## ete modifie depuis son dernier enregistrement (True : a chaque fermeture).
TOUJOURS_DEMANDER_A_LA_FERMETURE = False
_etat_enregistre = {"signature": None}
_fermeture = {"dialogue_ouvert": False}
TEXTE_BARRE_BASSE = "Biological Atlas of Severe Obesity"


def _maj_titre_fenetre ():
    SmartDigicat.title("abos v1.0" + (traduire(" - Project : ") + nom_projet if nom_projet else ""))


def verifier_projet_ouvert (donnees = False):
    """ Toutes les analyses se font dans un projet (et, pour certaines, apres
    l'import des donnees). Affiche un avertissement sinon. """
    if nom_projet is None:
        messagebox.showwarning("No project open", "Please first create a new project (button « New ») "
                                                  "or open an existing one (button « Open »).")
        return False
    if donnees and data is None:
        messagebox.showwarning("No data", "Please import the data first (button « Import data »).")
        return False
    return True


def analyse_autorisee ():
    """ Vrai si un projet est ouvert (nouveau ou existant) et si des donnees
    ont ete importees (comme dans SmartDigiCat). """
    return nom_projet is not None and data is not None


def dans_projet (fonction, donnees = False):
    """ Commande de bouton executee seulement si un projet est ouvert. """
    return lambda: fonction() if verifier_projet_ouvert(donnees) else None


##------ Historique : un « point » enregistre apres chaque action -------------
def _copie_parametres (dico):
    return {n: {c: (list(v) if isinstance(v, list) else v) for c, v in p.items()} for n, p in dico.items()}


def _etat_courant (etiquette):
    """ Etat du projet (les tableaux et les resultats ne sont jamais modifies
    sur place : ils sont partages entre les points sans copie). """
    _historique["compteur"] += 1
    return {"id": _historique["compteur"], "etiquette": etiquette,
            "data": data, "data_analy": data_analy, "filtres": dict(filtres),
            "colonnes_categorielles": list(colonnes_categorielles), "colonnes_double": list(colonnes_double),
            "analyses": list(analyses), "couleurs": dict(couleurs_boites), "positions": dict(positions_boites),
            "taille": taille_boites, "taille_comparaisons": taille_comparaisons, "methodes": dict(methodes_boites),
            "parametres": _copie_parametres(parametres_infomerge), "resultats": dict(resultats_boites),
            "corbeille": {n: dict(e, parametres = (dict(e["parametres"]) if e.get("parametres") else None))
                          for n, e in corbeille_boites.items()},
            "selection": boite_selectionnee["nom"],
            "comparaisons": list(comparaisons), "modeles_comparaison": {c: list(m) for c, m in modeles_comparaison.items()},
            "positions_comparaisons": dict(positions_comparaisons),
            "corbeille_comparaisons": {c: {"modeles": list(e["modeles"]), "position": e.get("position"),
                                           "indices": list(e.get("indices") or []), "couleur": e.get("couleur")}
                                       for c, e in corbeille_comparaisons.items()},
            "indices_comparaison": {c: list(v) for c, v in indices_comparaison.items()},
            "couleurs_comparaisons": dict(couleurs_comparaisons)}


def historique_valider (etiquette):
    """ Enregistre l'etat courant comme nouveau point de l'historique. """
    if _historique["restauration"] or nom_projet is None:
        return
    try:
        etat = _etat_courant(etiquette)
    except Exception:
        return
    etats = _historique["etats"]
    del etats[_historique["index"] + 1:]          # une nouvelle action invalide les « Redo » en attente
    etats.append(etat)
    while len(etats) > HISTORIQUE_TAILLE_MAX:
        del etats[0]
    _historique["index"] = len(etats) - 1


def _historique_reinitialiser (etiquette):
    _historique.update(etats = [], index = -1)
    historique_valider(etiquette)
    _projet_marquer_enregistre()                  # projet neuf ou tout juste ouvert


def _regler_taille_comparaisons (taille):
    """ Taille des boites de comparaison et position de la barre de zoom droite. """
    global taille_comparaisons
    taille_comparaisons = int(taille)
    try:
        scale_comparaisons.configure(command = "")
        scale_comparaisons.set(int((taille_comparaisons - TAILLE_BOITE_MIN) / (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN) * 100))
        scale_comparaisons.configure(command = zoomer_comparaisons)
    except (NameError, tk.TclError):
        pass


def _historique_appliquer (etat):
    global data, data_analy, filtres, colonnes_categorielles, colonnes_double, taille_boites
    _historique["restauration"] = True
    try:
        data, data_analy = etat["data"], etat["data_analy"]
        filtres = dict(etat["filtres"])
        colonnes_categorielles = list(etat["colonnes_categorielles"])
        colonnes_double = list(etat["colonnes_double"])
        analyses[:] = etat["analyses"]
        taille_boites = etat["taille"]
        _regler_taille_comparaisons(etat.get("taille_comparaisons", taille_comparaisons))
        for dico, cle in ((couleurs_boites, "couleurs"), (positions_boites, "positions"), (methodes_boites, "methodes"),
                          (resultats_boites, "resultats")):
            dico.clear()
            dico.update(etat[cle])
        parametres_infomerge.clear()
        parametres_infomerge.update(_copie_parametres(etat["parametres"]))
        corbeille_boites.clear()
        corbeille_boites.update({n: dict(e) for n, e in etat["corbeille"].items()})
        boite_selectionnee["nom"] = etat["selection"] if etat["selection"] in analyses else None
        comparaisons[:] = etat.get("comparaisons", [])
        modeles_comparaison.clear()
        modeles_comparaison.update({c: list(m) for c, m in etat.get("modeles_comparaison", {}).items()})
        positions_comparaisons.clear()
        positions_comparaisons.update(etat.get("positions_comparaisons", {}))
        corbeille_comparaisons.clear()
        corbeille_comparaisons.update({c: {"modeles": list(e["modeles"]), "position": e.get("position"),
                                           "indices": list(e.get("indices") or []), "couleur": e.get("couleur")}
                                       for c, e in etat.get("corbeille_comparaisons", {}).items()})
        indices_comparaison.clear()
        indices_comparaison.update({c: list(v) for c, v in etat.get("indices_comparaison", {}).items()})
        couleurs_comparaisons.clear()
        couleurs_comparaisons.update(etat.get("couleurs_comparaisons", {}))
        if boite_selectionnee.get("comparaison") not in comparaisons:
            boite_selectionnee["comparaison"] = None
        for titre in [t for t in traces_graphiques if t.startswith(PREFIXE_RESULTATS)]:
            traces_graphiques.pop(titre)          # graphiques de resultats retraces a la demande
    finally:
        _historique["restauration"] = False


def _message_barre (texte):
    try:
        bottom_frame.configure(text = texte)
        SmartDigicat.after(3500, lambda: bottom_frame.configure(text = TEXTE_BARRE_BASSE))
    except tk.TclError:
        pass


def _apres_historique (texte):
    """ Interface redessinee apres Undo / Redo : panneau Clustering. """
    if analyses or comparaisons:
        afficher_boites(Center_frame)
    elif panneau_courant is not None and panneau_courant.winfo_exists():
        panneau_courant.destroy()                 # retour a l'ecran d'accueil
    _message_barre(texte)


def _historique_bloque ():
    if calculs_en_cours or file_execution:
        messagebox.showinfo("Undo / Redo", "Please wait for the end of the running analyses.")
        return True
    return False


def annuler_derniere_action ():
    if not analyse_autorisee() or _historique["index"] <= 0 or _historique_bloque():
        return
    etiquette = _historique["etats"][_historique["index"]]["etiquette"]
    _historique["index"] -= 1
    _historique_appliquer(_historique["etats"][_historique["index"]])
    _apres_historique("Undo : " + etiquette)


def refaire_derniere_action ():
    if not analyse_autorisee() or _historique["index"] >= len(_historique["etats"]) - 1 or _historique_bloque():
        return
    _historique["index"] += 1
    etat = _historique["etats"][_historique["index"]]
    _historique_appliquer(etat)
    _apres_historique("Redo : " + etat["etiquette"])


##------ Modifications non enregistrees ---------------------------------------
def _signature_projet ():
    """ Point courant de l'historique + reglages non suivis par l'historique
    (options des graphiques de resultats, polices). """
    try:
        point = _historique["etats"][_historique["index"]]["id"] if _historique["etats"] else None
    except (IndexError, KeyError):
        point = None
    return (point, repr(sorted((n, sorted(p.items(), key = str)) for n, p in parametres_infomerge.items())),
            repr(police_graphiques), repr(point_moyenne), taille_boites, taille_comparaisons)


def _projet_marquer_enregistre ():
    _etat_enregistre["signature"] = _signature_projet()


def projet_a_des_modifications ():
    if nom_projet is None:
        return False
    try:
        return _signature_projet() != _etat_enregistre["signature"]
    except Exception:
        return True


##------ Enregistrement (« Save ») --------------------------------------------
def _dossier_associe (chemin_json):
    return os.path.splitext(chemin_json)[0] + "_fichiers"


def _vers_json (valeur):
    """ Valeurs JSON (les tuples deviennent des listes ; numpy -> Python). """
    if isinstance(valeur, dict):
        return {str(k): _vers_json(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_vers_json(v) for v in valeur]
    if isinstance(valeur, np.generic):
        return valeur.item()
    return valeur


def save_current_project (silencieux = False, autosave = False):
    """ Enregistre le projet. Renvoie True (enregistre), False (echec, deja
    signale) ou None (aucun projet). """
    if nom_projet is None:
        verifier_projet_ouvert()
        return None
    dossier = _dossier_associe(chemin_projet)
    nom_dossier = os.path.basename(dossier)
    executees = {n: r for n, r in resultats_boites.items() if n not in calculs_en_cours}
    contenu = {
        "logiciel": "abos", "version": VERSION_PROJET, "nom_projet": nom_projet,
        "enregistre_le": time.strftime("%Y-%m-%d %H:%M:%S"),
        "analyses": list(analyses), "couleurs_boites": dict(couleurs_boites),
        "positions_boites": positions_boites, "taille_boites": taille_boites, "taille_comparaisons": taille_comparaisons,
        "methodes_boites": dict(methodes_boites), "parametres_infomerge": parametres_infomerge,
        "corbeille": {n: {"couleur": e.get("couleur"), "position": e.get("position"), "methode": e.get("methode"),
                          "parametres": e.get("parametres")} for n, e in corbeille_boites.items()},
        "selection": boite_selectionnee["nom"],
        "comparaisons": list(comparaisons), "modeles_comparaison": modeles_comparaison,
        "positions_comparaisons": positions_comparaisons, "corbeille_comparaisons": corbeille_comparaisons,
        "indices_comparaison": indices_comparaison, "couleurs_comparaisons": couleurs_comparaisons,
        "filtres": filtres, "colonnes_categorielles": list(colonnes_categorielles),
        "colonnes_double": list(colonnes_double), "police_graphiques": police_graphiques,
        "point_moyenne": point_moyenne,
        "parametres_graphiques": {"Trajectory": parametres_trajectoire, "Box plot": parametres_boxplot,
                                  "Bar plot": parametres_barplot, "Histogram": parametres_histogramme},
        "durees_analyses": {n: round(d, 3) for n, d in durees_analyses.items() if n in analyses},   # temps restant estime
        "fichier_donnees": nom_dossier + "/donnees.pkl",
    }
    binaire = {"data": data, "data_analy": data_analy, "resultats": executees,
               "resultats_corbeille": {n: e.get("resultat") for n, e in corbeille_boites.items() if e.get("resultat") is not None}}
    try:
        os.makedirs(dossier, exist_ok = True)
        chemin_pkl = os.path.join(dossier, "donnees.pkl")
        with open(chemin_pkl + ".tmp", "wb") as fichier:
            pickle.dump(binaire, fichier, protocol = pickle.HIGHEST_PROTOCOL)
        os.replace(chemin_pkl + ".tmp", chemin_pkl)
        with open(chemin_projet + ".tmp", "w", encoding = "utf-8") as fichier:
            json.dump(_vers_json(contenu), fichier, ensure_ascii = False, indent = 1)
        os.replace(chemin_projet + ".tmp", chemin_projet)   # ecriture atomique : l'ancien fichier reste intact en cas d'echec
    except Exception as erreur:
        if autosave:                              # enregistrement automatique : echec signale dans la barre du bas
            _message_barre("Automatic save failed: " + str(erreur))
        else:
            messagebox.showerror("Save", "The project could not be saved:\n" + str(erreur))
        return False
    _projet_marquer_enregistre()
    if not silencieux:
        _message_barre("Project « " + nom_projet + " » saved")
        messagebox.showinfo("Save", "The project « " + nom_projet + " » has been saved in:\n" + chemin_projet)
    return True


##------ Espace de travail ----------------------------------------------------
def _reinitialiser_espace_travail ():
    """ Vide l'espace de travail (nouveau projet ou ouverture d'un projet). """
    global data, data_analy, filtres, colonnes_categorielles, colonnes_double, taille_boites
    data = data_analy = None
    filtres = {}
    colonnes_categorielles, colonnes_double = [], []
    for dico in (couleurs_boites, positions_boites, methodes_boites, parametres_infomerge, resultats_boites, corbeille_boites,
                 durees_analyses):
        dico.clear()
    analyses.clear()
    comparaisons.clear()
    modeles_comparaison.clear()
    positions_comparaisons.clear()
    corbeille_comparaisons.clear()
    indices_comparaison.clear()
    couleurs_comparaisons.clear()
    boite_selectionnee["comparaison"] = None
    file_execution.clear()
    noms_affiches.clear()
    traces_graphiques.clear()
    type_courant["titre"] = None
    boite_selectionnee["nom"] = None
    taille_boites = 90
    _regler_taille_comparaisons(TAILLE_COMPARAISON_DEFAUT)
    if panneau_courant is not None and panneau_courant.winfo_exists():
        panneau_courant.destroy()                 # retour a l'ecran d'accueil


def _travail_en_cours_perdu (titre):
    """ Avant New / Open : propose d'enregistrer le projet ouvert s'il a ete
    modifie. Renvoie False si l'utilisateur annule. """
    if calculs_en_cours or file_execution:
        messagebox.showinfo(titre, "Please wait for the end of the running analyses.")
        return False
    if nom_projet is None or not projet_a_des_modifications():
        return True
    choix = messagebox.askyesnocancel(titre, "The project « " + nom_projet + " » contains unsaved changes.\n\n"
                                             "Save it before continuing?")
    if choix is None:
        return False
    if choix:
        return save_current_project(silencieux = True) is True
    return True


def nouveau_projet ():
    """ Bouton « New » : nom et emplacement du projet, espace de travail vide,
    enregistrement initial. """
    global nom_projet, chemin_projet
    if not _travail_en_cours_perdu("New project"):
        return
    nom = simpledialog.askstring("New project", "Name of the new project", initialvalue = "New project")
    if nom is None or nom.strip() == "":
        return
    nom = nom.strip()
    emplacement = filedialog.asksaveasfilename(defaultextension = ".json", filetypes = [("ABOS project (JSON)", "*.json")],
                                               initialfile = nom_fichier_sur(nom) + ".json",
                                               title = "Location of the project « " + nom + " »")
    if not emplacement:
        return
    _reinitialiser_espace_travail()
    nom_projet, chemin_projet = nom, emplacement
    _historique_reinitialiser("New project")
    _maj_titre_fenetre()
    if save_current_project(silencieux = True):
        messagebox.showinfo("New project", "The project « " + nom + " » has been created and saved in:\n" + emplacement +
                            "\n\nYou can now import the data (« Import data »), then create one or more analyses "
                            "with the « Analysis » button (left vertical bar).")


def ouvrir_projet ():
    """ Bouton « Open » : ouvre un projet enregistre (fichier JSON). """
    global nom_projet, chemin_projet, data, data_analy, filtres, colonnes_categorielles, colonnes_double, taille_boites
    if not _travail_en_cours_perdu("Open project"):
        return
    chemin = filedialog.askopenfilename(filetypes = [("ABOS project (JSON)", "*.json"), ("All files", "*.*")], title = "Open a project")
    if not chemin:
        return
    try:
        with open(chemin, encoding = "utf-8") as fichier:
            contenu = json.load(fichier)
        if contenu.get("logiciel") != "abos":
            raise ValueError("this file is not an ABOS project.")
    except Exception as erreur:
        messagebox.showerror("Open project", "The project file could not be read:\n" + str(erreur))
        return
    binaire, avertissement = {}, None
    chemin_pkl = os.path.join(os.path.dirname(chemin), contenu.get("fichier_donnees") or "")
    if os.path.isfile(chemin_pkl):
        try:
            with open(chemin_pkl, "rb") as fichier:
                binaire = pickle.load(fichier)
        except Exception as erreur:
            avertissement = "The data and results could not be read:\n" + str(erreur)
    elif contenu.get("fichier_donnees"):
        avertissement = "The data file of the project was not found:\n" + chemin_pkl
    _reinitialiser_espace_travail()
    nom_projet, chemin_projet = contenu.get("nom_projet") or os.path.splitext(os.path.basename(chemin))[0], chemin
    data, data_analy = binaire.get("data"), binaire.get("data_analy")
    filtres = {c: (g, tuple(v) if g == "intervalle" else list(v)) for c, (g, v) in (contenu.get("filtres") or {}).items()}
    colonnes_categorielles = list(contenu.get("colonnes_categorielles") or [])
    colonnes_double = list(contenu.get("colonnes_double") or [])
    analyses.extend(contenu.get("analyses") or [])
    comparaisons.extend(contenu.get("comparaisons") or [])
    modeles_comparaison.update({c: [m for m in l if m in analyses] for c, l in (contenu.get("modeles_comparaison") or {}).items()})
    positions_comparaisons.update({c: tuple(v) for c, v in (contenu.get("positions_comparaisons") or {}).items()})
    corbeille_comparaisons.update({c: {"modeles": list(e.get("modeles") or []),
                                       "position": tuple(e["position"]) if e.get("position") else None,
                                       "indices": list(e.get("indices") or []), "couleur": e.get("couleur")}
                                   for c, e in (contenu.get("corbeille_comparaisons") or {}).items()})
    couleurs_comparaisons.update(contenu.get("couleurs_comparaisons") or {})
    indices_comparaison.update({c: [i for i in v if i in INDICES_COMPARAISON]
                                for c, v in (contenu.get("indices_comparaison") or {}).items()})
    couleurs_boites.update(contenu.get("couleurs_boites") or {})
    positions_boites.update({n: tuple(p) for n, p in (contenu.get("positions_boites") or {}).items()})
    taille_boites = int(contenu.get("taille_boites") or 90)
    _regler_taille_comparaisons(int(contenu.get("taille_comparaisons") or TAILLE_COMPARAISON_DEFAUT))
    methodes_boites.update(contenu.get("methodes_boites") or {})
    parametres_infomerge.update(contenu.get("parametres_infomerge") or {})
    resultats_boites.update({n: r for n, r in (binaire.get("resultats") or {}).items() if n in analyses})
    for n, e in (contenu.get("corbeille") or {}).items():
        corbeille_boites[n] = {"couleur": e.get("couleur"), "position": tuple(e["position"]) if e.get("position") else None,
                               "methode": e.get("methode"), "parametres": e.get("parametres"),
                               "resultat": (binaire.get("resultats_corbeille") or {}).get(n)}
    for cle, valeur in (contenu.get("police_graphiques") or {}).items():
        if cle in police_graphiques:
            police_graphiques[cle].update(valeur)
    point_moyenne.update({"afficher": False, "couleur": "red", "taille": 6})
    point_moyenne.update({k: v for k, v in (contenu.get("point_moyenne") or {}).items() if k in point_moyenne})
    for nom_type, memoire in (("Trajectory", parametres_trajectoire), ("Box plot", parametres_boxplot),
                              ("Bar plot", parametres_barplot), ("Histogram", parametres_histogramme)):
        lu = (contenu.get("parametres_graphiques") or {}).get(nom_type) or {}
        if lu:
            memoire["variables"] = lu.get("variables") or None
            memoire["parametres"] = lu.get("parametres") or {}
    boite_selectionnee["nom"] = contenu.get("selection") if contenu.get("selection") in analyses else None
    durees_analyses.update({n: float(d) for n, d in (contenu.get("durees_analyses") or {}).items() if n in analyses})
    _historique_reinitialiser("Open project")
    _maj_titre_fenetre()
    if analyses:
        afficher_boites(Center_frame)
    if avertissement:
        messagebox.showwarning("Open project", avertissement)
    _message_barre("Project « " + nom_projet + " » opened")


##------ Fermeture du logiciel ------------------------------------------------
def _boite_enregistrer_avant_quitter (modifie):
    """ Boite modale : « save », « quit » (sans enregistrer) ou « cancel ». """
    choix = {"valeur": "cancel"}
    fenetre = tk.Toplevel(SmartDigicat)
    fenetre.title(traduire("Save before quitting"))
    fenetre.transient(SmartDigicat)
    fenetre.resizable(False, False)

    def choisir (valeur):
        choix["valeur"] = valeur
        fenetre.destroy()

    tk.Label(fenetre, text = "Do you want to save your work before quitting ABOS?", font = ("arial", 15, "bold"),
             wraplength = 480, justify = "left").pack(padx = 24, pady = (20, 6), anchor = "w")
    detail = ("The project « " + nom_projet + " » contains unsaved changes.\nYour changes will be lost if you don't save them."
              if modifie else "The project « " + nom_projet + " » is open.")
    tk.Label(fenetre, text = detail, font = ("arial", 13), wraplength = 480, justify = "left",
             fg = "gray30").pack(padx = 24, pady = (0, 14), anchor = "w")
    boutons = tk.Frame(fenetre)
    boutons.pack(pady = (0, 18))
    bouton_save = ttk.Button(boutons, text = "Save", command = lambda: choisir("save"))
    bouton_save.pack(side = LEFT, padx = 6)
    ttk.Button(boutons, text = "Don't save", command = lambda: choisir("quit")).pack(side = LEFT, padx = 6)
    ttk.Button(boutons, text = "Cancel", command = lambda: choisir("cancel")).pack(side = LEFT, padx = 6)
    fenetre.bind("<Return>", lambda event: choisir("save"))
    fenetre.bind("<Escape>", lambda event: choisir("cancel"))
    fenetre.protocol("WM_DELETE_WINDOW", lambda: choisir("cancel"))
    fenetre.update_idletasks()
    x = SmartDigicat.winfo_rootx() + (SmartDigicat.winfo_width() - fenetre.winfo_reqwidth()) // 2
    y = SmartDigicat.winfo_rooty() + (SmartDigicat.winfo_height() - fenetre.winfo_reqheight()) // 2
    fenetre.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
    fenetre.grab_set()
    bouton_save.focus_set()
    SmartDigicat.wait_window(fenetre)
    return choix["valeur"]


def fermer_application (event = None):
    """ Fermeture (croix de la fenetre, Cmd+Q) : propose d'enregistrer le
    projet s'il a ete modifie depuis son dernier enregistrement. """
    if _fermeture["dialogue_ouvert"]:
        return
    _fermeture["dialogue_ouvert"] = True
    try:
        peut_fermer = True
        modifie = projet_a_des_modifications()
        if nom_projet is not None and (modifie or TOUJOURS_DEMANDER_A_LA_FERMETURE):
            choix = _boite_enregistrer_avant_quitter(modifie)
            if choix == "cancel":
                peut_fermer = False
            elif choix == "save" and save_current_project(silencieux = True) is not True:
                peut_fermer = messagebox.askyesno("Save before quitting", "The project could not be saved. Quit anyway, without saving?")
    except Exception:
        peut_fermer = True                        # une erreur de la boite ne doit jamais empecher de fermer
    finally:
        _fermeture["dialogue_ouvert"] = False
    if peut_fermer:
        SmartDigicat.destroy()


def installer_fermeture_propre ():
    SmartDigicat.protocol("WM_DELETE_WINDOW", fermer_application)
    if sys.platform == "darwin":
        try:                                      # Cmd+Q et « Quitter » du Dock : meme demande
            SmartDigicat.createcommand("::tk::mac::Quit", fermer_application)
        except tk.TclError:
            pass


##------ Enregistrement automatique toutes les 5 minutes ----------------------
INTERVALLE_AUTOSAVE_MS = 5 * 60 * 1000


def autosave_projet ():
    """ Enregistre le projet ouvert sans interrompre l'utilisateur (seulement
    s'il a ete modifie), puis se replanifie 5 minutes plus tard. """
    try:
        if nom_projet is not None and chemin_projet is not None and projet_a_des_modifications():
            if save_current_project(silencieux = True, autosave = True):
                _message_barre("Project « " + nom_projet + " » saved automatically (" + time.strftime("%H:%M") + ")")
    except Exception:
        pass
    try:
        SmartDigicat.after(INTERVALLE_AUTOSAVE_MS, autosave_projet)
    except tk.TclError:
        pass


##------ Boutons actifs seulement dans un projet ------------------------------
def _icone_grisee (chemin_relatif):
    """ Version grisee d'une icone (bouton desactive) ; None si PIL est absent. """
    try:
        from PIL import Image as _ImagePIL, ImageTk as _ImageTkPIL
        icone = _ImagePIL.open(my_path(chemin_relatif)).convert("RGBA")
        gris = icone.convert("L")
        alpha = icone.getchannel("A").point(lambda valeur: int(valeur * 0.35))
        return _ImageTkPIL.PhotoImage(_ImagePIL.merge("RGBA", (gris, gris, gris, alpha)))
    except Exception:
        return None


_etat_boutons = {"signature": None}


def maj_etat_boutons_projet ():
    """ Active / desactive les boutons selon le projet (et les donnees) ;
    Undo / Redo selon l'historique. Se replanifie toutes les 250 ms. """
    try:
        actif_analyse = analyse_autorisee()
        peut_annuler = actif_analyse and _historique["index"] > 0
        peut_refaire = actif_analyse and _historique["index"] < len(_historique["etats"]) - 1
        execution = bool(calculs_en_cours or file_execution)
        projet = nom_projet is not None
        signature = (actif_analyse, peut_annuler, peut_refaire, execution, projet)
        if signature != _etat_boutons["signature"]:
            _etat_boutons["signature"] = signature
            for bouton, icone, icone_grisee, condition in _boutons_lies_au_projet:
                actif = {"analyse": actif_analyse, "undo": peut_annuler, "redo": peut_refaire,
                         "execution": execution, "projet": projet}[condition]
                try:
                    bouton.configure(state = "normal" if actif else "disabled")
                    if icone_grisee is not None:
                        bouton.configure(image = icone if actif else icone_grisee)
                except tk.TclError:
                    pass
    finally:
        try:
            SmartDigicat.after(250, maj_etat_boutons_projet)
        except tk.TclError:
            pass


##=============================================================================
##  Boutons de la barre verticale gauche ajoutes (comme dans SmartDigiCat) :
##  Rename, arret de l'execution, capture de l'interface, export CSV des
##  analyses, langue et police.
##=============================================================================
def renommer_boite (parent):
    """ Bouton « Rename » : renomme la boite d'analyse selectionnee (sa
    configuration, son resultat et ses reglages suivent le nouveau nom). """
    ancien = boite_selectionnee["nom"]
    if ancien not in analyses:
        messagebox.showinfo("Rename", "Please select a box first (click on it in the Clustering panel).")
        return
    if ancien in calculs_en_cours or ancien in file_execution:
        messagebox.showinfo("Rename", "« " + ancien + " » is running: please wait for the end of the execution.")
        return
    nouveau = simpledialog.askstring("Rename", "New name of the analysis « " + ancien + " »", initialvalue = ancien)
    if nouveau is None or nouveau.strip() == "" or nouveau.strip() == ancien:
        return
    nouveau = nouveau.strip()
    if nouveau in analyses or nouveau in comparaisons:
        messagebox.showwarning("Name already used", "This name is already used. Choose a different name.")
        return
    analyses[analyses.index(ancien)] = nouveau
    for c in modeles_comparaison:                  # le nom suit dans les boites de comparaison
        modeles_comparaison[c] = [nouveau if m == ancien else m for m in modeles_comparaison[c]]
    for dico in (couleurs_boites, positions_boites, methodes_boites, parametres_infomerge, resultats_boites, durees_analyses):
        if ancien in dico:
            dico[nouveau] = dico.pop(ancien)
    for titre in (PREFIXE_RESULTATS + ancien, PREFIXE_RESULTATS + TOUTES_ANALYSES):
        traces_graphiques.pop(titre, None)
    noms_affiches[:] = [nouveau if n == ancien else n for n in noms_affiches]
    if ("analyse", ancien) in bornes_axes["graphiques"]:
        bornes_axes["graphiques"][("analyse", nouveau)] = bornes_axes["graphiques"].pop(("analyse", ancien))
    boite_selectionnee["nom"] = nouveau
    afficher_boites(parent)
    historique_valider("Rename « " + ancien + " » → « " + nouveau + " »")


def capturer_interface_courante ():
    """ Bouton de capture : image de la fenetre de l'application telle
    qu'elle est affichee, enregistree au format PNG. """
    SmartDigicat.update_idletasks()
    x, y = SmartDigicat.winfo_rootx(), SmartDigicat.winfo_rooty()
    largeur, hauteur = SmartDigicat.winfo_width(), SmartDigicat.winfo_height()
    try:
        from PIL import ImageGrab
        ecran = ImageGrab.grab()
        ## ecrans haute resolution (Retina) : pixels reels / pixels logiques
        ex = ecran.size[0] / SmartDigicat.winfo_screenwidth()
        ey = ecran.size[1] / SmartDigicat.winfo_screenheight()
        image = ecran.crop((int(x * ex), int(y * ey), int((x + largeur) * ex), int((y + hauteur) * ey)))
    except Exception as erreur:
        messagebox.showerror("Screenshot", "The screenshot of the interface failed:\n" + str(erreur))
        return
    chemin = filedialog.asksaveasfilename(defaultextension = ".png", filetypes = [("PNG image", "*.png"), ("All files", "*.*")],
                                          initialfile = "capture_abos.png", title = "Save the screenshot of the interface")
    if not chemin:
        return
    try:
        image.save(chemin)
        messagebox.showinfo("Screenshot", "The screenshot has been saved:\n" + chemin)
    except Exception as erreur:
        messagebox.showerror("Screenshot", "The image could not be saved:\n" + str(erreur))


def exporter_analyses_csv ():
    """ Bouton d'export : tableau des analyses du projet (configuration, etat,
    K retenu, criteres) et, a cote, la classe de chaque sujet pour les
    analyses executees (fichier « <nom>_clusters.csv »). """
    if not analyses:
        messagebox.showinfo("Export analyses", "No analysis created yet (button « Analysis »).")
        return
    chemin = filedialog.asksaveasfilename(defaultextension = ".csv", filetypes = [("CSV file", "*.csv"), ("All files", "*.*")],
                                          initialfile = "analyses.csv", title = "Export the analyses to a CSV file")
    if not chemin:
        return
    lignes, classes = [], {}
    for n in analyses:
        v = parametres_infomerge.get(n, {})
        x = resultats_boites.get(n) if n not in calculs_en_cours else None
        ligne = {"Analysis": n, "Method": methodes_boites.get(n), "State": etat_boite(n),
                 "Response": v.get("response"), "Identifier": v.get("id"), "Time": v.get("time"),
                 "Covariates": ", ".join(v.get("covariates") or []) or None,
                 "K (configuration)": (v.get("K") if str(v.get("K", "")).strip() != "" else "auto") if v else None,
                 "Criterion": (v.get("criterion") if methodes_boites.get(n) == "InfoMergeCluster" else "MSE") if v else None,
                 "Random effect": v.get("re"), "df": v.get("df"),
                 "Basis": v.get("basis"), "N.bs": v.get("N_bs"), "Covariate effect": v.get("cov_effect"),
                 "K selected": None, "Proportions": None, "BIC": None, "ICL": None, "Log-likelihood": None,
                 "MSE": None, "Lambda": None, "Subjects": None, "Measurements": None}
        if x is not None:
            ligne.update({"K selected": int(x.K), "Proportions": ", ".join("%.3f" % p for p in x.pi),
                          "Subjects": int(x.N), "Measurements": int(x.n_obs)})
            if getattr(x, "method", None) == "FKMS":
                ligne["MSE"] = round(x.mse, 5)
                if x.lambda_clust is not None:
                    ligne["Lambda"] = ", ".join("%.3g" % l for l in x.lambda_clust)
            else:
                ligne["Log-likelihood"] = round(float(x.loglik), 3)
                choisi = x.table[x.table["K"] == x.K]
                if len(choisi):
                    ligne.update({"BIC": round(float(choisi["BIC"].iloc[0]), 3), "ICL": round(float(choisi["ICL"].iloc[0]), 3)})
            classes[n] = x.cluster.map(lambda k: "C" + str(int(k)))
        lignes.append(ligne)
    fichiers = [chemin]
    try:
        pd.DataFrame(lignes).to_csv(chemin, sep = ";", index = False, encoding = "utf-8-sig")
        if classes:
            chemin_classes = os.path.splitext(chemin)[0] + "_clusters.csv"
            tableau = pd.DataFrame(classes)
            tableau.index.name = "Subject"
            tableau.to_csv(chemin_classes, sep = ";", encoding = "utf-8-sig")
            fichiers.append(chemin_classes)
    except Exception as erreur:
        messagebox.showerror("Export analyses", "The export failed:\n" + str(erreur))
        return
    messagebox.showinfo("Export analyses", "The analyses have been exported to:\n" + "\n".join(fichiers))


##------ Langue des instructions (bouton « langue ») ---------------------------
## Comme dans SmartDigiCat : le code n'est pas reecrit message par message.
##  - les boites de dialogue (messagebox, askstring, selecteurs de fichiers,
##    choix de couleur) sont enveloppees : titre et message passent par
##    traduire() juste avant d'etre affiches ;
##  - les textes des Label, cases a cocher et boutons des panneaux et boites
##    sont traduits a leur creation (et les Label quand leur texte change), puis
##    retraduits a chaud quand on change de langue.
## Langue source : anglais (textes du code). Pour ajouter un texte : un tuple
## (anglais, francais) dans _TRADUCTIONS_EXACTES (texte complet) ou dans
## _TRADUCTIONS_FRAGMENTS (morceau d'un message construit avec un nom, un
## chemin, un nombre...). Les noms des boutons des barres, des parametres de
## infomergecluster() et les valeurs des listes deroulantes ne sont pas traduits.
_TRADUCTIONS_EXACTES = [
    ## import et edition des donnees
    ("Excel sheets", "Feuilles Excel"),
    ("Select at least one sheet.", "Sélectionnez au moins une feuille."),
    ("Import", "Importer"),
    ("Cancel", "Annuler"),
    ("Import data", "Importer les données"),
    ("Data successfully loaded! \n You can carry out the desired analysis. \n (descriptive analyses or modeling)",
     "Données chargées avec succès ! \n Vous pouvez effectuer l'analyse souhaitée. \n (analyses descriptives ou modélisation)"),
    ("Please try again import failed", "Échec de l'importation, veuillez réessayer"),
    ("Categorizing variables", "Variables catégorielles"),
    ("Convert to double", "Convertir en réel"),
    ("Select the variables to treat as categorical", "Sélectionnez les variables à traiter comme catégorielles"),
    ("Select the variables to convert to quantitative (double)", "Sélectionnez les variables à convertir en quantitatives (réel)"),
    ("Convert variable", "Convertir les variables"),
    ("Save", "Enregistrer"),
    ("Filtering data", "Filtrage des données"),
    ("Select the variables used to filter the data", "Sélectionnez les variables servant à filtrer les données"),
    ("Quantitative variable: click on the variable to specify its min and max.\nQualitative or integer variable: click on the variable, then select the modalities to keep.",
     "Variable quantitative : cliquez sur la variable pour indiquer son minimum et son maximum.\nVariable qualitative ou entière : cliquez sur la variable, puis sélectionnez les modalités à conserver."),
    ("Select all", "Tout sélectionner"),
    ("Clear", "Tout désélectionner"),
    ("Please enter numeric values for min and max.", "Veuillez saisir des valeurs numériques pour le minimum et le maximum."),
    ("The min must be lower than or equal to the max.", "Le minimum doit être inférieur ou égal au maximum."),
    ("Remove filter", "Retirer le filtre"),
    ("The table is empty.", "Le tableau est vide."),
    ("Export stat", "Exporter les statistiques"),
    ("Please display the statistics first (button 'Overview stat').", "Veuillez d'abord afficher les statistiques (bouton « Overview stat »)."),
    ("Export clean", "Exporter les données"),
    ("Please load data to be analyzed", "Veuillez charger les données à analyser"),
    ("Missing value imputation", "Imputation des valeurs manquantes"),
    ("Column", "Colonne"),
    ("Select the column and the methods used to treat its missing values", "Sélectionnez la colonne et les méthodes de traitement de ses valeurs manquantes"),
    ("Applied when you click on « View & Edit »", "Appliqué au clic sur « View & Edit »"),
    ("Quantitative", "Quantitative"),
    ("Qualitative", "Qualitative"),
    ("Search & change modality", "Rechercher et changer une modalité"),
    ("Characteristic", "Caractéristique"),
    ("Search", "Rechercher"),
    ("Replace", "Remplacer"),
    ("Rename column", "Renommer une colonne"),
    ("Parameters for overview", "Paramètres d'affichage"),
    ("Select the columns to display", "Sélectionnez les colonnes à afficher"),
    ("Lines to display", "Lignes à afficher"),
    ("All rows", "Toutes les lignes"),
    ## options des graphiques
    ("Title option", "Options du titre"),
    ("Axes option", "Options des axes"),
    ("Legend option", "Options de la légende"),
    ("Mean point", "Point moyen"),
    ("View point", "Afficher le point"),
    ("Point size", "Taille des points"),
    ("Statistics option", "Options des statistiques"),
    ("Font size", "Taille de police"),
    ("Font style", "Style de police"),
    ("Please enter a number (or leave the box empty for an automatic limit).", "Veuillez saisir un nombre (ou laisser la case vide pour une limite automatique)."),
    ("Zoom axes", "Zoom des axes"),
    ("Y-depth", "Hauteur Y"),
    ("Y-depth must be a height in pixels (at least 100), or empty for the default value.",
     "La hauteur doit être un nombre de pixels (au moins 100), ou vide pour la valeur par défaut."),
    ("Refresh", "Actualiser"),
    ("No plot to refresh: draw a plot first (button 'Plot').", "Aucun graphique à actualiser : tracez d'abord un graphique (bouton « Plot »)."),
    ("Save plot", "Enregistrer les graphiques"),
    ("No plot to save: draw a plot first (button 'Plot').", "Aucun graphique à enregistrer : tracez d'abord un graphique (bouton « Plot »)."),
    ("Select the plots to save", "Sélectionnez les graphiques à enregistrer"),
    ("Resolution (dpi)", "Résolution (dpi)"),
    ("Folder", "Dossier"),
    ("Folder for the plots", "Dossier des graphiques"),
    ("Browse…", "Parcourir…"),
    ("Check at least one plot.", "Cochez au moins un graphique."),
    ("The resolution must be an integer (at least 50 dpi).", "La résolution doit être un entier (au moins 50 dpi)."),
    ("Word file name", "Nom du fichier Word"),
    ("Saved as <name>.docx in the folder", "Enregistré sous <nom>.docx dans le dossier"),
    ("No variable available for this plot.", "Aucune variable disponible pour ce graphique."),
    ("Response variables", "Variables réponses"),
    ("Check a variable to define the parameters of its plot", "Cochez une variable pour définir les paramètres de son graphique"),
    ("Check at least one response variable.", "Cochez au moins une variable réponse."),
    ("Plot", "Graphique"),
    ("Parameters of the trajectory plot", "Paramètres du graphique des trajectoires"),
    ("$...$ for mathematical notation, e.g.  BMI (kg/m$^2$)", "$...$ pour la notation mathématique, ex.  BMI (kg/m$^2$)"),
    ("Title", "Titre"),
    ("Y-axis label", "Titre de l'axe Y"),
    ("X-axis label", "Titre de l'axe X"),
    ("Group variable", "Variable de groupe"),
    ("Labels", "Libellés"),
    ("Breaks", "Bornes"),
    ("e.g.  0=Non diabetic; 1=Type 1; 2=Type 2   or   < 40; 40-50; >= 50  (order of the levels)",
     "ex.  0=Non diabétique; 1=Type 1; 2=Type 2   ou   < 40; 40-50; >= 50  (ordre des niveaux)"),
    ("e.g.  -Inf, 40, 50, Inf   (classes [a, b))", "ex.  -Inf, 40, 50, Inf   (classes [a, b))"),
    ("Legend title", "Titre de la légende"),
    ("Group labels", "Libellés du groupe"),
    ("e.g.  0=Non diabetic; 1=Type 1; 2=Type 2   or   No; Yes  (order of the levels)", "ex.  0=Non diabétique; 1=Type 1; 2=Type 2   ou   Non; Oui  (ordre des niveaux)"),
    ("Empty: name of the group variable", "Vide : nom de la variable de groupe"),
    ("Color", "Couleur"),
    ("Color of the trajectories", "Couleur des trajectoires"),
    ("Choose…", "Choisir…"),
    ("Line width", "Épaisseur des lignes"),
    ("Labels require a group variable.", "Les libellés exigent une variable de groupe."),
    ("The line width must be a positive number.", "L'épaisseur des lignes doit être un nombre positif."),
    ("Parameters of the box plot", "Paramètres de la boîte à moustaches"),
    ("X variable", "Variable X"),
    ("Quantitative X variable, e.g.  -Inf, 40, 50, Inf   (classes (a, b])", "Variable X quantitative, ex.  -Inf, 40, 50, Inf   (classes (a, b])"),
    ("One per class, e.g.  ≤ 40; ]40 ; 50]; > 50   (empty: (a,b])", "Un par classe, ex.  ≤ 40; ]40 ; 50]; > 50   (vide : (a,b])"),
    ("Empty: name of the X variable", "Vide : nom de la variable X"),
    ("Select the X variable.", "Sélectionnez la variable X."),
    ("The group variable must differ from the X variable.", "La variable de groupe doit être différente de la variable X."),
    ("Labels require breaks.", "Les libellés exigent des bornes."),
    ("Parameters of the bar plot", "Paramètres du diagramme en barres"),
    ("Modality axis label", "Titre de l'axe des modalités"),
    ("Frequency axis label", "Titre de l'axe des fréquences"),
    ("Quantitative variable, e.g.  -Inf, 40, 50, Inf   (classes (a, b])", "Variable quantitative, ex.  -Inf, 40, 50, Inf   (classes (a, b])"),
    ("One per class (empty:  ≤ 40; ]40 ; 50]; > 50)", "Un par classe (vide :  ≤ 40; ]40 ; 50]; > 50)"),
    ("Color of the bars", "Couleur des barres"),
    ("Count", "Comptage"),
    ("rows: one observation per row;  patients: first non-missing value of each patient",
     "rows : une observation par ligne ;  patients : première valeur non manquante de chaque patient"),
    ("Parameters of the histogram", "Paramètres de l'histogramme"),
    ("Empty: Count, Frequency (%) or Density, according to the scale", "Vide : Count, Frequency (%) ou Density, selon l'échelle"),
    ("Number of bins", "Nombre de classes"),
    ("  empty: Sturges rule", "  vide : règle de Sturges"),
    ("Scale", "Échelle"),
    ("The number of bins must be a positive integer (or empty).", "Le nombre de classes doit être un entier positif (ou vide)."),
    ("Bar plot", "Diagramme en barres"),
    ("Box plot", "Boîte à moustaches"),
    ("Histogram", "Histogramme"),
    ("Trajectory", "Trajectoires"),
    ("Envelope", "Enveloppe"),
    ("Regressed data", "Données régressées"),
    ("Parameters of fkms.covariables.lambda.gcv()", "Paramètres de fkms.covariables.lambda.gcv()"),
    ("K (empty: automatic, min MSE)", "K (vide : automatique, MSE minimal)"),
    ("Grid of lambda values (GCV)", "Grille des valeurs de lambda (GCV)"),
    ("Values of lambda tested by generalized cross-validation", "Valeurs de lambda testées par validation croisée généralisée"),
    ("Lower bound", "Borne inférieure"),
    ("Upper bound", "Borne supérieure"),
    ("Number of values", "Nombre de valeurs"),
    ("The values are equally spaced on a logarithmic scale between the two bounds.",
     "Les valeurs sont régulièrement espacées sur une échelle logarithmique entre les deux bornes."),
    ("Please enter numeric values.", "Veuillez saisir des valeurs numériques."),
    ("Check 0 < lower bound < upper bound and a number of values >= 2.",
     "Vérifiez que 0 < borne inférieure < borne supérieure et que le nombre de valeurs est >= 2."),
    ("N.bs (basis functions)", "N.bs (fonctions de base)"),
    ("basis (B-spline / Fourier)", "basis (B-spline / Fourier)"),
    ("All", "Toutes"),
    ## analyses (boites, configuration, resultats)
    ("New analysis", "Nouvelle analyse"),
    ("Do you want to define a new analysis?", "Voulez-vous définir une nouvelle analyse ?"),
    ("Name of the new analysis", "Nom de la nouvelle analyse"),
    ("Name already used", "Nom déjà utilisé"),
    ("This name is already used. Choose a different name.", "Ce nom est déjà utilisé. Choisissez un autre nom."),
    ("No analysis defined yet.\nClick on the « Analysis » button (left vertical bar) to create one.",
     "Aucune analyse définie pour l'instant.\nCliquez sur le bouton « Analysis » (barre verticale gauche) pour en créer une."),
    ("Settings", "Paramètres"),
    ("Please select a box first (click on it in the Clustering panel).", "Veuillez d'abord sélectionner une boîte (cliquez dessus dans le panneau Clustering)."),
    ("Please select a clustering method", "Veuillez choisir une méthode de clustering"),
    ("Display settings", "Afficher les paramètres"),
    ("Results", "Résultats"),
    ("Please import data first (button 'Import data').", "Veuillez d'abord importer les données (bouton « Import data »)."),
    ("Parameters of infomergecluster()", "Paramètres de infomergecluster()"),
    ("Data", "Données"),
    ("Identifier", "Identifiant"),
    ("Response", "Réponse"),
    ("Covariates", "Covariables"),
    ("Model", "Modèle"),
    ("Algorithm", "Algorithme"),
    ("K (empty: automatic)", "K (vide : automatique)"),
    ("df (B-spline functions)", "df (fonctions B-spline)"),
    ("re (random effect)", "re (effet aléatoire)"),
    ("K0 (empty: automatic)", "K0 (vide : automatique)"),
    ("seed (empty: random)", "seed (vide : aléatoire)"),
    ("ylab (empty: response)", "ylab (vide : réponse)"),
    ("legend (right column)", "legend (colonne de droite)"),
    ("Please enter numeric values for the numeric parameters.", "Veuillez saisir des valeurs numériques pour les paramètres numériques."),
    ("Identifier, time and response must be three different columns.", "L'identifiant, le temps et la réponse doivent être trois colonnes différentes."),
    ("A covariate cannot be the identifier, the time or the response.", "Une covariable ne peut pas être l'identifiant, le temps ou la réponse."),
    ('weights = "covariates" requires at least one covariate.', 'weights = "covariates" exige au moins une covariable.'),
    ("Check df >= degree + 1, 1 <= pen_order <= degree and 0 < level < 1.", "Vérifiez que df >= degree + 1, 1 <= pen_order <= degree et 0 < level < 1."),
    ("InfoMergeCluster is running.", "InfoMergeCluster est en cours d'exécution."),
    ("Summary", "Résumé"),
    ("All analyses", "Toutes les analyses"),
    ("No analysis executed", "Aucune analyse exécutée"),
    ("No analysis selected", "Aucune analyse sélectionnée"),
    ("No result yet.\nConfigure the analyses, then click on « Run ».", "Aucun résultat pour l'instant.\nConfigurez les analyses, puis cliquez sur « Run »."),
    ("No result for the current configuration.", "Aucun résultat pour la configuration actuelle."),
    ("Click on « Run » (top bar) to run InfoMergeCluster.", "Cliquez sur « Run » (barre du haut) pour lancer InfoMergeCluster."),
    ("No analysis selected.", "Aucune analyse sélectionnée."),
    ("Check the analyses to display (Summary).", "Cochez les analyses à afficher (Résumé)."),
    ("TN must be a positive integer (number of trajectories to display).", "TN doit être un entier positif (nombre de trajectoires à afficher)."),
    ## etats des boites
    ("Created", "Créée"),
    ("Configured", "Configurée"),
    ("Waiting", "En attente"),
    ("Running", "En cours"),
    ("Executed", "Exécutée"),
    ("No method", "Aucune méthode"),
    ## execution
    ("Execution in progress...", "Exécution en cours..."),
    ("Click the stop button (left bar) to interrupt it.", "Cliquez sur le bouton d'arrêt (barre de gauche) pour l'interrompre."),
    ("Run", "Exécution"),
    ("The analyses are already running.", "Les analyses sont déjà en cours."),
    ("No analysis to run: create a box (button 'Analysis'), then choose and configure its clustering method (button 'Settings').",
     "Aucune analyse à exécuter : créez une boîte (bouton « Analysis »), puis choisissez et configurez sa méthode de clustering (bouton « Settings »)."),
    ("Stopping the execution...", "Arrêt de l'exécution..."),
    ## suppression, corbeille, renommage
    ("Delete", "Supprimer"),
    ("Restore", "Restaurer"),
    ("The recycle bin is empty: no box deleted for the moment.", "La corbeille est vide : aucune boîte supprimée pour le moment."),
    ("Recycle bin", "Corbeille"),
    ("Select a box to restore", "Sélectionnez une boîte à restaurer"),
    ("Please select a box in the list.", "Veuillez sélectionner une boîte dans la liste."),
    ("This name is already used. Restoration cancelled.", "Ce nom est déjà utilisé. Restauration annulée."),
    ("Delete permanently", "Supprimer définitivement"),
    ("Close", "Fermer"),
    ("Rename", "Renommer"),
    ("New comparison", "Nouvelle comparaison"),
    ("Name of the new comparison box", "Nom de la nouvelle boîte de comparaison"),
    ("Select models, then click on the arrow", "Sélectionnez des modèles, puis cliquez sur la flèche"),
    ("Select one or more model boxes first (Shift, Ctrl or Cmd + click to select several), then click on the arrow.",
     "Sélectionnez d'abord une ou plusieurs boîtes de modèles (Maj, Ctrl ou Cmd + clic pour en sélectionner plusieurs), puis cliquez sur la flèche."),
    ("Select model boxes, then click on the arrow of the comparison box to add them.",
     "Sélectionnez des boîtes de modèles, puis cliquez sur la flèche de la boîte de comparaison pour les ajouter."),
    ("more", "de plus"),
    ("Models to compare", "Modèles à comparer"),
    ("Comparisons", "Comparaisons"),
    ("Drag an analysis box onto the comparison box to add it.", "Glissez une boîte d'analyse sur la boîte de comparaison pour l'ajouter."),
    ("Comparison", "Comparaison"),
    ("Please select a model in the list.", "Veuillez sélectionner un modèle dans la liste."),
    ("Remove from comparison", "Retirer de la comparaison"),
    ("Comparison index", "Indice de comparaison"),
    ("Comparison results", "Résultats des comparaisons"),
    ("Indices computed on the subjects classified by both models (1 = identical partitions)",
     "Indices calculés sur les sujets classés par les deux modèles (1 = partitions identiques)"),
    ("Comparison / Model 1", "Comparaison / Modèle 1"),
    ("Model 2", "Modèle 2"),
    ("Fewer than two executed models: add models and click on « Run ».",
     "Moins de deux modèles exécutés : ajoutez des modèles et cliquez sur « Run »."),
    ("Export CSV", "Exporter en CSV"),
    ("No index to export: each comparison needs at least two executed models.",
     "Aucun indice à exporter : chaque comparaison doit contenir au moins deux modèles exécutés."),
    ("Export the comparison results", "Exporter les résultats des comparaisons"),
    ("Color of the comparison box", "Couleur de la boîte de comparaison"),
    ("Default", "Par défaut"),
    ("default", "par défaut"),
    ("Models", "Modèles"),
    ("No model yet: select model boxes, then click on the arrow ➜.", "Aucun modèle pour l'instant : sélectionnez des boîtes de modèles, puis cliquez sur la flèche ➜."),
    ("ARI: adjusted Rand index;  Jaccard: Jaccard index (pairs of subjects grouped together)",
     "ARI : indice de Rand ajusté ;  Jaccard : indice de Jaccard (paires de sujets regroupés ensemble)"),
    ("To remove a model: click on it in the comparison box, then on the arrow ⬅.",
     "Pour retirer un modèle : cliquez dessus dans la boîte de comparaison, puis sur la flèche ⬅."),
    ("Check at least one comparison index.", "Cochez au moins un indice de comparaison."),
    ("Click on one or more models in the comparison box to select them, then click on the arrow ⬅.",
     "Cliquez sur un ou plusieurs modèles dans la boîte de comparaison pour les sélectionner, puis sur la flèche ⬅."),
    ("Please select a comparison box first (click on it in the Clustering panel).",
     "Veuillez d'abord sélectionner une boîte de comparaison (cliquez dessus dans le panneau Clustering)."),
    ("The recycle bin is empty: no comparison box deleted for the moment.",
     "La corbeille est vide : aucune boîte de comparaison supprimée pour le moment."),
    ("Recycle bin (comparisons)", "Corbeille (comparaisons)"),
    ("Select a comparison box to restore", "Sélectionnez une boîte de comparaison à restaurer"),
    ## projets
    ("No project open", "Aucun projet ouvert"),
    ("Please first create a new project (button « New ») or open an existing one (button « Open »).",
     "Veuillez d'abord créer un nouveau projet (bouton « New ») ou en ouvrir un existant (bouton « Open »)."),
    ("No data", "Aucune donnée"),
    ("Please import the data first (button « Import data »).", "Veuillez d'abord importer les données (bouton « Import data »)."),
    ("Please wait for the end of the running analyses.", "Veuillez attendre la fin des analyses en cours."),
    ("New project", "Nouveau projet"),
    ("Name of the new project", "Nom du nouveau projet"),
    ("Open a project", "Ouvrir un projet"),
    ("Open project", "Ouvrir un projet"),
    ("Save before quitting", "Enregistrer avant de quitter"),
    ("Do you want to save your work before quitting ABOS?", "Voulez-vous enregistrer votre travail avant de quitter ABOS ?"),
    ("Don't save", "Ne pas enregistrer"),
    ("The project could not be saved. Quit anyway, without saving?", "Le projet n'a pas pu être enregistré. Quitter quand même, sans enregistrer ?"),
    ## capture, export, langue
    ("Screenshot", "Capture d'écran"),
    ("Save the screenshot of the interface", "Enregistrer la capture de l'interface"),
    ("Export analyses", "Exporter les analyses"),
    ("No analysis created yet (button « Analysis »).", "Aucune analyse créée pour l'instant (bouton « Analysis »)."),
    ("Export the analyses to a CSV file", "Exporter les analyses vers un fichier CSV"),
    ("Font", "Police"),
    ("Default font", "Police par défaut"),
    ## ecran d'accueil
    ("Clustering sparse longitudinal trajectories", "Clustering de trajectoires longitudinales éparses"),
    ("Authors:", "Auteurs :"),
    ("Contact:", "Contact :"),
    ## « Export data » (graphique d'un modele)
    ("Export data", "Exporter les données"),
    ("Curve", "Courbes"),
    ("Select the plot of an executed model first.", "Sélectionnez d'abord le graphique d'un modèle exécuté."),
    ("The individual data of this model were not kept: the trajectories cannot be exported.",
     "Les données individuelles de ce modèle n'ont pas été conservées : les trajectoires ne peuvent pas être exportées."),
    ("Export the mean curves and their envelopes", "Exporter les courbes moyennes et leurs enveloppes"),
    ("Export the individual trajectories", "Exporter les trajectoires individuelles"),
    ("Export the mean curves and the individual trajectories", "Exporter les courbes moyennes et les trajectoires individuelles"),
    ## manuel d'utilisation (bouton « Help »)
    ("User manual", "Manuel d'utilisation"),
    ("Fit width", "Pleine largeur"),
    ("Contents:", "Sommaire :"),
    ("Open in PDF reader", "Ouvrir dans le lecteur PDF"),
    ("The user manual could not be found.", "Le manuel d'utilisation est introuvable."),
    ("The user manual could not be displayed.", "Le manuel d'utilisation n'a pas pu être affiché."),
    ("The English manual is not available yet: the French version is displayed.",
     "Le manuel en anglais n'est pas encore disponible : la version française est affichée."),
    ("The French manual is not available: the English version is displayed.",
     "Le manuel en français n'est pas disponible : la version anglaise est affichée."),
]

_TRADUCTIONS_FRAGMENTS = [
    ("The file could not be opened:\n", "Le fichier n'a pas pu être ouvert :\n"),
    ("Select the sheets to import\n", "Sélectionnez les feuilles à importer\n"),
    ("The file could not be read:\n", "Le fichier n'a pas pu être lu :\n"),
    ("The selected files do not have the same columns.", "Les fichiers sélectionnés n'ont pas les mêmes colonnes."),
    ("The selected sheets do not have the same columns.", "Les feuilles sélectionnées n'ont pas les mêmes colonnes."),
    ("A variable cannot be both categorical and double:\n", "Une variable ne peut pas être à la fois catégorielle et réelle :\n"),
    ("Non-numeric values will be set to missing:\n", "Les valeurs non numériques deviendront manquantes :\n"),
    ("\n\nContinue?", "\n\nContinuer ?"),
    (" value(s)", " valeur(s)"),
    ("The variable ", "La variable "),
    (" has no observed value.", " n'a aucune valeur observée."),
    ("Observed range: [", "Étendue observée : ["),
    ("Modalities of ", "Modalités de "),
    ("Filters:\n  ", "Filtres :\n  "),
    ("No filter.\n", "Aucun filtre.\n"),
    ("Rows kept: ", "Lignes conservées : "),
    (" modality(ies) kept", " modalité(s) conservée(s)"),
    ("Select at least one modality for: ", "Sélectionnez au moins une modalité pour : "),
    ("The table could not be exported:\n", "Le tableau n'a pas pu être exporté :\n"),
    ("Table exported to:\n", "Tableau exporté dans :\n"),
    ("The data could not be exported:\n", "Les données n'ont pas pu être exportées :\n"),
    ("Missing value:  N = ", "Valeurs manquantes :  N = "),
    ("All columns (", "Toutes les colonnes ("),
    ("Missing value (", "Valeurs manquantes ("),
    ("  |  total:  N = ", "  |  total :  N = "),
    ("Rows: ", "Lignes : "),
    (" , Columns: ", " , Colonnes : "),
    (" Number of ", " Nombre de "),
    ("The plot could not be drawn:\n", "Le graphique n'a pas pu être tracé :\n"),
    ("The folder does not exist:\n", "Le dossier n'existe pas :\n"),
    ("These files already exist and will be replaced:\n", "Ces fichiers existent déjà et seront remplacés :\n"),
    ("The Word document could not be created:\n", "Le document Word n'a pas pu être créé :\n"),
    ("The Word document could not be saved:\n", "Le document Word n'a pas pu être enregistré :\n"),
    (" plot(s) saved in:\n", " graphique(s) enregistré(s) dans :\n"),
    ("\n\nNot saved:\n", "\n\nNon enregistré(s) :\n"),
    ("The data must contain the columns ", "Les données doivent contenir les colonnes "),
    (".\nMissing: ", ".\nManquantes : "),
    ("Breaks: ", "Bornes : "),
    (" row(s) excluded: group value not listed in the group labels.", " ligne(s) exclue(s) : valeur du groupe absente des libellés du groupe."),
    ("None of the values in the group labels exists in '", "Aucune des valeurs des libellés du groupe n'existe dans '"),
    ("The breaks must contain at least two strictly increasing values.", "Les bornes doivent contenir au moins deux valeurs strictement croissantes."),
    ("Choose a color for the box « ", "Choisissez une couleur pour la boîte « "),
    ("InfoMergeCluster failed:\n", "InfoMergeCluster a échoué :\n"),
    ("Running InfoMergeCluster...", "Exécution d'InfoMergeCluster..."),
    ("Error: ", "Erreur : "),
    ("Do you really want to delete the box « ", "Voulez-vous vraiment supprimer la boîte « "),
    ("Do you really want to delete the comparison box « ", "Voulez-vous vraiment supprimer la boîte de comparaison « "),
    (" »?\n\nThe analyses it contains are not deleted. You can restore it later with the « Restore » button (right bar).",
     " » ?\n\nLes analyses qu'elle contient ne sont pas supprimées. Vous pourrez la restaurer avec le bouton « Restore » (barre de droite)."),
    (" model(s))", " modèle(s))"),
    ("New name of the comparison box « ", "Nouveau nom de la boîte de comparaison « "),
    (" » is already in « ", " » est déjà dans « "),
    ("The selected models are already in « ", "Les modèles sélectionnés sont déjà dans « "),
    (" model(s) added to « ", " modèle(s) ajouté(s) à « "),
    (" model(s) removed from « ", " modèle(s) retiré(s) de « "),
    (" model(s) in the comparison", " modèle(s) dans la comparaison"),
    ("Not executed (ignored): ", "Non exécuté(s) (ignoré(s)) : "),
    ("Results exported to:\n", "Résultats exportés dans :\n"),
    ("Choose a color for the comparison box « ", "Choisissez une couleur pour la boîte de comparaison « "),
    (" »?\n\nYou can restore it later with the « Restore » button.", " » ?\n\nVous pourrez la restaurer plus tard avec le bouton « Restore »."),
    ("A box is already named « ", "Une boîte porte déjà le nom « "),
    (" ». New name for the restored box:", " ». Nouveau nom de la boîte restaurée :"),
    (" (restored)", " (restaurée)"),
    ("Permanently delete « ", "Supprimer définitivement « "),
    (" »?\n\nThis action cannot be undone.", " » ?\n\nCette action est irréversible."),
    (" » is running: please wait for the end of the execution.", " » est en cours d'exécution : veuillez attendre la fin de l'exécution."),
    ("New name of the analysis « ", "Nouveau nom de l'analyse « "),
    (" analysis(es) executed.", " analyse(s) exécutée(s)."),
    ("Execution stopped by the user.", "Exécution arrêtée par l'utilisateur."),
    ("\n\nInterrupted:\n", "\n\nInterrompue(s) :\n"),
    ("\n\nNot configured (skipped):\n", "\n\nNon configurée(s) (ignorée(s)) :\n"),
    ("\n\nFailed:\n", "\n\nÉchec :\n"),
    ("stopped by the user", "arrêtée par l'utilisateur"),
    ("Running: ", "En cours : "),
    ("Elapsed time: ", "Temps écoulé : "),
    ("Estimated remaining time: ", "Temps restant estimé : "),
    ("estimating...", "estimation en cours..."),
    ("almost finished...", "presque terminé..."),
    (" analyses selected", " analyses sélectionnées"),
    (" - Project : ", " - Projet : "),
    ("The project could not be saved:\n", "Le projet n'a pas pu être enregistré :\n"),
    ("The project « ", "Le projet « "),
    (" » has been saved in:\n", " » a été enregistré dans :\n"),
    (" » contains unsaved changes.\n\nSave it before continuing?", " » contient des modifications non enregistrées.\n\nL'enregistrer avant de continuer ?"),
    (" » contains unsaved changes.\nYour changes will be lost if you don't save them.",
     " » contient des modifications non enregistrées.\nVos modifications seront perdues si vous ne les enregistrez pas."),
    (" » is open.", " » est ouvert."),
    ("Location of the project « ", "Emplacement du projet « "),
    (" » has been created and saved in:\n", " » a été créé et enregistré dans :\n"),
    ("\n\nYou can now import the data (« Import data »), then create one or more analyses with the « Analysis » button (left vertical bar).",
     "\n\nVous pouvez maintenant importer les données (« Import data »), puis créer une ou plusieurs analyses avec le bouton « Analysis » (barre verticale gauche)."),
    ("The project file could not be read:\n", "Le fichier du projet n'a pas pu être lu :\n"),
    ("this file is not an ABOS project.", "ce fichier n'est pas un projet ABOS."),
    ("The data and results could not be read:\n", "Les données et les résultats n'ont pas pu être lus :\n"),
    ("The data file of the project was not found:\n", "Le fichier de données du projet est introuvable :\n"),
    ("Project « ", "Projet « "),
    (" » saved automatically (", " » enregistré automatiquement ("),
    (" » opened", " » ouvert"),
    (" » saved", " » enregistré"),
    ("Automatic save failed: ", "Échec de l'enregistrement automatique : "),
    ("The screenshot of the interface failed:\n", "La capture de l'interface a échoué :\n"),
    ("The screenshot has been saved:\n", "La capture a été enregistrée :\n"),
    ("The image could not be saved:\n", "L'image n'a pas pu être enregistrée :\n"),
    ("The export failed:\n", "L'export a échoué :\n"),
    ("The analyses have been exported to:\n", "Les analyses ont été exportées dans :\n"),
]

LANGUES_DISPONIBLES = {"en": "English", "fr": "French"}
langue_courante = "en"                     # langue par defaut au lancement (texte source du code)
_traducteur = {}


def _table_traduction ():
    """ Tables anglais -> francais (construites une fois). """
    if not _traducteur:
        _traducteur["exactes"] = dict(_TRADUCTIONS_EXACTES)
        _traducteur["fragments"] = dict(_TRADUCTIONS_FRAGMENTS)
        ## les fragments les plus longs sont essayes en premier
        _traducteur["motif"] = re.compile("|".join(re.escape(c) for c in sorted(_traducteur["fragments"], key = len, reverse = True)))
    return _traducteur


def traduire (texte, exact_seulement = False):
    """ texte dans la langue courante ; un texte inconnu est renvoye tel quel. """
    if langue_courante == "en" or not isinstance(texte, str) or texte == "":
        return texte
    table = _table_traduction()
    if texte in table["exactes"]:
        return table["exactes"][texte]
    if exact_seulement:
        return texte
    return table["motif"].sub(lambda m: table["fragments"][m.group(0)], texte)


def _envelopper_dialogue (fonction, cles_texte = ("title", "message", "prompt", "initialvalue"), positionnels = True):
    """ Boite de dialogue dont titre / message / invite sont traduits avant affichage. """
    if getattr(fonction, "_traduit", False):
        return fonction

    def enveloppe (*args, **kwargs):
        if positionnels:
            args = tuple(traduire(a) if isinstance(a, str) else a for a in args)
        for cle in cles_texte:
            if isinstance(kwargs.get(cle), str):
                kwargs[cle] = traduire(kwargs[cle])
        return fonction(*args, **kwargs)

    enveloppe.__name__ = getattr(fonction, "__name__", "dialogue")
    enveloppe._traduit = True
    return enveloppe


for _nom_fonction in ("showinfo", "showwarning", "showerror", "askquestion", "askokcancel",
                      "askyesno", "askyesnocancel", "askretrycancel"):
    setattr(messagebox, _nom_fonction, _envelopper_dialogue(getattr(messagebox, _nom_fonction)))
for _nom_fonction in ("askstring", "askinteger", "askfloat"):
    setattr(simpledialog, _nom_fonction, _envelopper_dialogue(getattr(simpledialog, _nom_fonction)))
for _nom_fonction in ("askopenfilename", "asksaveasfilename", "askopenfilenames", "askdirectory"):
    setattr(filedialog, _nom_fonction, _envelopper_dialogue(getattr(filedialog, _nom_fonction), ("title",), False))
colorchooser.askcolor = _envelopper_dialogue(colorchooser.askcolor, ("title",), False)
del _nom_fonction

## widgets dont le texte est traduit a la creation (texte d'origine conserve)
_WIDGETS_TRADUITS = ("label", "checkbutton", "button", "radiobutton", "ttk::label", "ttk::button",
                     "ttk::checkbutton", "ttk::radiobutton", "ttk::menubutton")
_label_configure_origine = tk.Label.configure


def _label_configure (self, cnf = None, **kw):
    """ Label dont le texte change (messages, resumes) : texte traduit. """
    if isinstance(cnf, dict) and isinstance(cnf.get("text"), str):
        cnf = dict(cnf)
        self._texte_origine = cnf["text"]
        cnf["text"] = traduire(cnf["text"])
    if isinstance(kw.get("text"), str):
        self._texte_origine = kw["text"]
        kw["text"] = traduire(kw["text"])
    return _label_configure_origine(self, cnf, **kw)


tk.Label.configure = tk.Label.config = _label_configure


def _retraduire_widgets (widget):
    """ Changement de langue : textes des widgets deja affiches retraduits. """
    try:
        enfants = widget.winfo_children()
    except tk.TclError:
        return
    for enfant in enfants:
        origine = getattr(enfant, "_texte_origine", None)
        if origine is not None:
            try:
                tk.Misc.configure(enfant, text = traduire(origine))
            except tk.TclError:
                pass
        _retraduire_widgets(enfant)


FICHIER_PREFERENCES = os.path.join(os.path.expanduser("~"), ".abos_preferences.json")


def appliquer_langue (code_langue):
    """ Change la langue des instructions et met a jour ce qui est affiche. """
    global langue_courante
    if code_langue not in LANGUES_DISPONIBLES:
        return
    langue_courante = code_langue
    _retraduire_widgets(SmartDigicat)
    try:
        _manuel_apres_changement_langue()      # manuel affiche : rouvert dans la nouvelle langue
    except Exception:
        pass
    try:
        rafraichir_boites()                    # etats des boites d'analyse
        _maj_titre_fenetre()
    except Exception:
        pass
    try:
        with open(FICHIER_PREFERENCES, "w", encoding = "utf-8") as fichier:
            json.dump({"langue": langue_courante}, fichier)   # langue conservee d'une session a l'autre
    except OSError:
        pass


try:                                           # langue choisie lors de la session precedente
    with open(FICHIER_PREFERENCES, encoding = "utf-8") as _fichier:
        _langue_lue = json.load(_fichier).get("langue")
    if _langue_lue in LANGUES_DISPONIBLES:
        langue_courante = _langue_lue
except (OSError, ValueError, AttributeError):
    pass


##------ Police (bouton « langue ») -------------------------------------------
## Comme dans SmartDigiCat : la police choisie (famille, taille du texte
## courant) s'applique a toute l'interface, y compris aux panneaux construits
## ensuite (interception de la creation des widgets). Les tailles d'origine
## sont mises a l'echelle : texte courant de reference = 13.
TAILLE_POLICE_REFERENCE = 13
police_famille_choisie = None      # None : polices d'origine (arial)
police_taille_choisie = TAILLE_POLICE_REFERENCE
_dialogue_langue = {"fenetre": None, "construction": False}
_NOMS_POLICES_NOMMEES = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                         "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")
_polices_nommees_origine = {}


def _police_modifiee ():
    return police_famille_choisie is not None or police_taille_choisie != TAILLE_POLICE_REFERENCE


def _police_transformee (origine):
    """ Police d'origine d'un widget -> police avec le choix courant (famille,
    taille proportionnelle ; gras et italique conserves). """
    if not _police_modifiee():
        return origine
    try:
        if str(origine) in tkfont.names(SmartDigicat):
            return origine                         # polices nommees : modifiees directement
        brut = [str(e) for e in SmartDigicat.tk.splitlist(SmartDigicat.tk.call("font", "actual", origine))]
        reel = {brut[i].lstrip("-"): brut[i + 1] for i in range(0, len(brut) - 1, 2)}
        taille = max(6, int(abs(int(float(reel["size"]))) * police_taille_choisie / TAILLE_POLICE_REFERENCE + 0.5))
        police = [police_famille_choisie or reel["family"], taille]
        if reel.get("weight") == "bold":
            police.append("bold")
        if reel.get("slant") == "italic":
            police.append("italic")
        return tuple(police)
    except Exception:
        return origine


_widget_init_sans_police = tk.Widget.__init__


def _widget_init_avec_police (self, master, widgetName, cnf = {}, kw = {}, extra = ()):
    ## widgets crees apres le choix : ils recoivent la police choisie des leur creation,
    ## et leur texte dans la langue choisie (texte d'origine conserve pour la retraduction)
    origine = None
    texte_origine = None
    if not _dialogue_langue["construction"] and widgetName in _WIDGETS_TRADUITS:
        for nom_dico in ("kw", "cnf"):
            dico = kw if nom_dico == "kw" else cnf
            if isinstance(dico, dict) and isinstance(dico.get("text"), str):
                texte_origine = dico["text"]
                dico = dict(dico, text = traduire(texte_origine))
                if nom_dico == "kw":
                    kw = dico
                else:
                    cnf = dico
                break
    if not _dialogue_langue["construction"]:
        for nom_dico in ("kw", "cnf"):
            dico = kw if nom_dico == "kw" else cnf
            if isinstance(dico, dict) and dico.get("font") is not None:
                origine = dico["font"]
                if _police_modifiee():
                    dico = dict(dico, font = _police_transformee(origine))
                    if nom_dico == "kw":
                        kw = dico
                    else:
                        cnf = dico
                break
    _widget_init_sans_police(self, master, widgetName, cnf, kw, extra)
    if origine is not None:
        self._police_origine = origine
    if texte_origine is not None:
        self._texte_origine = texte_origine


if not getattr(tk.Widget.__init__, "_police_patch", False):
    _widget_init_avec_police._police_patch = True
    tk.Widget.__init__ = _widget_init_avec_police


def _appliquer_police_partout (widget):
    try:
        enfants = widget.winfo_children()
    except tk.TclError:
        return
    for enfant in enfants:
        try:
            origine = getattr(enfant, "_police_origine", None)
            if origine is None and "font" in enfant.keys():
                courante = str(enfant.cget("font"))
                if courante not in tkfont.names(SmartDigicat):
                    origine = enfant._police_origine = courante
            if origine is not None:
                enfant.configure(font = _police_transformee(origine))
        except Exception:
            pass
        _appliquer_police_partout(enfant)


def appliquer_police (famille, taille):
    """ Police (None : polices d'origine) et taille du texte courant appliquees
    a toute l'application. """
    global police_famille_choisie, police_taille_choisie
    if not _polices_nommees_origine:
        for nom in _NOMS_POLICES_NOMMEES:
            try:
                reel = tkfont.nametofont(nom, root = SmartDigicat).actual()
                _polices_nommees_origine[nom] = (reel["family"], abs(int(reel["size"])))
            except Exception:
                pass
    police_famille_choisie, police_taille_choisie = famille, int(taille)
    for nom, (famille_origine, taille_origine) in _polices_nommees_origine.items():
        try:
            tkfont.nametofont(nom, root = SmartDigicat).configure(
                family = famille or famille_origine,
                size = max(6, int(taille_origine * police_taille_choisie / TAILLE_POLICE_REFERENCE + 0.5)))
        except Exception:
            pass
    _appliquer_police_partout(SmartDigicat)


def choisir_langue_instructions ():
    """ Bouton « langue » : langue des instructions, police et taille de police. """
    fenetre = _dialogue_langue["fenetre"]
    if fenetre is not None and fenetre.winfo_exists():
        fenetre.lift()
        fenetre.focus_force()
        return
    _dialogue_langue["construction"] = True       # la boite elle-meme ne suit pas la police choisie
    try:
        fenetre = tk.Toplevel(SmartDigicat)
        _dialogue_langue["fenetre"] = fenetre
        fenetre.title("Langue et police / Language and font")
        fenetre.resizable(False, False)
        fenetre.transient(SmartDigicat)
        ## textes bilingues : lisibles quelle que soit la langue active
        tk.Label(fenetre, text = "Langue et police\nLanguage and font", font = ('arial', 14, 'bold')).pack(padx = 30, pady = (18, 8))
        tk.Label(fenetre, text = "Votre langue préférée / Your preferred language", font = ('arial', 12)).pack(pady = (4, 4))
        codes = list(LANGUES_DISPONIBLES)
        liste_langues = ttk.Combobox(fenetre, values = [LANGUES_DISPONIBLES[c] for c in codes], state = "readonly", width = 34)
        liste_langues.current(codes.index(langue_courante))
        liste_langues.pack(padx = 30, pady = (0, 8))
        familles = sorted({f for f in tkfont.families(SmartDigicat) if not f.startswith("@")}, key = str.lower)
        choix_familles = [None] + familles
        tk.Label(fenetre, text = "Type de police / Font", font = ('arial', 12)).pack(pady = (4, 4))
        liste_polices = ttk.Combobox(fenetre, values = ["Par défaut / Default (arial)"] + familles, state = "readonly", width = 34, height = 15)
        liste_polices.current(choix_familles.index(police_famille_choisie) if police_famille_choisie in choix_familles else 0)
        liste_polices.pack(padx = 30, pady = (0, 8))
        tailles = list(range(8, 31))
        tk.Label(fenetre, text = "Taille de police / Font size", font = ('arial', 12)).pack(pady = (4, 4))
        liste_tailles = ttk.Combobox(fenetre, values = [str(t) + ("  (par défaut / default)" if t == TAILLE_POLICE_REFERENCE else "") for t in tailles],
                                     state = "readonly", width = 34, height = 15)
        liste_tailles.current(tailles.index(police_taille_choisie) if police_taille_choisie in tailles else tailles.index(TAILLE_POLICE_REFERENCE))
        liste_tailles.pack(padx = 30, pady = (0, 8))

        def par_defaut ():
            liste_polices.current(0)
            liste_tailles.current(tailles.index(TAILLE_POLICE_REFERENCE))

        def valider (event = None):
            code = codes[liste_langues.current()]
            famille, taille = choix_familles[liste_polices.current()], tailles[liste_tailles.current()]
            fenetre.destroy()                      # d'abord fermer la boite (elle ne suit ni la langue ni la police)
            appliquer_langue(code)                 # instructions dans la langue choisie
            appliquer_police(famille, taille)

        cadre = tk.Frame(fenetre)
        cadre.pack(pady = (12, 18))
        ttk.Button(cadre, text = "OK", command = valider).pack(side = LEFT, padx = 6)
        ttk.Button(cadre, text = "Police par défaut / Default font", command = par_defaut).pack(side = LEFT, padx = 6)
        ttk.Button(cadre, text = "Annuler / Cancel", command = fenetre.destroy).pack(side = LEFT, padx = 6)
        fenetre.bind("<Return>", valider)
        fenetre.bind("<Escape>", lambda event: fenetre.destroy())
        fenetre.update_idletasks()
        x = SmartDigicat.winfo_rootx() + (SmartDigicat.winfo_width() - fenetre.winfo_reqwidth()) // 2
        y = SmartDigicat.winfo_rooty() + (SmartDigicat.winfo_height() - fenetre.winfo_reqheight()) // 2
        fenetre.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
        fenetre.grab_set()
        fenetre.focus_force()
    finally:
        _dialogue_langue["construction"] = False


##=============================================================================
##  Manuel d'utilisation (bouton « Help ») : PDF affiche dans le panneau central
##  dans la langue choisie. Fichiers : ABOS/manuals/User_manual_AbosCluster_XX.pdf
##  (XX = FR, EN...). Si le manuel de la langue choisie manque, un autre manuel
##  disponible est affiche avec un avertissement. Rendu hors ligne (pypdfium2).
##=============================================================================
DOSSIER_MANUELS = os.path.join("ABOS", "manuals")
FICHIERS_MANUELS = {"fr": "User_manual_AbosCluster_FR.pdf", "en": "User_manual_AbosCluster_EN.pdf"}
_AVIS_MANUEL_ABSENT = {"en": "The English manual is not available yet: the French version is displayed.",
                       "fr": "The French manual is not available: the English version is displayed."}
_manuel_affiche = {"visionneuse": None}


def chemin_manuel (code_langue):
    """ (chemin, langue du manuel trouve) ; manuel de la langue demandee en
    priorite, sinon le premier manuel disponible ; (None, None) si aucun. """
    for code in [code_langue] + [c for c in FICHIERS_MANUELS if c != code_langue]:
        chemin = my_path(os.path.join(DOSSIER_MANUELS, FICHIERS_MANUELS[code]))
        if os.path.isfile(chemin):
            return chemin, code
    return None, None


def ouvrir_fichier_systeme (chemin):
    """ Ouvre un fichier avec l'application associee du systeme (lecteur PDF). """
    try:
        if sys.platform.startswith("win"):
            os.startfile(chemin)
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", chemin])
    except Exception as erreur:
        messagebox.showerror("User manual", "The file could not be opened:\n" + str(erreur))


def _sommaire_pdf (document):
    """ Signets du PDF : liste de (niveau, titre, indice de page) ; compatible
    pypdfium2 4.x (PdfOutlineItem) et 5.x (PdfBookmark). """
    entrees = []
    try:
        for signet in document.get_toc(max_depth = 3):
            niveau = getattr(signet, "level", 0)
            if hasattr(signet, "get_title"):
                titre = signet.get_title()
            else:
                titre = getattr(signet, "title", "")
            if hasattr(signet, "get_dest"):
                destination = signet.get_dest()
                indice = destination.get_index() if destination is not None else None
            else:
                indice = getattr(signet, "page_index", None)
            if titre and indice is not None and niveau <= 1:
                titre = titre.replace("``", "\u201c").replace("''", "\u201d").strip()   # guillemets LaTeX
                entrees.append((niveau, titre, int(indice)))
    except Exception:
        pass
    return entrees


class VisionneuseManuel:
    """ Visionneuse PDF : pages affichees les unes sous les autres dans un
    canevas defilant ; seules les pages visibles sont rendues (rapide meme
    pour un long manuel). Molette : defilement ; Ctrl + molette : zoom. """
    MARGE = 14                 # espace entre les pages (pixels)
    ZOOMS = (0.5, 0.67, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
    FOND = "gray55"

    def __init__ (self, parent, chemin, langue_manuel, page = 0):
        import pypdfium2 as pdfium
        from PIL import ImageTk
        self._ImageTk = ImageTk
        self.chemin, self.langue_manuel = chemin, langue_manuel
        self.document = pdfium.PdfDocument(chemin)
        self.n_pages = len(self.document)
        self.tailles = [self.document.get_page_size(i) for i in range(self.n_pages)]
        self.largeur_max = max(l for l, h in self.tailles)
        self.echelle, self.pleine_largeur = 1.0, True
        self.positions, self.hauteur_totale = [], 1
        self.images, self.objets = {}, {}          # page -> PhotoImage / objets du canevas
        self._taches = {"vue": None, "taille": None}
        self._page_initiale = page
        self.cadre = Frame(parent, background = self.FOND)
        self.cadre.place(relx = 0, rely = 0, relwidth = 1, relheight = 1)
        self._barre()
        self._zone()
        self.cadre.bind("<Destroy>", self._detruite, add = "+")

    ##------ construction ------------------------------------------------------
    def _barre (self):
        fond = "gray90"
        barre = Frame(self.cadre, background = fond)
        barre.pack(side = "top", fill = "x")
        police = ('arial', 12)
        Label(barre, text = "User manual", font = ('arial', 13, 'bold'), background = fond).pack(side = LEFT, padx = (12, 18), pady = 6)
        opt = dict(font = police, relief = FLAT, background = "white", activebackground = "gray80", cursor = "hand2", bd = 0, padx = 8)
        tk.Button(barre, text = "◀", command = lambda: self.aller_page(self.page_courante() - 1), **opt).pack(side = LEFT, padx = 2, pady = 6)
        self.var_page = StringVar(value = "1")
        self.champ_page = champ = Entry(barre, textvariable = self.var_page, width = 4, justify = "center", font = police)
        champ.pack(side = LEFT, padx = (4, 2))
        champ.bind("<Return>", self._page_saisie)
        champ.bind("<KP_Enter>", self._page_saisie)
        Label(barre, text = "/ %d" % self.n_pages, font = police, background = fond).pack(side = LEFT, padx = (0, 4))
        tk.Button(barre, text = "▶", command = lambda: self.aller_page(self.page_courante() + 1), **opt).pack(side = LEFT, padx = 2)
        Frame(barre, width = 18, background = fond).pack(side = LEFT)
        tk.Button(barre, text = "−", command = lambda: self.zoomer(-1), **opt).pack(side = LEFT, padx = 2)
        self.lab_zoom = tk.Label(barre, text = "100 %", width = 6, font = police, background = fond)
        self.lab_zoom.pack(side = LEFT)
        tk.Button(barre, text = "+", command = lambda: self.zoomer(1), **opt).pack(side = LEFT, padx = 2)
        tk.Button(barre, text = "Fit width", command = self.ajuster_largeur, **opt).pack(side = LEFT, padx = (8, 2))
        self.sommaire = _sommaire_pdf(self.document)
        if self.sommaire:
            Frame(barre, width = 18, background = fond).pack(side = LEFT)
            Label(barre, text = "Contents:", font = police, background = fond).pack(side = LEFT, padx = (0, 4))
            self.liste_sommaire = ttk.Combobox(barre, state = "readonly", width = 38, height = 20,
                                               values = [("      " * niveau) + titre for niveau, titre, _ in self.sommaire])
            self.liste_sommaire.pack(side = LEFT)
            self.liste_sommaire.bind("<<ComboboxSelected>>", self._section_choisie)
        tk.Button(barre, text = "Open in PDF reader", command = lambda: ouvrir_fichier_systeme(self.chemin), **opt).pack(side = tk.RIGHT, padx = 10)
        if self.langue_manuel != langue_courante and langue_courante in _AVIS_MANUEL_ABSENT:
            Label(self.cadre, text = _AVIS_MANUEL_ABSENT[langue_courante], font = ('arial', 11, 'italic'),
                  background = "lightyellow", fg = "gray20").pack(side = "top", fill = "x", ipady = 3)

    def _zone (self):
        zone = Frame(self.cadre, background = self.FOND)
        zone.pack(side = "top", fill = BOTH, expand = YES)
        self.toile = Canvas(zone, background = self.FOND, highlightthickness = 0, yscrollincrement = 40, xscrollincrement = 40)
        defil_y = ttk.Scrollbar(zone, orient = "vertical", command = self.toile.yview)
        defil_x = ttk.Scrollbar(zone, orient = "horizontal", command = self.toile.xview)

        def suivi_y (*args):
            defil_y.set(*args)
            self._planifier_vue()

        self.toile.configure(yscrollcommand = suivi_y, xscrollcommand = defil_x.set)
        self.toile.grid(row = 0, column = 0, sticky = "nsew")
        defil_y.grid(row = 0, column = 1, sticky = "ns")
        defil_x.grid(row = 1, column = 0, sticky = "ew")
        zone.grid_rowconfigure(0, weight = 1)
        zone.grid_columnconfigure(0, weight = 1)
        self.toile.bind("<Configure>", self._taille_changee)
        self.toile.bind("<Enter>", self._activer_molette)
        self.toile.bind("<Leave>", self._desactiver_molette)
        for touche, action in (("<Prior>", lambda e: self.toile.yview_scroll(-1, "pages")),
                               ("<Next>", lambda e: self.toile.yview_scroll(1, "pages")),
                               ("<Up>", lambda e: self.toile.yview_scroll(-1, "units")),
                               ("<Down>", lambda e: self.toile.yview_scroll(1, "units")),
                               ("<Home>", lambda e: self.aller_page(0)),
                               ("<End>", lambda e: self.aller_page(self.n_pages - 1))):
            self.toile.bind(touche, action)

    ##------ molette -----------------------------------------------------------
    def _activer_molette (self, event = None):
        self.toile.focus_set()
        self.toile.bind_all("<MouseWheel>", self._molette)
        self.toile.bind_all("<Button-4>", self._molette)
        self.toile.bind_all("<Button-5>", self._molette)

    def _desactiver_molette (self, event = None):
        for evenement in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.toile.unbind_all(evenement)
            except tk.TclError:
                pass

    def _molette (self, event):
        if getattr(event, "num", None) in (4, 5):
            sens = -1 if event.num == 4 else 1
        elif sys.platform == "darwin":
            sens = -1 if event.delta > 0 else 1
        else:
            sens = -max(1, abs(event.delta) // 120) if event.delta > 0 else max(1, abs(event.delta) // 120)
        if event.state & 0x0004:                   # Ctrl + molette : zoom
            self.zoomer(-1 if sens > 0 else 1)
        else:
            self.toile.yview_scroll(sens * 2, "units")
        return "break"

    ##------ mise en page ------------------------------------------------------
    def _taille_changee (self, event = None):
        if self._taches["taille"] is not None:
            self.toile.after_cancel(self._taches["taille"])
        self._taches["taille"] = self.toile.after(120, self._apres_redimension)

    def _apres_redimension (self):
        self._taches["taille"] = None
        if self.pleine_largeur or not self.positions:
            page, fraction = (self._page_initiale, 0.0) if not self.positions else self._position_lecture()
            self._mise_en_page(self._echelle_largeur() if self.pleine_largeur else self.echelle, page, fraction)
        else:
            self._centrer_pages()

    def _echelle_largeur (self):
        largeur = max(200, self.toile.winfo_width() - 2 * self.MARGE)
        return max(0.3, min(4.0, largeur / self.largeur_max))

    def _mise_en_page (self, echelle, page = None, fraction = 0.0):
        """ Dispose les pages (rectangles blancs) a l'echelle voulue puis
        affiche la page demandee ; les images sont rendues a la demande. """
        if page is None:
            page, fraction = self._position_lecture()
        self.echelle = echelle
        self.lab_zoom.configure(text = "%d %%" % round(echelle * 100))
        self.toile.delete("all")
        self.images.clear()
        self.objets.clear()
        y, self.positions = self.MARGE, []
        for largeur, hauteur in self.tailles:
            self.positions.append(y)
            y += int(hauteur * echelle) + self.MARGE
        self.hauteur_totale = y
        for i, (largeur, hauteur) in enumerate(self.tailles):
            l, h = int(largeur * echelle), int(hauteur * echelle)
            self.toile.create_rectangle(0, self.positions[i] + 3, l, self.positions[i] + h + 3, fill = "gray35", outline = "", tags = ("ombre", "p%d" % i))
            self.toile.create_rectangle(0, self.positions[i], l, self.positions[i] + h, fill = "white", outline = "gray40", tags = ("feuille", "p%d" % i))
        self._centrer_pages()
        self.aller_page(page, fraction)

    def _centrer_pages (self):
        largeur_toile = self.toile.winfo_width()
        largeur_pages = int(self.largeur_max * self.echelle) + 2 * self.MARGE
        largeur_region = max(largeur_toile, largeur_pages)
        for i, (largeur, hauteur) in enumerate(self.tailles):
            x = (largeur_region - int(largeur * self.echelle)) // 2
            x_actuel = self.toile.coords("feuille&&p%d" % i)
            if x_actuel:
                self.toile.move("p%d" % i, x - x_actuel[0], 0)
        self.toile.configure(scrollregion = (0, 0, largeur_region, self.hauteur_totale))
        self._planifier_vue()

    ##------ navigation --------------------------------------------------------
    def _position_lecture (self):
        """ (page, fraction) en haut de la vue : conservee lors d'un zoom. """
        if not self.positions:
            return 0, 0.0
        haut = self.toile.canvasy(0)
        page = self.page_au_point(haut)
        hauteur = self.tailles[page][1] * self.echelle
        return page, min(1.0, max(0.0, (haut - self.positions[page]) / max(1.0, hauteur)))

    def page_au_point (self, y):
        import bisect
        return max(0, min(self.n_pages - 1, bisect.bisect_right(self.positions, y + self.MARGE) - 1))

    def page_courante (self):
        if not self.positions:
            return 0
        return self.page_au_point(self.toile.canvasy(0) + self.toile.winfo_height() / 3)

    def aller_page (self, page, fraction = 0.0):
        if not self.positions:
            self._page_initiale = page
            return
        page = max(0, min(self.n_pages - 1, int(page)))
        y = self.positions[page] - (self.MARGE if fraction == 0 else 0) + fraction * self.tailles[page][1] * self.echelle
        self.toile.yview_moveto(max(0.0, y) / max(1, self.hauteur_totale))
        self._planifier_vue()

    def _page_saisie (self, event = None):
        try:
            self.aller_page(int(self.var_page.get()) - 1)
        except ValueError:
            pass
        self.toile.focus_set()

    def _section_choisie (self, event = None):
        i = self.liste_sommaire.current()
        if 0 <= i < len(self.sommaire):
            self.aller_page(self.sommaire[i][2])
        self.toile.focus_set()

    def zoomer (self, sens):
        actuel = self.echelle
        if sens > 0:
            suivants = [z for z in self.ZOOMS if z > actuel + 1e-3]
            nouveau = suivants[0] if suivants else self.ZOOMS[-1]
        else:
            precedents = [z for z in self.ZOOMS if z < actuel - 1e-3]
            nouveau = precedents[-1] if precedents else self.ZOOMS[0]
        self.pleine_largeur = False
        if abs(nouveau - actuel) > 1e-3:
            self._mise_en_page(nouveau)

    def ajuster_largeur (self):
        self.pleine_largeur = True
        self._mise_en_page(self._echelle_largeur())

    ##------ rendu des pages visibles -----------------------------------------
    def _planifier_vue (self):
        if self._taches["vue"] is None:
            self._taches["vue"] = self.toile.after(15, self._maj_vue)

    def _maj_vue (self):
        self._taches["vue"] = None
        if not self.positions or not self.toile.winfo_exists():
            return
        haut = self.toile.canvasy(0)
        bas = haut + self.toile.winfo_height()
        premiere, derniere = self.page_au_point(haut), self.page_au_point(bas)
        voulues = set(range(max(0, premiere - 1), min(self.n_pages, derniere + 2)))
        for i in [p for p in self.images if p not in voulues]:     # memoire limitee aux pages proches
            self.toile.delete(self.objets.pop(i))
            del self.images[i]
        manquantes = [p for p in range(premiere, derniere + 1) if p not in self.images] + \
                     [p for p in sorted(voulues) if p not in self.images]
        if manquantes:
            self._rendre(manquantes[0])
            self._planifier_vue()                  # page suivante au prochain tour (interface fluide)
        try:
            en_saisie = self.toile.focus_get() is self.champ_page
        except (KeyError, tk.TclError):
            en_saisie = False
        if not en_saisie:                          # numero de page affiche (sauf pendant la saisie)
            self.var_page.set(str(self.page_courante() + 1))

    def _rendre (self, i):
        page = self.document[i]
        try:
            image = page.render(scale = self.echelle).to_pil()
        finally:
            try:
                page.close()
            except Exception:
                pass
        photo = self._ImageTk.PhotoImage(image, master = self.toile)
        x = self.toile.coords("feuille&&p%d" % i)[0]
        self.images[i] = photo
        self.objets[i] = self.toile.create_image(x, self.positions[i], image = photo, anchor = "nw", tags = ("p%d" % i,))

    ##------ fermeture ---------------------------------------------------------
    def _detruite (self, event):
        if event.widget is not self.cadre:
            return
        self._desactiver_molette()
        self.images.clear()
        try:
            self.document.close()
        except Exception:
            pass
        if _manuel_affiche["visionneuse"] is self:
            _manuel_affiche["visionneuse"] = None


def afficher_manuel (parent, page = 0):
    """ Bouton « Help » : manuel d'utilisation dans le panneau central, dans
    la langue choisie (bouton « langue »). """
    panneau = nouveau_panneau(parent)
    chemin, langue_manuel = chemin_manuel(langue_courante)
    if chemin is None:
        Label(panneau, text = "The user manual could not be found.", font = ('arial', 14), background = "white",
              fg = "gray20").place(relx = 0.5, rely = 0.45, anchor = "center")
        return
    try:
        _manuel_affiche["visionneuse"] = VisionneuseManuel(panneau, chemin, langue_manuel, page)
    except Exception as erreur:
        for enfant in panneau.winfo_children():
            enfant.destroy()
        Label(panneau, text = "The user manual could not be displayed.", font = ('arial', 14), background = "white",
              fg = "gray20").place(relx = 0.5, rely = 0.42, anchor = "center")
        Label(panneau, text = str(erreur), font = ('arial', 10), background = "white", fg = "gray40",
              wraplength = 700).place(relx = 0.5, rely = 0.50, anchor = "center")
        tk.Button(panneau, text = "Open in PDF reader", command = lambda: ouvrir_fichier_systeme(chemin),
                  font = ('arial', 12)).place(relx = 0.5, rely = 0.58, anchor = "center")


def _manuel_apres_changement_langue ():
    """ Manuel affiche : rouvert dans la nouvelle langue (meme page si le
    fichier ne change pas). """
    visionneuse = _manuel_affiche["visionneuse"]
    if visionneuse is None:
        return
    try:
        if not visionneuse.cadre.winfo_exists():
            return
        chemin, _ = chemin_manuel(langue_courante)
        page = visionneuse.page_courante() if chemin == visionneuse.chemin else 0
        afficher_manuel(Center_frame, page)
    except Exception:
        pass


col_bar = "gray80"   ##"#A1BCB3"

##------ Barre horizontale haute
top_frame = Canvas(SmartDigicat, width= 500 , height = 70, bg=col_bar, highlightthickness=0)

##------ Barre horizontale basse
bottom_frame = Label(SmartDigicat, text= "Biological Atlas of Severe Obesity" , fg="white", bg = col_bar)

##------ Barre verticale gauche
left_frame = Canvas(SmartDigicat, width= 50, bg='gray20', highlightthickness=0, relief=GROOVE)

##------ Barre verticale droite
right_frame = Canvas(SmartDigicat, width= 50, bg='gray20', highlightthickness=0, relief = GROOVE)


##------ Panneau central
Center_frame = Canvas(SmartDigicat, highlightthickness=0, background= 'white' , relief = GROOVE)

##print(Center_frame.winfo_children())




##------ Menus horizontals haut

button_New = Button(top_frame, image = New, text='New', repeatdelay = 0, borderwidth = 0 , compound = tk.LEFT, borderless = True, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, bordercolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Open = Button(top_frame, image = Open , text='Open' , borderwidth = 0 , compound = tk.LEFT, relief=FLAT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Save = Button(top_frame, image = Save , text='Save' , borderwidth = 0, compound = tk.LEFT, relief=FLAT, borderless = True, bordercolor = 'red', background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Undo = Button(top_frame, image = Undo, text= 'Undo',  borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Redo = Button(top_frame, image = Redo, text= 'Redo',  borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Model = Button(top_frame, image = Model, text= 'Model', borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Run = Button(top_frame, image = Run, text='Run' , borderwidth = 0, compound = tk.LEFT, relief=FLAT, borderless = True, bordercolor = 'red', background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_data = Button(top_frame, image = data_import, text = 'Import data' , compound = tk.LEFT,  borderwidth = 0, relief = FLAT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)

button_data_Edit = Button(top_frame, image = my_data_edit_p, text = 'Edit data' , compound = tk.LEFT,  borderwidth = 0, relief = FLAT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)


button_Results = Button(top_frame, image = Results, text= 'Plots', borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Log = Button(top_frame, image = Log, text= 'Log', borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Help = Button(top_frame, image = Help, text= 'Help', borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)
button_Website = Button(top_frame, image = Website, text= 'Website', width= 1, borderwidth = 0, compound = tk.LEFT, borderless = True, bordercolor = col_bar, background= col_bar, disabledforeground = col_bar, focuscolor = col_bar, highlightcolor = col_bar, highlightbackground= col_bar)



##------ Menus verticals de gauche
button_Analysis = Button(left_frame, image = Analysis, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Delete = Button(left_frame, image = Delete, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Restore = Button(left_frame, image = Restore,  borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Picture_save = Button(left_frame, image = Picture_save, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Csv_import = Button(left_frame, image = Csv_import ,  borderwidth = 0, relief = FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Settings = Button(left_frame, image = Settings,  borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Rename = Button(left_frame, image = Rename_model, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
## bouton d'arret : actif seulement pendant « Run »
button_arret_model = Button(left_frame, image = arret, command = demander_arret_execution, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
## barre verticale droite : creation d'une boite de comparaison de modeles
button_Comparison = Button(right_frame, image = Analysis, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Delete_c = Button(right_frame, image = Delete, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Rename_c = Button(right_frame, image = Rename_model, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Settings_c = Button(right_frame, image = Settings, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_Restore_c = Button(right_frame, image = Restore, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')
button_langue = Button(left_frame, image = langue, command = choisir_langue_instructions, borderwidth = 0, relief=FLAT, borderless = True, bordercolor = 'gray20', background= 'gray20', disabledforeground = 'gray20', focuscolor = 'gray20', highlightcolor = 'gray20', highlightbackground= 'gray20')



scale = Scale(left_frame, from_= 100, to= 0, sliderrelief= "ridge" , showvalue= False,  borderwidth= 0 , bg='cornflowerblue', activebackground= 'cornflowerblue', width= 35 , length= 200, troughcolor = 'gray80')


button_New.place(x = 5, y = 4, width = 70)
button_Open.place(x = 80 , y = 4, width =70)
button_Save.place(x = 155, y = 4, width =70)
button_Undo.place(x = 230, y = 4, width =70)
button_Redo.place(x = 305, y = 4, width = 70)
button_data.place(relx = 0.36, y = 4, width = 110)
button_data_Edit.place(relx = 0.458, y = 4, width = 100)
button_Results.place(relx = 0.548 , y = 4, width = 85)
button_Model.place(relx = 0.626 , y = 4, width = 80)
button_Run.place(relx = 0.70 , y = 4, width = 70)
button_Log.place(relx = 0.766 , y = 4, width = 85)
button_Help.place(relx = 0.844, y = 4, width = 70)
button_Website.pack(side = tk.RIGHT, fill = tk.NONE,  ipadx = 45, padx= 5)



## meme ordre que dans SmartDigiCat
button_Analysis.place(x = 5, y = 5, width= 40, height= 40)
button_Delete.place(x = 5, y = 60, width= 40, height= 40)
button_Rename.place(x = 5, y = 115, width= 40, height= 40)
button_Settings.place(x = 5, y = 165, width= 40, height= 40)
button_Restore.place(x = 5, y = 220, width= 40, height= 40)
button_arret_model.place(x = 5, y = 275, width= 40, height= 40)
button_Picture_save.place(x = 5, y = 330, width= 40, height= 40)
button_Csv_import.place(x = 5, y = 385, width= 40, height= 40)
button_langue.place(x = 5, y = 440, width= 40, height= 40)
button_Comparison.place(x = 5, y = 5, width= 40, height= 40)
## memes positions que les boutons qui suivent « Analysis » sur la barre gauche
button_Delete_c.place(x = 5, y = 60, width= 40, height= 40)
button_Rename_c.place(x = 5, y = 115, width= 40, height= 40)
button_Settings_c.place(x = 5, y = 165, width= 40, height= 40)
button_Restore_c.place(x = 5, y = 220, width= 40, height= 40)
##button_data.place(x = 5, y = 275, width= 40, height= 40)
scale.pack(side= BOTTOM, fill= BOTH, padx= 5)
scale.set(ZOOM_NEUTRE)
scale.configure(command = zoomer_graphique)        # zoom du graphique selectionne


top_frame.pack(side="top", fill='x', ipady= 4)
bottom_frame.pack(side="bottom", fill='x')
left_frame.pack(side="left", fill='y')
right_frame.pack(side="right", fill='y')
## barre de zoom propre aux boites de comparaison (meme aspect que celle de gauche)
scale_comparaisons = Scale(right_frame, from_= 100, to= 0, sliderrelief= "ridge" , showvalue= False,  borderwidth= 0 , bg='cornflowerblue', activebackground= 'cornflowerblue', width= 35 , length= 200, troughcolor = 'gray80')
scale_comparaisons.pack(side= BOTTOM, fill= BOTH, padx= 5)
scale_comparaisons.set(int((taille_comparaisons - TAILLE_BOITE_MIN) / (TAILLE_BOITE_MAX - TAILLE_BOITE_MIN) * 100))
scale_comparaisons.configure(command = zoomer_comparaisons)
Center_frame.pack(side= 'top', fill= BOTH, expand= YES)

img_smatdigicat_ = img_smatdigicat.zoom(3, 3)
can = Canvas(Center_frame, highlightthickness=0, background= 'white')
icone_centrale = can.create_image(0, 0, anchor = 'center' , image = img_smatdigicat_)
can.place(relx = 0, rely = 0, relwidth = 1, relheight = 1)


##welcome = Label(Center_frame, text="Welcome to  SmartDigicat \n \n  Your catalytic screening software", font=('Helvetica 16 bold italic'), fg = "gray20", background= "white")

##welcome = Label(Center_frame, text="SmartDigicat", font=('Helvetica 30 bold italic'), fg = "gray20", background= "white")
##------ Blocs auteurs et contacts (séparés, alignés ligne à ligne)
auteurs = [
    ("Komlan Noukpoape", "komlan-midodzi.noukpoape@inria.fr"),
    ("Cristian Preda",   "cristian.preda@inria.fr"),
]

style = dict(font=('arial', 15), fg="dimgray", background="white", anchor="w")
style_titre = dict(font=('arial', 15, 'bold'), fg="dimgray", background="white", anchor="w")

## Bloc de gauche : auteurs
frame_auteurs = Frame(Center_frame, background="white")
Label(frame_auteurs, text="Authors:", **style_titre).grid(row=0, column=0, sticky="w", pady=(0, 10))

## Bloc de droite : contacts
frame_contacts = Frame(Center_frame, background="white")
Label(frame_contacts, text="Contact:", **style_titre).grid(row=0, column=0, sticky="w", pady=(0, 10))

for i, (nom, mail) in enumerate(auteurs, start=1):
    Label(frame_auteurs, text=f"{i}. {nom}", **style).grid(row=i, column=0, sticky="w", pady=5)
    Label(frame_contacts, text=f"{i}. {mail}", **style).grid(row=i, column=0, sticky="w", pady=5)

## Positions relatives des blocs (modifiables ici)
REL_X_AUTEURS = 0.08
REL_X_CONTACTS = 0.7
REL_Y_BLOCS = 0.72

frame_auteurs.place(relx=REL_X_AUTEURS, rely=REL_Y_BLOCS, anchor="nw")
frame_contacts.place(relx=REL_X_CONTACTS, rely=REL_Y_BLOCS, anchor="nw")


##------ Icône centrale : se recentre sur les blocs auteurs/contacts
def placer_icone(event=None):
    largeur = Center_frame.winfo_width()
    hauteur = Center_frame.winfo_height()
    ## Bord gauche du bloc auteurs et bord droit du bloc contacts
    gauche = REL_X_AUTEURS * largeur
    droite = REL_X_CONTACTS * largeur + frame_contacts.winfo_reqwidth()
    ## Centre horizontal entre les deux blocs, centre vertical de l'espace au-dessus
    x = (gauche + droite) / 2
    y = (REL_Y_BLOCS * hauteur) / 2
    can.coords(icone_centrale, x, y)

Center_frame.bind("<Configure>", placer_icone)


##------ Actions des boutons de donnees
## toutes les analyses se font dans un projet (dans_projet) ; certaines exigent les donnees
button_data.configure(command = dans_projet(lambda: import_data(Center_frame)))
button_data_Edit.configure(command = dans_projet(lambda: edit_data(Center_frame), donnees = True))
button_Analysis.configure(command = dans_projet(lambda: nouvelle_analyse(Center_frame), donnees = True))
button_Comparison.configure(command = dans_projet(lambda: nouvelle_comparaison(Center_frame), donnees = True))
button_Delete_c.configure(command = dans_projet(lambda: supprimer_comparaison(Center_frame), donnees = True))
button_Rename_c.configure(command = dans_projet(lambda: renommer_comparaison(Center_frame), donnees = True))
button_Settings_c.configure(command = dans_projet(lambda: parametres_comparaison(Center_frame), donnees = True))
button_Restore_c.configure(command = dans_projet(lambda: corbeille_comparaison(Center_frame), donnees = True))
button_Delete.configure(command = dans_projet(lambda: supprimer_boite(Center_frame), donnees = True))
button_Restore.configure(command = dans_projet(lambda: corbeille(Center_frame), donnees = True))
button_Settings.configure(command = dans_projet(lambda: ouvrir_parametres_boite(Center_frame), donnees = True))
button_Rename.configure(command = dans_projet(lambda: renommer_boite(Center_frame), donnees = True))
button_Picture_save.configure(command = dans_projet(capturer_interface_courante))
button_Csv_import.configure(command = dans_projet(exporter_analyses_csv, donnees = True))
button_Run.configure(command = dans_projet(lambda: executer_boite(Center_frame), donnees = True))
button_Model.configure(command = dans_projet(lambda: afficher_boites(Center_frame), donnees = True))   # panneau Clustering (boites creees)
button_Results.configure(command = dans_projet(lambda: plots(Center_frame), donnees = True))
button_Log.configure(command = dans_projet(lambda: afficher_log(Center_frame), donnees = True))       # resultats des analyses executees
## projets et historique (comme dans SmartDigiCat)
button_New.configure(command = nouveau_projet)
button_Open.configure(command = ouvrir_projet)
button_Save.configure(command = dans_projet(save_current_project, donnees = True))
button_Undo.configure(command = annuler_derniere_action)
button_Redo.configure(command = refaire_derniere_action)
button_Help.configure(command = lambda: afficher_manuel(Center_frame))     # manuel dans le panneau central
URL_SITE = "https://clinicaltrials.gov/study/NCT01129297"
button_Website.configure(command = lambda: __import__("webbrowser").open(URL_SITE, new = 2))   # page de l'etude


## boutons desactives (icone grisee) tant qu'aucun projet n'est ouvert
## Meme principe que SmartDigiCat : les boutons d'analyse (barre du haut et
## barre verticale gauche) ne sont actifs que si un projet est ouvert ET que des
## donnees ont ete importees ; Undo / Redo en plus seulement s'il y a une action
## a annuler / refaire ; le bouton d'arret seulement pendant « Run » ; « Import
## data » des qu'un projet est cree ou ouvert. Restent toujours actifs : New,
## Open, Help, Website, capture de l'interface et langue.
_boutons_lies_au_projet = [
    ## barre verticale gauche
    (button_Analysis, Analysis, _icone_grisee('ABOS/new_analysis.png'), "analyse"),
    (button_Comparison, Analysis, _icone_grisee('ABOS/new_analysis.png'), "analyse"),
    (button_Delete_c, Delete, _icone_grisee('ABOS/delete.png'), "analyse"),
    (button_Rename_c, Rename_model, _icone_grisee('ABOS/Rename_model.png'), "analyse"),
    (button_Settings_c, Settings, _icone_grisee('ABOS/settings.png'), "analyse"),
    (button_Restore_c, Restore, _icone_grisee('ABOS/restore.png'), "analyse"),
    (button_Delete, Delete, _icone_grisee('ABOS/delete.png'), "analyse"),
    (button_Rename, Rename_model, _icone_grisee('ABOS/Rename_model.png'), "analyse"),
    (button_Settings, Settings, _icone_grisee('ABOS/settings.png'), "analyse"),
    (button_Restore, Restore, _icone_grisee('ABOS/restore.png'), "analyse"),
    (button_Csv_import, Csv_import, _icone_grisee('ABOS/csv_import.png'), "analyse"),
    (button_arret_model, arret, _icone_grisee('ABOS/arret.png'), "execution"),
    ## barre horizontale haute
    (button_data, data_import, _icone_grisee('ABOS/import_p.png'), "projet"),     # projet cree ou ouvert
    (button_Undo, Undo, _icone_grisee('ABOS/undo_p.png'), "undo"),
    (button_Redo, Redo, _icone_grisee('ABOS/redo_p.png'), "redo"),
    (button_Model, Model, _icone_grisee('ABOS/model_p.png'), "analyse"),
    (button_Run, Run, _icone_grisee('ABOS/run_p.png'), "analyse"),
    (button_data_Edit, my_data_edit_p, _icone_grisee('ABOS/settings_p-32.png'), "analyse"),
    (button_Log, Log, _icone_grisee('ABOS/log_p.png'), "analyse"),
    (button_Results, Results, _icone_grisee('ABOS/results_p.png'), "analyse"),
    (button_Save, Save, _icone_grisee('ABOS/save_p.png'), "analyse"),
]
for _bouton, _icone, _grisee, _condition in _boutons_lies_au_projet:
    try:                               # fond inchange et texte lisible a l'etat desactive (tkmacosx)
        _bouton.configure(disabledbackground = col_bar if _bouton.master is top_frame else "gray20",
                          disabledforeground = "gray55")
    except tk.TclError:
        pass
maj_etat_boutons_projet()
installer_fermeture_propre()
SmartDigicat.after(INTERVALLE_AUTOSAVE_MS, autosave_projet)    # enregistrement automatique toutes les 5 minutes

SmartDigicat.mainloop()