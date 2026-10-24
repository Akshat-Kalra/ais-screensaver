"""AIS lookup tables: MMSI MID -> flag, ship type codes, navigational status."""

from __future__ import annotations

_COUNTRIES = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AG": "Antigua and Barbuda",
    "AI": "Anguilla", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AR": "Argentina",
    "AS": "American Samoa", "AT": "Austria", "AU": "Australia", "AW": "Aruba", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BB": "Barbados", "BD": "Bangladesh", "BE": "Belgium",
    "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Bahrain", "BI": "Burundi", "BJ": "Benin",
    "BM": "Bermuda", "BN": "Brunei", "BO": "Bolivia", "BR": "Brazil", "BS": "Bahamas", "BT": "Bhutan",
    "BW": "Botswana", "BY": "Belarus", "BZ": "Belize", "CA": "Canada", "CC": "Cocos Islands",
    "CD": "DR Congo", "CF": "Central African Republic", "CG": "Congo", "CH": "Switzerland",
    "CI": "Côte d'Ivoire", "CK": "Cook Islands", "CL": "Chile", "CM": "Cameroon", "CN": "China",
    "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "CV": "Cabo Verde", "CW": "Curaçao",
    "CX": "Christmas Island", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DJ": "Djibouti",
    "DK": "Denmark", "DM": "Dominica", "DO": "Dominican Republic", "DZ": "Algeria", "EC": "Ecuador",
    "EE": "Estonia", "EG": "Egypt", "ER": "Eritrea", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland",
    "FJ": "Fiji", "FK": "Falkland Islands", "FM": "Micronesia", "FO": "Faroe Islands", "FR": "France",
    "GA": "Gabon", "GB": "United Kingdom", "GD": "Grenada", "GE": "Georgia", "GF": "French Guiana",
    "GH": "Ghana", "GI": "Gibraltar", "GL": "Greenland", "GM": "Gambia", "GN": "Guinea",
    "GP": "Guadeloupe", "GQ": "Equatorial Guinea", "GR": "Greece", "GT": "Guatemala",
    "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia",
    "HT": "Haiti", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IQ": "Iraq", "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JM": "Jamaica", "JO": "Jordan",
    "JP": "Japan", "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KI": "Kiribati",
    "KM": "Comoros", "KN": "Saint Kitts and Nevis", "KP": "North Korea", "KR": "South Korea",
    "KW": "Kuwait", "KY": "Cayman Islands", "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon",
    "LC": "Saint Lucia", "LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Liberia", "LS": "Lesotho",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "LY": "Libya", "MA": "Morocco",
    "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro", "MG": "Madagascar", "MH": "Marshall Islands",
    "MK": "North Macedonia", "ML": "Mali", "MM": "Myanmar", "MN": "Mongolia", "MO": "Macao",
    "MP": "Northern Mariana Islands", "MQ": "Martinique", "MR": "Mauritania", "MS": "Montserrat",
    "MT": "Malta", "MU": "Mauritius", "MV": "Maldives", "MW": "Malawi", "MX": "Mexico",
    "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia", "NC": "New Caledonia", "NE": "Niger",
    "NG": "Nigeria", "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal",
    "NR": "Nauru", "NU": "Niue", "NZ": "New Zealand", "OM": "Oman", "PA": "Panama", "PE": "Peru",
    "PF": "French Polynesia", "PG": "Papua New Guinea", "PH": "Philippines", "PK": "Pakistan",
    "PL": "Poland", "PM": "Saint Pierre and Miquelon", "PN": "Pitcairn", "PR": "Puerto Rico",
    "PS": "Palestine", "PT": "Portugal", "PW": "Palau", "PY": "Paraguay", "QA": "Qatar",
    "RE": "Réunion", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "RW": "Rwanda",
    "SA": "Saudi Arabia", "SB": "Solomon Islands", "SC": "Seychelles", "SD": "Sudan", "SE": "Sweden",
    "SG": "Singapore", "SH": "Saint Helena", "SI": "Slovenia", "SK": "Slovakia", "SL": "Sierra Leone",
    "SM": "San Marino", "SN": "Senegal", "SO": "Somalia", "SR": "Suriname", "SS": "South Sudan",
    "ST": "São Tomé and Príncipe", "SV": "El Salvador", "SY": "Syria", "SZ": "Eswatini",
    "TC": "Turks and Caicos", "TD": "Chad", "TF": "French Southern Territories", "TG": "Togo",
    "TH": "Thailand", "TJ": "Tajikistan", "TL": "Timor-Leste", "TM": "Turkmenistan", "TN": "Tunisia",
    "TO": "Tonga", "TR": "Türkiye", "TT": "Trinidad and Tobago", "TV": "Tuvalu", "TW": "Taiwan",
    "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VA": "Vatican City", "VC": "Saint Vincent and the Grenadines",
    "VE": "Venezuela", "VG": "British Virgin Islands", "VI": "U.S. Virgin Islands", "VN": "Vietnam",
    "VU": "Vanuatu", "WF": "Wallis and Futuna", "WS": "Samoa", "YE": "Yemen", "ZA": "South Africa",
    "ZM": "Zambia", "ZW": "Zimbabwe",
}

# ITU Maritime Identification Digits -> ISO 3166-1 alpha-2.
_MID_ISO: dict[int, str] = {
    201: "AL", 202: "AD", 203: "AT", 204: "PT", 205: "BE", 206: "BY", 207: "BG", 208: "VA",
    209: "CY", 210: "CY", 211: "DE", 212: "CY", 213: "GE", 214: "MD", 215: "MT", 216: "AM",
    218: "DE", 219: "DK", 220: "DK", 224: "ES", 225: "ES", 226: "FR", 227: "FR", 228: "FR",
    229: "MT", 230: "FI", 231: "FO", 232: "GB", 233: "GB", 234: "GB", 235: "GB", 236: "GI",
    237: "GR", 238: "HR", 239: "GR", 240: "GR", 241: "GR", 242: "MA", 243: "HU", 244: "NL",
    245: "NL", 246: "NL", 247: "IT", 248: "MT", 249: "MT", 250: "IE", 251: "IS", 252: "LI",
    253: "LU", 254: "MC", 255: "PT", 256: "MT", 257: "NO", 258: "NO", 259: "NO", 261: "PL",
    262: "ME", 263: "PT", 264: "RO", 265: "SE", 266: "SE", 267: "SK", 268: "SM", 269: "CH",
    270: "CZ", 271: "TR", 272: "UA", 273: "RU", 274: "MK", 275: "LV", 276: "EE", 277: "LT",
    278: "SI", 279: "RS",
    301: "AI", 303: "US", 304: "AG", 305: "AG", 306: "CW", 307: "AW", 308: "BS", 309: "BS",
    310: "BM", 311: "BS", 312: "BZ", 314: "BB", 316: "CA", 319: "KY", 321: "CR", 323: "CU",
    325: "DM", 327: "DO", 329: "GP", 330: "GD", 331: "GL", 332: "GT", 334: "HN", 336: "HT",
    338: "US", 339: "JM", 341: "KN", 343: "LC", 345: "MX", 347: "MQ", 348: "MS", 350: "NI",
    351: "PA", 352: "PA", 353: "PA", 354: "PA", 355: "PA", 356: "PA", 357: "PA", 358: "PR",
    359: "SV", 361: "PM", 362: "TT", 364: "TC", 366: "US", 367: "US", 368: "US", 369: "US",
    370: "PA", 371: "PA", 372: "PA", 373: "PA", 374: "PA", 375: "VC", 376: "VC", 377: "VC",
    378: "VG", 379: "VI",
    401: "AF", 403: "SA", 405: "BD", 408: "BH", 410: "BT", 412: "CN", 413: "CN", 414: "CN",
    416: "TW", 417: "LK", 419: "IN", 422: "IR", 423: "AZ", 425: "IQ", 428: "IL", 431: "JP",
    432: "JP", 434: "TM", 436: "KZ", 437: "UZ", 438: "JO", 440: "KR", 441: "KR", 443: "PS",
    445: "KP", 447: "KW", 450: "LB", 451: "KG", 453: "MO", 455: "MV", 457: "MN", 459: "NP",
    461: "OM", 463: "PK", 466: "QA", 468: "SY", 470: "AE", 471: "AE", 472: "TJ", 473: "YE",
    475: "YE", 477: "HK", 478: "BA",
    501: "TF", 503: "AU", 506: "MM", 508: "BN", 510: "FM", 511: "PW", 512: "NZ", 514: "KH",
    515: "KH", 516: "CX", 518: "CK", 520: "FJ", 523: "CC", 525: "ID", 529: "KI", 531: "LA",
    533: "MY", 536: "MP", 538: "MH", 540: "NC", 542: "NU", 544: "NR", 546: "PF", 548: "PH",
    550: "TL", 553: "PG", 555: "PN", 557: "SB", 559: "AS", 561: "WS", 563: "SG", 564: "SG",
    565: "SG", 566: "SG", 567: "TH", 570: "TO", 572: "TV", 574: "VN", 576: "VU", 577: "VU",
    578: "WF",
    601: "ZA", 603: "AO", 605: "DZ", 607: "TF", 608: "SH", 609: "BI", 610: "BJ", 611: "BW",
    612: "CF", 613: "CM", 615: "CG", 616: "KM", 617: "CV", 618: "TF", 619: "CI", 620: "KM",
    621: "DJ", 622: "EG", 624: "ET", 625: "ER", 626: "GA", 627: "GH", 629: "GM", 630: "GW",
    631: "GQ", 632: "GN", 633: "BF", 634: "KE", 635: "TF", 636: "LR", 637: "LR", 638: "SS",
    642: "LY", 644: "LS", 645: "MU", 647: "MG", 649: "ML", 650: "MZ", 654: "MR", 655: "MW",
    656: "NE", 657: "NG", 659: "NA", 660: "RE", 661: "RW", 662: "SD", 663: "SN", 664: "SC",
    665: "SH", 666: "SO", 667: "SL", 668: "ST", 669: "SZ", 670: "TD", 671: "TG", 672: "TN",
    674: "TZ", 675: "UG", 676: "CD", 677: "TZ", 678: "ZM", 679: "ZW",
    701: "AR", 710: "BR", 720: "BO", 725: "CL", 730: "CO", 735: "EC", 740: "FK", 745: "GF",
    750: "GY", 755: "PY", 760: "PE", 765: "SR", 770: "UY", 775: "VE",
}


def is_ship_mmsi(mmsi: int) -> bool:
    """True for ordinary ship station MMSIs (MIDxxxxxx), excluding base stations,
    aids to navigation, SAR aircraft, SARTs/EPIRBs and craft-associated numbers."""
    s = f"{mmsi:09d}"
    return len(s) == 9 and s[0] in "234567"


def flag_for(mmsi: int) -> dict | None:
    s = f"{mmsi:09d}"
    if len(s) != 9:
        return None
    iso = _MID_ISO.get(int(s[:3]))
    if not iso:
        return None
    return {"code": iso, "name": _COUNTRIES.get(iso, iso)}


_HAZARD = {1: "Hazard A", 2: "Hazard B", 3: "Hazard C", 4: "Hazard D"}

_SPECIAL = {
    30: ("Fishing", "fishing"),
    31: ("Towing", "tug"),
    32: ("Towing, large", "tug"),
    33: ("Dredger", "special"),
    34: ("Diving operations", "special"),
    35: ("Military", "military"),
    36: ("Sailing", "sailing"),
    37: ("Pleasure craft", "pleasure"),
    50: ("Pilot vessel", "special"),
    51: ("Search and rescue", "special"),
    52: ("Tug", "tug"),
    53: ("Port tender", "special"),
    54: ("Anti-pollution", "special"),
    55: ("Law enforcement", "special"),
    58: ("Medical transport", "special"),
    59: ("Noncombatant", "special"),
}

_DECADES = {
    2: ("Wing in ground", "highspeed"),
    4: ("High-speed craft", "highspeed"),
    6: ("Passenger", "passenger"),
    7: ("Cargo", "cargo"),
    8: ("Tanker", "tanker"),
    9: ("Other", "other"),
}


def ship_type_info(code: int | None) -> tuple[str, str]:
    """(label, category) for an AIS ship type code 0-99."""
    if code is None or code <= 0 or code > 99:
        return ("Unknown", "other")
    if code in _SPECIAL:
        return _SPECIAL[code]
    decade, unit = divmod(code, 10)
    if decade in _DECADES:
        label, cat = _DECADES[decade]
        if unit in _HAZARD:
            label = f"{label} · {_HAZARD[unit]}"
        return (label, cat)
    return ("Reserved", "other")


NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    9: "Reserved (HSC)",
    10: "Reserved (WIG)",
    11: "Towing astern",
    12: "Pushing ahead",
    13: "Reserved",
    14: "AIS-SART active",
}


def nav_status_label(code: int | None) -> str | None:
    if code is None:
        return None
    return NAV_STATUS.get(code)
