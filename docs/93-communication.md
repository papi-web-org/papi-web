**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Communication vers les joueur·euses

Cette page est dédiée à la communication vers les joueur·euses, pour une mise en œuvre rapide dans Papi-web (version 2.2 ?). 

## Médias cibles

Les deux médias cibles suivants sont envisagés :

- envoi de mél ;
- envoi de SMS ou MMS.

Dans les deux cas, les informations utilisées pour communiquer sont celles données par les joueur·euses à leur inscription (les informations saisies sur Chess Event sont récupérées par Papi-web).

Voir : [Création des fichiers Papi des tournois à partir de Chess Event](37-chessevent.md)

## Destinataires des envois

Le système doit être le plus souple possible et permettre les envois :

- à tou·tes les joueur·euses d'un évènement
- à tou·tes les joueur·euses d'un tournoi
- à tou·tes les joueur·euses apparié·es à la ronde courante d'un tournoi
- à le·la joueur·euse exempt·e à la ronde courante d'un tournoi
- à un·e ou plusieurs joueur·euses d'un tournoi choisi·es par l'arbitre

## Contenu et personnalisation

Les arbitres doivent pouvoir s'appuyer sur des messages-types, pour par exemple :

- prévenir de l'ouverture ou la fermeture imminente du pointage
- prévenir des appariements 
- envoyer le classement

Tous les messages doivent être personnalisables à l'aide des *tokens* suivants.

| Portée                       | *Token*                   | Remplacement                                                                       |
|------------------------------|---------------------------|------------------------------------------------------------------------------------|
| Évènement (**ev***ent*)      | `{{ev_name}}`             | Le nom de l'évènement                                                              |
| Tournoi (**to***urnament*)   | `{{to_name}}`             | Le nom du tournoi                                                                  |
|                              | `{{to_ffe_url}}`          | L'URL de la fiche du tournoi sur le site web fédéral                               |
| Ronde en cours (**ro***und*) | `{{ro_number}}`           | Le numéro de la ronde en cours                                                     |
|                              | `{{ro_datetime}}`         | La date et l'heure de la ronde en cours                                            |
|                              | `{{ro_time}}`             | L'heure de la ronde en cours                                                       |
| Joueur·euse (**pl***ayer*)   | `{{pl_last_name}}`        | Le nom de famille du·de la joueur·euse                                             |
|                              | `{{pl_first_name}}`       | Le nom de famille du·de la joueur·euse                                             |
|                              | `{{pl_gender}}`           | Le nom de famille du·de la joueur·euse                                             |
|                              | `{{pl_name}}`             | Le nom complet du·de la joueur·euse                                                |
|                              | `{{pl_rating}}`           | Le classement du·de la joueur·euse                                                 |
|                              | `{{pl_rating_type}}`      | Le type classement du·de la joueur·euse (Fide, National, Estimé)                   |
|                              | `{{pl_points}}`           | Le nombre de points du·de la joueur·euse                                           |
|                              | `{{pl_standings_points}}` | Le nombre de points réels du·de la joueur·euse                                     |
| Appariement (**pa***iring*)  | `{{pa_paired}}`           | True si le·la joueur·euse est apparié·e, False sinon                               |
|                              | `{{pa_paired_bye}}`       | True si le·la joueur·euse est exempt·e, False sinon                                |
|                              | `{{pa_unpaired}}`         | True si le·la joueur·euse est non apparié·e, False sinon                           |
|                              | `{{pa_unpaired_hp_bye}}`  | True si le·la joueur·euse est non apparié·e avec un demi-point de bye, False sinon |
|                              | `{{pa_unpaired_fp_bye}}`  | True si le·la joueur·euse est non apparié·e avec un point de bye, False sinon      |
|                              | `{{pa_board}}`            | Le numéro de l'échiquier de l'appariement                                          |
|                              | `{{pa_color}}`            | La couleur de l'appariement                                                        |
| Adversaire (**op***ponent*)  | `{{op_last_name}}`        | Le nom de famille de l'adversaire                                                  |
|                              | `{{op_first_name}}`       | Le nom de famille de l'adversaire                                                  |
|                              | `{{op_gender}}`           | Le nom de famille de l'adversaire                                                  |
|                              | `{{op_name}}`             | Le nom complet de l'adversaire                                                     |
|                              | `{{op_rating}}`           | Le classement de l'adversaire                                                      |
|                              | `{{op_rating_type}}`      | Le type classement de l'adversaire (Fide, National, Estimé)                        |
|                              | `{{op_points}}`           | Le nombre de points de l'adversaire                                                |
|                              | `{{op_standings_points}}` | Le nombre de points réels du·de la joueur·euse                                     |

Le moteur de modèles de Django est utilisé pour la personnalisation des contenus, ce qui permet par exemple l'utilisation des alternatives `{% if %}`...`{% else %}`...`{% endif %}` :

```
Bonjour {{pl_first_name}},
Tournoi : {{to_name}}
Apparaiement de la ronde {{ro_number}} :
{% if pa_paired %}
  {% if pa_paired_bye }}
    Exempt{% if pl_gender == 'F' %}e
  {% else %}
    Adversaire : {{op_name}} {{op_rating}}{{op_rating_type}} [{{op_points}}]
    Couleur : {{pa_color}}
    Échiquier : {{pa_board}}
  {% endif %}
{% endif %}
{% if pa_unpaired %}
  Non apparié{% if pl_gender == 'F' %}e {% if pa_unpaired_bye_hp %}(bye 0,5 point){% endif %}{% if pa_unpaired_bye_fp %}(bye 1 point){% endif %}
{% endif %}
```

## Moteurs d'envoi

Plusieurs moteurs d'envoi peuvent être définis sur la machine de l'arbitre, et utilisables par tous les tournois de tous les évènements.

### Moteur d'envoi de mél

Un moteur d'envoi par mél est défini par les paramètres suivants.

| Paramètre            | Type | Signification                                                                                                                     |
|----------------------|------|-----------------------------------------------------------------------------------------------------------------------------------|
| `type`               | enum | Valeur `smtp`                                                                                                                     |
| `smtp_host`          | str  | Le serveur SMTP (obligatoire)                                                                                                     |
| `smtp_security`      | enum | aucune (`smtp_port` = `25` par défaut)<br/>STARTTLS (`smtp_port` = `587` par défaut)<br/>SSL/TLS (`smtp_port` = `465` par défaut) |
| `smtp_port`          | int  | Le port utilisé (facultatif)                                                                                                      |
| `smtp_user`          | str  | Le compte utilisé pour s'authentifier sur le serveur SMTP (facultatif)                                                            |
| `smtp_password`      | str  | Le mot de passe (facultatif)                                                                                                      |
| `smtp_from_mail`     | str  | Le mél de l'envoyeur (facultatif)                                                                                                 |
| `smtp_from_name`     | str  | Le nom de l'envoyeur (facultatif)                                                                                                 |
| `smtp_bcc`           | str  | Adresses en copie cachée, séparées par les virgules (facultatif)                                                                  |
| `smtp_reply_to_mail` | str  | Le mél pour la réponse (facultatif)                                                                                               |
| `smtp_reply_to_name` | str  | Le nom pour la réponse (facultatif)                                                                                               |

L'envoi par mél est simple à mettre en place et gratuite, il suffit de disposer d'un compte mél chez un fournisseur.

### Moteur MailJet d'envoi de SMS

Un moteur MailJet d'envoi par SMS est défini par les paramètres suivants.

| Paramètre            | Type | Signification                                                          |
|----------------------|------|------------------------------------------------------------------------|
| `type`               | enum | Valeur `sms_mailjet`                                                   |
| `mailjet_sms_from`   | str  | L'envoyeur (facultatif, par défaut `Papi-web`)                         |
| `mailjet_sms_token`  | str  | le jeton d'authentification sur l'API MailJet                          |

L'envoi par SMS est plus complexe à mettre en place et payant, il faut s'appuyer sur un fournisseur d'envoi (par exemple ici [MailJet](https://mailjet.com)).
