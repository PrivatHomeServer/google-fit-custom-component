# Google Fit - Custom Component for Home-Assisant
This project is a custom component for [Home-Assistant](https://www.home-assistant.io/). The component/platform creates sensor information that reads data from Google Fit.

## What Data Can Be Retrieved
While Google Fit supports multiple data points, the custom component only provides two measurements currently:
- weight: in KG.
- last_updated: entry when the last weight was entered on Google Fit.

## Contributing
The sensor is designed to be flexible and allow customization to add new Google Fit dimensions with minimal effort with relative knowledge of Python and Fitness Rest API. If you want to add content, feel free to send a feature request.

## Installation
Copy the contents of `custom_components/google_fit` on this repository onto `config/custom_components/google_fit/` on your Home-Assistant.

## Usage
Add the following configuration to your sensor on your `configuration.yaml`:
```yaml
sensor:
  - platform: google_fit
    client_id: your_client_id
    client_secret: your_client_secret
```

In order to generate your client_id and client_secret, [see the prerequisites](https://www.home-assistant.io/components/calendar.google/#prerequisites) for
Google components.

### Recommendation
It is recommendable to store keep client_id and client_secret as secret as
possible. You can read about it on [the Secrets page](https://www.home-assistant.io/docs/configuration/secrets/).

Example:
```yaml
  - platform: google_fit
    client_id: !secret google_fit_client_id
    client_secret: !secret google_fit_client_secret
```
