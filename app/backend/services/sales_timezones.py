"""Conservative, address-based US calling zones without changing stored evidence.

The SQL and Python read models use the same reviewed state/city tables. A phone
area code is deliberately never an input: a business may keep a ported number.
Split-zone states require a reviewed city or an existing explicit IANA override.
"""

from zoneinfo import available_timezones

from sqlalchemy import and_, case, func, literal, or_


TIMEZONE_GROUPS = ("eastern", "central", "mountain", "pacific", "alaska", "hawaii", "unknown")
VALID_TIMEZONES = frozenset(available_timezones()) - {"localtime", "posixrules", "Factory"}
TRIM_CHARACTERS = " \t\r\n\v\f\u00a0"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_CODES = {name.upper(): code for code, name in STATE_NAMES.items()}
US_COUNTRIES = frozenset(("us", "usa", "unitedstates", "unitedstatesofamerica", "美国", "美國"))

STATE_ZONES = {
    **{code: "America/New_York" for code in (
        "CT", "DE", "DC", "GA", "ME", "MD", "MA", "NH", "NJ", "NY", "NC", "OH", "PA", "RI", "SC", "VT", "VA", "WV")},
    **{code: "America/Chicago" for code in ("AL", "AR", "IL", "IA", "LA", "MN", "MS", "MO", "OK", "WI")},
    **{code: "America/Denver" for code in ("CO", "MT", "NM", "UT", "WY")},
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "HI": "Pacific/Honolulu",
}


def _place_key(value):
    value = str(value or "").strip(TRIM_CHARACTERS).lower()
    for character in (" ", "-", ".", "'", "’"):
        value = value.replace(character, "")
    return value


# These are named cities, not blanket assumptions about split-zone states.
_CITY_ROWS = (
    ("AZ", "America/Phoenix", (
        "Phoenix", "Mesa", "Tempe", "Scottsdale", "Chandler", "Glendale", "Gilbert", "Tucson", "Peoria",
        "Surprise", "Goodyear", "Avondale", "Queen Creek", "Sun City", "Flagstaff", "Sedona", "Yuma", "Prescott")),
    ("NV", "America/Los_Angeles", (
        "Las Vegas", "North Las Vegas", "Henderson", "Reno", "Sparks", "Carson City", "Boulder City", "Pahrump", "Mesquite", "Elko")),
    ("NV", "America/Denver", ("West Wendover",)),
    ("OR", "America/Los_Angeles", (
        "Portland", "Beaverton", "Hillsboro", "Eugene", "Salem", "Bend", "Medford", "Corvallis", "Tigard", "Gresham",
        "Lake Oswego", "Happy Valley", "Clackamas", "West Linn", "Tualatin", "Wilsonville", "Milwaukie", "Oregon City", "Aloha", "Troutdale")),
    ("OR", "America/Boise", ("Ontario", "Vale", "Nyssa")),
    ("ID", "America/Boise", ("Boise", "Nampa", "Meridian", "Pocatello", "Idaho Falls", "Twin Falls", "Caldwell", "Eagle")),
    ("ID", "America/Los_Angeles", ("Coeur d'Alene", "Lewiston", "Moscow", "Sandpoint", "Post Falls")),
    ("AK", "America/Anchorage", ("Anchorage", "Fairbanks", "Juneau", "Wasilla", "Palmer", "Ketchikan", "Sitka", "Kenai", "Kodiak", "Seward", "Homer", "Bethel", "North Pole")),
    ("AK", "America/Adak", ("Adak",)),
    ("TX", "America/Chicago", ("Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "Plano", "Arlington", "Irving", "Sugar Land", "Katy", "Richardson", "Carrollton", "Frisco",
        "Allen", "Garland", "Lewisville", "McKinney", "Richmond", "The Colony", "Grapevine", "Bellaire", "Coppell", "Corsicana", "League City")),
    ("TX", "America/Denver", ("El Paso",)),
    ("FL", "America/New_York", ("Miami", "Orlando", "Tampa", "Jacksonville", "Tallahassee", "Fort Lauderdale", "Gainesville",
        "Boca Raton", "Cooper City", "Coral Springs", "Davie", "Hernando", "Miami Lakes", "North Miami Beach", "Pembroke Pines", "Sunrise",
        "Altamonte Springs", "Lady Lake", "Lakewood Ranch", "Port Orange", "Wellington", "Windermere", "Hallandale Beach", "Plantation")),
    ("FL", "America/Chicago", ("Pensacola", "Panama City", "Destin")),
    ("IN", "America/Indiana/Indianapolis", ("Indianapolis", "Bloomington", "Fort Wayne", "South Bend", "Lafayette")),
    ("IN", "America/Chicago", ("Gary", "Hammond", "Evansville")),
    ("KY", "America/Kentucky/Louisville", ("Louisville", "Lexington", "Frankfort")),
    ("KY", "America/Chicago", ("Bowling Green", "Paducah")),
    ("MI", "America/Detroit", ("Detroit", "Ann Arbor", "Lansing", "Grand Rapids", "Flint", "Madison Heights", "West Bloomfield Township", "Berkley", "Troy")),
    ("MI", "America/Menominee", ("Iron Mountain", "Menominee")),
    ("TN", "America/Chicago", ("Nashville", "Memphis", "Murfreesboro", "Jackson")),
    ("TN", "America/New_York", ("Knoxville", "Chattanooga")),
    ("KS", "America/Chicago", ("Wichita", "Topeka", "Kansas City", "Overland Park", "Lawrence")),
    ("NE", "America/Chicago", ("Omaha", "Lincoln", "Bellevue")),
    ("NE", "America/Denver", ("Scottsbluff",)),
    ("ND", "America/Chicago", ("Fargo", "Bismarck", "Grand Forks")),
    ("SD", "America/Chicago", ("Sioux Falls", "Aberdeen")),
    ("SD", "America/Denver", ("Rapid City",)),
)
CITY_ZONES = {(state, _place_key(city)): zone for state, zone, cities in _CITY_ROWS for city in cities}
NAVAJO_MARKERS = ("navajo nation", "navajo reservation")
GROUP_ZONES = {
    "eastern": frozenset(("America/New_York", "America/Detroit", "America/Indiana/Indianapolis", "America/Indiana/Marengo",
        "America/Indiana/Petersburg", "America/Indiana/Vevay", "America/Indiana/Vincennes", "America/Indiana/Winamac",
        "America/Kentucky/Louisville", "America/Kentucky/Monticello", "US/Eastern", "US/Michigan", "America/Fort_Wayne", "America/Indianapolis", "America/Louisville")),
    "central": frozenset(("America/Chicago", "America/Indiana/Knox", "America/Indiana/Tell_City", "America/Menominee",
        "America/North_Dakota/Beulah", "America/North_Dakota/Center", "America/North_Dakota/New_Salem", "US/Central", "America/Knox_IN")),
    "mountain": frozenset(("America/Denver", "America/Phoenix", "America/Boise", "US/Mountain", "US/Arizona", "America/Shiprock", "Navajo")),
    "pacific": frozenset(("America/Los_Angeles", "US/Pacific", "US/Pacific-New")),
    "alaska": frozenset(("America/Anchorage", "America/Juneau", "America/Metlakatla", "America/Nome", "America/Sitka", "America/Yakutat", "America/Adak", "US/Alaska", "US/Aleutian")),
    "hawaii": frozenset(("Pacific/Honolulu", "US/Hawaii", "HST", "Pacific/Johnston")),
}


def valid_timezone(value):
    value = str(value or "").strip(TRIM_CHARACTERS)
    return value if value in VALID_TIMEZONES else None


def timezone_group(zone):
    return next((group for group, zones in GROUP_ZONES.items() if zone in zones), "unknown")


def resolve_contact_timezone(*, country=None, state=None, city=None, address=None, profile_timezone=None):
    """Return a computed read model; never persist an inferred zone as confirmed."""
    zone = valid_timezone(profile_timezone)
    basis = "confirmed_profile" if zone else "unknown"
    if not zone and _place_key(country) in US_COUNTRIES:
        state = str(state or "").strip(TRIM_CHARACTERS).upper()
        state = STATE_CODES.get(state, state)
        navajo = state == "AZ" and any(marker in str(address or "").lower() for marker in NAVAJO_MARKERS)
        if not navajo:
            zone = STATE_ZONES.get(state)
            if zone:
                basis = "address_state"
            else:
                zone = CITY_ZONES.get((state, _place_key(city)))
                if zone:
                    basis = "address_city"
    return {"timezone": zone, "timezone_group": timezone_group(zone), "timezone_basis": basis,
            "timezone_needs_confirmation": basis != "confirmed_profile"}


def _sql_place_key(value):
    result = func.lower(func.trim(func.coalesce(value, ""), TRIM_CHARACTERS))
    for character in (" ", "-", ".", "'", "’"):
        result = func.replace(result, character, "")
    return result


def sql_timezone_group(zone):
    return case(*[(zone.in_(sorted(zones)), key) for key, zones in GROUP_ZONES.items()], else_="unknown")


def sql_contact_timezone(fields, profile_payload=None):
    """SQL equivalent used before filtering, facet counting and pagination.

    The caller supplies its currently authorized address expressions. Raw import
    metadata is not consulted, so later lead edits cannot resurrect a stale zone.
    """
    state = func.upper(func.trim(func.coalesce(fields["state"], ""), TRIM_CHARACTERS))
    is_us = _sql_place_key(fields["country"]).in_(sorted(US_COUNTRIES))
    city = _sql_place_key(fields["city"])

    def state_is(code):
        return state.in_((code, STATE_NAMES[code].upper()))

    navajo = and_(state_is("AZ"), or_(*(func.lower(func.coalesce(fields["address"], "")).contains(marker) for marker in NAVAJO_MARKERS)))
    address_allowed = and_(is_us, ~navajo)
    state_conditions = [(and_(address_allowed, state_is(code)), zone) for code, zone in STATE_ZONES.items()]
    city_conditions = [(and_(address_allowed, state_is(code), city.in_([_place_key(value) for value in cities])), zone)
                       for code, zone, cities in _CITY_ROWS]
    derived_zone = case(*(state_conditions + city_conditions), else_=None)
    derived_basis = case(*[(condition, "address_state") for condition, _ in state_conditions],
                         *[(condition, "address_city") for condition, _ in city_conditions], else_="unknown")
    if profile_payload is not None:
        safe_payload = case((func.json_valid(profile_payload), profile_payload), else_="{}")
        manual = case((func.json_type(safe_payload, "$.timezone") == "text", func.trim(func.json_extract(safe_payload, "$.timezone"), TRIM_CHARACTERS)), else_=None)
        manual_valid = manual.in_(sorted(VALID_TIMEZONES))
        zone = case((manual_valid, manual), else_=derived_zone)
        basis = case((manual_valid, "confirmed_profile"), else_=derived_basis)
        needs_confirmation = case((manual_valid, False), else_=True)
    else:
        zone, basis, needs_confirmation = derived_zone, derived_basis, literal(True)
    group = sql_timezone_group(zone)
    return {"timezone": zone, "timezone_group": group, "timezone_basis": basis,
            "timezone_needs_confirmation": needs_confirmation}
