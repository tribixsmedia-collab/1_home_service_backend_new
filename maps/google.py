"""
Every outbound call to Google Maps Platform lives here.

Three of its APIs are used, and they have to be enabled separately on the same
key, which is the single most common reason a pasted key half-works:

  Maps JavaScript API  -- the dashboard's own maps, loaded in the browser.
  Map Tiles API        -- raster tiles the customer app draws in flutter_map.
  Geocoding API        -- turning the pin's lat/long into a street address.

Nothing here raises: a map that cannot reach Google falls back to the free
one rather than taking a page down with it.
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import NamedTuple

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)


class Place(NamedTuple):
    """
    What a geocoder found: the address to show, and the town to say it in.

    `locality` exists for Plus Codes. "7M5237MC+37" is unambiguous but nobody
    reads it out; "37MC+37, Chennai" is the same square in a form a customer
    can repeat down a phone line, and the town half of that has to come from
    the geocoder. It is '' when the geocoder did not name one.
    """

    address: str = ''
    locality: str = ''


CREATE_SESSION_URL = 'https://tile.googleapis.com/v1/createSession'
GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'

TIMEOUT = 8


class GoogleMapsError(Exception):
    """Google answered, and the answer was no. Carries what it said."""


# ---------------------------------------------------------------------------
# Map Tiles API
# ---------------------------------------------------------------------------

def create_tile_session(api_key, map_type='roadmap', language='en-US', region='IN'):
    """
    Ask for a Map Tiles session token.

    Returns (token, expires_at). Raises GoogleMapsError with Google's own
    wording when the key is rejected, so the dashboard can show the admin the
    real reason rather than "something went wrong".
    """
    try:
        response = requests.post(
            CREATE_SESSION_URL,
            params={'key': api_key},
            json={
                'mapType': map_type,
                'language': language,
                'region': region,
                # Retina tiles: phones are high-density, and a 1x tile on one
                # renders roads and labels hairline-thin.
                'highDpi': True,
                'scale': 'scaleFactor2x',
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GoogleMapsError(f'Could not reach Google ({exc.__class__.__name__}).')

    if response.status_code != 200:
        raise GoogleMapsError(_error_text(response))

    data = response.json()
    token = data.get('session')
    if not token:
        raise GoogleMapsError('Google returned no session token.')

    # `expiry` is a unix timestamp as a string, roughly two weeks out. An hour
    # is shaved off so a token is never handed to an app moments before it dies.
    try:
        expires_at = datetime.fromtimestamp(
            int(data['expiry']) - 3600, tz=dt_timezone.utc,
        )
    except (KeyError, TypeError, ValueError):
        expires_at = timezone.now() + timedelta(days=1)

    return token, expires_at


# ---------------------------------------------------------------------------
# Geocoding API
# ---------------------------------------------------------------------------

def reverse_geocode(api_key, latitude, longitude, language='en'):
    """A Place for a point, or None when Google has nothing there."""
    data = _geocode_request(
        {'latlng': f'{latitude},{longitude}', 'key': api_key, 'language': language}
    )
    if data is None:
        return None

    result = (data.get('results') or [None])[0]
    if not result:
        return None
    return Place(
        address=result.get('formatted_address') or '',
        locality=_locality_from(result.get('address_components') or []),
    )


def geocode(api_key, query, language='en', region='in'):
    """
    Where a place name is, as (latitude, longitude), or None.

    The one caller is Plus Code lookup: a customer who pastes
    "37MC+37, Chennai" has given a code that only means something within a
    degree or so of Chennai, so the town has to be turned into a point before
    the code can be completed.
    """
    data = _geocode_request({
        'address': query,
        'key': api_key,
        'language': language,
        # Nudges ambiguous names towards this country rather than a namesake
        # somewhere else. A hint only -- it does not exclude anywhere.
        'region': region,
    })
    if data is None:
        return None

    result = (data.get('results') or [None])[0]
    if not result:
        return None
    location = (result.get('geometry') or {}).get('location') or {}
    try:
        return float(location['lat']), float(location['lng'])
    except (KeyError, TypeError, ValueError):
        return None


def _geocode_request(params):
    """
    One call to the Geocoding API. Returns the payload, or None for
    ZERO_RESULTS; raises GoogleMapsError on anything else, so a key with the
    API switched off is reported rather than read as "nowhere".
    """
    try:
        response = requests.get(GEOCODE_URL, params=params, timeout=TIMEOUT)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GoogleMapsError(f'Could not reach Google ({exc.__class__.__name__}).')

    status = data.get('status')
    if status == 'ZERO_RESULTS':
        return None
    if status != 'OK':
        raise GoogleMapsError(
            data.get('error_message') or f'Geocoding API said {status}.'
        )
    return data


# Most specific first: a Plus Code reads best against the smallest place a
# customer would still recognise the name of.
LOCALITY_COMPONENTS = (
    'locality',
    'postal_town',
    'sublocality',
    'administrative_area_level_3',
    'administrative_area_level_2',
    'administrative_area_level_1',
)


def _locality_from(components):
    """The town out of Google's address_components, or ''."""
    by_type = {}
    for component in components:
        for component_type in component.get('types') or []:
            by_type.setdefault(component_type, component.get('long_name') or '')

    for component_type in LOCALITY_COMPONENTS:
        if by_type.get(component_type):
            return by_type[component_type]
    return ''


# ---------------------------------------------------------------------------
# Key diagnostics, for the dashboard settings page
# ---------------------------------------------------------------------------

def check_key(api_key):
    """
    Try the two APIs that can be tested from a server and report on each.

    Returns [{'name', 'ok', 'detail'}, ...]. The Maps JavaScript API is not in
    the list: it only exists in a browser, so the settings page tests that one
    by drawing a real map with the key and listening for Google's rejection.
    """
    checks = []

    try:
        create_tile_session(api_key)
    except GoogleMapsError as exc:
        checks.append({
            'name': 'Map Tiles API',
            'ok': False,
            'detail': str(exc),
        })
    else:
        checks.append({
            'name': 'Map Tiles API',
            'ok': True,
            'detail': 'Serving tiles to the customer app.',
        })

    try:
        # Chennai. Any point does; this only has to prove the key is allowed.
        reverse_geocode(api_key, 13.0827, 80.2707)
    except GoogleMapsError as exc:
        checks.append({
            'name': 'Geocoding API',
            'ok': False,
            'detail': str(exc),
        })
    else:
        checks.append({
            'name': 'Geocoding API',
            'ok': True,
            'detail': 'Turning map pins into addresses.',
        })

    return checks


def _error_text(response):
    """Google's own error message when there is one, else the status code."""
    try:
        payload = response.json()
    except ValueError:
        return f'Google answered {response.status_code}.'

    error = payload.get('error') or {}
    message = error.get('message') or payload.get('error_message')
    if message:
        return message
    return f'Google answered {response.status_code}.'
