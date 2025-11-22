"""Weather bot module."""

import argparse
import re

import mgrs
import requests
from lxmfy import LXMFBot
from lxmfy.attachments import Attachment, AttachmentType

LAT_LON_REGEX = re.compile(r"^\s*(-?\d{1,3}(\.\d+)?)\s*,\s*(-?\d{1,3}(\.\d+)?)\s*$")
MGRS_REGEX = re.compile(r"^\s*\d{1,2}[C-X][A-Z]{2}\d{2,10}\s*$", re.IGNORECASE)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
GOES_CONUS_URL = "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/CONUS/GEOCOLOR/latest.jpg"

CONUS_LAT_MIN, CONUS_LAT_MAX = 24.0, 53.0
CONUS_LON_MIN, CONUS_LON_MAX = -125.0, -67.0

DEBUG_MODE = False
MGRS_CONVERTER = mgrs.MGRS()


def parse_command(content: str) -> tuple[str, str]:
    """Parse command and location from user input.

    Returns:
        Tuple of (command, location_string)

    """
    content_lower = content.lower().strip()
    commands = ["current", "hourly", "forecast", "detailed", "air"]

    for cmd in commands:
        if content_lower.startswith(cmd + " "):
            location = content[len(cmd) :].strip()
            return cmd, location

    return "default", content


def parse_location(
    location_str: str,
) -> tuple[float | None, float | None, str | None]:
    """Parse input string to determine lat/lon and original name if applicable."""
    loc_str_stripped = location_str.strip()

    lat_lon_match = LAT_LON_REGEX.match(loc_str_stripped)
    if lat_lon_match:
        try:
            lat = float(lat_lon_match.group(1))
            lon = float(lat_lon_match.group(3))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                if DEBUG_MODE:
                    print(f"Parsed as Lat/Lon: {lat}, {lon}")
                return lat, lon, None
        except ValueError:
            pass

    if MGRS_REGEX.match(loc_str_stripped):
        try:
            lat, lon = MGRS_CONVERTER.toLatLon(loc_str_stripped.encode("utf-8"))
            if DEBUG_MODE:
                print(f"Parsed MGRS {loc_str_stripped} to Lat/Lon: {lat}, {lon}")
            return lat, lon, None
        except Exception as e:
            if DEBUG_MODE:
                print(f"MGRS conversion error for '{loc_str_stripped}': {e}")

    lat, lon, city_name = geocode_city(location_str)
    if lat is not None:
        return lat, lon, city_name
    if DEBUG_MODE:
        print(f"Could not parse or geocode '{location_str}'")
    return None, None, None


def geocode_city(
    city_name: str,
) -> tuple[float | None, float | None, str | None]:
    """Geocode city name and return lat, lon, and formatted name."""
    try:
        params = {
            "name": city_name,
            "count": 1,
            "language": "en",
            "format": "json",
        }
        response = requests.get(GEOCODING_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            lat = result["latitude"]
            lon = result["longitude"]
            found_name = result.get("name", city_name)
            admin1 = result.get("admin1")
            country = result.get("country")
            display_name = found_name
            if admin1 and admin1 != found_name:
                display_name += f", {admin1}"
            if country:
                display_name += f", {country}"

            if DEBUG_MODE:
                print(
                    f"Geocoded '{city_name}' to '{display_name}' at Lat/Lon: {lat}, {lon}",
                )
            return lat, lon, display_name
        if DEBUG_MODE:
            print(f"No geocoding results found for '{city_name}'")
        return None, None, None

    except Exception as e:
        if DEBUG_MODE:
            print(f"Geocoding error for '{city_name}': {e}")
        return None, None, None


def get_detailed_current(
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> str | None:
    """Fetch detailed current weather with all available parameters."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weather_code",
            "cloud_cover",
            "pressure_msl",
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "uv_index",
        ],
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "current" not in data:
            return "Could not retrieve current weather data."

        curr = data["current"]

        header = (
            f"Weather for {location_name}:\n"
            if location_name
            else f"Weather for {lat:.2f}, {lon:.2f}:\n"
        )

        temp_c = curr.get("temperature_2m")
        feels_c = curr.get("apparent_temperature")
        humidity = curr.get("relative_humidity_2m")
        precip = curr.get("precipitation")
        cloud = curr.get("cloud_cover")
        pressure = curr.get("pressure_msl")
        wind_kmh = curr.get("wind_speed_10m")
        wind_gust = curr.get("wind_gusts_10m")
        winddir = curr.get("wind_direction_10m")
        code = curr.get("weather_code")
        uv_index = curr.get("uv_index")

        weather_desc = interpret_weather_code(code, 1)

        temp_f = (temp_c * 9 / 5) + 32 if temp_c is not None else None
        feels_f = (feels_c * 9 / 5) + 32 if feels_c is not None else None
        wind_mph = wind_kmh * 0.621371 if wind_kmh is not None else None
        wind_gust_mph = wind_gust * 0.621371 if wind_gust is not None else None

        output = [header]
        output.append(f"Condition: {weather_desc}\n")

        if temp_c is not None:
            output.append(f"Temperature: {temp_c:.1f}°C ({temp_f:.1f}°F)")
        if feels_c is not None:
            output.append(f"Feels like: {feels_c:.1f}°C ({feels_f:.1f}°F)")
        if humidity is not None:
            output.append(f"Humidity: {humidity}%")
        if wind_kmh is not None:
            wind_str = f"Wind: {wind_kmh:.1f} km/h ({wind_mph:.1f} mph)"
            if winddir is not None:
                wind_str += f" from {winddir}°"
            output.append(wind_str)
        if wind_gust is not None:
            output.append(f"Gusts: {wind_gust:.1f} km/h ({wind_gust_mph:.1f} mph)")
        if cloud is not None:
            output.append(f"Cloud cover: {cloud}%")
        if precip is not None and precip > 0:
            output.append(f"Precipitation: {precip} mm")
        if pressure is not None:
            output.append(f"Pressure: {pressure:.1f} hPa")
        if uv_index is not None:
            uv_category = interpret_uv_index(uv_index)
            output.append(f"UV Index: {uv_index:.1f} ({uv_category})")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching detailed weather: {e}")
        return None
    except Exception as e:
        print(f"Error processing detailed weather: {e}")
        return None


def get_hourly_forecast(
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> str | None:
    """Fetch 12-hour forecast."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "uv_index",
        ],
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "forecast_days": 2,
        "timezone": "auto",
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "hourly" not in data:
            return "Could not retrieve hourly forecast."

        hourly = data["hourly"]
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        precip_prob = hourly.get("precipitation_probability", [])
        precip = hourly.get("precipitation", [])
        codes = hourly.get("weather_code", [])
        winds = hourly.get("wind_speed_10m", [])
        uv_indices = hourly.get("uv_index", [])

        header = (
            f"12-Hour Forecast for {location_name}:\n"
            if location_name
            else f"12-Hour Forecast for {lat:.2f}, {lon:.2f}:\n"
        )
        output = [header]

        for i in range(min(12, len(times))):
            time_str = times[i]
            if "T" in time_str:
                date_part, time_part = time_str.split("T")
                time_display = f"{date_part} {time_part}"
            else:
                time_display = time_str

            temp_c = temps[i] if i < len(temps) else None
            temp_f = (temp_c * 9 / 5) + 32 if temp_c is not None else None
            prob = precip_prob[i] if i < len(precip_prob) else None
            prec = precip[i] if i < len(precip) else None
            code = codes[i] if i < len(codes) else None
            wind = winds[i] if i < len(winds) else None
            uv = uv_indices[i] if i < len(uv_indices) else None

            condition = interpret_weather_code(code, 1)

            line = (
                f"{time_display}:\n  {temp_c:.1f}°C ({temp_f:.1f}°F), {condition}"
            )
            if prob is not None and prob > 0:
                line += f"\n  Precip: {prob}%"
                if prec is not None and prec > 0:
                    line += f" ({prec:.1f} mm)"
            if wind is not None:
                wind_mph = wind * 0.621371
                line += f"\n  Wind: {wind:.0f} km/h ({wind_mph:.0f} mph)"
            if uv is not None and uv > 0:
                line += f"\n  UV: {uv:.1f}"

            output.append(line)

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching hourly forecast: {e}")
        return None
    except Exception as e:
        print(f"Error processing hourly forecast: {e}")
        return None


def get_daily_forecast(
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> str | None:
    """Fetch 7-day forecast."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "sunrise",
            "sunset",
            "uv_index_max",
        ],
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "forecast_days": 7,
        "timezone": "auto",
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "daily" not in data:
            return "Could not retrieve daily forecast."

        daily = data["daily"]
        times = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip_sum = daily.get("precipitation_sum", [])
        precip_prob = daily.get("precipitation_probability_max", [])
        wind_max = daily.get("wind_speed_10m_max", [])
        codes = daily.get("weather_code", [])
        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])
        uv_max = daily.get("uv_index_max", [])

        header = (
            f"7-Day Forecast for {location_name}:\n"
            if location_name
            else f"7-Day Forecast for {lat:.2f}, {lon:.2f}:\n"
        )
        output = [header]

        for i in range(min(7, len(times))):
            date_str = times[i]
            t_max_c = temp_max[i] if i < len(temp_max) else None
            t_min_c = temp_min[i] if i < len(temp_min) else None
            t_max_f = (t_max_c * 9 / 5) + 32 if t_max_c is not None else None
            t_min_f = (t_min_c * 9 / 5) + 32 if t_min_c is not None else None
            prec_sum = precip_sum[i] if i < len(precip_sum) else None
            prec_prob = precip_prob[i] if i < len(precip_prob) else None
            wind = wind_max[i] if i < len(wind_max) else None
            code = codes[i] if i < len(codes) else None
            sunrise = sunrises[i] if i < len(sunrises) else None
            sunset = sunsets[i] if i < len(sunsets) else None
            uv = uv_max[i] if i < len(uv_max) else None

            condition = interpret_weather_code(code, 1)

            line = f"{date_str}: {condition}"
            if t_max_c is not None and t_min_c is not None:
                line += f"\n  High: {t_max_c:.1f}°C ({t_max_f:.1f}°F), Low: {t_min_c:.1f}°C ({t_min_f:.1f}°F)"
            if sunrise and sunset:
                sunrise_time = sunrise.split("T")[1] if "T" in sunrise else sunrise
                sunset_time = sunset.split("T")[1] if "T" in sunset else sunset
                line += f"\n  Sun: {sunrise_time} - {sunset_time}"
            if uv is not None and uv > 0:
                uv_cat = interpret_uv_index(uv)
                line += f"\n  Max UV: {uv:.1f} ({uv_cat})"
            if prec_prob is not None and prec_prob > 0:
                line += f"\n  Precip: {prec_prob}%"
                if prec_sum is not None and prec_sum > 0:
                    line += f" ({prec_sum:.1f} mm)"
            if wind is not None:
                wind_mph = wind * 0.621371
                line += f"\n  Max wind: {wind:.0f} km/h ({wind_mph:.0f} mph)"

            output.append(line)

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching daily forecast: {e}")
        return None
    except Exception as e:
        print(f"Error processing daily forecast: {e}")
        return None


def get_air_quality(
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> str | None:
    """Fetch current air quality data."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "european_aqi",
            "us_aqi",
            "pm10",
            "pm2_5",
            "carbon_monoxide",
            "nitrogen_dioxide",
            "sulphur_dioxide",
            "ozone",
        ],
    }

    try:
        response = requests.get(AIR_QUALITY_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "current" not in data:
            return "Could not retrieve air quality data."

        curr = data["current"]

        header = (
            f"Air Quality for {location_name}:\n"
            if location_name
            else f"Air Quality for {lat:.2f}, {lon:.2f}:\n"
        )
        output = [header]

        us_aqi = curr.get("us_aqi")
        eu_aqi = curr.get("european_aqi")
        pm10 = curr.get("pm10")
        pm25 = curr.get("pm2_5")
        co = curr.get("carbon_monoxide")
        no2 = curr.get("nitrogen_dioxide")
        so2 = curr.get("sulphur_dioxide")
        o3 = curr.get("ozone")

        if us_aqi is not None:
            us_category = interpret_us_aqi(us_aqi)
            output.append(f"US AQI: {us_aqi} ({us_category})")

        if eu_aqi is not None:
            eu_category = interpret_eu_aqi(eu_aqi)
            output.append(f"European AQI: {eu_aqi} ({eu_category})")

        output.append("\nPollutants:")
        if pm25 is not None:
            output.append(f"  PM2.5: {pm25:.1f} μg/m³")
        if pm10 is not None:
            output.append(f"  PM10: {pm10:.1f} μg/m³")
        if no2 is not None:
            output.append(f"  NO₂: {no2:.1f} μg/m³")
        if so2 is not None:
            output.append(f"  SO₂: {so2:.1f} μg/m³")
        if o3 is not None:
            output.append(f"  O₃: {o3:.1f} μg/m³")
        if co is not None:
            output.append(f"  CO: {co:.0f} μg/m³")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching air quality: {e}")
        return None
    except Exception as e:
        print(f"Error processing air quality: {e}")
        return None


def interpret_uv_index(uv: float) -> str:
    """Interpret UV index value."""
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very High"
    return "Extreme"


def interpret_us_aqi(aqi: float) -> str:
    """Interpret US AQI value."""
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def interpret_eu_aqi(aqi: float) -> str:
    """Interpret European AQI value."""
    if aqi <= 20:
        return "Good"
    if aqi <= 40:
        return "Fair"
    if aqi <= 60:
        return "Moderate"
    if aqi <= 80:
        return "Poor"
    if aqi <= 100:
        return "Very Poor"
    return "Extremely Poor"


def get_comprehensive_weather(
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> str | None:
    """Get current weather, hourly, and daily forecast all together."""
    current = get_detailed_current(lat, lon, location_name)
    hourly = get_hourly_forecast(lat, lon, location_name)
    daily = get_daily_forecast(lat, lon, location_name)
    air = get_air_quality(lat, lon, location_name)

    parts = []
    if current:
        parts.append(current)
    if air:
        parts.append("\n" + "=" * 40 + "\n" + air)
    if hourly:
        parts.append("\n" + "=" * 40 + "\n" + hourly)
    if daily:
        parts.append("\n" + "=" * 40 + "\n" + daily)

    if parts:
        return "\n".join(parts)
    return None


def is_in_conus(lat: float, lon: float) -> bool:
    """Check if latitude and longitude fall within approximate CONUS bounds."""
    return (
        CONUS_LAT_MIN <= lat <= CONUS_LAT_MAX
        and CONUS_LON_MIN <= lon <= CONUS_LON_MAX
    )


def fetch_goes_conus_image() -> bytes | None:
    """Fetch the latest GOES CONUS geocolor image."""
    try:
        response = requests.get(GOES_CONUS_URL, timeout=20)
        response.raise_for_status()
        if "image/jpeg" in response.headers.get("Content-Type", "").lower():
            if DEBUG_MODE:
                print(
                    f"[DEBUG] Successfully downloaded GOES image from {GOES_CONUS_URL}",
                )
            return response.content
        if DEBUG_MODE:
            print(
                f"[DEBUG] Downloaded content from {GOES_CONUS_URL} is not JPEG image. Content-Type: {response.headers.get('Content-Type')}",
            )
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching GOES image: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching GOES image: {e}")
        return None


def interpret_weather_code(code: int | None, is_day: int = 1) -> str:
    """Provide a basic text description for WMO weather codes."""
    if code is None:
        return "Unknown"
    if code == 0:
        return "Clear sky"
    if code == 1:
        return "Mainly clear"
    if code == 2:
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code == 45:
        return "Fog"
    if code == 48:
        return "Depositing rime fog"
    if code in (51, 53, 55):
        return "Drizzle"
    if code in (56, 57):
        return "Freezing Drizzle"
    if code in (61, 63, 65):
        return "Rain"
    if code in (66, 67):
        return "Freezing Rain"
    if code in (71, 73, 75):
        return "Snow fall"
    if code == 77:
        return "Snow grains"
    if code in (80, 81, 82):
        return "Rain showers"
    if code in (85, 86):
        return "Snow showers"
    if code == 95:
        return "Thunderstorm"
    if code in (96, 99):
        return "Thunderstorm with hail"
    return f"Unknown code ({code})"


def process_weather_request(bot, destination, command: str, location_str: str, ctx=None):
    """Process weather request and send response.

    Args:
        bot: The LXMFBot instance.
        destination: The destination LXMF hash to send to.
        command: The weather command type.
        location_str: The location string to parse.
        ctx: Optional command context (if None, uses bot.send directly).

    """
    lat, lon, location_name = parse_location(location_str)

    if lat is None or lon is None:
        error_msg = "I couldn't understand that location. Type 'help' for format examples."
        if ctx:
            ctx.reply(error_msg)
        else:
            bot.send(destination, error_msg)
        return

    weather_info = None

    if command == "current":
        weather_info = get_detailed_current(lat, lon, location_name)
    elif command == "hourly":
        weather_info = get_hourly_forecast(lat, lon, location_name)
    elif command == "forecast":
        weather_info = get_daily_forecast(lat, lon, location_name)
    elif command == "air":
        weather_info = get_air_quality(lat, lon, location_name)
    elif command == "detailed":
        weather_info = get_comprehensive_weather(lat, lon, location_name)
    else:
        weather_info = get_detailed_current(lat, lon, location_name)

    if not weather_info:
        error_msg = "Sorry, I couldn't fetch the weather for that location."
        if ctx:
            ctx.reply(error_msg)
        else:
            bot.send(destination, error_msg)
        return

    attachment_obj = None
    if DEBUG_MODE:
        print(
            f"[DEBUG] Checking if location ({lat:.2f}, {lon:.2f}) is in CONUS...",
        )
    if is_in_conus(lat, lon):
        if DEBUG_MODE:
            print(
                "[DEBUG] Location IS in CONUS. Attempting to fetch GOES image...",
            )
        image_data = fetch_goes_conus_image()
        if image_data:
            if DEBUG_MODE:
                print(
                    f"[DEBUG] GOES image fetched successfully ({len(image_data)} bytes). Preparing attachment object...",
                )
            try:
                attachment_obj = Attachment(
                    type=AttachmentType.IMAGE,
                    name="goes_conus_latest.jpg",
                    data=image_data,
                    format="jpg",
                )
                if DEBUG_MODE:
                    print(
                        "[DEBUG] Attachment object prepared successfully.",
                    )
            except Exception as pack_e:
                if DEBUG_MODE:
                    print(
                        f"[DEBUG] Error creating Attachment object: {pack_e}",
                    )
                attachment_obj = None
        else:
            if DEBUG_MODE:
                print(
                    "[DEBUG] GOES image fetch failed (image_data is None).",
                )
            attachment_obj = None
    else:
        if DEBUG_MODE:
            print(
                "[DEBUG] Location is NOT in CONUS. Skipping image fetch.",
            )
        attachment_obj = None

    if DEBUG_MODE:
        print(
            f"[DEBUG] Preparing to send message. Attachment object present: {attachment_obj is not None}",
        )
    if attachment_obj:
        bot.send_with_attachment(
            destination=destination,
            message=weather_info,
            attachment=attachment_obj,
            title="Weather Update w/ Image",
        )
    else:
        if ctx:
            ctx.reply(weather_info)
        else:
            bot.send(destination, weather_info)


def main():
    """Main entry point for the weather bot."""
    parser = argparse.ArgumentParser(description="Run the LXMF Weather Bot.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed logging for location parsing and geocoding.",
    )
    parser.add_argument(
        "--config",
        "-c",
        metavar="PATH",
        dest="config_path",
        default=None,
        help="Path to Reticulum configuration directory.",
    )
    parser.add_argument(
        "--identity",
        "-i",
        metavar="PATH",
        dest="identity_path",
        default=None,
        help="Path to LXMF identity file.",
    )
    parser.add_argument(
        "--storage",
        "-s",
        metavar="PATH",
        dest="storage_path",
        default=None,
        help="Path to bot storage directory.",
    )
    args = parser.parse_args()

    global DEBUG_MODE
    DEBUG_MODE = args.debug

    bot_kwargs = {
        "name": "Weather Bot",
        "command_prefix": "",
        "storage_type": "json",
        "storage_path": args.storage_path or "data/weather",
        "announce": 6000,
        "announce_immediately": False,
        "first_message_enabled": True,
    }

    if args.config_path:
        bot_kwargs["config_path"] = args.config_path
    if args.identity_path:
        bot_kwargs["identity_path"] = args.identity_path

    bot = LXMFBot(**bot_kwargs)

    @bot.command(name="help", description="Show help information")
    def help_command(ctx):
        help_text = (
            "Weather Bot Commands:\n\n"
            "Basic usage: Send a location to get current weather\n"
            "- City name (e.g., London)\n"
            "- Latitude,Longitude (e.g., 40.71,-74.01)\n"
            "- MGRS coordinates (e.g., 18TWL123456)\n\n"
            "Advanced commands:\n"
            "- 'current <location>' - Detailed current weather\n"
            "- 'hourly <location>' - 12-hour forecast\n"
            "- 'forecast <location>' - 7-day forecast\n"
            "- 'air <location>' - Air quality index\n"
            "- 'detailed <location>' - Everything at once\n\n"
            "For US locations, I'll include a GOES satellite image!"
        )
        ctx.reply(help_text)

    @bot.command(name="current", description="Get detailed current weather for a location")
    def current_command(ctx):
        if not ctx.args:
            ctx.reply("Please provide a location. Example: current London")
            return
        location_str = " ".join(ctx.args)
        process_weather_request(bot, ctx.sender, "current", location_str, ctx=ctx)

    @bot.command(name="hourly", description="Get 12-hour forecast for a location")
    def hourly_command(ctx):
        if not ctx.args:
            ctx.reply("Please provide a location. Example: hourly London")
            return
        location_str = " ".join(ctx.args)
        process_weather_request(bot, ctx.sender, "hourly", location_str, ctx=ctx)

    @bot.command(name="forecast", description="Get 7-day forecast for a location")
    def forecast_command(ctx):
        if not ctx.args:
            ctx.reply("Please provide a location. Example: forecast London")
            return
        location_str = " ".join(ctx.args)
        process_weather_request(bot, ctx.sender, "forecast", location_str, ctx=ctx)

    @bot.command(name="air", description="Get air quality for a location")
    def air_command(ctx):
        if not ctx.args:
            ctx.reply("Please provide a location. Example: air London")
            return
        location_str = " ".join(ctx.args)
        process_weather_request(bot, ctx.sender, "air", location_str, ctx=ctx)

    @bot.command(name="detailed", description="Get comprehensive weather information for a location")
    def detailed_command(ctx):
        if not ctx.args:
            ctx.reply("Please provide a location. Example: detailed London")
            return
        location_str = " ".join(ctx.args)
        process_weather_request(bot, ctx.sender, "detailed", location_str, ctx=ctx)

    @bot.on_message()
    def handle_location_message(sender, message):
        content = message.content.decode("utf-8").strip()

        if content.lower() == "help":
            return False

        command, location_str = parse_command(content)
        process_weather_request(bot, sender, command, location_str)
        return False

    print(f"Starting bot: {bot.config.name}")
    print(f"Bot LXMF Address: <{bot.local.hash.hex()}>")
    bot.run()


if __name__ == "__main__":
    main()
