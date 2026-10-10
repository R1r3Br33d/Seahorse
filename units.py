#!/usr/bin/env python3
"""
units.py - every unit of measurement Seahorse knows, with exact conversions.

    convert(5, "mi", "km")            -> 8.04672 km
    convert(98.6, "degF", "degC")     -> 37 degC
    convert(30, "mpg", "L/100km")     -> 7.84049 L/100km (reciprocal units handled)
    convert(1, "kWh", "BTU")          -> 3412.14 BTU
    convert(60, "mi/h", "m/s")        -> compound units with * / ^ and parentheses-free products
    units("length")                   -> every length unit and its value in SI

Dimensional analysis guards every conversion: units are reduced to SI base
dimensions (length, mass, time, current, temperature, amount, luminous
intensity, information, angle, solid angle), and a conversion between
different dimensions is refused with an explanation.

Coverage: the 7 SI base units and 22 named derived units; all 24 SI prefixes
(quecto to quetta) and binary prefixes (Ki to Yi); US customary and imperial
length, area, volume (liquid and dry), mass, force, pressure, energy and
power; nautical, astronomical and atomic/Planck units; CGS and Gaussian
units; data and information; radiation and dose; photometry; viscosity;
concentration; angles; historical and traditional units (furlong, rod,
cubit, league, verst, li, shaku, tsubo, catty, tael, momme...); and nine
temperature scales (kelvin, Celsius, Fahrenheit, Rankine, Réaumur, Rømer,
Newton, Delisle, plus temperature differences).

Run directly:  python3 units.py 5 mi km   |   python3 units.py list [category]
"""

import difflib
import math
import re
import sys

BASES = ["m", "kg", "s", "A", "K", "mol", "cd", "bit", "rad", "sr"]
BASE_NAMES = {"m": "length", "kg": "mass", "s": "time", "A": "electric current", "K": "temperature",
              "mol": "amount of substance", "cd": "luminous intensity", "bit": "information",
              "rad": "angle", "sr": "solid angle"}

SI_PREFIXES = {
    "Q": 1e30, "R": 1e27, "Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6,
    "k": 1e3, "h": 1e2, "da": 1e1, "d": 1e-1, "c": 1e-2, "m": 1e-3, "µ": 1e-6, "μ": 1e-6, "u": 1e-6,
    "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18, "z": 1e-21, "y": 1e-24, "r": 1e-27, "q": 1e-30,
    "quetta": 1e30, "ronna": 1e27, "yotta": 1e24, "zetta": 1e21, "exa": 1e18, "peta": 1e15, "tera": 1e12,
    "giga": 1e9, "mega": 1e6, "kilo": 1e3, "hecto": 1e2, "deca": 1e1, "deka": 1e1, "deci": 1e-1,
    "centi": 1e-2, "milli": 1e-3, "micro": 1e-6, "nano": 1e-9, "pico": 1e-12, "femto": 1e-15,
    "atto": 1e-18, "zepto": 1e-21, "yocto": 1e-24, "ronto": 1e-27, "quecto": 1e-30,
}
BINARY_PREFIXES = {"Ki": 2 ** 10, "Mi": 2 ** 20, "Gi": 2 ** 30, "Ti": 2 ** 40, "Pi": 2 ** 50, "Ei": 2 ** 60,
                   "Zi": 2 ** 70, "Yi": 2 ** 80, "kibi": 2 ** 10, "mebi": 2 ** 20, "gibi": 2 ** 30,
                   "tebi": 2 ** 40, "pebi": 2 ** 50, "exbi": 2 ** 60, "zebi": 2 ** 70, "yobi": 2 ** 80}

# names (comma-separated; * = takes SI prefixes, ** = also binary prefixes) | definition | category
TABLE = r"""
m*, meter*, metre*                    | base m                     | length
kg, kilogram                          | base kg                    | mass
s*, sec, second*                      | base s                     | time
A*, amp*, ampere*                     | base A                     | electric current
K*, kelvin*                           | base K                     | temperature
mol*, mole*                           | base mol                   | amount of substance
cd*, candela*                         | base cd                    | luminous intensity
bit**, bits**, b**, shannon           | base bit                   | information
rad*, radian*                         | base rad                   | angle
sr*, steradian*                       | base sr                    | solid angle
g*, gram*, gramme*                    | 0.001 kg                   | mass
Hz*, hertz*                           | 1 s^-1                     | frequency
N*, newton*                           | 1 kg m s^-2                | force
Pa*, pascal*                          | 1 N m^-2                   | pressure
J*, joule*                            | 1 N m                      | energy
W*, watt*                             | 1 J s^-1                   | power
C*, coulomb*                          | 1 A s                      | electric charge
V*, volt*                             | 1 W A^-1                   | voltage
ohm*, Ω*                              | 1 V A^-1                   | resistance
S*, siemens*, mho                     | 1 ohm^-1                   | conductance
F*, farad*                            | 1 C V^-1                   | capacitance
H*, henry*                            | 1 V s A^-1                 | inductance
Wb*, weber*                           | 1 V s                      | magnetic flux
T*, tesla*                            | 1 Wb m^-2                  | magnetic flux density
lm*, lumen*                           | 1 cd sr                    | luminous flux
lx*, lux*                             | 1 lm m^-2                  | illuminance
Bq*, becquerel*                       | 1 s^-1                     | radioactivity
Gy*, gray*                            | 1 J kg^-1                  | absorbed dose
Sv*, sievert*                         | 1 J kg^-1                  | dose equivalent
kat*, katal*                          | 1 mol s^-1                 | catalytic activity
Å, angstrom, ångström                 | 1e-10 m                    | length
micron                                | 1e-6 m                     | length
fermi                                 | 1e-15 m                    | length
in, inch, inches                      | 0.0254 m                   | length
ft, foot, feet                        | 12 in                      | length
yd, yard, yards                       | 3 ft                       | length
mi, mile, miles, statute_mile         | 5280 ft                    | length
nmi, NM, nautical_mile                | 1852 m                     | length
survey_ft, survey_foot                | 0.3048006096012192 m       | length
survey_mi, survey_mile                | 5280 survey_ft             | length
thou, mil                             | 0.001 in                   | length
barleycorn                            | 0.3333333333333333 in      | length
hand                                  | 4 in                       | length
nail                                  | 2.25 in                    | length
span                                  | 9 in                       | length
cubit                                 | 18 in                      | length
ell                                   | 45 in                      | length
link                                  | 0.66 ft                    | length
rod, perch, pole                      | 16.5 ft                    | length
chain                                 | 66 ft                      | length
furlong                               | 660 ft                     | length
league                                | 3 mi                       | length
fathom                                | 6 ft                       | length
cable                                 | 185.2 m                    | length
pica                                  | 0.16666666666666666 in     | length
point, typographic_point              | 0.013888888888888888 in    | length
twip                                  | 0.0006944444444444445 in   | length
au, AU, astronomical_unit             | 149597870700 m             | length
ly, lightyear, light_year             | 9460730472580800 m         | length
pc*, parsec*                          | 30856775814913673 m        | length
bohr, a0                              | 5.29177210903e-11 m        | length
planck_length                         | 1.616255e-35 m             | length
mil_sv, scandinavian_mile             | 10000 m                    | length
verst                                 | 1066.8 m                   | length
li                                    | 500 m                      | length
ri                                    | 3927.2727272727 m          | length
shaku                                 | 0.30303030303030304 m      | length
sun_jp                                | 0.030303030303030304 m     | length
ha, hectare                           | 10000 m^2                  | area
are                                   | 100 m^2                    | area
acre, acres                           | 4046.8564224 m^2           | area
rood                                  | 0.25 acre                  | area
section                               | 1 mi^2                     | area
township                              | 36 mi^2                    | area
barn*                                 | 1e-28 m^2                  | area
circular_mil, cmil                    | 0.7853981633974483 thou^2  | area
dunam                                 | 1000 m^2                   | area
tsubo                                 | 3.305785123966942 m^2      | area
L*, l*, liter*, litre*                | 0.001 m^3                  | volume
cc                                    | 1 cm^3                     | volume
stere                                 | 1 m^3                      | volume
gal, gallon, us_gal                   | 231 in^3                   | volume
qt, quart                             | 0.25 gal                   | volume
pt, pint                              | 0.125 gal                  | volume
cup                                   | 0.0625 gal                 | volume
fl_oz, floz, fluid_ounce              | 0.0078125 gal              | volume
gill                                  | 4 fl_oz                    | volume
tbsp, tablespoon                      | 0.5 fl_oz                  | volume
tsp, teaspoon                         | 0.16666666666666666 fl_oz  | volume
fl_dr, fluid_dram                     | 0.125 fl_oz                | volume
minim                                 | 0.0020833333333333333 fl_oz | volume
bbl, barrel, oil_barrel               | 42 gal                     | volume
hogshead                              | 63 gal                     | volume
imp_gal, uk_gal, imperial_gallon      | 4.54609 L                  | volume
imp_qt, uk_qt                         | 0.25 imp_gal               | volume
imp_pt, uk_pt, imperial_pint          | 0.125 imp_gal              | volume
imp_fl_oz, uk_fl_oz                   | 0.00625 imp_gal            | volume
imp_gill                              | 5 imp_fl_oz                | volume
imp_bushel                            | 8 imp_gal                  | volume
dry_gal                               | 268.8025 in^3              | volume
dry_qt                                | 0.25 dry_gal               | volume
dry_pt                                | 0.125 dry_gal              | volume
peck                                  | 2 dry_gal                  | volume
bu, bushel                            | 2150.42 in^3               | volume
cord                                  | 128 ft^3                   | volume
board_foot, fbm                       | 144 in^3                   | volume
acre_foot, acre_ft                    | 1 acre ft                  | volume
metric_cup                            | 250 mL                     | volume
metric_tbsp                           | 15 mL                      | volume
metric_tsp                            | 5 mL                       | volume
drop                                  | 0.05 mL                    | volume
t*, tonne*, metric_ton                | 1000 kg                    | mass
lb, lbs, pound, pounds                | 0.45359237 kg              | mass
oz, ounce, ounces                     | 0.0625 lb                  | mass
gr, grain                             | 0.00014285714285714287 lb  | mass
dr, dram                              | 0.0625 oz                  | mass
st, stone                             | 14 lb                      | mass
ton, short_ton                        | 2000 lb                    | mass
long_ton                              | 2240 lb                    | mass
cwt, hundredweight                    | 100 lb                     | mass
long_cwt                              | 112 lb                     | mass
quarter_mass                          | 28 lb                      | mass
ozt, troy_oz, troy_ounce              | 480 gr                     | mass
troy_lb                               | 12 ozt                     | mass
dwt, pennyweight                      | 24 gr                      | mass
ct, carat                             | 0.2 g                      | mass
Da*, u, amu, dalton*                  | 1.66053906660e-27 kg       | mass
electron_mass, m_e                    | 9.1093837015e-31 kg        | mass
planck_mass                           | 2.176434e-8 kg             | mass
earth_mass                            | 5.9722e24 kg               | mass
solar_mass                            | 1.98847e30 kg              | mass
quintal                               | 100 kg                     | mass
jin, catty                            | 0.5 kg                     | mass
liang, tael                           | 50 g                       | mass
momme                                 | 3.75 g                     | mass
kan                                   | 3.75 kg                    | mass
min, minute, minutes                  | 60 s                       | time
h, hr, hour, hours                    | 3600 s                     | time
d, day, days                          | 86400 s                    | time
wk, week, weeks                       | 7 day                      | time
fortnight                             | 14 day                     | time
month, months                         | 2629746 s                  | time
yr, year, years, julian_year          | 365.25 day                 | time
common_year                           | 365 day                    | time
gregorian_year                        | 365.2425 day               | time
decade                                | 10 yr                      | time
century                               | 100 yr                     | time
millennium                            | 1000 yr                    | time
sidereal_day                          | 86164.0905 s               | time
shake                                 | 1e-8 s                     | time
planck_time                           | 5.391247e-44 s             | time
B**, byte**, bytes**, octet**         | 8 bit                      | information
nibble                                | 4 bit                      | information
nat                                   | 1.4426950408889634 bit     | information
hartley, ban, dit                     | 3.321928094887362 bit      | information
bps                                   | 1 bit s^-1                 | data rate
deg, degree, degrees, °               | 0.017453292519943295 rad   | angle
arcmin, arcminute, ′                  | 0.016666666666666666 deg   | angle
arcsec, arcsecond, ″                  | 0.016666666666666666 arcmin | angle
mas                                   | 0.001 arcsec               | angle
grad, gon, gradian                    | 0.015707963267948967 rad   | angle
turn, rev, revolution, cycle          | 6.283185307179586 rad      | angle
sqdeg, square_degree                  | 0.0003046174197867086 sr   | solid angle
rpm                                   | 0.016666666666666666 Hz    | frequency
dyn, dyne                             | 1e-5 N                     | force
kgf, kilogram_force, kp               | 9.80665 N                  | force
lbf, pound_force                      | 4.4482216152605 N          | force
ozf, ounce_force                      | 0.0625 lbf                 | force
kip                                   | 1000 lbf                   | force
tonf, ton_force                       | 2000 lbf                   | force
pdl, poundal                          | 1 lb ft s^-2               | force
sthene                                | 1000 N                     | force
slug                                  | 1 lbf s^2 ft^-1            | mass
bar*                                  | 100000 Pa                  | pressure
atm, atmosphere                       | 101325 Pa                  | pressure
at, technical_atmosphere              | 1 kgf cm^-2                | pressure
Torr, torr                            | 133.32236842105263 Pa      | pressure
mmHg                                  | 133.322387415 Pa           | pressure
inHg                                  | 3386.389 Pa                | pressure
inH2O                                 | 249.08891 Pa               | pressure
cmH2O                                 | 98.0665 Pa                 | pressure
psi                                   | 1 lbf in^-2                | pressure
ksi                                   | 1000 psi                   | pressure
barye, Ba                             | 0.1 Pa                     | pressure
erg                                   | 1e-7 J                     | energy
cal*, calorie*, thermochemical_calorie | 4.184 J                   | energy
Cal, kcal_food, food_calorie          | 4184 J                     | energy
cal_IT                                | 4.1868 J                   | energy
BTU, Btu, btu                         | 1055.05585262 J            | energy
therm                                 | 100000 BTU                 | energy
quad                                  | 1e15 BTU                   | energy
eV*, electronvolt*                    | 1.602176634e-19 J          | energy
Wh*, watt_hour*                       | 3600 J                     | energy
ton_tnt*, tTNT*                       | 4.184e9 J                  | energy
hartree, Eh                           | 4.3597447222071e-18 J      | energy
Ry, rydberg                           | 2.1798723611035e-18 J      | energy
ft_lbf, foot_pound                    | 1 ft lbf                   | energy
boe, barrel_of_oil_equivalent         | 6.1178632e9 J              | energy
toe, tonne_of_oil_equivalent          | 41.868e9 J                 | energy
foe                                   | 1e44 J                     | energy
hp, horsepower                        | 745.69987158227 W          | power
PS, metric_horsepower                 | 735.49875 W                | power
hp_e, electrical_horsepower           | 746 W                      | power
TR, ton_of_refrigeration              | 3516.8528420667 W          | power
Ah*, amp_hour*                        | 3600 C                     | electric charge
e_charge, elementary_charge           | 1.602176634e-19 C          | electric charge
statC, Fr, franklin                   | 3.3356409519815204e-10 C   | electric charge
abA, biot                             | 10 A                       | electric current
gauss, Gs                             | 1e-4 T                     | magnetic flux density
Mx, maxwell                           | 1e-8 Wb                    | magnetic flux
Oe, oersted                           | 79.57747154594767 A m^-1   | magnetic field strength
fc, foot_candle                       | 1 lm ft^-2                 | illuminance
phot                                  | 10000 lx                   | illuminance
nit, nt                               | 1 cd m^-2                  | luminance
stilb, sb                             | 10000 cd m^-2              | luminance
lambert                               | 3183.098861837907 cd m^-2  | luminance
foot_lambert, fL                      | 3.4262590996353905 cd m^-2 | luminance
Ci, curie                             | 3.7e10 Bq                  | radioactivity
Rd, rutherford                        | 1e6 Bq                     | radioactivity
rem                                   | 0.01 Sv                    | dose equivalent
rd, rad_dose                          | 0.01 Gy                    | absorbed dose
R_x, roentgen                         | 2.58e-4 C kg^-1            | exposure
P*, poise*                            | 0.1 Pa s                   | dynamic viscosity
St*, stokes*                          | 1e-4 m^2 s^-1              | kinematic viscosity
M_molar, molar                        | 1 mol L^-1                 | concentration
kn, kt, knot, knots                   | 1 nmi h^-1                 | speed
mph                                   | 1 mi h^-1                  | speed
kph, kmh                              | 1 km h^-1                  | speed
fps                                   | 1 ft s^-1                  | speed
c_light, speed_of_light               | 299792458 m s^-1           | speed
mach                                  | 340.29 m s^-1              | speed
g0, gn, gee, standard_gravity         | 9.80665 m s^-2             | acceleration
Gal, galileo                          | 0.01 m s^-2                | acceleration
percent, %                            | 0.01 1                     | ratio
permille, ‰                           | 0.001 1                    | ratio
ppm                                   | 1e-6 1                     | ratio
ppb                                   | 1e-9 1                     | ratio
ppt                                   | 1e-12 1                    | ratio
mpg, mpg_us                           | 1 mi gal^-1                | fuel economy
mpg_imp, mpg_uk                       | 1 mi imp_gal^-1            | fuel economy
"""

# Temperature scales with offsets: kelvin = (value + add) * mul
TEMPERATURE_SCALES = {
    "degC": (273.15, 1.0), "°C": (273.15, 1.0), "celsius": (273.15, 1.0), "C_temp": (273.15, 1.0),
    "degF": (459.67, 5 / 9), "°F": (459.67, 5 / 9), "fahrenheit": (459.67, 5 / 9),
    "degR": (0.0, 5 / 9), "°R": (0.0, 5 / 9), "rankine": (0.0, 5 / 9),
    "degRe": (218.52, 1.25), "reaumur": (218.52, 1.25), "réaumur": (218.52, 1.25),
    "degRo": (135.90375, 40 / 21), "romer": (135.90375, 40 / 21), "rømer": (135.90375, 40 / 21),
    "degN": (90.1395, 100 / 33), "newton_temp": (90.1395, 100 / 33),
}
# Delisle runs backwards: kelvin = 373.15 - value * 2/3
DELISLE = {"degDe", "delisle"}
# Temperature differences (no offset), usable inside compound units
DELTA = {"delta_degC": 1.0, "delta_degF": 5 / 9, "delta_degR": 5 / 9, "delta_K": 1.0}


class UnitError(ValueError):
    pass


def _dim_add(a, b, k=1):
    return tuple(x + k * y for x, y in zip(a, b))


ZERO = tuple(0 for _ in BASES)
UNITS = {}        # name -> (factor_to_SI, dim)
CATEGORY = {}     # name -> category
PREFIXABLE = {}   # name -> "si" | "binary"
CANONICAL = {}    # name -> first name in its row


def _build():
    for raw in TABLE.strip().splitlines():
        names, definition, category = [p.strip() for p in raw.split("|")]
        name_list = []
        for n in names.split(","):
            n = n.strip()
            kind = "binary" if n.endswith("**") else "si" if n.endswith("*") else None
            n = n.rstrip("*")
            name_list.append(n)
            if kind:
                PREFIXABLE[n] = kind
        if definition.startswith("base "):
            base = definition.split()[1]
            dim = tuple(1 if b == base else 0 for b in BASES)
            value = (1.0, dim)
        else:
            num, _, expr = definition.partition(" ")
            factor, dim = parse(expr) if expr.strip() != "1" else (1.0, ZERO)
            value = (float(num) * factor, dim)
        for n in name_list:
            UNITS[n] = value
            CATEGORY[n] = category
            CANONICAL[n] = name_list[0]
    for n, f in DELTA.items():
        UNITS[n] = (f, tuple(1 if b == "K" else 0 for b in BASES))
        CATEGORY[n] = "temperature difference"
        CANONICAL[n] = n


def lookup(token):
    """One unit token (no operators) -> (factor, dim)."""
    if token in UNITS:
        return UNITS[token]
    for prefixes, kinds in ((SI_PREFIXES, ("si", "binary")), (BINARY_PREFIXES, ("binary",))):
        for p in sorted(prefixes, key=len, reverse=True):
            if token.startswith(p) and len(token) > len(p):
                rest = token[len(p):]
                if rest in UNITS and PREFIXABLE.get(rest) in kinds:
                    f, d = UNITS[rest]
                    return prefixes[p] * f, d
    for suffix in ("es", "s"):  # plurals: furlongs, inches, miles
        if token.endswith(suffix) and len(token) > 3 and token[: -len(suffix)] in UNITS:
            return UNITS[token[: -len(suffix)]]
    low = {k.lower(): k for k in UNITS}
    if token.lower() in low and len(token) > 2:
        return UNITS[low[token.lower()]]
    close = difflib.get_close_matches(token, list(UNITS), n=3, cutoff=0.7)
    raise UnitError(f"unknown unit '{token}'" + (f" - did you mean {', '.join(close)}?" if close else ""))


_TOKEN = re.compile(r"\s*([*/·.]|\^|\*\*|-?\d+(?:\.\d+)?|[^\s*/·^()]+)")


def parse(expr):
    """'kg m^2 s^-2', 'km/h', 'N·m', 'L/100km', 'W/(m^2)' (no nesting) -> (factor, dim)."""
    expr = expr.replace("**", "^").replace("²", "^2").replace("³", "^3").replace("(", "").replace(")", "")
    expr = expr.strip()
    if not expr or expr == "1":
        return 1.0, ZERO
    factor, dim = 1.0, ZERO
    sign = 1
    tokens = [t for t in re.findall(r"\^-?\d+(?:\.\d+)?|[*/·]|[^\s*/·^]+", expr)]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("*", "·"):
            i += 1
            continue
        if tok == "/":
            sign = -1
            i += 1
            continue
        power = 1.0
        if i + 1 < len(tokens) and tokens[i + 1].startswith("^"):
            power = float(tokens[i + 1][1:])
            i += 1
        m = re.fullmatch(r"(\d+(?:\.\d+)?(?:e-?\d+)?)([A-Za-zµμÅΩ°′″%‰_].*)?", tok)
        if m and m.group(1) and m.group(2):       # '100km' = 100 * km
            f0, d0 = lookup(m.group(2))
            f, d = float(m.group(1)) * f0, d0
        elif m and m.group(1):
            f, d = float(m.group(1)), ZERO
        else:
            if tok in TEMPERATURE_SCALES or tok in DELISLE:
                raise UnitError(f"'{tok}' is a temperature scale with an offset; inside compound units use "
                                f"delta_degC, delta_degF or K")
            f, d = lookup(tok)
        factor *= f ** (sign * power)
        dim = _dim_add(dim, d, sign * power)
        i += 1
    return factor, dim


def describe_dim(dim):
    parts = []
    for b, p in zip(BASES, dim):
        if abs(p) > 1e-9:
            parts.append(b if p == 1 else f"{b}^{p:g}")
    return " ".join(parts) or "dimensionless"


def _to_kelvin(value, unit):
    if unit in DELISLE:
        return 373.15 - value * 2 / 3
    add, mul = TEMPERATURE_SCALES[unit]
    return (value + add) * mul


def _from_kelvin(k, unit):
    if unit in DELISLE:
        return (373.15 - k) * 3 / 2
    add, mul = TEMPERATURE_SCALES[unit]
    return k / mul - add


def convert(value, frm, to):
    """Convert value from one unit to another. Returns the number (raises UnitError when impossible)."""
    value = float(value)
    frm, to = str(frm).strip(), str(to).strip()
    is_temp = lambda u: u in TEMPERATURE_SCALES or u in DELISLE  # noqa: E731
    if is_temp(frm) or is_temp(to):
        k = _to_kelvin(value, frm) if is_temp(frm) else value * parse(frm)[0] if parse(frm)[1] == UNITS["K"][1] else None
        if k is None:
            raise UnitError(f"can't convert {frm} to a temperature")
        if is_temp(to):
            return _from_kelvin(k, to)
        f, d = parse(to)
        if d != UNITS["K"][1]:
            raise UnitError(f"{to} isn't a temperature unit")
        return k / f
    f1, d1 = parse(frm)
    f2, d2 = parse(to)
    if all(abs(a - b) < 1e-9 for a, b in zip(d1, d2)):
        return value * f1 / f2
    if all(abs(a + b) < 1e-9 for a, b in zip(d1, d2)):   # reciprocal units, e.g. mpg <-> L/100km
        if value == 0:
            raise UnitError("can't convert zero between reciprocal units")
        return 1 / (value * f1) / f2
    hint = ""
    ia = BASES.index("rad")
    if all(abs(a - b) < 1e-9 for i, (a, b) in enumerate(zip(d1, d2)) if i != ia):
        hint = " (they differ only by an angle: rpm and Hz count cycles - multiply by 2*pi rad per cycle for rad/s)"
    raise UnitError(f"can't convert {frm} ({describe_dim(d1)}) to {to} ({describe_dim(d2)}): "
                    f"they measure different things{hint}")


def fmt(x):
    if x == 0:
        return "0"
    if abs(x) >= 1e15 or abs(x) < 1e-6:
        return f"{x:.10g}"
    return f"{x:.10g}"


def explain(value, frm, to):
    """'5 mi = 8.04672 km' (string), for the calculator."""
    return f"{fmt(float(value))} {frm} = {fmt(convert(value, frm, to))} {to}"


def categories():
    return sorted(set(CATEGORY.values()))


def list_units(category=None):
    rows = {}
    for name, cat in CATEGORY.items():
        if category and category.lower() not in cat.lower():
            continue
        canon = CANONICAL[name]
        rows.setdefault((cat, canon), []).append(name)
    out = []
    for (cat, canon), names in sorted(rows.items()):
        f, d = UNITS[canon]
        si = describe_dim(d)
        out.append(f"{cat:<22} {', '.join(names):<46} = {fmt(f)} {si}")
    if not category or "temperature" in category.lower():
        out.append(f"{'temperature scale':<22} degC, degF, degR, degRe, degRo, degN, degDe (and °C, °F, celsius, "
                   f"fahrenheit, rankine, reaumur, romer, delisle)")
    return out


def count():
    return len(UNITS) + len(TEMPERATURE_SCALES) + len(DELISLE)


_build()

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        print("\n".join(list_units(a[1] if len(a) > 1 else None)))
        print(f"\n{count()} unit names, plus every SI and binary prefix")
    else:
        try:
            print(explain(float(a[0]), a[1], a[-1]))
        except UnitError as e:
            print(f"error: {e}")
