"""
Plus Codes -- Google's Open Location Code -- worked out here rather than asked
for over the wire.

A Plus Code is a street address for a place that has no street address, which
in this country is most of them: "7M5237MC+37" is a square about fourteen
metres across, and "37MC+37, Chennai" is the same square written the way a
customer would say it. Half our bookings arrive with an address that reads
"near the water tank, ask for Murugan", and a code the vendor can paste into
any maps app is worth more than another line of that.

Why the algorithm lives in this file instead of in a requirements.txt line:

  It is arithmetic, not a service. Encoding a point and decoding a code need
  no key, no quota, no billing account and no network -- which is the whole
  reason Plus Codes suit this project, where the map itself is deliberately
  keyless until an admin decides otherwise (see MapSettings).

  The spec is frozen, so this file can be too. A dependency that will never
  change is still a dependency that can one day fail to install on the
  deploy box.

Ported from Google's reference implementation (github.com/google/
open-location-code, Apache 2.0), renamed into this project's spelling and
otherwise faithful to it. Google's own published test vectors are in
maps/tests.py, and are the reason to trust this.

Vocabulary, because three words get used interchangeably elsewhere:

  full code    8FVC2222+22    stands alone anywhere on earth
  short code   2222+22        needs somewhere nearby to be read against
  padded code  8FVC0000+      deliberately vague, a large area
"""

import math
import re

# The 20 characters a code is written in. Vowels are absent on purpose, so no
# code spells a word in any language, and so is anything easily misread.
CODE_ALPHABET = '23456789CFGHJMPQRVWX'
ENCODING_BASE = len(CODE_ALPHABET)

SEPARATOR = '+'
SEPARATOR_POSITION = 8
PADDING_CHARACTER = '0'

LATITUDE_MAX = 90
LONGITUDE_MAX = 180

# A code never carries more than 15 digits; past that the square is smaller
# than any phone's GPS can honestly claim to know.
MAX_DIGIT_COUNT = 15

# The first ten digits are five latitude/longitude pairs, each pair narrowing
# the square by a factor of 20. Everything after them is grid refinement.
PAIR_CODE_LENGTH = 10
PAIR_PRECISION = ENCODING_BASE ** 3
PAIR_FIRST_PLACE_VALUE = ENCODING_BASE ** (PAIR_CODE_LENGTH // 2 - 1)

# How many degrees across the square is left after each pair of digits. Used
# when shortening, to decide how much of the front can be dropped.
PAIR_RESOLUTIONS = [20.0, 1.0, 0.05, 0.0025, 0.000125]

# The refinement digits divide each square into 4 columns by 5 rows, which is
# what keeps the cells roughly square rather than tall and thin.
GRID_CODE_LENGTH = MAX_DIGIT_COUNT - PAIR_CODE_LENGTH
GRID_COLUMNS = 4
GRID_ROWS = 5
GRID_LAT_FIRST_PLACE_VALUE = GRID_ROWS ** (GRID_CODE_LENGTH - 1)
GRID_LNG_FIRST_PLACE_VALUE = GRID_COLUMNS ** (GRID_CODE_LENGTH - 1)

# Everything below is done in whole numbers of these units and converted back
# to degrees at the very end, so no rounding error accumulates across the
# fifteen digits.
FINAL_LAT_PRECISION = PAIR_PRECISION * GRID_ROWS ** GRID_CODE_LENGTH
FINAL_LNG_PRECISION = PAIR_PRECISION * GRID_COLUMNS ** GRID_CODE_LENGTH

# Below six digits there is nothing left worth trimming.
MIN_TRIMMABLE_CODE_LEN = 6

# The length everything in this project encodes to unless told otherwise.
DEFAULT_CODE_LENGTH = PAIR_CODE_LENGTH


class PlusCodeError(ValueError):
    """A code that cannot be read, carrying wording fit to show a customer."""


class CodeArea:
    """
    The square a code stands for.

    A Plus Code is an area, never a point -- ten digits is about fourteen
    metres across. `latitude_center`/`longitude_center` are the point to drop
    a pin on; the bounds are there for anything that wants to draw the square.
    """

    def __init__(self, latitude_lo, longitude_lo, latitude_hi, longitude_hi,
                 code_length):
        self.latitude_lo = latitude_lo
        self.longitude_lo = longitude_lo
        self.latitude_hi = latitude_hi
        self.longitude_hi = longitude_hi
        self.code_length = code_length
        self.latitude_center = min(
            latitude_lo + (latitude_hi - latitude_lo) / 2, LATITUDE_MAX,
        )
        self.longitude_center = min(
            longitude_lo + (longitude_hi - longitude_lo) / 2, LONGITUDE_MAX,
        )

    def __repr__(self):
        return (f'CodeArea({self.latitude_center}, {self.longitude_center}, '
                f'{self.code_length} digits)')


# ---------------------------------------------------------------------------
# Reading a code
# ---------------------------------------------------------------------------

def is_valid(code):
    """Whether this is a code at all -- says nothing about where it is."""
    if not code or not isinstance(code, str):
        return False

    # Exactly one separator, at an even position no later than the eighth.
    if code.count(SEPARATOR) != 1:
        return False
    separator_at = code.find(SEPARATOR)
    if separator_at > SEPARATOR_POSITION or separator_at % 2 == 1:
        return False
    if len(code) == 1:
        return False

    padding_at = code.find(PADDING_CHARACTER)
    if padding_at != -1:
        # Padding says "somewhere in this large area", which only makes sense
        # on a code that is otherwise complete.
        if separator_at < SEPARATOR_POSITION:
            return False
        if padding_at == 0:
            return False
        # One run of it, of even length, and the code ends at the separator.
        padding = code[padding_at:code.rfind(PADDING_CHARACTER) + 1]
        if len(padding) % 2 == 1 or padding.count(PADDING_CHARACTER) != len(padding):
            return False
        if not code.endswith(SEPARATOR):
            return False

    # A lone digit after the separator would be half a pair.
    if len(code) - separator_at - 1 == 1:
        return False

    body = code.replace(SEPARATOR, '').replace(PADDING_CHARACTER, '')
    return all(character.upper() in CODE_ALPHABET for character in body)


def is_short(code):
    """A code with its leading digits dropped: needs a place to read it near."""
    return is_valid(code) and 0 <= code.find(SEPARATOR) < SEPARATOR_POSITION


def is_full(code):
    """A code that stands on its own anywhere on earth."""
    if not is_valid(code) or is_short(code):
        return False

    # The first digit alone can put the code off the top of the globe.
    if CODE_ALPHABET.find(code[0].upper()) * ENCODING_BASE >= LATITUDE_MAX * 2:
        return False
    if len(code) > 1:
        if CODE_ALPHABET.find(code[1].upper()) * ENCODING_BASE >= LONGITUDE_MAX * 2:
            return False
    return True


def decode(code):
    """
    The square a full code stands for, as a CodeArea.

    Raises PlusCodeError on anything that is not a full code -- short codes go
    through `recover_nearest` first, because they cannot be read without
    knowing roughly where they were written.
    """
    if not is_full(code):
        raise PlusCodeError(f'"{code}" is not a complete Plus Code.')

    # Separator and padding carry no value; they only mark shape.
    digits = re.sub(r'[+0]', '', code).upper()[:MAX_DIGIT_COUNT]

    # Worked out as integers in units of PAIR_PRECISION, converted at the end.
    normal_lat = -LATITUDE_MAX * PAIR_PRECISION
    normal_lng = -LONGITUDE_MAX * PAIR_PRECISION
    grid_lat = 0
    grid_lng = 0

    pair_digits = min(len(digits), PAIR_CODE_LENGTH)
    place_value = PAIR_FIRST_PLACE_VALUE
    for index in range(0, pair_digits, 2):
        normal_lat += CODE_ALPHABET.find(digits[index]) * place_value
        normal_lng += CODE_ALPHABET.find(digits[index + 1]) * place_value
        if index < pair_digits - 2:
            place_value //= ENCODING_BASE

    latitude_size = float(place_value) / PAIR_PRECISION
    longitude_size = float(place_value) / PAIR_PRECISION

    if len(digits) > PAIR_CODE_LENGTH:
        row_place_value = GRID_LAT_FIRST_PLACE_VALUE
        column_place_value = GRID_LNG_FIRST_PLACE_VALUE
        grid_digits = min(len(digits), MAX_DIGIT_COUNT)
        for index in range(PAIR_CODE_LENGTH, grid_digits):
            digit_value = CODE_ALPHABET.find(digits[index])
            grid_lat += (digit_value // GRID_COLUMNS) * row_place_value
            grid_lng += (digit_value % GRID_COLUMNS) * column_place_value
            if index < grid_digits - 1:
                row_place_value //= GRID_ROWS
                column_place_value //= GRID_COLUMNS
        latitude_size = float(row_place_value) / FINAL_LAT_PRECISION
        longitude_size = float(column_place_value) / FINAL_LNG_PRECISION

    latitude = float(normal_lat) / PAIR_PRECISION + float(grid_lat) / FINAL_LAT_PRECISION
    longitude = float(normal_lng) / PAIR_PRECISION + float(grid_lng) / FINAL_LNG_PRECISION

    return CodeArea(
        round(latitude, 14),
        round(longitude, 14),
        round(latitude + latitude_size, 14),
        round(longitude + longitude_size, 14),
        min(len(digits), MAX_DIGIT_COUNT),
    )


# ---------------------------------------------------------------------------
# Writing a code
# ---------------------------------------------------------------------------

def encode(latitude, longitude, code_length=DEFAULT_CODE_LENGTH):
    """
    The Plus Code for a point. Ten digits is the everyday length: a square
    about fourteen metres across, which is a doorway rather than a street.
    """
    if code_length < 2 or (code_length < PAIR_CODE_LENGTH and code_length % 2 == 1):
        raise PlusCodeError(f'{code_length} is not a usable code length.')
    code_length = min(code_length, MAX_DIGIT_COUNT)

    latitude = clip_latitude(latitude)
    longitude = normalize_longitude(longitude)
    # The north pole belongs to the square below it; encoding it as-is would
    # produce a code that decodes to somewhere off the map.
    if latitude == LATITUDE_MAX:
        latitude -= latitude_precision(code_length)

    # Whole numbers of the finest unit, so everything below is integer
    # division and nothing drifts across the fifteen digits.
    lat_value = int(round((latitude + LATITUDE_MAX) * FINAL_LAT_PRECISION, 6))
    lng_value = int(round((longitude + LONGITUDE_MAX) * FINAL_LNG_PRECISION, 6))

    code = ''
    if code_length > PAIR_CODE_LENGTH:
        for _ in range(GRID_CODE_LENGTH):
            index = (lat_value % GRID_ROWS) * GRID_COLUMNS + (lng_value % GRID_COLUMNS)
            code = CODE_ALPHABET[index] + code
            lat_value //= GRID_ROWS
            lng_value //= GRID_COLUMNS
    else:
        lat_value //= GRID_ROWS ** GRID_CODE_LENGTH
        lng_value //= GRID_COLUMNS ** GRID_CODE_LENGTH

    for _ in range(PAIR_CODE_LENGTH // 2):
        code = CODE_ALPHABET[lng_value % ENCODING_BASE] + code
        code = CODE_ALPHABET[lat_value % ENCODING_BASE] + code
        lat_value //= ENCODING_BASE
        lng_value //= ENCODING_BASE

    code = code[:SEPARATOR_POSITION] + SEPARATOR + code[SEPARATOR_POSITION:]

    if code_length >= SEPARATOR_POSITION:
        return code[:code_length + 1]
    # Shorter than the separator position: padded out to it, e.g. "8FVC0000+".
    padding = PADDING_CHARACTER * (SEPARATOR_POSITION - code_length)
    return code[:code_length] + padding + SEPARATOR


# ---------------------------------------------------------------------------
# The short form, and getting back from it
# ---------------------------------------------------------------------------

def shorten(code, latitude, longitude):
    """
    The code with its leading digits dropped, given somewhere it will be read.

    "7M5237MC+37" becomes "37MC+37", which is what goes on a card next to the
    town name. Returns the code unchanged when the reference point is too far
    away for anything to be safely dropped.
    """
    if not is_full(code):
        raise PlusCodeError(f'"{code}" is not a complete Plus Code.')
    if PADDING_CHARACTER in code:
        raise PlusCodeError('A padded Plus Code cannot be shortened.')

    code = code.upper()
    area = decode(code)
    if area.code_length < MIN_TRIMMABLE_CODE_LEN:
        raise PlusCodeError(
            f'A Plus Code needs at least {MIN_TRIMMABLE_CODE_LEN} digits '
            f'to be shortened.'
        )

    latitude = clip_latitude(latitude)
    longitude = normalize_longitude(longitude)
    distance = max(
        abs(area.latitude_center - latitude),
        abs(area.longitude_center - longitude),
    )
    # 0.3 rather than the 0.5 that would just fit, so a code shortened here
    # still recovers correctly from a reference point a little further off.
    for index in range(len(PAIR_RESOLUTIONS) - 2, 0, -1):
        if distance < PAIR_RESOLUTIONS[index] * 0.3:
            return code[(index + 1) * 2:]
    return code


def recover_nearest(code, reference_latitude, reference_longitude):
    """
    The full code a short one meant, read near a reference point.

    Short codes are ambiguous by design -- "37MC+37" repeats roughly every
    degree -- and this picks whichever of the repeats is nearest to where the
    reader is. A code that is already full comes back unchanged bar its
    capitalisation.
    """
    if is_full(code):
        return code.upper()
    if not is_short(code):
        raise PlusCodeError(f'"{code}" is not a Plus Code.')

    reference_latitude = clip_latitude(reference_latitude)
    reference_longitude = normalize_longitude(reference_longitude)
    code = code.upper()

    missing_digits = SEPARATOR_POSITION - code.find(SEPARATOR)
    # How large an area those missing digits covered, in degrees.
    resolution = pow(ENCODING_BASE, 2 - (missing_digits / 2))
    half_resolution = resolution / 2.0

    # Borrow the missing digits from the reference point, then check we did
    # not land a whole cell away from it.
    area = decode(
        encode(reference_latitude, reference_longitude)[:missing_digits] + code
    )

    if (reference_latitude + half_resolution < area.latitude_center
            and area.latitude_center - resolution >= -LATITUDE_MAX):
        area.latitude_center -= resolution
    elif (reference_latitude - half_resolution > area.latitude_center
            and area.latitude_center + resolution <= LATITUDE_MAX):
        area.latitude_center += resolution

    if reference_longitude + half_resolution < area.longitude_center:
        area.longitude_center -= resolution
    elif reference_longitude - half_resolution > area.longitude_center:
        area.longitude_center += resolution

    return encode(area.latitude_center, area.longitude_center, area.code_length)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

def clip_latitude(latitude):
    return min(LATITUDE_MAX, max(-LATITUDE_MAX, latitude))


def normalize_longitude(longitude):
    """Wraps the antimeridian, so 190 degrees east reads as -170."""
    while longitude < -LONGITUDE_MAX:
        longitude += 360
    while longitude >= LONGITUDE_MAX:
        longitude -= 360
    return longitude


def latitude_precision(code_length):
    """How many degrees of latitude a code of this length leaves undecided."""
    if code_length <= PAIR_CODE_LENGTH:
        return pow(ENCODING_BASE, math.floor((code_length / -2) + 2))
    return pow(ENCODING_BASE, -3) / pow(GRID_ROWS, code_length - PAIR_CODE_LENGTH)


# ---------------------------------------------------------------------------
# The shapes this project actually passes around
# ---------------------------------------------------------------------------
#
# Everything above is the published algorithm. Everything below is the small
# amount of opinion needed to put a code in front of a customer: which of the
# three ways of writing it goes where, and how to read back whatever they
# paste in.

# The first four characters are the "area code" -- about 100km across, which
# is what a town name replaces when the code is written the short way.
AREA_CODE_LENGTH = 4


def plus_code_for(latitude, longitude, code_length=DEFAULT_CODE_LENGTH):
    """
    The full code for a point, or '' when there is no point.

    Returning '' rather than raising is deliberate: most callers are handing
    this a nullable latitude/longitude off a model, and a missing pin is an
    ordinary state, not an error.
    """
    if latitude is None or longitude is None:
        return ''
    try:
        return encode(float(latitude), float(longitude), code_length)
    except (TypeError, ValueError):
        return ''


def local_form(code):
    """
    The last six-or-so characters -- "37MC+37" -- which only mean anything
    next to a town name. '' when the code has nothing to trim.
    """
    if not is_full(code) or PADDING_CHARACTER in code:
        return ''
    return code.upper()[AREA_CODE_LENGTH:]


def display_form(code, locality=''):
    """
    The way a code should be shown to a person.

    With a town, the short way Google Maps itself writes it -- "37MC+37,
    Chennai". Without one, the full code, which is longer but at least
    always resolvable.
    """
    if not code:
        return ''
    local = local_form(code)
    if local and locality:
        return f'{local}, {locality}'
    return code.upper()


def split_code_and_locality(text):
    """
    Pull a code and a place name out of whatever the customer pasted.

    People paste "37MC+37, Chennai", or "7M5237MC+37", or the whole line out
    of the Google Maps share sheet with the address trailing behind it. All
    that is needed is the first word containing a '+' -- everything after it
    is the locality, if there is one.

    Returns (code, locality), either of which may be ''.
    """
    if not text:
        return '', ''

    # Commas separate code from town; whitespace does too when they forgot it.
    parts = [part.strip() for part in re.split(r'[,\n]', str(text)) if part.strip()]
    if not parts:
        return '', ''

    head = parts[0]
    locality = ', '.join(parts[1:])

    # The head may still be "37MC+37 Chennai" with no comma.
    words = head.split()
    code = ''
    for index, word in enumerate(words):
        if SEPARATOR in word:
            code = word
            trailing = ' '.join(words[index + 1:]).strip()
            if trailing:
                locality = f'{trailing}, {locality}' if locality else trailing
            break

    return code.upper(), locality


def resolve(code, reference_latitude=None, reference_longitude=None):
    """
    A pasted code turned into a CodeArea.

    A full code needs nothing else. A short one needs somewhere to be read
    against -- the town it was written with, geocoded by the caller, or
    failing that wherever the customer's map is currently pointing.

    Raises PlusCodeError, worded for a customer, when it cannot be read.
    """
    code = (code or '').strip().upper()
    if not code:
        raise PlusCodeError('Enter a Plus Code, for example 37MC+37, Chennai.')

    if is_full(code):
        return decode(code)

    if not is_short(code):
        raise PlusCodeError(f'"{code}" is not a Plus Code.')

    if reference_latitude is None or reference_longitude is None:
        raise PlusCodeError(
            f'"{code}" is a short Plus Code. Add the town it is in, '
            f'for example "{code}, Chennai".'
        )

    return decode(recover_nearest(code, reference_latitude, reference_longitude))
