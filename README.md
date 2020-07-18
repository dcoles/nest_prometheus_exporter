# Prometheus Exporters

## Nest

Export metrics from Nest devices (e.g. Nest Thermostat)

### ⚠️ Important

This exporter uses the old ["Works with Nest" API](https://developers.nest.com/)
which has [now been sunset by Google](https://blog.google/products/google-nest/works-with-nest).

You can still use this exporter, but only if you have a pre-existing developer token.


## OpenWeather

Export metrics from [OpenWeather](https://openweathermap.org/).

Requires an [`appid`](https://openweathermap.org/appid) to be able to fetch metrics using the
[One Call API](https://openweathermap.org/api/one-call-api)

### Config

```json5
{
  // OpenWeather config (required)
  "openweather": {
    // OpenWeather appid (required)
    "appid": "xxx",
    // Locations to monitor (mapping of location name to lat/long)
    "locations": {
      "Melbourne, VIC": {
        "lat": -37.813611, "long": 144.963056
      }
    }
  }
}
```
