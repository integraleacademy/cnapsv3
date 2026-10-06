# Contrôle indicatif des documents

Configurer `OPENAI_API_KEY` dans Render. La clé reste uniquement côté serveur.
Le modèle par défaut est `gpt-4.1` ; `OPENAI_DOCUMENT_MODEL` peut sélectionner un modèle
compatible avec les images, Responses et les sorties JSON structurées.

À la sélection, le formulaire et la page de remplacement transmettent à OpenAI les fichiers
concernés : photo, identité du candidat/de l’hébergeant, domicile et attestation d’hébergement.
Le texte d’information précède le dépôt. Les résultats sont indicatifs, ne bloquent pas l’envoi
et ne modifient jamais la conformité enregistrée par l’administration.

## Analyse visuelle

Les PDF sont rendus en pixels : la couche de texte invisible ne peut pas prouver la lisibilité.
Chaque page d’identité est analysée séparément, avec sa vue entière et quatre détails qui
se chevauchent. Aucun filtre de netteté ne reconstruit les caractères. Les contrôles portent
sur les contours du texte, tous les champs, les bords/coins, les reflets et les masquages.
Un défaut produit une alerte ; une incertitude ne peut pas donner un résultat positif.
Un budget de 25 secondes couvre l’ensemble des pages. Une page problématique suffit à arrêter
le contrôle avec une alerte. Les appels sont réservés dans le quota avant l’analyse.

La réponse fournit seulement le type de pièce et les faces observées, sans nom, numéro ni
comparaison de visage. Le navigateur combine ces observations sur tous les fichiers sélectionnés :
carte d’identité/titre de séjour = recto ET verso du même type ; passeport = page avec photo.
Deux rectos ne remplacent pas un verso. Il est possible de déposer un PDF regroupé ou deux PDF.
Sur la page de remplacement, les anciens documents conservés ne sont pas réanalysés : un rappel
sur le dossier existant évite de présenter une face déjà transmise comme manquante.

La photo est contrôlée selon les critères visibles et reçoit un message positif court.
Le modèle compte les occurrences de portraits dans l'image entière, y compris les copies du
même visage, et identifie séparément les planches et montages. Le serveur exige explicitement
un seul portrait et une photo individuelle isolée avant tout résultat positif. Une planche
avec des cases vides reste une planche, même si un seul portrait subsiste. Ces observations
priment sur une liste de critères photographiques éventuellement positive ; un doute ne peut
pas produire de voyant vert. Le résultat positif porte la version de ce contrôle.
Les anciens résultats positifs de photos, y compris les reçus encore en circulation, sont
présentés comme non concluants : ils n'établissaient pas l'absence de planche. L'historique
en base et les décisions humaines de conformité restent inchangés.
L’attestation est examinée pour la présence visuelle de la signature de l’hébergeant ; cette
observation ne certifie pas l’authenticité de la signature.

## Domicile — règles du formulaire

Sont admis, à condition de dater de moins de trois mois : eau, gaz, électricité, gaz/électricité,
quittance de loyer, téléphone fixe seul, ainsi que les attestations de fournisseur d’énergie
(déjà prises en charge, notamment ENGIE). Mobile, Internet/fibre/ADSL/box et les offres groupées
Internet + fixe sont refusés. Le fournisseur ou la présence d’un numéro fixe ne suffit pas à
identifier un abonnement fixe seul. Un type incertain ne peut pas donner un résultat positif.
La date extraite est comparée à trois mois calendaires côté serveur (date française).
Une attestation « en date du X, depuis Y » utilise X, pas le début de contrat Y.

## Dépôt et sécurité

Tous les fichiers sélectionnés peuvent être remplacés avant l’envoi, même après un résultat
positif, pendant l’analyse ou après avoir cliqué sur Conserver. Le remplacement d’une face
conserve les autres fichiers ; annuler la sélection conserve l’ancien document.

Le serveur utilise Responses avec `store=false`, sans Files API. Aucun fichier n’est conservé
par cette vérification. Le dépôt habituel n’enregistre les documents qu’à l’envoi du formulaire.
Ne pas journaliser les corps des requêtes/réponses du fournisseur ni les documents.

Limites : 5 Mo par fichier, 12 pages par justificatif de domicile (toutes analysées),
4 pages par autre PDF, 2 analyses simultanées par processus,
30 appels réservés par session/heure, 600 par jour pour le service. Les compteurs SQLite
ne contiennent pas les documents. Cache en mémoire de 10 minutes (128 entrées maximum).
Pas de relance automatique ; délai réseau de 25 secondes, navigateur 35 secondes.
Les threads Gunicorn maintiennent le formulaire disponible pendant l’analyse. Un verrou
protège PDFium, qui n’est pas compatible avec des appels simultanés entre threads.

Une erreur, une limite ou une clé absente conserve toujours la possibilité de poursuivre.
L’échec d’une tentative sur un fichier recevable reçoit aussi un reçu signé lié au fichier
et à la session. Son motif technique est conservé au dépôt sous « Vérification non concluante ».
Les logs indiquent seulement le type de pièce et un code d’erreur interne autorisé.

Dans l’administration, ouvrir un dossier relance une fois le contrôle des justificatifs de
domicile sans résultat. Le bouton « Relancer la vérification » permet une nouvelle tentative
sur tout type de pièce pris en charge, à partir du fichier enregistré. L’appel exige la
session administrateur et un jeton anti-CSRF. Un résultat existant n’est pas relancé
automatiquement ; un document remplacé pendant l’analyse ne reçoit pas un résultat périmé.
Ces contrôles ne changent jamais la décision humaine de conformité et n’envoient aucun mail.

Tests : `python -m unittest discover -s tests` et `node --test tests/*.test.mjs`.
Utiliser `CNAPS_DB_PATH` et `CNAPS_UPLOAD_DIR` temporaires. Ne jamais créer de demande réelle
ni envoyer de notification pendant les vérifications.
