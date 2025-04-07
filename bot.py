import argparse
import re

import LXMF
import mgrs
import requests
from lxmfy import EventPriority, LXMFBot
from lxmfy.events import Event
from lxmfy.attachments import Attachment, AttachmentType

LAT_LON_REGEX = re.compile(r"^\s*(-?\d{1,3}(\.\d+)?)\s*,\s*(-?\d{1,3}(\.\d+)?)\s*$")
MGRS_REGEX = re.compile(r"^\s*\d{1,2}[C-X][A-Z]{2}\d{2,10}\s*$", re.IGNORECASE)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
GOES_CONUS_URL = "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/CONUS/GEOCOLOR/latest.jpg"

CONUS_LAT_MIN, CONUS_LAT_MAX = 24.0, 53.0
CONUS_LON_MIN, CONUS_LON_MAX = -125.0, -67.0

class WeatherBot:
    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
        self.bot = LXMFBot(
            name="Weather Bot",
            command_prefix="",
            storage_type="json",
            storage_path="data/weather",
            announce=600,
            announce_immediately=False,
            first_message_enabled=True
        )
        self.setup_events()
        self.m = mgrs.MGRS()

    def setup_events(self):
        @self.bot.events.on("message_received", priority=EventPriority.HIGH)
        def handle_location_message(event: Event):
            try:
                sender = event.data['sender']
                message = event.data['message']
                content = message.content.decode('utf-8').strip()

                if content.lower() == 'help':
                    help_text = (
                        "Send a location in one of these formats:\n"
                        "- City name (e.g., London)\n"
                        "- Latitude,Longitude (e.g., 40.71,-74.01)\n"
                        "- MGRS coordinates (e.g., 18TWL123456)\n"
                        "I'll respond with current weather conditions (metric and imperial units)."
                        "\nIf the location is in the US, I'll also send the latest GOES satellite image."
                    )
                    self.bot.send(sender, help_text)
                    return

                lat, lon, location_name = self.parse_location(content)

                if lat is not None and lon is not None:
                    weather_info = self.get_weather(lat, lon, location_name=location_name)
                    if weather_info:
                        image_content = None
                        if self.debug_mode:
                            print(f"[DEBUG] Checking if location ({lat:.2f}, {lon:.2f}) is in CONUS...")
                        if self.is_in_conus(lat, lon):
                            if self.debug_mode:
                                print("[DEBUG] Location IS in CONUS. Attempting to fetch GOES image...")
                            image_data = self.fetch_goes_conus_image()
                            attachment_obj = None
                            if image_data:
                                if self.debug_mode:
                                    print(f"[DEBUG] GOES image fetched successfully ({len(image_data)} bytes). Preparing attachment object...")
                                try:
                                    attachment_obj = Attachment(
                                        type=AttachmentType.IMAGE,
                                        name="goes_conus_latest.jpg",
                                        data=image_data,
                                        format="jpg"
                                    )
                                    if self.debug_mode:
                                        print("[DEBUG] Attachment object prepared successfully.")
                                except Exception as pack_e:
                                    if self.debug_mode:
                                        print(f"[DEBUG] Error creating Attachment object: {pack_e}")
                                    attachment_obj = None
                            else:
                                if self.debug_mode:
                                    print("[DEBUG] GOES image fetch failed (image_data is None).")
                                attachment_obj = None
                        else:
                            if self.debug_mode:
                                print("[DEBUG] Location is NOT in CONUS. Skipping image fetch.")
                            attachment_obj = None

                        if self.debug_mode:
                            print(f"[DEBUG] Preparing to send message. Attachment object present: {attachment_obj is not None}")
                        if attachment_obj:
                            self.bot.send_with_attachment(
                                destination=sender,
                                message=weather_info,
                                attachment=attachment_obj,
                                title="Weather Update w/ Image"
                            )
                        else:
                            self.bot.send(sender, weather_info)
                    else:
                        self.bot.send(sender, "Sorry, I couldn't fetch the weather for that location.")
                else:
                    self.bot.send(sender, "I couldn't understand that location. Type 'help' for format examples.")

            except Exception as e:
                print(f"Error processing message: {e}")

    def parse_location(self, location_str: str) -> tuple[float | None, float | None, str | None]:
        """Parse input string to determine lat/lon and original name if applicable."""
        loc_str_stripped = location_str.strip()

        lat_lon_match = LAT_LON_REGEX.match(loc_str_stripped)
        if lat_lon_match:
            try:
                lat = float(lat_lon_match.group(1))
                lon = float(lat_lon_match.group(3))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    if self.debug_mode:
                        print(f"Parsed as Lat/Lon: {lat}, {lon}")
                    return lat, lon, None
            except ValueError:
                pass

        if MGRS_REGEX.match(loc_str_stripped):
            try:
                lat, lon = self.m.toLatLon(loc_str_stripped.encode('utf-8'))
                if self.debug_mode:
                    print(f"Parsed MGRS {loc_str_stripped} to Lat/Lon: {lat}, {lon}")
                return lat, lon, None
            except Exception as e:
                if self.debug_mode:
                    print(f"MGRS conversion error for '{loc_str_stripped}': {e}")

        lat, lon, city_name = self.geocode_city(location_str)
        if lat is not None:
            return lat, lon, city_name
        else:
            if self.debug_mode:
                 print(f"Could not parse or geocode '{location_str}'")
            return None, None, None

    def geocode_city(self, city_name: str) -> tuple[float | None, float | None, str | None]:
        """Geocode city name and return lat, lon, and formatted name."""
        try:
            params = {
                "name": city_name,
                "count": 1,
                "language": "en",
                "format": "json"
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

                if self.debug_mode:
                    print(f"Geocoded '{city_name}' to '{display_name}' at Lat/Lon: {lat}, {lon}")
                return lat, lon, display_name
            else:
                if self.debug_mode:
                    print(f"No geocoding results found for '{city_name}'")
                return None, None, None

        except Exception as e:
            if self.debug_mode:
                 print(f"Geocoding error for '{city_name}': {e}")
            return None, None, None

    def get_weather(self, lat: float, lon: float, location_name: str | None = None) -> str | None:
        """Fetch weather data from Open-Meteo and display in metric and imperial."""

        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "temperature_unit": "celsius",
            "windspeed_unit": "kmh",
            "precipitation_unit": "mm"
        }
        try:
            response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if "current_weather" in data:
                cw = data["current_weather"]
                temp_c = cw.get("temperature")
                wind_kmh = cw.get("windspeed")
                winddir = cw.get("winddirection", "N/A")
                code = cw.get("weathercode", None)
                is_day = cw.get("is_day", 1)

                weather_desc = self.interpret_weather_code(code, is_day)

                temp_f_str = "N/A"
                if isinstance(temp_c, int | float):
                    temp_f = (temp_c * 9/5) + 32
                    temp_f_str = f"{temp_f:.1f}°F"
                temp_c_str = f"{temp_c}°C" if temp_c is not None else "N/A"

                wind_mph_str = "N/A"
                if isinstance(wind_kmh, int | float):
                    wind_mph = wind_kmh * 0.621371
                    wind_mph_str = f"{wind_mph:.1f} mph"
                wind_kmh_str = f"{wind_kmh} kmh" if wind_kmh is not None else "N/A"

                if location_name:
                    header = f"Weather for {location_name}:\n"
                else:
                    header = f"Weather for {lat:.2f}, {lon:.2f}:\n"

                return (f"{header}"
                        f"- Temp: {temp_c_str} ({temp_f_str})\n"
                        f"- Wind: {wind_kmh_str} ({wind_mph_str}) from {winddir}°\n"
                        f"- Condition: {weather_desc}")
            else:
                return "Could not retrieve current weather data."

        except requests.exceptions.RequestException as e:
            print(f"Error fetching weather from Open-Meteo: {e}")
            return None
        except Exception as e:
            print(f"Error processing weather data: {e}")
            return None

    def is_in_conus(self, lat: float, lon: float) -> bool:
        """Check if latitude and longitude fall within approximate CONUS bounds."""
        return CONUS_LAT_MIN <= lat <= CONUS_LAT_MAX and CONUS_LON_MIN <= lon <= CONUS_LON_MAX

    def fetch_goes_conus_image(self) -> bytes | None:
        """Fetch the latest GOES CONUS geocolor image."""
        try:
            response = requests.get(GOES_CONUS_URL, timeout=20)
            response.raise_for_status()
            if 'image/jpeg' in response.headers.get('Content-Type', '').lower():
                if self.debug_mode:
                    print(f"[DEBUG] Successfully downloaded GOES image from {GOES_CONUS_URL}")
                return response.content
            else:
                if self.debug_mode:
                    print(f"[DEBUG] Downloaded content from {GOES_CONUS_URL} is not JPEG image. Content-Type: {response.headers.get('Content-Type')}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching GOES image: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error fetching GOES image: {e}")
            return None

    def interpret_weather_code(self, code: int | None, is_day: int = 1) -> str:
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

    def run(self):
        print("Starting Weather Bot...")
        self.bot.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run the LXMF Weather Bot.')
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable detailed logging for location parsing and geocoding.'
    )
    args = parser.parse_args()

    weather_bot = WeatherBot(debug_mode=args.debug)
    weather_bot.run()
