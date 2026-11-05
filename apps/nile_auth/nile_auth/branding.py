"""Spec 0012: the brand constants and pure helpers. No Frappe import, so the tools tests can use it.

The hex values carry the names of brand/tokens.css. The certificate CSS is written by hand for an old
WebKit (no variables), so the contrast test reads the same values from here.
"""

PRINT_FORMAT_NAME = "Nile Certificate"
APP_NAME = "Nile Learning"

# Public files of the app, served at /assets/nile_auth/... (the image links sites/assets/nile_auth).
ASSET_BASE = "/assets/nile_auth"
LOGO_FILE = "nile-logo.png"
ICON_FILE = "icon.png"
LOGO_URL = f"{ASSET_BASE}/images/{LOGO_FILE}"
ICON_URL = f"{ASSET_BASE}/images/{ICON_FILE}"
STYLESHEET_URL = f"{ASSET_BASE}/css/nile-brand.css"
# The images folder is filled by the image build, byte for byte from brand/.
IMAGE_FILES = (LOGO_FILE, ICON_FILE)

# Set true by build task 8 only when the live probe shows the LMS page can take the stylesheet.
STYLESHEET_BUILT = False

# Brand tokens (brand/tokens.css).
NILE_BLUE = "#0E4EAF"
BRIGHT_NILE_BLUE = "#2070E1"
DEEP_NILE_BLUE = "#072F68"
SOLAR_AMBER = "#FF6600"
NILE_INK = "#001E2D"
NILE_SLATE = "#4D626C"
WHITE = "#FFFFFF"
LIGHT_BACKGROUND = "#F6F8FB"
RING = "#EEF2F8"

# Every pair that carries text on the certificate and in nile-brand.css: (name, text, background).
# Amber, Teal, Violet, the gradient and the ring are decoration only and never carry text.
TEXT_PAIRS = (
	("ink on white", NILE_INK, WHITE),
	("slate on white", NILE_SLATE, WHITE),
	("nile blue on white", NILE_BLUE, WHITE),
	("white on nile blue", WHITE, NILE_BLUE),
	("ink on light background", NILE_INK, LIGHT_BACKGROUND),
	("slate on light background", NILE_SLATE, LIGHT_BACKGROUND),
	("nile blue on light background", NILE_BLUE, LIGHT_BACKGROUND),
)
MIN_CONTRAST = 4.5

__all__ = [
	"APP_NAME",
	"ASSET_BASE",
	"ICON_FILE",
	"ICON_URL",
	"IMAGE_FILES",
	"LOGO_FILE",
	"LOGO_URL",
	"MIN_CONTRAST",
	"PRINT_FORMAT_NAME",
	"STYLESHEET_BUILT",
	"STYLESHEET_URL",
	"TEXT_PAIRS",
	"contrast_ratio",
]


def _channel(value: int) -> float:
	c = value / 255
	return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
	h = hex_color.lstrip("#")
	r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
	return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
	"""Return the WCAG contrast ratio of two hex colors (1 to 21)."""
	a, b = _luminance(foreground), _luminance(background)
	lighter, darker = max(a, b), min(a, b)
	return (lighter + 0.05) / (darker + 0.05)
