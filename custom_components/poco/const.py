DOMAIN = "poco"
DEFAULT_HOST = "poco.local"

HTTP_PATH = "/v3/extsw"
WS_PATH = "/websocket/ws.cgi"

HTTP_TIMEOUT = 10           # seconds for HTTP requests and WS initial connect
SCAN_INTERVAL_HTTP = 30     # seconds between polls when WS is unavailable
SCAN_INTERVAL_WS = 60       # seconds between fallback polls when WS maintains state
WS_RECONNECT_INTERVAL = 30  # maximum backoff (seconds) between WS reconnect attempts

# Poco action IDs (API spec v3.4.0)
ACT_QUERY  = 0
ACT_OFF    = 1
ACT_ON     = 2
ACT_DIM_DN = 3
ACT_DIM_UP = 4
ACT_T2BD   = 5
ACT_PSTART = 6
ACT_PPAUSE = 7
ACT_T2HSB  = 8   # set hue + saturation + brightness
ACT_T2HS   = 9   # set hue + saturation, keep brightness
ACT_T2B    = 10  # set brightness, keep hue + saturation
