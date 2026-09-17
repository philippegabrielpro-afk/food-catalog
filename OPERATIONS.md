# Food Catalog — réseau et sauvegardes

## Portée

Correctif pour le déploiement initial de Food Catalog v0.2.0. Le numéro de
version de l’API et le tag v0.2.0 existant ne sont pas modifiés par ce paquet.
Une nouvelle release sera préparée après les contrôles Git/CI. Aucun fichier
Diablotin, secret existant ou volume PostgreSQL n’est modifié par ce paquet.

## Vérifications avant déploiement

Depuis la branche `fix/catalog-network-backups` du dépôt Food Catalog :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

Résultat attendu sous Windows : **40 passed, 18 skipped**. Les 18 tests shell
sont volontairement réservés à Linux et doivent passer dans la CI. Les deux
avertissements de dépendances de test existants ne sont pas des échecs.
Dans l’environnement de préparation Linux : **58 passed**. Le test Docker réel
n’a pas pu y être exécuté faute de Docker ; il doit être vert dans GitHub Actions
avant de déployer. Ne pas confondre ces tests simulés du script avec une
restauration PostgreSQL réellement exécutée.

La CI ajoute la vérification du port publié sur localhost et d’une restauration
isolée avec PostgreSQL 17. Elle crée ses propres secrets et ressources ; elle
n’utilise ni le `.env` du VPS ni son volume. Docker Compose 2.24.4+ est requis
pour ce contrôle. Ne pas lancer `scripts/verify-compose.py` sur le VPS.

## Réseau attendu

- API : `private` et `access`, port **127.0.0.1:8080** uniquement.
- Base et sauvegarde : `private` uniquement, aucun port publié.
- Aucun réseau, port ni volume de Diablotin.
- Le volume reste `food-catalog_catalog_postgres_data` avec le projet Compose
  **food-catalog**. Changer le nom du projet ferait utiliser une autre base.

Le `docker-compose.override.yml` ajouté pendant le diagnostic du VPS reste
compatible avec ce correctif, mais devient redondant pour le réseau. Lors du
déploiement, utiliser explicitement le fichier Compose versionné et ne pas
supprimer ce fichier d’override avant d’avoir vérifié le résultat. Ne pas lancer
`down`, `down -v`, une purge Docker ou un redémarrage global du daemon.

## Sauvegarde

Le dossier déjà créé sur le VPS est `/home/ubuntu/food-catalog-backups`,
propriétaire `ubuntu:ubuntu` (UID/GID 1000), mode `700`. Les fichiers validés sont
mode `600`. Les paramètres de chemin et UID/GID peuvent être changés via `.env`.
Le dossier et les scripts montés doivent exister, Docker ne les crée pas.

Le conteneur sauvegarde une première fois après le démarrage sain de l’API,
puis attend 24 heures après chaque réussite. Un redémarrage déclenche une
nouvelle sauvegarde. Il n’y a **aucune purge des archives complètes**, même
anciennes. Seuls les fichiers temporaires créés par une tentative en échec sont
supprimés. Une erreur n’écrase ni un ancien dump ni le marqueur de réussite.
Un nom aléatoire évite de remplacer une sauvegarde du même horodatage.

Une erreur de dump/lecture fait échouer le processus ; elle apparaît dans les
logs et Docker le relance selon `unless-stopped`. Une réussite ancienne de plus
de 26 heures rend le service `unhealthy`. Ce statut ne déclenche pas à lui seul
une alerte externe ni un redémarrage. La santé doit être surveillée.

Après le déploiement contrôlé, commandes de lecture :

```bash
cd /home/ubuntu/food-catalog
sudo docker compose -p food-catalog --env-file .env -f docker-compose.yml ps
sudo docker compose -p food-catalog --env-file .env -f docker-compose.yml logs --tail=30 backup
```

Le premier log doit comporter `BACKUP_OK=food-catalog-...dump`. Une archive
lisible ne garantit pas à elle seule la récupération : la CI restaure dans une
base séparée, et la procédure de reprise du VPS devra aussi être testée.

Ces dumps ne contiennent pas les clés, `.env` et la configuration SSH. Ceux-ci
doivent être conservés séparément et de façon sécurisée, jamais dans Git.
Une sauvegarde sur le même VPS ne protège pas contre sa destruction ou la
perte du disque. La copie hors VPS et la politique de rétention restent à définir.

## Étape de déploiement restante

Le paquet ne modifie pas le VPS et n’active pas encore le conteneur de sauvegarde.
Il faut d’abord commit/push, contrôles CI, fusion, puis préparer une nouvelle
release. Transférer ensuite les fichiers validés, conserver le `.env` existant,
vérifier les identifiants des conteneurs et le volume, et démarrer seulement
`backup` avec `--no-deps --no-build`. L’API peut rester sur son image v0.2.0
durant cette étape : le changement réseau est déjà actif sur ce VPS. Vérifier
une sauvegarde, l’accès localhost et le maintien des conteneurs Diablotin avant
toute ouverture ou intégration externe. Ces commandes seront données au moment
du déploiement pour ne pas confondre le poste Windows et le serveur.
