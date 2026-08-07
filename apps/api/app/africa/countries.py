"""Registre des pays couverts par la plateforme.

Une seule table de vérité pour tout ce qui varie d'un pays à l'autre : indicatif
téléphonique, devise, fuseau, langues, moyens de paiement, TVA, jour de repos
hebdomadaire. Chaque partie de la plateforme y puise plutôt que de coder son propre
« si Bénin alors… » :

- l'agent codeur, pour écrire les prix, les horaires et les liens WhatsApp d'un site ;
- le formulaire d'inscription, pour proposer le bon indicatif par défaut ;
- la facturation, pour choisir la devise et le taux de TVA applicable ;
- le dashboard admin, pour ventiler l'activité par pays et par zone monétaire.

Le périmètre couvre l'Afrique de l'Ouest et centrale francophone (marché principal),
les grandes économies anglophones et le Maghreb. Ajouter un pays = ajouter une entrée
ici, rien d'autre.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.africa import currencies


@dataclass(frozen=True)
class Country:
    """Tout ce que la plateforme doit savoir d'un pays.

    Attributes:
        code: ISO 3166-1 alpha-2, la clé du registre.
        dial_code: indicatif international, sans le `+`.
        national_digits: longueurs acceptées pour un numéro national. C'est un
            ensemble parce que plusieurs pays sont en cours de migration : le Bénin
            est passé à 10 chiffres en 2024 et les deux formats circulent encore sur
            les cartes de visite qu'on nous demandera de retranscrire.
        mobile_prefixes: préfixes qui identifient un mobile. Sert à distinguer un
            numéro joignable sur WhatsApp d'un fixe — un site qui met un bouton
            WhatsApp sur un numéro fixe déçoit au premier clic.
        mobile_money: opérateurs de paiement mobile réellement utilisés, dans l'ordre
            de part de marché. L'ordre compte : c'est celui dans lequel un site
            généré doit les présenter.
        weekend: jours non ouvrés (0 = lundi). Le Maghreb travaille le dimanche et
            ferme le vendredi ; afficher « Fermé le samedi et dimanche » sur un site
            marocain est faux.
        vat_rate: taux de TVA normal, en pourcentage.
        emergency: numéros d'urgence, utiles aux sites de santé et de services.
    """

    code: str
    name_fr: str
    name_en: str
    dial_code: str
    currency: str
    timezone: str
    languages: tuple[str, ...]
    national_digits: tuple[int, ...]
    mobile_prefixes: tuple[str, ...] = ()
    mobile_money: tuple[str, ...] = ()
    psp: tuple[str, ...] = ()
    region: str = "afrique-ouest"
    economic_zone: str = ""
    vat_rate: float = 18.0
    weekend: tuple[int, ...] = (5, 6)
    capital: str = ""
    major_cities: tuple[str, ...] = ()
    emergency: dict[str, str] = field(default_factory=dict)

    @property
    def currency_obj(self) -> currencies.Currency:
        return currencies.get(self.currency)

    @property
    def primary_language(self) -> str:
        return self.languages[0] if self.languages else "fr"

    @property
    def flag(self) -> str:
        """Drapeau en émoji, dérivé du code ISO (indicateurs régionaux Unicode).

        Calculé plutôt que stocké : la formule est exacte pour tout code alpha-2 et
        évite trente caractères à maintenir à la main.
        """
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.code)


# Ordre : marché principal (UEMOA) d'abord, puis CEMAC, anglophones, Maghreb, reste.
COUNTRIES: dict[str, Country] = {
    # ----------------------------------------------------------------- UEMOA -- #
    "BJ": Country(
        "BJ", "Bénin", "Benin", "229", "XOF", "Africa/Porto-Novo", ("fr",),
        national_digits=(10, 8), mobile_prefixes=("01",),
        mobile_money=("MTN MoMo", "Moov Money", "Celtiis Cash"),
        psp=("KKiaPay", "FedaPay", "CinetPay", "PayDunya"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Porto-Novo", major_cities=("Cotonou", "Porto-Novo", "Parakou", "Abomey-Calavi", "Bohicon"),
        emergency={"police": "117", "pompiers": "118", "samu": "112"},
    ),
    "CI": Country(
        "CI", "Côte d'Ivoire", "Ivory Coast", "225", "XOF", "Africa/Abidjan", ("fr",),
        national_digits=(10,), mobile_prefixes=("01", "05", "07"),
        mobile_money=("Orange Money", "MTN MoMo", "Wave", "Moov Money"),
        psp=("CinetPay", "Wave", "Paystack", "PayDunya", "Flutterwave"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Yamoussoukro", major_cities=("Abidjan", "Bouaké", "Yamoussoukro", "Daloa", "San-Pédro"),
        emergency={"police": "110", "pompiers": "180", "samu": "185"},
    ),
    "SN": Country(
        "SN", "Sénégal", "Senegal", "221", "XOF", "Africa/Dakar", ("fr", "wo"),
        national_digits=(9,), mobile_prefixes=("70", "75", "76", "77", "78"),
        mobile_money=("Wave", "Orange Money", "Free Money", "Wizall"),
        psp=("PayDunya", "Wave", "CinetPay", "Paystack"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Dakar", major_cities=("Dakar", "Thiès", "Touba", "Saint-Louis", "Ziguinchor"),
        emergency={"police": "17", "pompiers": "18", "samu": "1515"},
    ),
    "TG": Country(
        "TG", "Togo", "Togo", "228", "XOF", "Africa/Lome", ("fr",),
        national_digits=(8,), mobile_prefixes=("70", "79", "90", "91", "92", "93", "96", "97", "98", "99"),
        mobile_money=("T-Money", "Flooz (Moov)"),
        psp=("PayGate", "CinetPay", "PayDunya", "KKiaPay"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Lomé", major_cities=("Lomé", "Sokodé", "Kara", "Kpalimé"),
        emergency={"police": "117", "pompiers": "118"},
    ),
    "BF": Country(
        "BF", "Burkina Faso", "Burkina Faso", "226", "XOF", "Africa/Ouagadougou", ("fr",),
        national_digits=(8,), mobile_prefixes=("5", "6", "7"),
        mobile_money=("Orange Money", "Moov Money", "Wave", "Coris Money"),
        psp=("CinetPay", "Wave", "PayDunya", "LigdiCash"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Ouagadougou", major_cities=("Ouagadougou", "Bobo-Dioulasso", "Koudougou"),
        emergency={"police": "17", "pompiers": "18"},
    ),
    "ML": Country(
        "ML", "Mali", "Mali", "223", "XOF", "Africa/Bamako", ("fr", "bm"),
        national_digits=(8,), mobile_prefixes=("6", "7", "8", "9"),
        mobile_money=("Orange Money", "Moov Money", "Sama Money", "Wave"),
        psp=("CinetPay", "Wave", "PayDunya"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=18.0,
        capital="Bamako", major_cities=("Bamako", "Sikasso", "Mopti", "Ségou"),
        emergency={"police": "17", "pompiers": "18"},
    ),
    "NE": Country(
        "NE", "Niger", "Niger", "227", "XOF", "Africa/Niamey", ("fr",),
        national_digits=(8,), mobile_prefixes=("8", "9"),
        mobile_money=("Airtel Money", "Moov Money", "Zamani Cash"),
        psp=("CinetPay", "PayDunya"),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=19.0,
        capital="Niamey", major_cities=("Niamey", "Zinder", "Maradi"),
        emergency={"police": "17", "pompiers": "18"},
    ),
    "GW": Country(
        "GW", "Guinée-Bissau", "Guinea-Bissau", "245", "XOF", "Africa/Bissau", ("pt", "fr"),
        national_digits=(9, 7), mobile_prefixes=("5", "6", "9"),
        mobile_money=("Orange Money", "MTN MoMo"),
        psp=("CinetPay",),
        region="afrique-ouest", economic_zone="UEMOA", vat_rate=17.0,
        capital="Bissau", major_cities=("Bissau", "Bafatá"),
    ),
    # ----------------------------------------------------------------- CEMAC -- #
    "CM": Country(
        "CM", "Cameroun", "Cameroon", "237", "XAF", "Africa/Douala", ("fr", "en"),
        national_digits=(9,), mobile_prefixes=("6",),
        mobile_money=("MTN MoMo", "Orange Money"),
        psp=("CinetPay", "Flutterwave", "MeSomb", "Notch Pay"),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=19.25,
        capital="Yaoundé", major_cities=("Douala", "Yaoundé", "Bafoussam", "Garoua", "Bamenda"),
        emergency={"police": "117", "pompiers": "118"},
    ),
    "GA": Country(
        "GA", "Gabon", "Gabon", "241", "XAF", "Africa/Libreville", ("fr",),
        national_digits=(9, 8), mobile_prefixes=("6", "7"),
        mobile_money=("Airtel Money", "Moov Money"),
        psp=("CinetPay", "Flutterwave"),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=18.0,
        capital="Libreville", major_cities=("Libreville", "Port-Gentil", "Franceville"),
    ),
    "CG": Country(
        "CG", "Congo", "Republic of the Congo", "242", "XAF", "Africa/Brazzaville", ("fr",),
        national_digits=(9,), mobile_prefixes=("0",),
        mobile_money=("MTN MoMo", "Airtel Money"),
        psp=("CinetPay", "Flutterwave"),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=18.0,
        capital="Brazzaville", major_cities=("Brazzaville", "Pointe-Noire"),
    ),
    "TD": Country(
        "TD", "Tchad", "Chad", "235", "XAF", "Africa/Ndjamena", ("fr", "ar"),
        national_digits=(8,), mobile_prefixes=("6", "9"),
        mobile_money=("Airtel Money", "Tigo Cash"),
        psp=("CinetPay",),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=18.0,
        capital="N'Djaména", major_cities=("N'Djaména", "Moundou"),
    ),
    "CF": Country(
        "CF", "Centrafrique", "Central African Republic", "236", "XAF", "Africa/Bangui", ("fr",),
        national_digits=(8,), mobile_prefixes=("7",),
        mobile_money=("Orange Money", "Telecel Money"),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=19.0,
        capital="Bangui", major_cities=("Bangui",),
    ),
    "GQ": Country(
        "GQ", "Guinée équatoriale", "Equatorial Guinea", "240", "XAF", "Africa/Malabo", ("es", "fr"),
        national_digits=(9,), mobile_prefixes=("222", "551"),
        mobile_money=("Muni",),
        region="afrique-centrale", economic_zone="CEMAC", vat_rate=15.0,
        capital="Malabo", major_cities=("Malabo", "Bata"),
    ),
    # --------------------------------------------------- Anglophones majeurs -- #
    "NG": Country(
        "NG", "Nigeria", "Nigeria", "234", "NGN", "Africa/Lagos", ("en",),
        national_digits=(10,), mobile_prefixes=("70", "80", "81", "90", "91"),
        mobile_money=("OPay", "PalmPay", "Moniepoint", "Paga", "Virement bancaire"),
        psp=("Paystack", "Flutterwave", "Monnify", "Squad"),
        region="afrique-ouest", economic_zone="CEDEAO", vat_rate=7.5,
        capital="Abuja", major_cities=("Lagos", "Abuja", "Kano", "Ibadan", "Port Harcourt"),
        emergency={"police": "112", "pompiers": "112"},
    ),
    "GH": Country(
        "GH", "Ghana", "Ghana", "233", "GHS", "Africa/Accra", ("en",),
        national_digits=(9,), mobile_prefixes=("2", "5"),
        mobile_money=("MTN MoMo", "Telecel Cash", "AirtelTigo Money"),
        psp=("Paystack", "Flutterwave", "Hubtel", "ExpressPay"),
        region="afrique-ouest", economic_zone="CEDEAO", vat_rate=15.0,
        capital="Accra", major_cities=("Accra", "Kumasi", "Tamale", "Takoradi"),
        emergency={"police": "191", "pompiers": "192"},
    ),
    "KE": Country(
        "KE", "Kenya", "Kenya", "254", "KES", "Africa/Nairobi", ("en", "sw"),
        national_digits=(9,), mobile_prefixes=("7", "1"),
        mobile_money=("M-Pesa", "Airtel Money"),
        psp=("Paystack", "Flutterwave", "Pesapal", "IntaSend"),
        region="afrique-est", economic_zone="EAC", vat_rate=16.0,
        capital="Nairobi", major_cities=("Nairobi", "Mombasa", "Kisumu", "Nakuru"),
        emergency={"police": "999", "samu": "999"},
    ),
    "ZA": Country(
        "ZA", "Afrique du Sud", "South Africa", "27", "ZAR", "Africa/Johannesburg", ("en", "af", "zu"),
        national_digits=(9,), mobile_prefixes=("6", "7", "8"),
        mobile_money=("SnapScan", "Zapper", "Ozow", "Carte bancaire"),
        psp=("Paystack", "PayFast", "Yoco", "Peach Payments"),
        region="afrique-australe", economic_zone="SADC", vat_rate=15.0,
        capital="Pretoria", major_cities=("Johannesburg", "Le Cap", "Durban", "Pretoria"),
        emergency={"police": "10111", "samu": "10177"},
    ),
    "RW": Country(
        "RW", "Rwanda", "Rwanda", "250", "RWF", "Africa/Kigali", ("rw", "fr", "en"),
        national_digits=(9,), mobile_prefixes=("7",),
        mobile_money=("MTN MoMo", "Airtel Money"),
        psp=("Flutterwave", "Paypack"),
        region="afrique-est", economic_zone="EAC", vat_rate=18.0,
        capital="Kigali", major_cities=("Kigali", "Butare"),
    ),
    "UG": Country(
        "UG", "Ouganda", "Uganda", "256", "UGX", "Africa/Kampala", ("en", "sw"),
        national_digits=(9,), mobile_prefixes=("7",),
        mobile_money=("MTN MoMo", "Airtel Money"),
        psp=("Flutterwave", "Pesapal"),
        region="afrique-est", economic_zone="EAC", vat_rate=18.0,
        capital="Kampala", major_cities=("Kampala", "Gulu", "Mbarara"),
    ),
    "TZ": Country(
        "TZ", "Tanzanie", "Tanzania", "255", "TZS", "Africa/Dar_es_Salaam", ("sw", "en"),
        national_digits=(9,), mobile_prefixes=("6", "7"),
        mobile_money=("M-Pesa", "Mixx by Yas", "Airtel Money", "HaloPesa"),
        psp=("Flutterwave", "Selcom"),
        region="afrique-est", economic_zone="EAC", vat_rate=18.0,
        capital="Dodoma", major_cities=("Dar es Salaam", "Dodoma", "Arusha", "Mwanza"),
    ),
    "CD": Country(
        "CD", "RD Congo", "DR Congo", "243", "CDF", "Africa/Kinshasa", ("fr", "ln", "sw"),
        national_digits=(9,), mobile_prefixes=("8", "9"),
        mobile_money=("M-Pesa", "Orange Money", "Airtel Money"),
        psp=("FlexPay", "CinetPay", "Flutterwave"),
        region="afrique-centrale", economic_zone="SADC", vat_rate=16.0,
        capital="Kinshasa", major_cities=("Kinshasa", "Lubumbashi", "Goma", "Bukavu"),
    ),
    "GN": Country(
        "GN", "Guinée", "Guinea", "224", "GNF", "Africa/Conakry", ("fr",),
        national_digits=(9,), mobile_prefixes=("6",),
        mobile_money=("Orange Money", "MTN MoMo"),
        psp=("CinetPay", "PayCard"),
        region="afrique-ouest", economic_zone="CEDEAO", vat_rate=18.0,
        capital="Conakry", major_cities=("Conakry", "Kankan", "Nzérékoré"),
    ),
    "MG": Country(
        "MG", "Madagascar", "Madagascar", "261", "MGA", "Indian/Antananarivo", ("mg", "fr"),
        national_digits=(9,), mobile_prefixes=("3",),
        mobile_money=("MVola", "Orange Money", "Airtel Money"),
        psp=("Flutterwave",),
        region="afrique-est", economic_zone="SADC", vat_rate=20.0,
        capital="Antananarivo", major_cities=("Antananarivo", "Toamasina", "Mahajanga"),
    ),
    "ET": Country(
        "ET", "Éthiopie", "Ethiopia", "251", "ETB", "Africa/Addis_Ababa", ("am", "en"),
        national_digits=(9,), mobile_prefixes=("9",),
        mobile_money=("Telebirr", "CBE Birr"),
        psp=("Chapa", "ArifPay"),
        region="afrique-est", vat_rate=15.0,
        capital="Addis-Abeba", major_cities=("Addis-Abeba", "Dire Dawa"),
    ),
    "MU": Country(
        "MU", "Maurice", "Mauritius", "230", "MUR", "Indian/Mauritius", ("en", "fr"),
        national_digits=(8,), mobile_prefixes=("5",),
        mobile_money=("Juice", "MyT Money", "Blink"),
        psp=("Peach Payments", "MIPS"),
        region="afrique-est", economic_zone="SADC", vat_rate=15.0,
        capital="Port-Louis", major_cities=("Port-Louis", "Curepipe"),
    ),
    # --------------------------------------------------------------- Maghreb -- #
    "MA": Country(
        "MA", "Maroc", "Morocco", "212", "MAD", "Africa/Casablanca", ("ar", "fr"),
        national_digits=(9,), mobile_prefixes=("6", "7"),
        mobile_money=("CIH Pay", "Wafacash", "Cash Plus", "Carte bancaire"),
        psp=("CMI", "PayZone", "Youcan Pay"),
        region="maghreb", economic_zone="UMA", vat_rate=20.0, weekend=(5, 6),
        capital="Rabat", major_cities=("Casablanca", "Rabat", "Marrakech", "Fès", "Tanger"),
        emergency={"police": "19", "pompiers": "15"},
    ),
    "TN": Country(
        "TN", "Tunisie", "Tunisia", "216", "TND", "Africa/Tunis", ("ar", "fr"),
        national_digits=(8,), mobile_prefixes=("2", "4", "5", "9"),
        mobile_money=("D17", "e-Dinar", "Flouci"),
        psp=("Paymee", "Konnect", "Flouci"),
        region="maghreb", economic_zone="UMA", vat_rate=19.0,
        capital="Tunis", major_cities=("Tunis", "Sfax", "Sousse"),
    ),
    "DZ": Country(
        "DZ", "Algérie", "Algeria", "213", "DZD", "Africa/Algiers", ("ar", "fr"),
        national_digits=(9,), mobile_prefixes=("5", "6", "7"),
        mobile_money=("BaridiMob", "CIB", "Edahabia"),
        psp=("SATIM", "Chargily"),
        region="maghreb", economic_zone="UMA", vat_rate=19.0, weekend=(4, 5),
        capital="Alger", major_cities=("Alger", "Oran", "Constantine"),
    ),
    "EG": Country(
        "EG", "Égypte", "Egypt", "20", "EGP", "Africa/Cairo", ("ar", "en"),
        national_digits=(10,), mobile_prefixes=("10", "11", "12", "15"),
        mobile_money=("Vodafone Cash", "InstaPay", "Fawry"),
        psp=("Paymob", "Fawry", "Kashier"),
        region="maghreb", vat_rate=14.0, weekend=(4, 5),
        capital="Le Caire", major_cities=("Le Caire", "Alexandrie", "Gizeh"),
    ),
}

DEFAULT_COUNTRY = "BJ"

# Index inverse indicatif → pays. Plusieurs pays peuvent partager un indicatif dans
# d'autres régions du monde ; ce n'est pas le cas ici, on garde donc une table plate.
_BY_DIAL: dict[str, str] = {}
for _code, _c in COUNTRIES.items():
    _BY_DIAL.setdefault(_c.dial_code, _code)


def get(code: str | None) -> Country:
    """Pays par code ISO, repli sur le pays par défaut.

    Comme pour les devises, un code inconnu vient d'une saisie ou d'un modèle : il ne
    doit jamais interrompre une génération de site.
    """
    return COUNTRIES.get((code or "").strip().upper(), COUNTRIES[DEFAULT_COUNTRY])


def find(code: str | None) -> Country | None:
    """Pays par code ISO, `None` si inconnu — pour les cas où le repli serait faux.

    À utiliser partout où la valeur est décisionnelle (choix d'une devise de
    facturation, application d'un taux de TVA) : facturer un client sud-africain au
    taux béninois parce que son code pays contenait une faute serait une erreur
    comptable, pas un détail d'affichage.
    """
    return COUNTRIES.get((code or "").strip().upper())


def by_dial_code(dial: str) -> Country | None:
    """Pays correspondant à un indicatif (`+229`, `229`, `00229`)."""
    digits = (dial or "").strip().lstrip("+").lstrip("0")
    return COUNTRIES.get(_BY_DIAL.get(digits, ""))


def list_countries(region: str | None = None, zone: str | None = None) -> list[Country]:
    """Pays du registre, filtrables par région ou zone économique.

    L'ordre du dictionnaire est délibéré (marché principal d'abord) et préservé :
    c'est celui dans lequel les listes déroulantes doivent apparaître.
    """
    out = list(COUNTRIES.values())
    if region:
        out = [c for c in out if c.region == region]
    if zone:
        out = [c for c in out if c.economic_zone == zone.upper()]
    return out


def currencies_in_use() -> list[str]:
    """Devises effectivement rattachées à un pays couvert, sans doublon."""
    seen: list[str] = []
    for c in COUNTRIES.values():
        if c.currency not in seen:
            seen.append(c.currency)
    return seen


def payment_methods(code: str) -> list[str]:
    """Moyens de paiement à présenter sur un site de ce pays, par ordre d'usage.

    Le mobile money passe avant la carte bancaire, et ce n'est pas un choix
    esthétique : sur nos marchés, la pénétration du mobile money dépasse largement
    celle de la carte. Un site qui ouvre sur « Payer par carte » perd la majorité de
    ses acheteurs à la première étape.
    """
    country = get(code)
    methods = list(country.mobile_money)
    for extra in ("Espèces à la livraison", "Virement bancaire"):
        if extra not in methods:
            methods.append(extra)
    return methods
