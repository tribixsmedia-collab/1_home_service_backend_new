"""
The three endpoints the mobile apps call.

All public, like branding: the location picker is reachable from the guest
browsing flow on the web, before anyone has a token.
"""

import logging

import requests
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import plus_codes
from .config import map_config
from .google import GoogleMapsError, Place
from .google import geocode as google_geocode
from .google import reverse_geocode as google_reverse_geocode
from .models import MapSettings

logger = logging.getLogger(__name__)

NOMINATIM_REVERSE_URL = 'https://nominatim.openstreetmap.org/reverse'
NOMINATIM_SEARCH_URL = 'https://nominatim.openstreetmap.org/search'

# Nominatim's usage policy requires an identifying User-Agent and blocks
# requests without one.
NOMINATIM_HEADERS = {'User-Agent': 'HomeServiceBackend/1.0'}


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def map_config_view(request):
    """
    GET /api/maps/config/

    What to draw. The app caches this and swaps its tile URL -- there is no
    Google-specific code path in the app beyond showing Google's attribution.

    On the Google option this hands out a tile URL with the key in it. That is
    how client-side maps work everywhere -- the key is visible in any app that
    draws its own tiles -- which is why the dashboard tells the admin to
    restrict the key in Google Cloud rather than pretending it stays secret.
    """
    return Response(map_config())


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def reverse_geocode_view(request):
    """
    GET /api/maps/reverse-geocode/?lat=..&lng=..

    The address under the customer's pin. Proxied rather than called from the
    app for three reasons: the Google key stays on the server, the app keeps
    one code path whichever provider is on, and Nominatim's rate limit and
    User-Agent rule are honoured in one place instead of on every phone.
    """
    try:
        latitude = float(request.query_params.get('lat', ''))
        longitude = float(request.query_params.get('lng', ''))
    except (TypeError, ValueError):
        return Response(
            {'detail': 'lat and lng are required, as numbers.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return Response(
            {'detail': 'lat and lng are out of range.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    settings_row = MapSettings.get_solo()

    if settings_row.is_google:
        try:
            place = google_reverse_geocode(settings_row.key, latitude, longitude)
        except GoogleMapsError as exc:
            # Geocoding API not enabled, quota gone, key restricted: the
            # customer should still get an address, so fall through to the
            # free one rather than handing the app an error.
            logger.warning('Google reverse geocode failed: %s', exc)
        else:
            return Response(
                _located(latitude, longitude, place or Place(), 'google')
            )

    return Response(_located(
        latitude, longitude,
        _nominatim_reverse_geocode(latitude, longitude) or Place(),
        'nominatim',
    ))


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def plus_code_view(request):
    """
    GET /api/maps/plus-code/?code=..&lat=..&lng=..

    The other direction: a Plus Code the customer typed or pasted, turned back
    into a point the map can move to.

    A full code -- "7M5237MC+37" -- resolves on arithmetic alone, offline, and
    is the case worth optimising for. A short one -- "37MC+37, Chennai" --
    repeats roughly every degree, so it needs somewhere to be read against.
    Two things are tried for that, in order:

      the town written after the code, geocoded here;
      `lat`/`lng`, which the app sends as wherever its map is pointing.

    Failing both, the customer is asked for the town by name rather than being
    silently dropped a degree away from where they meant.
    """
    code, locality = plus_codes.split_code_and_locality(
        request.query_params.get('code', '')
    )

    reference = _reference_point(request, locality) if plus_codes.is_short(code) else None
    try:
        area = plus_codes.resolve(code, *(reference or (None, None)))
    except plus_codes.PlusCodeError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    latitude = area.latitude_center
    longitude = area.longitude_center
    full_code = plus_codes.encode(latitude, longitude, area.code_length)

    # Name the square we landed on, so the customer can see it is the right
    # place before they confirm. A geocoder that is down costs them nothing.
    place = _describe(latitude, longitude)

    return Response({
        'latitude': latitude,
        'longitude': longitude,
        'plus_code': full_code,
        'plus_code_local': plus_codes.local_form(full_code),
        'locality': place.locality or locality,
        'plus_code_display': plus_codes.display_form(
            full_code, place.locality or locality,
        ),
        'address': place.address or None,
        # How far across the square is, in degrees. The app draws it rather
        # than pretending a 14-metre code is a single point.
        'code_length': area.code_length,
        'latitude_lo': area.latitude_lo,
        'longitude_lo': area.longitude_lo,
        'latitude_hi': area.latitude_hi,
        'longitude_hi': area.longitude_hi,
    })


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------

def _located(latitude, longitude, place, provider):
    """
    The one answer shape for "what is at this point?".

    The Plus Code is worked out here rather than asked of anyone: it is
    arithmetic on the lat/long we were already given, so it is present even
    when every geocoder on earth is unreachable and `address` is null.
    """
    code = plus_codes.plus_code_for(latitude, longitude)
    return {
        'address': place.address or None,
        'provider': provider,
        'plus_code': code,
        'plus_code_local': plus_codes.local_form(code),
        'locality': place.locality,
        'plus_code_display': plus_codes.display_form(code, place.locality),
    }


def _reference_point(request, locality):
    """
    Somewhere to read a short code against: the town it names, else the map.

    Returns (latitude, longitude) or None.
    """
    if locality:
        point = _geocode(locality)
        if point:
            return point

    try:
        latitude = float(request.query_params['lat'])
        longitude = float(request.query_params['lng'])
    except (KeyError, TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _describe(latitude, longitude):
    """Whatever the configured geocoder calls this point. Never raises."""
    settings_row = MapSettings.get_solo()
    if settings_row.is_google:
        try:
            return google_reverse_geocode(settings_row.key, latitude, longitude) or Place()
        except GoogleMapsError as exc:
            logger.warning('Google reverse geocode failed: %s', exc)
    return _nominatim_reverse_geocode(latitude, longitude) or Place()


def _geocode(query):
    """A place name turned into a point, by whichever geocoder is on."""
    settings_row = MapSettings.get_solo()
    if settings_row.is_google:
        try:
            point = google_geocode(settings_row.key, query)
        except GoogleMapsError as exc:
            logger.warning('Google geocode failed: %s', exc)
        else:
            if point:
                return point
    return _nominatim_geocode(query)


def _nominatim_reverse_geocode(latitude, longitude):
    """OpenStreetMap's free service. Returns a Place, or None."""
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={
                'format': 'json',
                'lat': latitude,
                'lon': longitude,
                # Needed for the locality: `display_name` alone is one long
                # string with no way to pick the town out of it.
                'addressdetails': 1,
            },
            headers=NOMINATIM_HEADERS,
            timeout=8,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    return Place(
        address=payload.get('display_name') or '',
        locality=_nominatim_locality(payload.get('address') or {}),
    )


def _nominatim_geocode(query):
    """A place name turned into a point by OpenStreetMap, or None."""
    try:
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params={'format': 'json', 'q': query, 'limit': 1},
            headers=NOMINATIM_HEADERS,
            timeout=8,
        )
        if response.status_code != 200:
            return None
        results = response.json()
    except (requests.RequestException, ValueError):
        return None

    if not results:
        return None
    try:
        return float(results[0]['lat']), float(results[0]['lon'])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# Most specific first, matching the order used for Google's components: a
# Plus Code reads best against the smallest place whose name is recognised.
NOMINATIM_LOCALITY_KEYS = (
    'city', 'town', 'village', 'municipality', 'suburb',
    'city_district', 'county', 'state_district', 'state',
)


def _nominatim_locality(address):
    """The town out of Nominatim's address breakdown, or ''."""
    for key in NOMINATIM_LOCALITY_KEYS:
        if address.get(key):
            return address[key]
    return ''
