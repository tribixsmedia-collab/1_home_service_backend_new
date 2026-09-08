"""
What has to stay true about the map switch.

The theme running through these: a half-finished or refused Google setup must
degrade to the free map, never to a blank one. An admin who pastes a key with
the wrong APIs enabled should see working maps and a clear message, not three
grey boxes across two apps.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import plus_codes
from .config import map_config, tile_session_for
from .google import GoogleMapsError, Place
from .models import MapSettings

KEY = 'AIzaTestKey'
SESSION = 'session-token-abc'


def _session_in_two_weeks():
    return SESSION, timezone.now() + timedelta(days=14)


class MapSettingsModelTests(TestCase):
    def test_get_solo_makes_one_row_and_reuses_it(self):
        first = MapSettings.get_solo()
        second = MapSettings.get_solo()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MapSettings.objects.count(), 1)

    def test_defaults_to_the_free_map(self):
        settings_row = MapSettings.get_solo()
        self.assertEqual(settings_row.provider, MapSettings.Provider.FREE)
        self.assertFalse(settings_row.is_google)

    def test_google_without_a_key_reads_back_as_free(self):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.save()

        self.assertFalse(settings_row.is_google)
        self.assertTrue(settings_row.is_awaiting_key)
        self.assertEqual(settings_row.effective_provider, MapSettings.Provider.FREE)

    def test_google_with_a_key_is_google(self):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()

        self.assertTrue(settings_row.is_google)
        self.assertFalse(settings_row.is_awaiting_key)

    def test_whitespace_is_not_a_key(self):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = '   '
        settings_row.save()

        self.assertFalse(settings_row.is_google)

    def test_an_expired_tile_session_is_not_live(self):
        settings_row = MapSettings.get_solo()
        settings_row.tile_session = SESSION
        settings_row.tile_session_expires_at = timezone.now() - timedelta(minutes=1)

        self.assertFalse(settings_row.has_live_tile_session())


class MapConfigTests(TestCase):
    def _configure_google(self):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()
        return settings_row

    def test_free_config_carries_the_keyless_tiles(self):
        config = map_config()

        self.assertEqual(config['provider'], MapSettings.Provider.FREE)
        self.assertEqual(config['tile_url'], MapSettings.FREE_TILE_URL)
        self.assertEqual(config['subdomains'], MapSettings.FREE_SUBDOMAINS)
        self.assertIn('OpenStreetMap', config['attribution'])
        self.assertTrue(config['retina_tiles'])

    def test_the_free_tiles_need_no_key_and_carry_no_watermark(self):
        # CARTO answers 200 while stamping "API KEY REQUIRED" over the tile,
        # and openstreetmap.org answers 418 to apps, so neither may come back.
        url = MapSettings.FREE_TILE_URL

        self.assertNotIn('key=', url)
        self.assertNotIn('cartocdn.com', url)
        self.assertNotIn('tile.openstreetmap.org', url)

    @patch('maps.config.create_tile_session', side_effect=lambda *a, **kw: _session_in_two_weeks())
    def test_google_config_fills_in_session_and_key_only(self, _mock):
        self._configure_google()

        config = map_config()

        self.assertEqual(config['provider'], MapSettings.Provider.GOOGLE)
        self.assertIn(f'session={SESSION}', config['tile_url'])
        self.assertIn(f'key={KEY}', config['tile_url'])
        # The renderer still has to substitute these itself.
        self.assertIn('{z}', config['tile_url'])
        self.assertIn('{x}', config['tile_url'])
        self.assertIn('{y}', config['tile_url'])

    @patch('maps.config.create_tile_session', side_effect=lambda *a, **kw: _session_in_two_weeks())
    def test_the_tile_session_is_minted_once_and_then_reused(self, mock_create):
        self._configure_google()

        map_config()
        map_config()

        self.assertEqual(mock_create.call_count, 1)
        self.assertEqual(MapSettings.get_solo().tile_session, SESSION)

    @patch('maps.config.create_tile_session',
           side_effect=GoogleMapsError('Map Tiles API has not been used'))
    def test_a_refused_session_falls_back_to_the_free_map(self, _mock):
        self._configure_google()

        config = map_config()

        self.assertEqual(config['provider'], MapSettings.Provider.FREE)
        self.assertEqual(config['tile_url'], MapSettings.FREE_TILE_URL)

    @patch('maps.config.create_tile_session', side_effect=lambda *a, **kw: _session_in_two_weeks())
    def test_no_session_is_requested_while_the_free_map_is_on(self, mock_create):
        map_config()

        mock_create.assert_not_called()

    @patch('maps.config.create_tile_session', side_effect=lambda *a, **kw: _session_in_two_weeks())
    def test_tile_session_for_returns_nothing_on_the_free_map(self, _mock):
        self.assertIsNone(tile_session_for(MapSettings.get_solo()))


class MapConfigEndpointTests(TestCase):
    url = '/api/maps/config/'

    def test_open_to_anyone(self):
        # The picker is reachable from guest browsing on the web, so this
        # cannot require a token.
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'FREE')

    def test_reverse_url_matches(self):
        self.assertEqual(reverse('map-config'), self.url)

    @patch('maps.config.create_tile_session', side_effect=lambda *a, **kw: _session_in_two_weeks())
    def test_serves_google_once_configured(self, _mock):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()

        payload = self.client.get(self.url).json()

        self.assertEqual(payload['provider'], 'GOOGLE')
        self.assertIn('tile.googleapis.com', payload['tile_url'])
        self.assertFalse(payload['retina_tiles'])


class ReverseGeocodeEndpointTests(TestCase):
    url = '/api/maps/reverse-geocode/'

    def test_rejects_a_missing_point(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)

    def test_rejects_a_point_off_the_globe(self):
        response = self.client.get(self.url, {'lat': '95', 'lng': '80'})

        self.assertEqual(response.status_code, 400)

    @patch('maps.views._nominatim_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai', 'Chennai'))
    def test_uses_the_free_service_on_the_free_map(self, mock_free):
        response = self.client.get(self.url, {'lat': '13.08', 'lng': '80.27'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['address'], '12 Anna Salai, Chennai')
        self.assertEqual(response.json()['provider'], 'nominatim')
        mock_free.assert_called_once()

    @patch('maps.views.google_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai 600002', 'Chennai'))
    def test_uses_google_once_configured(self, mock_google):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()

        payload = self.client.get(self.url, {'lat': '13.08', 'lng': '80.27'}).json()

        self.assertEqual(payload['provider'], 'google')
        self.assertEqual(payload['address'], '12 Anna Salai, Chennai 600002')
        mock_google.assert_called_once()

    @patch('maps.views._nominatim_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai', 'Chennai'))
    @patch('maps.views.google_reverse_geocode',
           side_effect=GoogleMapsError('Geocoding API has not been used'))
    def test_a_refused_google_key_still_returns_an_address(self, _mock_google, mock_free):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()

        payload = self.client.get(self.url, {'lat': '13.08', 'lng': '80.27'}).json()

        self.assertEqual(payload['provider'], 'nominatim')
        self.assertEqual(payload['address'], '12 Anna Salai, Chennai')
        mock_free.assert_called_once()
