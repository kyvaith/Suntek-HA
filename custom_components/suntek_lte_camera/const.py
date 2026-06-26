"""Constants for the Suntek LTE Camera integration."""

DOMAIN = "suntek_lte_camera"

DEFAULT_NAME = "Suntek LTE Camera"
DEFAULT_SERVER_ADDR = "https://depro.car-dv.com/4gcardv"
DEFAULT_WAKE_COMMAND = 999
DEFAULT_WAKE_COOLDOWN = 60
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_MEDIA_BACKUP_INTERVAL = 360
DEFAULT_MEDIA_BACKUP_LIMIT = 100

CONF_DEVICE_ID = "device_id"
CONF_CLOUD_DEVICE_ID = "cloud_device_id"
CONF_LOGIN = "login"
CONF_NAME = "name"
CONF_PASSWORD = "password"
CONF_SERVER_ADDR = "server_addr"
CONF_STREAM_URL_TEMPLATE = "stream_url_template"
CONF_STILL_IMAGE_URL_TEMPLATE = "still_image_url_template"
CONF_WAKE_BEFORE_STREAM = "wake_before_stream"
CONF_WAKE_COOLDOWN = "wake_cooldown"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MEDIA_BACKUP_ENABLED = "media_backup_enabled"
CONF_MEDIA_BACKUP_INTERVAL = "media_backup_interval"
CONF_MEDIA_BACKUP_LIMIT = "media_backup_limit"
CONF_MEDIA_BACKUP_INCLUDE_VIDEOS = "media_backup_include_videos"

ATTR_CONTENT = "content"
ATTR_ENTRY_ID = "entry_id"
ATTR_INCLUDE_IMAGES = "include_images"
ATTR_INCLUDE_VIDEOS = "include_videos"
ATTR_LIMIT = "limit"

SERVICE_REFRESH = "refresh"
SERVICE_SYNC_CLOUD_MEDIA = "sync_cloud_media"
SERVICE_WAKEUP = "wakeup"

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
