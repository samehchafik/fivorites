"""Acquisition de données pour Fivorites V2.

Le pipeline sépare strictement deux choses que la V1 confondait :

  collecte    → écrit du brut horodaté dans `raw_source`, sans jamais l'interpréter
  dérivation  → relit `raw_source` et produit les couches métier, hors ligne

Conséquence pratique : changer un champ dérivé ne coûte plus une requête HTTP.
"""

__version__ = "0.1.0"
