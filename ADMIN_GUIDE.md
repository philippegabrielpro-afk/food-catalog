# Food Catalog 0.2.0 — interface d’administration

Cet incrément concerne uniquement Food Catalog. Il ne modifie ni Diablotin,
ni son déploiement, ni ses repas et corrections personnelles.

## Installer et tester en local

Appliquer le paquet depuis la racine du dépôt Food Catalog, dans une branche
de travail, après avoir vérifié que `git status --short` est vide. Le paquet ne
contient ni `.env`, ni base de données, ni données alimentaires modifiées.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

Résultat attendu : 36 tests réussis. Les deux avertissements de dépendances
de test déjà présents ne signalent pas un échec de l’interface.

Pour le premier essai visuel, utiliser une base dédiée plutôt que modifier
la base locale existante. Arrêter au préalable le serveur local avec Ctrl+C.
Dans un nouveau terminal, à la racine de Food Catalog :

```powershell
$env:FOOD_CATALOG_DATABASE_URL = "sqlite:///./food-catalog-admin-test.db"
$env:FOOD_CATALOG_AUTO_IMPORT_CIQUAL = "true"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8080
```

L’adresse est `http://127.0.0.1:8080/admin`. Le premier démarrage importe les
3 484 aliments officiels dans cette base de test. Connexion avec la valeur
`FOOD_CATALOG_ADMIN_API_KEY` de votre `.env`, pas la clé consommateur.
Ne pas recopier cette clé dans une conversation, une capture ou un commit.
La base de test est ignorée par la règle `*.db` existante.

Ces variables ne s’appliquent qu’au terminal courant. Après les essais,
arrêter le serveur et fermer ce terminal pour retrouver la configuration
habituelle au prochain lancement. Ne pas réutiliser ces variables pour un
déploiement.

## Parcours d’acceptation

1. Une mauvaise clé doit être refusée. La clé consommateur aussi.
2. Le catalogue affiche 3 484 aliments. Les boutons paginent la liste.
3. Chercher « riz basmati cuit » ; ouvrir la fiche de code Ciqual 9125.
   Vérifier 32,9 g/100 g, la version 2025-11-03 et le lien de provenance.
4. Ajouter un synonyme générique et un tag, enregistrer après confirmation.
   La valeur et le nombre de références ne changent pas. Rechercher ce synonyme.
5. Ajouter une nouvelle valeur générique : source `manual`, version `test-1`,
   30 g/100 g, puis confirmer. Les deux références doivent rester visibles.
6. Essayer une autre valeur sous la même source, le même code et la même
   version : refus 409. Il faut une version distincte, pas écraser l’ancienne.
7. Utiliser la référence Ciqual par défaut. La correction manuelle reste dans
   l’historique. Aucune référence Ciqual n’est réécrite.
8. Créer un aliment générique de test, avec synonymes et tags. Vérifier sa
   recherche et son historique. Ne pas saisir de données personnelles.
9. Lancer l’import Ciqual fourni après confirmation. Il indique « déjà importé »
   et ne crée pas de doublons. L’historique expose version, date et SHA-256.
10. Vérifier le journal global et celui de la fiche : actions et données avant /
    après, sans clé. Seules les actions depuis cette mise à jour sont présentes.
11. Recharger la page : la connexion doit être perdue. Vérifier aussi la
    déconnexion explicite, puis l’affichage sur un écran mobile.
12. Annuler les confirmations : aucune écriture ne doit être faite.

Les tests Python couvrent l’API, la séparation des clés, l’intégrité des versions,
les collisions, la migration, le journal transactionnel et le catalogue complet.
La syntaxe JavaScript a été vérifiée avec Node. Un parcours supplémentaire en
DOM simulé, relié à un véritable serveur HTTP local, a validé connexion,
recherche, édition, ajout de version, retour à Ciqual, création, imports,
journal, absence de stockage de la clé et déconnexion. Ce contrôle n’est pas
une vérification du rendu : la validation visuelle dans un vrai navigateur
reste à effectuer avant toute release.

## Limites assumées

- Interface pilote à clé d’administration partagée : pas de comptes utilisateurs.
- Journal applicatif non inviolable, sans identité individuelle et sans reprise
  de l’historique antérieur. Pas de suppression d’aliment dans cette interface.
- Édition simultanée des libellés : la dernière écriture gagne ; pas de verrou
  optimiste dans ce pilote. Les versions nutritionnelles restent uniques.
- Pas de récupération automatique d’une nouvelle édition Ciqual, de fichier
  libre, de fichier audio ou de données médicales.
- Le service ne reçoit pas les quantités consommées, repas ou valeurs
  glucidiques personnalisées de Diablotin. Une correction générique du catalogue
  n’est pas une correction personnelle liée à un patient.
- Pas de mise en production ni de fusion déclenchée par ce paquet. Comptes,
  permissions, clés par client, sauvegardes, monitoring et limitation de débit
  devront être traités avant exposition commerciale.
