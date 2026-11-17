"""Conservative, address-based US calling zones without changing stored evidence.

The SQL and Python read models use the same reviewed state/city tables. A phone
area code is deliberately never an input: a business may keep a ported number.
Split-zone states require a reviewed city or an existing explicit IANA override.
"""

import json
from collections import defaultdict
from zoneinfo import available_timezones

from sqlalchemy import and_, case, func, literal, or_

from services.merchant_identity import has_concrete_name_and_address


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


ADDRESS_FIELDS = ("country", "state", "city", "address")
US_IANA_ZONES = frozenset().union(*GROUP_ZONES.values()) & VALID_TIMEZONES


def address_timezone_evidence(payload):
    """Only consume normalized import evidence, never an arbitrary raw timezone."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    metadata = payload.get("prospect_source") if isinstance(payload, dict) else None
    return metadata.get("address_timezone") if isinstance(metadata, dict) else None


def import_address_timezone(zone, record, source_url):
    if zone is None or zone == "":
        return None
    if not isinstance(zone, str):
        raise ValueError("IANA时区需要填写有效的美国时区名称")
    zone = zone.strip()
    location = [getattr(record, field, None) or "" for field in ADDRESS_FIELDS]
    country, state, city, address = location
    state_code = STATE_CODES.get(state.strip().upper(), state.strip().upper())
    if (zone not in US_IANA_ZONES or _place_key(country) not in US_COUNTRIES
            or state_code not in STATE_NAMES or not city.strip() or not has_concrete_name_and_address(record) or not source_url):
        raise ValueError("IANA时区需要有效的美国时区、完整门店地址（国家、州、城市、街道）和来源URL")
    if state_code in STATE_ZONES and timezone_group(STATE_ZONES[state_code]) != timezone_group(zone):
        raise ValueError("IANA时区与门店所在州不一致")
    return {"zone": zone, "location": location}


def resolve_contact_timezone(*, country=None, state=None, city=None, address=None, profile_timezone=None, address_evidence=None):
    """A reviewed source location remains inferred, including after conversion."""
    zone = valid_timezone(profile_timezone)
    basis = "confirmed_profile" if zone else "unknown"
    if not zone and isinstance(address_evidence, dict):
        if address_evidence.get("location") == [country or "", state or "", city or "", address or ""]:
            candidate = address_evidence.get("zone")
            if isinstance(candidate, str) and candidate in US_IANA_ZONES:
                zone, basis = candidate, "address_source"
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


def _sql_address_rules(fields):
    state = func.upper(func.trim(func.coalesce(fields["state"], ""), TRIM_CHARACTERS))
    is_us = _sql_place_key(fields["country"]).in_(sorted(US_COUNTRIES))
    city = _sql_place_key(fields["city"])
    states_by_zone = defaultdict(list)
    for state_code, zone in STATE_ZONES.items():
        states_by_zone[zone].extend((state_code, STATE_NAMES[state_code].upper()))
    state_rules = [(state.in_(codes), zone) for zone, codes in states_by_zone.items()]
    city_rules = []
    for state_code, zone, cities in _CITY_ROWS:
        matches = and_(state.in_((state_code, STATE_NAMES[state_code].upper())), city.in_([_place_key(c) for c in cities]))
        if state_code == "AZ":
            street = func.lower(func.coalesce(fields["address"], ""))
            matches = and_(matches, *(~street.contains(marker) for marker in NAVAJO_MARKERS))
        city_rules.append((matches, zone))
    return is_us, state_rules, city_rules


def _sql_source_zone(fields, payload):
    # Check the small locator first; old rows have no such evidence. An address
    # edit invalidates the imported inference in both pool and converted leads.
    document = case((func.json_valid(payload), payload), else_="{}")
    path = "$.prospect_source.address_timezone"
    candidate = func.json_extract(document, path + ".zone")
    loc = func.json_array(*(func.coalesce(fields[field], "") for field in ADDRESS_FIELDS))
    return case((candidate.in_(sorted(US_IANA_ZONES)),
                 case((func.json_extract(document, path + ".location") == loc, candidate))))


def _sql_manual_zone(payload):
    document = case((func.json_valid(payload), payload), else_="{}")
    candidate = func.trim(func.json_extract(document, "$.timezone"), TRIM_CHARACTERS)
    return case((candidate.in_(sorted(VALID_TIMEZONES)), candidate))


def sql_matches_contact_zones(fields, zones, *, source_payload=None, profile_payload=None):
    """Filter on exact IANA zones without expanding the timezone CASE per group."""
    selected = frozenset(zones) & VALID_TIMEZONES
    if not selected:
        return literal(False)
    is_us, state_rules, city_rules = _sql_address_rules(fields)
    rules = [condition for condition, zone in (*state_rules, *city_rules) if zone in selected]
    derived = and_(is_us, or_(*rules)) if rules else literal(False)
    if source_payload is None:
        source_payload = profile_payload  # Converted leads keep their import evidence in the profile.
    for payload, manual in ((source_payload, False), (profile_payload, True)):
        if payload is not None:
            explicit = _sql_manual_zone(payload) if manual else _sql_source_zone(fields, payload)
            # NULL falls back, a different valid manual zone suppresses inference.
            derived = func.coalesce(explicit.in_(sorted(selected)), derived)
    return derived


def sql_contact_timezone(fields, profile_payload=None, *, source_payload=None):
    """Resolve only the authorized location. Source evidence must match it exactly."""
    is_us, state_rules, city_rules = _sql_address_rules(fields)
    zone = case((is_us, case(*(state_rules + city_rules))))
    inferred_basis = case(*[(condition, "address_state") for condition, _ in state_rules],
                          *[(condition, "address_city") for condition, _ in city_rules], else_="unknown")
    basis = case((is_us, inferred_basis), else_="unknown")
    needs_confirmation = literal(True)
    if source_payload is None:
        source_payload = profile_payload
    if source_payload is not None:
        source = _sql_source_zone(fields, source_payload)
        zone = func.coalesce(source, zone)
        basis = case((source.is_not(None), "address_source"), else_=basis)
    if profile_payload is not None:
        manual = _sql_manual_zone(profile_payload)
        zone = func.coalesce(manual, zone)
        basis = case((manual.is_not(None), "confirmed_profile"), else_=basis)
        needs_confirmation = manual.is_(None)
    return {"timezone": zone, "timezone_group": sql_timezone_group(zone), "timezone_basis": basis,
            "timezone_needs_confirmation": needs_confirmation}
