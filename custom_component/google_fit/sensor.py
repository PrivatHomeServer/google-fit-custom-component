
import os

import datetime
import enum
import httplib2
import logging
import voluptuous

from googleapiclient import discovery as google_discovery

from homeassistant import const
from homeassistant import util
from homeassistant.components import sensor
from homeassistant.helpers import entity
from homeassistant.helpers import config_validation
from homeassistant.helpers.event import track_time_change

from oauth2client import client as oauth2client
from oauth2client import file as oauth2file

REQUIREMENTS = [
    'google-api-python-client==1.6.4',
    'oauth2client==4.0.0',
]

_LOGGER = logging.getLogger(__name__)

# Sensor details.
SENSOR = 'google_fit'

# Sensor base attributes.
ATTR_LAST_UPDATED = 'last_updated'
CONF_CLIENT_ID = 'client_id'
CONF_CLIENT_SECRET = 'client_secret'
DEFAULT_NAME = 'google_fit'
DEFAULT_CREDENTIALS_FILE = '.google_fit.credentials.json'
ICON = 'mdi:heart-pulse'
MIN_TIME_BETWEEN_SCANS = datetime.timedelta(minutes=15)
MIN_TIME_BETWEEN_FORCED_SCANS = datetime.timedelta(hours=60)
TOKEN_FILE = '.{}.token'.format(SENSOR)

# # Define schema of sensor.
PLATFORM_SCHEMA = config_validation.PLATFORM_SCHEMA.extend({
    voluptuous.Required(CONF_CLIENT_ID): config_validation.string,
    voluptuous.Required(CONF_CLIENT_SECRET): config_validation.string,

    voluptuous.Optional(
      const.CONF_NAME,
      default=DEFAULT_NAME
    ): config_validation.string,

    voluptuous.Optional(
      const.ATTR_UNIT_OF_MEASUREMENT,
      default=const.MASS_KILOGRAMS
    ): config_validation.string,
})

# Define base notifications.
NOTIFICATION_ID = 'google_fit_notification'
NOTIFICATION_TITLE = 'Google Fit Setup'

# Google Fit API URL.
API_VERSION = 'v1'
API_USER_ID = 'me'

# Endpoint scopes required for the sensor.
# Read more: https://developers.google.com/fit/rest/v1/authorization
API_SCOPE = 'https://www.googleapis.com/auth/fitness.body.read'


def setup(hass, config):
  """Set up the Google Fit platform."""
  token_file = hass.config.path(TOKEN_FILE)
  if not os.path.isfile(token_file):
    return do_authentication(hass, config)

  return True


def do_authentication(hass, config):
  """Notify user of actions and authenticate.

  Notify user of user_code and verification_url then poll until we have an
  access token.
  """
  oauth = oauth2client.OAuth2WebServerFlow(
      client_id=config[CONF_CLIENT_ID],
      client_secret=config[CONF_CLIENT_SECRET],
      scope=API_SCOPE,
      redirect_uri='Home-Assistant.io',
  )

  try:
    dev_flow = oauth.step1_get_device_and_user_codes()
  except oauth2client.OAuth2DeviceCodeError as err:
    hass.components.persistent_notification.create(
        'Error: {}<br />You will need to restart hass after fixing.'
        ''.format(err),
        title=NOTIFICATION_TITLE,
        notification_id=NOTIFICATION_ID)
    return False

  hass.components.persistent_notification.create(
      'In order to authorize Home-Assistant to view your Google Fit data '
      'you must visit: <a href="{}" target="_blank">{}</a> and enter '
      'code: {}'.format(dev_flow.verification_url,
                        dev_flow.verification_url,
                        dev_flow.user_code),
      title=NOTIFICATION_TITLE, notification_id=NOTIFICATION_ID
  )

  def step2_exchange(now):
    """Keep trying to validate the user_code until it expires."""
    if now >= util.dt.as_local(dev_flow.user_code_expiry):
      hass.components.persistent_notification.create(
          'Authentication code expired, please restart '
          'Home-Assistant and try again',
          title=NOTIFICATION_TITLE,
          notification_id=NOTIFICATION_ID)
      listener()

    try:
      credentials = oauth.step2_exchange(device_flow_info=dev_flow)
    except oauth2client.FlowExchangeError:
      # not ready yet, call again
      return

    storage = oauth2file.Storage(hass.config.path(TOKEN_FILE))
    storage.put(credentials)
    listener()

  listener = track_time_change(hass, step2_exchange,
                               second=range(0, 60, dev_flow.interval))
  return True


def setup_platform(hass, config, add_devices, discovery_info=None):
  """Adds sensor platform to the list of platforms."""
  setup(hass, config)

  token_file = hass.config.path(TOKEN_FILE)
  name = config.get(const.CONF_NAME)
  unit_of_measurement = config.get(const.ATTR_UNIT_OF_MEASUREMENT)

  add_devices([GoogleFitSensor(token_file, name, unit_of_measurement)], True)


class GoogleFitSensor(entity.Entity):
  """Representation of a Google Fit Sensor.

  Currently supported: Weight and Last Update for Weight.
  However, the sensor it is designed to be extensible for other measures.
  """

  def __init__(self, token_file, name, unit_of_measurement):
    """Initializes the sensor.

    token_file: str, File path for API token.
    name: str, Name of the sensor.
    unit_of_measurement: str, Unit of measurement of sensor.
    """
    # Authenticate to application.
    self._client = self._get_client(token_file)

    # Device name.
    self._name = name

    # State: Weight and last updated.
    self._state = const.STATE_UNKNOWN
    self._unit_of_measurement = unit_of_measurement or const.MASS_KILOGRAMS
    self._last_updated = const.STATE_UNKNOWN

  def _get_client(self, token_file):
    """Get the Google Fit service with the storage file token.

    Args:
      token_file: str, File path for API token.

    Return:
      Google Fit API client.
    """
    if not os.path.isfile(token_file):
      return

    credentials = oauth2file.Storage(token_file).get()
    http = credentials.authorize(httplib2.Http())
    service = google_discovery.build(
      'fitness', 'v1', http=http, cache_discovery=False)
    return service

  @property
  def name(self):
    """Returns the name of the sensor."""
    return self._name

  @property
  def state(self):
    """Returns the state of the sensor. Currently: weight."""
    return self._state

  @property
  def unit_of_measurement(self):
    """Returns the unit of measurement."""
    return self._unit_of_measurement

  @property
  def last_updated(self):
    """Returns date when it was last updated."""
    return self._last_updated

  @property
  def state_attributes(self):
    """Returns the state attributes. """
    return {
        const.ATTR_FRIENDLY_NAME: self._name,
        const.ATTR_UNIT_OF_MEASUREMENT: self._unit_of_measurement,
        ATTR_LAST_UPDATED: self._last_updated,
    }

  @util.Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
  def update(self):
    """Fetches new state data for the sensor.

    This is the only method that should fetch new data for Home Assistant.
    """
    if not self._client:
      return

    self._update_weight_data()

  def _get_datasources(self, data_type_name):
    """Gets data sources information for weight data.

    Args:
      data_type_name: str, Type of data sources to retrieve.

    Returns:
      Dictionary containing all available data sources.
    """
    datasources_request = self._client.users().dataSources().list(
      userId='me',
      dataTypeName=data_type_name,
    )
    data = datasources_request.execute()
    return data.get('dataSource')

  def _update_weight_data(self):
    """Extracts the relevant data points for the sensor from the Fitness API."""
    weight_datasources = self._get_datasources('com.google.weight')

    weight_datapoints = {}
    for datasource in weight_datasources:
      datasource_id = datasource.get('dataStreamId')
      weight_request = self._client.users().dataSources().dataPointChanges().list(
        userId='me',
        dataSourceId=datasource_id,
      )
      weight_data = weight_request.execute()
      weight_inserted_datapoints = weight_data.get('insertedDataPoint')

      for datapoint in weight_inserted_datapoints:
        point_value = datapoint.get('value')
        if not point_value:
          continue
        weight = point_value[0].get('fpVal')
        if not weight:
          continue
        weight = round(weight, 2)
        last_update_milis = int(datapoint.get('modifiedTimeMillis', 0))
        if not last_update_milis:
          continue
        weight_datapoints[last_update_milis] = weight

    if weight_datapoints:
      time_updates = list(weight_datapoints.keys())
      time_updates.sort(reverse=True)

      last_time_update = time_updates[0]
      last_weight = weight_datapoints[last_time_update]

      self._last_updated = round(last_time_update / 1000)
      self._state = last_weight
