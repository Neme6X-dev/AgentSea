"""Socle Afrique : ce qui change d'un pays à l'autre, regroupé en un seul endroit.

Rassembler pays, devises, téléphonie, paiement et conventions locales dans un même
package n'est pas un rangement : c'est ce qui empêche les règles régionales de se
disperser en conditions ponctuelles dans les routeurs et les prompts. Ouvrir un
nouveau pays doit se faire en ajoutant une entrée à `countries.COUNTRIES`, et nulle
part ailleurs.

Usage courant :

    from app.africa import countries, currencies, phone

    pays = countries.get("BJ")
    currencies.format_amount(15000, pays.currency)   # '15 000 FCFA'
    phone.normalize("01 97 00 00 00", "BJ")           # '+22901970000000'
"""
from app.africa import countries, currencies, locales, payments, phone

__all__ = ["countries", "currencies", "locales", "payments", "phone"]
