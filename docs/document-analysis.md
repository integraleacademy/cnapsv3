# Contrôle indicatif des documents

Configurer `OPENAI_API_KEY` dans l’environnement Render, puis enregistrer et redéployer.
Le modèle par défaut est `gpt-4.1` ; `OPENAI_DOCUMENT_MODEL` permet de le changer.
Utiliser un modèle compatible avec les images, Responses et les sorties JSON structurées.

Le navigateur envoie uniquement les fichiers sélectionnés pour l’identité, l’identité de
l’hébergeant et le domicile à `/api/document-analysis`. Le formulaire annonce leur transmission
à OpenAI. La clé reste sur le serveur. L’attestation d’hébergement affiche seulement un rappel
de signature après sélection ; elle n’est pas envoyée à OpenAI.

Le serveur rend les pages visibles du PDF, sans utiliser sa couche de texte cachée, puis envoie
ces images à l’API Responses avec `store=false`. Il ne crée pas de fichier OpenAI avec Files API.
Les fichiers ne sont pas conservés par cette vérification ; leur enregistrement habituel ne se
fait qu’à l’envoi du formulaire. Aucun nom, adresse ou numéro d’identité n’est demandé dans la
réponse. Ne pas journaliser les corps des requêtes/réponses du fournisseur.

La date du document est extraite par le modèle, puis comparée à trois mois calendaires côté
serveur (date française). Une attestation « en date du X, depuis Y » doit utiliser X. La moindre
détection de flou ou de caractères difficiles à lire produit une alerte. Aucun résultat ne
modifie le statut de conformité enregistré par l’administration.

Limites : 5 Mo, 4 pages, 2 analyses simultanées par processus, 30 analyses par session et par
heure, 600 par jour pour le service. Les compteurs SQLite ne contiennent pas les documents.
Les résultats d’une même session sont mis en cache en mémoire pendant 10 minutes (128 entrées
maximum). Appel API sans relance automatique, délai réseau de 25 secondes ; navigateur 35 secondes.
Les threads Gunicorn maintiennent l’accès au formulaire pendant cette attente ; les appels
PDFium sont protégés par un verrou car cette bibliothèque n’est pas compatible avec des appels
simultanés entre threads.

Une clé absente, une limite atteinte, une erreur API ou un résultat incertain affiche le message
adapté au type de document. L’utilisateur conserve toujours la possibilité de poursuivre.

Tests : `python -m unittest discover -s tests` et `node --test tests/*.test.mjs`.
Utiliser `CNAPS_DB_PATH` et `CNAPS_UPLOAD_DIR` temporaires pour les tests ; ne jamais soumettre
de demande réelle ni envoyer de notification pendant les vérifications.
