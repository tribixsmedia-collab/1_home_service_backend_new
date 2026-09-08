"""
What has to stay true about Plus Codes.

Two separate things are being defended here.

The first is the arithmetic, and those tests are not ours: they are Google's
own published vectors from the open-location-code repository, kept verbatim.
If maps/plus_codes.py ever drifts from the spec, a code written by this
backend stops matching the one Google Maps shows for the same doorway, which
is the entire point of using Plus Codes and would otherwise fail silently.

The second is the promise the endpoints make: that a Plus Code is available
even when every geocoder on earth is unreachable, because it is arithmetic on
a pin we already hold rather than an answer somebody else has to give us.
"""

from unittest.mock import patch

from django.test import TestCase

from . import plus_codes
from .google import Place, _locality_from
from .models import MapSettings

KEY = 'AIzaTestKey'

# Chennai, near Anna Salai. Used wherever a test needs a plausible point.
CHENNAI = (13.0827, 80.2707)


class EncodingTests(TestCase):
    """Google's published encoding vectors: latitude, longitude, length, code."""

    VECTORS = [
        (20.375, 2.775, 6, '7FG49Q00+'),
        (20.3700625, 2.7821875, 10, '7FG49QCJ+2V'),
        (20.3701125, 2.782234375, 11, '7FG49QCJ+2VX'),
        (20.3701135, 2.78223535, 13, '7FG49QCJ+2VXGJ'),
        (47.0000625, 8.0000625, 10, '8FVC2222+22'),
        (-41.2730625, 174.7859375, 10, '4VCPPQGP+Q9'),
        (0.5, -179.5, 4, '62G20000+'),
        (-89.9999375, -179.9999375, 10, '22222222+22'),
        (20.5, 2.5, 4, '7FG40000+'),
        (90, 1, 10, 'CFX3X2X2+X2'),
    ]

    def test_matches_googles_published_vectors(self):
        for latitude, longitude, length, expected in self.VECTORS:
            with self.subTest(code=expected):
                self.assertEqual(
                    plus_codes.encode(latitude, longitude, length), expected,
                )

    def test_every_code_decodes_back_to_itself(self):
        for _, _, _, code in self.VECTORS:
            with self.subTest(code=code):
                area = plus_codes.decode(code)
                self.assertEqual(
                    plus_codes.encode(
                        area.latitude_center, area.longitude_center,
                        area.code_length,
                    ),
                    code,
                )

    def test_the_north_pole_encodes_to_a_code_that_can_be_decoded(self):
        # Latitude 90 is the top edge of no square at all, so it has to be
        # nudged into the one below or it produces a code off the map.
        area = plus_codes.decode(plus_codes.encode(90, 1))

        self.assertLess(area.latitude_center, 90)

    def test_longitude_wraps_at_the_antimeridian(self):
        self.assertEqual(
            plus_codes.encode(1, 180), plus_codes.encode(1, -180),
        )

    def test_ten_digits_is_about_fourteen_metres(self):
        area = plus_codes.decode(plus_codes.encode(*CHENNAI))

        # 0.000125 degrees, which is the resolution the tenth digit leaves.
        self.assertAlmostEqual(area.latitude_hi - area.latitude_lo, 0.000125)

    def test_an_odd_short_length_is_refused(self):
        with self.assertRaises(plus_codes.PlusCodeError):
            plus_codes.encode(*CHENNAI, code_length=7)


class ValidityTests(TestCase):
    """Google's published validity vectors: code, valid, short, full."""

    VECTORS = [
        ('8FWC2345+G6', True, False, True),
        ('8FWC2345+G6G', True, False, True),
        ('8fwc2345+', True, False, True),
        ('8FWCX400+', True, False, True),
        ('WC2345+G6g', True, True, False),
        ('2345+G6', True, True, False),
        ('45+G6', True, True, False),
        ('+G6', True, True, False),
        ('G+', False, False, False),
        ('+', False, False, False),
        ('8FWC2345+G', False, False, False),
        ('8FWC2_45+G6', False, False, False),
        ('8FWC2345+G6+', False, False, False),
        ('8FWC2300+G6', False, False, False),
        ('WC2300+G6g', False, False, False),
        ('WC2345+G', False, False, False),
    ]

    def test_matches_googles_published_vectors(self):
        for code, valid, short, full in self.VECTORS:
            with self.subTest(code=code):
                self.assertEqual(plus_codes.is_valid(code), valid)
                self.assertEqual(plus_codes.is_short(code), short)
                self.assertEqual(plus_codes.is_full(code), full)

    def test_nothing_is_not_a_code(self):
        for value in ['', None, 0, [], '   ']:
            with self.subTest(value=value):
                self.assertFalse(plus_codes.is_valid(value))

    def test_a_decode_of_something_unreadable_says_so_in_words(self):
        with self.assertRaises(plus_codes.PlusCodeError):
            plus_codes.decode('not a code')


class ShortenTests(TestCase):
    """Google's published shortening vectors: code, latitude, longitude, short."""

    VECTORS = [
        ('9C3W9QCJ+2VX', 51.3701125, -1.217765625, '+2VX'),
        ('9C3W9QCJ+2VX', 51.3708675, -1.217765625, 'CJ+2VX'),
        ('9C3W9QCJ+2VX', 51.3701125, -1.220304375, 'CJ+2VX'),
        ('9C3W9QCJ+2VX', 51.44, -1.221, '9QCJ+2VX'),
        ('9C3W9QCJ+2VX', 51.5, -1.4, '9QCJ+2VX'),
        ('8FJFW222+', 42.899, 9.012, '22+'),
        ('796RXG22+', 14.95125, -23.5001, '22+'),
    ]

    def test_shortens_to_googles_published_vectors(self):
        for code, latitude, longitude, expected in self.VECTORS:
            with self.subTest(code=code):
                self.assertEqual(
                    plus_codes.shorten(code, latitude, longitude), expected,
                )

    def test_every_shortened_code_recovers_to_the_original(self):
        for code, latitude, longitude, short in self.VECTORS:
            with self.subTest(code=short):
                self.assertEqual(
                    plus_codes.recover_nearest(short, latitude, longitude), code,
                )

    def test_a_full_code_recovers_to_itself(self):
        self.assertEqual(
            plus_codes.recover_nearest('7M5237MC+37', *CHENNAI), '7M5237MC+37',
        )


class DisplayFormTests(TestCase):
    """The three ways a code gets written, and which goes where."""

    def test_a_point_becomes_a_full_code(self):
        code = plus_codes.plus_code_for(*CHENNAI)

        self.assertTrue(plus_codes.is_full(code))
        self.assertEqual(len(code), 11)

    def test_a_missing_pin_is_an_empty_code_not_an_error(self):
        # Most callers hand this a nullable column straight off a model.
        self.assertEqual(plus_codes.plus_code_for(None, None), '')
        self.assertEqual(plus_codes.plus_code_for(13.08, None), '')
        self.assertEqual(plus_codes.plus_code_for('', ''), '')

    def test_a_decimal_from_the_database_encodes(self):
        from decimal import Decimal

        self.assertEqual(
            plus_codes.plus_code_for(Decimal('13.0827'), Decimal('80.2707')),
            plus_codes.plus_code_for(13.0827, 80.2707),
        )

    def test_the_local_form_drops_the_area_code(self):
        self.assertEqual(plus_codes.local_form('7M5237MC+37'), '37MC+37')

    def test_a_padded_code_has_no_local_form(self):
        # "0000+" would be nonsense to show anyone.
        self.assertEqual(plus_codes.local_form('7FG40000+'), '')

    def test_a_short_code_has_no_local_form_to_take(self):
        self.assertEqual(plus_codes.local_form('37MC+37'), '')

    def test_a_town_makes_the_short_readable_form(self):
        self.assertEqual(
            plus_codes.display_form('7M5237MC+37', 'Chennai'), '37MC+37, Chennai',
        )

    def test_without_a_town_the_full_code_is_shown(self):
        # Longer, but it still resolves anywhere -- which the short one does not.
        self.assertEqual(
            plus_codes.display_form('7M5237MC+37', ''), '7M5237MC+37',
        )

    def test_nothing_displays_as_nothing(self):
        self.assertEqual(plus_codes.display_form('', 'Chennai'), '')


class ParsingTests(TestCase):
    """Whatever the customer pasted, pulled apart."""

    def test_a_code_with_a_town_after_a_comma(self):
        self.assertEqual(
            plus_codes.split_code_and_locality('37MC+37, Chennai'),
            ('37MC+37', 'Chennai'),
        )

    def test_a_code_with_a_town_and_no_comma(self):
        self.assertEqual(
            plus_codes.split_code_and_locality('37MC+37 Chennai'),
            ('37MC+37', 'Chennai'),
        )

    def test_a_bare_full_code(self):
        self.assertEqual(
            plus_codes.split_code_and_locality('7M5237MC+37'),
            ('7M5237MC+37', ''),
        )

    def test_lower_case_is_lifted(self):
        self.assertEqual(
            plus_codes.split_code_and_locality('37mc+37, chennai'),
            ('37MC+37', 'chennai'),
        )

    def test_a_whole_line_off_the_share_sheet(self):
        code, locality = plus_codes.split_code_and_locality(
            '37MC+37, Teynampet, Chennai, Tamil Nadu'
        )

        self.assertEqual(code, '37MC+37')
        self.assertEqual(locality, 'Teynampet, Chennai, Tamil Nadu')

    def test_surrounding_space_is_ignored(self):
        self.assertEqual(
            plus_codes.split_code_and_locality('  37MC+37 ,  Chennai  '),
            ('37MC+37', 'Chennai'),
        )

    def test_nothing_parses_to_nothing(self):
        self.assertEqual(plus_codes.split_code_and_locality(''), ('', ''))
        self.assertEqual(plus_codes.split_code_and_locality(None), ('', ''))


class ResolveTests(TestCase):
    def test_a_full_code_needs_no_reference_point(self):
        area = plus_codes.resolve('7M5237MC+37')

        self.assertAlmostEqual(area.latitude_center, 13.0827, places=3)
        self.assertAlmostEqual(area.longitude_center, 80.2707, places=3)

    def test_a_short_code_reads_against_the_reference_point(self):
        full = plus_codes.plus_code_for(*CHENNAI)
        short = plus_codes.shorten(full, *CHENNAI)

        area = plus_codes.resolve(short, *CHENNAI)

        self.assertEqual(
            plus_codes.encode(area.latitude_center, area.longitude_center), full,
        )

    def test_a_short_code_with_nowhere_to_read_it_asks_for_the_town(self):
        with self.assertRaises(plus_codes.PlusCodeError) as caught:
            plus_codes.resolve('37MC+37')

        self.assertIn('short Plus Code', str(caught.exception))

    def test_an_empty_code_asks_for_one(self):
        with self.assertRaises(plus_codes.PlusCodeError) as caught:
            plus_codes.resolve('')

        self.assertIn('Enter a Plus Code', str(caught.exception))

    def test_something_that_is_not_a_code_at_all(self):
        with self.assertRaises(plus_codes.PlusCodeError):
            plus_codes.resolve('12 Anna Salai')


class LocalityExtractionTests(TestCase):
    """Which of a geocoder's many names for a place goes next to the code."""

    def test_google_components_prefer_the_town_over_the_state(self):
        components = [
            {'long_name': 'Tamil Nadu', 'types': ['administrative_area_level_1']},
            {'long_name': 'Chennai', 'types': ['locality']},
            {'long_name': 'India', 'types': ['country']},
        ]

        self.assertEqual(_locality_from(components), 'Chennai')

    def test_google_components_fall_back_to_the_district(self):
        components = [
            {'long_name': 'India', 'types': ['country']},
            {'long_name': 'Chengalpattu', 'types': ['administrative_area_level_2']},
        ]

        self.assertEqual(_locality_from(components), 'Chengalpattu')

    def test_google_components_with_no_place_name(self):
        self.assertEqual(_locality_from([{'long_name': 'India',
                                          'types': ['country']}]), '')

    def test_nominatim_prefers_the_town_over_the_state(self):
        from .views import _nominatim_locality

        self.assertEqual(
            _nominatim_locality({'state': 'Tamil Nadu', 'city': 'Chennai'}),
            'Chennai',
        )

    def test_nominatim_with_no_place_name(self):
        from .views import _nominatim_locality

        self.assertEqual(_nominatim_locality({'country': 'India'}), '')


class ReverseGeocodeCarriesAPlusCodeTests(TestCase):
    url = '/api/maps/reverse-geocode/'

    @patch('maps.views._nominatim_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai', 'Chennai'))
    def test_the_point_comes_back_with_its_code(self, _mock):
        payload = self.client.get(self.url, {'lat': '13.0827', 'lng': '80.2707'}).json()

        self.assertEqual(payload['plus_code'],
                         plus_codes.plus_code_for(*CHENNAI))
        self.assertEqual(payload['plus_code_local'],
                         plus_codes.local_form(payload['plus_code']))
        self.assertEqual(payload['locality'], 'Chennai')
        self.assertTrue(payload['plus_code_display'].endswith(', Chennai'))

    @patch('maps.views._nominatim_reverse_geocode', return_value=None)
    def test_the_code_survives_a_geocoder_that_is_down(self, _mock):
        # This is the whole argument for computing it here: no address, no
        # town, no network -- and the customer still gets a usable code.
        payload = self.client.get(self.url, {'lat': '13.0827', 'lng': '80.2707'}).json()

        self.assertIsNone(payload['address'])
        self.assertEqual(payload['locality'], '')
        self.assertEqual(payload['plus_code'], plus_codes.plus_code_for(*CHENNAI))
        # With no town to write it against, the full code is what is shown.
        self.assertEqual(payload['plus_code_display'], payload['plus_code'])


class PlusCodeEndpointTests(TestCase):
    url = '/api/maps/plus-code/'

    @patch('maps.views._nominatim_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai', 'Chennai'))
    def test_a_full_code_resolves_to_its_point(self, _mock):
        payload = self.client.get(self.url, {'code': '7M5237MC+37'}).json()

        self.assertAlmostEqual(payload['latitude'], 13.0827, places=3)
        self.assertAlmostEqual(payload['longitude'], 80.2707, places=3)
        self.assertEqual(payload['plus_code'], '7M5237MC+37')
        self.assertEqual(payload['plus_code_display'], '37MC+37, Chennai')

    def test_open_to_anyone(self):
        # Reachable from guest browsing, like the rest of this app.
        with patch('maps.views._nominatim_reverse_geocode', return_value=None):
            response = self.client.get(self.url, {'code': '7M5237MC+37'})

        self.assertEqual(response.status_code, 200)

    @patch('maps.views._nominatim_reverse_geocode', return_value=None)
    def test_lower_case_and_spacing_are_forgiven(self, _mock):
        payload = self.client.get(self.url, {'code': ' 7m5237mc+37 '}).json()

        self.assertEqual(payload['plus_code'], '7M5237MC+37')

    @patch('maps.views._nominatim_reverse_geocode', return_value=None)
    @patch('maps.views._nominatim_geocode', return_value=CHENNAI)
    def test_a_short_code_is_read_against_the_town_beside_it(
            self, mock_geocode, _mock_reverse):
        full = plus_codes.plus_code_for(*CHENNAI)
        short = plus_codes.shorten(full, *CHENNAI)

        payload = self.client.get(self.url, {'code': f'{short}, Chennai'}).json()

        mock_geocode.assert_called_once_with('Chennai')
        self.assertEqual(payload['plus_code'], full)

    @patch('maps.views._nominatim_reverse_geocode', return_value=None)
    @patch('maps.views._nominatim_geocode', return_value=None)
    def test_a_short_code_falls_back_to_where_the_map_is_pointing(
            self, _mock_geocode, _mock_reverse):
        # The town could not be geocoded, so the app's own map centre is used.
        full = plus_codes.plus_code_for(*CHENNAI)
        short = plus_codes.shorten(full, *CHENNAI)

        payload = self.client.get(self.url, {
            'code': short, 'lat': str(CHENNAI[0]), 'lng': str(CHENNAI[1]),
        }).json()

        self.assertEqual(payload['plus_code'], full)

    def test_a_short_code_with_nothing_to_read_it_against_is_refused(self):
        response = self.client.get(self.url, {'code': '37MC+37'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Chennai', response.json()['detail'])

    def test_a_missing_code_is_refused_with_an_example(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn('37MC+37', response.json()['detail'])

    def test_something_that_is_not_a_code_is_refused(self):
        response = self.client.get(self.url, {'code': '12 Anna Salai'})

        self.assertEqual(response.status_code, 400)

    @patch('maps.views._nominatim_reverse_geocode', return_value=None)
    def test_the_square_is_handed_over_not_just_its_centre(self, _mock):
        # A Plus Code is an area. The app draws it rather than implying the
        # pin is accurate to the metre.
        payload = self.client.get(self.url, {'code': '7M5237MC+37'}).json()

        self.assertEqual(payload['code_length'], 10)
        self.assertLess(payload['latitude_lo'], payload['latitude'])
        self.assertGreater(payload['latitude_hi'], payload['latitude'])
        self.assertLess(payload['longitude_lo'], payload['longitude'])
        self.assertGreater(payload['longitude_hi'], payload['longitude'])

    @patch('maps.views.google_geocode', return_value=CHENNAI)
    @patch('maps.views.google_reverse_geocode',
           return_value=Place('12 Anna Salai, Chennai 600002', 'Chennai'))
    def test_google_is_used_for_the_town_once_configured(
            self, _mock_reverse, mock_geocode):
        settings_row = MapSettings.get_solo()
        settings_row.provider = MapSettings.Provider.GOOGLE
        settings_row.google_api_key = KEY
        settings_row.save()

        full = plus_codes.plus_code_for(*CHENNAI)
        short = plus_codes.shorten(full, *CHENNAI)

        payload = self.client.get(self.url, {'code': f'{short}, Chennai'}).json()

        mock_geocode.assert_called_once_with(KEY, 'Chennai')
        self.assertEqual(payload['plus_code'], full)
        self.assertEqual(payload['address'], '12 Anna Salai, Chennai 600002')
